import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import finalization
finally:
    sys.path.pop(0)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "safe POSIX file observations")
class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_contract_rejects_unknown_unbounded_duplicate_or_conflicting_requirements(self):
        artifact = {"path": "report", "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
        base = {"expected_exit_code": 0, "artifacts": [artifact], "absent": ["lease"]}
        invalid = [None, [], {**base, "unknown": True}, {**base, "expected_exit_code": True},
                   {**base, "absent": ["report"]}, {**base, "absent": ["lease", "lease"]},
                   {**base, "artifacts": [artifact, artifact]},
                   {**base, "artifacts": [{**artifact, "path": "lease/report"}]},
                   {**base, "artifacts": [{**artifact, "bytes": True}]},
                   {**base, "artifacts": [{**artifact, "bytes": finalization.MAX_ARTIFACT_BYTES + 1}]},
                   {**base, "artifacts": [{**artifact, "sha256": "not-a-digest"}]}]
        # None deliberately means an empty, explicit observational contract.
        self.assertEqual(finalization.requirements(None),
                         {"expected_exit_code": None, "artifacts": [], "absent": []})
        for value in invalid[1:]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                finalization.requirements(value)
        for path in ("../report", "/report", "./report", "a//b", "a/../b", ".", "", "a\\b", "a\x00b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                finalization.requirements({**base, "absent": [path]})

    def test_nested_regular_file_read_is_bounded_and_streamed(self):
        (self.root / "reports").mkdir()
        payload = b"x" * 1_100_000
        (self.root / "reports/report").write_bytes(payload)
        observed, retained = finalization.inspect_file(self.root, "reports/report", limit=len(payload))
        self.assertEqual(observed["bytes"], len(payload))
        self.assertEqual(observed["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(retained, b"")
        self.assertEqual(len(observed["identity"]), 5)
        with mock.patch.object(finalization.os, "read") as read:
            with self.assertRaisesRegex(ValueError, "byte limit"):
                finalization.inspect_file(self.root, "reports/report", limit=len(payload) - 1)
            read.assert_not_called()

    def test_symlinks_directories_fifo_and_symlink_root_are_not_artifacts(self):
        (self.root / "regular").write_bytes(b"x")
        (self.root / "link").symlink_to(self.root / "regular")
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "fifo")
        (self.root / "parent-link").symlink_to(self.root / "directory", target_is_directory=True)
        for path in ("link", "directory", "fifo", "parent-link/file"):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                finalization.inspect_file(self.root, path, limit=1)
        alias = self.root / "root-link"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            finalization.inspect_file(alias, "regular", limit=1)

    def test_replacing_name_during_read_is_rejected_without_retry(self):
        target = self.root / "report"
        target.write_bytes(b"same")
        original = finalization.os.read
        replaced = []

        def replace(fd, size):
            chunk = original(fd, size)
            if chunk and not replaced:
                replacement = self.root / "replacement"
                replacement.write_bytes(b"same")
                replacement.replace(target)
                replaced.append(True)
            return chunk

        with mock.patch.object(finalization.os, "read", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "changed during"):
                finalization.inspect_file(self.root, "report", limit=4)
        self.assertEqual(replaced, [True])

    def test_absence_is_not_following_symlinks_or_permission_failure(self):
        (self.root / "dangling").symlink_to(self.root / "missing")
        (self.root / "directory").mkdir()
        (self.root / "alias").symlink_to(self.root / "directory", target_is_directory=True)
        contract = finalization.requirements({"expected_exit_code": None, "artifacts": [],
                                              "absent": ["missing/child", "dangling", "alias/child"]})
        verdict = finalization.check(None, self.root, contract)
        by_path = {item["path"]: item for item in verdict["checks"] if "path" in item}
        self.assertTrue(by_path["missing/child"]["matched"])
        self.assertFalse(by_path["dangling"]["matched"])
        self.assertFalse(by_path["alias/child"]["matched"])
        self.assertIn("error", by_path["alias/child"])
        permission_contract = finalization.requirements({"expected_exit_code": None, "artifacts": [],
                                                        "absent": ["denied"]})
        with mock.patch.object(finalization.os, "stat", side_effect=PermissionError("denied")) as denied:
            # Replacing the callable otherwise changes its membership in
            # supports_dir_fd before the intended permission fault is reached.
            with mock.patch.object(finalization.os, "supports_dir_fd", os.supports_dir_fd | {denied}):
                failed = finalization.check(None, self.root, permission_contract)
        self.assertTrue(all(not item["matched"] for item in failed["checks"]))
        self.assertIn("error", failed["checks"][-1])

    def test_json_reader_rejects_duplicates_constants_nonobjects_and_truncation(self):
        path = self.root / "receipt.json"
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '[]', '{"a":'):
            path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                finalization.read_json(path)
        path.write_text(json.dumps({"a": 1}))
        value, metadata = finalization.read_json(path)
        self.assertEqual(value, {"a": 1})
        self.assertEqual(metadata["bytes"], path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            finalization.read_json(path, limit=1)
