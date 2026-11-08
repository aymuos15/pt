"""Check initial corpus probes against pytest, not against PT."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "probes"


class CorpusSmokeTests(unittest.TestCase):
    def run_probe(self, filename):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.xml"
            env = os.environ.copy()
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                 str(CORPUS / filename), f"--junitxml={report}"],
                cwd=directory, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertTrue(report.exists(), result.stdout + result.stderr)
            return result, ET.parse(report).getroot()

    def test_noop_probe_executes_one_success(self):
        result, report = self.run_probe("noop_cases.py")
        cases = report.findall(".//testcase")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([case.get("name") for case in cases], ["test_noop"])
        self.assertEqual(len(cases[0]), 0)

    def test_phase_probe_retains_adverse_outcomes(self):
        result, report = self.run_probe("phase_cases.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        cases = report.findall(".//testcase")
        self.assertEqual(len(cases), 4)
        by_name = {case.get("name"): case for case in cases}
        self.assertEqual(set(by_name), {"test_pass", "test_setup_failure",
                                        "test_teardown_failure", "test_strict_xpass"})
        self.assertEqual(len(by_name["test_pass"]), 0)
        setup = by_name["test_setup_failure"].find("error")
        teardown = by_name["test_teardown_failure"].find("error")
        xpass = by_name["test_strict_xpass"].find("failure")
        self.assertIsNotNone(setup)
        self.assertIn("failed on setup", setup.get("message", ""))
        self.assertIn("PT_PROBE_SETUP_FAILURE", setup.get("message", ""))
        self.assertIsNotNone(teardown)
        self.assertIn("failed on teardown", teardown.get("message", ""))
        self.assertIn("PT_PROBE_TEARDOWN_FAILURE", teardown.get("message", ""))
        self.assertIsNotNone(xpass)
        self.assertIn("XPASS(strict)", xpass.get("message", ""))


if __name__ == "__main__":
    unittest.main()
