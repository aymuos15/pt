"""Real file/process paired controls; fault injections do not qualify a PT backend."""

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import test_scenario_replay as controls


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import paired_scenarios as pairs
    import scenario_replay as scenario
    import scenario_inputs as inputs
    import pt_bench as timer
    import result_card as cards
    from inspect_run import inspect_run
    from summarize_run import summarize_run
    from schedule import paired_schedule
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux safe scenario/blob profile")
class PairedScenarioTests(unittest.TestCase):
    def setUp(self):
        # Composition avoids rediscovering the standalone test class here.
        self.fixture = controls.ScenarioReplayTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.payloads, self.output = self.fixture.root, self.fixture.payloads, self.fixture.output
        self.plans = {arm: copy.deepcopy(self.fixture.plan) for arm in pairs.ARMS}
        candidate = self.root / "candidate"
        shutil.copytree(self.fixture.cwd, candidate)
        (candidate / "source.txt").write_text("candidate dirty\n")
        self.plans["candidate"]["cwd"] = str(candidate)

    def produce(self, *, blocks=2, seed=None, apply=True):
        # Seed 1 selects AB for an odd block; seed 0 balances AB/BA for two.
        seed = (1 if blocks == 1 else 0) if seed is None else seed
        self.report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], self.payloads, blocks, seed, apply=apply)
        self.assert_counts(self.report, blocks=blocks)
        return self.report

    def assert_counts(self, report, *, blocks=2):
        sessions = 2 * blocks
        self.assertEqual(report["planned_session_count"], sessions)
        self.assertEqual(len(report["session_observations"]), sessions)
        self.assertEqual(sum(report["session_status_counts"].values()), sessions)
        self.assertEqual(report["attempted_unit_calls"] + report["known_not_called_units"], sessions)
        self.assertEqual(report["observed_session_count"] + report["unconfirmed_unit_calls"], report["attempted_unit_calls"])
        for noun, count in (("request", 2), ("phase", 6), ("file_effect", 12)):
            self.assertEqual(report[f"planned_{noun}_count"], sessions * count)
            self.assertEqual(sum(report[f"{noun}_status_counts"].values()), sessions * count)
        self.assertEqual(sum(report[key] for key in ("known_request_invocations", "unknown_request_invocations", "known_not_invoked_requests")), 2 * sessions)
        self.assertEqual(sum(report[key] for key in ("known_shutdown_invocations", "unknown_shutdown_invocations", "known_not_invoked_shutdowns")), sessions)
        self.assertEqual(sum(report["reset_status_counts"].values()), sessions)
        self.assertEqual(report["qualification"], {key: None for key in scenario.QUALIFICATION})
        self.assertFalse(report["confirmatory_eligible"])
        for row in report["session_observations"]:
            for noun in ("request", "phase", "file_effect"):
                self.assertEqual(row[f"planned_{noun}_count"], sum(row[f"{noun}_status_counts"].values()))
            self.assertEqual(len(row["request_observations"]), 2)

    def summary(self, *, blocks=2, blocked=True):
        summary = summarize_run(self.output)
        self.assert_counts(summary, blocks=blocks)
        self.assertEqual(summary["status"], "blocked" if blocked else "declared_file_scenario_observations")
        for key in ("ratio", "absolute_latency_ns", "bootstrap", "resource_observation"):
            self.assertIsNone(summary[key])
        return summary

    def saved(self, name):
        return json.loads((self.output / name).read_text())

    def save(self, name, value):
        path = self.output / name
        path.write_text(json.dumps(value))
        return {"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def events(self, arm):
        path = Path(self.plans[arm]["cwd"]) / "events"
        return [line.split(":")[:2] for line in path.read_text().splitlines()] if path.exists() else []

    def rebind_unit(self, unit):
        directory = self.output / "session-000001-baseline"
        unit["retained_inputs"] = scenario._inputs(directory)[0]
        receipt = self.saved("receipt-000001-baseline.json")
        receipt["unit"] = self.save("session-000001-baseline/unit.json", unit)
        record = self.saved("block-000001-baseline.json")
        record["receipt"] = self.save("receipt-000001-baseline.json", receipt)
        self.save("block-000001-baseline.json", record)

    def test_complete_balanced_campaign_retains_each_arms_actual_reset_and_input_bytes(self):
        report = self.produce()
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 4})
        self.assertEqual(report["schedule"], paired_schedule(2, 0))
        self.assertEqual({tuple(block["order"]) for block in report["schedule"]}, {pairs.ARMS, tuple(reversed(pairs.ARMS))})
        summary = self.summary(blocked=False)
        for arm in pairs.ARMS:
            self.assertEqual(self.events(arm), [["request", "first"], ["request", "second"], ["shutdown", "shutdown"]] * 2)
            self.assertEqual(summary["per_arm"][arm], {"planned_sessions": 2, "observed_sessions": 2, "completed_scenarios": 2,
                                                        "matched_declared_resets": 2, "observed_input_payloads": 4})
        reset_before = []
        for row in report["session_observations"]:
            reset = row["reset_evidence"]
            self.assertEqual(inputs.values(reset["after"]), scenario._states(self.plans[row["context"]["arm"]])[0])
            reset_before.append(reset["before"]["files"][-1]["value"]["sha256"])
            for request in row["request_observations"]:
                self.assertEqual(request["observed_input"]["value"], request["expected_input"])
                self.assertEqual(request["input_delivery_status"], "applied")
        self.assertNotEqual(reset_before[0], reset_before[1])
        self.assertEqual(inspect_run(self.output), report)

    def test_shared_payloads_are_frozen_once_before_any_arm_and_source_is_not_reopened(self):
        original = scenario.run_scenario
        calls = []

        def run(output, plan, payloads, **kwargs):
            self.assertEqual(payloads, self.output / "payloads")
            if not calls:
                frozen = pairs.capture_run(payloads)[0]
                self.assertEqual(frozen, self.saved("schedule.json")["frozen_payloads"])
                for path in self.payloads.iterdir():
                    path.write_bytes(b"later source corruption")
            calls.append(1)
            return original(output, plan, payloads, **kwargs)

        with mock.patch.object(scenario, "run_scenario", side_effect=run):
            self.produce()
        self.assertEqual(len(calls), 4)
        self.summary(blocked=False)

    def test_odd_seeded_ba_order_is_preserved_and_failure_stops_before_baseline(self):
        self.plans["candidate"]["requests"][0]["command"]["argv"][-1] = "fail"
        report = self.produce(blocks=1, seed=0)
        self.assertEqual(report["schedule"][0]["order"], ["candidate", "baseline"])
        self.assertEqual(report["session_observations"][0]["context"]["arm"], "candidate")
        self.assertEqual(self.events("baseline"), [])
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 1})
        self.summary(blocks=1)

    def test_arm_commands_may_differ_but_are_exactly_bound_not_replaced_by_shared_workflow(self):
        for request in self.plans["candidate"]["requests"]:
            request["command"]["argv"].append("candidate-only argument")
        self.produce(blocks=1)
        row = self.report["session_observations"][1]
        receipt = self.saved("receipt-000001-candidate.json")
        record = self.saved("block-000001-candidate.json")
        changed = copy.deepcopy(self.plans["candidate"])
        changed["requests"][0]["command"]["argv"].append("unrequested")
        self.assertEqual(row["status"], "completed_unqualified")
        with self.assertRaisesRegex(ValueError, "exact paired arm"):
            pairs._inspect_session(self.output / "session-000001-candidate", receipt, record, changed)

    def test_mismatched_scenario_cache_reset_edit_seed_inputs_and_budgets_fail_before_effects(self):
        original = copy.deepcopy(self.plans)
        for mode in ("scenario", "cache", "reset", "mode", "edit", "seed", "payload", "request_order", "budget", "timeout", "exit", "shutdown_timeout"):
            self.plans = copy.deepcopy(original)
            plan = self.plans["candidate"]
            if mode == "scenario":
                plan["scenario"]["id"] = "S4"
            elif mode == "cache":
                plan["scenario"]["cache_state"]["source"] = "edited"
            elif mode in ("reset", "mode"):
                value = self.fixture.value(b"different\n") if mode == "reset" else {**self.fixture.old, "mode": 0o640}
                plan["reset"][-1]["value"] = value
                plan["requests"][0]["edits"][-1]["before"] = value
            elif mode == "edit":
                plan["requests"][1]["edits"][-1]["after"] = self.fixture.new
            elif mode == "seed":
                plan["input_seed"] = 18
            elif mode == "payload":
                plan["requests"][0]["input"] = self.fixture.payload("first", {"other": "bytes"})
            elif mode == "request_order":
                plan["requests"].reverse()
            elif mode == "budget":
                plan["execution_timeout_seconds"] = 19
            elif mode == "timeout":
                plan["requests"][0]["command"]["timeout_seconds"] = 4
            elif mode == "exit":
                command = plan["requests"][0]["command"]
                command["guard_expectations"]["expected_exit_code"] = command["required_finalization"]["expected_exit_code"] = 7
            else:
                plan["shutdown"]["timeout_seconds"] = 4
            with self.subTest(mode=mode), mock.patch.object(scenario, "run_scenario") as called:
                with self.assertRaises(ValueError):
                    self.produce()
                called.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_invalid_seed_or_corrupt_last_payload_is_rejected_before_output_and_reset(self):
        for mode in ("seed", "corrupt"):
            for plan in self.plans.values():
                request = plan["requests"][-1]
                request["input"] = self.fixture.payload("second", {}, seed=18 if mode == "seed" else 17)
            if mode == "corrupt":
                (self.payloads / request["input"]["value"]["sha256"]).write_bytes(b"bad")
            with mock.patch.object(scenario, "run_scenario") as called:
                with self.assertRaises(ValueError):
                    self.produce()
                called.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_explicit_apply_valid_tokens_and_separate_roots_are_required_before_any_unit(self):
        for options in ({"apply": False}, {"apply": 1}, {"blocks": True}, {"blocks": 65}, {"blocks": 0}, {"seed": True}, {"seed": 0.0}):
            with mock.patch.object(scenario, "run_scenario") as called:
                with self.assertRaises(ValueError):
                    self.produce(**options)
                called.assert_not_called()
            self.assertFalse(self.output.exists())
        for cwd in (self.plans["baseline"]["cwd"], str(Path(self.plans["baseline"]["cwd"]) / "nested"), str(self.payloads)):
            self.plans["candidate"]["cwd"] = cwd
            Path(cwd).mkdir(exist_ok=True)
            with self.assertRaises(ValueError):
                self.produce()
        self.assertFalse(self.output.exists())

    def test_existing_output_and_overlapping_evidence_are_never_overwritten(self):
        self.output = Path(self.plans["baseline"]["cwd"]) / "evidence"
        with self.assertRaisesRegex(ValueError, "separate"):
            self.produce()
        self.output = self.root / "existing"
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with mock.patch.object(scenario, "run_scenario") as called:
            with self.assertRaises(FileExistsError):
                self.produce()
            called.assert_not_called()
        self.assertEqual((self.output / "user-work").read_text(), "keep")

    def test_clean_unsupported_profiles_continue_every_unit_but_report_no_effects_or_inputs(self):
        for label in ("S6", "S7", "S9"):
            self.output = self.root / label
            for plan in self.plans.values():
                plan["scenario"]["id"] = label
            with mock.patch.object(inputs, "mutate") as mutated, mock.patch.object(timer, "measure_and_publish") as launched:
                report = self.produce()
                mutated.assert_not_called()
                launched.assert_not_called()
            self.assertEqual(report["session_status_counts"], {"unsupported": 4})
            self.assertEqual(report["request_status_counts"], {"not_run_unsupported": 8})
            self.assertEqual(report["file_effect_status_counts"], {"not_run": 48})
            self.assertEqual(report["known_not_invoked_shutdowns"], 4)
            self.assertEqual(report["record_consistency"], "complete")
            self.assertTrue(all(row["observed_input"] is None for session in report["session_observations"] for row in session["request_observations"]))
            self.summary()

    def test_failed_request_keeps_failed_not_run_and_later_sessions_without_retry(self):
        self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "fail"
        report = self.produce()
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
        self.assertEqual(report["request_status_counts"], {"failed": 1, "not_run_campaign_aborted": 6, "not_run_prior_failure": 1})
        self.assertEqual(self.events("baseline"), [["request", "first"], ["shutdown", "shutdown"]])
        self.assertEqual(self.events("candidate"), [])
        self.assertEqual(self.saved("abort.json")["reason"], "session_failed")
        self.summary()

    def test_later_arm_failure_keeps_prior_complete_reset_and_input_observations(self):
        self.plans["candidate"]["requests"][0]["command"]["argv"][-1] = "fail"
        report = self.produce()
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "completed_unqualified": 1, "not_run_campaign_aborted": 2})
        summary = self.summary()
        self.assertEqual(summary["per_arm"]["baseline"]["matched_declared_resets"], 1)
        self.assertEqual(summary["per_arm"]["baseline"]["observed_input_payloads"], 2)
        self.assertEqual(summary["per_arm"]["candidate"]["observed_input_payloads"], 1)

    def test_expected_nonzero_outcomes_are_not_test_passes_or_latency_samples(self):
        for plan in self.plans.values():
            command = plan["requests"][0]["command"]
            command["argv"][-1] = "fail"
            command["guard_expectations"]["expected_exit_code"] = command["required_finalization"]["expected_exit_code"] = 7
        self.produce(blocks=1)
        self.summary(blocks=1, blocked=False)

    def test_partial_reset_or_edit_return_loss_keeps_installed_bytes_and_all_effect_denominators(self):
        original = inputs.mutate
        for mode in ("reset", "edit"):
            self.output = self.root / mode
            calls = []

            def fail(root, observed, desired, bundle):
                calls.append(observed["path"])
                result = original(root, observed, desired, bundle)
                if observed["path"] == "source.txt" and (mode == "reset" or len(calls) > 4):
                    raise OSError("fixture-only file effect return lost after install")
                return result

            with mock.patch.object(inputs, "mutate", side_effect=fail):
                report = self.produce()
            self.assertEqual(report["file_effect_status_counts"]["unknown"], 1)
            self.assertEqual(report["known_request_invocations"], 0)
            self.assertEqual(report["known_shutdown_invocations"], 1)
            self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
            row = report["session_observations"][0]
            self.assertIsNotNone(row["reset_evidence"]["after"])
            if mode == "edit":
                self.assertEqual(row["file_effect_status_counts"]["not_run"], 4)
            self.summary()

    def test_subject_mutation_of_tracked_inputs_is_not_hidden_by_matching_output(self):
        self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "mutate"
        report = self.produce()
        row = report["session_observations"][0]
        self.assertEqual(row["request_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual(row["request_observations"][0]["observed_input"]["value"], row["request_observations"][0]["expected_input"])
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
        self.summary()

    def test_shutdown_failure_hang_unreleased_state_and_deadline_block_all_later_sessions(self):
        for mode in ("fail", "hang", "unreleased", "deadline"):
            self.output = self.root / mode
            self.plans["baseline"]["shutdown"]["argv"][-1] = "normal" if mode == "deadline" else mode
            for plan in self.plans.values():
                plan["shutdown"]["timeout_seconds"] = 0.05 if mode == "hang" else 5
                plan["execution_timeout_seconds"] = 0.001 if mode == "deadline" else 20
            report = self.produce()
            self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
            self.assertEqual(report["session_observations"][0]["shutdown_status"], "observed_unqualified" if mode == "deadline" else "failed")
            self.summary()

    def test_inner_command_return_loss_remains_one_unknown_request_not_a_lost_whole_unit(self):
        original, calls = timer.measure_and_publish, []

        def lost(*args, **kwargs):
            receipt = original(*args, **kwargs)
            calls.append(1)
            if len(calls) == 1:
                raise OSError("fixture-only inner request return lost after commit")
            return receipt

        with mock.patch.object(timer, "measure_and_publish", side_effect=lost):
            report = self.produce()
        self.assertEqual(report["observed_session_count"], 1)
        self.assertEqual(report["unknown_request_invocations"], 1)
        self.assertEqual(report["unconfirmed_unit_calls"], 0)
        self.assertEqual(report["session_observations"][0]["request_status_counts"], {"not_run_prior_failure": 1, "unknown": 1})
        self.assertEqual(report["session_observations"][0]["reset_status"], "observed_unqualified")
        self.summary()

    def test_whole_unit_return_loss_before_or_after_commit_never_recovers_resets_or_inputs(self):
        original = scenario.run_scenario
        for mode in ("before", "after", "interrupt"):
            self.output = self.root / mode

            def lost(*args, **kwargs):
                if mode == "after":
                    original(*args, **kwargs)
                if mode == "interrupt":
                    raise KeyboardInterrupt("fixture-only whole-unit cancellation")
                raise OSError("fixture-only whole-unit return lost")

            with mock.patch.object(scenario, "run_scenario", side_effect=lost) as invoked:
                report = self.produce()
                invoked.assert_called_once()
            self.assertEqual(report["session_status_counts"], {"harness_error": 1, "not_run_campaign_aborted": 3})
            self.assertEqual(report["request_status_counts"], {"not_run_campaign_aborted": 6, "unknown_unobserved": 2})
            self.assertEqual(report["phase_status_counts"], {"not_run_campaign_aborted": 18, "unknown_unobserved": 6})
            self.assertEqual(report["file_effect_status_counts"], {"not_run": 36, "unknown_unobserved": 12})
            self.assertEqual(report["unknown_request_invocations"], 2)
            self.assertEqual(report["unknown_shutdown_invocations"], 1)
            row = report["session_observations"][0]
            self.assertIsNone(row["reset_evidence"])
            self.assertTrue(all(request["observed_input"] is None for request in row["request_observations"]))
            self.assertEqual(self.saved("abort.json")["diagnostic_inputs"] is not None, mode == "after")
            self.assertEqual((self.output / "session-000001-baseline/unit.json").exists(), mode == "after")
            self.summary()

    def test_unconfirmed_inner_unit_publication_keeps_returned_observations_but_aborts_campaign(self):
        original = timer.write_record

        def fail(path, value):
            original(path, value)
            if Path(path) == self.output / "session-000001-baseline/unit.json":
                raise OSError("fixture-only scenario unit publication return lost")

        with mock.patch.object(timer, "write_record", side_effect=fail):
            report = self.produce()
        self.assertEqual(report["observed_session_count"], 1)
        self.assertEqual(report["known_request_invocations"], 2)
        self.assertEqual(report["session_observations"][0]["reset_status"], "observed_unqualified")
        self.assertEqual(report["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
        self.summary()

    def test_receipt_publication_failures_do_not_erase_observations_or_confirm_visible_commits(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, value):
                if Path(path) == self.output / "receipt-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode != "omit":
                        raise OSError("fixture-only paired receipt publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            row = report["session_observations"][0]
            self.assertEqual(row["status"], "completed_unqualified")
            self.assertFalse(row["receipt_record_committed"])
            self.assertFalse(row["session_record_committed"])
            self.assertEqual(report["known_request_invocations"], 2)
            self.assertEqual(report["record_consistency"], "aborted")
            self.summary()

    def test_metadata_publication_failure_or_validation_cancellation_never_runs_next_unit(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong", "validation"):
            self.output = self.root / mode
            calls = []
            original_inspect = pairs._inspect_session

            def validate(*args, **kwargs):
                calls.append(1)
                if mode == "validation" and len(calls) == 1:
                    raise KeyboardInterrupt("fixture-only paired validation interruption")
                return original_inspect(*args, **kwargs)

            def fail(path, value):
                if mode != "validation" and Path(path) == self.output / "block-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode != "omit":
                        raise OSError("fixture-only metadata publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail), mock.patch.object(pairs, "_inspect_session", side_effect=validate):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.produce()
                    continue
                report = self.produce()
            row = report["session_observations"][0]
            self.assertTrue(row["receipt_record_committed"])
            self.assertFalse(row["session_record_committed"])
            self.assertEqual(report["known_not_called_units"], 3)
            self.summary()

    def test_abort_publication_failure_leaves_an_unexplained_prefix_not_approval(self):
        self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "fail"
        original = timer.write_record

        def fail(path, value):
            if Path(path) == self.output / "abort.json":
                raise OSError("fixture-only abort storage failure")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            with self.assertRaises(OSError):
                self.produce()
        self.assertEqual(self.events("candidate"), [])
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_frozen_plan_or_payload_mutation_stops_next_call_without_repair(self):
        original = scenario.run_scenario
        for mode in ("plan", "payload", "identity"):
            self.output = self.root / mode
            calls = []

            def change(*args, **kwargs):
                receipt = original(*args, **kwargs)
                calls.append(1)
                if len(calls) == 1:
                    path = self.output / "schedule.json" if mode == "plan" else next((self.output / "payloads").iterdir())
                    if mode == "identity":
                        raw = path.read_bytes()
                        path.unlink()
                        path.write_bytes(raw)
                    else:
                        path.write_bytes(path.read_bytes() + b"\n")
                return receipt

            with mock.patch.object(scenario, "run_scenario", side_effect=change):
                if mode != "identity":
                    with self.assertRaises(ValueError):
                        self.produce()
                else:
                    report = self.produce()
                    self.assertEqual(report["session_status_counts"], {"completed_unqualified": 1, "not_run_campaign_aborted": 2, "not_run_plan_changed": 1})
                    self.summary()
            self.assertEqual(len(calls), 1)
            self.assertEqual(self.saved("abort.json")["reason"], "plan_binding_failed")

    def test_missing_abort_or_later_evidence_after_failure_is_not_a_favorable_subset(self):
        self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "fail"
        self.produce()
        abort = (self.output / "abort.json").read_bytes()
        (self.output / "abort.json").unlink()
        with self.assertRaises(ValueError):
            inspect_run(self.output)
        (self.output / "abort.json").write_bytes(abort)
        shutil.copytree(self.output / "session-000001-baseline", self.output / "session-000001-candidate")
        with self.assertRaisesRegex(ValueError, "work after abort"):
            inspect_run(self.output)

    def test_false_failure_abort_cannot_exclude_a_complete_session(self):
        self.produce(blocks=1)
        record = self.saved("block-000001-candidate.json")
        self.save("abort.json", {"schema_version": 1, "kind": "paired_scenario_abort", "mode": "exploratory_unqualified",
                                 "context": record["context"], "campaign_plan": record["campaign_plan"], "reason": "session_failed", "error": "unjustified exclusion",
                                 "call_clock": None, "diagnostic_receipt": None, "diagnostic_session": None, "diagnostic_inputs": None})
        with self.assertRaisesRegex(ValueError, "lacks an observed failed unit"):
            inspect_run(self.output)

    def test_lost_whole_return_diagnostics_are_inventory_bound_without_scenario_reconstruction(self):
        original = scenario.run_scenario

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("fixture-only lost return")

        with mock.patch.object(scenario, "run_scenario", side_effect=lost):
            self.produce()
        with mock.patch.object(scenario, "inspect_scenario", side_effect=AssertionError("recovered lost return")):
            self.summary()
        (self.output / "session-000001-baseline/extra.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "diagnostic inventory differs"):
            inspect_run(self.output)

    def test_abort_context_and_missing_return_bookkeeping_cannot_invent_observed_or_skipped_work(self):
        with mock.patch.object(scenario, "run_scenario", side_effect=OSError("fixture-only whole-unit return loss")):
            self.produce()
        original = self.saved("abort.json")
        for mode in ("clock", "context", "diagnostic", "reason"):
            value = copy.deepcopy(original)
            if mode == "clock":
                value["call_clock"] = None
            elif mode == "context":
                value["context"]["block"] = 64
            elif mode == "diagnostic":
                value["diagnostic_inputs"] = self.saved("schedule.json")["frozen_payloads"]
            else:
                value["reason"] = "plan_binding_failed"
            self.save("abort.json", value)
            with self.subTest(mode=mode), self.assertRaises((ValueError, OSError)):
                inspect_run(self.output)

    def test_each_paired_pytest_request_has_one_import_collection_and_call_in_a_fresh_process(self):
        raw = (b"import json,os\nfrom pathlib import Path\n"
               b"with Path('imports').open('a') as stream: stream.write(str(os.getpid())+'\\n')\n"
               b"def test_input():\n"
               b"    p=json.loads(Path('request.json').read_text())\n"
               b"    assert Path('source.txt').read_text()==p['data']['source.txt']\n"
               b"    with Path('calls').open('a') as stream: stream.write(p['request_id']+'\\n')\n")
        value = self.fixture.value(raw)
        for plan in self.plans.values():
            plan["reset"].append({"path": "test_case.py", "value": value})
            plan["reset"].sort(key=lambda item: item["path"])
            for request in plan["requests"]:
                request["command"].update(argv=[sys.executable, "-m", "pytest", "-q", "test_case.py"], guard_expectations=None,
                                          required_finalization={"expected_exit_code": 0, "artifacts": [], "absent": []})
        # Both arms share the same explicit fixture-only plugin environment.
        with mock.patch.dict(os.environ, {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}):
            report = pairs.run_pairs(self.output, self.plans["baseline"], self.plans["candidate"], self.payloads, 1, 0, apply=True)
        self.assertEqual(report["planned_file_effect_count"], 26)
        self.assertEqual(sum(report["file_effect_status_counts"].values()), 26)
        self.assertEqual(report["session_status_counts"], {"completed_unqualified": 2})
        pids = []
        for plan in self.plans.values():
            cwd = Path(plan["cwd"])
            pids.extend((cwd / "imports").read_text().splitlines())
            self.assertEqual((cwd / "calls").read_text().splitlines(), ["first", "second"])
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(pids), 4)
        self.assertIsNone(report["qualification"]["actual_loaded_code"])

    def test_omitted_reset_transition_request_shutdown_or_input_snapshots_fail_after_rebinding(self):
        self.produce(blocks=1)
        original = self.saved("session-000001-baseline/unit.json")
        for mode in ("reset", "transition", "request", "shutdown", "snapshot", "operation_order"):
            unit = copy.deepcopy(original)
            if mode in ("reset", "transition", "request", "shutdown"):
                unit["phases"].pop({"reset": 0, "transition": 1, "request": 2, "shutdown": 5}[mode])
            elif mode == "snapshot":
                unit["phases"][2]["before"]["files"].pop()
            else:
                unit["phases"][1]["operations"].reverse()
            self.rebind_unit(unit)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                inspect_run(self.output)

    def test_wrong_pre_request_bytes_are_not_reset_success_after_digest_rebinding(self):
        self.produce(blocks=1)
        unit = self.saved("session-000001-baseline/unit.json")
        unit["phases"][2]["before"]["files"][-1]["value"] = self.fixture.old
        self.rebind_unit(unit)
        with self.assertRaisesRegex(ValueError, "state mismatch"):
            inspect_run(self.output)

    def test_missing_receipts_extra_files_and_corrupt_or_unlisted_payloads_are_rejected(self):
        self.produce(blocks=1)
        path = self.output / "receipt-000001-baseline.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            inspect_run(self.output)
        path.write_bytes(raw)
        for extra in (self.output / "extra.json", self.output / "payloads/extra"):
            extra.write_text("{}")
            with self.assertRaises(ValueError):
                inspect_run(self.output)
            extra.unlink()
        next((self.output / "payloads").iterdir()).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "frozen payload bytes differ"):
            inspect_run(self.output)

    def test_call_enclosure_publication_order_and_later_call_overlap_are_checked(self):
        self.produce(blocks=1)
        name = "block-000001-baseline.json"
        original = self.saved(name)
        for mode in ("enclosure", "publication"):
            value = copy.deepcopy(original)
            clock = value["call_clock" if mode == "enclosure" else "receipt_publication_clock"]
            if mode == "enclosure":
                clock["monotonic_start_ns"] = clock["monotonic_end_ns"]
                clock["elapsed_ns"] = 0
            else:
                clock["monotonic_start_ns"] = original["call_clock"]["monotonic_start_ns"]
                clock["elapsed_ns"] = clock["monotonic_end_ns"] - clock["monotonic_start_ns"]
            self.save(name, value)
            with self.assertRaises(ValueError):
                inspect_run(self.output)
        self.save(name, original)
        value = self.saved("block-000001-candidate.json")
        value["call_clock"]["monotonic_start_ns"] = original["call_clock"]["monotonic_start_ns"]
        value["call_clock"]["elapsed_ns"] = value["call_clock"]["monotonic_end_ns"] - value["call_clock"]["monotonic_start_ns"]
        self.save("block-000001-candidate.json", value)
        with self.assertRaisesRegex(ValueError, "overlap"):
            inspect_run(self.output)

    def test_changed_context_plan_or_receipt_binding_cannot_relabel_arms(self):
        self.produce(blocks=1)
        original = self.saved("block-000001-baseline.json")
        for mode in ("arm", "position", "plan", "receipt"):
            value = copy.deepcopy(original)
            if mode == "arm":
                value["context"]["arm"] = "candidate"
            elif mode == "position":
                value["context"]["position"] = 2
            else:
                value["campaign_plan" if mode == "plan" else "receipt"]["sha256"] = "0" * 64
            self.save("block-000001-baseline.json", value)
            with self.assertRaisesRegex(ValueError, "context, plan or receipt binding"):
                inspect_run(self.output)

    def test_summary_rejects_subset_duplicates_reordering_and_phase_relabelling(self):
        self.produce()
        rows = self.report["session_observations"]
        for mode in ("subset", "duplicate", "order", "unit", "reset", "input"):
            values = copy.deepcopy(rows)
            if mode == "subset":
                values.pop()
            elif mode == "duplicate":
                values[1] = copy.deepcopy(values[0])
            elif mode == "order":
                values.reverse()
            elif mode == "unit":
                values[0]["sample_unit"] = "replay_step"
            elif mode == "reset":
                values[0]["reset_evidence"] = None
            else:
                values[0]["request_observations"].pop()
            with self.assertRaisesRegex(ValueError, "every inspected session"):
                pairs.summarize(self.report, values)
        with self.assertRaisesRegex(ValueError, "bootstrap is unsupported"):
            summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=0)

    def test_scenario_campaign_cannot_be_relabelled_as_existing_latency_or_resource_card(self):
        self.produce(blocks=1)
        with self.assertRaisesRegex(ValueError, "not a latency/resource result-card"):
            cards.generate_result_card(self.output)

    def test_repeated_summaries_relocate_without_live_worktree_reads_or_subject_execution(self):
        self.produce(blocks=1)
        expected = self.summary(blocks=1, blocked=False)
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        for plan in self.plans.values():
            (Path(plan["cwd"]) / "source.txt").write_text("later unrelated state")
        with mock.patch.object(inputs, "read", side_effect=AssertionError("live read")), mock.patch.object(scenario, "run_scenario") as run, mock.patch.object(inputs, "mutate") as mutate:
            self.assertEqual(summarize_run(moved), expected)
            self.assertEqual(summarize_run(self.output), expected)
            run.assert_not_called()
            mutate.assert_not_called()

    def test_nonregular_paths_and_aggregate_limits_fail_closed_not_truncated(self):
        self.produce(blocks=1)
        for setting in ("MAX_FILES", "MAX_BYTES"):
            with mock.patch.object(pairs, setting, 1):
                with self.assertRaisesRegex(ValueError, "aggregate file/byte limit"):
                    inspect_run(self.output)
        alias = self.root / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            inspect_run(alias)
        os.mkfifo(self.output / "fifo")
        with self.assertRaises(ValueError):
            inspect_run(self.output)

    def test_declared_repeated_input_artifact_budget_fails_before_output_and_units(self):
        with mock.patch.object(pairs, "MAX_DECLARED_BYTES", 1), mock.patch.object(scenario, "run_scenario") as invoked:
            with self.assertRaisesRegex(ValueError, "repeated declared"):
                self.produce()
            invoked.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_inspection_identity_changes_are_rejected_without_retry(self):
        self.produce(blocks=1)
        original, calls = pairs._snapshot, []

        def changed(path):
            captured = original(path)
            calls.append(1)
            if len(calls) > 1:
                captured[0]["schedule.json"]["identity"][-1] += 1
            return captured

        with mock.patch.object(pairs, "_snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                inspect_run(self.output)
        self.assertEqual(len(calls), 2)

    def test_schedule_and_workflow_digest_cannot_be_changed_independently_of_frozen_arms(self):
        self.produce(blocks=1)
        plan = self.saved("schedule.json")
        for mode in ("schedule", "digest", "payload_inventory"):
            value = copy.deepcopy(plan)
            if mode == "schedule":
                value["schedule"][0]["order"].reverse()
            elif mode == "digest":
                value["workflow_sha256"] = "0" * 64
            else:
                value["frozen_payloads"]["files"].pop()
            with self.assertRaises(ValueError):
                pairs.validate_plan(value)

    def test_schema_closure_strict_tokens_and_all_references_resolve_offline(self):
        names = ("paired-scenario-v1.schema.json", "scenario-replay-v1.schema.json", "paired-replay-v1.schema.json",
                 "managed-replay-v1.schema.json", "lifecycle-v2.schema.json", "result-card-v1.schema.json",
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
        self.produce(blocks=1)
        original = self.saved("schedule.json")
        for mutate in (lambda value: value.update(schema_version=True), lambda value: value.update(seed=0.0),
                       lambda value: value.update(confirmatory_eligible=True), lambda value: value["sessions"]["baseline"].update(input_seed=True),
                       lambda value: value["frozen_payloads"]["files"][0].update(bytes=1.0)):
            value = copy.deepcopy(original)
            mutate(value)
            with self.assertRaises(ValueError):
                pairs.validate("plan", value)

    def test_paired_receipt_persistence_finishes_before_next_unit_but_is_outside_scenario_endpoint(self):
        original = timer.write_record
        entered, release = threading.Event(), threading.Event()

        def hold(path, value):
            if Path(path) == self.output / "receipt-000001-baseline.json":
                entered.set()
                if not release.wait(timeout=15):
                    raise RuntimeError("test did not release paired receipt publication")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=hold), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.produce, blocks=1)
            try:
                self.assertTrue(entered.wait(timeout=15))
                self.assertEqual(self.events("candidate"), [])
                self.assertTrue((self.output / "session-000001-baseline/unit.json").exists())
            finally:
                release.set()
            future.result(timeout=30)
        record = self.saved("block-000001-baseline.json")
        receipt = self.saved("receipt-000001-baseline.json")
        self.assertLessEqual(receipt["clock"]["monotonic_end_ns"], record["receipt_publication_clock"]["monotonic_start_ns"])
        self.assertLessEqual(record["receipt_publication_clock"]["monotonic_end_ns"], self.saved("block-000001-candidate.json")["call_clock"]["monotonic_start_ns"])

    def test_cli_apply_success_unsupported_and_aborted_campaigns_route_full_ledgers(self):
        original = copy.deepcopy(self.plans)
        for mode in ("complete", "unsupported", "failed"):
            self.output = self.root / mode
            self.plans = copy.deepcopy(original)
            if mode == "unsupported":
                for plan in self.plans.values():
                    plan["scenario"]["id"] = "S7"
            elif mode == "failed":
                self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "fail"
            paths = {}
            for arm, plan in self.plans.items():
                paths[arm] = self.root / (arm + ".json")
                paths[arm].write_text(json.dumps(plan))
            command = [sys.executable, str(HARNESS / "paired_scenarios.py"), "--output", str(self.output), "--blocks", "1", "--seed", "1",
                       "--baseline-plan", str(paths["baseline"]), "--candidate-plan", str(paths["candidate"]), "--payloads", str(self.payloads)]
            if mode == "complete":
                result = subprocess.run(command, capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.output.exists())
            result = subprocess.run([*command, "--apply"], capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, {"complete": 0, "unsupported": 3, "failed": 2}[mode], result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assert_counts(json.loads(result.stdout), blocks=1)
            for script, code in (("inspect_run.py", 0), ("summarize_run.py", 0 if mode == "complete" else 1)):
                result = subprocess.run([sys.executable, str(HARNESS / script), str(self.output)], capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assert_counts(json.loads(result.stdout), blocks=1)


if __name__ == "__main__":
    unittest.main()
