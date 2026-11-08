import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PAIRED = Path(__file__).resolve().parents[1] / "paired.py"


class ExploratoryPairsTests(unittest.TestCase):
    def invoke(self, output, baseline, candidate, blocks=2, timeout=2,
               baseline_prepare=None, candidate_prepare=None,
               baseline_probe=None, candidate_probe=None, capture_raw=False, raw_limit=100):
        args = [
            sys.executable, str(PAIRED), "--output", str(output), "--cwd", str(output.parent),
            "--baseline-json", json.dumps(baseline), "--candidate-json", json.dumps(candidate),
            "--blocks", str(blocks), "--seed", "3", "--timeout", str(timeout),
        ]
        if baseline_prepare is not None:
            args += ["--baseline-prepare-json", json.dumps(baseline_prepare)]
        if candidate_prepare is not None:
            args += ["--candidate-prepare-json", json.dumps(candidate_prepare)]
        if baseline_probe is not None:
            args += ["--baseline-probe-json", json.dumps(baseline_probe)]
        if candidate_probe is not None:
            args += ["--candidate-probe-json", json.dumps(candidate_probe)]
        if capture_raw:
            args += ["--capture-raw", "--raw-limit-bytes", str(raw_limit)]
        return subprocess.run(args, capture_output=True, text=True, timeout=15)

    def test_schedule_and_all_arm_records_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [sys.executable, "-c", "print('base')"],
                                 [sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            schedule = json.loads((output / "schedule.json").read_text())
            self.assertEqual(schedule["mode"], "exploratory_unqualified")
            self.assertEqual(schedule["host_metadata"]["status"], "incomplete_unqualified")
            self.assertEqual(len(schedule["schedule"]), 2)
            samples = [json.loads(path.read_text()) for path in output.glob("block-*.json")]
            self.assertEqual(len(samples), 4)
            for sample in samples:
                self.assertEqual(sample["mode"], "exploratory_unqualified")
                self.assertEqual(sample["result"]["status"], "exited_unqualified")
                self.assertEqual(sample["result"]["returncode"],
                                 0 if sample["arm"] == "baseline" else 7)
                expected_order = schedule["schedule"][sample["block"] - 1]["order"]
                self.assertEqual(sample["arm"], expected_order[sample["position"] - 1])
            again = self.invoke(output, ["nonexistent"], ["nonexistent"])
            self.assertEqual(again.returncode, 2)
            self.assertEqual(len(list(output.glob("block-*.json"))), 4)

    def test_launch_error_does_not_discard_other_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, ["/nonexistent/pt-bench-command"],
                                 [sys.executable, "-c", "pass"], blocks=1)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            candidate = json.loads((output / "block-000001-candidate.json").read_text())
            self.assertEqual(baseline["result"]["status"], "launch_error")
            self.assertEqual(candidate["result"]["status"], "exited_unqualified")

    def test_invalid_input_does_not_create_run(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [], [sys.executable, "-c", "pass"])
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_timeout_remains_visible_and_other_arm_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [sys.executable, "-c", "import time; time.sleep(5)"],
                                 [sys.executable, "-c", "pass"], blocks=1, timeout=0.1)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            candidate = json.loads((output / "block-000001-candidate.json").read_text())
            self.assertEqual(baseline["result"]["status"], "timeout")
            self.assertEqual(candidate["result"]["status"], "exited_unqualified")

    def test_preparation_runs_before_its_arm_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            prepare = [sys.executable, "-c", "from pathlib import Path; Path('state').write_text('ready')"]
            command = [sys.executable, "-c", "from pathlib import Path; assert Path('state').read_text() == 'ready'; Path('state').unlink()"]
            result = self.invoke(output, command, command, baseline_prepare=prepare,
                                 candidate_prepare=prepare)
            self.assertEqual(result.returncode, 0, result.stderr)
            for arm in ("baseline", "candidate"):
                for block in (1, 2):
                    prep = json.loads((output / f"preparation-{block:06d}-{arm}.json").read_text())
                    sample = json.loads((output / f"block-{block:06d}-{arm}.json").read_text())
                    self.assertEqual(prep["result"]["returncode"], 0)
                    self.assertEqual(sample["result"]["returncode"], 0)
                    self.assertEqual(sample["preparation"], "recorded")

    def test_failed_preparation_prevents_only_that_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            marker = Path(directory) / "must-not-exist"
            command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
            result = self.invoke(output, command, [sys.executable, "-c", "pass"], blocks=1,
                                 baseline_prepare=[sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            prep = json.loads((output / "preparation-000001-baseline.json").read_text())
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            candidate = json.loads((output / "block-000001-candidate.json").read_text())
            self.assertEqual(prep["result"]["returncode"], 3)
            self.assertEqual(baseline["result"]["status"], "not_run_preparation_failed")
            self.assertEqual(candidate["result"]["status"], "exited_unqualified")

    def test_preparation_timeout_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = self.invoke(output, [sys.executable, "-c", "pass"],
                                 [sys.executable, "-c", "pass"], blocks=1, timeout=0.1,
                                 baseline_prepare=[sys.executable, "-c", "import time; time.sleep(5)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            prep = json.loads((output / "preparation-000001-baseline.json").read_text())
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            self.assertEqual(prep["result"]["status"], "timeout")
            self.assertEqual(baseline["result"]["status"], "not_run_preparation_failed")

    def test_state_probe_follows_preparation_and_failure_blocks_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            marker = Path(directory) / "baseline-ran"
            prepare = [sys.executable, "-c", "from pathlib import Path; Path('state').write_text('ready')"]
            probe = [sys.executable, "-c", "from pathlib import Path; assert Path('state').read_text() == 'ready'; raise SystemExit(5)"]
            baseline = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
            result = self.invoke(output, baseline, [sys.executable, "-c", "pass"], blocks=1,
                                 baseline_prepare=prepare, baseline_probe=probe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            probe_record = json.loads((output / "probe-000001-baseline.json").read_text())
            baseline_record = json.loads((output / "block-000001-baseline.json").read_text())
            self.assertEqual(probe_record["result"]["returncode"], 5)
            self.assertEqual(baseline_record["state_probe"], "recorded")
            self.assertEqual(baseline_record["result"]["status"], "not_run_probe_failed")
            inspection = subprocess.run([sys.executable, str(PAIRED.parent / "inspect_run.py"),
                                         str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 0, inspection.stderr)
            self.assertFalse(json.loads(inspection.stdout)["confirmatory_eligible"])
            probe_path = output / "probe-000001-baseline.json"
            probe_record["result"]["returncode"] = 0
            probe_path.write_text(json.dumps(probe_record))
            inspection = subprocess.run([sys.executable, str(PAIRED.parent / "inspect_run.py"),
                                         str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 2)
            probe_path.unlink()
            inspection = subprocess.run([sys.executable, str(PAIRED.parent / "inspect_run.py"),
                                         str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 2)

    def test_successful_state_probe_allows_work_but_is_unqualified(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            command = [sys.executable, "-c", "pass"]
            result = self.invoke(output, command, command, blocks=1, baseline_probe=command)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            self.assertEqual(baseline["state_probe"], "recorded")
            self.assertEqual(baseline["result"]["returncode"], 0)
            self.assertEqual(baseline["mode"], "exploratory_unqualified")

    def test_failed_preparation_skips_configured_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            command = [sys.executable, "-c", "pass"]
            result = self.invoke(output, command, command, blocks=1, baseline_probe=command,
                                 baseline_prepare=[sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline = json.loads((output / "block-000001-baseline.json").read_text())
            self.assertEqual(baseline["state_probe"], "skipped_preparation_failed")
            self.assertFalse((output / "probe-000001-baseline.json").exists())
            inspection = subprocess.run([sys.executable, str(PAIRED.parent / "inspect_run.py"),
                                         str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 0, inspection.stderr)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX raw capture")
    def test_raw_capture_covers_all_stages_and_inspection_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            prepare = [sys.executable, "-c", "print('prep')"]
            probe = [sys.executable, "-c", "print('probe')"]
            baseline = [sys.executable, "-c", "print('abcdefgh')"]
            candidate = [sys.executable, "-c", "print('ok')"]
            result = self.invoke(output, baseline, candidate, blocks=1, baseline_prepare=prepare,
                                 baseline_probe=probe, capture_raw=True, raw_limit=4)
            self.assertEqual(result.returncode, 0, result.stderr)
            baseline_record = json.loads((output / "block-000001-baseline.json").read_text())
            stdout = baseline_record["result"]["raw_capture"]["stdout"]
            self.assertTrue(stdout["truncated"])
            self.assertEqual((output / "blobs" / stdout["sha256"]).read_bytes(), b"abcd")
            for prefix in ("preparation", "probe"):
                stage = json.loads((output / f"{prefix}-000001-baseline.json").read_text())
                self.assertIn("raw_capture", stage["result"])
            inspect_command = [sys.executable, str(PAIRED.parent / "inspect_run.py"), str(output)]
            inspection = subprocess.run(inspect_command, capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 0, inspection.stderr)
            self.assertFalse(json.loads(inspection.stdout)["confirmatory_eligible"])
            (output / "blobs" / stdout["sha256"]).write_bytes(b"evil")
            inspection = subprocess.run(inspect_command, capture_output=True, text=True, timeout=15)
            self.assertEqual(inspection.returncode, 2)
            self.assertIn("raw blob", inspection.stderr)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX raw capture")
    def test_negative_raw_limit_does_not_create_run(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            command = [sys.executable, "-c", "pass"]
            result = self.invoke(output, command, command, blocks=1, capture_raw=True, raw_limit=-1)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX raw capture")
    def test_raw_inspection_rejects_truncation_lies_missing_symlinks_and_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "run"
            result = self.invoke(output, [sys.executable, "-c", "print('abcdef')"],
                                 [sys.executable, "-c", "pass"], blocks=1,
                                 capture_raw=True, raw_limit=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            record_path = output / "block-000001-baseline.json"
            original = json.loads(record_path.read_text())
            blob = output / "blobs" / original["result"]["raw_capture"]["stdout"]["sha256"]
            payload = blob.read_bytes()
            inspect_command = [sys.executable, str(PAIRED.parent / "inspect_run.py"), str(output)]

            lie = json.loads(json.dumps(original))
            lie["result"]["raw_capture"]["stdout"]["truncated"] = False
            record_path.write_text(json.dumps(lie))
            self.assertEqual(subprocess.run(inspect_command, capture_output=True, timeout=15).returncode, 2)
            record_path.write_text(json.dumps(original))

            blob.unlink()
            self.assertEqual(subprocess.run(inspect_command, capture_output=True, timeout=15).returncode, 2)
            outside = root / "outside"
            outside.write_bytes(payload)
            blob.symlink_to(outside)
            self.assertEqual(subprocess.run(inspect_command, capture_output=True, timeout=15).returncode, 2)
            blob.unlink()
            blob.write_bytes(payload)
            (output / "blobs" / "unexpected").write_bytes(b"extra")
            self.assertEqual(subprocess.run(inspect_command, capture_output=True, timeout=15).returncode, 2)

    @unittest.skipUnless(os.name == "posix", "POSIX detached descendant behavior")
    def test_uncertain_cleanup_aborts_before_later_arm(self):
        detached = [sys.executable, "-c", (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2.5)'], "
            "start_new_session=True)"
        )]
        for phase in ("preparation", "measurement"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                marker = Path(directory) / "candidate-ran"
                candidate = [sys.executable, "-c",
                             f"from pathlib import Path; Path({str(marker)!r}).touch()"]
                baseline = detached if phase == "measurement" else [sys.executable, "-c", "pass"]
                prepare = detached if phase == "preparation" else None
                # seed=3 schedules baseline first for one block.
                result = self.invoke(output, baseline, candidate, blocks=1, timeout=0.2,
                                     baseline_prepare=prepare)
                self.assertEqual(result.returncode, 2)
                self.assertIn("cleanup uncertain", result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse((output / "block-000001-candidate.json").exists())
                inspection = subprocess.run([sys.executable, str(PAIRED.parent / "inspect_run.py"),
                                             str(output)], capture_output=True, text=True, timeout=15)
                self.assertEqual(inspection.returncode, 2)
                baseline_record = json.loads((output / "block-000001-baseline.json").read_text())
                if phase == "preparation":
                    prep = json.loads((output / "preparation-000001-baseline.json").read_text())
                    self.assertFalse(prep["result"]["output_complete"])
                    self.assertEqual(baseline_record["result"]["status"], "not_run_preparation_failed")
                else:
                    self.assertEqual(baseline_record["result"]["status"], "timeout")
                    self.assertFalse(baseline_record["result"]["output_complete"])


if __name__ == "__main__":
    unittest.main()
