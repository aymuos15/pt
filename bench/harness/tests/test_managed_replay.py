"""Managed-session boundary/fault controls; never conformance or performance samples."""

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_timing_boundaries import ObservedBoundaryTests


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import analysis
    import blob_store
    import raw_capture
    import managed_replay as replay
    import pt_bench as timer
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux lifecycle/blob replay profile")
class ManagedReplayTests(ObservedBoundaryTests):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.output = self.root / "run"
        self.probe = HARNESS / "tests/fixtures/replay_probe.py"
        self.digest = hashlib.sha256(b"ready\n").hexdigest()
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": self.digest}
        self.plan = {"schema_version": 1, "kind": "managed_session_replay_plan", "mode": "exploratory_unqualified",
                     "sample_unit": replay.UNIT, "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT,
                     "scope": "fresh_serial_commands_with_declared_state", "cwd": str(self.cwd), "execution_timeout_seconds": 20,
                     "preparation": self.step("preparation", "preparation"),
                     "interactions": [self.step("interaction", "first"), self.step("interaction", "second")],
                     "shutdown": self.step("shutdown", "shutdown"),
                     "finalization": {"expected_exit_code": None, "artifacts": [self.artifact("report-shutdown")], "absent": ["lease"]},
                     "capture_raw": False, "raw_limit_bytes": 1024}

    def artifact(self, path):
        return {"path": path, "bytes": 6, "sha256": self.digest}

    def step(self, role, name, mode="normal"):
        return {"id": name, "argv": [sys.executable, str(self.probe), str(self.cwd), role, name, mode],
                "timeout_seconds": 5, "idle_before_seconds": 0, "guard_expectations": copy.deepcopy(self.guard),
                "required_finalization": {"expected_exit_code": 0, "artifacts": [self.artifact(f"report-{name}")],
                                          "absent": ["lease"] if role == "shutdown" else []}}

    def run_replay(self):
        self.receipt = replay.run_replay(self.output, self.plan)
        return self.receipt

    def sample(self):
        return json.loads((self.output / "unit.json").read_text())

    def summary(self):
        result = replay.inspect_replay(self.output, self.receipt)
        self.assertFalse(result["confirmatory_eligible"])
        self.assertIsNone(result["verified_independent_units"])
        self.assertEqual(result["observed_session_count"], 1)
        self.assertEqual(sum(result["interaction_status_counts"].values()), 2)
        self.assertEqual(sum(result["phase_status_counts"].values()), 4)
        self.assertEqual(sum(result[key] for key in ("known_phase_invocation_attempts", "unknown_phase_invocations", "known_not_invoked_phases")), 4)
        self.assertIsNone(result["ratio"])
        self.assertIsNone(result["bootstrap"])
        self.assertFalse(result["whole_boundary_resource_accounting_complete"])
        return result

    def begins(self):
        return [line.split(":")[0] for line in (self.cwd / "events").read_text().splitlines() if ":begin:" in line]

    def rebind(self, sample):
        raw = (json.dumps(sample) + "\n").encode()
        (self.output / "unit.json").write_bytes(raw)
        self.receipt["sample"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def test_whole_session_is_one_bound_unit_with_fresh_ordered_processes_and_shutdown(self):
        self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "completed_unqualified")
        self.assertEqual(self.begins(), ["preparation", "first", "second", "shutdown"])
        self.assertEqual((self.cwd / "state").read_text(), "2")
        pids = [line.rsplit(":", 1)[1] for line in (self.cwd / "events").read_text().splitlines() if ":begin:" in line]
        self.assertEqual(len(set(pids)), 4)
        self.assertFalse((self.cwd / "lease").exists())
        self.assertEqual(self.receipt["sample"]["sha256"], hashlib.sha256((self.output / "unit.json").read_bytes()).hexdigest())
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def check_boundary(self, role, position):
        step = self.plan[role] if role != "interactions" else self.plan[role][0]
        step["argv"][-1] = "wait"
        name = step["id"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run_replay)
            window = self.hold_and_release(future, (self.cwd / f"{name}.entered").exists,
                                           (self.cwd / f"{name}.release").touch)
            future.result(timeout=20)
        self.assert_covers_stage(self.receipt["clock"], window)
        self.assert_covers_stage(self.sample()["steps"][position]["clock"], window)
        self.assertEqual(self.summary()["status"], "completed_unqualified")

    def test_preparation_is_inside_whole_session_endpoint(self):
        self.check_boundary("preparation", 0)

    def test_interaction_is_inside_whole_session_endpoint(self):
        self.check_boundary("interactions", 1)

    def test_required_shutdown_is_inside_whole_session_endpoint(self):
        self.check_boundary("shutdown", 3)

    def test_idle_is_charged_once_without_becoming_an_independent_observation(self):
        self.plan["interactions"][0]["idle_before_seconds"] = 0.15
        self.run_replay()
        row = self.sample()["steps"][1]
        self.assertGreaterEqual(row["idle_clock"]["elapsed_ns"], 150_000_000)
        self.assertGreaterEqual(self.receipt["clock"]["elapsed_ns"], row["clock"]["elapsed_ns"])
        self.assertEqual(self.summary()["observed_session_count"], 1)
        sample = self.sample()
        sample["steps"][1]["idle_clock"]["monotonic_end_ns"] = sample["steps"][1]["idle_clock"]["monotonic_start_ns"]
        sample["steps"][1]["idle_clock"]["elapsed_ns"] = 0
        self.rebind(sample)
        with self.assertRaisesRegex(ValueError, "omitted a requested idle"):
            replay.inspect_replay(self.output, self.receipt)

    def test_unit_publication_and_reporting_are_inside_endpoint_and_receipt_transport_is_outside(self):
        entered, release = self.root / "publish.entered", self.root / "publish.release"
        original = timer.write_record

        def hold(path, value):
            if Path(path).name == "unit.json":
                entered.touch()
                deadline = time.monotonic() + 15
                while not release.exists():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("parent did not release unit publication")
                    time.sleep(0.005)
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=hold):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.run_replay)
                window = self.hold_and_release(future, entered.exists, release.touch)
                future.result(timeout=20)
        self.assert_covers_stage(self.receipt["clock"], window)
        self.assert_covers_stage(self.receipt["unit_publication_clock"], window)
        early = copy.deepcopy(self.receipt)
        early["clock"].update(monotonic_end_ns=window[0], elapsed_ns=window[0] - early["clock"]["monotonic_start_ns"])
        with self.assertRaisesRegex(ValueError, "outside its session"):
            replay.inspect_replay(self.output, early)

    def test_api_validation_and_plan_publication_delays_are_inside_session_clock(self):
        for stage in ("validation", "plan_publication"):
            self.output = self.root / stage
            entered, release = threading.Event(), threading.Event()
            original = replay.validate_plan if stage == "validation" else timer.write_record

            def hold(*args, **kwargs):
                if stage == "validation" or Path(args[0]).name == "plan.json":
                    entered.set()
                    if not release.wait(timeout=15):
                        raise RuntimeError("parent did not release plan setup")
                return original(*args, **kwargs)

            target = mock.patch.object(replay, "validate_plan", side_effect=hold) if stage == "validation" else mock.patch.object(timer, "write_record", side_effect=hold)
            with target, ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.run_replay)
                window = self.hold_and_release(future, entered.is_set, release.set)
                future.result(timeout=20)
            self.assert_covers_stage(self.receipt["clock"], window)
            if stage == "plan_publication":
                self.assert_covers_stage(self.receipt["plan_publication_clock"], window)
            self.assertEqual(self.summary()["status"], "completed_unqualified")

    def test_post_shutdown_archive_and_final_recheck_are_inside_endpoint(self):
        for stage in ("archive", "recheck"):
            self.output = self.root / stage
            entered, release = threading.Event(), threading.Event()
            original = replay.files.archive if stage == "archive" else replay._file_observation
            calls = []

            def hold(*args, **kwargs):
                if stage == "recheck":
                    calls.append(1)
                if (stage == "archive" and args[1]["scope"] == replay.FILE_SCOPE) or (stage == "recheck" and len(calls) == 2):
                    entered.set()
                    if not release.wait(timeout=15):
                        raise RuntimeError("parent did not release session finalization")
                return original(*args, **kwargs)

            target = mock.patch.object(replay.files, "archive", side_effect=hold) if stage == "archive" else mock.patch.object(replay, "_file_observation", side_effect=hold)
            with target, ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.run_replay)
                window = self.hold_and_release(future, entered.is_set, release.set)
                future.result(timeout=20)
            self.assert_covers_stage(self.receipt["clock"], window)
            clock = self.sample()["post_shutdown_clock"] if stage == "archive" else self.receipt["finalization_clock"]
            self.assert_covers_stage(clock, window)
            self.assertEqual(self.summary()["status"], "completed_unqualified")

    def test_failed_preparation_skips_every_interaction_but_runs_shutdown_once(self):
        self.plan["preparation"]["argv"][-1] = "fail"
        self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["interaction_status_counts"], {"not_run_prior_failure": 2})
        self.assertEqual(self.begins(), ["preparation", "shutdown"])
        self.assertFalse((self.cwd / "lease").exists())

    def test_failed_interaction_keeps_effects_without_retry_and_skips_remaining_work(self):
        self.plan["interactions"][0]["argv"][-1] = "fail"
        self.run_replay()
        self.assertEqual(self.summary()["interaction_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual(self.begins(), ["preparation", "first", "shutdown"])
        self.assertEqual((self.cwd / "state").read_text(), "1")

    def test_expected_nonzero_interaction_is_explicit_not_a_test_pass(self):
        step = self.plan["interactions"][0]
        step["argv"][-1] = "fail"
        step["guard_expectations"]["expected_exit_code"] = 7
        step["required_finalization"]["expected_exit_code"] = 7
        self.run_replay()
        self.assertEqual(self.summary()["status"], "completed_unqualified")
        self.assertEqual(self.sample()["steps"][1]["receipt"]["result"]["returncode"], 7)
        self.assertEqual(self.begins(), ["preparation", "first", "second", "shutdown"])

    def test_guard_mismatch_is_retained_and_cannot_be_repaired_by_shutdown(self):
        self.plan["interactions"][0]["guard_expectations"]["expected_stdout_sha256"] = "0" * 64
        self.run_replay()
        self.assertEqual(self.summary()["status"], "aborted")
        self.assertEqual(self.begins(), ["preparation", "first", "shutdown"])

    def test_timeout_and_launch_failure_still_attempt_shutdown_and_preserve_counts(self):
        for label in ("timeout", "launch"):
            self.output = self.root / label
            step = self.plan["interactions"][0]
            step["argv"] = [sys.executable, str(self.probe), str(self.cwd), "interaction", "first", "hang"] if label == "timeout" else ["/nonexistent/pt-replay-command"]
            step["timeout_seconds"] = 0.04
            self.run_replay()
            summary = self.summary()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["shutdown_status"], "observed_unqualified")
            self.assertEqual(self.sample()["steps"][1]["receipt"]["result"]["status"], "timeout" if label == "timeout" else "launch_error")
            self.assertFalse((self.cwd / "lease").exists())

    def test_execution_deadline_reserves_shutdown_budget_and_does_not_invoke_skipped_steps(self):
        self.plan["execution_timeout_seconds"] = 0.001
        original = replay.validate_plan

        def exhaust(plan):
            original(plan)
            time.sleep(0.01)  # Charge a real validation delay rather than relying on disk/host speed.

        with mock.patch.object(replay, "validate_plan", side_effect=exhaust):
            self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(self.begins(), ["shutdown"])
        self.assertEqual(self.sample()["steps"][0]["status"], "not_run_execution_deadline")
        self.assertEqual(self.sample()["steps"][-1]["effective_timeout_seconds"], 5)

    def test_step_timeout_is_clamped_to_remaining_execution_budget_not_shutdown_reserve(self):
        self.plan["execution_timeout_seconds"] = 2
        self.run_replay()
        self.assertEqual(self.summary()["status"], "completed_unqualified")
        steps = self.sample()["steps"]
        for row in steps[:-1]:
            self.assertGreater(row["effective_timeout_seconds"], 0)
            self.assertLess(row["effective_timeout_seconds"], 2)
        self.assertEqual(steps[-1]["effective_timeout_seconds"], 5)

    def test_shutdown_failure_and_unreleased_marker_cannot_be_success_even_with_matching_stdout(self):
        for mode in ("fail", "unreleased"):
            self.output = self.root / f"shutdown-{mode}"
            self.plan["shutdown"]["argv"][-1] = mode
            self.run_replay()
            summary = self.summary()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["shutdown_status"], "failed")
            receipt = self.sample()["steps"][-1]["receipt"]
            self.assertEqual(receipt["result"]["stdout_sha256"], self.digest)
            self.assertEqual(receipt["observation_guard"]["matched_expected_observations"], mode == "unreleased")

    def test_observer_exception_and_interruption_keep_invocation_unknown_and_run_cleanup_once(self):
        original = timer.measure_and_publish
        for error in (OSError("injected observer failure"), KeyboardInterrupt("injected cancellation"), RuntimeError("injected harness error")):
            self.output = self.root / type(error).__name__

            def fail(*args, **kwargs):
                if Path(args[3]).name == "step-0002.json":
                    raise error
                return original(*args, **kwargs)

            with mock.patch.object(timer, "measure_and_publish", side_effect=fail) as measured:
                self.run_replay()
                self.assertEqual(measured.call_count, 3)
            summary = self.summary()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["unknown_phase_invocations"], 1)
            self.assertEqual(summary["known_not_invoked_phases"], 1)
            self.assertFalse((self.cwd / "lease").exists())

    def test_idle_cancellation_and_error_do_not_invent_command_attempts(self):
        self.plan["interactions"][0]["idle_before_seconds"] = 0.1
        for error in (KeyboardInterrupt("injected idle cancellation"), OSError("injected idle error")):
            self.output = self.root / type(error).__name__
            with mock.patch.object(replay.time, "sleep", side_effect=error):
                self.run_replay()
            summary = self.summary()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["known_phase_invocation_attempts"], 2)
            self.assertEqual(summary["unknown_phase_invocations"], 0)
            self.assertEqual(summary["known_not_invoked_phases"], 2)
            self.assertEqual(summary["shutdown_status"], "observed_unqualified")

    def test_validation_cancellation_after_return_preserves_known_attempt_and_skips_later_work(self):
        original = timer.inspect_lifecycle
        for error in (KeyboardInterrupt("injected validation cancellation"), RuntimeError("injected validation failure")):
            self.output = self.root / type(error).__name__

            def fail(path, *args, **kwargs):
                if Path(path).name == "step-0002.json":
                    raise error
                return original(path, *args, **kwargs)

            with mock.patch.object(timer, "inspect_lifecycle", side_effect=fail):
                self.run_replay()
            summary = self.summary()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["known_phase_invocation_attempts"], 3)
            self.assertEqual(summary["unknown_phase_invocations"], 0)
            self.assertEqual(self.sample()["steps"][1]["error"]["stage"], "step_validation")
            self.assertFalse((self.cwd / "lease").exists())

    def test_missing_return_after_step_commit_retains_fragment_not_independent_sample(self):
        original = timer.measure_and_publish
        self.plan["capture_raw"] = True

        def fail(*args, **kwargs):
            receipt = original(*args, **kwargs)
            if Path(args[3]).name == "step-0002.json":
                raise OSError("injected missing return after commit")
            return receipt

        with mock.patch.object(timer, "measure_and_publish", side_effect=fail):
            self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["unknown_phase_invocations"], 1)
        self.assertEqual(summary["unconfirmed_diagnostic_fragment_count"], 1)
        self.assertEqual(self.begins(), ["preparation", "first", "shutdown"])

    def test_shutdown_timeout_is_final_failure_not_an_automatic_retry(self):
        self.plan["shutdown"]["argv"][-1] = "hang"
        self.plan["shutdown"]["timeout_seconds"] = 0.1
        self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["shutdown_status"], "failed")
        self.assertEqual(self.sample()["steps"][-1]["receipt"]["result"]["status"], "timeout")
        self.assertIn("required_shutdown_not_completed", summary["outcome_reasons"])

    def test_unit_publication_failures_keep_completed_shutdown_and_only_valid_diagnostic_recovery(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong"):
            self.output = self.root / f"publication-{mode}"

            def fail(path, value):
                if Path(path).name == "unit.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode in ("error", "committed_then_error"):
                        raise OSError("injected unit publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                self.run_replay()
            self.assertFalse((self.cwd / "lease").exists())
            self.assertIsNone(self.receipt["sample"])
            self.assertIsNotNone(self.receipt["diagnostic_sample"])
            if mode == "wrong":
                with self.assertRaises(ValueError):
                    replay.inspect_replay(self.output, self.receipt)
            else:
                self.assertEqual(self.summary()["status"], "aborted")

    def test_step_publication_failure_cannot_skip_shutdown_or_approve_unconfirmed_step_fragments(self):
        original = timer.write_record

        def fail(path, value):
            if Path(path).name == "step-0002.json":
                Path(path).write_text("{}")
                return
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["unconfirmed_diagnostic_fragment_count"], 1)
        self.assertEqual(self.sample()["steps"][1]["status"], "failed")
        self.assertIsNone(self.sample()["steps"][1]["receipt"]["sample"])
        self.assertFalse((self.cwd / "lease").exists())

    def test_final_file_changes_during_unit_publication_are_retained_as_failure(self):
        original = timer.write_record

        def mutate(path, value):
            original(path, value)
            if Path(path).name == "unit.json":
                (self.cwd / "lease").touch()

        with mock.patch.object(timer, "write_record", side_effect=mutate):
            self.run_replay()
        self.assertEqual(self.summary()["status"], "aborted")
        self.assertTrue(any(item["stage"] == "finalization_recheck" for item in self.receipt["errors"]))

    def test_final_archive_error_retains_full_ledger_and_shutdown_without_fake_archive(self):
        original = replay.files.archive

        def fail(root, observed, bundle):
            if observed["scope"] == replay.FILE_SCOPE:
                raise RuntimeError("injected final archive failure")
            return original(root, observed, bundle)

        with mock.patch.object(replay.files, "archive", side_effect=fail):
            self.run_replay()
        self.assertEqual(self.summary()["status"], "aborted")
        self.assertIsNone(self.sample()["artifact_archive"])
        self.assertFalse((self.cwd / "lease").exists())

    def test_raw_prefix_limits_and_truncation_stay_visible_without_whole_output_claim(self):
        self.plan.update(capture_raw=True, raw_limit_bytes=4)
        self.run_replay()
        summary = self.summary()
        self.assertEqual(summary["status"], "completed_unqualified")
        self.assertEqual(summary["raw_capture_truncated_phase_count"], 4)
        for row in self.sample()["steps"]:
            capture = row["receipt"]["result"]["raw_capture"]
            self.assertTrue(capture["stdout"]["truncated"])
            self.assertEqual(capture["stdout"]["stored_bytes"], 4)
            self.assertFalse(capture["stderr"]["truncated"])

    def test_effective_timeouts_and_budget_timestamps_are_independently_checked(self):
        self.run_replay()
        original = self.sample()
        for mutation in ("timeout", "timestamp", "error_scope"):
            sample = copy.deepcopy(original)
            row = sample["steps"][1]
            if mutation == "timeout":
                row["effective_timeout_seconds"] = 4
            elif mutation == "timestamp":
                row["timeout_computed_at_ns"] = row["clock"]["monotonic_start_ns"] - 1
            else:
                sample["errors"] = [{"stage": "idle", "error": "wrong evidence scope"}]
            self.rebind(sample)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                replay.inspect_replay(self.output, self.receipt)

    def test_evidence_fingerprint_changes_during_inspection_are_not_retried_or_ignored(self):
        self.run_replay()
        original = replay.capture_run
        calls = []

        def changed(directory):
            content, identities = original(directory)
            calls.append(1)
            if len(calls) > 1:
                identities["unit.json"][-1] += 1  # Synthetic identity-only change; no native qualification claim.
            return content, identities

        with mock.patch.object(replay, "capture_run", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                replay.inspect_replay(self.output, self.receipt)

    def test_plan_mutation_stops_later_interactions_but_still_uses_original_shutdown(self):
        original = timer.measure_and_publish

        def mutate(*args, **kwargs):
            receipt = original(*args, **kwargs)
            if Path(args[3]).name == "step-0001.json":
                path = self.output / "plan.json"
                path.write_bytes(path.read_bytes() + b"\n")
            return receipt

        with mock.patch.object(timer, "measure_and_publish", side_effect=mutate):
            self.run_replay()
        self.assertEqual(self.begins(), ["preparation", "shutdown"])
        self.assertEqual(self.receipt["outcome"]["status"], "aborted")
        with self.assertRaisesRegex(ValueError, "plan byte binding"):
            replay.inspect_replay(self.output, self.receipt)

    def test_removed_reordered_or_falsely_skipped_phases_are_rejected_with_rebound_unit_bytes(self):
        self.run_replay()
        original = self.sample()
        for mutation in ("remove", "order", "skip_shutdown", "wrong_argv", "false_status", "inventory"):
            sample = copy.deepcopy(original)
            if mutation == "remove":
                sample["steps"].pop()
            elif mutation == "order":
                sample["steps"][1], sample["steps"][2] = sample["steps"][2], sample["steps"][1]
            elif mutation == "skip_shutdown":
                sample["steps"][-1] = replay._row(4, "shutdown", self.plan["shutdown"], "not_run_prior_failure")
            elif mutation == "wrong_argv":
                sample["steps"][1]["receipt"]["result"]["argv"] = ["/wrong/command"]
            elif mutation == "false_status":
                sample["steps"][1]["status"] = "failed"
            else:
                sample["retained_inputs"]["sha256"] = "0" * 64
            self.rebind(sample)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                replay.inspect_replay(self.output, self.receipt)

    def test_missing_or_extra_input_files_and_corrupt_archives_are_not_exclusions(self):
        self.run_replay()
        path = self.output / "step-0002.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((ValueError, OSError)):
            replay.inspect_replay(self.output, self.receipt)
        path.write_bytes(raw)
        extra = self.output / "unexplained.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            replay.inspect_replay(self.output, self.receipt)
        extra.unlink()
        next((self.output / "blobs").iterdir()).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            replay.inspect_replay(self.output, self.receipt)

    def test_historical_inspection_never_reruns_commands_or_uses_later_worktree_files(self):
        self.run_replay()
        expected = self.summary()
        for path in self.cwd.glob("report-*"):
            path.unlink()
        (self.cwd / "lease").touch()
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        with mock.patch.object(timer, "measure") as measured:
            self.assertEqual(expected, replay.inspect_replay(moved, self.receipt))
            measured.assert_not_called()

    def test_schema_types_closed_fields_and_qualification_labels_fail_closed(self):
        self.run_replay()
        for mutate in (lambda value: value.update(confirmatory_eligible=True),
                       lambda value: value["clock"].update(elapsed_ns=True),
                       lambda value: value["clock"].update(elapsed_ns=float(value["clock"]["elapsed_ns"])),
                       lambda value: value.update(unexpected=True),
                       lambda value: value.update(sample_unit="independent_interactions")):
            receipt = copy.deepcopy(self.receipt)
            mutate(receipt)
            with self.assertRaises(ValueError):
                replay.validate("receipt", receipt)
        sample = self.sample()
        sample["steps"][0]["receipt"]["result"]["stdout_bytes"] = 6.0
        with self.assertRaises(ValueError):
            replay.validate("sample", sample)

    def test_invalid_plans_and_existing_outputs_fail_before_any_project_work(self):
        for mutate in (lambda value: value["interactions"].append(copy.deepcopy(value["interactions"][0])),
                       lambda value: value["shutdown"].update(timeout_seconds=True),
                       lambda value: value["shutdown"]["required_finalization"].update(expected_exit_code=7),
                       lambda value: value["interactions"][0]["guard_expectations"].update(expected_exit_code=7),
                       lambda value: value["interactions"][0].update(id="bad\n"),
                       lambda value: value["interactions"][0].update(argv=["bad\0command"]),
                       lambda value: value["finalization"].update(expected_exit_code=0),
                       lambda value: value["shutdown"].update(idle_before_seconds=1),
                       lambda value: value.update(execution_timeout_seconds=float("nan"))):
            plan = copy.deepcopy(self.plan)
            mutate(plan)
            with mock.patch.object(timer, "measure") as measured:
                with self.assertRaises(ValueError):
                    replay.run_replay(self.output, plan)
                measured.assert_not_called()
            self.assertFalse(self.output.exists())
        self.output.mkdir()
        with mock.patch.object(timer, "measure") as measured:
            with self.assertRaises(FileExistsError):
                self.run_replay()
            measured.assert_not_called()

    def test_plan_and_aggregate_limits_fail_before_execution_and_unit_overflow_drops_nothing(self):
        for mutation in ("plan_bytes", "interaction_count", "raw_budget"):
            plan = copy.deepcopy(self.plan)
            if mutation == "plan_bytes":
                plan["preparation"]["argv"].append("x" * replay.MAX_PLAN_BYTES)
            elif mutation == "interaction_count":
                plan["interactions"] = [self.step("interaction", f"item_{index}") for index in range(33)]
            else:
                plan.update(capture_raw=True, raw_limit_bytes=128 * 1024 * 1024)
            with mock.patch.object(timer, "measure") as measured:
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    replay.run_replay(self.output, plan)
                measured.assert_not_called()
            self.assertFalse(self.output.exists())
        with mock.patch.object(replay, "MAX_UNIT_BYTES", 100):
            self.run_replay()
        self.assertIsNone(self.receipt["sample"])
        self.assertEqual(len(self.receipt["diagnostic_sample"]["steps"]), 4)
        self.assertEqual(self.summary()["status"], "aborted")
        self.assertFalse((self.cwd / "lease").exists())
        with mock.patch.object(replay.files, "MAX_RECEIPT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "receipt exceeds byte limit"):
                replay.inspect_replay(self.output, self.receipt)

    def test_inspection_rejects_symlinks_fifos_and_unexpected_nested_evidence(self):
        self.run_replay()
        alias = self.root / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            replay.inspect_replay(alias, self.receipt)
        path = self.output / "step-0002.json"
        saved = self.root / "saved-step.json"
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises((OSError, ValueError)):
            replay.inspect_replay(self.output, self.receipt)
        path.unlink()
        saved.rename(path)
        os.mkfifo(self.output / "fifo")
        with self.assertRaises((OSError, ValueError)):
            replay.inspect_replay(self.output, self.receipt)
        (self.output / "fifo").unlink()
        (self.output / "nested").mkdir()
        with self.assertRaises(ValueError):
            replay.inspect_replay(self.output, self.receipt)

    def test_steps_cannot_become_independent_latency_or_bootstrap_samples(self):
        self.run_replay()
        rows = self.sample()["steps"]
        samples = [{**row, "block": str(index // 2), "arm": "baseline" if index % 2 == 0 else "candidate",
                    "status": "valid_expected_outcome", "elapsed_ns": 10} for index, row in enumerate(rows)]
        for field in ("measurement_layer", "sample_unit"):
            labelled = [{key: value for key, value in sample.items() if key != field} for sample in samples]
            with self.assertRaisesRegex(ValueError, "correlated diagnostics"):
                analysis.paired_geometric_ratio(labelled)
            with self.assertRaisesRegex(ValueError, "correlated diagnostics"):
                analysis.bootstrap_paired_ratio(labelled, seed=0, resamples=20)

    def test_schema_and_all_references_are_offline_and_valid(self):
        names = ("managed-replay-v1.schema.json", "lifecycle-v2.schema.json", "result-card-v1.schema.json",
                 "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
        schemas = [json.loads((HARNESS / name).read_text()) for name in names]
        registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
        pending = []
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            pending.append((schema, schema["$id"]))
        while pending:
            value, base = pending.pop()
            if isinstance(value, dict):
                if "$ref" in value:
                    registry.resolver(base_uri=base).lookup(value["$ref"])
                pending.extend((child, base) for child in value.values())
            elif isinstance(value, list):
                pending.extend((child, base) for child in value)

    def test_cli_retains_abort_receipt_and_all_planned_counts_without_traceback(self):
        self.plan["interactions"][0]["argv"][-1] = "fail"
        plan_path, receipt_path = self.root / "requested.json", self.root / "receipt.json"
        plan_path.write_text(json.dumps(self.plan))
        command = [sys.executable, str(HARNESS / "managed_replay.py"), "--plan", str(plan_path), "--output", str(self.output)]
        produced = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(produced.returncode, 1, produced.stderr)
        receipt_path.write_text(produced.stdout)
        checked = subprocess.run([sys.executable, str(HARNESS / "inspect_replay.py"), "--directory", str(self.output), "--receipt", str(receipt_path)],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        summary = json.loads(checked.stdout)
        self.assertEqual(summary["planned_interaction_count"], 2)
        self.assertEqual(summary["interaction_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        receipt = json.loads(produced.stdout)
        receipt["clock"]["elapsed_ns"] = True
        receipt_path.write_text(json.dumps(receipt))
        checked = subprocess.run([sys.executable, str(HARNESS / "inspect_replay.py"), "--directory", str(self.output), "--receipt", str(receipt_path)],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 2)
        self.assertNotIn("Traceback", checked.stderr)


if __name__ == "__main__":
    unittest.main()
