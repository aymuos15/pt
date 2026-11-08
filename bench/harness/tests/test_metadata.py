import importlib.util
from pathlib import Path
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "metadata", Path(__file__).resolve().parents[1] / "metadata.py"
)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


class MetadataTests(unittest.TestCase):
    def test_reports_scoped_runtime_information_not_environment(self):
        with mock.patch.dict(metadata.os.environ, {"PT_FAKE_SECRET": "secret-value"}):
            result = metadata.collect_metadata()
        self.assertEqual(result["status"], "incomplete_unqualified")
        self.assertEqual(len(result["harness_python_executable_sha256"]), 64)
        self.assertIsNone(result["harness_python_digest_error"])
        self.assertNotIn("secret-value", repr(result))
        self.assertNotIn("PT_FAKE_SECRET", repr(result))
        self.assertIn("arm environments not inspected", result["limitations"])

    def test_unreadable_executable_and_unavailable_affinity_are_explicit(self):
        with mock.patch.object(metadata.sys, "executable", "/nonexistent/python"):
            with mock.patch.object(metadata.os, "sched_getaffinity", side_effect=PermissionError,
                                   create=True):
                result = metadata.collect_metadata()
        self.assertIsNone(result["harness_python_executable_sha256"])
        self.assertEqual(result["harness_python_digest_error"], "FileNotFoundError")
        self.assertIsNone(result["harness_affinity_cpus"])
        self.assertEqual(result["affinity_error"], "PermissionError")


if __name__ == "__main__":
    unittest.main()
