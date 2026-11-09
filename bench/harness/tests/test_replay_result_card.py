"""Offline replay-card reconstruction and adverse controls, never qualification."""

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


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import blob_store
    import raw_capture
    import managed_replay as replay
    import paired_replay as pairs
    import pt_bench as timer
    import replay_result_card as replay_cards
    import result_card as cards
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux managed replay/blob profile")
class ReplayResultCardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run = self.root / "run"
        self.output = self.root / "card.json"
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
        # Fixture declarations only; these are not authenticated or qualified pins.
        self.pairing = {"input_seed": 0, "edit_sequence_sha256": hashlib.sha256(b"fixture-no-edits").hexdigest(),
                        "external_state_sha256": hashlib.sha256(b"fixture-empty-state").hexdigest()}

    def artifact(self, name):
        return {"path": name, "bytes": 6, "sha256": self.digest}

    def step(self, arm, role, name):
        return {"id": name, "argv": [sys.executable, str(self.probe), str(self.cwds[arm]), role, name, "normal"],
                "timeout_seconds": 5, "idle_before_seconds": 0,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": self.digest},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [self.artifact("report-" + name)],
                                          "absent": ["lease"] if role == "shutdown" else []}}

    def produce(self, *, pairing="fixture"):
        return pairs.run_pairs(self.run, self.plans["baseline"], self.plans["candidate"], 2, 0,
                               pairing=self.pairing if pairing == "fixture" else pairing)

    def assert_denominators(self, card):
        self.assertEqual(card["kind"], replay_cards.KIND)
        self.assertEqual(card["sample_unit"], replay.UNIT)
        self.assertEqual(card["timing_endpoint"], replay.ENDPOINT)
        self.assertEqual(card["classification"], "exploratory")
        self.assertFalse(card["confirmatory_eligible"])
        self.assertEqual(card["qualification"]["qualified_session_count"], 0)
        self.assertEqual(set(card["qualification"]["unresolved_fields"]), set(replay_cards.UNRESOLVED_FIELDS))
        self.assertEqual(len(card["qualification"]["unresolved_fields"]), 24)
        self.assertTrue(all(value is None for value in card["qualification"]["unresolved_fields"].values()))
        counts = card["denominators"]
        self.assertEqual(counts["planned_sessions"], 4)
        self.assertEqual(sum(counts["session_status_counts"].values()), 4)
        self.assertEqual(len(card["session_observations"]), 4)
        self.assertEqual(sum(counts[key] for key in ("known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions")), 4)
        self.assertEqual(sum(counts["observed_phase_status_counts"].values()) + counts["unknown_phase_count"] + counts["not_run_phase_count"], counts["planned_phase_count"])
        self.assertEqual(sum(counts["observed_interaction_status_counts"].values()) + counts["unknown_interaction_count"] + counts["not_run_interaction_count"], counts["planned_interaction_count"])
        self.assertIsNone(counts["verified_independent_sessions"])
        self.assertIsNone(counts["verified_independent_blocks"])
        self.assertIsNone(card["statistics"]["resource_observation"])
        self.assertFalse(card["statistics"]["whole_boundary_resource_accounting_complete"])

    def assert_blocked(self, card):
        self.assert_denominators(card)
        self.assertEqual(card["statistics"]["status"], "blocked")
        for field in ("ratio", "absolute_latency_ns", "bootstrap"):
            self.assertIsNone(card["statistics"][field])

    def test_recursive_evidence_reader_sources_and_private_publication_bind_all_bytes(self):
        self.produce()
        before = {arm: (cwd / "events").read_bytes() for arm, cwd in self.cwds.items()}
        original = cards.summarize_run
        with (mock.patch.object(replay, "run_replay") as measured, mock.patch.object(timer, "measure") as process,
              mock.patch.object(cards, "summarize_run", wraps=original) as summarized):
            card = cards.write_result_card(self.run, self.output, bootstrap_resamples=30, bootstrap_seed=7)
            summarized.assert_called_once()
            measured.assert_not_called()
            process.assert_not_called()
        self.assert_denominators(card)
        expected = {str(path.relative_to(self.run)) for path in self.run.rglob("*") if path.is_file()}
        self.assertEqual({item["path"] for item in card["evidence"]["files"]}, expected)
        self.assertEqual(set(card["evidence"]["directories"]), {str(path.relative_to(self.run)) for path in self.run.rglob("*") if path.is_dir()})
        self.assertEqual(card["evidence"]["total_bytes"], sum((self.run / name).stat().st_size for name in expected))
        for item in card["evidence"]["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256((self.run / item["path"]).read_bytes()).hexdigest())
        self.assertEqual({item["path"] for item in card["generator"]["implementation"]["files"]}, set(replay_cards.SOURCE_FILES))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.output.read_text()), card)
        self.assertEqual(before, {arm: (cwd / "events").read_bytes() for arm, cwd in self.cwds.items()})
        with mock.patch.object(replay, "run_replay") as measured:
            self.assertEqual(cards.inspect_result_card(card, self.run)["card_consistency"], "checked_unqualified")
            measured.assert_not_called()

    def test_declarations_and_generator_runtime_never_fill_qualification_gaps(self):
        self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_denominators(card)
        self.assertEqual(card["context"]["pairing"], self.pairing)
        self.assertEqual(card["context"]["pairing_identity_status"], "declared_only_unverified")
        self.assertTrue(card["generator"]["runtime"]["python_version"])
        for field in ("matched_replay_inputs_and_external_state", "arm_python_pytest_plugin_identities", "independent_session_count", "whole_session_resource_accounting"):
            self.assertIsNone(card["qualification"]["unresolved_fields"][field])

    def test_failed_preparation_retains_every_skipped_session_and_interaction(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        self.produce()
        card = cards.generate_result_card(self.run, bootstrap_resamples=20, bootstrap_seed=0)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"aborted": 1, "not_run_run_aborted": 3})
        self.assertEqual(card["session_observations"][0]["observed_interaction_status_counts"], {"not_run_prior_failure": 2})
        self.assertEqual(card["denominators"]["not_run_phase_count"], 12)
        self.assertEqual(card["denominators"]["not_run_interaction_count"], 6)
        self.assertEqual(card["campaign"]["abort"]["reason"], "session_failed")

    def test_later_failure_preserves_prior_success_and_never_selects_complete_subset(self):
        self.plans["candidate"]["interactions"][0]["argv"][-1] = "fail"
        self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"aborted": 1, "completed_unqualified": 1, "not_run_run_aborted": 2})
        self.assertEqual(card["session_observations"][1]["observed_interaction_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual(card["session_observations"][1]["shutdown_status"], "observed_unqualified")

    def test_expected_nonzero_observations_remain_unqualified(self):
        for plan in self.plans.values():
            step = plan["interactions"][0]
            step["argv"][-1] = "fail"
            step["guard_expectations"]["expected_exit_code"] = step["required_finalization"]["expected_exit_code"] = 7
        self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_denominators(card)
        self.assertEqual(card["statistics"]["status"], "exploratory_point_estimate")
        self.assertEqual(card["context"]["sessions"]["baseline"]["interactions"][0]["required_finalization"]["expected_exit_code"], 7)

    def test_shutdown_failure_or_unreleased_state_cannot_become_successful_card(self):
        for mode in ("fail", "unreleased", "hang"):
            self.run = self.root / mode
            self.plans["baseline"]["shutdown"]["argv"][-1] = mode
            for plan in self.plans.values():
                plan["shutdown"]["timeout_seconds"] = 0.1 if mode == "hang" else 5
            self.produce()
            card = cards.generate_result_card(self.run)
            self.assert_blocked(card)
            self.assertEqual(card["session_observations"][0]["shutdown_status"], "failed")
            self.assertIn("required_shutdown_not_completed", card["session_observations"][0]["outcome_reasons"])

    def test_timeout_and_launch_failure_keep_session_failure_not_censored_success(self):
        for mode in ("timeout", "launch"):
            self.run = self.root / mode
            for plan in self.plans.values():
                plan["interactions"][0]["timeout_seconds"] = 0.04
            self.plans["baseline"]["interactions"][0]["argv"] = (
                [sys.executable, str(self.probe), str(self.cwds["baseline"]), "interaction", "first", "hang"]
                if mode == "timeout" else ["/nonexistent/pt-replay-card-command"])
            self.produce()
            card = cards.generate_result_card(self.run)
            self.assert_blocked(card)
            self.assertEqual(card["denominators"]["known_session_invocations"], 1)

    def test_missing_return_and_cancellation_keep_unknown_effects_not_zero_duration(self):
        for error in (OSError("injected lost return"), KeyboardInterrupt("injected cancellation"), RuntimeError("injected observer error")):
            self.run = self.root / type(error).__name__
            with mock.patch.object(replay, "run_replay", side_effect=error):
                self.produce()
            card = cards.generate_result_card(self.run)
            self.assert_blocked(card)
            self.assertEqual(card["denominators"]["observed_sessions"], 0)
            self.assertEqual(card["denominators"]["unknown_session_invocations"], 1)
            self.assertEqual(card["denominators"]["unknown_phase_count"], 4)
            self.assertEqual(card["denominators"]["unknown_interaction_count"], 2)
            row = card["session_observations"][0]
            for field in ("elapsed_ns", "observed_phase_status_counts", "observed_interaction_status_counts", "phase_invocation_counts", "shutdown_status"):
                self.assertIsNone(row[field])
            self.assertIn(type(error).__name__, card["campaign"]["abort"]["error"])

    def test_lost_return_after_unit_commit_inventories_diagnostics_without_approving_endpoint(self):
        original = replay.run_replay

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected post-commit lost return")

        with mock.patch.object(replay, "run_replay", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["unknown_session_invocations"], 1)
        self.assertTrue(card["campaign"]["abort"]["diagnostic_inputs_present"])
        self.assertIn("session-000001-baseline/unit.json", {item["path"] for item in card["evidence"]["files"]})
        self.assertIsNone(card["session_observations"][0]["elapsed_ns"])

    def test_missing_phase_return_with_returned_session_retains_inner_uncertainty(self):
        original = timer.measure_and_publish

        def fail(*args, **kwargs):
            if Path(args[3]).name == "step-0002.json":
                raise OSError("injected phase return loss")
            return original(*args, **kwargs)

        with mock.patch.object(timer, "measure_and_publish", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["unknown_session_invocations"], 0)
        self.assertEqual(card["session_observations"][0]["phase_invocation_counts"], {"known_attempted": 2, "unknown": 1, "not_invoked": 1})

    def test_unconfirmed_receipt_publication_never_becomes_confirmed_in_card(self):
        original = timer.write_record

        def fail(path, value):
            if Path(path) == self.run / "receipt-000001-baseline.json":
                original(path, value)
                raise OSError("injected after receipt commit")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["denominators"]["session_status_counts"], {"completed_unqualified": 1, "not_run_run_aborted": 3})
        self.assertFalse(card["session_observations"][0]["receipt_record_committed"])
        self.assertTrue(card["campaign"]["abort"]["diagnostic_receipt_present"])

    def test_unconfirmed_session_metadata_is_not_promoted_by_card_inventory(self):
        original = timer.write_record

        def fail(path, value):
            if Path(path) == self.run / "block-000001-baseline.json":
                raise OSError("injected metadata publication failure")
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertTrue(card["session_observations"][0]["receipt_record_committed"])
        self.assertFalse(card["session_observations"][0]["session_record_committed"])
        self.assertTrue(card["campaign"]["abort"]["diagnostic_session_present"])

    def test_step_publication_fragments_stay_diagnostic_and_bound(self):
        original = timer.write_record

        def fail(path, value):
            if Path(path).name == "step-0002.json":
                Path(path).write_text("{}")
                return
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        self.assert_blocked(card)
        self.assertEqual(card["session_observations"][0]["unconfirmed_diagnostic_fragment_count"], 1)
        self.assertIn("unconfirmed_diagnostic_fragments", card["session_observations"][0]["outcome_reasons"])

    def test_unresolved_inputs_missing_guards_and_truncated_raw_block_all_comparisons(self):
        original = copy.deepcopy(self.plans)
        for mode in ("unresolved", "guard", "raw"):
            self.run = self.root / mode
            self.plans = copy.deepcopy(original)
            if mode == "guard":
                self.plans["baseline"]["preparation"]["guard_expectations"] = None
            elif mode == "raw":
                for plan in self.plans.values():
                    plan.update(capture_raw=True, raw_limit_bytes=4)
            self.produce(pairing=None if mode == "unresolved" else "fixture")
            card = cards.generate_result_card(self.run, bootstrap_resamples=20, bootstrap_seed=0)
            self.assert_blocked(card)
            self.assertEqual(card["denominators"]["session_status_counts"], {"completed_unqualified": 4})
            if mode == "raw":
                self.assertTrue(all(row["raw_capture_truncated_phase_count"] == 4 for row in card["session_observations"]))

    def test_whole_session_statistics_and_seeded_resampling_match_existing_summary(self):
        self.produce()
        source = summarize_run(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        card = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        self.assert_denominators(card)
        for field in ("status", "ratio", "absolute_latency_ns", "bootstrap", "latency_unit", "resampling_unit"):
            self.assertEqual(card["statistics"][field], source[field])
        self.assertEqual(card["statistics"]["bootstrap"]["blocks"], 2)
        self.assertEqual(card["denominators"]["planned_interaction_count"], 8)
        self.assertEqual(card["statistics"]["resampling_unit"], "whole_paired_complete_sessions")

    def test_same_bytes_options_and_relocated_bundle_reconstruct_identical_cards(self):
        self.produce()
        first = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        self.assertEqual(first, cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7))
        moved = self.root / "moved"
        shutil.copytree(self.run, moved)
        self.assertEqual(first, cards.generate_result_card(moved, bootstrap_resamples=30, bootstrap_seed=7))
        cards.inspect_result_card(first, moved)
        second = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=8)
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertNotEqual(first["reconstruction_sha256"], second["reconstruction_sha256"])

    def test_later_worktree_changes_do_not_replace_historical_evidence(self):
        self.produce()
        card = cards.generate_result_card(self.run)
        for cwd in self.cwds.values():
            for path in cwd.glob("report-*"):
                path.unlink()
            (cwd / "lease").touch()
        self.assertEqual(cards.inspect_result_card(card, self.run)["card_consistency"], "checked_unqualified")

    def test_qualification_upgrades_missing_unknowns_zeros_and_unit_relabels_fail_schema(self):
        self.produce()
        original = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        mutations = [lambda value: value.update(classification="qualified"),
                     lambda value: value.update(confirmatory_eligible=True),
                     lambda value: value.update(unexpected=True),
                     lambda value: value.update(sample_unit="replay_step"),
                     lambda value: value["statistics"].update(resampling_unit="interactions"),
                     lambda value: value["statistics"].update(resource_observation=0),
                     lambda value: value["denominators"].update(verified_independent_sessions=4),
                     lambda value: value["qualification"]["unresolved_fields"].pop("generation_validity"),
                     lambda value: value["qualification"]["unresolved_fields"].update(matched_replay_inputs_and_external_state=True),
                     lambda value: value["qualification"]["unresolved_fields"].update(whole_session_resource_accounting=0),
                     lambda value: value["session_observations"][0].update(sample_unit="replay_step")]
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                cards.validate_card(changed)

    def test_strict_integer_tokens_apply_through_all_shared_schema_references(self):
        self.produce()
        original = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        mutations = [lambda value: value["denominators"].update(planned_sessions=True),
                     lambda value: value["session_observations"][0].update(elapsed_ns=float(value["session_observations"][0]["elapsed_ns"])),
                     lambda value: value["context"]["sessions"]["baseline"].update(raw_limit_bytes=1024.0),
                     lambda value: value["statistics"]["bootstrap"].update(blocks=2.0),
                     lambda value: value["session_observations"][0]["phase_guard_counts"].update(matched=True),
                     lambda value: value["evidence"]["files"][0].update(bytes=True),
                     lambda value: value["statistics"].update(ratio=float("nan"))]
        for mutate in mutations:
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                cards.validate_card(changed)

    def test_forged_counts_statistics_options_and_reader_versions_fail_reconstruction(self):
        self.produce()
        original = cards.generate_result_card(self.run, bootstrap_resamples=30, bootstrap_seed=7)
        for mode in ("ratio", "elapsed", "counts", "seed", "runtime", "source", "hash"):
            changed = copy.deepcopy(original)
            if mode == "ratio":
                changed["statistics"]["ratio"] += 1
            elif mode == "elapsed":
                changed["session_observations"][0]["elapsed_ns"] += 1
            elif mode == "counts":
                changed["denominators"]["known_session_invocations"] = 0
            elif mode == "seed":
                changed["analysis_request"]["bootstrap_seed"] = 8
            elif mode == "runtime":
                changed["generator"]["runtime"]["jsonschema_version"] = "0.0.0"
            elif mode == "source":
                changed["generator"]["implementation"]["files"][0]["sha256"] = "0" * 64
            else:
                changed["reconstruction_sha256"] = "0" * 64
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_failed_not_run_sessions_cannot_be_omitted_or_reordered_into_favorable_card(self):
        self.plans["candidate"]["interactions"][0]["argv"][-1] = "fail"
        self.produce()
        original = cards.generate_result_card(self.run)
        for mode in ("omit", "order", "context", "cause", "commit"):
            changed = copy.deepcopy(original)
            if mode == "omit":
                changed["session_observations"] = changed["session_observations"][:2]
                changed["denominators"]["planned_sessions"] = 2
                changed["denominators"]["session_status_counts"].pop("not_run_run_aborted")
            elif mode == "order":
                changed["session_observations"].reverse()
            elif mode == "context":
                changed["context"]["sessions"]["baseline"]["preparation"]["argv"].append("unrequested")
            elif mode == "cause":
                changed["campaign"]["abort"]["error"] = "relabelled cause"
            else:
                changed["session_observations"][0]["session_record_committed"] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_unknown_session_cannot_be_relabelled_not_run_or_observed_with_fabricated_time(self):
        with mock.patch.object(replay, "run_replay", side_effect=OSError("injected missing return")):
            self.produce()
        original = cards.generate_result_card(self.run)
        for attempted in (False, True):
            changed = copy.deepcopy(original)
            changed["session_observations"][0]["invocation_attempted"] = attempted
            changed["session_observations"][0]["elapsed_ns"] = 0
            changed["denominators"]["unknown_session_invocations"] = 0
            changed["denominators"]["known_session_invocations" if attempted else "known_not_invoked_sessions"] += 1
            with self.assertRaises(ValueError):
                cards.inspect_result_card(changed, self.run)

    def test_whitespace_changes_bind_exact_bytes_even_if_source_summary_is_unchanged(self):
        self.produce()
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

    def test_unknown_session_diagnostic_bytes_are_bound_without_becoming_observations(self):
        original = replay.run_replay

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected missing return")

        with mock.patch.object(replay, "run_replay", side_effect=fail):
            self.produce()
        card = cards.generate_result_card(self.run)
        path = self.run / "session-000001-baseline/unit.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            cards.inspect_result_card(card, self.run)

    def test_missing_extra_and_corrupt_evidence_never_produces_subset_cards(self):
        self.produce()
        path = self.run / "receipt-000001-baseline.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())
        path.write_bytes(raw)
        extra = self.run / "extra.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            cards.write_result_card(self.run, self.output)
        extra.unlink()
        next((self.run / "session-000001-baseline/blobs").iterdir()).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_abort_is_not_a_complete_favorable_prefix(self):
        self.plans["baseline"]["preparation"]["argv"][-1] = "fail"
        self.produce()
        (self.run / "abort.json").unlink()
        with self.assertRaises(ValueError):
            cards.generate_result_card(self.run)

    def test_card_and_evidence_limits_reject_instead_of_truncating_sessions(self):
        self.produce()
        with mock.patch.object(cards, "MAX_CARD_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "no session or evidence entry may be truncated"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())
        for attribute in ("MAX_CAMPAIGN_FILES", "MAX_CAMPAIGN_BYTES"):
            with mock.patch.object(pairs, attribute, 1):
                with self.assertRaises(ValueError):
                    cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_fifo_nested_input_and_output_aliases_fail_safely(self):
        self.produce()
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

    def test_source_mutation_during_summary_fails_once_before_card_publication(self):
        self.produce()
        original = cards.summarize_run

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.run / "block-000001-baseline.json"
            path.write_bytes(path.read_bytes() + b"\n")
            return result

        with mock.patch.object(cards, "summarize_run", side_effect=mutate) as summarized:
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.write_result_card(self.run, self.output)
            summarized.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_post_publication_source_mutation_retains_stale_card_and_reports_failure(self):
        self.produce()
        original = cards.write_record

        def mutate(path, value):
            original(path, value)
            record = self.run / "block-000001-baseline.json"
            record.write_bytes(record.read_bytes() + b"\n")

        with mock.patch.object(cards, "write_record", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.write_result_card(self.run, self.output)
        self.assertTrue(self.output.exists())
        with self.assertRaises(ValueError):
            cards.inspect_result_card(json.loads(self.output.read_text()), self.run)

    def test_reader_source_changes_are_checked_without_editing_repository_files(self):
        self.produce()
        copied = self.root / "reader"
        copied.mkdir()
        for name in replay_cards.SOURCE_FILES:
            shutil.copyfile(HARNESS / name, copied / name)
        original = cards.summarize_run

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = copied / "replay_result_card.py"
            path.write_bytes(path.read_bytes() + b"\n")
            return result

        with mock.patch.object(replay_cards, "HARNESS", copied), mock.patch.object(cards, "summarize_run", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.generate_result_card(self.run)

    def test_identity_only_evidence_change_is_not_retried_or_accepted(self):
        self.produce()
        original = replay_cards.capture_evidence
        calls = []

        def mutate(directory):
            inventory, identity = original(directory)
            calls.append(1)
            if len(calls) > 1:
                identity[0]["schedule.json"]["identity"][-1] += 1  # Explicit synthetic ctime-only mutation.
            return inventory, identity

        with mock.patch.object(replay_cards, "capture_evidence", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "changed during generation/publication"):
                cards.generate_result_card(self.run)
        self.assertEqual(len(calls), 2)

    def test_existing_omitted_or_wrong_card_publications_never_overwrite_or_replay(self):
        self.produce()
        self.output.write_text("user work")
        with mock.patch.object(cards, "_build") as build:
            with self.assertRaises(FileExistsError):
                cards.write_result_card(self.run, self.output)
            build.assert_not_called()
        self.assertEqual(self.output.read_text(), "user work")
        for mode in ("error", "omit", "wrong"):
            self.output = self.root / f"card-{mode}.json"

            def fail(path, value):
                if mode == "error":
                    raise OSError("injected card disk error")
                if mode == "wrong":
                    Path(path).write_text("{}")

            with mock.patch.object(cards, "write_record", side_effect=fail), mock.patch.object(replay, "run_replay") as measured:
                with self.assertRaises((OSError, ValueError)):
                    cards.write_result_card(self.run, self.output)
                measured.assert_not_called()

    def test_missing_dependency_identity_fails_instead_of_inventing_runtime_version(self):
        self.produce()
        with mock.patch.object(cards, "version", side_effect=cards.PackageNotFoundError("fixture-only")):
            with self.assertRaisesRegex(ValueError, "dependency identity unavailable"):
                cards.write_result_card(self.run, self.output)
        self.assertFalse(self.output.exists())

    def test_legacy_kind_cannot_be_used_to_accept_or_relabel_replay_card(self):
        self.produce()
        card = cards.generate_result_card(self.run)
        card["kind"] = "paired_exploratory_result_card"
        with self.assertRaises(ValueError):
            cards.validate_card(card)

    def test_schema_and_references_are_closed_offline_and_valid(self):
        names = ("replay-result-card-v1.schema.json", "paired-replay-v1.schema.json", "managed-replay-v1.schema.json",
                 "result-card-v1.schema.json", "lifecycle-v2.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
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

    def test_cli_generates_and_inspects_complete_then_blocked_unknown_card(self):
        for mode in ("complete", "unknown"):
            self.run = self.root / mode
            self.output = self.root / f"{mode}-card.json"
            if mode == "unknown":
                with mock.patch.object(replay, "run_replay", side_effect=OSError("injected missing return")):
                    self.produce()
            else:
                self.produce()
            command = [sys.executable, str(HARNESS / "result_card.py"), str(self.run), "--output", str(self.output)]
            produced = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(produced.returncode, 0 if mode == "complete" else 1, produced.stderr)
            self.assertEqual(json.loads(produced.stdout)["planned_session_count"], 4)
            command = [sys.executable, str(HARNESS / "inspect_result_card.py"), str(self.output), "--run", str(self.run)]
            inspected = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            card = json.loads(self.output.read_text())
            card["classification"] = "qualified"
            self.output.write_text(json.dumps(card))
            inspected = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(inspected.returncode, 2)
            self.assertNotIn("Traceback", inspected.stderr)


if __name__ == "__main__":
    unittest.main()
