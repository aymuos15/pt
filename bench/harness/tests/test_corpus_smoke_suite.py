import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "corpus_smoke_suite", Path(__file__).resolve().parents[1] / "corpus_smoke_suite.py"
)
corpus_suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus_suite)


class CorpusSmokeSuiteTests(unittest.TestCase):
    def test_failures_and_skips_are_not_counted_as_passes(self):
        class Cases(unittest.TestCase):
            def test_pass(self):
                pass

            def test_fail(self):
                self.fail("intentional negative control")

            @unittest.skip("intentional negative control")
            def test_skip(self):
                pass

        suite = unittest.TestSuite([Cases("test_pass"), Cases("test_fail"), Cases("test_skip")])
        result = corpus_suite.run_suite(suite)
        self.assertEqual(result["status"], "failed_or_incomplete")
        self.assertEqual(result["expected_tests"], 3)
        self.assertEqual([item["status"] for item in result["outcomes"]], ["passed", "failed", "skipped"])
        self.assertIn("intentional negative control", result["failures"][0]["detail"])

    def test_empty_suite_does_not_pass(self):
        self.assertEqual(corpus_suite.run_suite(unittest.TestSuite())["status"], "failed_or_incomplete")


if __name__ == "__main__":
    unittest.main()
