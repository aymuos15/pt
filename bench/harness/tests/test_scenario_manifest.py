"""Offline manifest association controls; declared pins never become qualifications."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import test_paired_scenarios as controls


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import scenario_manifest as bindings
    import paired_scenarios as pairs
    import scenario_replay as scenario
    import scenario_inputs as inputs
    import pt_bench as timer
    import manifest as manifests
    import result_card as cards
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial safe Linux scenario/blob profile")
class ScenarioManifestTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controls.PairedScenarioTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.output, self.plans = self.fixture.root, self.fixture.output, self.fixture.plans
        self.path = self.root / "campaign.yaml"
        self.data = yaml.safe_load((HARNESS.parent / "benchmark-campaign.template.yaml").read_text())
        self.data["experiment"].update(paired_blocks=2, random_seed=0, sample_unit="complete_session_replay",
                                       analysis_unit="independent_paired_session", timeout_seconds=20)
        self.data["analysis"]["resampling_unit"] = "independent_paired_session"
        self.data["scenario"]["id"] = "S3"
        for arm in pairs.ARMS:
            self.data[arm]["cwd"] = self.plans[arm]["cwd"]
        self.save_manifest()

    def save_manifest(self):
        self.path.write_text(yaml.safe_dump(self.data))

    def produce(self):
        self.report = self.fixture.produce()
        return self.report

    def generate(self):
        self.binding = bindings.generate_binding(self.path, self.output)
        self.assert_counts(self.binding)
        return self.binding

    def assert_counts(self, value):
        counts = value["denominators"]
        self.assertEqual(counts["planned_session_count"], 4)
        self.assertEqual(len(value["session_observations"]), 4)
        self.assertEqual(sum(counts["session_status_counts"].values()), 4)
        for noun, total in (("request", 8), ("phase", 24), ("file_effect", 48)):
            self.assertEqual(counts[f"planned_{noun}_count"], total)
            self.assertEqual(sum(counts[f"{noun}_status_counts"].values()), total)
        self.assertEqual(counts["attempted_unit_calls"] + counts["known_not_called_units"], 4)
        self.assertEqual(sum(counts[key] for key in ("known_request_invocations", "unknown_request_invocations", "known_not_invoked_requests")), 8)
        self.assertEqual(value["qualification"], {key: None for key in bindings.QUALIFICATION})
        self.assertEqual(value["statistics"], {key: None for key in ("ratio", "absolute_latency_ns", "bootstrap", "resource_observation")})
        self.assertFalse(value["confirmatory_eligible"])
        self.assertEqual(value["status"], "blocked")
        self.assertEqual(sum(value["check_status_counts"].values()), len(value["declaration_checks"]))
        self.assertEqual(value["manifest"]["declaration"], self.data)

    def inspect(self, value=None):
        return bindings.inspect_binding(self.binding if value is None else value, self.path, self.output)

    def uniform_commands(self):
        code = ("import json; from pathlib import Path; p=json.loads(Path('request.json').read_text()); "
                "assert Path('source.txt').read_text()==p['data']['source.txt']; "
                "Path('report-'+p['request_id']).write_text('ready\\n'); print('ready')")
        for arm, plan in self.plans.items():
            for request in plan["requests"]:
                request["command"]["argv"] = [sys.executable, "-c", code]
            self.data[arm]["argv"] = copy.deepcopy(plan["requests"][0]["command"]["argv"])
        self.save_manifest()

    def checks(self, value, field):
        return [item for item in value["declaration_checks"] if item["manifest_field"] == field]

    def test_binding_retains_manifest_nulls_all_planned_outcomes_and_each_actual_reset_input(self):
        self.produce()
        value = self.generate()
        self.assertEqual(value["declaration_consistency"], "checked_unqualified")
        self.assertIn("candidate.binary_sha256", value["manifest"]["frozen_structure_error_paths"])
        self.assertEqual(value["manifest"]["bytes"], self.path.stat().st_size)
        self.assertEqual(value["manifest"]["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        for original, observed in zip(self.report["session_observations"], value["session_observations"]):
            self.assertEqual(observed, {key: item for key, item in original.items() if key != "scenario_summary"})
            self.assertIsNotNone(observed["reset_evidence"]["before"])
            self.assertTrue(all(request["observed_input"] is not None for request in observed["request_observations"]))
        self.assertEqual(self.inspect()["binding_consistency"], "checked_unqualified")

    def test_uniform_manifest_argv_is_checked_against_every_request_not_only_the_first(self):
        self.uniform_commands()
        self.produce()
        value = self.generate()
        for arm in pairs.ARMS:
            self.assertEqual([check["status"] for check in self.checks(value, arm + ".argv")], ["matched_declaration"] * 2)
        self.assertEqual(value["declaration_consistency"], "checked_unqualified")

    def test_heterogeneous_requests_cannot_be_linked_by_selecting_a_matching_first_command(self):
        for arm in pairs.ARMS:
            self.data[arm]["argv"] = copy.deepcopy(self.plans[arm]["requests"][0]["command"]["argv"])
        self.save_manifest()
        self.produce()
        value = self.generate()
        for arm in pairs.ARMS:
            self.assertEqual([check["status"] for check in self.checks(value, arm + ".argv")], ["matched_declaration", "conflicting_declaration"])
        self.assertEqual(value["declaration_consistency"], "conflicts_found")
        self.assertEqual(self.inspect()["binding_consistency"], "checked_unqualified")

    def test_manifest_single_expected_exit_must_describe_every_request(self):
        for plan in self.plans.values():
            command = plan["requests"][1]["command"]
            command["argv"][-1] = "fail"
            command["guard_expectations"]["expected_exit_code"] = command["required_finalization"]["expected_exit_code"] = 7
        self.produce()
        value = self.generate()
        self.assertEqual(value["denominators"]["session_status_counts"], {"completed_unqualified": 4})
        checks = self.checks(value, "scenario.expected_exit_code")
        self.assertEqual(sum(check["status"] == "conflicting_declaration" for check in checks), 2)

    def test_declared_cache_unknowns_are_not_inferred_from_manifest_warm_or_cold_policies(self):
        self.produce()
        value = self.generate()
        checks = [check for check in value["declaration_checks"] if check["manifest_field"].startswith("scenario.cache_state.")]
        self.assertEqual(len(checks), 16)
        self.assertTrue(all(check["status"] == "unknown_evidence_declaration" for check in checks))
        self.assertTrue(all(value is None for value in value["qualification"].values()))

    def test_declared_cache_matches_are_not_cache_or_reset_qualification(self):
        for plan in self.plans.values():
            plan["scenario"]["cache_state"] = copy.deepcopy(self.data["scenario"]["cache_state"])
        self.produce()
        value = self.generate()
        checks = [check for check in value["declaration_checks"] if check["manifest_field"].startswith("scenario.cache_state.")]
        self.assertTrue(all(check["status"] == "matched_declaration" for check in checks))
        self.assertIsNone(value["qualification"]["reset_equivalence"])

    def test_mismatched_id_cache_cwd_seed_counts_units_and_budgets_remain_visible_conflicts(self):
        self.produce()
        original = copy.deepcopy(self.data)
        for mode in ("id", "cwd", "seed", "count", "unit", "budget"):
            self.data = copy.deepcopy(original)
            if mode == "id":
                self.data["scenario"]["id"] = "S4"
            elif mode == "cwd":
                self.data["baseline"]["cwd"] = "/different/worktree"
            elif mode == "seed":
                self.data["experiment"]["random_seed"] = 1
            elif mode == "count":
                self.data["experiment"]["paired_blocks"] = 1
            elif mode == "unit":
                self.data["experiment"]["sample_unit"] = "complete_invocation"
            else:
                self.data["experiment"]["timeout_seconds"] = 19
            self.save_manifest()
            with self.subTest(mode=mode):
                value = self.generate()
                self.assertEqual(value["declaration_consistency"], "conflicts_found")
                self.assertTrue(any(check["status"] == "conflicting_declaration" for check in value["declaration_checks"]))

    def test_explicit_different_known_cache_declaration_is_not_an_unknown_or_match(self):
        for plan in self.plans.values():
            plan["scenario"]["cache_state"]["source"] = "edited"
        self.produce()
        value = self.generate()
        self.assertTrue(all(check["status"] == "conflicting_declaration" for check in self.checks(value, "scenario.cache_state.source")))

    def test_original_manifest_declaration_conflicts_are_preserved_not_hidden_by_evidence(self):
        self.data["claim_family"] = "equal_work"
        self.data["scenario"]["scope"] = "affected"
        self.save_manifest()
        self.produce()
        value = self.generate()
        self.assertIn("affected_scope_is_not_equal_work", [item["code"] for item in value["manifest"]["declaration_conflicts"]])
        self.assertEqual(value["declaration_consistency"], "conflicts_found")

    def test_shipping_endpoint_analysis_script_and_resource_pins_remain_unverified_even_when_plausible(self):
        for arm in pairs.ARMS:
            self.data[arm]["reset_script_sha256"] = "a" * 64
            self.data[arm]["state_probe_sha256"] = "b" * 64
        self.data["scenario"]["reset_policy_document_sha256"] = "c" * 64
        self.save_manifest()
        self.produce()
        value = self.generate()
        for field in ("primary_endpoint", "analysis", "machine", "baseline.reset_script_sha256", "candidate.state_probe_sha256", "scenario.reset_policy_document_sha256"):
            self.assertEqual(self.checks(value, field)[0]["status"], "not_observed_by_profile")
        self.assertEqual(self.checks(value, "experiment.sample_unit")[0]["relation"], "whole_session_scope_only")
        self.assertEqual(self.checks(value, "experiment.timeout_seconds")[0]["relation"], "execution_dispatch_budget_only")

    def test_frozen_looking_manifest_does_not_imply_preregistration_or_verified_artifacts(self):
        self.data.update(status="frozen", campaign_id="test-only-fake-pins")
        for arm in pairs.ARMS:
            self.data[arm].update(revision="a" * 40, binary_sha256="a" * 64, environment_lock_sha256="a" * 64,
                                  interpreter_sha256="a" * 64, reset_script_sha256="a" * 64, state_probe_sha256="a" * 64,
                                  argv=self.plans[arm]["requests"][0]["command"]["argv"])
        self.data["scenario"].update(repository="test-owned", source_revision="a" * 40, expected_inventory_sha256="a" * 64,
                                      expected_outcome_artifact_sha256="a" * 64, output_profile="test", reset_policy_document_sha256="a" * 64)
        self.data["machine"].update(profile_sha256="a" * 64, memory_budget_bytes=1, memory_metric="test")
        self.data["experiment"].update(exclusion_policy_sha256="a" * 64, pilot_report_sha256="a" * 64)
        self.data["analysis"].update(practical_absolute_gain_seconds=0.1, analysis_code_sha256="a" * 64)
        self.save_manifest()
        self.produce()
        value = self.generate()
        self.assertEqual(value["manifest"]["frozen_structure_error_paths"], [])
        self.assertIsNone(value["qualification"]["manifest_preregistration"])
        self.assertIsNone(value["qualification"]["artifact_provenance"])

    def test_failed_campaign_and_not_run_work_remain_in_every_bound_denominator(self):
        self.plans["baseline"]["requests"][0]["command"]["argv"][-1] = "fail"
        self.produce()
        value = self.generate()
        self.assertEqual(value["denominators"]["session_status_counts"], {"aborted": 1, "not_run_campaign_aborted": 3})
        self.assertEqual(value["denominators"]["request_status_counts"], {"failed": 1, "not_run_campaign_aborted": 6, "not_run_prior_failure": 1})
        self.assertEqual(value["campaign"]["abort"]["reason"], "session_failed")
        self.assertEqual(value["campaign"]["plan"]["schedule"], self.report["schedule"])
        self.assertEqual(self.inspect()["denominators"], value["denominators"])

    def test_unsupported_profiles_keep_all_not_run_reset_input_and_effect_observations(self):
        for plan in self.plans.values():
            plan["scenario"]["id"] = "S9"
        self.data["scenario"]["id"] = "S9"
        self.save_manifest()
        self.produce()
        value = self.generate()
        self.assertEqual(value["denominators"]["session_status_counts"], {"unsupported": 4})
        self.assertEqual(value["denominators"]["file_effect_status_counts"], {"not_run": 48})
        self.assertTrue(all(request["observed_input"] is None for row in value["session_observations"] for request in row["request_observations"]))

    def test_partial_reset_effects_are_not_promoted_to_confirmed_returns(self):
        original = inputs.mutate

        def lose(root, observed, desired, bundle):
            result = original(root, observed, desired, bundle)
            if observed["path"] == "source.txt":
                raise OSError("test-only lost file-effect return after installation")
            return result

        with mock.patch.object(inputs, "mutate", side_effect=lose):
            self.produce()
        value = self.generate()
        self.assertEqual(value["denominators"]["file_effect_status_counts"]["unknown"], 1)
        self.assertEqual(value["denominators"]["known_request_invocations"], 0)
        self.assertEqual(value["session_observations"][0]["reset_status"], "failed")

    def test_whole_return_loss_never_recovers_reset_input_or_request_outcomes_from_complete_files(self):
        original = scenario.run_scenario

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("test-only whole-session return loss after commit")

        with mock.patch.object(scenario, "run_scenario", side_effect=lost):
            self.produce()
        with mock.patch.object(scenario, "inspect_scenario", side_effect=AssertionError("recovered a missing return")):
            value = self.generate()
            self.inspect()
        row = value["session_observations"][0]
        self.assertIsNone(row["reset_evidence"])
        self.assertEqual(value["denominators"]["unknown_request_invocations"], 2)
        self.assertEqual(value["denominators"]["file_effect_status_counts"], {"not_run": 36, "unknown_unobserved": 12})
        self.assertTrue(all(request["observed_input"] is None for request in row["request_observations"]))

    def test_unconfirmed_paired_publication_retains_returned_observations_and_false_commit_flags(self):
        original = timer.write_record

        def fail(path, value):
            original(path, value)
            if Path(path) == self.output / "receipt-000001-baseline.json":
                raise OSError("test-only unconfirmed paired receipt publication")

        with mock.patch.object(timer, "write_record", side_effect=fail):
            self.produce()
        value = self.generate()
        row = value["session_observations"][0]
        self.assertFalse(row["receipt_record_committed"])
        self.assertTrue(row["unit_observation_returned"])
        self.assertIsNotNone(row["reset_evidence"])
        self.assertEqual(value["campaign"]["record_consistency"], "aborted")

    def test_no_current_worktree_subject_reset_artifact_or_controller_calls_during_binding(self):
        self.produce()
        before = pairs._snapshot(self.output)
        manifest_bytes = self.path.read_bytes()
        with mock.patch.object(scenario, "run_scenario") as run, mock.patch.object(inputs, "mutate") as mutate, mock.patch.object(inputs, "read", side_effect=AssertionError("live file read")), mock.patch.object(timer, "measure_and_publish") as measure:
            self.generate()
            self.inspect()
            run.assert_not_called()
            mutate.assert_not_called()
            measure.assert_not_called()
        self.assertEqual(pairs._snapshot(self.output), before)
        self.assertEqual(self.path.read_bytes(), manifest_bytes)

    def test_identical_sources_repeat_and_relocate_but_manifest_comment_changes_are_bound(self):
        self.produce()
        value = self.generate()
        self.assertEqual(bindings.generate_binding(self.path, self.output), value)
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        path = self.root / "renamed.yaml"
        path.write_bytes(self.path.read_bytes())
        self.assertEqual(bindings.generate_binding(path, moved), value)
        path.write_bytes(path.read_bytes() + b"\n# changed bytes, same declaration\n")
        with self.assertRaisesRegex(ValueError, "differs from reconstructed"):
            bindings.inspect_binding(value, path, moved)

    def test_omitted_reordered_duplicated_or_relabelled_observations_fail_even_with_recomputed_digest(self):
        self.produce()
        original = self.generate()
        for mode in ("subset", "duplicate", "order", "unit", "requests", "reset", "counts", "checks"):
            value = copy.deepcopy(original)
            if mode == "subset":
                value["session_observations"].pop()
            elif mode == "duplicate":
                value["session_observations"][1] = copy.deepcopy(value["session_observations"][0])
            elif mode == "order":
                value["session_observations"].reverse()
            elif mode == "unit":
                value["session_observations"][0]["sample_unit"] = "replay_step"
            elif mode == "requests":
                value["session_observations"][0]["request_observations"].pop()
            elif mode == "reset":
                value["session_observations"][0]["reset_evidence"] = None
            elif mode == "counts":
                value["denominators"]["planned_request_count"] -= 1
            else:
                value["declaration_checks"].pop()
            value["reconstruction_sha256"] = bindings._reconstruction(value)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.inspect(value)

    def test_declared_nulls_check_verdicts_inventory_or_manifest_values_cannot_be_forged(self):
        self.produce()
        original = self.generate()
        for mode in ("null", "check", "inventory", "manifest", "implementation", "runtime"):
            value = copy.deepcopy(original)
            if mode == "null":
                value["manifest"]["declaration"]["candidate"]["binary_sha256"] = "a" * 64
            elif mode == "check":
                value["declaration_checks"][0]["status"] = "matched_declaration"
            elif mode == "inventory":
                value["evidence"]["files"].pop()
            elif mode == "manifest":
                value["manifest"]["sha256"] = "0" * 64
            elif mode == "implementation":
                value["generator"]["implementation"]["files"].pop()
            else:
                value["generator"]["runtime"]["python_version"] = "0.0.0"
            value["reconstruction_sha256"] = bindings._reconstruction(value)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.inspect(value)

    def test_qualification_status_statistics_and_strict_numeric_tokens_cannot_be_promoted(self):
        self.produce()
        original = self.generate()
        mutations = (lambda value: value.update(status="qualified"), lambda value: value.update(confirmatory_eligible=True),
                     lambda value: value.update(schema_version=True), lambda value: value.update(extra=1),
                     lambda value: value["qualification"].update(reset_equivalence=True), lambda value: value["qualification"].pop("manifest_preregistration"),
                     lambda value: value["statistics"].update(ratio=1.1), lambda value: value["denominators"].update(planned_request_count=8.0),
                     lambda value: value["manifest"]["declaration"].update(schema_version=True))
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            with self.assertRaises(ValueError):
                bindings.validate_binding(value)

    def test_manifest_yaml_ambiguities_and_nonregular_or_oversized_inputs_fail_before_inspection(self):
        raw = self.path.read_bytes()
        for content in (raw + b"\nstatus: draft\n", b"a: &x 1\nb: *x\n", raw.replace(b"paired_blocks: 2", b"paired_blocks: 2.0"),
                        b"a: " + b"[" * 1000 + b"0" + b"]" * 1000, b"x" * (manifests.MAX_MANIFEST_BYTES + 1)):
            self.path.write_bytes(content)
            with mock.patch.object(pairs, "inspect_pairs") as inspected:
                with self.assertRaises(ValueError):
                    bindings.generate_binding(self.path, self.output)
                inspected.assert_not_called()
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaises(ValueError):
            bindings.generate_binding(self.path, self.output)

    def test_manifest_mutation_between_load_and_check_is_rejected_without_retry(self):
        original = manifests.load_structural_manifest

        def change(path):
            result = original(path)
            path.write_bytes(path.read_bytes() + b"\n")
            return result

        with mock.patch.object(manifests, "load_structural_manifest", side_effect=change) as loaded:
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                bindings.generate_binding(self.path, self.output)
            loaded.assert_called_once()

    def test_evidence_and_implementation_identity_changes_fail_without_reconstruction_retry(self):
        self.produce()
        for name in ("capture_evidence", "capture_implementation"):
            original, calls = getattr(bindings, name), []

            def change(*args):
                value = original(*args)
                calls.append(1)
                if len(calls) > 1:
                    if name == "capture_evidence":
                        value[1][0]["schedule.json"]["identity"][-1] += 1
                    else:
                        next(iter(value[1].values()))[-1] += 1
                return value

            with mock.patch.object(bindings, name, side_effect=change):
                with self.assertRaisesRegex(ValueError, "changed; no retry"):
                    bindings.generate_binding(self.path, self.output)
            self.assertEqual(len(calls), 2)

    def test_missing_or_corrupt_nested_evidence_fails_not_a_smaller_report(self):
        self.produce()
        self.generate()
        unit = self.fixture.saved("session-000001-baseline/unit.json")
        unit["phases"].pop()
        self.fixture.rebind_unit(unit)
        with self.assertRaisesRegex(ValueError, "omitted planned"):
            self.inspect()

    def test_wrong_campaign_kind_is_not_reinterpreted_or_used_as_a_latency_binding(self):
        self.output.mkdir()
        (self.output / "schedule.json").write_text(json.dumps({"kind": "paired_managed_replay_campaign"}))
        with self.assertRaises(ValueError):
            bindings.generate_binding(self.path, self.output)

    def test_recursive_inventory_includes_shared_payloads_empty_blob_directories_and_diagnostic_fragments(self):
        self.produce()
        value = self.generate()
        names = [item["path"] for item in value["evidence"]["files"]]
        self.assertTrue(any(name.startswith("payloads/") for name in names))
        self.assertIn("payloads", value["evidence"]["directories"])
        for row in value["session_observations"]:
            directory = f"session-{row['context']['block']:06d}-{row['context']['arm']}"
            self.assertIn(directory + "/blobs", value["evidence"]["directories"])
        self.assertEqual(value["evidence"]["total_bytes"], sum(item["bytes"] for item in value["evidence"]["files"]))

    def test_binding_byte_limit_never_trims_manifest_rows_or_evidence(self):
        self.produce()
        with mock.patch.object(bindings, "MAX_BINDING_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "no declaration or planned outcome"):
                bindings.generate_binding(self.path, self.output)
        self.assertFalse((self.root / "binding.json").exists())

    def test_publication_is_private_no_overwrite_and_outside_bound_run(self):
        self.produce()
        with self.assertRaisesRegex(ValueError, "outside the bound campaign"):
            bindings.write_binding(self.path, self.output, self.output / "binding.json")
        output = self.root / "binding.json"
        value = bindings.write_binding(self.path, self.output, output)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(output.read_text()), value)
        with self.assertRaises(FileExistsError):
            bindings.write_binding(self.path, self.output, output)
        self.assertEqual(json.loads(output.read_text()), value)

    def test_omitted_wrong_or_unconfirmed_binding_publication_is_not_approved(self):
        self.produce()
        original = timer.write_record
        for mode in ("omit", "wrong", "after"):
            output = self.root / (mode + ".json")

            def fail(path, value):
                if mode == "wrong":
                    Path(path).write_text("{}")
                elif mode == "after":
                    original(path, value)
                    raise OSError("test-only lost binding publication return")

            with mock.patch.object(timer, "write_record", side_effect=fail):
                with self.assertRaises((OSError, ValueError)):
                    bindings.write_binding(self.path, self.output, output)

    def test_schema_references_resolve_offline_with_unchanged_original_manifest_schema(self):
        names = ("scenario-manifest-v1.schema.json", "paired-scenario-v1.schema.json", "scenario-replay-v1.schema.json",
                 "paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json",
                 "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
        schemas = [json.loads((HARNESS / name).read_text()) for name in names]
        campaign = json.loads(manifests.SCHEMA_PATH.read_text())
        registry = Registry().with_resources([(schema["$id"], Resource.from_contents(schema)) for schema in schemas] + [
            ("urn:pt:bench:benchmark-campaign-v1", Resource.from_contents(campaign))])
        pending = [(schema, schema["$id"]) for schema in schemas] + [(campaign, "urn:pt:bench:benchmark-campaign-v1")]
        for schema, _ in pending:
            Draft202012Validator.check_schema(schema)
        while pending:
            value, base = pending.pop()
            if isinstance(value, dict):
                if "$ref" in value:
                    registry.resolver(base_uri=base).lookup(value["$ref"])
                pending.extend((child, base) for child in value.values())
            elif isinstance(value, list):
                pending.extend((child, base) for child in value)

    def test_cli_bind_inspect_conflict_and_bootstrap_refusal_do_not_execute_manifest_commands(self):
        self.produce()
        marker = self.root / "must-not-exist"
        self.data["candidate"]["argv"] = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
        self.save_manifest()
        output = self.root / "binding.json"
        command = [sys.executable, str(HARNESS / "scenario_manifest.py"), "bind", "--manifest", str(self.path), "--run", str(self.output), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["declaration_consistency"], "conflicts_found")
        result = subprocess.run([sys.executable, str(HARNESS / "scenario_manifest.py"), "inspect", "--manifest", str(self.path),
                                 "--run", str(self.output), "--binding", str(output)], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        result = subprocess.run([*command, "--bootstrap-resamples", "20"], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
