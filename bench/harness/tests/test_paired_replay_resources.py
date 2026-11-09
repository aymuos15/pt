"""Paired whole-session resource controls: synthetic counters are not native qualification."""

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
import uuid

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_timing_boundaries import ObservedBoundaryTests
import test_replay_resources as controls
from test_cgroup_accounting import delegated_parent


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import paired_replay_resources as pairs
    import replay_resources as diagnostic
    import resource_run as resources
    import managed_replay as replay
    import pt_bench as timer
    import result_card as cards
    from inspect_run import inspect_run
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


class PairedResourceFixture(controls.ReplayFixture):
    def prepare_pairs(self):
        self.prepare()
        self.plans = {"baseline": self.plan}
        candidate = copy.deepcopy(self.plan)
        cwd = self.root / "candidate"
        cwd.mkdir()
        candidate["cwd"] = str(cwd)
        for _, step in replay._steps(candidate):
            step["argv"] = [str(cwd) if value == str(self.cwd) else value for value in step["argv"]]
        self.plans["candidate"] = candidate
        self.pairing = {"input_seed": 0, "edit_sequence_sha256": hashlib.sha256(b"fixture-no-edits").hexdigest(),
                        "external_state_sha256": hashlib.sha256(b"fixture-empty-state").hexdigest()}

    def assert_campaign_counts(self, report, *, sessions=4, phases=16, interactions=8):
        self.assertEqual(report["planned_session_count"], sessions)
        self.assertEqual(len(report["session_observations"]), sessions)
        self.assertEqual(sum(report["session_status_counts"].values()), sessions)
        self.assertEqual(sum(report[key] for key in ("known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions")), sessions)
        self.assertEqual(sum(report["replay_session_status_counts"].values()), sessions)
        self.assertEqual(sum(report[key] for key in ("known_boundary_invocations", "unknown_boundary_invocations", "known_not_invoked_boundaries")), sessions)
        self.assertEqual(report["planned_phase_count"], phases)
        self.assertEqual(sum(report["phase_status_counts"].values()), phases)
        self.assertEqual(sum(report[key] for key in ("known_phase_invocation_attempts", "unknown_phase_invocations", "known_not_invoked_phases")), phases)
        self.assertEqual(report["planned_interaction_count"], interactions)
        self.assertEqual(sum(report["interaction_status_counts"].values()), interactions)
        self.assertEqual(report["sample_unit"], replay.UNIT)
        self.assertEqual(report["measurement_layer"], "resource_diagnostic")
        self.assertIsNone(report["verified_independent_sessions"])
        self.assertIsNone(report["verified_independent_blocks"])
        self.assertFalse(report["confirmatory_eligible"])

    def begins(self, arm):
        path = Path(self.plans[arm]["cwd"]) / "events"
        return [line.split(":")[0] for line in path.read_text().splitlines() if ":begin:" in line] if path.exists() else []


