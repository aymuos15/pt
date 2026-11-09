"""Synthetic state/format controls plus explicitly capability-gated native tests."""

from contextlib import redirect_stderr
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import cgroup_accounting as accounting
    import resource_run as observer
    import pt_bench as timer
    from finalization import MAX_RECEIPT_BYTES, read_json
finally:
    sys.path.pop(0)


class SyntheticGroup:
    """Ordinary Python state only; never represents native kernel evidence."""

    def __init__(self, *, missing=(), work="normal", fault=None):
        self.path = Path("/synthetic/delegated") / ("pt-bench-" + "a" * 32)
        self.identity = [1, 2]
        self.missing, self.work, self.fault = set(missing), work, fault
        self.executed = self.removed = self.closed = False
        self.kills = self.cpu_reads = 0
        self.initial_cpu_reads = 0
        self.interrupted_population = False
        self.cpu = {"usage_usec": 0, "user_usec": 0, "system_usec": 0}
        self.current = self.peak = self.populated = 0
        self.events = {"oom": 0, "oom_kill": 0, "high": 0}

    def read(self, name):
        if name in self.missing:
            raise FileNotFoundError(name)
        if self.executed and self.fault == name:
            raise OSError(f"injected unreadable {name}")
        if name == "cgroup.events" and self.executed and self.fault == "interrupt_population" and not self.interrupted_population:
            self.interrupted_population = True
            raise KeyboardInterrupt("injected interrupted population read")
        if name == "cpu.stat":
            if self.executed:
                self.cpu_reads += 1
                if self.fault == "decreasing_cpu" and self.cpu_reads > 1:
                    return "usage_usec 10\nuser_usec 8\nsystem_usec 2\n"
            else:
                self.initial_cpu_reads += 1
                if self.fault == "initial_cpu_read" and self.initial_cpu_reads == 2:
                    raise OSError("injected initial CPU read failure")
            return "".join(f"{key} {value}\n" for key, value in self.cpu.items())
        if name == "memory.events":
            return "".join(f"{key} {value}\n" for key, value in self.events.items())
        values = {"memory.current": self.current, "memory.peak": self.peak, "cgroup.events": self.populated}
        return f"populated {self.populated}\nfrozen 0\n" if name == "cgroup.events" else f"{values[name]}\n"

    def open(self, name, *, write=False):
        if name in self.missing:
            raise PermissionError(f"injected denied {name}")
        return os.open(os.devnull, os.O_WRONLY if write else os.O_RDONLY)

    def kill(self):
        self.kills += 1
        if self.fault == "kill":
            raise PermissionError("injected cgroup.kill failure")
        self.populated, self.current = 0, 0
        self.cpu["usage_usec"] += 50000
        self.cpu["system_usec"] += 50000

    def remove(self):
        if self.populated or self.fault == "remove":
            raise OSError("injected nonempty/removal failure")
        self.removed = True

    def reader(self):
        return self  # No real descriptors in the synthetic counter-state model.

    def close(self):
        self.closed = True

    def measure(self, argv, cwd, timeout, *, _pass_fds):
        assert list(_pass_fds) == [int(argv[4]), int(argv[5])]
        start = time.monotonic_ns()
        self.executed = True
        if self.work != "enrollment_error":
            os.write(int(argv[5]), b"enrolled\n")
        else:
            os.write(int(argv[5]), b"enrollment_error:13\n")
        self.cpu = {"usage_usec": 300000, "user_usec": 260000, "system_usec": 40000}
        self.peak = 96 * 1024 * 1024
        if self.work in ("background", "timeout", "exception", "interrupt"):
            self.populated, self.current = 1, 64 * 1024 * 1024
        if self.work == "exception":
            raise OSError("injected measurement failure")
        if self.work == "interrupt":
            raise KeyboardInterrupt("injected cancellation")
        if self.work == "oom":
            self.events.update(oom=1, oom_kill=1)
        if self.work == "exec_error":
            os.write(int(argv[5]), b"exec_error:2\n")
        result = {"status": "timeout" if self.work == "timeout" else "exited_unqualified",
                  "argv": argv, "cwd": cwd, **timer._timing(start),
                  "returncode": 7 if self.work == "nonzero" else 0,
                  "process_reaped": True, "output_complete": True,
                  "stdout_bytes": 0, "stderr_bytes": 0,
                  "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                  "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
        return result


class ResourceAccountingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.command = [sys.executable, "-c", "pass"]

    def observe(self, group=None, **options):
        group = group or SyntheticGroup()
        with (mock.patch.object(observer, "CgroupDirectory", return_value=group),
              mock.patch.object(timer, "measure", side_effect=group.measure) as measured):
            record = observer.observe_resources(self.command, self.root, 5, cgroup_parent="/synthetic/delegated",
                                                cleanup_grace=0, **options)
        self.assertTrue(group.closed)
        return record, group, measured

    def test_counter_parsing_rejects_ambiguous_incomplete_and_out_of_range_values(self):
        for raw in ("-1", "NaN", "1.0", "true", " 1", "1 2", "", str(2**64)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                accounting.uint(raw)
        for raw in ("usage_usec 1\nusage_usec 2\n", "usage_usec 0\n", "usage_usec -1\n", "unknown? 1\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                accounting.counters(raw, accounting.CPU_KEYS)
        self.assertEqual(accounting.uint("0\n"), 0)

    def test_ordinary_filesystem_cannot_be_used_as_an_accounting_backend(self):
        with self.assertRaises(accounting.UnsupportedAccounting):
            accounting.CgroupDirectory(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_no_parent_nonlinux_and_denied_delegation_never_launch_subject(self):
        with mock.patch.object(timer, "measure") as measured:
            record = observer.observe_resources(self.command, self.root, 5)
            self.assertEqual(record["status"], "unsupported")
            self.assertIsNone(record["cpu_delta_usec"])
            self.assertIsNone(record["peak_charged_bytes"])
            measured.assert_not_called()
        with mock.patch.object(accounting.sys, "platform", "unsupported"):
            with self.assertRaises(accounting.UnsupportedAccounting):
                accounting.CgroupDirectory(self.root)
        with mock.patch.object(observer, "CgroupDirectory", side_effect=PermissionError("not delegated")):
            record = observer.observe_resources(self.command, self.root, 5, cgroup_parent=self.root)
            self.assertEqual(record["status"], "unsupported")

    def test_failed_setup_cleanup_is_failed_not_a_successful_unsupported_probe(self):
        with mock.patch.object(observer, "CgroupDirectory", side_effect=accounting.AccountingSetupError("private cgroup retained")):
            record = observer.observe_resources(self.command, self.root, 5, cgroup_parent=self.root)
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["run_attempted"])
        self.assertIn("private cgroup retained", record["errors"][0]["error"])

    def test_required_capabilities_fail_closed_and_do_not_invent_zero_metrics(self):
        for name in ("cpu.stat", "memory.current", "memory.peak", "memory.events", "cgroup.events", "cgroup.kill", "cgroup.procs"):
            record, group, measured = self.observe(SyntheticGroup(missing=[name]))
            with self.subTest(missing=name):
                self.assertEqual(record["status"], "unsupported")
                self.assertFalse(record["run_attempted"])
                self.assertIsNone(record["cpu_delta_usec"])
                self.assertIsNone(record["peak_charged_bytes"])
                self.assertIsNone(record["sampled_current_max_bytes"])
                self.assertTrue(group.removed)
                measured.assert_not_called()

    def test_dynamic_loader_environment_is_unsupported_not_executed_outside_boundary(self):
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "fixture-only-not-loaded.so"}):
            record, _, measured = self.observe()
        measured.assert_not_called()
        self.assertEqual(record["status"], "unsupported")
        self.assertFalse(record["capabilities"]["enrollment"]["supported"])
        self.assertNotIn("fixture-only-not-loaded.so", json.dumps(record))

    def test_explicit_partial_diagnostic_never_promotes_sampled_current_to_peak(self):
        record, _, measured = self.observe(SyntheticGroup(missing=["memory.peak"]), allow_missing_peak=True)
        self.assertEqual(record["status"], "partial_unsupported")
        self.assertEqual(record["cpu_delta_usec"]["usage_usec"], 300000)
        self.assertIsNone(record["peak_charged_bytes"])
        self.assertFalse(record["whole_boundary_accounting_complete"])
        self.assertEqual(measured.call_count, 1)
        for missing in ("cpu.stat", "memory.current", "cgroup.kill"):
            record, _, measured = self.observe(SyntheticGroup(missing=["memory.peak", missing]), allow_missing_peak=True)
            self.assertEqual(record["status"], "unsupported")
            measured.assert_not_called()

    def test_kernel_whole_group_peak_is_used_even_when_sampler_misses_transient_memory(self):
        record, group, measured = self.observe()
        self.assertEqual(record["status"], "observed_unqualified")
        self.assertEqual(record["peak_charged_bytes"], 96 * 1024 * 1024)
        self.assertEqual(record["sampled_current_max_bytes"], 0)
        self.assertEqual(record["cpu_delta_usec"], {"usage_usec": 300000, "user_usec": 260000, "system_usec": 40000})
        self.assertTrue(record["whole_boundary_accounting_complete"])
        self.assertEqual(measured.call_count, 1)
        self.assertEqual(group.kills, 0)
        self.assertFalse(record["confirmatory_eligible"])

    def test_background_cpu_and_persistent_memory_are_retained_after_leader_return(self):
        record, group, _ = self.observe(SyntheticGroup(work="background"))
        self.assertEqual(record["process"]["returncode"], 0)
        self.assertEqual(record["status"], "failed")
        self.assertIn("background_work_outlived_command", record["failure_reasons"])
        self.assertEqual(record["cpu_delta_usec"]["usage_usec"], 350000)
        self.assertEqual(record["sampled_current_max_bytes"], 64 * 1024 * 1024)
        self.assertEqual(record["peak_charged_bytes"], 96 * 1024 * 1024)
        self.assertEqual(record["snapshots"]["final"]["population"], 0)
        self.assertEqual(group.kills, 1)
        self.assertTrue(group.removed)

    def test_timeout_measurement_error_and_cancellation_do_not_replay_or_omit_cleanup(self):
        for work in ("timeout", "exception", "interrupt"):
            record, group, measured = self.observe(SyntheticGroup(work=work))
            with self.subTest(work=work):
                self.assertEqual(record["status"], "failed")
                self.assertEqual(measured.call_count, 1)
                self.assertEqual(group.kills, 1)
                self.assertTrue(group.removed)
                self.assertIsNotNone(record["cpu_delta_usec"])
                observer.inspect_resource_record(record)
        record, group, measured = self.observe(SyntheticGroup(work="background", fault="interrupt_population"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(group.kills, 1)
        self.assertTrue(group.removed)
        self.assertEqual(measured.call_count, 1)

    def test_initial_counter_read_failure_blocks_work_even_after_a_successful_probe(self):
        record, group, measured = self.observe(SyntheticGroup(fault="initial_cpu_read"))
        measured.assert_not_called()
        self.assertTrue(record["capabilities"]["cpu_stat"]["supported"])
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["run_attempted"])
        self.assertIsNone(record["cpu_delta_usec"])
        self.assertTrue(group.removed)

    def test_failed_enrollment_or_exec_is_not_confused_with_completed_subject_work(self):
        for work in ("enrollment_error", "exec_error"):
            record, _, measured = self.observe(SyntheticGroup(work=work))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["enrollment"]["status"], "failed")
            self.assertEqual(measured.call_count, 1)

    def test_nonzero_subject_outcome_keeps_complete_resource_evidence_without_becoming_a_pass(self):
        record, _, _ = self.observe(SyntheticGroup(work="nonzero"))
        self.assertEqual(record["process"]["returncode"], 7)
        self.assertTrue(record["whole_boundary_accounting_complete"])
        self.assertEqual(record["status"], "observed_unqualified")
        self.assertFalse(record["confirmatory_eligible"])

    def test_oom_events_and_post_launch_capability_loss_remain_failures(self):
        record, _, _ = self.observe(SyntheticGroup(work="oom"))
        self.assertIn("oom_observed", record["failure_reasons"])
        for name in ("cpu.stat", "memory.current", "memory.peak", "memory.events"):
            record, _, _ = self.observe(SyntheticGroup(fault=name))
            with self.subTest(file=name):
                self.assertEqual(record["status"], "failed")
                self.assertTrue(record["errors"])
                self.assertFalse(record["whole_boundary_accounting_complete"])

    def test_decreasing_midrun_cpu_counters_are_not_reported_as_lower_resource_cost(self):
        record, _, _ = self.observe(SyntheticGroup(fault="decreasing_cpu"))
        self.assertEqual(record["status"], "failed")
        self.assertIsNone(record["cpu_delta_usec"])
        self.assertIn("cpu_accounting_incomplete", record["failure_reasons"])
        self.assertTrue(any(item["stage"] == "derivation" for item in record["errors"]))

    def test_kill_or_group_removal_failure_retains_uncertain_boundary_and_original_metrics(self):
        for fault in ("kill", "remove"):
            record, group, measured = self.observe(SyntheticGroup(work="background", fault=fault))
            with self.subTest(fault=fault):
                self.assertEqual(record["status"], "failed")
                self.assertFalse(record["group"]["removed"])
                self.assertIn("group_not_removed", record["failure_reasons"])
                self.assertEqual(group.kills, 1)
                self.assertEqual(measured.call_count, 1)
                self.assertIsNotNone(record["cpu_delta_usec"])

    def test_nonfresh_group_is_rejected_before_work_and_never_adopted(self):
        for metric in ("current", "peak", "populated", "cpu"):
            group = SyntheticGroup()
            if metric == "cpu":
                group.cpu["usage_usec"] = 1
            else:
                setattr(group, metric, 1)
            record, _, measured = self.observe(group)
            self.assertEqual(record["status"], "failed")
            self.assertIn("boundary_not_fresh", record["failure_reasons"])
            self.assertEqual(group.kills, 0, "do not kill or adopt a pre-existing task")
            measured.assert_not_called()

    def test_truncated_or_failed_sampler_is_explicit_and_blocks_completeness(self):
        group = SyntheticGroup()
        original = group.measure

        def slow(*args, **kwargs):
            result = original(*args, **kwargs)
            time.sleep(0.03)
            return result

        group.measure = slow
        with mock.patch.object(accounting, "MAX_SAMPLES", 1):
            record, _, _ = self.observe(group, sample_interval=0.001)
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["sampling"]["truncated"])
        self.assertIn("sampling_truncated", record["failure_reasons"])
        with mock.patch.object(accounting.CurrentMemorySampler, "start", side_effect=RuntimeError("injected thread startup failure")):
            record, group, measured = self.observe()
        self.assertEqual(record["status"], "failed")
        self.assertTrue(group.removed)
        measured.assert_not_called()

    def test_schema_and_all_bundled_references_are_valid_offline(self):
        schemas = [json.loads((HARNESS / name).read_text()) for name in
                   ("resource-observation-v1.schema.json", "lifecycle-v2.schema.json")]
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

    def test_unknown_missing_fields_and_boolean_integer_float_ambiguity_are_rejected(self):
        record, _, _ = self.observe()
        mutations = [
            lambda value: value.update(unexpected=True),
            lambda value: value.pop("capabilities"),
            lambda value: value["snapshots"]["final"].pop("cpu_stat"),
            lambda value: value["cpu_delta_usec"].update(usage_usec=True),
            lambda value: value["snapshots"]["final"]["cpu_stat"].update(user_usec=260000.0),
            lambda value: value["capabilities"]["memory_peak"].update(supported=1),
            lambda value: value["clock"].update(elapsed_ns=-1),
            lambda value: value["configuration"].update(timeout_seconds=float("inf")),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(record)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                observer.inspect_resource_record(changed)

    def test_leader_only_cost_false_peak_and_incomplete_scope_controls_are_rejected(self):
        record, _, _ = self.observe(SyntheticGroup(work="background"))
        mutations = [
            lambda value: value["cpu_delta_usec"].update(usage_usec=1000),
            lambda value: value.update(peak_charged_bytes=value["sampled_current_max_bytes"]),
            lambda value: value.update(scope="direct_process_only"),
            lambda value: value["cleanup"].update(residual_at_command_return=False),
            lambda value: value.update(status="observed_unqualified", whole_boundary_accounting_complete=True),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(record)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                observer.inspect_resource_record(changed)

    def test_partial_and_unsupported_records_cannot_be_promoted_by_relabeling_or_zero_substitution(self):
        partial, _, _ = self.observe(SyntheticGroup(missing=["memory.peak"]), allow_missing_peak=True)
        unsupported, _, _ = self.observe(SyntheticGroup(missing=["memory.peak"]))
        for record in (partial, unsupported):
            for field, value in (("peak_charged_bytes", 0), ("status", "observed_unqualified"),
                                 ("whole_boundary_accounting_complete", True)):
                changed = copy.deepcopy(record)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    observer.inspect_resource_record(changed)

    def test_record_round_trip_is_order_independent_and_published_without_overwrite(self):
        record, _, _ = self.observe()
        path = self.root / "resource.json"
        observer.publish_resource_record(path, record)
        loaded, _ = read_json(path, limit=MAX_RECEIPT_BYTES)
        self.assertEqual(observer.inspect_resource_record(loaded), observer.inspect_resource_record(record))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            observer.publish_resource_record(path, record)

    def test_failed_publication_does_not_replay_resource_work(self):
        record, _, _ = self.observe()
        with mock.patch.object(timer, "write_record", side_effect=OSError("injected disk failure")):
            with self.assertRaises(OSError):
                observer.publish_resource_record(self.root / "resource.json", record)
        with mock.patch.object(timer, "write_record", return_value=None):
            with self.assertRaises(OSError):
                observer.publish_resource_record(self.root / "omitted.json", record)

    def test_invalid_configuration_and_existing_output_stop_before_subject_work(self):
        for options in ({"allow_missing_peak": 1}, {"sample_interval": 0}, {"cleanup_grace": -1}):
            with self.subTest(options=options), mock.patch.object(observer, "CgroupDirectory") as group:
                with self.assertRaises(ValueError):
                    observer.observe_resources(self.command, self.root, 5, **options)
                group.assert_not_called()
        path = self.root / "exists.json"
        path.write_text("existing")
        argv = ["resource-run", "--cwd", str(self.root), "--timeout", "5", "--output", str(path), "--", *self.command]
        with (mock.patch.object(sys, "argv", argv), mock.patch.object(observer, "observe_resources") as run,
              redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit):
                observer.main()
            run.assert_not_called()


def delegated_parent():
    requested = os.environ.get("PT_BENCH_CGROUP_PARENT")
    if requested:
        return Path(requested)
    if sys.platform != "linux":
        return None
    try:
        path = Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1].lstrip("/")
        for parent in (path, *path.parents):
            if (parent.stat().st_uid == os.geteuid() and os.access(parent, os.W_OK)
                    and "memory" in (parent / "cgroup.subtree_control").read_text().split()):
                return parent
    except (OSError, IndexError):
        return None
    return None


@unittest.skipUnless(sys.platform == "linux", "native resource checks require Linux cgroup v2")
class NativeResourceAccountingTests(unittest.TestCase):
    def setUp(self):
        self.parent = delegated_parent()
        if self.parent is None:
            self.skipTest("no writable delegated memory-enabled parent; no privileged reconfiguration attempted")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.probe = HARNESS / "tests/fixtures/resource_probe.py"

    def run_probe(self, mode, *, allow_missing_peak=True):
        record = observer.observe_resources([sys.executable, str(self.probe), str(self.root), mode], self.root, 15,
                                            cgroup_parent=self.parent, allow_missing_peak=allow_missing_peak,
                                            cleanup_grace=0.05)
        if not record["run_attempted"]:
            if record["status"] == "unsupported":
                self.skipTest(f"native capability unavailable: {record['capabilities']}")
            self.fail(f"native resource setup failed, not an unsupported skip: {record['errors']}")
        return record

    def test_missing_native_peak_is_explicit_and_strict_mode_starts_no_subject(self):
        marker = self.root / "ran"
        record = observer.observe_resources([sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
                                            self.root, 5, cgroup_parent=self.parent)
        if record["group"] is None:
            self.assertEqual(record["status"], "unsupported", record["errors"])
            self.skipTest(f"native delegated group unavailable: {record['capabilities']}")
        if not record["capabilities"]["memory_peak"]["supported"]:
            self.assertEqual(record["status"], "unsupported")
            self.assertFalse(marker.exists())
            self.assertIsNone(record["peak_charged_bytes"])
            self.assertIsNone(record["cpu_delta_usec"])
        elif record["status"] == "unsupported":
            self.skipTest(f"unrelated native capability unavailable: {record['capabilities']}")
        else:
            self.assertEqual(record["status"], "observed_unqualified")
            self.assertTrue(marker.exists())
        self.assertTrue(record["group"]["removed"])

    def test_native_descendant_cpu_and_memory_are_observed_not_just_the_leader(self):
        record = self.run_probe("cooperative")
        sentinel = json.loads((self.root / "worker-0.json").read_text())
        self.assertGreaterEqual(sentinel["cpu_ns"], 200_000_000)
        self.assertGreaterEqual(record["cpu_delta_usec"]["usage_usec"], 150_000)
        self.assertGreaterEqual(record["sampled_current_max_bytes"], 48 * 1024 * 1024)
        self.assertEqual(record["snapshots"]["final"]["population"], 0)
        self.assertTrue(record["group"]["removed"])
        self.assertFalse(record["cleanup"]["kill_requested"])
        if not record["capabilities"]["memory_peak"]["supported"]:
            self.assertEqual(record["status"], "partial_unsupported")
            self.assertIsNone(record["peak_charged_bytes"])
            self.assertFalse(record["whole_boundary_accounting_complete"])
        else:
            self.assertEqual(record["status"], "observed_unqualified")
            self.assertGreaterEqual(record["peak_charged_bytes"], record["sampled_current_max_bytes"])

    def test_native_detached_worker_with_closed_pipes_is_counted_killed_and_failed(self):
        record = self.run_probe("detached")
        self.assertEqual(record["process"]["returncode"], 0)
        self.assertEqual(record["status"], "failed")
        self.assertIn("background_work_outlived_command", record["failure_reasons"])
        self.assertGreaterEqual(record["cpu_delta_usec"]["usage_usec"], 150_000)
        self.assertGreaterEqual(record["sampled_current_max_bytes"], 48 * 1024 * 1024)
        self.assertTrue(record["cleanup"]["kill_requested"])
        self.assertEqual(record["snapshots"]["final"]["population"], 0)
        self.assertTrue(record["group"]["removed"])
        self.assertFalse(Path(record["group"]["path"]).exists())

    def test_native_nested_cgroup_worker_cannot_disappear_from_population_or_cleanup(self):
        record = self.run_probe("subgroup_detached")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["process"]["returncode"], 0)
        self.assertGreaterEqual(record["cpu_delta_usec"]["usage_usec"], 150_000)
        self.assertGreaterEqual(record["sampled_current_max_bytes"], 48 * 1024 * 1024)
        self.assertTrue(record["cleanup"]["residual_at_command_return"])
        self.assertTrue(record["cleanup"]["kill_requested"])
        self.assertTrue(record["group"]["removed"])
        self.assertFalse(Path(record["group"]["path"]).exists())

    def test_native_enrollment_preserves_subject_argv_cwd_environment_and_closes_control_fds(self):
        code = ("import json,os,sys; print(json.dumps([sys.argv[1:], os.getcwd(), "
                "os.environ['PT_RESOURCE_FIXTURE_VALUE'], "
                "[os.readlink('/proc/self/fd/'+f) for f in os.listdir('/proc/self/fd') "
                "if f.isdigit() and int(f)>2 and os.path.exists('/proc/self/fd/'+f)]]))")
        command = [sys.executable, "-c", code, "with space", "", "\u03bb"]
        with mock.patch.dict(os.environ, {"PT_RESOURCE_FIXTURE_VALUE": "fixture-only"}):
            record = observer.observe_resources(command, self.root, 5, cgroup_parent=self.parent, allow_missing_peak=True)
        if not record["run_attempted"]:
            if record["status"] == "unsupported":
                self.skipTest(f"native capability unavailable: {record['capabilities']}")
            self.fail(f"native resource setup failed, not an unsupported skip: {record['errors']}")
        expected = (json.dumps([["with space", "", "\u03bb"], str(self.root), "fixture-only", []]) + "\n").encode()
        self.assertEqual(record["process"]["returncode"], 0)
        self.assertEqual(record["process"]["stdout_sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(record["process"]["stdout_bytes"], len(expected))
        self.assertEqual(record["enrollment"]["status"], "confirmed")

    def test_native_peak_is_a_whole_group_maximum_not_sum_of_sequential_child_maxima(self):
        record = self.run_probe("sequential", allow_missing_peak=False)
        for index in (0, 1):
            self.assertEqual(json.loads((self.root / f"worker-{index}.json").read_text())["allocated_bytes"], 80 * 1024 * 1024)
        self.assertGreaterEqual(record["peak_charged_bytes"], 72 * 1024 * 1024)
        self.assertLess(record["peak_charged_bytes"], 145 * 1024 * 1024)
        self.assertEqual(record["status"], "observed_unqualified")

    def test_native_record_cli_inspects_saved_counters_and_refuses_missing_fields(self):
        record = self.run_probe("cooperative")
        path = self.root / "resource.json"
        observer.publish_resource_record(path, record)
        command = [sys.executable, str(HARNESS / "inspect_resources.py"), str(path)]
        checked = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertFalse(json.loads(checked.stdout)["confirmatory_eligible"])
        del record["cpu_delta_usec"]
        path.write_text(json.dumps(record))
        checked = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 2)
        self.assertIn("resource schema", checked.stderr)
        self.assertNotIn("Traceback", checked.stderr)


if __name__ == "__main__":
    unittest.main()
