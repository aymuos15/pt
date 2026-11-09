"""Whole-session resources: explicit synthetic faults plus capability-gated native controls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from test_cgroup_accounting import SyntheticGroup, delegated_parent


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import replay_resources as observations
    import managed_replay as replay
    import resource_run as resources
    import pt_bench as timer
    from analysis import guarded_exploratory_ratio
finally:
    sys.path.pop(0)


class ReplayFixture:
    def prepare(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.output = self.root / "run"
        self.digest = hashlib.sha256(b"ready\n").hexdigest()
        self.probe = HARNESS / "tests/fixtures/replay_probe.py"
        self.plan = {"schema_version": 1, "kind": "managed_session_replay_plan", "mode": "exploratory_unqualified",
                     "sample_unit": replay.UNIT, "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT,
                     "scope": "fresh_serial_commands_with_declared_state", "cwd": str(self.cwd), "execution_timeout_seconds": 20,
                     "preparation": self.step("preparation", "preparation"),
                     "interactions": [self.step("interaction", "first"), self.step("interaction", "second")],
                     "shutdown": self.step("shutdown", "shutdown"),
                     "finalization": {"expected_exit_code": None, "artifacts": [self.artifact("report-shutdown")], "absent": ["lease"]},
                     "capture_raw": False, "raw_limit_bytes": 1024}

    def artifact(self, path):
        return {"path": path, "bytes": 6, "sha256": self.digest}

    def step(self, role, name):
        return {"id": name, "argv": [sys.executable, str(self.probe), str(self.cwd), role, name, "normal"],
                "timeout_seconds": 5, "idle_before_seconds": 0,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": self.digest},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [self.artifact("report-" + name)],
                                          "absent": ["lease"] if role == "shutdown" else []}}

    def summary(self):
        return observations.inspect_observation(self.output, self.receipt)

    def assert_counts(self, summary, count=4, interactions=2):
        self.assertEqual(summary["planned_session_count"], 1)
        self.assertEqual(summary["planned_phase_count"], count)
        self.assertEqual(sum(summary["phase_status_counts"].values()), count)
        self.assertEqual(sum(summary[key] for key in ("known_phase_invocation_attempts", "unknown_phase_invocations", "known_not_invoked_phases")), count)
        self.assertEqual(sum(summary["interaction_status_counts"].values()), interactions)
        for key in ("ratio", "bootstrap", "verified_independent_units", "per_phase_resource_metrics", "idle_only_resource_metrics"):
            self.assertIsNone(summary[key])
        self.assertFalse(summary["confirmatory_eligible"])
        self.assertEqual(summary["measurement_layer"], "resource_diagnostic")

    def rebind(self, name, value):
        path = self.output / name
        path.write_text(json.dumps(value))
        field = {"request.json": "request", "resource.json": "resource", "driver.json": "driver"}[name]
        self.receipt[field] = {"name": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        self.receipt["retained_inputs"] = observations._capture(self.output)[0]


class SyntheticReplayGroup(SyntheticGroup):
    """Real isolated driver/commands but synthetic enrollment and counters, never native evidence."""

    def __init__(self, measure, **options):
        super().__init__(**options)
        self.real_measure = measure

    def measure(self, argv, cwd, timeout, *, _pass_fds):
        start = time.monotonic_ns()
        result = super().measure(argv, cwd, timeout, _pass_fds=_pass_fds)
        if self.work not in ("normal", "background", "oom"):
            return result
        result = self.real_measure(argv[7:], cwd, timeout)
        result.update(argv=argv, **timer._timing(start))
        return result


@unittest.skipUnless(sys.platform == "linux", "initial Linux replay/blob profile")
class ReplayResourceTests(ReplayFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()
        self.real_measure = timer.measure

    def observe(self, group=None, **options):
        group = group or SyntheticReplayGroup(self.real_measure)
        with (mock.patch.object(resources, "CgroupDirectory", return_value=group),
              mock.patch.object(timer, "measure", side_effect=group.measure) as measured):
            self.receipt = observations.run_observation(self.output, self.plan, options.pop("outer_timeout", 30),
                                                       cgroup_parent="/synthetic/delegated", cleanup_grace=0, **options)
        self.assertTrue(group.closed)
        return self.summary(), group, measured

    def fault_driver(self, mode):
        path = self.root / f"driver-{mode}.py"
        path.write_text(f'''# Explicit test-only substituted harness driver, never production semantics.
import argparse
from pathlib import Path
import sys
sys.path.insert(0, {str(HARNESS)!r})
import replay_resources as observations
observations.DRIVER = Path(__file__).resolve()
original = observations.replay.run_replay
original_publish = observations._publish
mode = {mode!r}
def lost(*args, **kwargs):
    if mode == "lost_after":
        original(*args, **kwargs)
    raise OSError("fixture-only missing managed replay return")
def publish(path, value, kind):
    if kind == "driver":
        if mode == "committed_then_error":
            original_publish(path, value, kind)
        elif mode == "wrong":
            path.write_text("{{}}")
        raise OSError("fixture-only driver publication error")
    return original_publish(path, value, kind)
if mode.startswith("lost_"):
    observations.replay.run_replay = lost
else:
    observations._publish = publish
parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path)
parser.add_argument("--request-sha256")
args = parser.parse_args()
try:
    code = observations.driver_main(args.root, args.request_sha256)
except OSError as exc:
    print(str(exc), file=sys.stderr)
    code = 2
raise SystemExit(code)
''')
        return path

    def test_one_group_covers_one_real_driver_and_every_phase_with_explicit_overhead_and_clocks(self):
        summary, group, measured = self.observe()
        self.assert_counts(summary)
        measured.assert_called_once()
        self.assertEqual(summary["status"], "observed_unqualified")
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertTrue(summary["driver_completion_confirmed"])
        self.assertTrue(summary["whole_session_accounting_complete"])
        self.assertEqual(summary["cpu_delta_usec"]["usage_usec"], 300000)  # Synthetic counters only.
        self.assertTrue(group.removed)
        self.assertNotEqual(summary["observer_process"]["pid"], summary["driver_process"]["pid"])
        self.assertEqual(summary["clock_alignment"], observations.CLOCK_ALIGNMENT)
        self.assertEqual(summary["overhead_policy"], observations.OVERHEAD)
        request = json.loads((self.output / "request.json").read_text())
        self.assertEqual(request["driver"]["sha256"], hashlib.sha256(observations.DRIVER.read_bytes()).hexdigest())
        self.assertEqual(request["replay_plan"], self.plan)
        expected = {str(path.relative_to(self.output)) for path in self.output.rglob("*") if path.is_file()}
        self.assertEqual({item["path"] for item in self.receipt["retained_inputs"]["files"]}, expected)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def test_no_delegation_is_unsupported_and_starts_no_driver_or_subject(self):
        with mock.patch.object(timer, "measure") as measured:
            self.receipt = observations.run_observation(self.output, self.plan, 30)
            measured.assert_not_called()
        summary = self.summary()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "unsupported")
        self.assertEqual(summary["known_not_invoked_phases"], 4)
        self.assertEqual(summary["session_status"], "not_run_unsupported")
        self.assertIsNone(summary["cpu_delta_usec"])
        self.assertIsNone(summary["sampled_current_max_bytes"])
        self.assertIsNone(summary["peak_charged_bytes"])
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_every_required_capability_blocks_before_driver_work(self):
        for index, name in enumerate(("cpu.stat", "memory.current", "memory.peak", "memory.events", "cgroup.events", "cgroup.kill", "cgroup.procs")):
            self.output = self.root / f"missing-{index}"
            summary, group, measured = self.observe(SyntheticReplayGroup(self.real_measure, missing=[name]))
            measured.assert_not_called()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "unsupported")
            self.assertIsNone(summary["cpu_delta_usec"])
            self.assertIsNone(summary["peak_charged_bytes"])
            self.assertFalse((self.output / "session").exists())
            self.assertTrue(group.removed)

    def test_explicit_missing_peak_runs_once_but_remains_partial_with_null_peak(self):
        summary, _, measured = self.observe(SyntheticReplayGroup(self.real_measure, missing=["memory.peak"]), allow_missing_peak=True)
        measured.assert_called_once()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "partial_unsupported")
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertIsNone(summary["peak_charged_bytes"])
        self.assertIsNotNone(summary["cpu_delta_usec"])
        self.assertFalse(summary["whole_session_accounting_complete"])
        for field, value in (("peak_charged_bytes", 0), ("whole_boundary_accounting_complete", True), ("status", "observed_unqualified")):
            resource = json.loads((self.output / "resource.json").read_text())
            resource[field] = value
            self.rebind("resource.json", resource)
            with self.assertRaises(ValueError):
                self.summary()

    def test_preparation_failure_keeps_failed_and_not_run_phases_and_required_shutdown(self):
        self.plan["preparation"]["argv"][-1] = "fail"
        summary, _, _ = self.observe()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["phase_status_counts"], {"failed": 1, "not_run_prior_failure": 2, "observed_unqualified": 1})
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")
        self.assertTrue(summary["driver_completion_confirmed"])
        self.assertTrue(summary["counter_boundary_accounting_complete"])
        self.assertFalse(summary["whole_session_accounting_complete"])
        self.assertIsNotNone(summary["cpu_delta_usec"])

    def test_interaction_failure_preserves_effects_and_skips_later_work_without_retry(self):
        self.plan["interactions"][0]["argv"][-1] = "fail"
        summary, _, measured = self.observe()
        measured.assert_called_once()
        self.assert_counts(summary)
        self.assertEqual(summary["interaction_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual((self.cwd / "state").read_text(), "1")
        self.assertFalse((self.cwd / "lease").exists())

    def test_execution_deadline_still_uses_original_reserved_shutdown(self):
        self.plan["execution_timeout_seconds"] = 0.001
        summary, _, _ = self.observe()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["known_not_invoked_phases"], 3)
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")

    def test_shutdown_failure_timeout_and_missing_release_remain_failed_diagnostics(self):
        for mode in ("fail", "hang", "unreleased"):
            self.output = self.root / mode
            self.plan["shutdown"]["argv"][-1] = mode
            self.plan["shutdown"]["timeout_seconds"] = 0.1 if mode == "hang" else 5
            summary, _, _ = self.observe()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["shutdown_status"], "failed")

    def test_lingering_boundary_workers_fail_even_when_all_session_sentinels_match(self):
        summary, group, _ = self.observe(SyntheticReplayGroup(self.real_measure, work="background"))
        self.assert_counts(summary)
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertEqual(summary["status"], "failed")
        self.assertIn("background_work_outlived_command", summary["resource_failure_reasons"])
        self.assertEqual(group.kills, 1)
        self.assertGreater(summary["cpu_delta_usec"]["usage_usec"], 300000)  # Synthetic cleanup is also charged.

    def test_enrollment_exec_errors_timeouts_and_cancellation_keep_unknown_session_phases(self):
        for work in ("enrollment_error", "exec_error", "timeout", "exception", "interrupt"):
            self.output = self.root / work
            summary, group, measured = self.observe(SyntheticReplayGroup(self.real_measure, work=work))
            measured.assert_called_once()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["session_status"], "unknown")
            self.assertEqual(summary["unknown_phase_invocations"], 4)
            self.assertEqual(summary["known_not_invoked_phases"], 0)
            self.assertIsNone(summary["shutdown_status"])

    def test_counter_sampler_oom_and_cleanup_faults_cannot_be_promoted_by_completed_replay(self):
        for fault in ("cpu.stat", "memory.peak", "memory.current", "memory.events", "cgroup.events", "remove", "decreasing_cpu", "kill"):
            self.output = self.root / fault
            group = SyntheticReplayGroup(self.real_measure, work="background" if fault == "kill" else "normal", fault=fault)
            summary, _, _ = self.observe(group)
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["session_status"], "completed_unqualified")
            if fault == "cpu.stat":
                self.assertIsNone(summary["cpu_delta_usec"])

    def test_sampling_truncation_and_oom_keep_completed_replay_but_fail_accounting(self):
        self.output = self.root / "truncated"
        with mock.patch("cgroup_accounting.MAX_SAMPLES", 1):
            summary, _, _ = self.observe()
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertIn("sampling_truncated", summary["resource_failure_reasons"])
        self.output = self.root / "oom"
        summary, _, _ = self.observe(SyntheticReplayGroup(self.real_measure, work="oom"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertIn("oom_observed", summary["resource_failure_reasons"])

    def test_setup_failure_and_dynamic_loader_environment_never_start_subject(self):
        with mock.patch.object(resources, "CgroupDirectory", side_effect=RuntimeError("fixture-only retained group setup failure")):
            self.receipt = observations.run_observation(self.output, self.plan, 30)
        summary = self.summary()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "not_run_boundary_failed")
        self.assertEqual(summary["known_not_invoked_phases"], 4)
        self.output = self.root / "loader"
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "fixture-only-never-loaded"}):
            summary, _, measured = self.observe()
        measured.assert_not_called()
        self.assertEqual(summary["status"], "unsupported")
        self.assertFalse((self.output / "session").exists())

    def test_resource_observer_missing_return_keeps_all_metrics_unknown_without_replay(self):
        for error in (OSError("injected resource return loss"), RuntimeError("injected observer error"), KeyboardInterrupt("injected cancellation")):
            self.output = self.root / type(error).__name__
            with mock.patch.object(resources, "observe_resources", side_effect=error) as measured:
                self.receipt = observations.run_observation(self.output, self.plan, 30)
                measured.assert_called_once()
            summary = self.summary()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["unknown_phase_invocations"], 4)
            for field in ("cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes", "resource_status"):
                self.assertIsNone(summary[field])

    def test_resource_publication_failures_keep_matching_diagnostics_not_fake_commits(self):
        original = resources.publish_resource_record
        for mode in ("error", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, resource):
                if mode == "committed_then_error":
                    original(path, resource)
                elif mode == "wrong":
                    path.write_text("{}")
                raise OSError("injected resource publication failure")

            with mock.patch.object(resources, "publish_resource_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.observe()
                    continue
                summary, _, _ = self.observe()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["resource_record_confirmed"])
            self.assertIsNotNone(summary["cpu_delta_usec"])
            self.assertIsNotNone(self.receipt["diagnostic_resource"])

    def test_lost_managed_return_before_or_after_unit_commit_never_invents_phase_outcomes(self):
        for mode in ("lost_before", "lost_after"):
            self.output = self.root / mode
            with mock.patch.object(observations, "DRIVER", self.fault_driver(mode)):
                summary, _, _ = self.observe()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertTrue(summary["driver_completion_confirmed"])
            self.assertEqual(summary["unknown_phase_invocations"], 4)
            self.assertEqual(summary["observed_session_count"], 0)
            self.assertIsNone(summary["shutdown_status"])
            self.assertEqual((self.output / "session/unit.json").exists(), mode == "lost_after")

    def test_driver_publication_faults_preserve_diagnostics_without_fake_completion(self):
        for mode in ("error", "committed_then_error", "wrong"):
            self.output = self.root / mode
            with mock.patch.object(observations, "DRIVER", self.fault_driver(mode)):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.observe()
                    continue
                summary, _, _ = self.observe()
            self.assert_counts(summary)
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["driver_completion_confirmed"])
            self.assertEqual(summary["observed_session_count"], int(mode == "committed_then_error"))
            self.assertTrue((self.output / "session/unit.json").exists())

    def test_lost_outer_resource_return_keeps_returned_replay_evidence_but_unknown_metrics(self):
        original = resources.observe_resources

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("fixture-only lost outer resource return after driver completed")

        with mock.patch.object(resources, "observe_resources", side_effect=lost):
            summary, _, _ = self.observe()
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertEqual(summary["known_phase_invocation_attempts"], 4)
        self.assertIsNone(summary["cpu_delta_usec"])
        self.assertFalse(summary["driver_completion_confirmed"])

    def test_missing_transport_exit_or_observer_completion_cannot_confirm_driver_publication(self):
        self.observe()
        original = json.loads((self.output / "resource.json").read_text())
        for field, value in (("stdout_sha256", "0" * 64), ("returncode", 7), ("stderr_bytes", 1)):
            resource = copy.deepcopy(original)
            resource["process"][field] = value
            self.rebind("resource.json", resource)
            summary = self.summary()
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["driver_completion_confirmed"])
            self.assertEqual(summary["session_status"], "completed_unqualified")

    def test_cross_process_clock_domains_are_explicit_and_not_numerically_aligned(self):
        self.observe()
        driver = json.loads((self.output / "driver.json").read_text())
        driver["process"]["pid"] = self.receipt["observer_process"]["pid"]
        self.rebind("driver.json", driver)
        with self.assertRaisesRegex(ValueError, "distinct observer and driver"):
            self.summary()

    def test_only_same_process_clock_arithmetic_is_required_for_historical_inspection(self):
        self.observe()
        resource = json.loads((self.output / "resource.json").read_text())

        def shift(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("monotonic_start_ns", "monotonic_end_ns"):
                        value[key] += 10**15
                    else:
                        shift(item)
            elif isinstance(value, list):
                for item in value:
                    shift(item)

        # Synthetic independent observer offset: driver clocks are untouched.
        shift(resource)
        shift(self.receipt["observer_clock"])
        self.rebind("resource.json", resource)
        self.assertEqual(self.summary()["status"], "observed_unqualified")

    def test_rebound_omitted_shutdown_fails_semantic_inspection_not_only_stale_hashes(self):
        self.observe()
        unit_path = self.output / "session/unit.json"
        unit = json.loads(unit_path.read_text())
        unit["steps"].pop()
        unit_path.write_text(json.dumps(unit))
        driver = json.loads((self.output / "driver.json").read_text())
        driver["receipt"]["sample"].update(bytes=unit_path.stat().st_size, sha256=hashlib.sha256(unit_path.read_bytes()).hexdigest())
        self.rebind("driver.json", driver)
        with self.assertRaisesRegex(ValueError, "omitted a planned phase"):
            self.summary()

    def test_a_different_valid_session_cannot_replace_the_frozen_requested_plan(self):
        self.observe()
        request = json.loads((self.output / "request.json").read_text())
        request["replay_plan"]["preparation"]["argv"].append("not-executed")
        self.rebind("request.json", request)
        driver = json.loads((self.output / "driver.json").read_text())
        driver["request"] = self.receipt["request"]
        self.rebind("driver.json", driver)
        resource = json.loads((self.output / "resource.json").read_text())
        resource["configuration"]["argv"] = observations._command(request, self.receipt["request"])
        resource["process"]["argv"][-1] = self.receipt["request"]["sha256"]
        self.rebind("resource.json", resource)
        with self.assertRaisesRegex(ValueError, "actual session plan differs"):
            self.summary()

    def test_wrong_invocation_bindings_and_omitted_driver_inventory_are_rejected(self):
        self.observe()
        original = copy.deepcopy(self.receipt)
        self.receipt["driver"] = None
        with self.assertRaises(ValueError):
            self.summary()
        self.receipt = original
        driver = json.loads((self.output / "driver.json").read_text())
        driver["invocation_id"] = "0" * 32
        self.rebind("driver.json", driver)
        with self.assertRaisesRegex(ValueError, "invocation binding differs"):
            self.summary()

    def test_unknowns_are_not_replaced_by_zeros_and_strict_types_and_schema_closure_apply(self):
        self.observe()
        original = copy.deepcopy(self.receipt)
        for mutation in (lambda value: value.update(confirmatory_eligible=True), lambda value: value.update(unknown_field=0),
                         lambda value: value.update(schema_version=True), lambda value: value.update(diagnostic_resource=0),
                         lambda value: value.update(clock_alignment="shared_clock"), lambda value: value["observer_process"].update(pid=1.0)):
            changed = copy.deepcopy(original)
            mutation(changed)
            with self.assertRaises(ValueError):
                observations.validate("receipt", changed)

    def test_unsafe_or_extra_evidence_and_corrupt_blobs_fail_closed(self):
        self.observe()
        alias = self.root / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            observations.inspect_observation(alias, self.receipt)
        os.mkfifo(self.output / "fifo")
        with self.assertRaises(ValueError):
            self.summary()
        (self.output / "fifo").unlink()
        (self.output / "extra").mkdir()
        with self.assertRaises(ValueError):
            self.summary()
        (self.output / "extra").rmdir()
        blob = next((self.output / "session/blobs").iterdir())
        blob.write_bytes(b"corrupt")
        self.receipt["retained_inputs"] = observations._capture(self.output)[0]
        with self.assertRaises(ValueError):
            self.summary()

    def test_historical_inspection_relocates_without_worktree_cgroup_or_command_access(self):
        expected, _, _ = self.observe()
        for path in self.cwd.glob("report-*"):
            path.unlink()
        (self.cwd / "lease").touch()
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        with mock.patch.object(resources, "observe_resources") as measured, mock.patch.object(resources, "CgroupDirectory") as group:
            self.assertEqual(observations.inspect_observation(moved, self.receipt), expected)
            measured.assert_not_called()
            group.assert_not_called()

    def test_observed_fingerprint_changes_during_inspection_are_not_retried(self):
        self.observe()
        original = observations._capture
        calls = []

        def changed(path):
            value = original(path)
            calls.append(1)
            if len(calls) > 1:
                value[1]["request.json"][-1] += 1  # Explicit synthetic fingerprint-only change.
            return value

        with mock.patch.object(observations, "_capture", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                self.summary()
        self.assertEqual(len(calls), 2)

    def test_invalid_settings_watchdog_and_existing_outputs_stop_before_any_boundary(self):
        for options in ({"outer_timeout": 29}, {"allow_missing_peak": 1}, {"sample_interval": 0}, {"outer_timeout": True}):
            with mock.patch.object(resources, "observe_resources") as measured:
                with self.assertRaises(ValueError):
                    self.observe(**options)
                measured.assert_not_called()
            self.assertFalse(self.output.exists())
        self.output.mkdir()
        marker = self.output / "user-work"
        marker.write_text("keep")
        with mock.patch.object(resources, "observe_resources") as measured:
            with self.assertRaises(FileExistsError):
                self.observe()
            measured.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")

    def test_request_publication_and_receipt_or_evidence_size_limits_drop_nothing(self):
        original = timer.write_record

        def omit(path, value):
            if Path(path).name == "request.json":
                return
            return original(path, value)

        with mock.patch.object(timer, "write_record", side_effect=omit), mock.patch.object(resources, "observe_resources") as measured:
            with self.assertRaises(OSError):
                observations.run_observation(self.output, self.plan, 30)
            measured.assert_not_called()
        self.output = self.root / "complete"
        self.observe()
        for attribute in ("MAX_EVIDENCE_FILES", "MAX_EVIDENCE_BYTES"):
            with mock.patch.object(observations, attribute, 1):
                with self.assertRaisesRegex(ValueError, "aggregate file/byte limit"):
                    self.summary()
        with mock.patch.object(observations.files, "MAX_RECEIPT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "receipt limits"):
                self.summary()

    def test_schema_references_resolve_offline_and_new_diagnostics_are_not_latency_samples(self):
        schemas = [json.loads((HARNESS / name).read_text()) for name in (
            "replay-resource-v1.schema.json", "managed-replay-v1.schema.json", "resource-observation-v1.schema.json",
            "lifecycle-v2.schema.json", "result-card-v1.schema.json", "paired-resource-v1.schema.json")]
        registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
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
        with self.assertRaisesRegex(ValueError, "resource diagnostic"):
            guarded_exploratory_ratio([{"block": "1", "arm": "baseline", "elapsed_ns": 1,
                                        "status": "guard_matched_unqualified", "measurement_layer": "resource_diagnostic"}])

    def test_cli_unsupported_receipt_and_read_only_inspection_keep_null_metrics(self):
        path, receipt_path = self.root / "plan.json", self.root / "receipt.json"
        path.write_text(json.dumps(self.plan))
        result = subprocess.run([sys.executable, str(HARNESS / "replay_resources.py"), "--plan", str(path), "--output", str(self.output),
                                 "--outer-timeout", "30"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt_path.write_text(result.stdout)
        result = subprocess.run([sys.executable, str(HARNESS / "inspect_replay_resources.py"), "--directory", str(self.output),
                                 "--receipt", str(receipt_path)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assert_counts(summary)
        self.assertEqual(summary["status"], "unsupported")


@unittest.skipUnless(sys.platform == "linux", "native whole-session checks require Linux cgroup v2")
class NativeReplayResourceTests(ReplayFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()
        self.parent = delegated_parent()
        if self.parent is None:
            self.skipTest("no writable delegated memory-enabled parent; no host reconfiguration attempted")
        self.probe = HARNESS / "tests/fixtures/replay_resource_probe.py"
        self.plan["interactions"] = [self.plan["interactions"][0]]
        self.plan["interactions"][0]["idle_before_seconds"] = 0.3
        for role, step in replay._steps(self.plan):
            step["argv"] = [sys.executable, str(self.probe), str(self.cwd), role, "normal"]
            step["required_finalization"]["artifacts"] = [self.artifact("report-" + role)]

    def observe_native(self, **options):
        self.receipt = observations.run_observation(self.output, self.plan, options.pop("outer_timeout", 30), cgroup_parent=self.parent,
                                                   allow_missing_peak=options.pop("allow_missing_peak", True), **options)
        resource = json.loads((self.output / "resource.json").read_text())
        if not resource["run_attempted"]:
            if resource["status"] == "unsupported":
                self.skipTest(f"native capability unavailable: {resource['capabilities']}")
            self.fail(f"native setup failed, not an unsupported skip: {resource['errors']}")
        return self.summary(), resource

    def test_background_cpu_and_residency_through_idle_plus_shutdown_are_inside_one_boundary(self):
        summary, resource = self.observe_native()
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertTrue(summary["driver_completion_confirmed"])
        prepared = json.loads((self.cwd / "preparation.progress").read_text())
        interacted = json.loads((self.cwd / "interaction.progress").read_text())
        worker = json.loads((self.cwd / "worker.finished").read_text())
        shutdown_cpu = int((self.cwd / "shutdown.cpu").read_text())
        self.assertGreater(interacted["cpu_ns"] - prepared["cpu_ns"], 100_000_000)
        self.assertGreaterEqual(shutdown_cpu, 150_000_000)
        self.assertGreaterEqual(resource["cpu_delta_usec"]["usage_usec"] * 1000, worker["cpu_ns"] + shutdown_cpu - 50_000_000)
        self.assertGreaterEqual(summary["sampled_current_max_bytes"], 64 * 1024 * 1024)
        self.assertFalse(resource["cleanup"]["kill_requested"])
        self.assertEqual(resource["snapshots"]["final"]["population"], 0)
        self.assertTrue(resource["group"]["removed"])
        self.assertFalse(Path(resource["group"]["path"]).exists())
        if not resource["capabilities"]["memory_peak"]["supported"]:
            self.assertEqual(summary["status"], "partial_unsupported")
            self.assertIsNone(summary["peak_charged_bytes"])
            self.assertFalse(summary["whole_session_accounting_complete"])
        else:
            self.assertEqual(summary["status"], "observed_unqualified")
            self.assertGreaterEqual(summary["peak_charged_bytes"], summary["sampled_current_max_bytes"])

    def test_detached_worker_left_after_successful_shutdown_sentinel_is_counted_killed_and_failed(self):
        self.plan["shutdown"]["argv"][-1] = "leave_worker"
        summary, resource = self.observe_native(cleanup_grace=0.05)
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertEqual(summary["status"], "failed")
        self.assertIn("background_work_outlived_command", summary["resource_failure_reasons"])
        self.assertTrue(resource["cleanup"]["kill_requested"])
        self.assertGreaterEqual(summary["sampled_current_max_bytes"], 64 * 1024 * 1024)
        self.assertEqual(resource["snapshots"]["final"]["population"], 0)
        self.assertTrue(resource["group"]["removed"])

    def test_failed_interaction_still_runs_declared_shutdown_and_never_retries(self):
        self.plan["interactions"][0]["argv"][-1] = "fail"
        summary, resource = self.observe_native()
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "aborted")
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")
        self.assertTrue((self.cwd / "worker.finished").exists())
        self.assertFalse(resource["cleanup"]["kill_requested"])
        self.assertEqual(len((self.cwd / "events").read_text().splitlines()), 3)

    def test_strict_missing_peak_starts_no_driver_or_session_then_explicit_mode_is_partial(self):
        self.receipt = observations.run_observation(self.output, self.plan, 30, cgroup_parent=self.parent)
        resource = json.loads((self.output / "resource.json").read_text())
        summary = self.summary()
        if resource["group"] is None or any(not resource["capabilities"][key]["supported"] for key in resources.CAPABILITIES if key != "memory_peak"):
            self.assertEqual(resource["status"], "unsupported", resource["errors"])
            self.skipTest(f"native delegated capabilities unavailable: {resource['capabilities']}")
        if resource["capabilities"]["memory_peak"]["supported"]:
            self.assertEqual(summary["status"], "observed_unqualified")
        else:
            self.assertEqual(summary["status"], "unsupported")
            self.assertEqual(summary["known_not_invoked_phases"], 3)
            self.assertIsNone(summary["cpu_delta_usec"])
            self.assertIsNone(summary["peak_charged_bytes"])
            self.assertEqual(list(self.cwd.iterdir()), [])
        self.assertTrue(resource["group"]["removed"])

    def test_outer_watchdog_of_explicit_test_only_hang_driver_leaves_replay_outcome_unknown(self):
        self.plan["execution_timeout_seconds"] = 0.01
        self.plan["shutdown"]["timeout_seconds"] = 0.01
        with mock.patch.object(observations, "DRIVER", HARNESS / "tests/fixtures/replay_resource_hang_driver.py"):
            summary, resource = self.observe_native(outer_timeout=5.1)
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(resource["process"]["status"], "timeout")
        self.assertEqual(summary["session_status"], "unknown")
        self.assertEqual(summary["unknown_phase_invocations"], 3)
        self.assertIsNone(summary["shutdown_status"])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(resource["snapshots"]["final"]["population"], 0)
        self.assertTrue(resource["group"]["removed"])

    def test_cancellation_after_worker_creation_kills_owned_boundary_without_fake_shutdown_receipt(self):
        def cancel(process, timeout, capture=None):
            deadline = time.monotonic() + 10
            while not (self.cwd / "worker.progress").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("native fixture did not start before cancellation")
                time.sleep(0.01)
            raise KeyboardInterrupt("test-only cancellation after worker became resident")

        with mock.patch.object(timer, "_stream_posix", side_effect=cancel):
            summary, resource = self.observe_native(cleanup_grace=0.01)
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["session_status"], "unknown")
        self.assertIsNone(summary["shutdown_status"])
        self.assertTrue(resource["cleanup"]["kill_requested"])
        self.assertEqual(resource["snapshots"]["final"]["population"], 0)
        self.assertTrue(resource["group"]["removed"])

    def test_subject_argv_cwd_environment_and_no_harness_imports_survive_isolated_driver(self):
        code = ("import json,os,sys; from pathlib import Path; "
                "Path('subject-transport.json').write_text(json.dumps([sys.argv[1:],os.getcwd(),os.environ['PT_REPLAY_RESOURCE_FIXTURE'],"
                "[name for name in ('managed_replay','replay_resources') if name in sys.modules]])); "
                "Path('report-interaction').write_text('ready\\n'); print('ready')")
        self.plan["interactions"][0]["argv"] = [sys.executable, "-c", code, "with space", "", "\u03bb"]
        with mock.patch.dict(os.environ, {"PT_REPLAY_RESOURCE_FIXTURE": "fixture-only"}):
            summary, resource = self.observe_native()
        self.assert_counts(summary, count=3, interactions=1)
        self.assertEqual(summary["session_status"], "completed_unqualified")
        self.assertEqual(json.loads((self.cwd / "subject-transport.json").read_text()), [["with space", "", "\u03bb"], str(self.cwd), "fixture-only", []])
        self.assertFalse(resource["cleanup"]["kill_requested"])


if __name__ == "__main__":
    unittest.main()
