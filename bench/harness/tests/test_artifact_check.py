import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    spec = importlib.util.spec_from_file_location("artifact_check", HARNESS / "artifact_check.py")
    artifacts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(artifacts)
finally:
    sys.path.pop(0)

TEMPLATE = yaml.safe_load((HARNESS.parent / "benchmark-campaign.template.yaml").read_text())


@unittest.skipUnless(hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd,
                     "requires safe POSIX bundle lookup")
class ArtifactCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = copy.deepcopy(TEMPLATE)

    def test_matching_shared_digest_is_hashed_once_but_not_qualified(self):
        payload = b"test artifact"
        digest = hashlib.sha256(payload).hexdigest()
        (self.root / digest).write_bytes(payload)
        self.data["candidate"]["binary_sha256"] = digest
        self.data["baseline"]["binary_sha256"] = digest
        with mock.patch.object(artifacts, "_digest_status", wraps=artifacts._digest_status) as check:
            result = artifacts.check_artifacts(self.data, self.root)
        self.assertEqual(check.call_count, 1)
        statuses = {item["field"]: item["status"] for item in result["listed_artifact_checks"]}
        self.assertEqual(statuses["candidate.binary_sha256"], "matched")
        self.assertEqual(statuses["baseline.binary_sha256"], "matched")
        self.assertEqual(statuses["candidate.interpreter_sha256"], "unresolved")
        self.assertNotIn("scenario.coverage_config_sha256", statuses)
        self.assertFalse(result["all_listed_digests_resolved_and_matching"])
        self.assertFalse(result["confirmatory_eligible"])

    def test_missing_mismatched_and_coverage_requirements_are_visible(self):
        missing = "a" * 64
        mismatch = "b" * 64
        (self.root / mismatch).write_bytes(b"wrong")
        self.data["candidate"]["binary_sha256"] = missing
        self.data["baseline"]["binary_sha256"] = mismatch
        self.data["scenario"]["coverage"] = "branch"
        result = artifacts.check_artifacts(self.data, self.root)
        statuses = {item["field"]: item["status"] for item in result["listed_artifact_checks"]}
        self.assertEqual(statuses["candidate.binary_sha256"], "missing")
        self.assertEqual(statuses["baseline.binary_sha256"], "mismatch")
        self.assertEqual(statuses["scenario.coverage_config_sha256"], "unresolved")

    def test_all_digest_matches_still_do_not_qualify_campaign(self):
        payload = b"same placeholder file, not proof of artifact semantics"
        digest = hashlib.sha256(payload).hexdigest()
        (self.root / digest).write_bytes(payload)
        for arm in ("candidate", "baseline"):
            for field in artifacts.ARM_FIELDS:
                self.data[arm][field] = digest
        for section, fields in artifacts.OTHER_FIELDS.items():
            for field in fields:
                self.data[section][field] = digest
        result = artifacts.check_artifacts(self.data, self.root)
        self.assertTrue(result["all_listed_digests_resolved_and_matching"])
        self.assertFalse(result["confirmatory_eligible"])

    def test_symlinks_and_nonregular_files_are_not_read(self):
        link_digest = "a" * 64
        dir_digest = "b" * 64
        (self.root / link_digest).symlink_to("/etc/passwd")
        (self.root / dir_digest).mkdir()
        self.data["candidate"]["binary_sha256"] = link_digest
        self.data["baseline"]["binary_sha256"] = dir_digest
        result = artifacts.check_artifacts(self.data, self.root)
        statuses = {item["field"]: item["status"] for item in result["listed_artifact_checks"]}
        self.assertEqual(statuses["candidate.binary_sha256"], "unreadable")
        self.assertEqual(statuses["baseline.binary_sha256"], "not_regular")

    def test_unvalidated_digest_cannot_escape_bundle(self):
        self.data["candidate"]["binary_sha256"] = "../../etc/passwd"
        with self.assertRaises(artifacts.ManifestError):
            artifacts.check_artifacts(self.data, self.root)

    def test_cli_reports_unresolved_draft(self):
        result = subprocess.run([sys.executable, str(HARNESS / "artifact_check.py"),
                                 str(HARNESS.parent / "benchmark-campaign.template.yaml"),
                                 str(self.root)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('"confirmatory_eligible": false', result.stdout)
        self.assertIn('"status": "unresolved"', result.stdout)


if __name__ == "__main__":
    unittest.main()
