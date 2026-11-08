import importlib.util
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock


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
        self.assertEqual(result["clock_domain"], "harness_process_monotonic")
        self.assertEqual(result["elapsed_ns"],
                         result["monotonic_end_ns"] - result["monotonic_start_ns"])

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

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux procfs and POSIX process groups")
    def test_timeout_stops_owned_child_process_group(self):
        # The descendant records its PID and Linux start time so cleanup never
        # signals an unrelated process if a PID happens to be reused.
        program = (
            "import os,sys,time\n"
            "from pathlib import Path\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    fields = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()\n"
            "    Path(sys.argv[1]).write_text(str(os.getpid()) + ' ' + fields[19])\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "child.txt"
            result = pt_bench.measure([sys.executable, "-c", program, str(ready)], directory, 1.5)
            self.assertEqual(result["status"], "timeout")
            self.assertTrue(result["process_reaped"])
            self.assertTrue(result["output_complete"])
            self.assertTrue(ready.exists(), "child did not start before timeout")
            pid_text, start_time = ready.read_text().split()
            pid = int(pid_text)
            process_stat = Path("/proc") / pid_text / "stat"
            try:
                deadline = time.monotonic() + 2
                while True:
                    try:
                        fields = process_stat.read_text().rsplit(")", 1)[1].split()
                    except FileNotFoundError:
                        fields = None
                    if (fields is None or fields[19] != start_time or fields[0] == "Z"
                            or time.monotonic() >= deadline):
                        break
                    time.sleep(0.02)
                if fields is not None and fields[19] == start_time:
                    self.assertEqual(fields[0], "Z", "owned child remains live after timeout")
            finally:
                # If the test fails, terminate only the exact descendant it made.
                try:
                    fields = process_stat.read_text().rsplit(")", 1)[1].split()
                    if fields[19] == start_time and fields[0] != "Z":
                        os.kill(pid, signal.SIGKILL)
                except FileNotFoundError:
                    pass

    @unittest.skipUnless(os.name == "posix", "POSIX streaming implementation")
    def test_large_output_is_streamed_with_exact_hashes(self):
        program = "import os; os.write(1, b'a' * 2000000); os.write(2, b'b' * 1000000)"
        result = pt_bench.measure([sys.executable, "-c", program], ".", 5)
        self.assertTrue(result["output_complete"])
        self.assertEqual(result["stdout_bytes"], 2000000)
        self.assertEqual(result["stderr_bytes"], 1000000)
        self.assertEqual(result["stdout_sha256"], hashlib.sha256(b"a" * 2000000).hexdigest())
        self.assertEqual(result["stderr_sha256"], hashlib.sha256(b"b" * 1000000).hexdigest())

    @unittest.skipUnless(os.name == "posix", "POSIX process groups")
    def test_detached_pipe_holder_cannot_block_timeout_cleanup(self):
        program = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.6)'], "
            "start_new_session=True)"
        )
        result = pt_bench.measure([sys.executable, "-c", program], ".", 0.2)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["output_complete"])
        self.assertTrue(result["process_reaped"])
        self.assertEqual(result["returncode"], 0)
        self.assertLess(result["elapsed_ns"], 1_500_000_000)

    @unittest.skipUnless(os.name == "posix", "POSIX streaming implementation")
    def test_unexpected_stream_failure_terminates_and_reaps_child(self):
        original_popen = pt_bench.subprocess.Popen
        processes = []

        def track_process(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        for failure in (OSError("injected pipe failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(pt_bench.subprocess, "Popen", side_effect=track_process):
                    with mock.patch.object(pt_bench, "_stream_posix", side_effect=failure):
                        with self.assertRaises(type(failure)):
                            pt_bench.measure([sys.executable, "-c", "import time; time.sleep(30)"],
                                             ".", 5)
                process = processes[-1]
                self.assertIsNotNone(process.poll())
                self.assertTrue(process.stdout.closed)
                self.assertTrue(process.stderr.closed)

    def test_missing_executable_is_recorded(self):
        result = pt_bench.measure(["/nonexistent/pt-bench-executable"], ".", 1)
        self.assertEqual(result["status"], "launch_error")
        self.assertIn("error", result)
        self.assertEqual(result["elapsed_ns"],
                         result["monotonic_end_ns"] - result["monotonic_start_ns"])

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

    def test_serialization_and_publication_failure_leave_no_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            with self.assertRaises(ValueError):
                pt_bench.write_record(str(path), {"invalid": float("nan")})
            self.assertFalse(path.exists())
            with mock.patch.object(pt_bench.os, "link", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    pt_bench.write_record(str(path), {"status": "ready"})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_concurrent_publication_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sample.json")

            def publish(value):
                try:
                    pt_bench.write_record(path, {"value": value})
                    return True
                except FileExistsError:
                    return False

            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(publish, range(8)))
            self.assertEqual(sum(outcomes), 1)
            self.assertIn(json.loads(Path(path).read_text())["value"], range(8))
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
