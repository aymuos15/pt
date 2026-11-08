import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


HARNESS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guards = load("guards")
timer = load("pt_bench")


def check(result, output, exit_code=0):
    return guards.check_observation(
        result, expected_exit_code=exit_code, expected_stdout_bytes=len(output),
        expected_stdout_sha256=hashlib.sha256(output).hexdigest(),
    )


class ObservationGuardTests(unittest.TestCase):
    def test_good_sentinel_is_still_unqualified(self):
        result = timer.measure([sys.executable, "-c", "print('executed')"], ".", 3)
        verdict = check(result, b"executed\n")
        self.assertTrue(verdict["matched_expected_observations"])
        self.assertFalse(verdict["confirmatory_eligible"])

    def test_broken_candidate_skips_expected_output_but_returns_zero(self):
        result = timer.measure([sys.executable, "-c", "pass"], ".", 3)
        self.assertEqual(result["returncode"], 0)
        verdict = check(result, b"executed\n")
        self.assertFalse(verdict["matched_expected_observations"])
        self.assertIn("stdout_digest", verdict["mismatches"])

    def test_expected_nonzero_is_distinct_from_unexpected_exit(self):
        result = timer.measure([sys.executable, "-c", "raise SystemExit(7)"], ".", 3)
        self.assertTrue(check(result, b"", 7)["matched_expected_observations"])
        self.assertIn("exit_code", check(result, b"", 0)["mismatches"])

    def test_timeout_and_missing_cleanup_never_match(self):
        result = timer.measure([sys.executable, "-c", "import time; time.sleep(5)"], ".", 0.1)
        self.assertIn("not_completed", check(result, b"")["mismatches"])
        fabricated = {"status": "exited_unqualified", "returncode": 0, "stdout_bytes": 0,
                      "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                      "process_reaped": True, "output_complete": False}
        self.assertIn("incomplete_output", check(fabricated, b"")["mismatches"])

    def test_invalid_expectations_fail_closed(self):
        for code, size, digest in [(True, 0, "0" * 64), (0, -1, "0" * 64),
                                   (0, True, "0" * 64), (0, 0, "bad")]:
            with self.subTest(code=code, size=size, digest=digest), self.assertRaises(ValueError):
                guards.check_observation({}, expected_exit_code=code,
                                         expected_stdout_bytes=size, expected_stdout_sha256=digest)


if __name__ == "__main__":
    unittest.main()
