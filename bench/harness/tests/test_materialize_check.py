import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    spec = importlib.util.spec_from_file_location("materialize_check", HARNESS / "materialize_check.py")
    materialize = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(materialize)
finally:
    sys.path.pop(0)


class MaterializationReportTests(unittest.TestCase):
    def read_report(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            path.write_text(text)
            return materialize.normalize_report(path)

    def test_preserves_duplicate_occurrences_and_order(self):
        result = self.read_report(
            '<testsuite><testcase name="same"/><testcase name="same">'
            '<error message="PT_PROBE_SETUP_FAILURE"/></testcase></testsuite>'
        )
        self.assertEqual(result, [
            {"name": "same", "kind": "passed", "marker": ""},
            {"name": "same", "kind": "error", "marker": "PT_PROBE_SETUP_FAILURE"},
        ])

    def test_does_not_hide_unrecognized_failure(self):
        result = self.read_report('<testsuite><testcase name="test_pass">'
                                  '<failure message="unexpected"/></testcase></testsuite>')
        self.assertNotEqual(result, materialize.EXPECTED[:1])

    def test_rejects_ambiguous_testcase(self):
        with self.assertRaises(ValueError):
            self.read_report('<testsuite><testcase name="x"><failure/><error/>'
                             '</testcase></testsuite>')


if __name__ == "__main__":
    unittest.main()
