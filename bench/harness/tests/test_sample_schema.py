import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import jsonschema


HARNESS = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((HARNESS / "sample.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


class ExploratorySampleSchemaTests(unittest.TestCase):
    def make_records(self, baseline, candidate, prepare=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        output = root / "run"
        command = [sys.executable, str(HARNESS / "paired.py"), "--timing-endpoint", "command", "--output", str(output),
                   "--cwd", str(root), "--baseline-json", json.dumps(baseline),
                   "--candidate-json", json.dumps(candidate), "--blocks", "1", "--seed", "3",
                   "--timeout", "0.2"]
        if prepare is not None:
            command += ["--baseline-prepare-json", json.dumps(prepare)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(path.read_text()) for path in sorted(output.glob("block-*.json"))]

    def test_schema_itself_is_valid(self):
        jsonschema.Draft202012Validator.check_schema(SCHEMA)

    def test_completed_timeout_and_launch_error_records_validate(self):
        scenarios = [
            ([sys.executable, "-c", "pass"], ["/nonexistent/pt-test-command"]),
            ([sys.executable, "-c", "import time; time.sleep(5)"], [sys.executable, "-c", "pass"]),
        ]
        for baseline, candidate in scenarios:
            for record in self.make_records(baseline, candidate):
                with self.subTest(status=record["result"]["status"]):
                    VALIDATOR.validate(record)

    def test_failed_preparation_record_validates(self):
        command = [sys.executable, "-c", "pass"]
        records = self.make_records(command, command, [sys.executable, "-c", "raise SystemExit(4)"])
        self.assertIn("not_run_preparation_failed", [item["result"]["status"] for item in records])
        for record in records:
            VALIDATOR.validate(record)

    def test_malformed_measurements_and_claims_are_rejected(self):
        record = self.make_records([sys.executable, "-c", "pass"],
                                   [sys.executable, "-c", "pass"])[0]
        mutations = []
        wrong_mode = copy.deepcopy(record)
        wrong_mode["mode"] = "confirmatory"
        mutations.append(wrong_mode)
        missing_hash = copy.deepcopy(record)
        del missing_hash["result"]["stdout_sha256"]
        mutations.append(missing_hash)
        contradictory = copy.deepcopy(record)
        contradictory["result"]["process_reaped"] = False
        mutations.append(contradictory)
        missing_preparation = copy.deepcopy(record)
        del missing_preparation["preparation"]
        mutations.append(missing_preparation)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(jsonschema.ValidationError):
                VALIDATOR.validate(mutation)


if __name__ == "__main__":
    unittest.main()
