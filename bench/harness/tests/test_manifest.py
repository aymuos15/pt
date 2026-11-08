import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml


HARNESS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manifest", HARNESS / "manifest.py")
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)
TEMPLATE = (HARNESS.parent / "benchmark-campaign.template.yaml").read_text()


class ManifestTests(unittest.TestCase):
    def check_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.yaml"
            path.write_text(text)
            return manifest.check_structure(path)

    def test_draft_template_structural_validity_does_not_qualify(self):
        result = self.check_text(TEMPLATE)
        self.assertEqual(result["structure"], "valid")
        self.assertEqual(result["declared_status"], "draft")
        self.assertFalse(result["confirmatory_eligible"])
        self.assertIn("campaign_id", result["frozen_structure_error_paths"])
        self.assertIn("candidate.binary_sha256", result["frozen_structure_error_paths"])

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


if __name__ == "__main__":
    unittest.main()