@unittest.skipUnless(sys.platform == "linux", "initial Linux replay/blob profile")
class PairedReplayResourceTests(PairedResourceFixture, ObservedBoundaryTests):
    def setUp(self):
        self.prepare_pairs()
        self.real_measure = timer.measure
        self.groups = []

    def produce(self, configurations=None, *, blocks=2, **options):
        self.groups = []
        configurations = configurations or [{}]

        def group(parent):
            settings = configurations[min(len(self.groups), len(configurations) - 1)]
            item = controls.SyntheticReplayGroup(self.real_measure, **settings)
            item.path = Path(parent) / ("pt-bench-" + uuid.uuid4().hex)
            item.identity = [1, len(self.groups) + 1]
            self.groups.append(item)
            return item

        def measure(*args, **kwargs):
            return self.groups[-1].measure(*args, **kwargs)

        with mock.patch.object(resources, "CgroupDirectory", side_effect=group), mock.patch.object(timer, "measure", side_effect=measure):
            self.report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], blocks, 0, options.pop("outer_timeout", 30),
                                          pairing=options.pop("pairing", self.pairing), cgroup_parent=options.pop("cgroup_parent", "/synthetic/delegated"),
                                          cleanup_grace=0, **options)
        return self.report

    def assert_blocked(self, *, sessions=4, phases=16, interactions=8):
        summary = summarize_run(self.output)
        self.assert_campaign_counts(summary, sessions=sessions, phases=phases, interactions=interactions)
        self.assertEqual(summary["status"], "blocked")
        for key in ("ratio", "absolute_latency_ns", "bootstrap", "whole_campaign_peak_charged_bytes", "idle_only_resource_metrics", "per_phase_resource_metrics"):
            self.assertIsNone(summary[key])
        return summary

    def saved(self, name):
        return json.loads((self.output / name).read_text())

    def test_complete_diagnostics_pair_whole_sessions_once_with_distinct_groups_and_no_latency_estimate(self):
        report = self.produce()
        self.assert_campaign_counts(report)
        self.assertEqual(report["session_status_counts"], {"observed_unqualified": 4})
        self.assertTrue(report["all_session_accounting_complete"])
        self.assertEqual(report["record_consistency"], "complete")
        self.assertEqual(len(self.groups), 4)
        self.assertEqual(len({group.path for group in self.groups}), 4)
        self.assertTrue(all(group.closed and group.removed for group in self.groups))
        summary = summarize_run(self.output)
        self.assertEqual(summary["status"], "diagnostic_resource_observations")
        self.assertEqual(summary["per_arm_resources_unit"], "complete_session_including_driver_not_measurement_stage_only")
        for arm in pairs.ARMS:
            self.assertEqual(self.begins(arm).count("preparation"), 2)
            self.assertEqual(self.begins(arm).count("shutdown"), 2)
            values = summary["per_arm_resources"][arm]
            self.assertEqual(values["cpu_usage_usec"], {"observed_units": 2, "unknown_units": 0, "observed_sum": 600000})  # Synthetic counters.
            self.assertEqual(values["peak_charged_bytes"]["maximum_observed_per_session"], 96 * 1024 * 1024)
        for row in summary["session_observations"]:
            self.assertEqual(row["phase_guard_counts"], {"matched": 4})
            self.assertIsNone(row["elapsed_ns"])
            self.assertNotEqual(row["observer_process"]["pid"], row["driver_process"]["pid"])
        for key in ("ratio", "absolute_latency_ns", "bootstrap", "whole_campaign_peak_charged_bytes"):
            self.assertIsNone(summary[key])

    def test_clean_unsupported_checks_continue_all_planned_units_without_subjects_or_fake_zeros(self):
        report = self.produce([{"missing": ["memory.peak"]}])
        self.assert_campaign_counts(report)
        self.assertEqual(report["session_status_counts"], {"unsupported": 4})
        self.assertEqual(report["record_consistency"], "complete")
        self.assertEqual(report["known_not_invoked_sessions"], 4)
        self.assertEqual(report["unit_observation_count"], 4)
        self.assertEqual(self.begins("baseline"), [])
        self.assertEqual(self.begins("candidate"), [])
        summary = self.assert_blocked()
        for arm in pairs.ARMS:
            self.assertEqual(summary["per_arm_resources"][arm]["cpu_usage_usec"], {"observed_units": 0, "unknown_units": 2, "observed_sum": None})

    def test_one_unsupported_arm_does_not_hide_other_arms_diagnostics(self):
        report = self.produce([{"missing": ["memory.peak"]}, {}, {}, {"missing": ["memory.peak"]}])
        self.assert_campaign_counts(report)
        self.assertEqual(report["session_status_counts"], {"observed_unqualified": 2, "unsupported": 2})
        self.assertEqual(self.begins("baseline"), [])
        self.assertEqual(self.begins("candidate").count("preparation"), 2)
        self.assert_blocked()

    def test_explicit_partial_support_continues_but_native_peak_stays_null_and_campaign_blocked(self):
        report = self.produce([{"missing": ["memory.peak"]}], allow_missing_peak=True)
        self.assertEqual(report["session_status_counts"], {"partial_unsupported": 4})
        self.assertEqual(report["observed_session_count"], 4)
        self.assertFalse(report["all_session_accounting_complete"])
        summary = self.assert_blocked()
        for arm in pairs.ARMS:
            self.assertEqual(summary["per_arm_resources"][arm]["peak_charged_bytes"], {"observed_units": 0, "unknown_units": 2, "maximum_observed_per_session": None})
            self.assertEqual(summary["per_arm_resources"][arm]["cpu_usage_usec"]["observed_sum"], 600000)

    def test_failed_preparation_retains_failed_skipped_phases_and_all_later_not_run_sessions(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        report = self.produce()
        self.assert_campaign_counts(report)
        self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
        self.assertEqual(report["phase_status_counts"], {"failed": 1, "not_run_prior_failure": 2, "not_run_run_aborted": 12, "observed_unqualified": 1})
        self.assertEqual(self.begins("baseline"), ["preparation", "shutdown"])
        self.assertEqual(self.begins("candidate"), [])
        self.assert_blocked()

    def test_later_failure_retains_prior_success_and_failed_costs_without_subset_selection(self):
        self.plans["candidate"]["interactions"][0]["argv"][-1] = "fail"
        report = self.produce()
        self.assert_campaign_counts(report)
        self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 2, "observed_unqualified": 1})
        summary = self.assert_blocked()
        self.assertEqual(summary["per_arm_resources"]["candidate"]["cpu_usage_usec"], {"observed_units": 1, "unknown_units": 1, "observed_sum": 300000})
        self.assertEqual(self.begins("candidate"), ["preparation", "first", "shutdown"])

    def test_expected_nonzero_work_remains_a_diagnostic_not_passing_tests_or_latency(self):
        for plan in self.plans.values():
            step = plan["interactions"][0]
            step["argv"][-1] = "fail"
            step["guard_expectations"]["expected_exit_code"] = step["required_finalization"]["expected_exit_code"] = 7
        self.produce()
        summary = summarize_run(self.output)
        self.assertEqual(summary["status"], "diagnostic_resource_observations")
        self.assertFalse(summary["confirmatory_eligible"])
        self.assertIsNone(summary["ratio"])

    def test_shutdown_failure_timeout_unreleased_state_and_deadline_never_allow_later_sessions(self):
        for mode in ("fail", "hang", "unreleased", "deadline"):
            self.output = self.root / mode
            self.plans["baseline"]["shutdown"]["argv"][-1] = mode if mode != "deadline" else "normal"
            for plan in self.plans.values():
                plan["shutdown"]["timeout_seconds"] = 0.1 if mode == "hang" else 5
                plan["execution_timeout_seconds"] = 0.001 if mode == "deadline" else 20
            report = self.produce()
            self.assert_campaign_counts(report)
            self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
            self.assertEqual(report["session_observations"][0]["shutdown_status"], "observed_unqualified" if mode == "deadline" else "failed")
            self.assert_blocked()

    def test_lingering_workers_fail_even_after_matching_replay_shutdown_and_costs_stay_visible(self):
        report = self.produce([{"work": "background"}])
        self.assertEqual(report["session_observations"][0]["session_status"], "completed_unqualified")
        self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
        self.assertEqual(len(self.groups), 1)
        self.assertEqual(self.groups[0].kills, 1)
        self.assertGreater(self.assert_blocked()["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"], 300000)

    def test_enrollment_counter_and_cleanup_failures_stop_remaining_units_without_retry(self):
        for settings in ({"work": "enrollment_error"}, {"fault": "cpu.stat"}, {"fault": "remove"}):
            self.output = self.root / (settings.get("work") or settings["fault"])
            report = self.produce([settings])
            self.assert_campaign_counts(report)
            self.assertEqual(len(self.groups), 1)
            self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
            self.assert_blocked()

    def test_outer_observer_return_loss_preserves_unknown_unit_and_not_run_denominators(self):
        for error in (OSError("fixture-only lost return"), RuntimeError("fixture-only observer failure"), KeyboardInterrupt("fixture-only cancellation")):
            self.output = self.root / type(error).__name__
            with mock.patch.object(diagnostic, "run_observation", side_effect=error) as observed:
                report = self.produce()
                observed.assert_called_once()
            self.assert_campaign_counts(report)
            self.assertEqual(report["session_status_counts"], {"harness_error": 1, "not_run_run_aborted": 3})
            self.assertEqual(report["unknown_session_invocations"], 1)
            self.assertEqual(report["unknown_phase_invocations"], 4)
            self.assertEqual(report["known_not_invoked_phases"], 12)
            self.assertIsNone(report["session_observations"][0]["cpu_delta_usec"])
            self.assert_blocked()

    def test_return_lost_after_complete_unit_commit_binds_diagnostics_without_promoting_metrics(self):
        original = diagnostic.run_observation

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("fixture-only lost whole-unit return after commit")

        with mock.patch.object(diagnostic, "run_observation", side_effect=lost):
            report = self.produce()
        self.assert_campaign_counts(report)
        self.assertTrue((self.output / "unit-000001-baseline/session/unit.json").exists())
        self.assertTrue(self.saved("abort.json")["diagnostic_inputs"]["files"])
        self.assertEqual(report["observed_session_count"], 0)
        self.assertEqual(report["unknown_session_invocations"], 1)
        self.assertIsNone(report["session_observations"][0]["cpu_delta_usec"])
        self.assert_blocked()

    def test_receipt_publication_failure_preserves_matching_copy_without_confirming_commit(self):
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
                        raise OSError("fixture-only paired receipt publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            self.assert_campaign_counts(report)
            self.assertFalse(report["session_observations"][0]["receipt_record_committed"])
            self.assertEqual(report["known_not_invoked_sessions"], 3)
            self.assert_blocked()

    def test_session_metadata_publication_failure_and_validation_cancellation_remain_observer_abort(self):
        original = timer.write_record
        for mode in ("error", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, value):
                if Path(path) == self.output / "block-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    raise OSError("fixture-only paired metadata publication failure")
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            self.assertFalse(report["session_observations"][0]["session_record_committed"])
            self.assert_blocked()
        self.output = self.root / "validation"
        original_inspect = pairs._inspect_unit
        calls = []

        def interrupt(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt("fixture-only paired validation cancellation")
            return original_inspect(*args, **kwargs)

        with mock.patch.object(pairs, "_inspect_unit", side_effect=interrupt):
            self.produce()
        self.assert_blocked()

    def test_abort_publication_failure_cannot_approve_unexplained_prefix(self):
        self.plans["baseline"]["interactions"][0]["argv"][-1] = "fail"
        original = timer.write_record

        def fail(path, value):
            if Path(path) == self.output / "abort.json":
                raise OSError("fixture-only abort storage failure")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            with self.assertRaises(OSError):
                self.produce()
        self.assertEqual(self.begins("candidate"), [])
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_campaign_plan_and_driver_mutation_stop_later_calls_and_do_not_repair_bindings(self):
        original = timer.write_record

        def change(path, value):
            original(path, value)
            if Path(path) == self.output / "receipt-000001-baseline.json":
                plan = self.output / "schedule.json"
                plan.write_bytes(plan.read_bytes() + b"\n")

        with mock.patch.object(timer, "write_record", side_effect=change):
            with self.assertRaisesRegex(ValueError, "abort plan byte binding"):
                self.produce()
        self.assertEqual(len(self.groups), 1)
        self.assertEqual(self.begins("candidate"), [])
        # The driver path/source hash is independently frozen for future calls.
        self.output = self.root / "changed-driver"
        calls = []
        original_run = diagnostic.run_observation

        def mutate(*args, **kwargs):
            receipt = original_run(*args, **kwargs)
            calls.append(1)
            if len(calls) == 1:
                changed_driver.write_bytes(changed_driver.read_bytes() + b"\n")
            return receipt

        changed_driver = self.root / "driver.py"
        # A no-parent campaign safely tests source freezing without launching this copy.
        shutil.copyfile(diagnostic.DRIVER, changed_driver)
        with mock.patch.object(diagnostic, "DRIVER", changed_driver), mock.patch.object(diagnostic, "run_observation", side_effect=mutate):
            report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], 2, 0, 30, pairing=self.pairing)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["session_status_counts"], {"not_run_plan_changed": 1, "not_run_run_aborted": 2, "unsupported": 1})
        self.assert_blocked()

    def test_settings_arm_plan_driver_and_output_identity_are_bound_to_each_scheduled_unit(self):
        self.produce()
        original = self.saved("schedule.json")
        receipt = self.saved("receipt-000001-baseline.json")
        record = self.saved("block-000001-baseline.json")
        for mode in ("parent", "timeout", "arm", "driver", "output"):
            plan = copy.deepcopy(original)
            if mode == "parent":
                plan["resources"]["parents"]["baseline"] = "/different/delegation"
            elif mode == "timeout":
                plan["resources"]["outer_timeout_seconds"] = 31
            elif mode == "arm":
                plan["sessions"]["baseline"]["preparation"]["argv"].append("unrequested")
            elif mode == "driver":
                plan["driver"]["sha256"] = "0" * 64
            else:
                plan["output_root"] = "/different/origin"
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "differs from paired arm"):
                pairs._inspect_unit(self.output / "unit-000001-baseline", receipt, record, plan, record["context"])

    def test_reused_private_group_or_invocation_is_rejected_not_counted_as_fresh_session(self):
        self.produce()
        unit = self.output / "unit-000001-candidate"
        originals = {path: path.read_bytes() for path in [unit / "request.json", unit / "resource.json", unit / "driver.json",
                                                        self.output / "receipt-000001-candidate.json", self.output / "block-000001-candidate.json"]}
        paths = [self.output / name / "resource.json" for name in ("unit-000001-baseline", "unit-000001-candidate")]
        first, second = (json.loads(path.read_text()) for path in paths)
        second["group"]["path"] = first["group"]["path"]
        paths[1].write_text(json.dumps(second))
        receipt_path = self.output / "receipt-000001-candidate.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["resource"].update(bytes=paths[1].stat().st_size, sha256=hashlib.sha256(paths[1].read_bytes()).hexdigest())
        receipt["retained_inputs"] = diagnostic._capture(paths[1].parent)[0]
        receipt_path.write_text(json.dumps(receipt))
        record_path = self.output / "block-000001-candidate.json"
        record = json.loads(record_path.read_text())
        record["receipt"].update(bytes=receipt_path.stat().st_size, sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest())
        record_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "group reused"):
            inspect_run(self.output)
        for path, raw in originals.items():
            path.write_bytes(raw)

        def binding(path):
            return {"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        request = json.loads((unit / "request.json").read_text())
        request["invocation_id"] = self.saved("unit-000001-baseline/request.json")["invocation_id"]
        (unit / "request.json").write_text(json.dumps(request))
        driver = json.loads((unit / "driver.json").read_text())
        driver.update(invocation_id=request["invocation_id"], request=binding(unit / "request.json"))
        (unit / "driver.json").write_text(json.dumps(driver))
        resource = json.loads((unit / "resource.json").read_text())
        resource["configuration"]["argv"] = diagnostic._command(request, binding(unit / "request.json"))
        resource["process"]["argv"][-1] = binding(unit / "request.json")["sha256"]
        transport = diagnostic._transport(request, binding(unit / "driver.json"))
        resource["process"].update(stdout_bytes=len(transport), stdout_sha256=hashlib.sha256(transport).hexdigest())
        (unit / "resource.json").write_text(json.dumps(resource))
        receipt = self.saved("receipt-000001-candidate.json")
        receipt.update(request=binding(unit / "request.json"), resource=binding(unit / "resource.json"), driver=binding(unit / "driver.json"),
                       retained_inputs=diagnostic._capture(unit)[0])
        receipt_path.write_text(json.dumps(receipt))
        record = self.saved("block-000001-candidate.json")
        record["receipt"] = binding(receipt_path)
        record_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "invocation identity reused"):
            inspect_run(self.output)

    def test_omitted_shutdown_is_rejected_after_resource_transport_and_outer_digests_are_rebound(self):
        self.produce()
        unit = self.output / "unit-000001-baseline"
        path = unit / "session/unit.json"
        sample = json.loads(path.read_text())
        sample["steps"].pop()
        path.write_text(json.dumps(sample))
        driver = json.loads((unit / "driver.json").read_text())
        driver["receipt"]["sample"].update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (unit / "driver.json").write_text(json.dumps(driver))
        receipt = self.saved("receipt-000001-baseline.json")
        receipt["driver"].update(bytes=(unit / "driver.json").stat().st_size, sha256=hashlib.sha256((unit / "driver.json").read_bytes()).hexdigest())
        resource = json.loads((unit / "resource.json").read_text())
        transport = diagnostic._transport(json.loads((unit / "request.json").read_text()), receipt["driver"])
        resource["process"].update(stdout_bytes=len(transport), stdout_sha256=hashlib.sha256(transport).hexdigest())
        (unit / "resource.json").write_text(json.dumps(resource))
        receipt["resource"].update(bytes=(unit / "resource.json").stat().st_size, sha256=hashlib.sha256((unit / "resource.json").read_bytes()).hexdigest())
        receipt["retained_inputs"] = diagnostic._capture(unit)[0]
        receipt_path = self.output / "receipt-000001-baseline.json"
        receipt_path.write_text(json.dumps(receipt))
        record = self.saved("block-000001-baseline.json")
        record["receipt"].update(bytes=receipt_path.stat().st_size, sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest())
        (self.output / "block-000001-baseline.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "omitted a planned phase"):
            inspect_run(self.output)

    def test_call_order_observer_provenance_and_early_endpoints_are_checked_without_driver_clock_alignment(self):
        self.produce()
        path = self.output / "block-000001-baseline.json"
        original = self.saved(path.name)
        changed = copy.deepcopy(original)
        changed["call_clock"]["monotonic_start_ns"] = changed["call_clock"]["monotonic_end_ns"]
        changed["call_clock"]["elapsed_ns"] = 0
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        path.write_text(json.dumps(original))
        second_path = self.output / "block-000001-candidate.json"
        second = self.saved(second_path.name)
        second["call_clock"]["monotonic_start_ns"] = original["call_clock"]["monotonic_start_ns"]
        second["call_clock"]["elapsed_ns"] = second["call_clock"]["monotonic_end_ns"] - second["call_clock"]["monotonic_start_ns"]
        second_path.write_text(json.dumps(second))
        with self.assertRaisesRegex(ValueError, "intervals overlap"):
            inspect_run(self.output)
        plan = self.saved("schedule.json")
        plan["observer_process"]["pid"] += 1
        receipt = self.saved("receipt-000001-baseline.json")
        with self.assertRaisesRegex(ValueError, "declared coordinator"):
            pairs._inspect_unit(self.output / "unit-000001-baseline", receipt, original, plan, original["context"])

    def test_missing_abort_unexpected_later_executed_units_and_false_failure_cannot_be_ignored(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        self.produce()
        path = self.output / "abort.json"
        saved = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        path.write_bytes(saved)
        shutil.copytree(self.output / "unit-000001-baseline", self.output / "unit-000001-candidate")
        with self.assertRaisesRegex(ValueError, "unexpected or missing"):
            inspect_run(self.output)

    def test_a_false_failure_abort_is_not_an_exclusion_policy(self):
        self.produce()
        row = self.report["session_observations"][-1]
        record = self.saved(pairs._names(row["context"]["block"], row["context"]["arm"])[2])
        abort = {"schema_version": 1, "kind": "paired_replay_resource_abort", "mode": "exploratory_unqualified",
                 "context": row["context"], "campaign_plan": record["campaign_plan"], "reason": "session_failed", "error": "unjustified exclusion",
                 "call_clock": None, "diagnostic_receipt": None, "diagnostic_session": None, "diagnostic_inputs": None}
        (self.output / "abort.json").write_text(json.dumps(abort))
        with self.assertRaisesRegex(ValueError, "lacks an observed failure"):
            inspect_run(self.output)

    def test_missing_records_corrupt_blobs_and_unexpected_files_do_not_become_favorable_subsets(self):
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
        next((self.output / "unit-000001-baseline/session/blobs").iterdir()).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_unresolved_declarations_missing_guards_and_truncated_raw_preserve_units_but_block_summary(self):
        original = copy.deepcopy(self.plans)
        for mode in ("pairing", "guard", "raw"):
            self.output = self.root / mode
            self.plans = copy.deepcopy(original)
            if mode == "guard":
                self.plans["baseline"]["preparation"]["guard_expectations"] = None
            elif mode == "raw":
                for plan in self.plans.values():
                    plan.update(capture_raw=True, raw_limit_bytes=4)
            report = self.produce(pairing=None if mode == "pairing" else self.pairing)
            self.assertEqual(report["session_status_counts"], {"observed_unqualified": 4})
            self.assert_blocked()

    def test_summary_rejects_subset_duplicate_reordered_or_relabelled_interaction_units(self):
        self.produce()
        inspection = inspect_run(self.output)
        rows = inspection["session_observations"]
        for mode in ("subset", "duplicate", "order", "unit"):
            changed = copy.deepcopy(rows)
            if mode == "subset":
                changed = changed[:2]
            elif mode == "duplicate":
                changed[1] = copy.deepcopy(changed[0])
            elif mode == "order":
                changed.reverse()
            else:
                changed[0]["sample_unit"] = "replay_step"
            with self.assertRaisesRegex(ValueError, "every inspected whole-session"):
                pairs.summarize(inspection, changed)
        with self.assertRaisesRegex(ValueError, "bootstrap is unsupported"):
            summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=0)

    def test_repeated_summaries_and_relocated_history_never_access_worktree_cgroup_or_commands(self):
        self.produce()
        expected = summarize_run(self.output)
        self.assertEqual(summarize_run(self.output), expected)
        for plan in self.plans.values():
            for path in Path(plan["cwd"]).glob("report-*"):
                path.unlink()
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        with mock.patch.object(diagnostic, "run_observation") as observed, mock.patch.object(resources, "CgroupDirectory") as group:
            self.assertEqual(summarize_run(moved), expected)
            observed.assert_not_called()
            group.assert_not_called()

    def test_nonregular_paths_aggregate_limits_and_fingerprint_mutation_fail_closed(self):
        self.produce()
        for attribute in ("MAX_CAMPAIGN_FILES", "MAX_CAMPAIGN_BYTES"):
            with mock.patch.object(pairs, attribute, 1):
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
        original, calls = pairs._snapshot, []

        def changed(path):
            captured = original(path)
            calls.append(1)
            if len(calls) > 1:
                captured[0]["schedule.json"]["identity"][-1] += 1  # Explicit synthetic fingerprint mutation.
            return captured

        with mock.patch.object(pairs, "_snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                inspect_run(self.output)
        self.assertEqual(len(calls), 2)

    def test_mismatched_workflow_settings_and_unsafe_cwds_fail_before_any_boundary(self):
        original = copy.deepcopy(self.plans)
        for mode in ("order", "idle", "budget", "cwd", "capture"):
            self.plans = copy.deepcopy(original)
            candidate = self.plans["candidate"]
            if mode == "order":
                candidate["interactions"].reverse()
            elif mode == "idle":
                candidate["interactions"][0]["idle_before_seconds"] = 0.1
            elif mode == "budget":
                candidate["execution_timeout_seconds"] = 19
            elif mode == "cwd":
                candidate["cwd"] = self.plans["baseline"]["cwd"]
            else:
                candidate["capture_raw"] = True
            with mock.patch.object(diagnostic, "run_observation") as observed:
                with self.assertRaises(ValueError):
                    self.produce()
                observed.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_invalid_tokens_watchdog_and_existing_outputs_stop_before_work_without_overwrite(self):
        for options in ({"outer_timeout": 29}, {"blocks": True}, {"blocks": 65}, {"allow_missing_peak": 1},
                        {"sample_interval": float("nan")}, {"pairing": {**self.pairing, "input_seed": True}}):
            with mock.patch.object(diagnostic, "run_observation") as observed:
                with self.assertRaises(ValueError):
                    self.produce(**options)
                observed.assert_not_called()
            self.assertFalse(self.output.exists())
        self.output.mkdir()
        path = self.output / "user-work"
        path.write_text("keep")
        with mock.patch.object(diagnostic, "run_observation") as observed:
            with self.assertRaises(FileExistsError):
                self.produce()
            observed.assert_not_called()
        self.assertEqual(path.read_text(), "keep")

    def test_separate_arm_parents_are_bound_not_treated_as_equal_resource_budgets(self):
        self.produce(baseline_cgroup_parent="/synthetic/baseline", candidate_cgroup_parent="/synthetic/candidate")
        self.assertEqual(self.saved("schedule.json")["resources"]["parents"], {"baseline": "/synthetic/baseline", "candidate": "/synthetic/candidate"})
        for row in self.report["session_observations"]:
            arm = row["context"]["arm"]
            request = self.saved(pairs._names(row["context"]["block"], arm)[0] + "/request.json")
            self.assertEqual(request["configuration"]["cgroup_parent"], "/synthetic/" + arm)
        self.assertIsNone(self.report["verified_independent_sessions"])
        self.assertFalse(self.report["confirmatory_eligible"])

    def test_receipt_persistence_is_observer_work_and_must_finish_before_next_session_starts(self):
        original = timer.write_record
        entered, release = threading.Event(), threading.Event()

        def hold(path, value):
            if Path(path) == self.output / "receipt-000001-baseline.json":
                entered.set()
                if not release.wait(timeout=15):
                    raise RuntimeError("parent did not release paired resource receipt persistence")
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
        record = self.saved("block-000001-baseline.json")
        receipt = self.saved("receipt-000001-baseline.json")
        self.assertLessEqual(receipt["observer_clock"]["monotonic_end_ns"], window[0])
        self.assert_covers_stage(record["receipt_publication_clock"], window)

    def test_schema_closure_strict_types_and_all_references_resolve_offline(self):
        schemas = [json.loads((HARNESS / name).read_text()) for name in (
            "paired-replay-resource-v1.schema.json", "replay-resource-v1.schema.json", "paired-replay-v1.schema.json",
            "managed-replay-v1.schema.json", "resource-observation-v1.schema.json", "lifecycle-v2.schema.json",
            "result-card-v1.schema.json", "paired-resource-v1.schema.json")]
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
        self.produce([{"missing": ["memory.peak"]}])
        plan = self.saved("schedule.json")
        for mutate in (lambda value: value.update(schema_version=True), lambda value: value.update(confirmatory_eligible=True),
                       lambda value: value["resources"].update(sample_interval_ns=1e6), lambda value: value["pairing"].update(input_seed=0.0)):
            changed = copy.deepcopy(plan)
            mutate(changed)
            with self.assertRaises(ValueError):
                pairs.validate("plan", changed)

    def test_card_tools_dispatch_resource_format_and_preserve_no_return_aborts(self):
        with mock.patch.object(diagnostic, "run_observation", side_effect=OSError("fixture-only missing return")):
            self.produce()
        # Match the CLI's import path for this new lazy card reader even when
        # this one regression is run without the card test module imported.
        with mock.patch.object(sys, "path", [str(HARNESS), *sys.path]):
            card = cards.generate_result_card(self.output)
        self.assertEqual(card["kind"], "paired_replay_resource_exploratory_result_card")
        self.assertEqual(card["denominators"]["unknown_session_invocations"], 1)
        self.assertEqual(card["denominators"]["known_not_invoked_sessions"], 3)
        self.assertEqual(card["statistics"]["status"], "blocked")
        self.assertTrue(all(value is None for value in card["qualification"]["unresolved_fields"].values()))

    def test_cli_unsupported_campaign_routes_to_inspection_and_blocked_resource_summary(self):
        paths = {}
        for arm, plan in self.plans.items():
            paths[arm] = self.root / f"{arm}.json"
            paths[arm].write_text(json.dumps(plan))
        command = [sys.executable, str(HARNESS / "paired_replay_resources.py"), "--output", str(self.output), "--blocks", "2", "--seed", "0",
                   "--outer-timeout", "30", "--baseline-plan", str(paths["baseline"]), "--candidate-plan", str(paths["candidate"])]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assert_campaign_counts(json.loads(result.stdout))
        for script, code in (("inspect_run.py", 0), ("summarize_run.py", 1)):
            result = subprocess.run([sys.executable, str(HARNESS / script), str(self.output)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assert_campaign_counts(json.loads(result.stdout))


@unittest.skipUnless(sys.platform == "linux", "native paired replay resource checks require Linux cgroup v2")
class NativePairedReplayResourceTests(PairedResourceFixture, unittest.TestCase):
    def setUp(self):
        self.prepare_pairs()
        self.parent = delegated_parent()
        if self.parent is None:
            self.skipTest("no writable delegated memory-enabled parent; no privileged setup attempted")
        probe = HARNESS / "tests/fixtures/replay_resource_probe.py"
        for plan in self.plans.values():
            plan["interactions"] = [plan["interactions"][0]]
            for role, step in replay._steps(plan):
                step["argv"] = [sys.executable, str(probe), plan["cwd"], role, "normal"]
                step["idle_before_seconds"] = 0.3 if role == "interaction" else 0
                step["required_finalization"]["artifacts"] = [self.artifact("report-" + role)]

    def native(self, **options):
        report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], 1, 1, 30, pairing=self.pairing,
                                 cgroup_parent=options.pop("cgroup_parent", self.parent), allow_missing_peak=options.pop("allow_missing_peak", True), **options)
        if all(row["status"] == "unsupported" for row in report["session_observations"]):
            self.skipTest(f"native required capabilities unavailable: {[row['unsupported_capabilities'] for row in report['session_observations']]}")
        return report, summarize_run(self.output)

    def test_native_two_arms_include_idle_workers_and_shutdown_in_distinct_removed_groups(self):
        report, summary = self.native()
        self.assert_campaign_counts(report, sessions=2, phases=6, interactions=2)
        self.assertEqual(report["observed_session_count"], 2)
        group_paths = set()
        for row in report["session_observations"]:
            arm = row["context"]["arm"]
            name = pairs._names(1, arm)[0]
            raw = json.loads((self.output / name / "resource.json").read_text())
            group_paths.add(raw["group"]["path"])
            self.assertTrue(raw["group"]["removed"])
            self.assertFalse(Path(raw["group"]["path"]).exists())
            self.assertEqual(raw["snapshots"]["final"]["population"], 0)
            self.assertFalse(raw["cleanup"]["kill_requested"])
            self.assertEqual(row["session_status"], "completed_unqualified")
            cwd = Path(self.plans[arm]["cwd"])
            prepared = json.loads((cwd / "preparation.progress").read_text())
            interacted = json.loads((cwd / "interaction.progress").read_text())
            self.assertGreater(interacted["cpu_ns"] - prepared["cpu_ns"], 100_000_000)
            self.assertGreaterEqual(row["sampled_current_max_bytes"], 64 * 1024 * 1024)
            self.assertGreaterEqual(row["cpu_delta_usec"]["usage_usec"], 300000)
            if not raw["capabilities"]["memory_peak"]["supported"]:
                self.assertEqual(row["status"], "partial_unsupported")
                self.assertIsNone(row["peak_charged_bytes"])
                self.assertEqual(summary["status"], "blocked")
        self.assertEqual(len(group_paths), 2)

    def test_native_leftover_worker_fails_and_other_arm_remains_not_run(self):
        self.plans["baseline"]["shutdown"]["argv"][-1] = "leave_worker"
        report, summary = self.native(cleanup_grace=0.01)
        self.assert_campaign_counts(report, sessions=2, phases=6, interactions=2)
        self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 1})
        row = report["session_observations"][0]
        self.assertEqual(row["session_status"], "completed_unqualified")
        self.assertIn("background_work_outlived_command", row["resource_failure_reasons"])
        raw = json.loads((self.output / "unit-000001-baseline/resource.json").read_text())
        self.assertTrue(raw["cleanup"]["kill_requested"])
        self.assertTrue(raw["group"]["removed"])
        self.assertEqual(list(Path(self.plans["candidate"]["cwd"]).iterdir()), [])
        self.assertEqual(summary["status"], "blocked")

    def test_native_unsupported_baseline_does_not_prevent_partial_candidate_session(self):
        report, summary = self.native(cgroup_parent=None, candidate_cgroup_parent=self.parent)
        self.assert_campaign_counts(report, sessions=2, phases=6, interactions=2)
        self.assertEqual(report["session_observations"][0]["status"], "unsupported")
        self.assertEqual(report["session_observations"][1]["session_status"], "completed_unqualified")
        self.assertIsNone(report["session_observations"][0]["cpu_delta_usec"])
        self.assertEqual(report["record_consistency"], "complete")
        self.assertEqual(summary["status"], "blocked")

    def test_native_strict_missing_peak_keeps_all_sessions_not_invoked_with_no_metrics(self):
        report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], 1, 1, 30, pairing=self.pairing, cgroup_parent=self.parent)
        self.assert_campaign_counts(report, sessions=2, phases=6, interactions=2)
        for row in report["session_observations"]:
            if row["unsupported_capabilities"] and "memory_peak" in row["unsupported_capabilities"]:
                self.assertEqual(row["status"], "unsupported")
                self.assertIsNone(row["cpu_delta_usec"])
                self.assertIsNone(row["peak_charged_bytes"])
                self.assertFalse(row["session_invocation_attempted"])
        self.assertFalse(report["confirmatory_eligible"])

    def test_native_cancellation_keeps_unknown_first_session_and_later_not_run_with_owned_cleanup(self):
        def cancel(process, timeout, capture=None):
            deadline = time.monotonic() + 10
            while not (self.cwd / "worker.progress").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("native worker did not become resident before cancellation")
                time.sleep(0.01)
            raise KeyboardInterrupt("fixture-only cancellation of the first paired resource session")

        with mock.patch.object(timer, "_stream_posix", side_effect=cancel):
            report, summary = self.native(cleanup_grace=0.01)
        self.assert_campaign_counts(report, sessions=2, phases=6, interactions=2)
        self.assertEqual(report["session_status_counts"], {"failed": 1, "not_run_run_aborted": 1})
        self.assertEqual(report["session_observations"][0]["session_status"], "unknown")
        self.assertEqual(report["unknown_session_invocations"], 1)
        self.assertEqual(report["unknown_phase_invocations"], 3)
        self.assertIsNone(report["session_observations"][0]["shutdown_status"])
        self.assertEqual(summary["status"], "blocked")
        raw = json.loads((self.output / "unit-000001-baseline/resource.json").read_text())
        self.assertTrue(raw["cleanup"]["kill_requested"])
        self.assertTrue(raw["group"]["removed"])
        self.assertEqual(raw["snapshots"]["final"]["population"], 0)


if __name__ == "__main__":
    unittest.main()
