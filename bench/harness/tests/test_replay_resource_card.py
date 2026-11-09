"""Offline resource-card controls; synthetic counters are never native qualification."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import test_paired_replay_resources as campaigns
import test_replay_resources as resource_controls


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import replay_resource_card as resource_cards
    import result_card as cards
    import replay_resources as diagnostic
    import paired_replay_resources as pairs
    import resource_run as resources
    import managed_replay as replay
    import pt_bench as timer
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux replay/blob profile")
class ResourceReplayCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Each disposable synthetic campaign is produced once and copied for
        # isolated offline tests. Card generation never invokes these producers.
        cls.sources = {}

    @classmethod
    def fixture(cls, mode):
        if mode in cls.sources:
            return cls.sources[mode]
        holder = campaigns.PairedReplayResourceTests("runTest")
        holder.setUp()
        cls.addClassCleanup(holder.doCleanups)
        configurations, options = [{}], {}
        if mode in ("unsupported", "partial"):
            configurations = [{"missing": ["memory.peak"]}]
            options["allow_missing_peak"] = mode == "partial"
        elif mode == "mixed":
            configurations = [{"missing": ["memory.peak"]}, {}, {}, {"missing": ["memory.peak"]}]
        elif mode == "failed-preparation":
            holder.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        elif mode == "later-failure":
            holder.plans["candidate"]["interactions"][0]["argv"][-1] = "fail"
        elif mode == "shutdown":
            holder.plans["baseline"]["shutdown"]["argv"][-1] = "unreleased"
        elif mode == "leftover":
            configurations = [{"work": "background"}]
        elif mode == "counter-failure":
            configurations = [{"fault": "cpu.stat"}]
        elif mode == "guard":
            holder.plans["baseline"]["preparation"]["guard_expectations"] = None
        elif mode == "raw":
            for plan in holder.plans.values():
                plan.update(capture_raw=True, raw_limit_bytes=4)
        elif mode == "pairing":
            options["pairing"] = None
        elif mode == "nonzero":
            for plan in holder.plans.values():
                step = plan["interactions"][0]
                step["argv"][-1] = "fail"
                step["guard_expectations"]["expected_exit_code"] = step["required_finalization"]["expected_exit_code"] = 7
        elif mode == "deadline":
            for plan in holder.plans.values():
                plan["execution_timeout_seconds"] = 0.001

        if mode in ("lost-before", "lost-after"):
            original = diagnostic.run_observation

            def lost(*args, **kwargs):
                if mode == "lost-after":
                    original(*args, **kwargs)
                raise OSError("fixture-only lost whole-resource-replay return")

            with mock.patch.object(diagnostic, "run_observation", side_effect=lost):
                holder.produce()
        elif mode in ("paired-receipt", "paired-session", "resource-publication"):
            original = timer.write_record

            def fail(path, value):
                original(path, value)
                target = (holder.output / "receipt-000001-baseline.json" if mode == "paired-receipt" else
                          holder.output / "block-000001-baseline.json" if mode == "paired-session" else
                          holder.output / "unit-000001-baseline/resource.json")
                if Path(path) == target:
                    raise OSError("fixture-only unconfirmed publication after visible commit")

            with mock.patch.object(timer, "write_record", side_effect=fail):
                holder.produce()
        elif mode == "managed-return":
            driver_holder = resource_controls.ReplayResourceTests("runTest")
            driver_holder.root = holder.root
            path = driver_holder.fault_driver("lost_after")
            with mock.patch.object(diagnostic, "DRIVER", path):
                holder.produce()
        elif mode == "resource-return":
            original = resources.observe_resources

            def lost(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("fixture-only lost resource return after driver completion")

            with mock.patch.object(resources, "observe_resources", side_effect=lost):
                holder.produce()
        elif mode == "boundary-failure":
            with mock.patch.object(resources, "CgroupDirectory", side_effect=RuntimeError("fixture-only pre-launch setup failure")):
                pairs.run_pairs(holder.output, holder.plans["baseline"], holder.plans["candidate"], 2, 0, 30, pairing=holder.pairing)
        elif mode == "plan-changed":
            original = diagnostic.run_observation
            driver = holder.root / "unused-driver.py"
            driver.write_bytes(diagnostic.DRIVER.read_bytes())

            def change(*args, **kwargs):
                receipt = original(*args, **kwargs)
                driver.write_bytes(driver.read_bytes() + b"\n")
                return receipt

            # No parent: the copied driver is never executed. Its later byte
            # change must stop the next planned call as known not invoked.
            with mock.patch.object(diagnostic, "DRIVER", driver), mock.patch.object(diagnostic, "run_observation", side_effect=change):
                pairs.run_pairs(holder.output, holder.plans["baseline"], holder.plans["candidate"], 2, 0, 30, pairing=holder.pairing)
        else:
            holder.produce(configurations, **options)
        cls.sources[mode] = holder.output
        return holder.output

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run = self.root / "run"
        self.output = self.root / "card.json"

    def use(self, mode="complete"):
        self.run = self.root / mode
        shutil.copytree(self.fixture(mode), self.run)
        return self.run

    def assert_counts(self, card):
        self.assertEqual(card["kind"], resource_cards.KIND)
        self.assertEqual(card["classification"], "exploratory")
        self.assertEqual(card["measurement_layer"], "resource_diagnostic")
        self.assertEqual(card["sample_unit"], replay.UNIT)
        self.assertFalse(card["confirmatory_eligible"])
        self.assertEqual(card["qualification"]["qualified_session_count"], 0)
        self.assertEqual(card["qualification"]["unresolved_fields"], {field: None for field in resource_cards.UNRESOLVED_FIELDS})
        self.assertEqual(len(card["qualification"]["unresolved_fields"]), 24)
        counts = card["denominators"]
        self.assertEqual(counts["planned_sessions"], len(card["session_observations"]))
        self.assertEqual(counts["planned_sessions"], 4)
        self.assertEqual(sum(counts["session_status_counts"].values()), 4)
        self.assertEqual(sum(counts["replay_session_status_counts"].values()), 4)
        self.assertEqual(sum(counts[key] for key in ("known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions")), 4)
        self.assertEqual(sum(counts[key] for key in ("known_boundary_invocations", "unknown_boundary_invocations", "known_not_invoked_boundaries")), 4)
        self.assertEqual(counts["planned_phase_count"], sum(counts["phase_status_counts"].values()))
        self.assertEqual(counts["planned_phase_count"], sum(counts[key] for key in ("known_phase_invocation_attempts", "known_not_invoked_phases", "unknown_phase_invocations")))
        self.assertEqual(counts["planned_interaction_count"], sum(counts["interaction_status_counts"].values()))
        self.assertIsNone(counts["verified_independent_sessions"])
        self.assertIsNone(counts["verified_independent_blocks"])
        for field in ("ratio", "absolute_latency_ns", "bootstrap", "whole_campaign_peak_charged_bytes", "idle_only_resource_metrics", "per_phase_resource_metrics"):
            self.assertIsNone(card["statistics"][field])
        self.assertTrue(all(row["elapsed_ns"] is None for row in card["session_observations"]))

    def blocked(self, card):
        self.assert_counts(card)
        self.assertEqual(card["statistics"]["status"], "blocked")
        self.assertTrue(card["blockers"])

    def test_recursive_inventory_private_publication_and_reader_closure_bind_every_file_without_commands(self):
        self.use()
        original = cards.summarize_run
        with (mock.patch.object(diagnostic, "run_observation") as observed, mock.patch.object(timer, "measure") as measured,
              mock.patch.object(resources, "CgroupDirectory") as group, mock.patch.object(cards, "summarize_run", wraps=original) as summarized):
            card = cards.write_result_card(self.run, self.output)
            summarized.assert_called_once()
            observed.assert_not_called()
            measured.assert_not_called()
            group.assert_not_called()
        self.assert_counts(card)
        expected_files = {str(path.relative_to(self.run)) for path in self.run.rglob("*") if path.is_file()}
        expected_dirs = {str(path.relative_to(self.run)) for path in self.run.rglob("*") if path.is_dir()}
        self.assertEqual({item["path"] for item in card["evidence"]["files"]}, expected_files)
        self.assertEqual(set(card["evidence"]["directories"]), expected_dirs)
        self.assertEqual(card["evidence"]["total_bytes"], sum((self.run / name).stat().st_size for name in expected_files))
        for item in card["evidence"]["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256((self.run / item["path"]).read_bytes()).hexdigest())
        self.assertEqual({item["path"] for item in card["generator"]["implementation"]["files"]}, set(resource_cards.SOURCE_FILES))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.output.read_text()), card)
        self.assertEqual(cards.inspect_result_card(card, self.run)["card_consistency"], "checked_unqualified")

    def test_complete_accounting_never_fills_qualification_or_claims_native_peak_support(self):
        self.use()
        card = cards.generate_result_card(self.run)
        self.assert_counts(card)
        self.assertTrue(card["campaign"]["all_session_accounting_complete"])
        self.assertEqual(card["statistics"]["status"], "diagnostic_resource_observations")
        self.assertTrue(card["generator"]["runtime"]["python_version"])
        self.assertEqual(card["context"]["pairing_identity_status"], "declared_only_unverified")
        for field in ("whole_session_resource_accounting", "machine_profile_and_resource_budget", "semantic_contract_and_equal_work", "independent_session_count"):
            self.assertIsNone(card["qualification"]["unresolved_fields"][field])

    def test_unsupported_units_preserve_not_invoked_phases_and_null_metrics_not_zero(self):
        self.use("unsupported")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"unsupported": 4})
        self.assertEqual(card["denominators"]["known_not_invoked_sessions"], 4)
        self.assertEqual(card["denominators"]["unit_observation_count"], 4)
        for arm in pairs.ARMS:
            self.assertEqual(card["statistics"]["per_arm_resources"][arm]["cpu_usage_usec"], {"observed_units": 0, "unknown_units": 2, "observed_sum": None})
        for row in card["session_observations"]:
            self.assertIsNone(row["cpu_delta_usec"])
            self.assertIsNone(row["peak_charged_bytes"])
            self.assertIn("memory_peak", row["unsupported_capabilities"])
            self.assertEqual(row["resource_enrollment"]["status"], "not_started")

    def test_partial_support_retains_cpu_but_missing_peak_and_qualifications_stay_null(self):
        self.use("partial")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"partial_unsupported": 4})
        self.assertEqual(card["denominators"]["replay_session_status_counts"], {"completed_unqualified": 4})
        for row in card["session_observations"]:
            self.assertIsNotNone(row["cpu_delta_usec"])
            self.assertIsNone(row["peak_charged_bytes"])
            self.assertFalse(row["whole_session_accounting_complete"])

    def test_mixed_support_keeps_both_arms_and_metric_coverage_denominators(self):
        self.use("mixed")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"observed_unqualified": 2, "unsupported": 2})
        self.assertEqual(card["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_units"], 0)
        self.assertEqual(card["statistics"]["per_arm_resources"]["candidate"]["cpu_usage_usec"]["observed_units"], 2)

    def test_failed_preparation_preserves_failed_and_skipped_phases_and_all_later_not_run(self):
        self.use("failed-preparation")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
        self.assertEqual(card["session_observations"][0]["interaction_status_counts"], {"not_run_prior_failure": 2})
        self.assertEqual(card["session_observations"][0]["shutdown_status"], "observed_unqualified")
        self.assertEqual(card["campaign"]["abort"]["reason"], "session_failed")

    def test_later_failure_retains_prior_observation_and_failed_unit_costs_without_subset_selection(self):
        self.use("later-failure")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"failed": 1, "not_run_run_aborted": 2, "observed_unqualified": 1})
        self.assertEqual(card["statistics"]["per_arm_resources"]["candidate"]["cpu_usage_usec"], {"observed_units": 1, "unknown_units": 1, "observed_sum": 300000})
        self.assertEqual(card["session_observations"][1]["session_status"], "aborted")

    def test_matching_shutdown_stdout_with_unreleased_state_is_still_failed(self):
        self.use("shutdown")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertEqual(row["phase_guard_counts"], {"matched": 4})
        self.assertEqual(row["shutdown_status"], "failed")
        self.assertIn("required_shutdown_not_completed", row["replay_outcome"]["outcome_reasons"])

    def test_lingering_worker_kill_and_cleanup_details_cannot_disappear_into_completed_replay(self):
        self.use("leftover")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertEqual(row["session_status"], "completed_unqualified")
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["resource_cleanup"]["kill_requested"])
        self.assertTrue(row["resource_group"]["removed"])
        self.assertIn("background_work_outlived_command", row["resource_failure_reasons"])
        self.assertGreater(card["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"], 300000)

    def test_counter_failure_preserves_errors_and_unknown_metric_with_known_session_outcome(self):
        self.use("counter-failure")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertIsNone(row["cpu_delta_usec"])
        self.assertEqual(row["session_status"], "completed_unqualified")
        self.assertTrue(row["resource_errors"])
        self.assertIsNone(card["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"])

    def test_lost_api_return_before_or_after_commit_keeps_unknown_effects_and_metrics(self):
        for mode in ("lost-before", "lost-after"):
            self.use(mode)
            card = cards.generate_result_card(self.run)
            self.blocked(card)
            self.assertEqual(card["denominators"]["unknown_session_invocations"], 1)
            self.assertEqual(card["denominators"]["known_not_invoked_sessions"], 3)
            self.assertEqual(card["denominators"]["unknown_phase_invocations"], 4)
            row = card["session_observations"][0]
            for key in ("cpu_delta_usec", "peak_charged_bytes", "resource_group", "resource_enrollment", "resource_cleanup", "resource_errors", "observer_errors", "driver_error", "replay_outcome", "shutdown_status"):
                self.assertIsNone(row[key])
            self.assertEqual(card["campaign"]["abort"]["diagnostic_inputs_present"], mode == "lost-after")
            if mode == "lost-after":
                self.assertIn("unit-000001-baseline/session/unit.json", {item["path"] for item in card["evidence"]["files"]})

    def test_missing_managed_return_retains_known_boundary_counters_and_explicit_driver_error(self):
        self.use("managed-return")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertTrue(row["boundary_run_attempted"])
        self.assertIsNone(row["session_invocation_attempted"])
        self.assertIsNotNone(row["cpu_delta_usec"])
        self.assertEqual(row["session_status"], "unknown")
        self.assertIn("OSError", row["driver_error"]["error"])
        self.assertEqual(row["unknown_phase_invocations"], 4)

    def test_lost_resource_return_preserves_managed_outcomes_but_not_boundary_metrics(self):
        self.use("resource-return")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertTrue(row["unit_observation_returned"])
        self.assertTrue(row["session_invocation_attempted"])
        self.assertEqual(row["session_status"], "completed_unqualified")
        self.assertEqual(row["known_phase_invocation_attempts"], 4)
        self.assertIsNone(row["boundary_run_attempted"])
        self.assertIsNone(row["cpu_delta_usec"])
        self.assertIsNone(row["resource_group"])
        self.assertEqual(row["observer_errors"][0]["stage"], "resource_observation")
        self.assertFalse(row["driver_completion_confirmed"])

    def test_boundary_setup_failure_remains_known_not_run_with_retained_observer_errors(self):
        self.use("boundary-failure")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["session_status"], "not_run_boundary_failed")
        self.assertFalse(row["boundary_run_attempted"])
        self.assertFalse(row["session_invocation_attempted"])
        self.assertEqual(card["denominators"]["known_not_invoked_sessions"], 4)
        self.assertEqual(row["known_not_invoked_phases"], 4)
        self.assertTrue(row["resource_errors"])
        self.assertIsNone(row["cpu_delta_usec"])

    def test_frozen_driver_change_stops_before_later_invocation_without_unknown_effects(self):
        self.use("plan-changed")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"not_run_plan_changed": 1, "not_run_run_aborted": 2, "unsupported": 1})
        self.assertEqual(card["denominators"]["known_not_invoked_sessions"], 4)
        self.assertEqual(card["denominators"]["unknown_session_invocations"], 0)
        self.assertEqual(card["campaign"]["abort"]["reason"], "plan_binding_failed")
        self.assertEqual(card["session_observations"][1]["phase_status_counts"], {"not_run_plan_changed": 4})

    def test_unconfirmed_paired_receipt_and_metadata_never_invent_commits(self):
        for mode in ("paired-receipt", "paired-session"):
            self.use(mode)
            card = cards.generate_result_card(self.run)
            self.blocked(card)
            row = card["session_observations"][0]
            self.assertEqual(row["status"], "observed_unqualified")
            self.assertEqual(row["receipt_record_committed"], mode == "paired-session")
            self.assertFalse(row["session_record_committed"])
            self.assertFalse(card["campaign"]["all_session_accounting_complete"])

    def test_unconfirmed_inner_resource_publication_retains_diagnostic_counters_and_observer_error(self):
        self.use("resource-publication")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        row = card["session_observations"][0]
        self.assertIsNotNone(row["cpu_delta_usec"])
        self.assertFalse(row["resource_record_confirmed"])
        self.assertEqual(row["observer_errors"][0]["stage"], "resource_publication")
        self.assertEqual(row["session_status"], "completed_unqualified")

    def test_expected_nonzero_and_expired_execution_budget_retain_their_declared_outcomes(self):
        self.use("nonzero")
        card = cards.generate_result_card(self.run)
        self.assert_counts(card)
        self.assertEqual(card["statistics"]["status"], "diagnostic_resource_observations")
        self.use("deadline")
        card = cards.generate_result_card(self.run)
        self.blocked(card)
        self.assertEqual(card["session_observations"][0]["known_not_invoked_phases"], 3)
        self.assertEqual(card["session_observations"][0]["shutdown_status"], "observed_unqualified")

    def test_guards_raw_truncation_and_unresolved_pairing_keep_observations_but_block_summary(self):
        for mode in ("guard", "raw", "pairing"):
            self.use(mode)
            card = cards.generate_result_card(self.run)
            self.blocked(card)
            self.assertEqual(card["denominators"]["session_status_counts"], {"observed_unqualified": 4})
            if mode == "raw":
                self.assertTrue(all(row["replay_outcome"]["raw_capture_truncated_phase_count"] == 4 for row in card["session_observations"]))

    def test_statistics_match_existing_whole_session_summary_and_never_sum_memory_peaks(self):
        self.use()
        summary = summarize_run(self.run)
        card = cards.generate_result_card(self.run)
        self.assertEqual(card["statistics"], {key: summary[key] for key in resource_cards.STATISTIC_FIELDS})
        for arm in pairs.ARMS:
            self.assertEqual(card["statistics"]["per_arm_resources"][arm]["peak_charged_bytes"]["maximum_observed_per_session"], 96 * 1024 * 1024)  # Synthetic maximum, not sum.
        self.assertIsNone(card["statistics"]["whole_campaign_peak_charged_bytes"])

    def test_same_bytes_and_relocated_history_reconstruct_identical_cards_without_current_worktree_access(self):
        self.use()
        first = cards.generate_result_card(self.run)
        self.assertEqual(first, cards.generate_result_card(self.run))
        moved = self.root / "moved"
        shutil.copytree(self.run, moved)
        with (mock.patch.object(diagnostic, "run_observation") as observed, mock.patch.object(resources, "CgroupDirectory") as group,
              mock.patch.object(replay, "_file_observation", side_effect=AssertionError("current worktree read"))):
            self.assertEqual(first, cards.generate_result_card(moved))
            cards.inspect_result_card(first, moved)
            observed.assert_not_called()
            group.assert_not_called()

    def test_qualification_upgrades_missing_fields_and_latency_promotions_fail_closed_schema(self):
        self.use()
        original = cards.generate_result_card(self.run)
        mutations = (lambda value: value.update(classification="qualified"), lambda value: value.update(confirmatory_eligible=True),
                     lambda value: value.update(unexpected=True), lambda value: value.update(measurement_layer="managed_replay"),
                     lambda value: value["qualification"]["unresolved_fields"].pop("generation_validity"),
                     lambda value: value["qualification"]["unresolved_fields"].update(whole_session_resource_accounting=True),
                     lambda value: value["qualification"]["unresolved_fields"].update(machine_profile_and_resource_budget=0),
                     lambda value: value["denominators"].update(verified_independent_sessions=4),
                     lambda value: value["statistics"].update(ratio=1), lambda value: value["statistics"].update(whole_campaign_peak_charged_bytes=0),
                     lambda value: value["session_observations"][0].update(elapsed_ns=1),
                     lambda value: value["context"].update(verified_inputs=True))
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError):
                cards.validate_card(changed)

    def test_strict_integer_tokens_apply_through_all_shared_resource_schema_references(self):
        self.use()
        original = cards.generate_result_card(self.run)
        mutations = (lambda value: value.update(schema_version=True), lambda value: value["denominators"].update(planned_sessions=4.0),
                     lambda value: value["session_observations"][0]["cpu_delta_usec"].update(usage_usec=True),
                     lambda value: value["session_observations"][0]["resource_group"].update(identity=[1.0, 2]),
                     lambda value: value["context"]["resources"].update(sample_interval_ns=20000000.0),
                     lambda value: value["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"].update(observed_sum=600000.0),
                     lambda value: value["session_observations"][0]["phase_guard_counts"].update(matched=True),
                     lambda value: value["evidence"]["files"][0].update(bytes=True),
                     lambda value: value["session_observations"][0].update(peak_charged_bytes=float("nan")))
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError):
                cards.validate_card(changed)

    def test_forged_counters_totals_cleanup_and_reader_versions_fail_full_reconstruction(self):
        self.use()
        original = cards.generate_result_card(self.run)
        mutations = (lambda value: value["session_observations"][0]["cpu_delta_usec"].update(usage_usec=1),
                     lambda value: value["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"].update(observed_sum=1),
                     lambda value: value["session_observations"][0]["resource_group"].update(removed=False),
                     lambda value: value["denominators"].update(known_session_invocations=0),
                     lambda value: value["context"]["resources"].update(allow_missing_peak=True),
                     lambda value: value["generator"]["runtime"].update(jsonschema_version="0.0.0"),
                     lambda value: value["generator"]["implementation"]["files"][0].update(sha256="0" * 64),
                     lambda value: value.update(reconstruction_sha256="0" * 64))
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_missing_native_peak_cannot_be_substituted_by_zero_or_complete_accounting(self):
        self.use("partial")
        original = cards.generate_result_card(self.run)
        for mode in ("zero", "complete", "capability"):
            changed = copy.deepcopy(original)
            row = changed["session_observations"][0]
            if mode == "zero":
                row["peak_charged_bytes"] = 0
            elif mode == "complete":
                row["whole_session_accounting_complete"] = True
            else:
                row["unsupported_capabilities"] = {}
            with self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_unknown_session_cannot_be_relabelled_not_run_or_given_zero_cost_or_commit(self):
        self.use("lost-after")
        original = cards.generate_result_card(self.run)
        for mode in ("not-run", "cost", "commit", "recovered"):
            changed = copy.deepcopy(original)
            row = changed["session_observations"][0]
            if mode == "not-run":
                row["session_invocation_attempted"] = False
            elif mode == "cost":
                row["cpu_delta_usec"] = {"usage_usec": 0, "user_usec": 0, "system_usec": 0}
            elif mode == "commit":
                row["receipt_record_committed"] = True
            else:
                row["session_status"] = "completed_unqualified"
            with self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_failed_not_run_sessions_cannot_be_omitted_reordered_or_excluded_into_favorable_card(self):
        self.use("later-failure")
        original = cards.generate_result_card(self.run)
        for mode in ("omit", "order", "cause", "guard"):
            changed = copy.deepcopy(original)
            if mode == "omit":
                changed["session_observations"] = changed["session_observations"][:2]
                changed["denominators"]["planned_sessions"] = 2
                changed["denominators"]["session_status_counts"].pop("not_run_run_aborted")
            elif mode == "order":
                changed["session_observations"].reverse()
            elif mode == "cause":
                changed["campaign"]["abort"]["error"] = "favorable exclusion"
            else:
                changed["session_observations"][1]["phase_guard_counts"] = {"matched": 4}
            with self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_unsupported_checks_cannot_be_promoted_to_executed_zero_resource_sessions(self):
        self.use("unsupported")
        card = cards.generate_result_card(self.run)
        card["session_observations"][0]["session_invocation_attempted"] = True
        card["session_observations"][0]["sampled_current_max_bytes"] = 0
        card["denominators"]["observed_sessions"] = 1
        with self.assertRaises(ValueError):
            cards.inspect_result_card(card, self.run)

    def test_exact_source_bytes_are_bound_even_when_whitespace_does_not_change_summary(self):
        self.use()
        original = cards.generate_result_card(self.run)
        path = self.run / "block-000001-baseline.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            cards.inspect_result_card(original, self.run)
        fresh = cards.generate_result_card(self.run)
        self.assertEqual(original["statistics"], fresh["statistics"])
        self.assertNotEqual(original["evidence"]["sha256"], fresh["evidence"]["sha256"])
        original["evidence"]["sha256"] = fresh["evidence"]["sha256"]
        with self.assertRaises(ValueError):
            cards.inspect_result_card(original, self.run)

    def test_unknown_return_diagnostic_bytes_are_bound_but_never_become_observed_metrics(self):
        self.use("lost-after")
        original = cards.generate_result_card(self.run)
        unit = self.run / "unit-000001-baseline"
        path = unit / "session/unit.json"
        path.write_bytes(path.read_bytes() + b"\n")
        abort_path = self.run / "abort.json"
        abort = json.loads(abort_path.read_text())
        abort["diagnostic_inputs"] = diagnostic._capture(unit)[0]
        abort_path.write_text(json.dumps(abort))
        with self.assertRaises(ValueError):
            cards.inspect_result_card(original, self.run)
        fresh = cards.generate_result_card(self.run)
        self.assertIsNone(fresh["session_observations"][0]["cpu_delta_usec"])
        self.assertNotEqual(fresh["evidence"]["sha256"], original["evidence"]["sha256"])

    def test_missing_extra_or_corrupt_source_evidence_produces_no_subset_card(self):
        self.use()
        path = self.run / "receipt-000001-baseline.json"
        saved = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())
        path.write_bytes(saved)
        extra = self.run / "extra.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            cards.write_result_card(self.run, self.output)
        extra.unlink()
        next((self.run / "unit-000001-baseline/session/blobs").iterdir()).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_abort_does_not_certify_favorable_prefix(self):
        self.use("failed-preparation")
        (self.run / "abort.json").unlink()
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)

    def test_card_and_evidence_bounds_fail_without_truncating_outcomes(self):
        self.use()
        with mock.patch.object(cards, "MAX_CARD_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "no outcome or evidence entry may be truncated"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())
        for attribute in ("MAX_CAMPAIGN_FILES", "MAX_CAMPAIGN_BYTES"):
            with mock.patch.object(pairs, attribute, 1):
                with self.assertRaises(ValueError):
                    cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_nonregular_inputs_and_output_aliases_fail_safely(self):
        self.use()
        alias = self.root / "alias"
        alias.symlink_to(self.run, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            cards.generate_result_card(alias)
        with self.assertRaisesRegex(ValueError, "outside"):
            cards.write_result_card(self.run, alias / "card.json")
        os.mkfifo(self.run / "fifo")
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)
        (self.run / "fifo").unlink()
        (self.run / "nested").mkdir()
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)

    def test_source_mutation_during_summary_fails_before_publication_without_retry(self):
        self.use()
        original = cards.summarize_run

        def change(*args, **kwargs):
            summary = original(*args, **kwargs)
            path = self.run / "block-000001-baseline.json"
            path.write_bytes(path.read_bytes() + b"\n")
            return summary

        with mock.patch.object(cards, "summarize_run", side_effect=change) as summarized:
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.write_result_card(self.run, self.output)
            summarized.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_post_publication_source_mutation_retains_unconfirmed_file_and_reports_failure(self):
        self.use()
        original = cards.write_record

        def change(path, value):
            original(path, value)
            source = self.run / "block-000001-baseline.json"
            source.write_bytes(source.read_bytes() + b"\n")

        with mock.patch.object(cards, "write_record", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.write_result_card(self.run, self.output)
        self.assertTrue(self.output.exists())
        with self.assertRaises(ValueError):
            cards.inspect_result_card(json.loads(self.output.read_text()), self.run)

    def test_reader_source_changes_are_detected_without_editing_repository_files(self):
        self.use()
        copied = self.root / "reader"
        copied.mkdir()
        for name in resource_cards.SOURCE_FILES:
            shutil.copyfile(HARNESS / name, copied / name)
        original = cards.summarize_run

        def change(*args, **kwargs):
            summary = original(*args, **kwargs)
            path = copied / "replay_resource_card.py"
            path.write_bytes(path.read_bytes() + b"\n")
            return summary

        with mock.patch.object(resource_cards, "HARNESS", copied), mock.patch.object(cards, "summarize_run", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.generate_result_card(self.run)

    def test_identity_only_mutations_are_not_retried_or_ignored(self):
        self.use()
        original, calls = resource_cards.capture_evidence, []

        def change(path):
            inventory, identities = original(path)
            calls.append(1)
            if len(calls) > 1:
                identities[0]["schedule.json"]["identity"][-1] += 1  # Explicit synthetic identity-only mutation.
            return inventory, identities

        with mock.patch.object(resource_cards, "capture_evidence", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.generate_result_card(self.run)
        self.assertEqual(len(calls), 2)

    def test_existing_and_failed_card_publications_never_overwrite_or_execute_subject(self):
        self.use()
        self.output.write_text("user work")
        with mock.patch.object(cards, "_build") as build:
            with self.assertRaises(FileExistsError):
                cards.write_result_card(self.run, self.output)
            build.assert_not_called()
        self.assertEqual(self.output.read_text(), "user work")
        for mode in ("error", "omit", "wrong"):
            self.output = self.root / (mode + ".json")

            def fail(path, value):
                if mode == "error":
                    raise OSError("fixture-only card storage error")
                if mode == "wrong":
                    Path(path).write_text("{}")

            with mock.patch.object(cards, "write_record", side_effect=fail), mock.patch.object(diagnostic, "run_observation") as observed:
                with self.assertRaises((OSError, ValueError)):
                    cards.write_result_card(self.run, self.output)
                observed.assert_not_called()

    def test_missing_runtime_identity_is_error_not_an_invented_version(self):
        self.use()
        with mock.patch.object(cards, "version", side_effect=cards.PackageNotFoundError("fixture-only")):
            with self.assertRaisesRegex(ValueError, "dependency identity unavailable"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_bootstrap_requests_and_legacy_kind_relabels_are_rejected(self):
        self.use()
        with mock.patch.object(resource_cards, "capture_evidence") as captured:
            for options in ({"bootstrap_resamples": 20}, {"bootstrap_seed": 0}, {"bootstrap_resamples": 20, "bootstrap_seed": 0}):
                with self.assertRaisesRegex(ValueError, "bootstrap is unsupported"):
                    cards.generate_result_card(self.run, **options)
            captured.assert_not_called()
        card = cards.generate_result_card(self.run)
        # The standalone test removes its temporary harness import path after
        # initial imports. Restore it for the deliberately different lazy reader,
        # as the CLI does, rather than rely on another test importing that module.
        with mock.patch.object(sys, "path", [str(HARNESS), *sys.path]):
            for kind in ("paired_exploratory_result_card", "paired_replay_exploratory_result_card"):
                changed = copy.deepcopy(card)
                changed["kind"] = kind
                with self.assertRaises(ValueError):
                    cards.validate_card(changed)

    def test_schema_and_all_references_are_valid_and_resolved_offline(self):
        names = ("replay-resource-card-v1.schema.json", "paired-replay-resource-v1.schema.json", "replay-resource-v1.schema.json",
                 "paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "resource-observation-v1.schema.json",
                 "lifecycle-v2.schema.json", "result-card-v1.schema.json", "replay-result-card-v1.schema.json", "paired-resource-v1.schema.json")
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

    def test_cli_generates_complete_unsupported_and_unknown_cards_and_rejects_forgeries(self):
        for mode in ("complete", "unsupported", "lost-after"):
            self.use(mode)
            self.output = self.root / (mode + "-card.json")
            command = [sys.executable, str(HARNESS / "result_card.py"), str(self.run), "--output", str(self.output)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0 if mode == "complete" else 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["planned_session_count"], 4)
            command = [sys.executable, str(HARNESS / "inspect_result_card.py"), str(self.output), "--run", str(self.run)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            card = json.loads(self.output.read_text())
            card["qualification"]["unresolved_fields"]["whole_session_resource_accounting"] = True
            self.output.write_text(json.dumps(card))
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
