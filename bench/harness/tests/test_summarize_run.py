import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HARNESS = Path(__file__).resolve().parents[1]
PAIRED = HARNESS / "paired.py"
SUMMARY = HARNESS / "summarize_run.py"
SENTINEL = b"executed\n"
GUARD = {"expected_exit_code": 0, "expected_stdout_bytes": len(SENTINEL),
         "expected_stdout_sha256": hashlib.sha256(SENTINEL).hexdigest()}


class ExploratorySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "run"

    def make_run(self, candidate, *, guarded=True, capture_limit=None):
        baseline = [sys.executable, "-c", "print('executed')"]
        command = [sys.executable, str(PAIRED), "--output", str(self.output), "--cwd", str(self.root),
                   "--baseline-json", json.dumps(baseline), "--candidate-json", json.dumps(candidate),
                   "--blocks", "2", "--seed", "5", "--timeout", "3", "--timing-endpoint", "command"]
        if guarded:
            command += ["--baseline-guard-json", json.dumps(GUARD), "--candidate-guard-json", json.dumps(GUARD)]
        if capture_limit is not None:
            command += ["--capture-raw", "--raw-limit-bytes", str(capture_limit)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def summarize(self, *arguments):
        return subprocess.run([sys.executable, str(SUMMARY), str(self.output), *arguments],
                              capture_output=True, text=True, timeout=15)

    def test_all_guarded_records_produce_only_exploratory_estimate(self):
        self.make_run([sys.executable, "-c", "print('executed')"])
        result = self.summarize()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "exploratory_point_estimate")
        self.assertEqual(report["blocks"], 2)
        self.assertEqual(report["observation_guard_counts"], {"matched": 4})
        self.assertEqual(report["ratio_direction"], "baseline_over_candidate")
        self.assertEqual(report["timing_endpoint"], "process_launch_through_exit_pipes_and_optional_raw_finalization_v1")
        self.assertGreater(report["ratio"], 0)
        absolute = report["absolute_latency_ns"]
        self.assertGreater(absolute["baseline_mean"], 0)
        self.assertGreater(absolute["candidate_mean"], 0)
        self.assertAlmostEqual(absolute["mean_paired_baseline_minus_candidate"],
                               absolute["baseline_mean"] - absolute["candidate_mean"], places=5)
        self.assertIsNone(report["bootstrap"])
        self.assertFalse(report["confirmatory_eligible"])

    def test_optional_bootstrap_is_reproducible_and_unqualified(self):
        self.make_run([sys.executable, "-c", "print('executed')"])
        arguments = ("--bootstrap-resamples", "100", "--bootstrap-seed", "7")
        first, second = self.summarize(*arguments), self.summarize(*arguments)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        report, repeated = json.loads(first.stdout), json.loads(second.stdout)
        self.assertEqual(report["bootstrap"], repeated["bootstrap"])
        self.assertEqual(report["bootstrap"]["bootstrap_resamples"], 100)
        self.assertEqual(report["bootstrap"]["blocks"], 2)
        self.assertEqual(report["bootstrap"]["mode"], "exploratory_unqualified")
        self.assertIn("independence not established", report["limitations"])
        self.assertFalse(report["confirmatory_eligible"])

    def test_bootstrap_requires_both_valid_options(self):
        self.make_run([sys.executable, "-c", "print('executed')"])
        for args in (("--bootstrap-resamples", "100"), ("--bootstrap-seed", "7"),
                     ("--bootstrap-resamples", "1", "--bootstrap-seed", "7")):
            with self.subTest(args=args):
                self.assertEqual(self.summarize(*args).returncode, 2)

    def test_wrong_work_and_missing_guards_block_without_dropping_pairs(self):
        self.make_run([sys.executable, "-c", "pass"])
        result = self.summarize("--bootstrap-resamples", "100", "--bootstrap-seed", "7")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["blocks"], 2)
        self.assertIsNone(report["ratio"])
        self.assertIsNone(report["absolute_latency_ns"])
        self.assertIsNone(report["bootstrap"])
        self.assertEqual(len(report["blockers"]), 2)
        self.assertTrue(all("guard_mismatch" in item["reasons"] for item in report["blockers"]))

    def test_no_guard_blocks_entire_run(self):
        self.make_run([sys.executable, "-c", "print('executed')"], guarded=False)
        report = json.loads(self.summarize().stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["blockers"]), 4)
        self.assertIsNone(report["ratio"])

    def test_missing_interval_blocks_estimate(self):
        self.make_run([sys.executable, "-c", "print('executed')"])
        path = self.output / "block-000001-baseline.json"
        record = json.loads(path.read_text())
        for field in ("monotonic_start_ns", "monotonic_end_ns", "clock_domain"):
            del record["result"][field]
        path.write_text(json.dumps(record))
        result = self.summarize()
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["recorded_interval_order"], "incomplete")
        self.assertIn("recorded_interval_order_incomplete", report["blockers"][0]["reasons"])
        self.assertIsNone(report["ratio"])

    @unittest.skipUnless(sys.platform != "win32", "POSIX raw capture")
    def test_truncated_capture_blocks_estimate(self):
        self.make_run([sys.executable, "-c", "print('executed')"], capture_limit=1)
        report = json.loads(self.summarize().stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(all("raw_capture_truncated" in item["reasons"] for item in report["blockers"]))
        self.assertIsNone(report["ratio"])


if __name__ == "__main__":
    unittest.main()
