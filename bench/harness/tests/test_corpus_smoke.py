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

    def test_dynamic_collection_and_fixture_lifetimes(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.txt"
            report = Path(directory) / "report.xml"
            env = os.environ.copy()
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            env["PT_PROBE_EVENT_FILE"] = str(events)
            base = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                    "-o", "disable_test_id_escaping_and_forfeit_all_rights_to_community_support=True",
                    str(CORPUS / "lifecycle_cases.py")]
            collected = subprocess.run(base + ["--collect-only"], cwd=directory, env=env,
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(collected.returncode, 0, collected.stdout + collected.stderr)
            self.assertIn("test_lifecycle[α]", collected.stdout)
            self.assertIn("test_lifecycle[β]", collected.stdout)
            self.assertFalse(events.exists(), "collection must not execute fixtures")

            run = subprocess.run(base + [f"--junitxml={report}"], cwd=directory, env=env,
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            cases = ET.parse(report).getroot().findall(".//testcase")
            self.assertEqual([case.get("name") for case in cases],
                             ["test_lifecycle[α]", "test_lifecycle[β]"])
            self.assertEqual(events.read_text().splitlines(), [
                "session setup", "setup alpha", "call alpha", "teardown alpha",
                "setup beta", "call beta", "teardown beta", "session teardown",
            ])

    def test_import_probe_detects_extra_collection_session(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "imports.txt"
            env = os.environ.copy()
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            env["PT_PROBE_IMPORT_EVENTS"] = str(events)
            command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                       str(CORPUS / "import_effect_cases.py")]

            def invoke(extra):
                result = subprocess.run(command + extra, cwd=directory, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            invoke([])
            self.assertEqual(events.read_text().splitlines(), ["module import", "test call"])
            # Negative control: a separate preflight collection visibly adds an import.
            invoke(["--collect-only"])
            invoke([])
            self.assertEqual(events.read_text().splitlines(), [
                "module import", "test call", "module import", "module import", "test call",
            ])

    def test_custom_collector_preserves_duplicate_node_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_file = root / "cases.ptcase"
            case_file.write_text("pass:duplicate\npass:duplicate\nfail:expected-failure\n")
            report = root / "report.xml"
            env = os.environ.copy()
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            env["PYTHONPATH"] = str(CORPUS)
            command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p",
                       "custom_collector_plugin", "-q", str(case_file)]
            collected = subprocess.run(command + ["--collect-only"], cwd=directory, env=env,
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(collected.returncode, 0, collected.stdout + collected.stderr)
            self.assertEqual(collected.stdout.count("cases.ptcase::duplicate"), 2)
            run = subprocess.run(command + [f"--junitxml={report}"], cwd=directory, env=env,
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            cases = ET.parse(report).getroot().findall(".//testcase")
            self.assertEqual([case.get("name") for case in cases],
                             ["duplicate", "duplicate", "expected-failure"])
            self.assertEqual(len(cases[0]), 0)
            self.assertEqual(len(cases[1]), 0)
            failure = cases[2].find("failure")
            self.assertIsNotNone(failure)
            self.assertIn("PT_CUSTOM_COLLECTOR_EXPECTED_FAILURE", "".join(failure.itertext()))


if __name__ == "__main__":
    unittest.main()
