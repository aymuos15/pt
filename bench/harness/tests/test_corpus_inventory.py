import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


HARNESS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("corpus_inventory", HARNESS / "corpus_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def manifest_text(path, digest, *, probe_id="example", allocation="unassigned"):
    return (f'schema_version = 1\nstatus = "draft_unqualified"\n[[probes]]\n'
            f'id = "{probe_id}"\npath = "{path}"\nsha256 = "{digest}"\n'
            f'expected_exit_code = 0\nallocation = "{allocation}"\n')


class CorpusInventoryTests(unittest.TestCase):
    def test_repository_inventory(self):
        result = inventory.check_inventory(HARNESS.parent / "corpus" / "manifest.toml")
        self.assertEqual(result["declared_probes_verified"], 5)
        self.assertFalse(result["behavior_qualified"])
        self.assertFalse(result["complete_tree_verified"])

    def test_modified_and_missing_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "probe.py"
            probe.write_bytes(b"initial")
            manifest = root / "manifest.toml"
            manifest.write_text(manifest_text("probe.py", hashlib.sha256(b"initial").hexdigest()))
            self.assertEqual(inventory.check_inventory(manifest)["declared_probes_verified"], 1)
            probe.write_bytes(b"changed")
            with self.assertRaisesRegex(inventory.InventoryError, "SHA-256 mismatch"):
                inventory.check_inventory(manifest)
            probe.unlink()
            with self.assertRaises(inventory.InventoryError):
                inventory.check_inventory(manifest)

    def test_escape_bad_digest_and_assignment_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "manifest.toml"
            valid_digest = "0" * 64
            for text in (manifest_text("../escape", valid_digest),
                         manifest_text("/absolute", valid_digest),
                         manifest_text("probe.py", "invalid"),
                         manifest_text("probe.py", valid_digest, allocation="holdout")):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(inventory.InventoryError):
                    inventory.check_inventory(path)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "corpus"
            root.mkdir()
            outside = parent / "outside.py"
            outside.write_bytes(b"outside")
            (root / "link.py").symlink_to(outside)
            path = root / "manifest.toml"
            path.write_text(manifest_text("link.py", hashlib.sha256(b"outside").hexdigest()))
            with self.assertRaises(inventory.InventoryError):
                inventory.check_inventory(path)


if __name__ == "__main__":
    unittest.main()
