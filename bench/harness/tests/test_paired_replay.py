"""Paired whole-session boundary and adverse controls; not benchmark qualification."""

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_timing_boundaries import ObservedBoundaryTests


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import blob_store
    import raw_capture
    import managed_replay as replay
    import paired_replay as pairs
    import pt_bench as timer
    import result_card as cards
    from inspect_run import inspect_run
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux managed replay/blob profile")
class PairedReplayTests(ObservedBoundaryTests):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "run"
        self.cwds = {arm: self.root / arm for arm in pairs.ARMS}
        self.digest = hashlib.sha256(b"ready\n").hexdigest()
        self.probe = HARNESS / "tests/fixtures/replay_probe.py"
        self.plans = {}
        for arm, cwd in self.cwds.items():
            cwd.mkdir()
            self.plans[arm] = {"schema_version": 1, "kind": "managed_session_replay_plan", "mode": "exploratory_unqualified",
                               "sample_unit": replay.UNIT, "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT,
                               "scope": "fresh_serial_commands_with_declared_state", "cwd": str(cwd), "execution_timeout_seconds": 20,
                               "preparation": self.step(arm, "preparation", "preparation"),
                               "interactions": [self.step(arm, "interaction", "first"), self.step(arm, "interaction", "second")],
                               "shutdown": self.step(arm, "shutdown", "shutdown"),
                               "finalization": {"expected_exit_code": None, "artifacts": [self.artifact("report-shutdown")], "absent": ["lease"]},
                               "capture_raw": False, "raw_limit_bytes": 1024}
        # Declarations for this test-owned fixture only, never authenticated pins.
        self.pairing = {"input_seed": 0, "edit_sequence_sha256": hashlib.sha256(b"fixture-no-edits").hexdigest(),
                        "external_state_sha256": hashlib.sha256(b"fixture-empty-state").hexdigest()}

    def artifact(self, path):
        return {"path": path, "bytes": 6, "sha256": self.digest}

    def step(self, arm, role, name):
        return {"id": name, "argv": [sys.executable, str(self.probe), str(self.cwds[arm]), role, name, "normal"],
                "timeout_seconds": 5, "idle_before_seconds": 0,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": self.digest},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [self.artifact("report-" + name)],
                                          "absent": ["lease"] if role == "shutdown" else []}}

    def produce(self, *, blocks=2, seed=0, **options):
        self.report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], blocks, seed,
                                     pairing=options.pop("pairing", self.pairing), **options)
        return self.report

    def assert_counts(self, report, planned=4):
        self.assertEqual(report["planned_session_count"], planned)
        self.assertEqual(len(report["session_observations"]), planned)
        self.assertEqual(sum(report["session_status_counts"].values()), planned)
        self.assertEqual(sum(report[key] for key in ("known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions")), planned)
        self.assertEqual(sum(report["observed_phase_status_counts"].values()) + report["not_run_phase_count"] + report["unknown_phase_count"], report["planned_phase_count"])
        self.assertEqual(report["sample_unit"], replay.UNIT)
        self.assertEqual(report["timing_endpoint"], replay.ENDPOINT)
        self.assertIsNone(report["verified_independent_sessions"])
        self.assertIsNone(report["verified_independent_blocks"])
        self.assertIsNone(report["resource_observation"])
        self.assertFalse(report["whole_boundary_resource_accounting_complete"])
        self.assertFalse(report["confirmatory_eligible"])

    def assert_blocked(self):
        summary = summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=0)
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "blocked")
        for field in ("ratio", "absolute_latency_ns", "bootstrap"):
            self.assertIsNone(summary[field])
        return summary

    def begins(self, arm):
        path = self.cwds[arm] / "events"
        return [line.split(":")[0] for line in path.read_text().splitlines() if ":begin:" in line] if path.exists() else []

    def saved(self, name):
        return json.loads((self.output / name).read_text())

    def test_complete_pairs_use_new_sessions_in_balanced_serial_schedule(self):
        report = self.produce()
        self.assert_counts(report)
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 4})
        self.assertEqual(report["record_consistency"], "complete")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        plan = self.saved("schedule.json")
        self.assertEqual({tuple(block["order"]) for block in plan["schedule"]}, {("baseline", "candidate"), ("candidate", "baseline")})
        previous = None
        for row in report["session_observations"]:
            number, arm = row["context"]["block"], row["context"]["arm"]
            directory, receipt_name, record_name = pairs._names(number, arm)
            record, receipt = self.saved(record_name), self.saved(receipt_name)
            self.assertEqual(record["receipt"]["sha256"], hashlib.sha256((self.output / receipt_name).read_bytes()).hexdigest())
            self.assertEqual(row["elapsed_ns"], receipt["clock"]["elapsed_ns"])
            self.assertEqual(row["phase_guard_counts"], {"matched": 4})
            self.assertTrue(row["receipt_record_committed"] and row["session_record_committed"])
            self.assertEqual(row["replay_summary"]["observed_session_count"], 1)
            self.assertTrue((self.output / directory / "unit.json").is_file())
            if previous is not None:
                self.assertGreaterEqual(record["call_clock"]["monotonic_start_ns"], previous)
            previous = record["receipt_publication_clock"]["monotonic_end_ns"]
        for arm, cwd in self.cwds.items():
            self.assertEqual(self.begins(arm).count("preparation"), 2)
            self.assertEqual(self.begins(arm).count("shutdown"), 2)
            self.assertEqual((cwd / "state").read_text(), "2")
            self.assertFalse((cwd / "lease").exists())

    def test_failed_preparation_preserves_failed_session_and_every_not_run_session(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        report = self.produce()
        self.assert_counts(report)
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_run_aborted": 3})
        self.assertEqual(self.begins("baseline"), ["preparation", "shutdown"])
        self.assertEqual(self.begins("candidate"), [])
        self.assertEqual(report["session_observations"][0]["replay_summary"]["interaction_status_counts"], {"not_run_prior_failure": 2})
        self.assert_blocked()

    def test_later_failed_interaction_keeps_prior_success_and_skips_later_pairs(self):
        self.plans["candidate"]["interactions"][0]["argv"][-1] = "fail"
        report = self.produce()
        self.assert_counts(report)
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "completed_unqualified": 1, "not_run_run_aborted": 2})
        self.assertEqual(self.begins("candidate"), ["preparation", "first", "shutdown"])
        self.assertEqual(report["observed_session_count"], 2)
        self.assert_blocked()

    def test_explicit_expected_nonzero_matches_only_when_both_workflows_declare_it(self):
        for session in self.plans.values():
            step = session["interactions"][0]
            step["argv"][-1] = "fail"
            step["guard_expectations"]["expected_exit_code"] = step["required_finalization"]["expected_exit_code"] = 7
        self.produce()
        summary = summarize_run(self.output)
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "exploratory_point_estimate")
        self.assertEqual(summary["session_status_counts"], {"completed_unqualified": 4})

    def test_guard_mismatch_aborts_without_replaying_or_dropping_the_pair(self):
        self.plans["baseline"]["interactions"][0]["guard_expectations"]["expected_stdout_sha256"] = "0" * 64
        report = self.produce()
        self.assertEqual(report["known_session_invocations"], 1)
        self.assertEqual(report["known_not_invoked_sessions"], 3)
        self.assertEqual(self.begins("baseline"), ["preparation", "first", "shutdown"])
        self.assert_blocked()

    def test_shutdown_failure_timeout_and_unreleased_state_stop_all_later_sessions(self):
        for mode in ("fail", "hang", "unreleased"):
            self.output = self.root / mode
            self.plans["baseline"]["shutdown"]["argv"][-1] = mode
            for session in self.plans.values():
                session["shutdown"]["timeout_seconds"] = 0.1 if mode == "hang" else 5
            report = self.produce()
            self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_run_aborted": 3})
            self.assertEqual(report["session_observations"][0]["replay_summary"]["shutdown_status"], "failed")
            self.assert_blocked()

    def test_timeout_and_launch_error_remain_failed_whole_sessions(self):
        for mode in ("timeout", "launch"):
            self.output = self.root / mode
            for session in self.plans.values():
                session["interactions"][0]["timeout_seconds"] = 0.04
            self.plans["baseline"]["interactions"][0]["argv"] = (
                [sys.executable, str(self.probe), str(self.cwds["baseline"]), "interaction", "first", "hang"]
                if mode == "timeout" else ["/nonexistent/pt-paired-replay-command"])
            report = self.produce()
            self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_run_aborted": 3})
            self.assertEqual(report["session_observations"][0]["replay_summary"]["shutdown_status"], "observed_unqualified")
            self.assert_blocked()

    def test_unresolved_shared_input_declarations_keep_completed_sessions_but_block_estimates(self):
        report = self.produce(pairing=None)
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 4})
        self.assertEqual(report["pairing_identity_status"], "unresolved")
        summary = self.assert_blocked()
        self.assertIn("pairing_identity_unresolved", summary["blockers"][0]["reasons"])

    def test_missing_phase_guard_is_not_equal_work_or_an_eligible_subset_estimate(self):
        self.plans["candidate"]["preparation"]["guard_expectations"] = None
        report = self.produce()
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 4})
        self.assert_blocked()

    def test_bounded_raw_prefix_truncation_preserves_all_units_but_blocks_analysis(self):
        for session in self.plans.values():
            session.update(capture_raw=True, raw_limit_bytes=4)
        report = self.produce()
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 4})
        self.assertTrue(all(row["replay_summary"]["raw_capture_truncated_phase_count"] == 4 for row in report["session_observations"]))
        self.assert_blocked()

    def test_bootstrap_resamples_complete_pairs_not_interactions_and_reconstructs_identically(self):
        self.produce()
        with mock.patch.object(pairs, "guarded_exploratory_bootstrap", wraps=pairs.guarded_exploratory_bootstrap) as bootstrap:
            first = summarize_run(self.output, bootstrap_resamples=30, bootstrap_seed=7)
        samples = bootstrap.call_args.args[0]
        self.assertEqual(len(samples), 4)
        self.assertTrue(all(sample["sample_unit"] == replay.UNIT for sample in samples))
        self.assertEqual(first["bootstrap"]["blocks"], 2)
        self.assertEqual(first["resampling_unit"], "whole_paired_complete_sessions")
        self.assertEqual(first, summarize_run(self.output, bootstrap_resamples=30, bootstrap_seed=7))
        expected = math.exp(sum(math.log(samples[index]["elapsed_ns"]) - math.log(samples[index + 1]["elapsed_ns"])
                                if samples[index]["arm"] == "baseline" else math.log(samples[index + 1]["elapsed_ns"]) - math.log(samples[index]["elapsed_ns"])
                                for index in (0, 2)) / 2)
        self.assertAlmostEqual(first["ratio"], expected)
        inspection = inspect_run(self.output)
        swapped = copy.deepcopy(inspection["session_observations"])
        for row in swapped:
            row["context"]["arm"] = "candidate" if row["context"]["arm"] == "baseline" else "baseline"
        # Synthetic label swap checks direction only, not a new execution or qualification.
        self.assertAlmostEqual(pairs.summarize(inspection, swapped)["ratio"], 1 / first["ratio"])

    def test_summary_rejects_omitted_duplicate_and_relabelled_step_units(self):
        self.produce()
        inspection = inspect_run(self.output)
        original = inspection["session_observations"]
        for mutation in ("omitted_pair", "duplicate", "step_unit", "inner_unit"):
            rows = copy.deepcopy(original)
            if mutation == "omitted_pair":
                rows = rows[:2]
            elif mutation == "duplicate":
                rows[1] = copy.deepcopy(rows[0])
            elif mutation == "step_unit":
                rows[0]["sample_unit"] = "replay_step"
            else:
                rows[0]["replay_summary"]["sample_unit"] = "replay_step"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "every planned whole-session"):
                pairs.summarize(inspection, rows)

    def test_session_clock_contains_preparation_and_is_the_only_comparison_duration(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "wait"
        entered = self.cwds["baseline"] / "preparation.entered"
        release = self.cwds["baseline"] / "preparation.release"
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.produce)
            window = self.hold_and_release(future, entered.exists, release.touch)
            future.result(timeout=30)
        receipt = self.saved("receipt-000001-baseline.json")
        self.assert_covers_stage(receipt["clock"], window)
        row = self.report["session_observations"][0]
        self.assertEqual(row["elapsed_ns"], receipt["clock"]["elapsed_ns"])
        inner = json.loads((self.output / "session-000001-baseline/unit.json").read_text())
        self.assertGreater(row["elapsed_ns"], sum(step["receipt"]["result"]["elapsed_ns"] for step in inner["steps"] if step["role"] == "interaction"))

    def test_receipt_persistence_is_outside_session_clock_and_finishes_before_next_session(self):
        entered, release = threading.Event(), threading.Event()
        original = timer.write_record

        def hold(path, value):
            if Path(path) == self.output / "receipt-000001-baseline.json":
                entered.set()
                if not release.wait(timeout=15):
                    raise RuntimeError("parent did not release receipt publication")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=hold), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.produce)
            def ready():
                if entered.is_set():
                    self.assertEqual(self.begins("candidate"), [])
                    return True
                return False
            window = self.hold_and_release(future, ready, release.set)
            future.result(timeout=30)
        receipt = self.saved("receipt-000001-baseline.json")
        record = self.saved("block-000001-baseline.json")
        self.assertLessEqual(receipt["clock"]["monotonic_end_ns"], window[0])
        self.assert_covers_stage(record["receipt_publication_clock"], window)

    def test_missing_return_and_cancellation_preserve_unknown_session_and_not_run_denominators(self):
        for error in (OSError("injected missing return"), KeyboardInterrupt("injected cancellation"), RuntimeError("injected runtime error")):
            self.output = self.root / type(error).__name__
            with mock.patch.object(replay, "run_replay", side_effect=error) as measured:
                report = self.produce()
                self.assertEqual(measured.call_count, 1)
            self.assert_counts(report)
            self.assertEqual(report["session_status_counts"], {"harness_error": 1, "not_run_run_aborted": 3})
            self.assertEqual(report["unknown_session_invocations"], 1)
            self.assertEqual(report["unknown_phase_count"], 4)
            self.assertEqual(report["not_run_phase_count"], 12)
            self.assertIsNone(report["session_observations"][0]["elapsed_ns"])
            self.assertTrue(report["infrastructure_failure"])
            self.assert_blocked()

    def test_missing_return_after_commit_keeps_bound_diagnostic_bytes_not_a_completed_sample(self):
        original = replay.run_replay

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected lost return after shutdown and unit commit")

        with mock.patch.object(replay, "run_replay", side_effect=fail) as measured:
            report = self.produce()
            self.assertEqual(measured.call_count, 1)
        self.assert_counts(report)
        self.assertEqual(report["unknown_session_invocations"], 1)
        self.assertEqual(report["observed_session_count"], 0)
        self.assertTrue(self.saved("abort.json")["diagnostic_inputs"]["files"])
        self.assertTrue((self.output / "session-000001-baseline/unit.json").is_file())
        self.assertEqual(self.begins("baseline"), ["preparation", "first", "second", "shutdown"])
        self.assert_blocked()

    def test_receipt_publication_faults_recover_only_matching_diagnostic_copies(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, value):
                if Path(path) == self.output / "receipt-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode in ("error", "committed_then_error"):
                        raise OSError("injected receipt publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            self.assert_counts(report)
            self.assertEqual(report["session_status_counts"], {"completed_unqualified": 1, "not_run_run_aborted": 3})
            self.assertFalse(report["session_observations"][0]["receipt_record_committed"])
            self.assertFalse(report["session_observations"][0]["session_record_committed"])
            self.assertTrue(report["infrastructure_failure"])
            self.assert_blocked()

    def test_session_metadata_publication_faults_never_invent_commits_or_retry_work(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, value):
                if Path(path) == self.output / "block-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode in ("error", "committed_then_error"):
                        raise OSError("injected session metadata publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            self.assert_counts(report)
            self.assertTrue(report["session_observations"][0]["receipt_record_committed"])
            self.assertFalse(report["session_observations"][0]["session_record_committed"])
            self.assertEqual(report["known_not_invoked_sessions"], 3)
            self.assert_blocked()

    def test_validation_cancellation_after_return_is_retained_as_observer_abort(self):
        original = pairs._inspect_session
        calls = []

        def interrupt(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt("injected post-return validation cancellation")
            return original(*args, **kwargs)

        with mock.patch.object(pairs, "_inspect_session", side_effect=interrupt):
            report = self.produce()
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 1, "not_run_run_aborted": 3})
        self.assertTrue(report["infrastructure_failure"])
        self.assert_blocked()

    def test_abort_publication_failure_preserves_files_but_cannot_approve_partial_campaign(self):
        self.plans["baseline"]["interactions"][0]["argv"][-1] = "fail"
        original = timer.write_record

        def fail(path, value):
            if Path(path) == self.output / "abort.json":
                raise OSError("injected abort publication failure")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            with self.assertRaises(OSError):
                self.produce()
        self.assertTrue((self.output / "session-000001-baseline/unit.json").is_file())
        self.assertEqual(self.begins("candidate"), [])
        with self.assertRaises((OSError, ValueError)):
            inspect_run(self.output)

    def test_frozen_campaign_plan_mutation_stops_later_sessions_and_fails_binding(self):
        original = timer.write_record

        def mutate(path, value):
            original(path, value)
            if Path(path) == self.output / "receipt-000001-baseline.json":
                plan = self.output / "schedule.json"
                plan.write_bytes(plan.read_bytes() + b"\n")

        with mock.patch.object(timer, "write_record", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "plan byte binding"):
                self.produce()
        self.assertEqual(len(list(self.output.glob("session-*"))), 1)
        self.assertEqual(self.begins("candidate"), [])

    def test_a_different_but_internally_valid_session_plan_cannot_be_substituted(self):
        original = replay.run_replay

        def substitute(output, plan):
            changed = copy.deepcopy(plan)
            changed["preparation"]["argv"].append("unrequested-argument")
            return original(output, changed)

        with mock.patch.object(replay, "run_replay", side_effect=substitute):
            with self.assertRaisesRegex(ValueError, "plan differs from paired arm"):
                self.produce()
        self.assertEqual(self.begins("candidate"), [])

    def test_pairing_mismatches_are_rejected_before_any_session_starts(self):
        original = copy.deepcopy(self.plans)
        for mutation in ("order", "count", "idle", "timeout", "execution_budget", "capture", "raw_limit", "exit", "duplicate_id"):
            self.plans = copy.deepcopy(original)
            candidate = self.plans["candidate"]
            if mutation == "order":
                candidate["interactions"].reverse()
            elif mutation == "count":
                candidate["interactions"].pop()
            elif mutation == "idle":
                candidate["interactions"][0]["idle_before_seconds"] = 0.1
            elif mutation == "timeout":
                candidate["interactions"][0]["timeout_seconds"] = 4
            elif mutation == "execution_budget":
                candidate["execution_timeout_seconds"] = 19
            elif mutation == "capture":
                candidate["capture_raw"] = True
            elif mutation == "raw_limit":
                candidate["raw_limit_bytes"] = 2048
            elif mutation == "exit":
                candidate["interactions"][0]["required_finalization"]["expected_exit_code"] = 7
                candidate["interactions"][0]["guard_expectations"]["expected_exit_code"] = 7
            else:
                candidate["interactions"][1]["id"] = "first"
            with mock.patch.object(replay, "run_replay") as measured:
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    self.produce()
                measured.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_shared_nested_and_alias_cwds_are_rejected_without_inventing_isolation(self):
        nested = self.cwds["baseline"] / "nested"
        nested.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(self.cwds["baseline"], target_is_directory=True)
        for path in (self.cwds["baseline"], nested, alias):
            self.plans["candidate"]["cwd"] = str(path)
            with mock.patch.object(replay, "run_replay") as measured:
                with self.assertRaisesRegex(ValueError, "separate nonnested"):
                    self.produce()
                measured.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_invalid_types_counts_pins_and_declaration_budgets_fail_before_output(self):
        for count, seed, pairing in ((True, 0, self.pairing), (2.0, 0, self.pairing), (65, 0, self.pairing),
                                     (2, True, self.pairing), (2, 0, {**self.pairing, "input_seed": True}),
                                     (2, 0, {**self.pairing, "external_state_sha256": "a" * 64 + "\n"})):
            with mock.patch.object(replay, "run_replay") as measured:
                with self.assertRaises(ValueError):
                    self.produce(blocks=count, seed=seed, pairing=pairing)
                measured.assert_not_called()
            self.assertFalse(self.output.exists())
        for session in self.plans.values():
            session.update(capture_raw=True, raw_limit_bytes=10 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "aggregate declared"):
            self.produce(blocks=4)
        self.assertFalse(self.output.exists())

    def test_existing_outputs_are_never_reused_or_overwritten(self):
        self.output.mkdir()
        marker = self.output / "user-work"
        marker.write_text("keep")
        with mock.patch.object(replay, "run_replay") as measured:
            with self.assertRaises(FileExistsError):
                self.produce()
            measured.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")

    def test_history_can_relocate_and_never_rereads_later_worktrees_or_executes_commands(self):
        self.produce()
        expected = summarize_run(self.output, bootstrap_resamples=30, bootstrap_seed=7)
        for cwd in self.cwds.values():
            for path in cwd.glob("report-*"):
                path.unlink()
            (cwd / "lease").touch()
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        with mock.patch.object(replay, "run_replay") as measured:
            self.assertEqual(expected, summarize_run(moved, bootstrap_resamples=30, bootstrap_seed=7))
            measured.assert_not_called()

    def test_wrong_metadata_context_byte_bindings_and_call_clock_are_rejected(self):
        self.produce()
        path = self.output / "block-000001-baseline.json"
        original = self.saved(path.name)
        for mutation in ("context", "receipt", "plan", "clock"):
            record = copy.deepcopy(original)
            if mutation == "context":
                record["context"]["arm"] = "candidate"
            elif mutation == "receipt":
                record["receipt"]["sha256"] = "0" * 64
            elif mutation == "plan":
                record["campaign_plan"]["sha256"] = "0" * 64
            else:
                record["call_clock"]["monotonic_start_ns"] = record["call_clock"]["monotonic_end_ns"]
                record["call_clock"]["elapsed_ns"] = 0
            path.write_text(json.dumps(record))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                inspect_run(self.output)

    def test_omitted_shutdown_is_rejected_even_after_unit_and_receipt_digests_are_rebound(self):
        self.produce()
        directory, receipt_name, record_name = pairs._names(1, "baseline")
        unit_path = self.output / directory / "unit.json"
        unit = json.loads(unit_path.read_text())
        unit["steps"].pop()
        raw = json.dumps(unit).encode()
        unit_path.write_bytes(raw)
        receipt = self.saved(receipt_name)
        receipt["sample"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        raw = json.dumps(receipt).encode()
        (self.output / receipt_name).write_bytes(raw)
        record = self.saved(record_name)
        record["receipt"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (self.output / record_name).write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "omitted a planned phase"):
            inspect_run(self.output)

    def test_unexplained_missing_or_extra_records_are_not_favorable_subset_campaigns(self):
        self.produce()
        path = self.output / "receipt-000001-baseline.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            inspect_run(self.output)
        path.write_bytes(raw)
        extra = self.output / "extra.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        extra.unlink()
        next((self.output / "session-000001-baseline/blobs").iterdir()).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_missing_abort_or_later_executed_session_cannot_be_implicitly_ignored(self):
        self.plans["baseline"]["interactions"][0]["argv"][-1] = "fail"
        self.produce()
        path = self.output / "abort.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        path.write_bytes(raw)
        shutil.copytree(self.output / "session-000001-baseline", self.output / "session-000001-candidate")
        with self.assertRaisesRegex(ValueError, "unexpected or missing"):
            inspect_run(self.output)

    def test_false_session_failure_abort_is_not_a_registered_exclusion(self):
        self.produce()
        row = self.report["session_observations"][-1]
        _, _, record_name = pairs._names(row["context"]["block"], row["context"]["arm"])
        abort = {"schema_version": 1, "kind": "paired_managed_replay_abort", "mode": "exploratory_unqualified",
                 "context": row["context"], "campaign_plan": self.saved(record_name)["campaign_plan"], "reason": "session_failed",
                 "error": "unjustified exclusion", "call_clock": None, "diagnostic_receipt": None,
                 "diagnostic_session": None, "diagnostic_inputs": None}
        (self.output / "abort.json").write_text(json.dumps(abort))
        with self.assertRaisesRegex(ValueError, "lacks an observed session failure"):
            inspect_run(self.output)

    def test_nonregular_inputs_and_whole_campaign_read_limits_fail_closed(self):
        self.produce()
        for attribute, value in (("MAX_CAMPAIGN_FILES", 1), ("MAX_CAMPAIGN_BYTES", 1)):
            with mock.patch.object(pairs, attribute, value):
                with self.assertRaisesRegex(ValueError, "aggregate file/byte limit"):
                    inspect_run(self.output)
        alias = self.root / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            inspect_run(alias)
        os.mkfifo(self.output / "fifo")
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        (self.output / "fifo").unlink()
        (self.output / "nested").mkdir()
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_fingerprint_only_mutation_during_inspection_is_not_retried(self):
        self.produce()
        original = pairs._snapshot
        calls = []

        def mutate(directory):
            result = original(directory)
            calls.append(1)
            if len(calls) > 1:
                result[0]["schedule.json"]["identity"][-1] += 1  # Synthetic observer-only mutation.
            return result

        with mock.patch.object(pairs, "_snapshot", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                inspect_run(self.output)

    def test_schema_closure_and_integer_token_types_apply_through_replay_references(self):
        self.produce()
        plan = self.saved("schedule.json")
        for mutate in (lambda value: value.update(schema_version=True),
                       lambda value: value["pairing"].update(input_seed=1.0),
                       lambda value: value["sessions"]["baseline"].update(raw_limit_bytes=1.0),
                       lambda value: value.update(confirmatory_eligible=True)):
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.assertRaises(ValueError):
                pairs.validate("plan", changed)
        record = self.saved("block-000001-baseline.json")
        record["context"]["block"] = True
        with self.assertRaises(ValueError):
            pairs.validate("session", record)

    def test_schema_and_all_references_resolve_only_from_bundled_files(self):
        names = ("paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json",
                 "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
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

    def test_one_pair_and_invalid_bootstrap_requests_do_not_gain_independent_samples(self):
        self.produce(blocks=1)
        summary = summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=0)
        self.assert_counts(summary, planned=2)
        self.assertEqual(summary["status"], "blocked")
        for options in ({"bootstrap_resamples": 20}, {"bootstrap_resamples": True, "bootstrap_seed": 0},
                        {"bootstrap_resamples": 20, "bootstrap_seed": True}):
            with self.assertRaises(ValueError):
                summarize_run(self.output, **options)

    def test_legacy_result_cards_reject_replay_format_explicitly_including_no_return_aborts(self):
        with mock.patch.object(replay, "run_replay", side_effect=OSError("injected missing return")):
            self.produce()
        with self.assertRaisesRegex(ValueError, "paired replay result cards are not implemented"):
            cards.generate_result_card(self.output)

    def test_cli_routes_accounted_abort_through_inspection_and_blocked_summary(self):
        self.plans["baseline"]["interactions"][0]["argv"][-1] = "fail"
        paths = {}
        for arm, plan in self.plans.items():
            paths[arm] = self.root / f"{arm}.json"
            paths[arm].write_text(json.dumps(plan))
        args = [sys.executable, str(HARNESS / "paired_replay.py"), "--output", str(self.output), "--blocks", "2", "--seed", "0",
                "--baseline-plan", str(paths["baseline"]), "--candidate-plan", str(paths["candidate"]),
                "--pairing-json", json.dumps(self.pairing)]
        produced = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(produced.returncode, 1, produced.stderr)
        self.assert_counts(json.loads(produced.stdout))
        for script, exit_code in (("inspect_run.py", 0), ("summarize_run.py", 1)):
            result = subprocess.run([sys.executable, str(HARNESS / script), str(self.output)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, exit_code, result.stderr)
            self.assertFalse(json.loads(result.stdout)["confirmatory_eligible"])
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
