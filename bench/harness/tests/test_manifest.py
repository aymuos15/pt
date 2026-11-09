import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    spec = importlib.util.spec_from_file_location("manifest", HARNESS / "manifest.py")
    manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest)
finally:
    sys.path.pop(0)
TEMPLATE = (HARNESS.parent / "benchmark-campaign.template.yaml").read_text()


class ManifestTests(unittest.TestCase):
    def check_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.yaml"
            path.write_text(text)
            return manifest.check_structure(path)

    def check_data(self, data):
        return self.check_text(yaml.safe_dump(data))

    def test_draft_template_structural_validity_does_not_qualify(self):
        result = self.check_text(TEMPLATE)
        self.assertEqual(result["structure"], "valid")
        self.assertEqual(result["declared_status"], "draft")
        self.assertFalse(result["confirmatory_eligible"])
        self.assertIn("campaign_id", result["frozen_structure_error_paths"])
        self.assertIn("candidate.binary_sha256", result["frozen_structure_error_paths"])
        self.assertEqual(result["declaration_consistency"], "checked_unqualified")
        self.assertEqual(result["declaration_conflicts"], [])
        self.assertTrue(result["unchecked_requirements"])

    def test_frozen_label_does_not_bypass_checks(self):
        with self.assertRaises(manifest.ManifestError):
            self.check_text(TEMPLATE.replace("status: draft", "status: frozen", 1))

    def test_duplicate_key_rejected(self):
        with self.assertRaisesRegex(manifest.ManifestError, "duplicate mapping key"):
            self.check_text(TEMPLATE + "\nstatus: frozen\n")

    def test_alias_and_unsafe_tag_rejected(self):
        for text in ("a: &x 1\nb: *x\n", "!!python/object/apply:os.system ['true']"):
            with self.subTest(text=text), self.assertRaises(manifest.ManifestError):
                self.check_text(text)

    def test_bad_schema_and_oversized_input_rejected(self):
        for text in (TEMPLATE.replace("schema_version: 1", "schema_version: 2"),
                     "a" * (manifest.MAX_MANIFEST_BYTES + 1)):
            with self.subTest(length=len(text)), self.assertRaises(manifest.ManifestError):
                self.check_text(text)

    def test_nonfinite_yaml_values_rejected(self):
        for number in (".nan", ".inf", "-.inf"):
            text = TEMPLATE.replace("timeout_seconds: null", f"timeout_seconds: {number}")
            with self.subTest(number=number), self.assertRaisesRegex(
                    manifest.ManifestError, "non-finite"):
                self.check_text(text)

    def test_structurally_frozen_fake_hashes_still_not_qualified(self):
        data = yaml.safe_load(TEMPLATE)
        data["status"] = "frozen"
        data["campaign_id"] = "synthetic-not-a-real-campaign"
        for arm in ("baseline", "candidate"):
            data[arm].update({"revision": "a" * 40, "binary_sha256": "a" * 64,
                              "environment_lock_sha256": "a" * 64,
                              "interpreter_sha256": "a" * 64, "argv": ["/fake"],
                              "cwd": "/fake", "reset_script_sha256": "a" * 64,
                              "state_probe_sha256": "a" * 64})
        data["scenario"].update({"repository": "fake", "source_revision": "a" * 40,
                                 "expected_inventory_sha256": "a" * 64,
                                 "expected_outcome_artifact_sha256": "a" * 64,
                                 "output_profile": "fake",
                                 "reset_policy_document_sha256": "a" * 64})
        data["machine"].update({"profile_sha256": "a" * 64, "memory_budget_bytes": 1,
                                "memory_metric": "fake"})
        data["experiment"].update({"timeout_seconds": 1, "exclusion_policy_sha256": "a" * 64,
                                   "pilot_report_sha256": "a" * 64})
        data["analysis"].update({"practical_absolute_gain_seconds": 0.1,
                                 "analysis_code_sha256": "a" * 64})
        result = self.check_text(yaml.safe_dump(data))
        self.assertEqual(result["declared_status"], "frozen")
        self.assertEqual(result["frozen_structure_error_paths"], [])
        self.assertFalse(result["confirmatory_eligible"])

    def test_integer_fields_reject_boolean_and_integral_float_yaml_values(self):
        paths = [("schema_version",), ("scenario", "workers"), ("scenario", "expected_exit_code"),
                 ("machine", "memory_budget_bytes"), ("machine", "native_library_threads"),
                 ("experiment", "paired_blocks"), ("experiment", "minimum_time_windows"),
                 ("experiment", "random_seed"), ("analysis", "bootstrap_resamples"),
                 ("analysis", "bootstrap_seed")]
        for path in paths:
            original = yaml.safe_load(TEMPLATE)
            container = original
            for key in path[:-1]:
                container = container[key]
            integer = container[path[-1]] if container[path[-1]] is not None else 1
            for replacement in (True, float(integer)):
                container[path[-1]] = replacement
                with self.subTest(path=path, replacement=replacement), self.assertRaises(manifest.ManifestError):
                    self.check_data(original)

    def test_boolean_constants_cannot_be_replaced_by_zero_or_one(self):
        for section, fields in (("experiment", ("fixed_sample_count_before_confirmation",)),
                               ("analysis", ("dependence_review_required",)),
                               ("publication", ("require_correctness_qualification", "preserve_failed_and_excluded_samples",
                                                "publish_eligible_and_total_denominators", "include_idle_memory_and_session_cost",
                                                "allow_confirmatory_with_unresolved_fields"))):
            for field in fields:
                data = yaml.safe_load(TEMPLATE)
                data[section][field] = int(data[section][field])
                with self.subTest(section=section, field=field), self.assertRaises(manifest.ManifestError):
                    self.check_data(data)

    def test_numeric_fields_allow_finite_floats_but_not_boolean_substitutes(self):
        for section, field in (("machine", "cpu_budget"), ("experiment", "timeout_seconds"),
                               ("analysis", "confidence_level"), ("analysis", "practical_relative_gain"),
                               ("analysis", "practical_absolute_gain_seconds")):
            data = yaml.safe_load(TEMPLATE)
            data[section][field] = 0.5
            self.assertFalse(self.check_data(data)["confirmatory_eligible"])
            data[section][field] = True
            with self.subTest(section=section, field=field), self.assertRaises(manifest.ManifestError):
                self.check_data(data)

    def test_non_json_yaml_types_and_excessive_nesting_are_rejected(self):
        for value in ("2026-11-09", "!!set {one: null}", "!!binary YWJj", "1.0e+999"):
            text = TEMPLATE.replace("campaign_id: null", f"campaign_id: {value}")
            with self.subTest(value=value), self.assertRaises(manifest.ManifestError):
                self.check_text(text)
        with self.assertRaisesRegex(manifest.ManifestError, "nesting"):
            self.check_text("value: " + "[" * 1000 + "0" + "]" * 1000)

    def test_digest_revision_newline_and_command_nul_ambiguities_are_rejected(self):
        for section, field, value in (("candidate", "binary_sha256", "a" * 64 + "\n"),
                                      ("scenario", "source_revision", "a" * 40 + "\n"),
                                      ("candidate", "argv", ["python", "bad\0argument"]),
                                      ("baseline", "cwd", "/bad\0cwd")):
            data = yaml.safe_load(TEMPLATE)
            data[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(manifest.ManifestError):
                self.check_data(data)

    def test_affected_subset_cannot_be_declared_equal_work(self):
        data = yaml.safe_load(TEMPLATE)
        data["scenario"]["scope"] = "affected"
        report = self.check_data(data)
        self.assertEqual(report["structure"], "valid")
        self.assertEqual(report["declaration_consistency"], "conflicts_found")
        self.assertEqual(report["declaration_conflicts"], [{"code": "affected_scope_is_not_equal_work",
                                                           "fields": ["claim_family", "scenario.scope"]}])
        self.assertFalse(report["confirmatory_eligible"])
        data["claim_family"] = "incremental_feedback"
        data["primary_endpoint"] = "edit_to_complete_valid_result"
        self.assertEqual(self.check_data(data)["declaration_conflicts"], [])
        data["scenario"]["scope"] = "full"
        with self.assertRaises(manifest.ManifestError):
            self.check_data(data)

    def test_equal_work_mismatched_interpreter_pins_are_visible_not_silently_equalized(self):
        data = yaml.safe_load(TEMPLATE)
        data["baseline"]["interpreter_sha256"] = "a" * 64
        data["candidate"]["interpreter_sha256"] = "b" * 64
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"][0]["code"], "equal_work_interpreter_pins_differ")
        for value in ("a" * 64, None):
            data["candidate"]["interpreter_sha256"] = value
            report = self.check_data(data)
            self.assertEqual(report["declaration_conflicts"], [])
            self.assertFalse(report["confirmatory_eligible"], "matching or missing declarations do not verify real pins")

    def test_serial_contract_rejects_parallel_count_without_inventing_unknown_contract_semantics(self):
        data = yaml.safe_load(TEMPLATE)
        data["scenario"]["workers"] = 4
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"][0]["code"], "serial_contract_requires_one_worker")
        data["scenario"]["contract_id"] = "unassessed-parallel-contract"
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"], [])
        self.assertFalse(report["contract_recognized_for_declaration_checks"])
        self.assertFalse(report["confirmatory_eligible"])

    def test_amortization_requires_whole_session_units_and_endpoint(self):
        data = yaml.safe_load(TEMPLATE)
        data["claim_family"] = "prepared_session_amortization"
        report = self.check_data(data)
        self.assertEqual([item["code"] for item in report["declaration_conflicts"]],
                         ["amortization_requires_complete_session_cost", "amortization_requires_session_replay"])
        data["experiment"].update(sample_unit="complete_session_replay", analysis_unit="independent_paired_session")
        data["analysis"]["resampling_unit"] = "independent_paired_session"
        data["primary_endpoint"] = "complete_session_cost"
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"], [])
        self.assertFalse(report["confirmatory_eligible"], "declared replay does not prove lifecycle costs or independence")

    def test_session_endpoint_cannot_be_a_single_invocation_unit(self):
        data = yaml.safe_load(TEMPLATE)
        data["primary_endpoint"] = "complete_session_cost"
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"][0]["code"], "session_endpoint_requires_session_unit")

    def test_resampling_cannot_silently_change_the_independent_analysis_unit(self):
        data = yaml.safe_load(TEMPLATE)
        data["analysis"]["resampling_unit"] = "independent_paired_session"
        self.assertEqual(self.check_data(data)["declaration_conflicts"][0]["code"], "resampling_unit_differs_from_analysis_unit")
        data["analysis"]["resampling_unit"] = "higher_level_cluster"
        report = self.check_data(data)
        self.assertEqual(report["declaration_conflicts"], [])
        self.assertFalse(report["confirmatory_eligible"], "a declaration cannot prove cluster evidence or effective N")

    def test_multiple_conflicts_are_deterministic_and_source_is_never_rewritten(self):
        data = yaml.safe_load(TEMPLATE)
        data["scenario"].update(scope="affected", workers=4)
        data["analysis"]["resampling_unit"] = "independent_paired_session"
        raw = yaml.safe_dump(data).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.yaml"
            path.write_bytes(raw)
            first = manifest.check_structure(path)
            second = manifest.check_structure(path)
            self.assertEqual(first, second)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(raw).digest())
            self.assertEqual(len(first["declaration_conflicts"]), 3)
            self.assertEqual([item["code"] for item in first["declaration_conflicts"]],
                             sorted(item["code"] for item in first["declaration_conflicts"]))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "safe POSIX nonregular input check")
    def test_symlink_directory_and_fifo_inputs_are_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "real.yaml"
            source.write_text(TEMPLATE)
            link, fifo = root / "link.yaml", root / "fifo.yaml"
            link.symlink_to(source)
            os.mkfifo(fifo)
            for path in (link, fifo, root):
                with self.subTest(path=path), self.assertRaises(manifest.ManifestError):
                    manifest.check_structure(path)

    def test_field_diagnostics_do_not_echo_command_or_pin_values(self):
        data = yaml.safe_load(TEMPLATE)
        data["candidate"]["argv"] = ["private-token-do-not-echo", 0]
        with self.assertRaises(manifest.ManifestError) as caught:
            self.check_data(data)
        self.assertIn("candidate.argv", str(caught.exception))
        self.assertNotIn("private-token-do-not-echo", str(caught.exception))

    def test_cli_distinguishes_conflicting_declarations_from_malformed_input_and_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, marker = root / "campaign.yaml", root / "should-not-run"
            data = yaml.safe_load(TEMPLATE)
            data["candidate"]["argv"] = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
            for scope, exit_code in (("full", 0), ("affected", 1)):
                data["scenario"]["scope"] = scope
                path.write_text(yaml.safe_dump(data))
                checked = subprocess.run([sys.executable, str(HARNESS / "manifest.py"), str(path)],
                                         capture_output=True, text=True, timeout=15)
                self.assertEqual(checked.returncode, exit_code, checked.stderr)
                self.assertFalse(json.loads(checked.stdout)["confirmatory_eligible"])
                self.assertFalse(marker.exists())
            data["schema_version"] = True
            path.write_text(yaml.safe_dump(data))
            checked = subprocess.run([sys.executable, str(HARNESS / "manifest.py"), str(path)],
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(checked.returncode, 2)
            self.assertNotIn("Traceback", checked.stderr)


if __name__ == "__main__":
    unittest.main()
