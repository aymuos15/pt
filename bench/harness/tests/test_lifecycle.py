from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from test_timing_boundaries import ObservedBoundaryTests


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import finalization
    import raw_capture
    spec = importlib.util.spec_from_file_location("lifecycle_timer_test", HARNESS / "pt_bench.py")
    timer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timer)
finally:
    sys.path.pop(0)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "publication-inclusive POSIX endpoint")
class LifecycleTests(ObservedBoundaryTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = self.root / "sample.json"
        self.payload = b'{"report":"final"}\n'
        self.contract = {"expected_exit_code": 0, "artifacts": [
            {"path": "report.json", "bytes": len(self.payload), "sha256": hashlib.sha256(self.payload).hexdigest()}
        ], "absent": ["lease"]}
        self.command = [sys.executable, "-c", (
            "from pathlib import Path; Path('lease').touch(); "
            f"Path('report.json').write_bytes({self.payload!r}); Path('lease').unlink()"
        )]
        self.entered = threading.Event()
        self.release = threading.Event()

    def invoke(self, **kwargs):
        return timer.measure_and_publish(self.command, str(self.root), 5, self.sample,
                                         required_finalization=self.contract, **kwargs)

    def pause(self):
        self.entered.set()
        if not self.release.wait(timeout=15):
            raise RuntimeError("parent did not release lifecycle stage")

    def assert_finalized(self, receipt):
        self.assertEqual(receipt["lifecycle"]["status"], "finalized_unqualified")
        self.assertFalse(receipt["confirmatory_eligible"])
        self.assertEqual(receipt["errors"], [])
        self.assertTrue(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"])
        record = json.loads(self.sample.read_text())
        self.assertNotIn("lifecycle", record)
        self.assertEqual(receipt["result"], record["result"])
        self.assertEqual(receipt["sample"]["sha256"], hashlib.sha256(self.sample.read_bytes()).hexdigest())
        self.assertLessEqual(receipt["lifecycle"]["monotonic_start_ns"], record["result"]["monotonic_start_ns"])
        self.assertGreaterEqual(receipt["lifecycle"]["monotonic_end_ns"], record["result"]["monotonic_end_ns"])

    def test_published_sample_and_receipt_bind_both_intervals_without_self_timestamp(self):
        self.assert_finalized(self.invoke())

    def test_known_delay_in_each_real_publication_step_is_inside_lifecycle(self):
        for stage in ("writer", "fsync", "link", "temporary_cleanup", "readback"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                self.entered.clear()
                self.release.clear()
                if stage == "writer":
                    owner, name = timer, "write_record"
                elif stage in ("fsync", "link"):
                    owner, name = timer.os, stage
                elif stage == "temporary_cleanup":
                    owner, name = Path, "unlink"
                else:
                    owner, name = finalization, "inspect_file"
                original = getattr(owner, name)

                def delayed(*args, **kwargs):
                    relevant = (stage not in ("temporary_cleanup", "readback")
                                or (stage == "temporary_cleanup" and args[0].name.startswith(".sample.json."))
                                or (stage == "readback" and args[1] == "sample.json"))
                    if relevant:
                        self.pause()
                    return original(*args, **kwargs)

                with mock.patch.object(owner, name, delayed):
                    receipt, window = self.observe(self.invoke, self.entered.is_set, self.release.set)
                self.assert_finalized(receipt)
                self.assert_covers_stage(receipt["lifecycle"], window)
                self.assertLess(receipt["result"]["monotonic_end_ns"], window[0])
                with self.assertRaisesRegex(AssertionError, "timer ended before release"):
                    self.assert_covers_stage(receipt["result"], window)

    def test_both_pre_and_post_publication_required_checks_are_inside_lifecycle(self):
        original = finalization.check
        for paused_call in (1, 2):
            with self.subTest(paused_call=paused_call), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                self.entered.clear()
                self.release.clear()
                calls = []

                def delayed(*args, **kwargs):
                    calls.append(True)
                    if len(calls) == paused_call:
                        self.pause()
                    return original(*args, **kwargs)

                def before_release():
                    self.assertEqual(self.sample.exists(), paused_call == 2)

                with mock.patch.object(finalization, "check", delayed):
                    receipt, window = self.observe(self.invoke, self.entered.is_set, self.release.set,
                                                   before_release)
                self.assert_finalized(receipt)
                self.assert_covers_stage(receipt["lifecycle"], window)

    def test_failed_serialization_fsync_link_and_temporary_cleanup_never_finalize(self):
        for stage in ("serialization", "fsync", "link", "temporary_cleanup"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                if stage == "serialization":
                    patcher = mock.patch.object(timer.json, "dump", side_effect=ValueError("injected serialization failure"))
                elif stage in ("fsync", "link"):
                    patcher = mock.patch.object(timer.os, stage, side_effect=OSError("injected publication failure"))
                else:
                    original = Path.unlink

                    def fail_cleanup(path, *args, **kwargs):
                        if path.name.startswith(".sample.json."):
                            raise OSError("injected temporary cleanup failure")
                        return original(path, *args, **kwargs)

                    patcher = mock.patch.object(Path, "unlink", fail_cleanup)
                with (patcher, mock.patch.object(timer, "_abort_process") as abort,
                      mock.patch.object(timer, "measure", wraps=timer.measure) as measured):
                    receipt = self.invoke()
                abort.assert_not_called()
                self.assertEqual(measured.call_count, 1, "publication failure must not replay command work")
                self.assertEqual(receipt["result"]["returncode"], 0)
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertIsNone(receipt["sample"])
                self.assertEqual(receipt["errors"][0]["stage"], "sample_publication")
                self.assertFalse(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"])
                self.assertEqual(self.sample.exists(), stage == "temporary_cleanup")

    def test_omitted_wrong_or_symlink_publication_is_rejected_by_readback(self):
        for mode in ("omit", "wrong", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"

                def broken_writer(path, record):
                    if mode == "wrong":
                        Path(path).write_text("{}")
                    elif mode == "symlink":
                        (self.root / "elsewhere").write_text("{}")
                        Path(path).symlink_to(self.root / "elsewhere")

                with mock.patch.object(timer, "write_record", broken_writer):
                    receipt = self.invoke()
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertIsNone(receipt["sample"])
                self.assertEqual(receipt["errors"][0]["stage"], "sample_publication")

    def test_existing_destination_prevents_work_and_racing_destination_is_not_adopted(self):
        self.sample.write_text("existing")
        with mock.patch.object(timer, "measure") as measure:
            with self.assertRaises(FileExistsError):
                self.invoke()
            measure.assert_not_called()
        self.sample.unlink()
        original = timer.write_record

        def race(path, record):
            Path(path).write_text("another caller")
            original(path, record)

        with mock.patch.object(timer, "write_record", race):
            receipt = self.invoke()
        self.assertEqual(self.sample.read_text(), "another caller")
        self.assertIsNone(receipt["sample"])
        self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")

    def test_required_report_missing_wrong_or_lease_unreleased_blocks_zero_exit(self):
        for program in ("pass", "from pathlib import Path; Path('report.json').write_bytes(b'wrong')",
                        f"from pathlib import Path; Path('report.json').write_bytes({self.payload!r}); Path('lease').touch()"):
            with self.subTest(program=program), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                self.command = [sys.executable, "-c", program]
                receipt = self.invoke()
                self.assertEqual(receipt["result"]["returncode"], 0)
                self.assertIsNotNone(receipt["sample"], "retain the failed observation")
                self.assertFalse(receipt["required_finalization"]["after_publication"]["matched"])
                self.assertFalse(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"])

    def test_artifact_or_cleanup_changes_during_publication_are_not_retried_away(self):
        for change in ("contents", "same_bytes_replacement", "lease"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                original = timer.write_record

                def mutate(path, record):
                    original(path, record)
                    if change == "contents":
                        (self.root / "report.json").write_bytes(b"wrong")
                    elif change == "same_bytes_replacement":
                        replacement = self.root / "replacement"
                        replacement.write_bytes(self.payload)
                        replacement.replace(self.root / "report.json")
                    else:
                        (self.root / "lease").touch()

                with mock.patch.object(timer, "write_record", mutate):
                    receipt = self.invoke()
                self.assertTrue(receipt["required_finalization"]["before_publication"]["matched"])
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertEqual(receipt["errors"][-1]["stage"], "required_finalization")
                self.assertFalse(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"])

    def test_sample_changed_during_post_publication_checks_cannot_finalize(self):
        original = finalization.check
        calls = []

        def mutate(*args, **kwargs):
            verdict = original(*args, **kwargs)
            calls.append(True)
            if len(calls) == 2:
                self.sample.write_text("{}")
            return verdict

        with mock.patch.object(finalization, "check", mutate):
            receipt = self.invoke()
        self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
        self.assertEqual(receipt["errors"][-1]["stage"], "sample_publication")
        with self.assertRaisesRegex(ValueError, "sample does not match"):
            timer.inspect_lifecycle(self.sample, receipt)

    def test_timeout_launch_error_and_incomplete_process_observations_remain_failures(self):
        cases = (([sys.executable, "-c", "import time; time.sleep(5)"], 0.05, "timeout"),
                 (["/nonexistent/pt-lifecycle-command"], 1, "launch_error"))
        for command, timeout, status in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "sample.json"
                receipt = timer.measure_and_publish(command, str(self.root), timeout, output)
                self.assertEqual(receipt["result"]["status"], status)
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertIsNotNone(receipt["sample"])
                self.assertFalse(timer.inspect_lifecycle(output, receipt)["lifecycle_finalized"])
        observed = timer.measure([sys.executable, "-c", "pass"], str(self.root), 5)
        for field in ("process_reaped", "output_complete"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(timer, "measure", return_value={**observed, field: False}):
                    receipt = timer.measure_and_publish(self.command, str(self.root), 5,
                                                        Path(directory) / "sample.json")
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")

    def test_expected_nonzero_exit_can_finalize_but_wrong_exit_cannot(self):
        self.contract = {"expected_exit_code": 7, "artifacts": [], "absent": []}
        self.command = [sys.executable, "-c", "raise SystemExit(7)"]
        self.assert_finalized(self.invoke())
        self.sample.unlink()
        self.contract["expected_exit_code"] = 0
        receipt = self.invoke()
        self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
        self.assertEqual(receipt["result"]["returncode"], 7)

    @unittest.skipUnless(sys.platform == "linux", "Linux native blob publication")
    def test_raw_capture_is_verified_and_publication_failure_is_not_success(self):
        bundle = self.root / "blobs"
        bundle.mkdir()
        self.command = [sys.executable, "-c", "print('bytes')"]
        self.contract = {"expected_exit_code": 0, "artifacts": [], "absent": []}
        receipt = self.invoke(raw_bundle=bundle)
        self.assert_finalized(receipt)
        item = receipt["result"]["raw_capture"]["stdout"]
        (bundle / item["sha256"]).write_bytes(b"wrong\n")
        with self.assertRaisesRegex(ValueError, "finalization evidence"):
            timer.inspect_lifecycle(self.sample, receipt)
        self.sample.unlink()
        with mock.patch.object(raw_capture.RawCapture, "publish", side_effect=OSError("injected blob failure")):
            receipt = self.invoke(raw_bundle=bundle)
        self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
        self.assertIsNone(receipt["result"])
        self.assertFalse(self.sample.exists())
        self.assertEqual(receipt["errors"][0]["stage"], "measurement")
        self.assertFalse(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"])

    def test_post_commit_inspection_rejects_tampering_missing_artifacts_and_incomplete_receipts(self):
        receipt = self.invoke()
        for field, value in (("elapsed_ns", True), ("elapsed_ns", 1), ("clock_domain", "child_clock"),
                             ("endpoint", "execution_only"), ("status", "qualified")):
            changed = copy.deepcopy(receipt)
            changed["lifecycle"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                timer.inspect_lifecycle(self.sample, changed)
        for field in ("sample", "required_finalization", "lifecycle", "errors"):
            changed = copy.deepcopy(receipt)
            del changed[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                timer.inspect_lifecycle(self.sample, changed)
        changed = copy.deepcopy(receipt)
        changed["sample"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "sample does not match"):
            timer.inspect_lifecycle(self.sample, changed)
        (self.root / "report.json").unlink()
        with self.assertRaisesRegex(ValueError, "finalization evidence"):
            timer.inspect_lifecycle(self.sample, receipt)
        self.sample.write_text("{}")
        with self.assertRaisesRegex(ValueError, "sample does not match"):
            timer.inspect_lifecycle(self.sample, receipt)

    def test_type_ambiguous_json_evidence_is_not_equal_to_typed_observations(self):
        receipt = self.invoke()
        original_bytes = self.sample.read_bytes()
        ambiguous = copy.deepcopy(receipt)
        ambiguous["required_finalization"]["before_publication"]["matched"] = 1
        ambiguous["required_finalization"]["after_publication"]["matched"] = 1
        with self.subTest(mutation="integer_instead_of_boolean"), self.assertRaises(ValueError):
            timer.inspect_lifecycle(self.sample, ambiguous)
        record = json.loads(original_bytes)
        record["schema_version"] = True
        self.sample.write_text(json.dumps(record))
        ambiguous = copy.deepcopy(receipt)
        ambiguous["sample"].update(bytes=self.sample.stat().st_size,
                                  sha256=hashlib.sha256(self.sample.read_bytes()).hexdigest())
        with self.subTest(mutation="boolean_instead_of_integer"), self.assertRaises(ValueError):
            timer.inspect_lifecycle(self.sample, ambiguous)

    @unittest.skipUnless(sys.version_info >= (3, 11), "coverage-backed fixture needs Python >= 3.11")
    def test_real_pytest_report_and_cooperative_cleanup_use_the_new_validation_path(self):
        expected_report = {"exitstatus": 0, "collected": ["test_work.py::test_work"],
                           "reports": [{"nodeid": "test_work.py::test_work", "phase": phase, "outcome": "passed"}
                                       for phase in ("setup", "call", "teardown")]}
        self.payload = json.dumps(expected_report).encode()
        self.contract["artifacts"] = [{"path": "pytest-report.json", "bytes": len(self.payload),
                                       "sha256": hashlib.sha256(self.payload).hexdigest()}]
        probe = HARNESS / "tests/fixtures/timing_probe.py"
        for mode, target, matched in (("omit-delay", "collection", True), ("omit-cleanup", "unused", False)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                self.command = [sys.executable, str(probe), str(self.root), target, mode]
                receipt = self.invoke()
                self.assertEqual(receipt["result"]["returncode"], 0)
                self.assertEqual(timer.inspect_lifecycle(self.sample, receipt)["lifecycle_finalized"], matched)

    def test_cli_emits_receipt_and_checker_requires_both_new_artifacts(self):
        args = [sys.executable, str(HARNESS / "pt_bench.py"), "--cwd", str(self.root), "--timeout", "5",
                "--output", str(self.sample), "--finalization-json", json.dumps(self.contract), "--", *self.command]
        completed = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt_path = self.root / "receipt.json"
        receipt_path.write_text(completed.stdout)
        check = [sys.executable, str(HARNESS / "inspect_lifecycle.py"), "--sample", str(self.sample),
                 "--receipt", str(receipt_path)]
        inspected = subprocess.run(check, capture_output=True, text=True, timeout=15)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertFalse(json.loads(inspected.stdout)["confirmatory_eligible"])
        receipt_path.write_text(completed.stdout[:-10])
        self.assertEqual(subprocess.run(check, capture_output=True, timeout=15).returncode, 2)
        receipt_path.unlink()
        self.assertEqual(subprocess.run(check, capture_output=True, timeout=15).returncode, 2)

    def test_cli_reports_required_check_and_publication_failures_nonzero_with_evidence(self):
        for mode in ("required_check", "publication"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.sample = self.root / "sample.json"
                command = [sys.executable, "-c", "pass"] if mode == "required_check" else self.command
                argv = ["pt-bench", "--cwd", str(self.root), "--timeout", "5", "--output", str(self.sample),
                        "--finalization-json", json.dumps(self.contract), "--", *command]
                captured = io.StringIO()
                original = timer.write_record

                def writer(*args, **kwargs):
                    if mode == "publication":
                        raise OSError("injected writer failure")
                    return original(*args, **kwargs)

                with (mock.patch.object(sys, "argv", argv), mock.patch.object(timer, "write_record", writer),
                      redirect_stdout(captured)):
                    status = timer.main()
                self.assertEqual(status, 1 if mode == "required_check" else 2)
                receipt = json.loads(captured.getvalue())
                self.assertEqual(receipt["result"]["returncode"], 0)
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertEqual(self.sample.exists(), mode == "required_check")

    def test_interruption_after_commit_is_unconfirmed_and_never_replays_work(self):
        original = timer.write_record

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt()

        with (mock.patch.object(timer, "write_record", interrupted),
              mock.patch.object(timer, "measure", wraps=timer.measure) as measured,
              mock.patch.object(timer, "_abort_process") as abort):
            with self.assertRaises(KeyboardInterrupt):
                self.invoke()
        self.assertEqual(measured.call_count, 1)
        abort.assert_not_called()
        self.assertTrue(self.sample.is_file())
        self.assertNotIn("lifecycle", json.loads(self.sample.read_text()))

    def test_invalid_contract_is_rejected_before_execution(self):
        with mock.patch.object(timer, "measure") as measure:
            with self.assertRaises(ValueError):
                timer.measure_and_publish(self.command, str(self.root), 5, self.sample,
                                          required_finalization={"claimed_pass": True})
            measure.assert_not_called()
        for raw in ('{"expected_exit_code":0,"artifacts":[],"absent":[],"absent":["lease"]}',
                    '{"expected_exit_code":NaN,"artifacts":[],"absent":[]}'):
            argv = ["pt-bench", "--cwd", str(self.root), "--timeout", "5", "--output", str(self.sample),
                    "--finalization-json", raw, "--", *self.command]
            with (self.subTest(raw=raw), mock.patch.object(sys, "argv", argv),
                  mock.patch.object(timer, "measure") as measured, redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit) as stopped:
                    timer.main()
                self.assertEqual(stopped.exception.code, 2)
                measured.assert_not_called()

    def test_stdout_receipt_failure_is_nonzero_and_does_not_rewrite_sample(self):
        argv = ["pt-bench", "--cwd", str(self.root), "--timeout", "5", "--output", str(self.sample),
                "--", *self.command]
        stream = mock.Mock()
        stream.write.side_effect = BrokenPipeError("receipt consumer closed")
        captured_error = io.StringIO()
        with mock.patch.object(sys, "argv", argv), redirect_stdout(stream), redirect_stderr(captured_error):
            with self.assertRaises(SystemExit) as stopped:
                timer.main()
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("receipt consumer closed", captured_error.getvalue())
        self.assertTrue(self.sample.is_file())
        self.assertNotIn("lifecycle", json.loads(self.sample.read_text()))
