import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "junit_inventory", Path(__file__).resolve().parents[1] / "junit_inventory.py"
)
junit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(junit)


class JUnitInventoryTests(unittest.TestCase):
    def parse(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            path.write_text(content)
            return junit.read_inventory(path)

    def test_duplicate_occurrences_and_order_are_preserved(self):
        report = self.parse('<testsuite><testcase classname="x" name="same"/>'
                            '<testcase classname="x" name="same"><skipped type="pytest.xfail" '
                            'message="expected"/></testcase></testsuite>')
        self.assertEqual(report["occurrences"], 2)
        self.assertEqual(report["records"], [["x", "same", []],
                                              ["x", "same", [["skipped", "pytest.xfail", "expected"]]]])
        self.assertEqual(report["outcome_tags"], {"no_junit_failure_or_skip": 1, "skipped:pytest.xfail": 1})

    def test_changed_outcome_or_order_changes_digest(self):
        first = self.parse('<testsuite><testcase classname="x" name="a"/>'
                           '<testcase classname="x" name="b"/></testsuite>')
        for text in ('<testsuite><testcase classname="x" name="b"/><testcase classname="x" name="a"/></testsuite>',
                     '<testsuite><testcase classname="x" name="a"><failure/></testcase>'
                     '<testcase classname="x" name="b"/></testsuite>'):
            with self.subTest(text=text):
                self.assertNotEqual(first["ordered_inventory_sha256"], self.parse(text)["ordered_inventory_sha256"])

    def test_dtd_missing_identity_and_bad_root_are_rejected(self):
        for text in ('<!DOCTYPE testsuite [<!ENTITY x "bad">]><testsuite/>',
                     '<testsuite><testcase name="missing-class"/></testsuite>',
                     '<not-junit/>'):
            with self.subTest(text=text), self.assertRaises(junit.JUnitError):
                self.parse(text)

    def test_cli_rejects_matching_counts_with_different_test_occurrences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first.xml", root / "second.xml"
            first.write_text('<testsuite><testcase classname="x" name="a"/></testsuite>')
            second.write_text('<testsuite><testcase classname="x" name="b"/></testsuite>')
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "junit_inventory.py"),
                       str(first), str(second)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["matched"])
            self.assertFalse(report["confirmatory_eligible"])
            self.assertEqual(report["first"]["occurrences"], report["second"]["occurrences"])

if __name__ == "__main__":
    unittest.main()
