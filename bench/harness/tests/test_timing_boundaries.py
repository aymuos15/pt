"""Known-delay checks for the exploratory outer timer, not performance tests."""

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest


spec = importlib.util.spec_from_file_location(
    "pt_bench_boundaries", Path(__file__).resolve().parents[1] / "pt_bench.py"
)
timer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timer)


class TimerBoundaryTests(unittest.TestCase):
    def assert_completed_after_delay(self, result, minimum_ns):
        self.assertEqual(result["status"], "exited_unqualified")
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["output_complete"])
        self.assertTrue(result["process_reaped"])
        self.assertGreaterEqual(result["elapsed_ns"], minimum_ns)

    def test_delay_before_first_output_is_inside_timer(self):
        result = timer.measure([sys.executable, "-c",
                                "import time; time.sleep(0.15); print('ready')"], ".", 5)
        self.assert_completed_after_delay(result, 120_000_000)
        self.assertEqual(result["stdout_sha256"], hashlib.sha256(b"ready\n").hexdigest())

    def test_shutdown_after_output_is_inside_timer(self):
        program = "import atexit,time; atexit.register(time.sleep,0.15); print('ready',flush=True)"
        result = timer.measure([sys.executable, "-c", program], ".", 5)
        self.assert_completed_after_delay(result, 120_000_000)
        self.assertEqual(result["stdout_bytes"], len(b"ready\n"))

    def test_process_exit_is_awaited_after_pipes_close(self):
        program = "import os,time; os.close(1); os.close(2); time.sleep(0.15)"
        result = timer.measure([sys.executable, "-c", program], ".", 5)
        self.assert_completed_after_delay(result, 120_000_000)

    @unittest.skipUnless(os.name == "posix", "requires POSIX fork and pipe behavior")
    def test_inherited_pipe_drain_is_inside_timer(self):
        program = (
            "import os,time; pid=os.fork(); "
            "(time.sleep(0.15), os.write(1,b'child'), os._exit(0)) if pid == 0 else os._exit(0)"
        )
        result = timer.measure([sys.executable, "-c", program], ".", 5)
        self.assert_completed_after_delay(result, 120_000_000)
        self.assertEqual(result["stdout_bytes"], len(b"child"))
        self.assertEqual(result["stdout_sha256"], hashlib.sha256(b"child").hexdigest())


if __name__ == "__main__":
    unittest.main()
