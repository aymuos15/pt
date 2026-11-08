import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "coverage_lines.py"
spec = importlib.util.spec_from_file_location("coverage_lines", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def report():
    return {"meta": {"format": 3, "version": "7.17.2", "branch_coverage": False, "show_contexts": False},
            "files": {"src/example.py": {"executed_lines": [3, 1], "missing_lines": [2], "excluded_lines": [4]}}}


class CoverageLineTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            path.write_text(json.dumps(data))
            return coverage.read_line_report(path)

    def test_line_sets_are_sorted_but_paths_are_not_normalized(self):
        first = self.parse(report())
        self.assertEqual(first["records"], [["src/example.py", [1, 3], [2], [4]]])
        changed = report()
        changed["files"]["other/example.py"] = changed["files"].pop("src/example.py")
        self.assertNotEqual(first["line_inventory_sha256"], self.parse(changed)["line_inventory_sha256"])

    def test_branch_context_missing_duplicate_and_overlapping_lines_fail(self):
        cases = []
        for key in ("branch_coverage", "show_contexts"):
            data = report()
            data["meta"][key] = True
            cases.append(data)
        missing = report()
        del missing["files"]["src/example.py"]["missing_lines"]
        cases.append(missing)
        duplicate = report()
        duplicate["files"]["src/example.py"]["executed_lines"] = [1, 1]
        cases.append(duplicate)
        overlap = report()
        overlap["files"]["src/example.py"]["excluded_lines"] = [1]
        cases.append(overlap)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(coverage.CoverageReportError):
                self.parse(data)

    def test_equal_percentages_do_not_hide_changed_lines(self):
        first, second = report(), copy.deepcopy(report())
        second["files"]["src/example.py"]["executed_lines"] = [1, 2]
        second["files"]["src/example.py"]["missing_lines"] = [3]
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a.json", Path(directory) / "b.json"
            a.write_text(json.dumps(first))
            b.write_text(json.dumps(second))
            result = subprocess.run([sys.executable, str(SCRIPT), str(a), str(b)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["matched"])
            self.assertFalse(json.loads(result.stdout)["confirmatory_eligible"])


if __name__ == "__main__":
    unittest.main()
