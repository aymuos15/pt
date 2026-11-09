"""Bound paired resource diagnostics; synthetic counters are never native evidence."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_cgroup_accounting import SyntheticGroup, delegated_parent


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import analysis
    import blob_store  # Optional archive import must also work in this isolated test module.
    import paired
    import paired_resources as campaign
    import pt_bench as timer
    import resource_run as resources
    from inspect_run import inspect_run
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


EMPTY = hashlib.sha256(b"").hexdigest()


class PairedResourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "run"
        self.cwds = {arm: self.root / arm for arm in campaign.ARMS}
        for cwd in self.cwds.values():
            cwd.mkdir()
        self.command = [sys.executable, "-c", "pass"]
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": 0, "expected_stdout_sha256": EMPTY}
        self.groups = []

    def produce(self, states=(), *, blocks=2, **changes):
        self.groups = []

        def group(parent):
            index = len(self.groups)
            state = states[index] if index < len(states) else "complete"
            missing = ["memory.peak"] if state == "partial" else ["cpu.stat"] if state == "unsupported" else []
            current = SyntheticGroup(missing=missing, work=state if state not in ("complete", "partial", "unsupported") else "normal")
            current.path = Path(parent) / f"pt-bench-{uuid.uuid4().hex}"
            current.identity = [1, index + 1]
            self.groups.append(current)
            return current

        def measure(*args, **kwargs):
            return self.groups[-1].measure(*args, **kwargs)

        options = {"resource_cgroup_parent": "/synthetic/delegated"}
        options.update({f"{arm}_{key}": value for arm in campaign.ARMS for key, value in
                        (("cwd", self.cwds[arm]), ("guard", self.guard))})
        options.update(changes)
        with (mock.patch.object(resources, "CgroupDirectory", side_effect=group),
              mock.patch.object(timer, "measure", side_effect=measure) as measured):
            self.last_measured = measured
            return paired.run_pairs(self.output, self.root, self.command, self.command, blocks,
                                    3 if blocks == 1 else 0, 5, timing_endpoint=resources.ENDPOINT, **options)

    def read(self, name):
        return json.loads((self.output / name).read_text())

    def assert_denominator(self, summary, planned=4):
        self.assertEqual(summary["planned_arm_count"], planned)
        self.assertEqual(sum(summary["resource_status_counts"].values()), planned)
        self.assertEqual(len(summary["resource_observations"]), planned)
        self.assertEqual(sum(item["planned_units"] for item in summary["per_arm_resources"].values()), planned)
        self.assertFalse(summary["confirmatory_eligible"])
        self.assertIsNone(summary["ratio"])
        self.assertIsNone(summary["absolute_latency_ns"])
        self.assertIsNone(summary["bootstrap"])

    def rewrite_resource(self, name, record):
        raw = (json.dumps(record) + "\n").encode()
        (self.output / f"resource-{name}").write_bytes(raw)
        stage = self.read(name)
        stage["resource"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (self.output / name).write_text(json.dumps(stage))

    def test_complete_synthetic_campaign_has_bound_units_but_no_latency_estimates(self):
        self.produce()
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["status"], "diagnostic_resource_observations")
        self.assertEqual(summary["measurement_layer"], "resource_diagnostic")
        self.assertEqual(summary["observed_arm_count"], 4)
        self.assertEqual(summary["measurement_resource_record_count"], 4)
        self.assertEqual(self.last_measured.call_count, 4)
        for arm in campaign.ARMS:
            values = summary["per_arm_resources"][arm]
            self.assertEqual(values["cpu_usage_usec"], {"observed_units": 2, "unknown_units": 0, "observed_sum": 600000})
            self.assertEqual(values["peak_charged_bytes"]["maximum_observed_per_unit"], 96 * 1024 * 1024)
        stage = self.read("block-000001-baseline.json")
        raw = (self.output / stage["resource"]["name"]).read_bytes()
        self.assertEqual(stage["resource"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_every_unsupported_arm_is_recorded_without_subject_work_or_zero_imputation(self):
        self.produce(["unsupported"] * 4)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["resource_status_counts"], {"unsupported": 4})
        self.assertEqual(summary["measurement_resource_record_count"], 4)
        self.assertEqual(summary["observed_arm_count"], 0)
        self.last_measured.assert_not_called()
        for arm in campaign.ARMS:
            values = summary["per_arm_resources"][arm]
            self.assertEqual(values["cpu_usage_usec"], {"observed_units": 0, "unknown_units": 2, "observed_sum": None})
            self.assertIsNone(values["peak_charged_bytes"]["maximum_observed_per_unit"])
        self.assertTrue(all("cpu_stat" in item["unsupported_capabilities"] for item in summary["resource_observations"]))

    def test_asymmetric_capabilities_keep_unfavorable_arm_and_full_denominator(self):
        self.produce(["unsupported", "complete", "complete", "complete"])
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["observed_arm_count"], 3)
        self.assertEqual(summary["resource_status_counts"], {"observed_unqualified": 3, "unsupported": 1})
        self.assertEqual(summary["per_arm_resources"]["baseline"]["cpu_usage_usec"]["unknown_units"], 1)
        self.assertEqual(summary["per_arm_resources"]["candidate"]["cpu_usage_usec"]["unknown_units"], 0)
        self.assertEqual(summary["status"], "blocked")

    def test_partial_diagnostics_preserve_cpu_but_never_promote_sampled_memory_to_peak(self):
        self.produce(["partial"] * 4, resource_allow_missing_peak=True)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["resource_status_counts"], {"partial_unsupported": 4})
        self.assertEqual(summary["observed_arm_count"], 4)
        self.assertEqual(summary["status"], "blocked")
        for arm in campaign.ARMS:
            values = summary["per_arm_resources"][arm]
            self.assertEqual(values["cpu_usage_usec"]["observed_units"], 2)
            self.assertEqual(values["peak_charged_bytes"], {"observed_units": 0, "unknown_units": 2, "maximum_observed_per_unit": None})
            self.assertEqual(values["sampled_current_max_bytes"]["observed_units"], 2)

    def test_preparation_probe_and_measurement_units_are_not_combined_into_arm_peaks(self):
        self.produce(baseline_prepare=self.command, baseline_probe=self.command, baseline_probe_guard=self.guard)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["planned_stage_count"], 8)
        self.assertEqual(sum(summary["stage_resource_status_counts"].values()), 8)
        self.assertEqual(len(summary["stage_resource_observations"]), 8)
        self.assertEqual(summary["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"], 600000)
        self.assertEqual(self.last_measured.call_count, 8)

    def test_unsupported_preparation_skips_probe_and_measurement_with_explicit_states(self):
        self.produce(["unsupported", "complete"], blocks=1,
                     baseline_prepare=self.command, baseline_probe=self.command, baseline_probe_guard=self.guard)
        summary = summarize_run(self.output)
        self.assert_denominator(summary, 2)
        self.assertEqual(summary["planned_stage_count"], 4)
        self.assertEqual(summary["observed_arm_count"], 1)
        self.assertIn("not_run_preparation_resource_unsupported", summary["resource_status_counts"])
        self.assertEqual(self.last_measured.call_count, 1)
        record = self.read("block-000001-baseline.json")
        self.assertEqual(record["result"]["status"], "not_run_preparation_resource_unsupported")
        self.assertFalse((self.output / "resource-block-000001-baseline.json").exists())

    def test_failed_preparation_or_probe_skips_its_arm_without_dropping_it(self):
        for stage in ("prepare", "probe"):
            self.output = self.root / f"skip-{stage}"
            self.produce(["nonzero", "complete"], blocks=1, **{f"baseline_{stage}": self.command})
            summary = summarize_run(self.output)
            self.assert_denominator(summary, 2)
            self.assertEqual(summary["observed_arm_count"], 1)
            self.assertIn(f"not_run_{'preparation' if stage == 'prepare' else 'probe'}_failed", summary["resource_status_counts"])
            self.assertEqual(summary["record_consistency"], "complete")

    def test_background_timeout_or_measurement_failure_aborts_with_all_later_arms_unknown(self):
        for state in ("background", "timeout", "exception", "exec_error", "interrupt"):
            self.output = self.root / f"failed-{state}"
            with self.subTest(state=state), self.assertRaises(paired.RunAbortedError):
                self.produce([state])
            summary = summarize_run(self.output)
            self.assert_denominator(summary)
            self.assertEqual(summary["record_consistency"], "aborted")
            self.assertEqual(summary["resource_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
            self.assertEqual(summary["observed_arm_count"], 1)
            self.assertEqual(self.last_measured.call_count, 1)
            self.assertEqual(summary["per_arm_resources"]["candidate"]["cpu_usage_usec"]["unknown_units"], 2)

    def test_harness_error_without_a_returned_observation_keeps_invocation_uncertain(self):
        with mock.patch.object(resources, "observe_resources", side_effect=ValueError("injected missing return")):
            with self.assertRaises(paired.RunAbortedError):
                self.produce()
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["unknown_invocation_arm_count"], 1)
        self.assertEqual(summary["observed_arm_count"], 0)
        self.assertIsNone(summary["resource_observations"][0]["run_attempted"])
        self.assertTrue(all(item["run_attempted"] is False for item in summary["resource_observations"][1:]))
        self.assertIsNone(summary["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"])

    def test_preparation_abort_keeps_stage_cost_without_claiming_a_measurement(self):
        with self.assertRaises(paired.RunAbortedError):
            self.produce(["background"], baseline_prepare=self.command, baseline_probe=self.command)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["observed_arm_count"], 0)
        self.assertEqual(summary["planned_stage_count"], 8)
        self.assertEqual(summary["stage_resource_status_counts"]["failed"], 1)
        self.assertIsNotNone(summary["stage_resource_observations"][0]["cpu_delta_usec"])
        self.assertTrue(all(item["cpu_delta_usec"] is None for item in summary["resource_observations"]))

    def test_matching_guard_does_not_hide_failed_declared_report_and_wrong_bytes_are_retained(self):
        payload = b"done\n"
        contract = {"expected_exit_code": 0, "artifacts": [{"path": "report", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}], "absent": []}
        (self.cwds["baseline"] / "report").write_bytes(b"bad\n")
        with self.assertRaises(paired.RunAbortedError):
            self.produce(baseline_finalization=contract)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        first = summary["resource_observations"][0]
        self.assertTrue(first["guard_matched"])
        self.assertFalse(first["finalization_matched"])
        stage = self.read("block-000001-baseline.json")
        reference = stage["artifact_archive"]["artifacts"][0]
        self.assertEqual((self.output / "blobs" / reference["sha256"]).read_bytes(), b"bad\n")
        self.assertEqual(self.read("abort.json")["reason"], "required_finalization_failed")

    def test_archived_reports_remain_historical_not_live_worktree_checks(self):
        payload = b"done\n"
        contract = {"expected_exit_code": 0, "artifacts": [{"path": "report", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}], "absent": ["lease"]}
        for cwd in self.cwds.values():
            (cwd / "report").write_bytes(payload)
        self.produce(baseline_finalization=contract, candidate_finalization=contract)
        for cwd in self.cwds.values():
            (cwd / "report").unlink()
            (cwd / "lease").touch()
        self.assertEqual(summarize_run(self.output)["status"], "diagnostic_resource_observations")

    def test_expected_nonzero_measurement_is_explicit_and_unexpected_exit_blocks(self):
        self.produce(["nonzero"] * 4, baseline_guard={**self.guard, "expected_exit_code": 7}, candidate_guard={**self.guard, "expected_exit_code": 7})
        self.assertEqual(summarize_run(self.output)["status"], "diagnostic_resource_observations")
        self.output = self.root / "unexpected"
        self.produce(["nonzero"] * 4)
        summary = summarize_run(self.output)
        self.assert_denominator(summary)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["observed_arm_count"], 4)

    def test_resource_publication_failures_recover_only_valid_diagnostics_without_replay(self):
        original = timer.write_record
        for mode in ("error", "omit", "committed_then_error", "wrong"):
            self.output = self.root / f"raw-{mode}"

            def fail(path, value):
                if Path(path).name == "resource-block-000001-baseline.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode in ("error", "committed_then_error"):
                        raise OSError("injected resource publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", fail), self.assertRaises(paired.RunAbortedError):
                self.produce()
            self.assertEqual(self.last_measured.call_count, 1)
            if mode == "wrong":
                with self.assertRaises(ValueError):
                    summarize_run(self.output)
            else:
                summary = summarize_run(self.output)
                self.assert_denominator(summary)
                self.assertEqual(summary["observed_arm_count"], 1)
                self.assertFalse(summary["resource_observations"][0]["resource_record_committed"])
                self.assertIsNotNone(summary["resource_observations"][0]["cpu_delta_usec"])

    def test_stage_publication_failure_retains_resource_binding_and_diagnostic_stage(self):
        original = campaign.write_record
        for mode in ("error", "omit", "wrong"):
            self.output = self.root / f"stage-{mode}"

            def fail(path, value):
                if Path(path).name == "block-000001-baseline.json":
                    if mode == "error":
                        raise OSError("injected stage publication failure")
                    if mode == "wrong":
                        Path(path).write_text("{}")
                    return
                return original(path, value)

            with mock.patch.object(campaign, "write_record", fail), self.assertRaises(paired.RunAbortedError):
                self.produce()
            self.assertEqual(self.last_measured.call_count, 1)
            if mode == "wrong":
                with self.assertRaises(ValueError):
                    summarize_run(self.output)
            else:
                summary = summarize_run(self.output)
                self.assert_denominator(summary)
                self.assertTrue(summary["resource_observations"][0]["resource_record_committed"])
                self.assertFalse(summary["resource_observations"][0]["stage_record_committed"])
                self.assertTrue(summary["resource_observations"][0]["guard_matched"])

    def test_skipped_measurement_publication_failure_is_a_recoverable_accounted_abort(self):
        original = campaign.write_record
        for mode in ("error", "omit", "wrong"):
            self.output = self.root / f"skipped-{mode}"

            def fail(path, value):
                if Path(path).name == "block-000001-baseline.json":
                    if mode == "error":
                        raise OSError("injected skipped-record failure")
                    if mode == "wrong":
                        Path(path).write_text("{}")
                    return
                return original(path, value)

            with mock.patch.object(campaign, "write_record", fail), self.assertRaises(paired.RunAbortedError):
                self.produce(["nonzero"], baseline_prepare=self.command)
            self.assertEqual(self.last_measured.call_count, 1)
            if mode == "wrong":
                with self.assertRaises(ValueError):
                    summarize_run(self.output)
            else:
                summary = summarize_run(self.output)
                self.assert_denominator(summary)
                self.assertEqual(summary["observed_arm_count"], 0)
                self.assertEqual(summary["record_consistency"], "aborted")
                self.assertEqual(summary["resource_status_counts"], {"not_run_preparation_failed": 1, "not_run_run_aborted": 3})

    def test_missing_abort_cannot_turn_a_partial_campaign_into_a_complete_subset(self):
        with self.assertRaises(paired.RunAbortedError):
            self.produce(["background"])
        (self.output / "abort.json").unlink()
        with self.assertRaisesRegex(ValueError, "without required abort"):
            summarize_run(self.output)

    def test_missing_records_and_corrupt_byte_bindings_are_rejected_not_excluded(self):
        self.produce()
        for name in ("resource-block-000001-baseline.json", "block-000001-baseline.json"):
            path = self.output / name
            raw = path.read_bytes()
            path.unlink()
            with self.assertRaises((ValueError, OSError)):
                summarize_run(self.output)
            path.write_bytes(raw)
        stage = self.read("block-000001-baseline.json")
        stage["resource"]["sha256"] = "0" * 64
        (self.output / "block-000001-baseline.json").write_text(json.dumps(stage))
        with self.assertRaisesRegex(ValueError, "byte binding"):
            summarize_run(self.output)

    def test_rebound_record_with_different_stage_configuration_is_rejected(self):
        self.produce()
        name = "block-000001-baseline.json"
        raw = self.read(f"resource-{name}")
        # A timeout setting is structurally valid but not the campaign's setting.
        raw["configuration"]["timeout_seconds"] = 10
        self.rewrite_resource(name, raw)
        with self.assertRaisesRegex(ValueError, "stage configuration"):
            summarize_run(self.output)

    def test_overlapping_intervals_and_reused_private_group_are_rejected(self):
        self.produce()
        plan = self.read("schedule.json")
        first, second = plan["schedule"][0]["order"]
        previous = self.read(f"resource-block-000001-{first}.json")
        name = f"block-000001-{second}.json"
        original = self.read(f"resource-{name}")
        for mutation in ("clock", "group"):
            changed = copy.deepcopy(original)
            if mutation == "clock":
                changed["clock"]["monotonic_start_ns"] = previous["clock"]["monotonic_end_ns"] - 1
                changed["clock"]["elapsed_ns"] = changed["clock"]["monotonic_end_ns"] - changed["clock"]["monotonic_start_ns"]
            else:
                changed["group"]["path"] = previous["group"]["path"]
            self.rewrite_resource(name, changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                summarize_run(self.output)

    def test_resource_options_do_not_silently_change_legacy_or_lifecycle_modes(self):
        for endpoint in (timer.COMMAND_ENDPOINT, timer.LIFECYCLE_ENDPOINT):
            with self.assertRaisesRegex(ValueError, "explicit resource"):
                paired.run_pairs(self.output, self.root, self.command, self.command, 1, 3, 5,
                                 timing_endpoint=endpoint, resource_cgroup_parent="/synthetic/delegated")
            self.assertFalse(self.output.exists())
        for options in ({"capture_raw": True}, {"raw_limit_bytes": 0}, {"resource_allow_missing_peak": 1}, {"resource_sample_interval": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.produce(**options)
            self.assertFalse(self.output.exists())

    def test_bootstrap_requests_cannot_turn_resource_endpoint_into_latency_analysis(self):
        self.produce()
        with self.assertRaisesRegex(ValueError, "bootstrap is unsupported"):
            summarize_run(self.output, bootstrap_resamples=20, bootstrap_seed=0)
        for status in ("guard_matched_unqualified", "valid_expected_outcome"):
            samples = [{"block": str(number), "arm": arm, "status": status, "elapsed_ns": 10,
                        "timing_endpoint": resources.ENDPOINT} for number in (1, 2) for arm in campaign.ARMS]
            estimate = analysis.guarded_exploratory_ratio if status == "guard_matched_unqualified" else analysis.paired_geometric_ratio
            bootstrap = analysis.guarded_exploratory_bootstrap if status == "guard_matched_unqualified" else analysis.bootstrap_paired_ratio
            with self.assertRaisesRegex(ValueError, "not latency"):
                estimate(samples)
            with self.assertRaisesRegex(ValueError, "not latency"):
                bootstrap(samples, seed=0, resamples=20)

    def test_schema_references_types_and_context_are_closed_and_offline(self):
        schemas = [json.loads((HARNESS / name).read_text()) for name in
                   ("paired-resource-v1.schema.json", "resource-observation-v1.schema.json", "lifecycle-v2.schema.json")]
        registry = Registry().with_resources((item["$id"], Resource.from_contents(item)) for item in schemas)
        pending = []
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            pending.append((schema, schema["$id"]))
        while pending:
            value, base = pending.pop()
            if isinstance(value, dict):
                if "$ref" in value:
                    registry.resolver(base_uri=base).lookup(value["$ref"])
                pending.extend((child, base) for child in value.values())
            elif isinstance(value, list):
                pending.extend((child, base) for child in value)
        self.produce()
        plan = self.read("schedule.json")
        for field, value in (("seed", True), ("seed", 1.0), ("unknown", True), ("resources", None), ("measurement_layer", "shipping_timing")):
            changed = {**plan, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                campaign.validate("plan", changed)
        record = self.read("block-000001-baseline.json")
        record["context"]["block"] = True
        with self.assertRaises(ValueError):
            campaign.validate("stage", record)


@unittest.skipUnless(sys.platform == "linux", "native paired resource profile requires Linux")
class NativePairedResourceTests(unittest.TestCase):
    def setUp(self):
        self.parent = delegated_parent()
        if self.parent is None:
            self.skipTest("no writable already delegated memory-enabled parent")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "run"
        self.cwds = {arm: self.root / arm for arm in campaign.ARMS}
        for cwd in self.cwds.values():
            cwd.mkdir()
        self.command = [sys.executable, "-c", "from pathlib import Path; f=Path('calls').open('a'); f.write('call\\n'); f.close(); print('ready')"]
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": hashlib.sha256(b"ready\n").hexdigest()}

    def args(self):
        args = [sys.executable, str(HARNESS / "paired.py"), "--output", str(self.output), "--cwd", str(self.root),
                "--timing-endpoint", "resource", "--blocks", "2", "--seed", "0", "--timeout", "15",
                "--baseline-json", json.dumps(self.command), "--candidate-json", json.dumps(self.command)]
        for arm in campaign.ARMS:
            args += [f"--{arm}-cwd", str(self.cwds[arm]), f"--{arm}-guard-json", json.dumps(self.guard)]
        return args

    def test_native_strict_cli_preserves_all_unsupported_arms_and_never_runs_without_peak(self):
        result = subprocess.run([*self.args(), "--resource-cgroup-parent", str(self.parent)], capture_output=True, text=True, timeout=30)
        self.assertIn(result.returncode, (0, 3), result.stderr)
        checked = subprocess.run([sys.executable, str(HARNESS / "inspect_run.py"), str(self.output)], capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        summary = summarize_run(self.output)
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertEqual(sum(summary["resource_status_counts"].values()), 4)
        if result.returncode == 3:
            self.assertEqual(summary["observed_arm_count"], 0)
            self.assertEqual(summary["resource_status_counts"], {"unsupported": 4})
            self.assertTrue(all(not (cwd / "calls").exists() for cwd in self.cwds.values()))

    def test_native_partial_diagnostics_run_each_requested_measurement_once_with_unknown_peak(self):
        result = subprocess.run([*self.args(), "--resource-cgroup-parent", str(self.parent), "--resource-allow-missing-peak"],
                                capture_output=True, text=True, timeout=30)
        self.assertIn(result.returncode, (0, 1, 3), result.stderr)
        summary = summarize_run(self.output)
        if summary["observed_arm_count"] == 0:
            self.assertEqual(result.returncode, 3)
            self.skipTest("native required resource capability unavailable")
        self.assertEqual(summary["observed_arm_count"], 4)
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertIsNone(summary["ratio"])
        for arm, cwd in self.cwds.items():
            self.assertEqual(len((cwd / "calls").read_text().splitlines()), 2)
            self.assertEqual(summary["per_arm_resources"][arm]["cpu_usage_usec"]["observed_units"], 2)
        if summary["resource_status_counts"] == {"partial_unsupported": 4}:
            self.assertEqual(summary["status"], "blocked")
            self.assertTrue(all(item["peak_charged_bytes"] is None for item in summary["resource_observations"]))

    def test_native_asymmetric_unsupported_parent_does_not_disappear_from_summary(self):
        result = subprocess.run([*self.args(), "--candidate-resource-cgroup-parent", str(self.parent), "--resource-allow-missing-peak"],
                                capture_output=True, text=True, timeout=30)
        self.assertIn(result.returncode, (1, 3), result.stderr)
        summary = summarize_run(self.output)
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertEqual(summary["resource_status_counts"].get("unsupported"), 2 if result.returncode == 1 else 4)
        self.assertFalse((self.cwds["baseline"] / "calls").exists())
        self.assertIsNone(summary["per_arm_resources"]["baseline"]["cpu_usage_usec"]["observed_sum"])

    def test_native_detached_background_work_aborts_remaining_planned_arms(self):
        probe = HARNESS / "tests/fixtures/resource_probe.py"
        options = {f"{arm}_{key}": value for arm in campaign.ARMS for key, value in
                   (("cwd", self.cwds[arm]), ("guard", self.guard))}
        try:
            paired.run_pairs(self.output, self.root, [sys.executable, str(probe), str(self.cwds["baseline"]), "detached"],
                             self.command, 2, 0, 15, timing_endpoint=resources.ENDPOINT,
                             resource_cgroup_parent=self.parent, resource_allow_missing_peak=True, **options)
        except paired.RunAbortedError:
            summary = summarize_run(self.output)
            self.assertEqual(summary["planned_arm_count"], 4)
            self.assertEqual(summary["resource_status_counts"], {"failed": 1, "not_run_run_aborted": 3})
            self.assertFalse((self.cwds["candidate"] / "calls").exists())
            self.assertGreaterEqual(summary["resource_observations"][0]["cpu_delta_usec"]["usage_usec"], 150000)
        else:
            summary = summarize_run(self.output)
            self.assertEqual(summary["observed_arm_count"], 0)
            self.skipTest("native required resource capability unavailable; no subject ran")


if __name__ == "__main__":
    unittest.main()
