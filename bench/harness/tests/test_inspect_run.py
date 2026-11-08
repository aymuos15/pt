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
        self.assertFalse(summary["confirmatory_eligible"])

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


if __name__ == "__main__":
    unittest.main()
