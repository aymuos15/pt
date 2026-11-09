import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from test_timing_boundaries import ObservedBoundaryTests


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import analysis
    import blob_store
    import finalization
    import paired
    import paired_lifecycle as driver
    import pt_bench as timer
    import raw_capture
    from inspect_run import inspect_run
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux paired lifecycle/blob target")
class PairedLifecycleTests(ObservedBoundaryTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "run"
        self.cwds = {arm: self.root / arm for arm in driver.ARMS}
        for path in self.cwds.values():
            path.mkdir()
        self.payload = b"done\n"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.contract = {"expected_exit_code": 0, "artifacts": [
            {"path": "report", "bytes": len(self.payload), "sha256": self.digest}], "absent": ["lease"]}
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": len(self.payload),
                      "expected_stdout_sha256": self.digest}
        self.command = [sys.executable, "-c", (
            "from pathlib import Path; "
            "f=Path('calls').open('a'); f.write('call\\n'); f.close(); "
            "Path('lease').touch(); Path('report').write_bytes(b'done\\n'); Path('lease').unlink(); print('done')"
        )]
        self.entered, self.release = threading.Event(), threading.Event()

    def run_pairs(self, *, blocks=2, **changes):
        options = {f"{arm}_{key}": value for arm in driver.ARMS for key, value in
                   (("cwd", self.cwds[arm]), ("guard", self.guard), ("finalization", self.contract))}
        options.update(changes)
        # A one-block choice and a two-block shuffle consume the seed
        # differently. These fixtures intentionally fail the first baseline.
        seed = 3 if blocks == 1 else 0
        return paired.run_pairs(self.output, self.root, self.command, self.command, blocks, seed, 5, **options)

    def all_stages(self):
        return {f"baseline_{key}": value for key, value in
                (("prepare", self.command), ("probe", self.command), ("probe_guard", self.guard),
                 ("prepare_finalization", self.contract), ("probe_finalization", self.contract))}

    def read(self, name):
        return json.loads((self.output / name).read_text())

    def pause(self):
        self.entered.set()
        if not self.release.wait(timeout=15):
            raise RuntimeError("parent did not release paired stage")

    def assert_blocked(self, *, blocks=2):
        inspection = inspect_run(self.output)
        self.assertEqual(inspection["record_consistency"], "aborted")
        self.assertEqual(inspection["planned_arm_count"], blocks * 2)
        self.assertEqual(sum(inspection["arm_status_counts"].values()), blocks * 2)
        summary = summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=7) if blocks > 1 else summarize_run(self.output)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["planned_arm_count"], blocks * 2)
        self.assertIsNone(summary["ratio"])
        self.assertIsNone(summary["absolute_latency_ns"])
        self.assertIsNone(summary["bootstrap"])
        self.assertFalse(summary["confirmatory_eligible"])
        self.assertFalse((self.cwds["candidate"] / "calls").exists())
        return inspection, summary

    def test_default_cli_produces_v2_samples_receipts_and_lifecycle_summary(self):
        args = [sys.executable, str(HARNESS / "paired.py"), "--output", str(self.output), "--cwd", str(self.root),
                "--baseline-json", json.dumps(self.command), "--candidate-json", json.dumps(self.command),
                "--blocks", "2", "--seed", "3", "--timeout", "5"]
        for arm in driver.ARMS:
            args += [f"--{arm}-cwd", str(self.cwds[arm]), f"--{arm}-guard-json", json.dumps(self.guard),
                     f"--{arm}-finalization-json", json.dumps(self.contract)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("schedule.json")["schema_version"], 2)
        inspection = inspect_run(self.output)
        self.assertEqual(inspection["timing_endpoint"], timer.LIFECYCLE_ENDPOINT)
        self.assertEqual(inspection["observed_arm_count"], 4)
        self.assertEqual(inspection["stage_lifecycle_status_counts"], {"finalized_unqualified": 4})
        summary = summarize_run(self.output, bootstrap_resamples=50, bootstrap_seed=7)
        repeated = summarize_run(self.output, bootstrap_resamples=50, bootstrap_seed=7)
        self.assertEqual(summary["bootstrap"], repeated["bootstrap"])
        self.assertEqual(summary["bootstrap"]["timing_endpoint"], timer.LIFECYCLE_ENDPOINT)
        for arm in driver.ARMS:
            receipts = [self.read(f"receipt-block-{number:06d}-{arm}.json") for number in (1, 2)]
            self.assertEqual(summary["absolute_latency_ns"][f"{arm}_mean"],
                             sum(receipt["lifecycle"]["elapsed_ns"] for receipt in receipts) / 2)
            self.assertGreater(summary["absolute_latency_ns"][f"{arm}_mean"],
                               sum(receipt["result"]["elapsed_ns"] for receipt in receipts) / 2)

    def test_historical_artifacts_survive_repeated_stages_and_later_worktree_changes(self):
        self.run_pairs(capture_raw=True, **self.all_stages())
        receipt = self.read("receipt-block-000001-baseline.json")
        self.assertEqual((self.output / "blobs" / self.digest).read_bytes(), self.payload)
        for root in self.cwds.values():
            (root / "report").unlink()
            (root / "lease").touch()
        # The old receipt cannot certify live state, and the new paired
        # inspector deliberately certifies only retained historical evidence.
        with self.assertRaises(ValueError):
            timer.inspect_lifecycle(self.output / "block-000001-baseline.json", receipt)
        report = summarize_run(self.output)
        self.assertEqual(report["status"], "exploratory_point_estimate")
        self.assertFalse(report["confirmatory_eligible"])
        inspection = inspect_run(self.output)
        self.assertEqual(inspection["stage_lifecycle_status_counts"], {"finalized_unqualified": 8})
        self.assertIn("no work, generation, reset, current-state or resource qualification", inspection["limitations"])

    def test_sample_publication_delay_in_every_stage_is_counted_by_analysis(self):
        original = timer.write_record
        for stage in driver.STAGES:
            with self.subTest(stage=stage):
                self.output = self.root / f"run-{stage}"
                self.entered.clear()
                self.release.clear()
                filename = driver._filename(stage, 1, "baseline")

                def delayed(path, record):
                    if Path(path).name == filename:
                        self.pause()
                    return original(path, record)

                with mock.patch.object(timer, "write_record", delayed):
                    _, window = self.observe(lambda: self.run_pairs(blocks=1, **self.all_stages()),
                                              self.entered.is_set, self.release.set)
                receipt = self.read(f"receipt-{filename}")
                self.assert_covers_stage(receipt["lifecycle"], window)
                self.assertLess(receipt["result"]["monotonic_end_ns"], window[0])
                with self.assertRaisesRegex(AssertionError, "timer ended before release"):
                    self.assert_covers_stage(receipt["result"], window)
                report = summarize_run(self.output)
                measured = self.read("receipt-block-000001-baseline.json")
                self.assertEqual(report["absolute_latency_ns"]["baseline_mean"], measured["lifecycle"]["elapsed_ns"])

    def test_archival_delay_is_inside_the_measured_arm_interval(self):
        original = finalization.archive

        def delayed(*args, **kwargs):
            if Path(args[0]) == self.cwds["baseline"]:
                self.pause()
            return original(*args, **kwargs)

        with mock.patch.object(finalization, "archive", delayed):
            _, window = self.observe(lambda: self.run_pairs(blocks=1), self.entered.is_set, self.release.set)
        receipt = self.read("receipt-block-000001-baseline.json")
        self.assert_covers_stage(receipt["lifecycle"], window)
        self.assertEqual(summarize_run(self.output)["absolute_latency_ns"]["baseline_mean"], receipt["lifecycle"]["elapsed_ns"])

    def test_receipt_persistence_is_excluded_but_blocks_the_next_stage(self):
        original = driver.write_record

        def delayed(path, value):
            if Path(path).name == "receipt-preparation-000001-baseline.json":
                self.pause()
            return original(path, value)

        def before_release():
            self.assertEqual((self.cwds["baseline"] / "calls").read_text().splitlines(), ["call"])
            self.assertFalse((self.cwds["candidate"] / "calls").exists())

        with mock.patch.object(driver, "write_record", delayed):
            _, window = self.observe(lambda: self.run_pairs(blocks=1, **self.all_stages()),
                                      self.entered.is_set, self.release.set, before_release)
        prep = self.read("receipt-preparation-000001-baseline.json")
        probe = self.read("receipt-probe-000001-baseline.json")
        self.assertLess(prep["lifecycle"]["monotonic_end_ns"], window[0])
        self.assertGreaterEqual(probe["lifecycle"]["monotonic_start_ns"], window[1])

    def test_failed_sample_publication_at_each_stage_aborts_without_replay_or_dropped_pairs(self):
        original = timer.write_record
        for index, stage in enumerate(driver.STAGES):
            with self.subTest(stage=stage):
                self.output = self.root / f"failed-{stage}"
                (self.cwds["baseline"] / "calls").unlink(missing_ok=True)
                filename = driver._filename(stage, 1, "baseline")

                def fail(path, value):
                    if Path(path).name == filename:
                        raise OSError("injected subject publication failure")
                    return original(path, value)

                with mock.patch.object(timer, "write_record", fail):
                    with self.assertRaises(paired.RunAbortedError):
                        self.run_pairs(**self.all_stages())
                self.assertEqual(len((self.cwds["baseline"] / "calls").read_text().splitlines()), index + 1)
                receipt = self.read(f"receipt-{filename}")
                self.assertEqual(receipt["result"]["returncode"], 0)
                self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
                self.assertIsNone(receipt["sample"])
                self.assertEqual(receipt["errors"][0]["stage"], "sample_publication")
                inspection, _ = self.assert_blocked()
                self.assertEqual(inspection["arm_status_counts"]["not_run_run_aborted"], 3)

    def test_failed_omitted_or_wrong_receipt_publication_preserves_abort_evidence(self):
        original = driver.write_record
        for mode in ("error", "omit", "wrong"):
            with self.subTest(mode=mode):
                self.output = self.root / f"receipt-{mode}"
                (self.cwds["baseline"] / "calls").unlink(missing_ok=True)

                def fail(path, value):
                    if Path(path).name == "receipt-block-000001-baseline.json":
                        if mode == "error":
                            raise OSError("injected receipt failure")
                        if mode == "wrong":
                            Path(path).write_text("{}")
                        return
                    return original(path, value)

                with mock.patch.object(driver, "write_record", fail):
                    with self.assertRaises(paired.RunAbortedError):
                        self.run_pairs()
                abort = self.read("abort.json")
                self.assertEqual(abort["reason"], "receipt_publication_failed")
                self.assertEqual((self.cwds["baseline"] / "calls").read_text().splitlines(), ["call"])
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        summarize_run(self.output)
                else:
                    _, summary = self.assert_blocked()
                    self.assertIn("receipt_publication_failed", summary["blockers"][1]["reasons"])

    def test_archive_failure_never_becomes_a_faster_sample(self):
        with mock.patch.object(blob_store, "publish", side_effect=OSError("injected archive failure")):
            with self.assertRaises(paired.RunAbortedError):
                self.run_pairs()
        receipt = self.read("receipt-block-000001-baseline.json")
        self.assertIsNotNone(receipt["sample"])
        self.assertEqual(receipt["errors"][0]["stage"], "artifact_archive")
        self.assert_blocked()
        forged = copy.deepcopy(receipt)
        forged["errors"] = []
        forged["lifecycle"]["status"] = "finalized_unqualified"
        with self.assertRaises(ValueError):
            timer.inspect_lifecycle(self.output / "block-000001-baseline.json", forged,
                                    archived_bundle=self.output / "blobs")

    def test_matching_guard_does_not_hide_failed_cleanup_or_report_and_retains_wrong_bytes(self):
        original_command = self.command
        for mode in ("lease", "report"):
            with self.subTest(mode=mode):
                self.output = self.root / f"bad-{mode}"
                program = "from pathlib import Path; Path('report').write_bytes(b'done\\n'); print('done')"
                if mode == "lease":
                    program += "; Path('lease').touch()"
                else:
                    (self.cwds["baseline"] / "lease").unlink(missing_ok=True)
                    program += "; Path('report').write_bytes(b'bad\\n')"
                self.command = [sys.executable, "-c", program]
                with self.assertRaises(paired.RunAbortedError):
                    self.run_pairs()
                receipt = self.read("receipt-block-000001-baseline.json")
                self.assertTrue(receipt["observation_guard"]["matched_expected_observations"])
                self.assertEqual(receipt["result"]["returncode"], 0)
                if mode == "report":
                    refs = receipt["artifact_archive"]["artifacts"]
                    self.assertEqual((self.output / "blobs" / refs[0]["sha256"]).read_bytes(), b"bad\n")
                self.assert_blocked()
        self.command = original_command

    def test_failed_preparation_skips_only_its_arm_but_keeps_the_denominator(self):
        failed = [sys.executable, "-c", "raise SystemExit(7)"]
        self.run_pairs(baseline_prepare=failed)
        inspection = inspect_run(self.output)
        self.assertEqual(inspection["arm_status_counts"], {"exited_unqualified": 2, "not_run_preparation_failed": 2})
        summary = summarize_run(self.output)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertIsNone(summary["ratio"])

    def test_missing_receipts_samples_and_blobs_or_relabelled_endpoints_are_rejected(self):
        self.run_pairs()
        for filename in ("receipt-block-000001-baseline.json", "block-000001-baseline.json", f"blobs/{self.digest}"):
            path = self.output / filename
            data = path.read_bytes()
            path.unlink()
            with self.subTest(missing=filename), self.assertRaises((ValueError, OSError)):
                summarize_run(self.output)
            path.write_bytes(data)
        plan = self.read("schedule.json")
        plan["timing_endpoint"] = timer.COMMAND_ENDPOINT
        (self.output / "schedule.json").write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            summarize_run(self.output)

    def test_overlapping_lifecycle_intervals_and_changed_contracts_are_rejected(self):
        self.run_pairs()
        plan = self.read("schedule.json")
        first, second = plan["schedule"][0]["order"]
        first_receipt = self.read(f"receipt-block-000001-{first}.json")
        path = self.output / f"receipt-block-000001-{second}.json"
        original = self.read(path.name)
        changed = copy.deepcopy(original)
        timing = changed["lifecycle"]
        timing["monotonic_start_ns"] = first_receipt["lifecycle"]["monotonic_end_ns"] - 1
        timing["elapsed_ns"] = timing["monotonic_end_ns"] - timing["monotonic_start_ns"]
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "overlap"):
            inspect_run(self.output)
        path.write_text(json.dumps(original))
        plan["finalization"]["baseline"]["measurement"]["absent"] = []
        (self.output / "schedule.json").write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, "stage plan"):
            inspect_run(self.output)

    def test_legacy_command_mode_cannot_request_unmeasured_finalization(self):
        with self.assertRaisesRegex(ValueError, "publication-inclusive"):
            self.run_pairs(timing_endpoint=timer.COMMAND_ENDPOINT)
        self.assertFalse(self.output.exists())

    def test_analysis_rejects_mixed_or_partly_unlabelled_endpoints(self):
        samples = [{"block": "1", "arm": arm, "status": "guard_matched_unqualified", "elapsed_ns": 10,
                    "timing_endpoint": timer.LIFECYCLE_ENDPOINT} for arm in driver.ARMS]
        samples[1]["timing_endpoint"] = timer.COMMAND_ENDPOINT
        with self.assertRaisesRegex(ValueError, "mixed"):
            analysis.guarded_exploratory_ratio(samples)
        del samples[1]["timing_endpoint"]
        with self.assertRaisesRegex(ValueError, "mixed"):
            analysis.guarded_exploratory_ratio(samples)

    def test_schedule_publication_failure_stops_before_any_command(self):
        original = driver.write_record
        for mode in ("error", "omit", "wrong"):
            with self.subTest(mode=mode):
                self.output = self.root / f"schedule-{mode}"

                def fail(path, value):
                    if Path(path).name == "schedule.json":
                        if mode == "error":
                            raise OSError("injected schedule publication failure")
                        if mode == "wrong":
                            Path(path).write_text("{}")
                        return
                    return original(path, value)

                with mock.patch.object(driver, "write_record", fail):
                    with self.assertRaises((OSError, ValueError)):
                        self.run_pairs()
                self.assertFalse(any((root / "calls").exists() for root in self.cwds.values()))
                with self.assertRaises((OSError, ValueError)):
                    summarize_run(self.output)

    def test_unexpected_exits_block_all_pairs_and_expected_nonzero_is_explicit(self):
        self.command = self.command[:-1] + [self.command[-1] + "; raise SystemExit(7)"]
        self.run_pairs()
        inspection = inspect_run(self.output)
        self.assertEqual(inspection["record_consistency"], "complete")
        self.assertEqual(inspection["observed_arm_count"], 4)
        self.assertEqual(inspection["stage_lifecycle_status_counts"], {"finalization_failed": 4})
        summary = summarize_run(self.output)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(len(summary["blockers"]), 4)
        self.assertIsNone(summary["ratio"])
        self.output = self.root / "expected-nonzero"
        self.guard["expected_exit_code"] = 7
        self.contract["expected_exit_code"] = 7
        self.run_pairs()
        summary = summarize_run(self.output)
        self.assertEqual(summary["status"], "exploratory_point_estimate")
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertFalse(summary["confirmatory_eligible"])

    def test_archive_corruption_and_type_ambiguous_receipt_evidence_are_rejected(self):
        self.run_pairs()
        name = "receipt-block-000001-baseline.json"
        receipt = self.read(name)
        oversized = copy.deepcopy(receipt["artifact_archive"])
        oversized["artifacts"][0]["stored_bytes"] = len(self.payload) + 1
        with mock.patch.object(finalization, "inspect_file") as read:
            with self.assertRaisesRegex(ValueError, "byte budget"):
                finalization.archived_check(receipt["result"], self.contract,
                                            receipt["required_finalization"]["before_publication"], oversized,
                                            self.output / "blobs", capture_raw=False)
            read.assert_not_called()
        changed = copy.deepcopy(receipt)
        changed["required_finalization"]["before_publication"]["matched"] = 1
        changed["required_finalization"]["after_publication"]["matched"] = 1
        (self.output / name).write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            summarize_run(self.output)
        (self.output / name).write_text(json.dumps(receipt))
        (self.output / "blobs" / self.digest).write_bytes(b"fake\n")
        with self.assertRaisesRegex(ValueError, "archived artifact bytes"):
            summarize_run(self.output)

    def test_bad_or_conflicting_contracts_never_create_a_run(self):
        invalid = [
            {"unknown_option": True}, {"baseline_finalization": {"claimed_pass": True}},
            {"baseline_prepare_finalization": self.contract},
            {"baseline_finalization": {**self.contract, "expected_exit_code": 7}},
            {"baseline_probe": self.command, "baseline_probe_guard": {**self.guard, "expected_exit_code": 7}},
            {"baseline_finalization": {**self.contract, "absent": ["../lease"]}},
        ]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_pairs(**options)
            self.assertFalse(self.output.exists())
        self.assertFalse(any((root / "calls").exists() for root in self.cwds.values()))
        empty_digest = hashlib.sha256(b"").hexdigest()
        duplicate_guard = ('{"expected_exit_code":0,"expected_exit_code":7,"expected_stdout_bytes":0,'
                           f'"expected_stdout_sha256":"{empty_digest}"}}')
        # Build the duplicate-key input explicitly; JSON object ambiguity must
        # not be normalized silently before freezing a stage contract.
        args = [sys.executable, str(HARNESS / "paired.py"), "--output", str(self.output), "--cwd", str(self.root),
                "--baseline-json", json.dumps(self.command), "--candidate-json", json.dumps(self.command),
                "--blocks", "1", "--seed", "3", "--timeout", "5", "--baseline-guard-json", duplicate_guard]
        rejected = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("duplicate JSON key", rejected.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_abort_does_not_turn_a_partial_run_into_a_complete_estimate(self):
        original = timer.write_record

        def fail(path, value):
            if Path(path).name == "block-000001-baseline.json":
                raise OSError("injected publication failure")
            return original(path, value)

        with mock.patch.object(timer, "write_record", fail):
            with self.assertRaises(paired.RunAbortedError):
                self.run_pairs()
        (self.output / "abort.json").unlink()
        with self.assertRaisesRegex(ValueError, "without required abort"):
            summarize_run(self.output)

    def test_matching_byte_replacement_during_archival_is_a_failure_without_retry(self):
        original = blob_store.publish
        replaced = []

        def replace(source, bundle, **kwargs):
            result = original(source, bundle, **kwargs)
            if not replaced:
                replacement = self.cwds["baseline"] / "replacement"
                replacement.write_bytes(self.payload)
                replacement.replace(self.cwds["baseline"] / "report")
                replaced.append(True)
            return result

        with mock.patch.object(blob_store, "publish", replace):
            with self.assertRaises(paired.RunAbortedError):
                self.run_pairs()
        receipt = self.read("receipt-block-000001-baseline.json")
        self.assertEqual(receipt["lifecycle"]["status"], "finalization_failed")
        self.assertEqual(receipt["errors"][0]["stage"], "artifact_archive")
        self.assertEqual((self.cwds["baseline"] / "calls").read_text().splitlines(), ["call"])
        self.assertEqual((self.output / "blobs" / self.digest).read_bytes(), self.payload)
        # A published but unreferenced blob is retained, not silently deleted
        # to make a failed bundle look complete.
        with self.assertRaisesRegex(ValueError, "unexpected or missing paired artifact blobs"):
            summarize_run(self.output)
