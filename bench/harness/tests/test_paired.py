import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PAIRED = Path(__file__).resolve().parents[1] / "paired.py"


class ExploratoryPairsTests(unittest.TestCase):
    def invoke(self, output, baseline, candidate, blocks=2, timeout=2):
        return subprocess.run([
            sys.executable, str(PAIRED), "--output", str(output), "--cwd", str(output.parent),
            "--baseline-json", json.dumps(baseline), "--candidate-json", json.dumps(candidate),
            "--blocks", str(blocks), "--seed", "3", "--timeout", str(timeout),
        ], capture_output=True, text=True, timeout=15)

    def test_schedule_and_all_arm_records_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [sys.executable, "-c", "print('base')"],
                                 [sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            schedule = json.loads((output / "schedule.json").read_text())
            self.assertEqual(schedule["mode"], "exploratory_unqualified")
            self.assertEqual(len(schedule["schedule"]), 2)
            samples = [json.loads(path.read_text()) for path in output.glob("block-*.json")]
            self.assertEqual(len(samples), 4)
            for sample in samples:
                self.assertEqual(sample["mode"], "exploratory_unqualified")
                self.assertEqual(sample["result"]["status"], "exited_unqualified")
                self.assertEqual(sample["result"]["returncode"],
                                 0 if sample["arm"] == "baseline" else 7)
                expected_order = schedule["schedule"][sample["block"] - 1]["order"]
                self.assertEqual(sample["arm"], expected_order[sample["position"] - 1])
            again = self.invoke(output, ["nonexistent"], ["nonexistent"])
            self.assertEqual(again.returncode, 2)
            self.assertEqual(len(list(output.glob("block-*.json"))), 4)

    def test_launch_error_does_not_discard_other_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, ["/nonexistent/pt-bench-command"],
                                 [sys.executable, "-c", "pass"], blocks=1)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            candidate = json.loads((output / "block-000001-candidate.json").read_text())
            self.assertEqual(baseline["result"]["status"], "launch_error")
            self.assertEqual(candidate["result"]["status"], "exited_unqualified")

    def test_invalid_input_does_not_create_run(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [], [sys.executable, "-c", "pass"])
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_timeout_remains_visible_and_other_arm_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [sys.executable, "-c", "import time; time.sleep(5)"],
                                 [sys.executable, "-c", "pass"], blocks=1, timeout=0.1)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            candidate = json.loads((output / "block-000001-candidate.json").read_text())
            self.assertEqual(baseline["result"]["status"], "timeout")
            self.assertEqual(candidate["result"]["status"], "exited_unqualified")


if __name__ == "__main__":
    unittest.main()
