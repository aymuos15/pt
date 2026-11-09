"""Result-card consistency controls, not product conformance or benchmark evidence."""

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
import uuid

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_cgroup_accounting import SyntheticGroup


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import blob_store
    import paired
    import paired_lifecycle
    import paired_resources
    import pt_bench as timer
    import raw_capture
    import resource_run as resources
    import result_card as cards
    from finalization import read_json
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux lifecycle/blob profile")
class ResultCardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run = self.root / "run"
        self.output = self.root / "card.json"
        self.cwds = {arm: self.root / arm for arm in ("baseline", "candidate")}
        for cwd in self.cwds.values():
            cwd.mkdir()
        self.command = [sys.executable, "-c", (
            "from pathlib import Path; f=Path('calls').open('a'); f.write('call\\n'); f.close(); "
            "Path('report').write_bytes(b'ready\\n'); print('ready')"
        )]
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": 6,
                      "expected_stdout_sha256": hashlib.sha256(b"ready\n").hexdigest()}
        self.contract = {"expected_exit_code": 0, "artifacts": [
            {"path": "report", "bytes": 6, "sha256": self.guard["expected_stdout_sha256"]}], "absent": ["lease"]}

    def produce(self, *, endpoint=timer.LIFECYCLE_ENDPOINT, baseline=None, **changes):
        options = {f"{arm}_{key}": value for arm in self.cwds for key, value in
                   (("cwd", self.cwds[arm]), ("guard", self.guard))}
        if endpoint == timer.LIFECYCLE_ENDPOINT:
            options.update({f"{arm}_finalization": self.contract for arm in self.cwds})
        options.update(changes)
        paired.run_pairs(self.run, self.root, baseline or self.command, self.command, 2, 0, 5,
                         timing_endpoint=endpoint, **options)

    def produce_resources(self, states=(), **changes):
        self.groups = []

        def group(parent):
            index = len(self.groups)
            state = states[index] if index < len(states) else "complete"
            current = SyntheticGroup(missing=["memory.peak"] if state == "partial" else ["cpu.stat"] if state == "unsupported" else [],
                                     work=state if state not in ("partial", "unsupported", "complete") else "normal")
            current.path = Path(parent) / f"pt-bench-{uuid.uuid4().hex}"
            current.identity = [1, index + 1]
            self.groups.append(current)
            return current

        options = {"resource_cgroup_parent": "/synthetic/delegated"}
        options.update({f"{arm}_{key}": value for arm in self.cwds for key, value in
                        (("cwd", self.cwds[arm]), ("guard", {"expected_exit_code": 0, "expected_stdout_bytes": 0,
                                                          "expected_stdout_sha256": hashlib.sha256(b"").hexdigest()}))})
        options.update(changes)
        with (mock.patch.object(resources, "CgroupDirectory", side_effect=group),
              mock.patch.object(timer, "measure", side_effect=lambda *args, **kwargs: self.groups[-1].measure(*args, **kwargs))):
            paired.run_pairs(self.run, self.root, [sys.executable, "-c", "pass"], [sys.executable, "-c", "pass"], 2, 0, 5,
                             timing_endpoint=timer.RESOURCE_ENDPOINT, **options)

    def assert_denominators(self, card, planned=4):
        values = card["denominators"]
        self.assertEqual(values["planned_arms"], planned)
        self.assertEqual(len(card["measurement_observations"]), planned)
        self.assertEqual(sum(values["arm_status_counts"].values()), planned)
        self.assertEqual(sum(values[key] for key in ("known_invocation_attempts", "known_not_invoked_arms", "unknown_invocation_arms")), planned)
        self.assertEqual(card["classification"], "exploratory")
        self.assertFalse(card["confirmatory_eligible"])
        self.assertEqual(card["qualification"]["qualified_arm_count"], 0)
        self.assertEqual(set(card["qualification"]["unresolved_fields"]), set(cards.UNRESOLVED_FIELDS))
        self.assertTrue(all(value is None for value in card["qualification"]["unresolved_fields"].values()))

    def assert_blocked(self, card):
        self.assert_denominators(card)
        self.assertEqual(card["statistics"]["status"], "blocked")
        for key in ("ratio", "absolute_latency_ns", "bootstrap"):
            self.assertIsNone(card["statistics"][key])

    def test_lifecycle_card_binds_all_records_blobs_and_analysis_without_reexecuting(self):
        self.produce(capture_raw=True)
        expected = summarize_run(self.run)
        before = {arm: (cwd / "calls").read_bytes() for arm, cwd in self.cwds.items()}
        with mock.patch.object(timer, "measure") as measured:
            card = cards.write_result_card(self.run, self.output)
            checked = cards.inspect_result_card(card, self.run)
            measured.assert_not_called()
        self.assert_denominators(card)
        self.assertEqual(checked["card_consistency"], "checked_unqualified")
        self.assertEqual(card["statistics"]["ratio"], expected["ratio"])
        self.assertEqual(card["statistics"]["absolute_latency_ns"], expected["absolute_latency_ns"])
        self.assertEqual(card["context"]["timing_endpoint"], timer.LIFECYCLE_ENDPOINT)
        self.assertTrue(any(item["path"].startswith("blobs/") for item in card["evidence"]["files"]))
        self.assertTrue(any(item["path"].startswith("receipt-") for item in card["evidence"]["files"]))
        self.assertEqual(before, {arm: (cwd / "calls").read_bytes() for arm, cwd in self.cwds.items()})
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(read_json(self.output, limit=cards.MAX_CARD_BYTES)[0], card)

    def test_legacy_command_endpoint_is_named_and_never_upgraded_to_lifecycle_or_test_validity(self):
        self.produce(endpoint=timer.COMMAND_ENDPOINT)
        card = cards.generate_result_card(self.run)
        self.assert_denominators(card)
        self.assertEqual(card["context"]["timing_endpoint"], timer.COMMAND_ENDPOINT)
        self.assertEqual(card["context"]["measurement_layer"], "exploratory_command_timing")
        self.assertTrue(all(item["lifecycle_finalized"] is None for item in card["measurement_observations"]))
        self.assertIsNone(card["statistics"]["per_arm_resources"])
        self.assertEqual(card["evidence"]["directories"], [])

    def test_unexpected_nonzero_and_missing_guard_block_comparisons_without_dropping_arms(self):
        failed = [sys.executable, "-c", "raise SystemExit(7)"]
        self.produce(baseline=failed, baseline_finalization=None)
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["known_invocation_attempts"], 4)
        self.assertEqual(sum(row["returncode"] == 7 for row in card["measurement_observations"]), 2)
        self.run = self.root / "unguarded"
        self.produce(baseline_guard=None, candidate_guard=None)
        self.assert_blocked(cards.generate_result_card(self.run))

    def test_explicitly_expected_nonzero_outcomes_remain_observations_not_passing_tests(self):
        command = [sys.executable, "-c", "raise SystemExit(7)"]
        guard = {"expected_exit_code": 7, "expected_stdout_bytes": 0, "expected_stdout_sha256": hashlib.sha256(b"").hexdigest()}
        paired.run_pairs(self.run, self.root, command, command, 2, 0, 5, baseline_guard=guard, candidate_guard=guard)
        card = cards.generate_result_card(self.run)
        self.assert_denominators(card)
        self.assertEqual(card["statistics"]["status"], "exploratory_point_estimate")
        self.assertTrue(all(row["returncode"] == 7 for row in card["measurement_observations"]))
        self.assertIsNone(card["qualification"]["unresolved_fields"]["execution_occurrences"])

    def test_timeout_and_launch_failures_are_retained_not_turning_censoring_into_success(self):
        for label, command in (("launch", ["/nonexistent/pt-result-card-command"]),
                               ("timeout", [sys.executable, "-c", "import time; time.sleep(5)"])):
            self.run = self.root / label
            paired.run_pairs(self.run, self.root, command, command, 2, 0, 0.03,
                             baseline_guard=self.guard, candidate_guard=self.guard)
            card = cards.generate_result_card(self.run)
            self.assert_blocked(card)
            expected_status = "launch_error" if label == "launch" else "timeout"
            self.assertEqual(card["denominators"]["arm_status_counts"], {expected_status: 4})
            self.assertEqual(card["denominators"]["known_invocation_attempts"], 4)

    def test_failed_preparation_and_probe_keep_not_run_arms_in_both_timing_formats(self):
        failed = [sys.executable, "-c", "raise SystemExit(7)"]
        for endpoint in (timer.LIFECYCLE_ENDPOINT, timer.COMMAND_ENDPOINT):
            for stage in ("prepare", "probe"):
                self.run = self.root / f"skip-{endpoint[:7]}-{stage}"
                self.produce(endpoint=endpoint, **{f"baseline_{stage}": failed})
                card = cards.generate_result_card(self.run)
                self.assert_blocked(card)
                self.assertEqual(card["denominators"]["known_not_invoked_arms"], 2)
                self.assertEqual(card["denominators"]["known_invocation_attempts"], 2)
                self.assertEqual(sum(item["status"].startswith("not_run_") for item in card["measurement_observations"]), 2)

    def test_declared_finalization_abort_retains_failure_and_every_remaining_arm(self):
        (self.cwds["baseline"] / "lease").touch()
        with self.assertRaises(paired.RunAbortedError):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["arm_status_counts"], {"exited_unqualified": 1, "not_run_run_aborted": 3})
        self.assertEqual(card["denominators"]["known_invocation_attempts"], 1)
        self.assertFalse(card["measurement_observations"][0]["lifecycle_finalized"])
        self.assertTrue(any(item["path"] == "abort.json" for item in card["evidence"]["files"]))

    def test_missing_return_keeps_invocation_uncertain_not_zero_or_a_success(self):
        with mock.patch.object(timer, "measure", side_effect=OSError("injected measurement failure")):
            with self.assertRaises(paired.RunAbortedError):
                self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["unknown_invocation_arms"], 1)
        self.assertIsNone(card["measurement_observations"][0]["invocation_attempted"])
        self.assertEqual(card["denominators"]["known_not_invoked_arms"], 3)

    def test_preparation_harness_error_does_not_imply_measurement_was_attempted(self):
        with mock.patch("paired_lifecycle.measure_and_publish", side_effect=ValueError("injected no return")):
            with self.assertRaises(paired.RunAbortedError):
                self.produce(baseline_prepare=self.command)
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["known_not_invoked_arms"], 4)
        self.assertEqual(card["denominators"]["unknown_invocation_arms"], 0)

    def test_all_unsupported_resource_observations_preserve_null_metrics_and_denominators(self):
        self.produce_resources(["unsupported"] * 4)
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["resource_status_counts"], {"unsupported": 4})
        self.assertEqual(card["denominators"]["known_not_invoked_arms"], 4)
        for row in card["measurement_observations"]:
            self.assertIsNone(row["elapsed_ns"])
            self.assertIsNone(row["resources"]["cpu_delta_usec"])
            self.assertIsNone(row["resources"]["peak_charged_bytes"])
            self.assertIn("cpu_stat", row["resources"]["unsupported_capabilities"])

    def test_asymmetric_partial_resource_data_does_not_become_complete_subset_estimate(self):
        self.produce_resources(["unsupported", "partial", "partial", "unsupported"], resource_allow_missing_peak=True)
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["resource_status_counts"], {"partial_unsupported": 2, "unsupported": 2})
        self.assertEqual(card["denominators"]["known_invocation_attempts"], 2)
        self.assertTrue(all(row["resources"]["peak_charged_bytes"] is None for row in card["measurement_observations"]))
        self.assertEqual(card["statistics"]["per_arm_resources"]["baseline"]["peak_charged_bytes"]["unknown_units"], 2)

    def test_complete_synthetic_resource_data_is_never_promoted_to_latency_or_qualification(self):
        self.produce_resources()
        card = cards.generate_result_card(self.run)
        self.assert_denominators(card)
        self.assertEqual(card["statistics"]["status"], "diagnostic_resource_observations")
        self.assertIsNone(card["statistics"]["ratio"])
        self.assertIsNone(card["statistics"]["absolute_latency_ns"])
        self.assertTrue(all(row["elapsed_ns"] is None for row in card["measurement_observations"]))
        with self.assertRaisesRegex(ValueError, "bootstrap is unsupported"):
            cards.generate_result_card(self.run, bootstrap_resamples=20, bootstrap_seed=0)

    def test_strict_types_apply_through_resource_and_bootstrap_schema_references(self):
        self.produce_resources()
        original = cards.generate_result_card(self.run)
        for replacement in (True, 300000.0):
            card = copy.deepcopy(original)
            card["measurement_observations"][0]["resources"]["cpu_delta_usec"]["usage_usec"] = replacement
            with self.assertRaises(ValueError):
                cards.validate_card(card)
        self.run = self.root / "timing"
        self.produce()
        original = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        for replacement in (True, 30.0):
            card = copy.deepcopy(original)
            card["statistics"]["bootstrap"]["bootstrap_resamples"] = replacement
            with self.assertRaises(ValueError):
                cards.validate_card(card)

    def test_resource_stage_failure_keeps_stage_costs_and_all_not_run_measurements(self):
        with self.assertRaises(paired.RunAbortedError):
            self.produce_resources(["background"], baseline_prepare=[sys.executable, "-c", "pass"])
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["known_not_invoked_arms"], 4)
        self.assertEqual(card["denominators"]["planned_resource_stage_count"], 6)
        first = card["stage_resource_observations"][0]
        self.assertEqual(first["context"]["stage"], "preparation")
        self.assertEqual(first["status"], "failed")
        self.assertIsNotNone(first["resources"]["cpu_delta_usec"])
        self.assertEqual(card["statistics"]["per_arm_resources"]["baseline"]["cpu_usage_usec"]["unknown_units"], 2)

    def test_resource_publication_recovery_preserves_diagnostic_flags_not_false_commits(self):
        with mock.patch.object(resources, "publish_resource_record", side_effect=OSError("injected publication failure")):
            with self.assertRaises(paired.RunAbortedError):
                self.produce_resources()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["known_invocation_attempts"], 1)
        row = card["measurement_observations"][0]
        self.assertFalse(row["resources"]["resource_record_committed"])
        self.assertIsNotNone(row["resources"]["cpu_delta_usec"])

    def test_resource_harness_error_retains_unknown_invocation_and_every_planned_arm(self):
        with mock.patch.object(resources, "observe_resources", side_effect=ValueError("injected missing observer return")):
            with self.assertRaises(paired.RunAbortedError):
                self.produce_resources()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["unknown_invocation_arms"], 1)
        self.assertEqual(card["denominators"]["known_invocation_attempts"], 0)

    def test_same_inputs_options_and_moved_bundle_reconstruct_identical_cards(self):
        self.produce()
        options = {"bootstrap_resamples": 30, "bootstrap_seed": 7}
        first = cards.generate_result_card(self.run, **options)
        self.assertEqual(first, cards.generate_result_card(self.run, **options))
        moved = self.root / "moved"
        shutil.copytree(self.run, moved)
        self.assertEqual(first, cards.generate_result_card(moved, **options))
        self.assertEqual(first["statistics"]["bootstrap"]["bootstrap_seed"], 7)
        cards.inspect_result_card(first, moved)
        different = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=8)
        self.assertEqual(first["evidence"]["sha256"], different["evidence"]["sha256"])
        self.assertNotEqual(first["reconstruction_sha256"], different["reconstruction_sha256"])

    def test_older_legacy_records_without_clock_order_stay_blocked_and_do_not_gain_metadata(self):
        self.produce(endpoint=timer.COMMAND_ENDPOINT)
        for path in self.run.glob("block-*.json"):
            value = json.loads(path.read_text())
            for key in ("monotonic_start_ns", "monotonic_end_ns", "clock_domain"):
                value["result"].pop(key)
            path.write_text(json.dumps(value))
        path = self.run / "schedule.json"
        plan = json.loads(path.read_text())
        plan.pop("host_metadata")
        path.write_text(json.dumps(plan))
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertIsNone(card["context"]["host_observations"])

    def test_wrong_statistics_analysis_options_denominators_order_or_context_are_rejected(self):
        self.produce()
        original = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        for mutation in ("ratio", "options", "counts", "omission", "order", "context", "source_version"):
            changed = copy.deepcopy(original)
            if mutation == "ratio":
                changed["statistics"]["ratio"] += 1
            elif mutation == "options":
                changed["analysis_request"]["bootstrap_seed"] = 8
            elif mutation == "counts":
                changed["denominators"]["known_invocation_attempts"] = 0
            elif mutation == "omission":
                changed["measurement_observations"] = changed["measurement_observations"][:2]
                changed["denominators"]["planned_arms"] = 2
            elif mutation == "order":
                changed["measurement_observations"].reverse()
            elif mutation == "context":
                changed["context"]["commands"]["baseline"]["measurement"] = ["/different/command"]
            else:
                changed["generator"]["runtime"]["jsonschema_version"] = "0.0.0"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_qualification_upgrade_unknown_fields_missing_nulls_and_type_ambiguity_fail_closed(self):
        self.produce()
        original = cards.generate_result_card(self.run)
        mutations = [lambda value: value.update(classification="qualified"),
                     lambda value: value.update(confirmatory_eligible=True),
                     lambda value: value.update(unexpected=True),
                     lambda value: value["qualification"]["unresolved_fields"].pop("generation_validity"),
                     lambda value: value["qualification"]["unresolved_fields"].update(candidate_revision="a" * 40),
                     lambda value: value["denominators"].update(planned_arms=True),
                     lambda value: value["denominators"].update(planned_arms=4.0),
                     lambda value: value["measurement_observations"][0].update(invocation_attempted=1),
                     lambda value: value["evidence"]["files"][0].update(bytes=1.0),
                     lambda value: value["statistics"].update(ratio=float("nan"))]
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                cards.validate_card(changed)

    def test_edited_whitespace_and_forged_inventory_digest_do_not_approve_stale_card(self):
        self.produce()
        original = cards.generate_result_card(self.run)
        plan = self.run / "schedule.json"
        plan.write_bytes(plan.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            cards.inspect_result_card(original, self.run)
        fresh = cards.generate_result_card(self.run)
        self.assertNotEqual(original["evidence"]["sha256"], fresh["evidence"]["sha256"])
        self.assertEqual(original["statistics"], fresh["statistics"])
        original["evidence"]["sha256"] = fresh["evidence"]["sha256"]
        with self.assertRaises(ValueError):
            cards.inspect_result_card(original, self.run)

    def test_later_worktree_changes_do_not_replace_historical_evidence_and_bad_blobs_fail(self):
        self.produce()
        card = cards.generate_result_card(self.run)
        for cwd in self.cwds.values():
            (cwd / "report").unlink()
            (cwd / "lease").touch()
        cards.inspect_result_card(card, self.run)
        blob = next((self.run / "blobs").iterdir())
        blob.write_bytes(b"bad\n")
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)

    def test_missing_or_extra_evidence_and_unaccounted_abort_never_become_subset_cards(self):
        self.produce()
        path = self.run / "receipt-block-000001-baseline.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            cards.generate_result_card(self.run)
        path.write_bytes(raw)
        extra = self.run / "unexplained.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)
        extra.unlink()
        self.run = self.root / "abort-without-cause"
        (self.cwds["baseline"] / "lease").touch()
        with self.assertRaises(paired.RunAbortedError):
            self.produce()
        (self.run / "abort.json").unlink()
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)

    def test_root_record_blob_and_output_alias_symlinks_are_not_followed(self):
        self.produce()
        alias = self.root / "alias"
        alias.symlink_to(self.run, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            cards.generate_result_card(alias)
        with self.assertRaisesRegex(ValueError, "outside"):
            cards.write_result_card(self.run, alias / "card.json")
        record = self.run / "block-000001-baseline.json"
        saved = self.root / "record-copy.json"
        record.rename(saved)
        record.symlink_to(saved)
        with self.assertRaises((OSError, ValueError)):
            cards.generate_result_card(self.run)
        record.unlink()
        saved.rename(record)
        blob = next((self.run / "blobs").iterdir())
        saved_blob = self.root / "blob-copy"
        blob.rename(saved_blob)
        blob.symlink_to(saved_blob)
        with self.assertRaises((OSError, ValueError)):
            cards.generate_result_card(self.run)
        outside = self.root / "outside"
        outside.mkdir()
        parent_alias = self.root / "parent-alias"
        parent_alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            cards.write_result_card(self.run, parent_alias / "card.json")
        self.assertFalse((outside / "card.json").exists())

    def test_nonregular_unexpected_nested_files_and_resource_bounds_are_rejected(self):
        directory = self.root / "inventory"
        directory.mkdir()
        (directory / "a").write_text("a")
        (directory / "blobs").mkdir()
        with mock.patch.object(cards, "MAX_EVIDENCE_FILES", 1):
            self.assertEqual(len(cards.capture_run(directory)[0]["files"]), 1)
            (directory / "b").write_text("b")
            with self.assertRaises(ValueError):
                cards.capture_run(directory)
        (directory / "b").unlink()
        with mock.patch.object(cards, "MAX_TOTAL_BYTES", 0):
            with self.assertRaises(ValueError):
                cards.capture_run(directory)
        nested = directory / "blobs" / "nested"
        nested.mkdir()
        with self.assertRaises(ValueError):
            cards.capture_run(directory)
        nested.rmdir()
        os.mkfifo(directory / "fifo")
        with self.assertRaises(ValueError):
            cards.capture_run(directory)

    def test_oversized_cards_fail_without_truncating_or_dropping_arms(self):
        self.produce()
        with mock.patch.object(cards, "MAX_CARD_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "no arm or evidence entry may be truncated"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(cards.generate_result_card(self.run)["measurement_observations"]), 4)

    def test_unresolved_generator_dependency_identity_is_a_visible_error_not_an_invented_version(self):
        self.produce()
        with mock.patch.object(cards, "version", side_effect=cards.PackageNotFoundError("fixture-only")):
            with self.assertRaisesRegex(ValueError, "dependency identity unavailable"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_source_change_during_summary_or_after_publication_is_not_silently_retried(self):
        self.produce()
        original = cards.summarize_run
        plan = self.run / "schedule.json"

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            plan.write_bytes(plan.read_bytes() + b"\n")
            return result

        with mock.patch.object(cards, "summarize_run", side_effect=mutate) as summarized:
            with self.assertRaisesRegex(ValueError, "changed during"):
                cards.write_result_card(self.run, self.output)
            self.assertEqual(summarized.call_count, 1)
        self.assertFalse(self.output.exists())
        original_writer = cards.write_record

        def mutate_after(path, value):
            original_writer(path, value)
            plan.write_bytes(plan.read_bytes() + b"\n")

        with mock.patch.object(cards, "write_record", side_effect=mutate_after):
            with self.assertRaisesRegex(ValueError, "changed during"):
                cards.write_result_card(self.run, self.output)
        self.assertTrue(self.output.exists(), "retained failed publication is not silently deleted")
        saved, _ = read_json(self.output, limit=cards.MAX_CARD_BYTES)
        with self.assertRaises(ValueError):
            cards.inspect_result_card(saved, self.run)

    def test_matching_bytes_with_changed_fingerprints_are_not_accepted_by_generation_guard(self):
        self.produce()
        capture = cards.capture_run
        calls = []

        def changed_identity(directory):
            inventory, identities = capture(directory)
            calls.append(1)
            if len(calls) > 1:
                identities["schedule.json"][-1] += 1  # Explicit synthetic ctime-only mutation.
            return inventory, identities

        with mock.patch.object(cards, "capture_run", side_effect=changed_identity):
            with self.assertRaisesRegex(ValueError, "changed during"):
                cards.generate_result_card(self.run)

    def test_implementation_changes_are_bound_and_detected_without_editing_repository_sources(self):
        self.produce()
        copied = self.root / "reader-sources"
        copied.mkdir()
        for name in cards.SOURCE_FILES:
            shutil.copyfile(HARNESS / name, copied / name)
        original = cards.summarize_run

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = copied / "analysis.py"
            path.write_bytes(path.read_bytes() + b"\n")
            return result

        with mock.patch.object(cards, "HARNESS", copied), mock.patch.object(cards, "summarize_run", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during"):
                cards.generate_result_card(self.run)

    def test_existing_outputs_and_failed_omitted_or_wrong_publications_do_not_overwrite_or_replay(self):
        self.produce()
        self.output.write_text("existing")
        with mock.patch.object(cards, "_build") as build:
            with self.assertRaises(FileExistsError):
                cards.write_result_card(self.run, self.output)
            build.assert_not_called()
        self.assertEqual(self.output.read_text(), "existing")
        self.output.unlink()
        for mode in ("error", "omit", "wrong"):
            self.output = self.root / f"card-{mode}.json"

            def fail(path, value):
                if mode == "error":
                    raise OSError("injected card disk failure")
                if mode == "wrong":
                    Path(path).write_text("{}")

            with mock.patch.object(cards, "write_record", side_effect=fail), mock.patch.object(timer, "measure") as measured:
                with self.assertRaises((OSError, ValueError)):
                    cards.write_result_card(self.run, self.output)
                measured.assert_not_called()

    def test_schemas_and_all_references_are_offline_and_valid(self):
        schemas = [json.loads((HARNESS / name).read_text()) for name in
                   ("result-card-v1.schema.json", "lifecycle-v2.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")]
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

    def test_cli_emits_and_reconstructs_blocked_cards_but_rejects_malformed_edits(self):
        self.produce_resources(["unsupported"] * 4)
        command = [sys.executable, str(HARNESS / "result_card.py"), str(self.run), "--output", str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["confirmatory_eligible"])
        inspect = [sys.executable, str(HARNESS / "inspect_result_card.py"), str(self.output), "--run", str(self.run)]
        checked = subprocess.run(inspect, capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        card = json.loads(self.output.read_text())
        card["qualification"]["unresolved_fields"]["generation_validity"] = True
        self.output.write_text(json.dumps(card))
        checked = subprocess.run(inspect, capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 2)
        self.assertNotIn("Traceback", checked.stderr)


if __name__ == "__main__":
    unittest.main()
