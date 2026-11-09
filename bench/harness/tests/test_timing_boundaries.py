"""Known-delay checks for the exploratory outer timer, not performance tests."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, wait
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "pt_bench_boundaries", Path(__file__).resolve().parents[1] / "pt_bench.py"
)
timer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timer)


DELAY_SECONDS = 0.15
STAGES = ("collection", "teardown", "reporting", "coverage_merge", "coverage_report", "cleanup")
PROBE = Path(__file__).parent / "fixtures" / "timing_probe.py"


class ObservedBoundaryTests(unittest.TestCase):
    """The parent observes a blocked stage, then releases it after a known wait.

    Only parent/harness monotonic readings are compared. Child timestamps and
    pytest's own durations are not timing authorities, and startup cannot stand
    in for the observed stage. These are correctness-instrumented fixtures.
    """

    def await_ready(self, future, ready):
        deadline = time.monotonic() + 15
        while not ready():
            if future.done():
                self.fail(f"command returned without reaching the stage: {future.result()}")
            if time.monotonic() >= deadline:
                self.fail("stage did not become ready")
            time.sleep(0.005)

    def hold_and_release(self, future, ready, release, before_release=None):
        try:
            self.await_ready(future, ready)
            if before_release is not None:
                before_release()
            opened = time.monotonic_ns()
            done, _ = wait([future], timeout=DELAY_SECONDS)
            if done:
                future.result()  # Preserve a worker exception rather than disguising it.
                self.fail("command returned before stage release")
            released = time.monotonic_ns()
            self.assertGreaterEqual(released - opened, 120_000_000)
            return opened, released
        finally:
            # Always unblock the fixture, including when an assertion fails.
            release()

    def observe(self, operation, ready, release, before_release=None):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(operation)
            window = self.hold_and_release(future, ready, release, before_release)
            return future.result(timeout=20), window

    def assert_covers_stage(self, result, window):
        opened, released = window
        self.assertEqual(result["clock_domain"], "harness_process_monotonic")
        self.assertEqual(result["elapsed_ns"],
                         result["monotonic_end_ns"] - result["monotonic_start_ns"])
        self.assertLessEqual(result["monotonic_start_ns"], opened, "timer started after stage")
        self.assertGreaterEqual(result["monotonic_end_ns"], released, "timer ended before release")
        self.assertGreaterEqual(result["elapsed_ns"], released - opened)

    def assert_process_completed(self, result):
        self.assertEqual(result["status"], "exited_unqualified")
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["output_complete"])
        self.assertTrue(result["process_reaped"])


@unittest.skipUnless(sys.version_info >= (3, 11), "coverage fixture requires Python >= 3.11")
class PytestStageBoundaryTests(ObservedBoundaryTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def measure_probe(self, stage, mode="wait"):
        result = timer.measure(
            [sys.executable, str(PROBE), str(self.root), stage, mode], str(self.root), 20,
        )
        failure = self.root / "failure.txt"
        self.assertFalse(failure.exists(), failure.read_text() if failure.exists() else "")
        return result

    def assert_completion_evidence(self, result):
        self.assert_process_completed(result)
        expected = ["collection:begin", "collection:end", "setup", "call",
                    "teardown:begin", "fixture-finalized", "teardown:end"]
        for stage in STAGES[2:]:
            expected += [f"{stage}:begin", f"{stage}:end"]
        self.assertEqual((self.root / "events.txt").read_text().splitlines(), expected)
        report = json.loads((self.root / "pytest-report.json").read_text())
        self.assertEqual(report, {
            "exitstatus": 0, "collected": ["test_work.py::test_work"],
            "reports": [{"nodeid": "test_work.py::test_work", "phase": phase, "outcome": "passed"}
                        for phase in ("setup", "call", "teardown")],
        })
        report = json.loads((self.root / "coverage.json").read_text())
        self.assertEqual(report["meta"]["version"], "7.17.2")
        self.assertFalse(report["meta"]["branch_coverage"])
        self.assertEqual(list(report["files"]), ["payload.py"])
        self.assertEqual(report["files"]["payload.py"]["executed_lines"], [1, 2, 4, 5])
        self.assertEqual(report["files"]["payload.py"]["missing_lines"], [])
        self.assertTrue((self.root / ".coverage").is_file())
        self.assertEqual(list(self.root.glob(".coverage.*")), [])
        self.assertFalse((self.root / "lease").exists(), "required lease was not released")
        self.assertEqual(json.loads((self.root / "cleanup.json").read_text()), {"released": True})

    def check_stage(self, stage):
        def before_release():
            events = (self.root / "events.txt").read_text().splitlines()
            self.assertEqual(events[-1], f"{stage}:begin")
            absent = {"collection": "lease", "teardown": "pytest-report.json",
                      "reporting": "pytest-report.json", "coverage_merge": ".coverage",
                      "coverage_report": "coverage.json", "cleanup": "cleanup.json"}
            self.assertFalse((self.root / absent[stage]).exists())
            if stage in ("teardown", "cleanup"):
                self.assertTrue((self.root / "lease").is_file())
            if stage == "coverage_merge":
                self.assertEqual(sorted(path.name for path in self.root.glob(".coverage.*")),
                                 [".coverage.companion", ".coverage.pytest"])

        result, window = self.observe(
            lambda: self.measure_probe(stage), (self.root / "ready").exists,
            (self.root / "release").touch, before_release,
        )
        self.assert_completion_evidence(result)
        self.assert_covers_stage(result, window)
        # A broken timer can still wait for all artifacts but record an early
        # endpoint. Reject it using the observed stage, not an elapsed threshold.
        early = {**result, "monotonic_end_ns": window[0],
                 "elapsed_ns": window[0] - result["monotonic_start_ns"]}
        with self.assertRaisesRegex(AssertionError, "timer ended before release"):
            self.assert_covers_stage(early, window)

    def test_real_pytest_collection_is_inside_timer(self):
        self.check_stage("collection")

    def test_real_pytest_fixture_teardown_is_inside_timer(self):
        self.check_stage("teardown")

    def test_test_owned_pytest_report_is_inside_timer(self):
        self.check_stage("reporting")

    def test_real_coverage_combine_and_save_are_inside_timer(self):
        self.check_stage("coverage_merge")

    def test_real_coverage_json_report_is_inside_timer(self):
        self.check_stage("coverage_report")

    def test_cooperative_required_resource_release_is_inside_timer(self):
        self.check_stage("cleanup")

    def test_omitting_delay_is_detected_even_with_complete_artifacts(self):
        for stage in STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.measure_probe, stage, "omit-delay")
                    result = future.result(timeout=20)
                    self.assert_completion_evidence(result)
                    self.assertEqual((self.root / "ready").read_text(), stage)
                    self.assertFalse((self.root / "release").exists())
                    with self.assertRaisesRegex(AssertionError, "returned before stage release"):
                        self.hold_and_release(future, (self.root / "ready").exists,
                                              (self.root / "release").touch)

    def test_zero_exit_and_complete_reports_do_not_prove_required_cleanup(self):
        result, window = self.observe(
            lambda: self.measure_probe("cleanup", "omit-cleanup"),
            (self.root / "ready").exists, (self.root / "release").touch,
        )
        self.assert_process_completed(result)
        self.assert_covers_stage(result, window)
        with self.assertRaisesRegex(AssertionError, "required lease was not released"):
            self.assert_completion_evidence(result)


class HarnessPublicationBoundaryTests(ObservedBoundaryTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entered = threading.Event()
        self.release = threading.Event()

    def pause(self):
        self.entered.set()
        if not self.release.wait(timeout=15):
            raise RuntimeError("parent did not release publication stage")

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "O_NOFOLLOW"),
                         "requires Linux native blob publication")
    def test_raw_blob_publication_and_spool_cleanup_are_inside_timer(self):
        sys.path.insert(0, str(PROBE.parents[2]))
        self.addCleanup(sys.path.pop, 0)
        import raw_capture
        for stage in ("publish", "__exit__"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory)
                self.entered.clear()
                self.release.clear()
                original = getattr(raw_capture.RawCapture, stage)
                instances = []

                def delayed(instance, *args):
                    instances.append(instance)
                    self.pause()
                    return original(instance, *args)

                with mock.patch.object(raw_capture.RawCapture, stage, delayed):
                    result, window = self.observe(
                        lambda: timer.measure([sys.executable, "-c", "print('bytes')"],
                                              str(self.root), 5, raw_bundle=bundle),
                        self.entered.is_set, self.release.set,
                    )
                self.assert_process_completed(result)
                self.assert_covers_stage(result, window)
                self.assertEqual(len(instances), 1)
                self.assertTrue(all(spool.closed for spool in instances[0].files.values()))
                for name, expected in (("stdout", b"bytes\n"), ("stderr", b"")):
                    item = result["raw_capture"][name]
                    self.assertFalse(item["truncated"])
                    self.assertEqual((bundle / item["sha256"]).read_bytes(), expected)
                    self.assertEqual(item["sha256"], hashlib.sha256(expected).hexdigest())

    def test_sample_json_publication_remains_outside_reported_elapsed_time(self):
        destination = self.root / "sample.json"
        original = timer.write_record
        measured = []

        def delayed(path, record):
            measured.append(record["result"])
            self.pause()
            original(path, record)

        argv = [str(PROBE.parents[2] / "pt_bench.py"), "--cwd", str(self.root),
                "--timeout", "5", "--output", str(destination), "--",
                sys.executable, "-c", "pass"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(timer, "write_record", delayed):
            status, window = self.observe(
                timer.main, self.entered.is_set, self.release.set,
                lambda: self.assertFalse(destination.exists()),
            )
        self.assertEqual(status, 0)
        result = json.loads(destination.read_text())["result"]
        self.assertEqual(result, measured[0])
        self.assert_process_completed(result)
        self.assertLess(result["monotonic_end_ns"], window[0])
        with self.assertRaisesRegex(AssertionError, "timer ended before release"):
            self.assert_covers_stage(result, window)


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
