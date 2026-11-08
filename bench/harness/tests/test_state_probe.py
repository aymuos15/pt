import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "state_probe", Path(__file__).resolve().parents[1] / "state_probe.py"
)
state_probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state_probe)


@unittest.skipUnless(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                     and os.open in os.supports_dir_fd, "requires safe POSIX relative lookup")
class StateProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.left, self.right = self.root / "left", self.root / "right"
        for directory in (self.left, self.right):
            (directory / "nested").mkdir(parents=True)
            (directory / "nested" / "data.txt").write_bytes(b"old!")
            (directory / "unicode-λ.txt").write_bytes(b"second")

    def test_same_content_different_roots_and_order_match(self):
        first = state_probe.probe(self.left, ["nested/data.txt", "unicode-λ.txt"], max_file_bytes=100)
        second = state_probe.probe(self.right, ["unicode-λ.txt", "nested/data.txt"], max_file_bytes=100)
        self.assertEqual(first, second)
        self.assertFalse(first["atomic_snapshot"])
        self.assertFalse(first["confirmatory_eligible"])

    def test_same_size_same_mtime_edit_changes_digest(self):
        path = self.left / "nested" / "data.txt"
        before = state_probe.probe(self.left, ["nested/data.txt"], max_file_bytes=100)
        old_stat = path.stat()
        path.write_bytes(b"new!")
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size, old_stat.st_size)
        self.assertEqual(path.stat().st_mtime_ns, old_stat.st_mtime_ns)
        after = state_probe.probe(self.left, ["nested/data.txt"], max_file_bytes=100)
        self.assertNotEqual(before["state_sha256"], after["state_sha256"])

    def test_unsafe_paths_duplicates_and_limits_fail_closed(self):
        for files, limit in [([], 100), (["../escape"], 100), (["/absolute"], 100),
                             (["nested/./data.txt"], 100), (["nested/data.txt"] * 2, 100),
                             (["nested/data.txt"], 3), (["missing"], 100),
                             (["nested/data.txt"], True)]:
            with self.subTest(files=files, limit=limit), self.assertRaises(state_probe.StateProbeError):
                state_probe.probe(self.left, files, max_file_bytes=limit)

    def test_symlinks_and_nonregular_files_are_rejected(self):
        (self.left / "file-link").symlink_to(self.right / "nested" / "data.txt")
        (self.left / "dir-link").symlink_to(self.right / "nested", target_is_directory=True)
        os.mkfifo(self.left / "fifo")
        for path in ("file-link", "dir-link/data.txt", "fifo", "nested"):
            with self.subTest(path=path), self.assertRaises(state_probe.StateProbeError):
                state_probe.probe(self.left, [path], max_file_bytes=100)

    def test_file_changed_during_read_is_rejected(self):
        path = self.left / "nested" / "data.txt"
        original_read = os.read
        changed = False

        def change_during_read(fd, size):
            nonlocal changed
            chunk = original_read(fd, size)
            if chunk and not changed:
                changed = True
                path.write_bytes(b"different-size")
            return chunk

        with mock.patch.object(state_probe.os, "read", side_effect=change_during_read):
            with self.assertRaisesRegex(state_probe.StateProbeError, "changed during read"):
                state_probe.probe(self.left, ["nested/data.txt"], max_file_bytes=100)

    def test_guarded_paired_probe_blocks_same_stat_content_change(self):
        script = Path(__file__).resolve().parents[1] / "state_probe.py"
        paired = script.parent / "paired.py"
        inspect = script.parent / "inspect_run.py"
        probe_argv = [sys.executable, str(script), "--root", ".", "--file", "nested/data.txt"]
        reference = subprocess.run(probe_argv, cwd=self.left, capture_output=True, timeout=15, check=True)
        guard = {"expected_exit_code": 0, "expected_stdout_bytes": len(reference.stdout),
                 "expected_stdout_sha256": hashlib.sha256(reference.stdout).hexdigest()}
        changed = self.right / "nested" / "data.txt"
        old_stat = changed.stat()
        changed.write_bytes(b"new!")
        os.utime(changed, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self.assertEqual((changed.stat().st_size, changed.stat().st_mtime_ns),
                         (old_stat.st_size, old_stat.st_mtime_ns))
        marker = "from pathlib import Path; Path('work-ran').touch()"
        command = [sys.executable, "-c", marker]
        output = self.root / "paired-run"
        result = subprocess.run([
            sys.executable, str(paired), "--output", str(output), "--cwd", str(self.root),
            "--baseline-cwd", str(self.left), "--candidate-cwd", str(self.right),
            "--baseline-json", json.dumps(command), "--candidate-json", json.dumps(command),
            "--baseline-probe-json", json.dumps(probe_argv), "--candidate-probe-json", json.dumps(probe_argv),
            "--baseline-probe-guard-json", json.dumps(guard), "--candidate-probe-guard-json", json.dumps(guard),
            "--blocks", "1", "--seed", "3", "--timeout", "5",
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.left / "work-ran").exists())
        self.assertFalse((self.right / "work-ran").exists())
        candidate = json.loads((output / "block-000001-candidate.json").read_text())
        self.assertEqual(candidate["result"]["status"], "not_run_probe_failed")
        probe = json.loads((output / "probe-000001-candidate.json").read_text())
        self.assertIn("stdout_digest", probe["observation_guard"]["mismatches"])
        inspection = subprocess.run([sys.executable, str(inspect), str(output)], capture_output=True,
                                    text=True, timeout=15)
        self.assertEqual(inspection.returncode, 0, inspection.stderr)
        self.assertFalse(json.loads(inspection.stdout)["confirmatory_eligible"])


if __name__ == "__main__":
    unittest.main()
