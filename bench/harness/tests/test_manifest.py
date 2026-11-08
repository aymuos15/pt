import importlib.util
from pathlib import Path
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
