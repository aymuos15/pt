import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HARNESS = Path(__file__).resolve().parents[1]
RESET = HARNESS.parent / "resets" / "restore_declared_files.py"
spec = importlib.util.spec_from_file_location("restore_declared_files", RESET)
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


def declaration(path, content):
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest()}


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW")
                     and all(fn in os.supports_dir_fd for fn in (os.open, os.stat, os.rename, os.unlink)),
                     "requires POSIX descriptor-relative operations")
class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / "seed"
        self.target = self.root / "target"
        for directory in (self.seed, self.target):
            (directory / "nested").mkdir(parents=True)
        (self.seed / "first").write_bytes(b"fresh-one")
        (self.seed / "nested" / "second").write_bytes(b"fresh-two")
        (self.target / "first").write_bytes(b"dirty-one")
        (self.target / "nested" / "second").write_bytes(b"dirty-two")
        (self.target / "unrelated").write_bytes(b"untouched")
        self.files = [declaration("first", b"fresh-one"), declaration("nested/second", b"fresh-two")]

    def test_restores_only_declared_existing_files(self):
        (self.target / "first").chmod(0o640)
        result = reset.restore(self.seed, self.target, self.files, max_file_bytes=100)
        self.assertEqual((self.target / "first").read_bytes(), b"fresh-one")
        self.assertEqual((self.target / "nested" / "second").read_bytes(), b"fresh-two")
        self.assertEqual((self.target / "unrelated").read_bytes(), b"untouched")
        self.assertEqual(stat.S_IMODE((self.target / "first").stat().st_mode), 0o640)
        self.assertEqual(result["status"], "applied_unqualified")
        self.assertFalse(result["atomic_multi_file"])
        self.assertFalse(result["confirmatory_eligible"])
        self.assertEqual(list(self.target.rglob(".pt-reset-*.tmp")), [])

    def test_bad_later_seed_does_not_apply_earlier_stage(self):
        self.files[1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(reset.ResetError, "after 0 replacements"):
            reset.restore(self.seed, self.target, self.files, max_file_bytes=100)
        self.assertEqual((self.target / "first").read_bytes(), b"dirty-one")
        self.assertEqual((self.target / "nested" / "second").read_bytes(), b"dirty-two")
        self.assertEqual(list(self.target.rglob(".pt-reset-*.tmp")), [])

    def test_failure_during_apply_is_reported_as_partial(self):
        original = os.rename
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected rename failure")
            return original(*args, **kwargs)

        with mock.patch.object(reset.os, "rename", side_effect=fail_second):
            # Capability detection uses the original function object.
            with mock.patch.object(reset.os, "supports_dir_fd", reset.os.supports_dir_fd | {reset.os.rename}):
                with self.assertRaisesRegex(reset.ResetError, "after 1 replacements"):
                    reset.restore(self.seed, self.target, self.files, max_file_bytes=100)
        self.assertEqual((self.target / "first").read_bytes(), b"fresh-one")
        self.assertEqual((self.target / "nested" / "second").read_bytes(), b"dirty-two")
        self.assertEqual(list(self.target.rglob(".pt-reset-*.tmp")), [])

    def test_symlink_or_missing_target_fails_without_touching_other_files(self):
        original = self.target / "first"
        original.unlink()
        original.symlink_to(self.target / "unrelated")
        with self.assertRaises(reset.ResetError):
            reset.restore(self.seed, self.target, self.files, max_file_bytes=100)
        self.assertEqual((self.target / "unrelated").read_bytes(), b"untouched")
        original.unlink()
        with self.assertRaises(reset.ResetError):
            reset.restore(self.seed, self.target, self.files, max_file_bytes=100)

    def test_invalid_paths_overlapping_roots_and_missing_apply_are_rejected(self):
        for files in ([declaration("../escape", b"x")], [self.files[0], self.files[0]]):
            with self.subTest(files=files), self.assertRaises(reset.ResetError):
                reset.restore(self.seed, self.target, files, max_file_bytes=100)
        with self.assertRaises(reset.ResetError):
            reset.restore(self.seed, self.seed, self.files, max_file_bytes=100)
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1, "files": self.files}))
        result = subprocess.run([sys.executable, str(RESET), "--manifest", str(manifest),
                                 "--seed-root", str(self.seed), "--target-root", str(self.target)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--apply is required", result.stderr)
        self.assertEqual((self.target / "first").read_bytes(), b"dirty-one")

    def test_manifest_duplicate_keys_and_oversized_seed_are_rejected(self):
        manifest = self.root / "manifest.json"
        manifest.write_text('{"schema_version":1,"schema_version":1,"files":[]}')
        with self.assertRaisesRegex(reset.ResetError, "duplicate manifest key"):
            reset.load_manifest(manifest)
        with self.assertRaisesRegex(reset.ResetError, "size limit"):
            reset.restore(self.seed, self.target, self.files, max_file_bytes=2)
        self.assertEqual((self.target / "first").read_bytes(), b"dirty-one")

    def test_failed_reset_prevents_paired_arm_execution(self):
        manifest = self.root / "bad-manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1, "files": [
            {"path": "first", "sha256": "0" * 64},
        ]}))
        prepare = [sys.executable, str(RESET), "--manifest", str(manifest), "--seed-root", str(self.seed),
                   "--target-root", ".", "--apply"]
        baseline_marker = self.target / "must-not-run"
        baseline = [sys.executable, "-c", f"from pathlib import Path; Path({str(baseline_marker)!r}).touch()"]
        candidate = [sys.executable, "-c", "pass"]
        output = self.root / "failed-run"
        result = subprocess.run([
            sys.executable, str(HARNESS / "paired.py"), "--output", str(output), "--cwd", str(self.root),
            "--baseline-cwd", str(self.target), "--baseline-json", json.dumps(baseline),
            "--candidate-json", json.dumps(candidate), "--baseline-prepare-json", json.dumps(prepare),
            "--blocks", "1", "--seed", "3", "--timeout", "5",
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(baseline_marker.exists())
        self.assertEqual((self.target / "first").read_bytes(), b"dirty-one")
        record = json.loads((output / "block-000001-baseline.json").read_text())
        self.assertEqual(record["result"]["status"], "not_run_preparation_failed")

    def test_paired_preparation_and_guarded_state_probe(self):
        candidate = self.root / "candidate"
        (candidate / "nested").mkdir(parents=True)
        (candidate / "first").write_bytes(b"other")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1, "files": [self.files[0]]}))
        state = HARNESS / "state_probe.py"
        probe = [sys.executable, str(state), "--root", ".", "--file", "first"]
        seed_probe = [sys.executable, str(state), "--root", str(self.seed), "--file", "first"]
        observed = subprocess.run(seed_probe, capture_output=True, timeout=15, check=True).stdout
        expectation = {"expected_exit_code": 0, "expected_stdout_bytes": len(observed),
                       "expected_stdout_sha256": hashlib.sha256(observed).hexdigest()}
        prepare = [sys.executable, str(RESET), "--manifest", str(manifest), "--seed-root", str(self.seed),
                   "--target-root", ".", "--apply"]
        command = [sys.executable, "-c", "from pathlib import Path; assert Path('first').read_bytes() == b'fresh-one'"]
        output = self.root / "run"
        result = subprocess.run([
            sys.executable, str(HARNESS / "paired.py"), "--output", str(output), "--cwd", str(self.root),
            "--baseline-cwd", str(self.target), "--candidate-cwd", str(candidate),
            "--baseline-json", json.dumps(command), "--candidate-json", json.dumps(command),
            "--baseline-prepare-json", json.dumps(prepare), "--candidate-prepare-json", json.dumps(prepare),
            "--baseline-probe-json", json.dumps(probe), "--candidate-probe-json", json.dumps(probe),
            "--baseline-probe-guard-json", json.dumps(expectation),
            "--candidate-probe-guard-json", json.dumps(expectation),
            "--blocks", "1", "--seed", "3", "--timeout", "5",
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for arm in ("baseline", "candidate"):
            record = json.loads((output / f"block-000001-{arm}.json").read_text())
            self.assertEqual(record["result"]["returncode"], 0)
            self.assertEqual(record["mode"], "exploratory")
            self.assertEqual(record["schema_version"], 2)
            receipt = json.loads((output / f"receipt-block-000001-{arm}.json").read_text())
            self.assertEqual(receipt["mode"], "exploratory_unqualified")
            self.assertFalse(receipt["confirmatory_eligible"])
        inspection = subprocess.run([sys.executable, str(HARNESS / "inspect_run.py"), str(output)],
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(inspection.returncode, 0, inspection.stderr)
        self.assertFalse(json.loads(inspection.stdout)["confirmatory_eligible"])


if __name__ == "__main__":
    unittest.main()
