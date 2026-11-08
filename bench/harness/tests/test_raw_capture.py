import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TIMER = Path(__file__).resolve().parents[1] / "pt_bench.py"


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX raw capture")
class RawCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "blobs"
        self.bundle.mkdir()
        self.record = self.root / "sample.json"

    def run_timer(self, code, limit=100, timeout=5):
        return subprocess.run([
            sys.executable, str(TIMER), "--cwd", str(self.root), "--timeout", str(timeout),
            "--output", str(self.record), "--raw-output-bundle", str(self.bundle),
            "--raw-limit-bytes", str(limit), "--", sys.executable, "-c", code,
        ], capture_output=True, text=True, timeout=15)

    def test_captures_complete_streams_as_verified_blobs(self):
        result = self.run_timer("import os; os.write(1,b'out'); os.write(2,b'err')")
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = json.loads(self.record.read_text())["result"]
        capture = sample["raw_capture"]
        self.assertEqual(capture["capture_mode"], "bounded_prefix")
        for name, payload in (("stdout", b"out"), ("stderr", b"err")):
            item = capture[name]
            self.assertFalse(item["truncated"])
            self.assertEqual(item["stored_bytes"], len(payload))
            self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual((self.bundle / item["sha256"]).read_bytes(), payload)
            self.assertEqual(sample[f"{name}_sha256"], item["sha256"])
        self.assertEqual(sample["elapsed_ns"], sample["monotonic_end_ns"] - sample["monotonic_start_ns"])

    def test_limit_records_prefix_without_hiding_truncation(self):
        result = self.run_timer("import os; os.write(1,b'abcdefgh')", limit=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = json.loads(self.record.read_text())["result"]
        captured = sample["raw_capture"]["stdout"]
        self.assertTrue(captured["truncated"])
        self.assertEqual(captured["stored_bytes"], 3)
        self.assertEqual((self.bundle / captured["sha256"]).read_bytes(), b"abc")
        self.assertEqual(sample["stdout_bytes"], 8)
        self.assertEqual(sample["stdout_sha256"], hashlib.sha256(b"abcdefgh").hexdigest())
        self.assertNotEqual(sample["stdout_sha256"], captured["sha256"])

    def test_corrupt_existing_blob_fails_without_publishing_sample(self):
        digest = hashlib.sha256(b"expected").hexdigest()
        (self.bundle / digest).write_bytes(b"corrupt!")
        result = self.run_timer("import os; os.write(1,b'expected')")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.record.exists())
        self.assertEqual((self.bundle / digest).read_bytes(), b"corrupt!")

    def test_timeout_retains_observed_prefix_without_becoming_success(self):
        result = self.run_timer("import os,time; os.write(1,b'before'); time.sleep(5)", timeout=0.1)
        self.assertEqual(result.returncode, 1)
        sample = json.loads(self.record.read_text())["result"]
        self.assertEqual(sample["status"], "timeout")
        blob = sample["raw_capture"]["stdout"]
        self.assertEqual((self.bundle / blob["sha256"]).read_bytes(), b"before")
        self.assertFalse(blob["truncated"])

    def test_post_exit_blob_failure_does_not_signal_reaped_process(self):
        sys.path.insert(0, str(TIMER.parent))
        try:
            import raw_capture
            spec = importlib.util.spec_from_file_location("timer_capture_test", TIMER)
            timer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(timer)
            with mock.patch.object(raw_capture.RawCapture, "publish", side_effect=ValueError("injected")):
                with mock.patch.object(timer, "_abort_process") as abort:
                    with self.assertRaisesRegex(ValueError, "injected"):
                        timer.measure([sys.executable, "-c", "pass"], str(self.root), 5,
                                      raw_bundle=self.bundle)
                    abort.assert_not_called()
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
