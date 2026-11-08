import base64
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location(
    "installed_inventory", Path(__file__).resolve().parents[1] / "installed_inventory.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def hashed_entry(path, content, mode="sha256"):
    encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
    return SimpleNamespace(path=path, hash=SimpleNamespace(mode=mode, value=encoded), size=len(content))


class FakeDistribution:
    def __init__(self, root, name, entries):
        self.root = root
        self.metadata = {"Name": name}
        self.files = entries

    def locate_file(self, entry):
        return self.root / entry.path


class InstalledInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "lib").mkdir()
        (self.root / "bin").mkdir()

    def test_hashed_files_verified_with_explicit_exclusions(self):
        (self.root / "lib" / "module.py").write_bytes(b"module")
        (self.root / "lib" / "RECORD").write_bytes(b"record")
        (self.root / "bin" / "tool").write_bytes(b"entrypoint")
        dist = FakeDistribution(self.root, "Example_Pkg", [
            hashed_entry("lib/module.py", b"module"),
            SimpleNamespace(path="lib/RECORD", hash=None, size=None),
            hashed_entry("bin/tool", b"entrypoint"),
        ])
        result = inventory.scan(self.root, [dist])
        self.assertEqual(result["record_hashed_files_verified"], 2)
        self.assertEqual(result["comparable_files"], 1)
        self.assertEqual(result["unhashed_record_entries"], ["example-pkg:lib/RECORD"])
        self.assertEqual(result["verified_noncomparable_entrypoints"], ["example-pkg:bin/tool"])
        self.assertFalse(result["unlisted_files_checked"])
        self.assertFalse(result["record_provenance_verified"])

    def test_changed_or_missing_hashed_file_fails(self):
        path = self.root / "lib" / "module.py"
        path.write_bytes(b"edited")
        dist = FakeDistribution(self.root, "example", [hashed_entry("lib/module.py", b"origin")])
        with self.assertRaisesRegex(inventory.InventoryError, "disagrees"):
            inventory.scan(self.root, [dist])
        path.unlink()
        with self.assertRaises(inventory.InventoryError):
            inventory.scan(self.root, [dist])

    def test_outside_symlink_and_duplicate_file_fail(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink, missing_ok=True)
        (self.root / "lib" / "escape").symlink_to(outside)
        with self.assertRaises(inventory.InventoryError):
            inventory.scan(self.root, [FakeDistribution(self.root, "x", [hashed_entry("lib/escape", b"outside")])])
        (self.root / "lib" / "module.py").write_bytes(b"module")
        entry = hashed_entry("lib/module.py", b"module")
        with self.assertRaisesRegex(inventory.InventoryError, "duplicate"):
            inventory.scan(self.root, [FakeDistribution(self.root, "x", [entry, entry])])

    def test_no_or_unsupported_hashes_fail(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.scan(self.root, [])
        (self.root / "lib" / "module.py").write_bytes(b"module")
        entry = hashed_entry("lib/module.py", b"module", mode="md5")
        with self.assertRaisesRegex(inventory.InventoryError, "unsupported"):
            inventory.scan(self.root, [FakeDistribution(self.root, "x", [entry])])


if __name__ == "__main__":
    unittest.main()
