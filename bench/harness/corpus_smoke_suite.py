"""Run the current synthetic corpus checks and retain individual outcomes."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


class OutcomeRecorder(unittest.TestResult):
    """Record every test disposition; a skip or expected failure is not a pass."""

    def __init__(self):
        super().__init__()
        self.outcomes = []

    def _record(self, test, status):
        self.outcomes.append({"test": test.id(), "status": status})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "expected_failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected_success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(subtest, "subtest_failure")


def run_suite(suite: unittest.TestSuite) -> dict:
    expected_count = suite.countTestCases()
    result = OutcomeRecorder()
    suite.run(result)
    passed = (expected_count > 0 and len(result.outcomes) == expected_count
              and all(item["status"] == "passed" for item in result.outcomes))
    return {"status": "passed" if passed else "failed_or_incomplete",
            "expected_tests": expected_count, "outcomes": result.outcomes,
            "failures": [{"test": test.id(), "detail": detail}
                         for test, detail in result.failures + result.errors]}


def main() -> int:
    test_directory = Path(__file__).resolve().parent / "tests"
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.discover(str(test_directory), pattern="test_corpus_smoke.py"),
        loader.discover(str(test_directory), pattern="test_bytecode_probe.py"),
    ])
    result = run_suite(suite)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
