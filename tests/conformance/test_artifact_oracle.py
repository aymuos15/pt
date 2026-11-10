import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import artifact_oracle as oracle
from test_support import case_root


class ArtifactOracleTests(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        (self.root / "report").mkdir()
        self.raw = b"required report\x00\xff\n"
        (self.root / "report/result").write_bytes(self.raw)
        self.expected = [{"path": "report/result", "bytes": len(self.raw), "sha256": hashlib.sha256(self.raw).hexdigest()}]

    def test_checks_actual_binary_bytes_and_required_cleanup(self):
        report = oracle.check_artifacts(self.root, self.expected, absent=["lease", "not-created/deep"])
        self.assertEqual(report["status"], "matched_declared_artifact_bytes_and_absences")
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(report["files"], self.expected)

    def test_missing_wrong_size_or_forged_hash_is_not_a_verified_report(self):
        for raw in (b"wrong", self.raw[:-1] + b"!"):
            (self.root / "report/result").write_bytes(raw)
            with self.assertRaises(oracle.ArtifactError):
                oracle.check_artifacts(self.root, self.expected)
        (self.root / "report/result").unlink()
        with self.assertRaises(FileNotFoundError):
            oracle.check_artifacts(self.root, self.expected)

    def test_zero_exit_style_complete_report_cannot_waive_a_leftover_lease(self):
        (self.root / "lease").write_text("unreleased")
        with self.assertRaisesRegex(oracle.ArtifactError, "cleanup"):
            oracle.check_artifacts(self.root, self.expected, absent=["lease"])

    def test_dangling_cleanup_symlink_counts_as_present(self):
        (self.root / "lease").symlink_to("missing-target")
        with self.assertRaisesRegex(oracle.ArtifactError, "cleanup"):
            oracle.check_artifacts(self.root, self.expected, absent=["lease"])

    def test_linked_leaf_parent_and_fifo_are_refused_without_blocking(self):
        (self.root / "alias").symlink_to(self.root / "report", target_is_directory=True)
        (self.root / "leaf").symlink_to(self.root / "report/result")
        os.mkfifo(self.root / "pipe")
        for name in ("alias/result", "leaf", "pipe"):
            with self.subTest(name=name), self.assertRaises((OSError, oracle.ArtifactError)):
                oracle.read_file(self.root, name)

    def test_unsafe_duplicate_conflicting_and_boolean_descriptors_fail_closed(self):
        for path in ("../report/result", "/report/result", "report//result", "report/./result", "report\\result", ".", ""):
            with self.subTest(path=path), self.assertRaises(oracle.ArtifactError):
                oracle.check_artifacts(self.root, [{**self.expected[0], "path": path}])
        for required, absent in ((self.expected * 2, []), (self.expected, ["report/result"]),
                                 ([{**self.expected[0], "bytes": True}], []), ([{**self.expected[0], "verified": True}], [])):
            with self.assertRaises(oracle.ArtifactError):
                oracle.check_artifacts(self.root, required, absent=absent)

    def test_file_count_size_and_total_bounds_are_enforced(self):
        with mock.patch.object(oracle, "MAX_FILE_BYTES", 1), self.assertRaises(oracle.ArtifactError):
            oracle.read_file(self.root, "report/result")
        with mock.patch.object(oracle, "MAX_TOTAL_BYTES", 1), self.assertRaises(oracle.ArtifactError):
            oracle.check_artifacts(self.root, self.expected)
        with mock.patch.object(oracle, "MAX_PATHS", 0), self.assertRaises(oracle.ArtifactError):
            oracle.check_artifacts(self.root, self.expected)


if __name__ == "__main__":
    unittest.main()
