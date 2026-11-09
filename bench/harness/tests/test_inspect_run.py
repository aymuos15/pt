import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HARNESS = Path(__file__).resolve().parents[1]
PAIRED = HARNESS / "paired.py"
INSPECT = HARNESS / "inspect_run.py"


class InspectRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "run"

    def make_run(self, preparation=None):
        command = [sys.executable, "-c", "pass"]
        args = [sys.executable, str(PAIRED), "--output", str(self.run_dir),
                "--cwd", str(self.root), "--baseline-json", json.dumps(command),
                "--candidate-json", json.dumps(command), "--blocks", "1", "--seed", "5",
                "--timeout", "2"]
        if preparation is not None:
            args += ["--baseline-prepare-json", json.dumps(preparation)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def inspect(self):
        return subprocess.run([sys.executable, str(INSPECT), str(self.run_dir)],
                              capture_output=True, text=True, timeout=15)

    def test_complete_run_remains_unqualified(self):
        self.make_run()
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["record_consistency"], "complete")
        self.assertEqual(summary["arm_status_counts"], {"exited_unqualified": 2})
        self.assertEqual(summary["recorded_interval_order"], "nonoverlapping")
        self.assertEqual(summary["timing_endpoint"], "process_launch_through_exit_pipes_and_optional_raw_finalization_v1")
        self.assertFalse(summary["confirmatory_eligible"])
        plan_path = self.run_dir / "schedule.json"
        plan = json.loads(plan_path.read_text())
        plan["timing_endpoint"] = "invocation_through_sample_publication_and_declared_finalization_v1"
        plan_path.write_text(json.dumps(plan))
        rejected = self.inspect()
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("do not mix", rejected.stderr)

    def test_legacy_run_without_state_probes_remains_readable(self):
        self.make_run()
        plan_path = self.run_dir / "schedule.json"
        plan = json.loads(plan_path.read_text())
        del plan["state_probe_argv"]
        plan_path.write_text(json.dumps(plan))
        for path in self.run_dir.glob("block-*.json"):
            record = json.loads(path.read_text())
            del record["state_probe"]
            path.write_text(json.dumps(record))
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["confirmatory_eligible"])

    def test_failed_preparation_is_preserved(self):
        self.make_run([sys.executable, "-c", "raise SystemExit(7)"])
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["arm_status_counts"], {
            "exited_unqualified": 1, "not_run_preparation_failed": 1})

    def test_missing_and_unexpected_records_fail(self):
        self.make_run()
        missing = self.run_dir / "block-000001-baseline.json"
        original = missing.read_bytes()
        missing.unlink()
        self.assertEqual(self.inspect().returncode, 2)
        missing.write_bytes(original)
        (self.run_dir / "block-000001-extra.json").write_text("{}")
        self.assertEqual(self.inspect().returncode, 2)

    def test_tampered_position_command_and_duplicate_keys_fail(self):
        self.make_run()
        path = self.run_dir / "block-000001-baseline.json"
        original = json.loads(path.read_text())
        for mutation in ("position", "argv", "duplicate"):
            data = json.loads(json.dumps(original))
            if mutation == "position":
                data["position"] = 3
                path.write_text(json.dumps(data))
            elif mutation == "argv":
                data["result"]["argv"] = ["different"]
                path.write_text(json.dumps(data))
            else:
                path.write_text('{"arm":"baseline","arm":"candidate"}')
            with self.subTest(mutation=mutation):
                self.assertEqual(self.inspect().returncode, 2)

    def test_malformed_output_and_reaping_fields_fail(self):
        self.make_run()
        path = self.run_dir / "block-000001-baseline.json"
        original = json.loads(path.read_text())
        mutations = [
            ("stdout_bytes", -1), ("stdout_bytes", True), ("stderr_bytes", None),
            ("stdout_sha256", "not-a-digest"), ("stderr_sha256", "A" * 64),
            ("returncode", None), ("process_reaped", False),
        ]
        for field, value in mutations:
            data = json.loads(json.dumps(original))
            data["result"][field] = value
            path.write_text(json.dumps(data))
            with self.subTest(field=field, value=value):
                self.assertEqual(self.inspect().returncode, 2)

    def test_timing_fields_must_agree_and_legacy_records_remain_readable(self):
        self.make_run()
        path = self.run_dir / "block-000001-baseline.json"
        original = json.loads(path.read_text())
        for change in ("wrong_elapsed", "missing_end", "wrong_domain"):
            data = json.loads(json.dumps(original))
            if change == "wrong_elapsed":
                data["result"]["elapsed_ns"] += 1
            elif change == "missing_end":
                del data["result"]["monotonic_end_ns"]
            else:
                data["result"]["clock_domain"] = "other_process"
            path.write_text(json.dumps(data))
            with self.subTest(change=change):
                self.assertEqual(self.inspect().returncode, 2)
        legacy = json.loads(json.dumps(original))
        for field in ("monotonic_start_ns", "monotonic_end_ns", "clock_domain"):
            del legacy["result"][field]
        path.write_text(json.dumps(legacy))
        result = self.inspect()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["recorded_interval_order"], "incomplete")

    def test_overlapping_recorded_arms_are_rejected(self):
        self.make_run()
        plan = json.loads((self.run_dir / "schedule.json").read_text())
        first_arm, second_arm = plan["schedule"][0]["order"]
        first = json.loads((self.run_dir / f"block-000001-{first_arm}.json").read_text())
        second_path = self.run_dir / f"block-000001-{second_arm}.json"
        second = json.loads(second_path.read_text())
        duration = second["result"]["elapsed_ns"]
        second["result"]["monotonic_start_ns"] = first["result"]["monotonic_end_ns"] - 1
        second["result"]["monotonic_end_ns"] = second["result"]["monotonic_start_ns"] + duration
        second_path.write_text(json.dumps(second))
        result = self.inspect()
        self.assertEqual(result.returncode, 2)
        self.assertIn("overlap", result.stderr)

    def test_overlapping_preparation_and_measurement_are_rejected(self):
        self.make_run([sys.executable, "-c", "pass"])
        prep_path = self.run_dir / "preparation-000001-baseline.json"
        prep = json.loads(prep_path.read_text())
        measurement = json.loads((self.run_dir / "block-000001-baseline.json").read_text())
        prep["result"]["monotonic_end_ns"] = measurement["result"]["monotonic_start_ns"] + 1
        prep["result"]["elapsed_ns"] = (prep["result"]["monotonic_end_ns"]
                                       - prep["result"]["monotonic_start_ns"])
        prep_path.write_text(json.dumps(prep))
        result = self.inspect()
        self.assertEqual(result.returncode, 2)
        self.assertIn("overlap", result.stderr)

    def test_arm_records_must_match_exploratory_sample_schema(self):
        self.make_run()
        path = self.run_dir / "block-000001-baseline.json"
        original = json.loads(path.read_text())
        for change in ("extra_claim", "missing_preparation", "missing_digest"):
            record = json.loads(json.dumps(original))
            if change == "extra_claim":
                record["confirmatory_eligible"] = True
            elif change == "missing_preparation":
                del record["preparation"]
            else:
                del record["result"]["stdout_sha256"]
            path.write_text(json.dumps(record))
            with self.subTest(change=change):
                result = self.inspect()
                self.assertEqual(result.returncode, 2)
                self.assertIn("sample schema", result.stderr)


if __name__ == "__main__":
    unittest.main()
