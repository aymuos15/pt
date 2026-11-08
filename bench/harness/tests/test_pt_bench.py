import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "pt_bench", Path(__file__).resolve().parents[1] / "pt_bench.py"
)
pt_bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pt_bench)


class MeasureTests(unittest.TestCase):
    def test_success_is_explicitly_unqualified(self):
        result = pt_bench.measure([sys.executable, "-c", "print('hello')"], ".", 5)
        self.assertEqual(result["status"], "exited_unqualified")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout_bytes"], 6)
        self.assertGreater(result["elapsed_ns"], 0)

    def test_nonzero_exit_is_retained_not_labeled_pass(self):
        result = pt_bench.measure([sys.executable, "-c", "raise SystemExit(7)"], ".", 5)
        self.assertEqual(result["status"], "exited_unqualified")
        self.assertEqual(result["returncode"], 7)

    def test_empty_argument_is_forwarded(self):
        result = pt_bench.measure(
            [sys.executable, "-c", "import sys; assert sys.argv[1] == ''", ""], ".", 5
        )
        self.assertEqual(result["returncode"], 0)

    def test_timeout_is_not_success(self):
        result = pt_bench.measure([sys.executable, "-c", "import time; time.sleep(5)"], ".", 0.1)
        self.assertEqual(result["status"], "timeout")
        self.assertIsNotNone(result["returncode"])

    def test_missing_executable_is_recorded(self):
        result = pt_bench.measure(["/nonexistent/pt-bench-executable"], ".", 1)
        self.assertEqual(result["status"], "launch_error")
        self.assertIn("error", result)

    def test_bad_arguments_rejected(self):
        for argv, timeout in [([], 1), ([""], 1), (["x"], 0), (["x"], float("nan"))]:
            with self.subTest(argv=argv, timeout=timeout):
                with self.assertRaises(ValueError):
                    pt_bench.measure(argv, ".", timeout)

    def test_records_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sample.json")
            pt_bench.write_record(path, {"status": "first"})
            with self.assertRaises(FileExistsError):
                pt_bench.write_record(path, {"status": "second"})
            self.assertEqual(json.loads(Path(path).read_text())["status"], "first")


if __name__ == "__main__":
    unittest.main()
