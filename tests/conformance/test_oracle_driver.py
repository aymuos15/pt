"""Synthetic outer-driver failure checks, separate from real-pytest qualification."""

import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import check_oracle as driver
from test_support import case_root


class OracleDriverTests(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        self.output = self.root / "run"
        sys.path.insert(0, str(driver.ROOT / "bench/harness"))
        try:
            import pt_bench
            import raw_capture
        finally:
            sys.path.pop(0)
        self.timer = pt_bench
        self.calls = 0

    def fake_measure(self, command, cwd, *args, **kwargs):
        self.calls += 1
        driver._save(Path(cwd) / "checks.json", {
            "kind": "development_oracle_controls", "planned": 1, "ran": 1, "successful": True, "confirmatory_eligible": False,
            "status_counts": {"passed": 1}, "outcomes": [{"test": "explicit_synthetic_control", "status": "passed", "details": [], "subtests": []}]})
        empty = hashlib.sha256(b"").hexdigest()
        return {"synthetic_test_control": True, "status": "exited_unqualified", "process_reaped": True, "output_complete": True,
                "returncode": 0, "stdout_bytes": 0, "stderr_bytes": 0, "stdout_sha256": empty, "stderr_sha256": empty,
                "raw_capture": {"stdout": {"truncated": False}, "stderr": {"truncated": False}}}

    def test_requires_explicit_execution_separate_roots_and_no_overwrite(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            driver.check(self.output)
        with self.assertRaisesRegex(ValueError, "separate"):
            driver.check(driver.ROOT / "not-created", execute=True)
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with mock.patch.object(self.timer, "measure", side_effect=self.fake_measure), self.assertRaises(FileExistsError):
            driver.check(self.output, execute=True)
        self.assertEqual((self.output / "user-work").read_text(), "keep")
        self.assertEqual(self.calls, 0)

    def test_complete_synthetic_child_checks_cannot_upgrade_any_qualification(self):
        with mock.patch.object(self.timer, "measure", side_effect=self.fake_measure):
            result = driver.check(self.output, execute=True)
        self.assertEqual(result["status"], "passed_development_oracle_checks")
        self.assertTrue(result["observation"]["synthetic_test_control"])
        self.assertTrue(all(value is None for value in result["qualification"].values()))
        self.assertFalse(result["confirmatory_eligible"])

    def test_lost_return_after_complete_looking_checks_is_not_recovered_or_retried(self):
        def lost(*args, **kwargs):
            self.fake_measure(*args, **kwargs)
            raise OSError("explicit synthetic loss of the observer API return")

        with mock.patch.object(self.timer, "measure", side_effect=lost):
            result = driver.check(self.output, execute=True)
        self.assertEqual(result["status"], "unknown_execution_return")
        self.assertIsNone(result["observation"])
        self.assertIsNone(result["checks"])
        self.assertTrue((self.output / "checks.json").exists())
        self.assertEqual(self.calls, 1)

    def test_changed_frozen_source_does_not_become_a_success_despite_a_passing_child(self):
        def changed(*args, **kwargs):
            result = self.fake_measure(*args, **kwargs)
            (self.output / "frozen/tests/conformance/pt_reference_observer.py").write_text("changed")
            return result

        with mock.patch.object(self.timer, "measure", side_effect=changed):
            result = driver.check(self.output, execute=True)
        self.assertEqual(result["status"], "incomplete_oracle_check")
        self.assertIn("source changed", result["errors"][0]["error"])

    def test_failed_skipped_and_not_run_child_units_remain_in_the_denominator(self):
        def failed(*args, **kwargs):
            result = self.fake_measure(*args, **kwargs)
            path = self.output / "checks.json"
            value = json.loads(path.read_text())
            value.update(planned=3, ran=2, successful=False, status_counts={"failed": 1, "skipped": 1, "not_run": 1},
                         outcomes=[{"test": str(index), "status": status} for index, status in enumerate(("failed", "skipped", "not_run"))])
            path.write_text(json.dumps(value))
            result["returncode"] = 1
            return result

        with mock.patch.object(self.timer, "measure", side_effect=failed):
            result = driver.check(self.output, execute=True)
        self.assertEqual(result["status"], "incomplete_oracle_check")
        self.assertEqual(len(result["checks"]["outcomes"]), 3)
        self.assertEqual(result["checks"]["status_counts"], {"failed": 1, "skipped": 1, "not_run": 1})


if __name__ == "__main__":
    unittest.main()
