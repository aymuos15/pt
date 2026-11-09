"""Independent, opt-in cgroup resource pass; never a performance/conformance claim."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from cgroup_accounting import (
    CAPABILITIES, CPU_KEYS, MAX_SAMPLES, CgroupDirectory, CurrentMemorySampler,
    capabilities, counters, delta, snapshot,
)
from evidence import StrictValidator, validate_json_types
from finalization import MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, inspect_file
from metadata import collect_metadata
import pt_bench as timer


ENDPOINT = timer.RESOURCE_ENDPOINT
SCOPE = "subject_exec_and_all_future_inheriting_cgroup_descendants"
MEMORY_METRIC = "cgroup_v2_charged_memory_not_rss_or_pss"
LAUNCHER = Path(__file__).resolve().with_name("cgroup_exec.py")
LIMITATIONS = [
    "diagnostic resource pass, not primary paired latency or semantic qualification",
    "shared/precharged memory can be charged elsewhere; kernel charged memory is not total physical ownership",
    "external pre-existing processes and cgroup escapes are unsupported; caller-owned non-hostile delegation only",
    "harness and launcher bootstrap excluded; post-enrollment launcher overhead included without subtraction",
    "no resource-budget, source, equal-work, authenticity or power-loss-durability qualification",
    "observer record publication is outside the resource lifecycle interval",
]


@lru_cache(maxsize=1)
def _validator():
    root = Path(__file__).resolve().parent
    schemas = [json.loads((root / name).read_text()) for name in
               ("resource-observation-v1.schema.json", "lifecycle-v2.schema.json")]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return StrictValidator(schemas[0], registry=registry)


def _shape(record):
    validate_json_types(record)
    error = next(_validator().iter_errors(record), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"resource schema at {path}: violates {error.validator}")


def _required(record):
    return [key for key in CAPABILITIES if key != "memory_peak" or not record["configuration"]["allow_missing_peak"]]


def _fresh(initial):
    return (initial is not None and initial["population"] == 0
            and all(initial[key] in (None, 0) for key in ("memory_current", "memory_peak"))
            and (initial["cpu_stat"] is None or all(initial["cpu_stat"][key] == 0 for key in CPU_KEYS))
            and (initial["memory_events"] is None or all(value == 0 for value in initial["memory_events"].values())))


def _counter_delta(record, field, keys):
    snapshots = [record["snapshots"][key] for key in ("initial", "command_return", "final")]
    values = [value[field] for value in snapshots if value is not None and value[field] is not None]
    for left, right in zip(values, values[1:]):
        delta(left, right, keys)
    first, last = record["snapshots"]["initial"], record["snapshots"]["final"]
    return delta(first[field], last[field], keys)


def _peak(record):
    snapshots = [record["snapshots"][key] for key in ("initial", "command_return", "final")]
    values = [value["memory_peak"] for value in snapshots
              if value is not None and value["memory_peak"] is not None]
    if any(right < left for left, right in zip(values, values[1:])):
        raise ValueError("kernel memory.peak decreased")
    peak = record["snapshots"]["final"]["memory_peak"]
    if peak is not None and record["sampled_current_max_bytes"] is not None and peak < record["sampled_current_max_bytes"]:
        raise ValueError("memory.peak is below observed current memory")
    return peak


def _failures(record):
    reasons = []
    attempted = record["run_attempted"]
    first, last = record["snapshots"]["initial"], record["snapshots"]["final"]
    if first is not None and (first["population"] == 1
            or any(first[key] not in (None, 0) for key in ("memory_current", "memory_peak"))
            or any((first["cpu_stat"] or {}).get(key, 0) != 0 for key in CPU_KEYS)
            or any((first["memory_events"] or {}).values())):
        reasons.append("boundary_not_fresh")
    if record["group"] is not None and not record["group"]["removed"]:
        reasons.append("group_not_removed")
    if record["cleanup"]["kill_requested"]:
        reasons.append("forced_boundary_termination")
    if attempted:
        result = record["process"]
        if result is None:
            reasons.append("measurement_not_observed")
        elif (result["status"] != "exited_unqualified" or not result.get("process_reaped")
              or not result.get("output_complete")):
            reasons.append("process_incomplete")
        if record["enrollment"]["status"] != "confirmed":
            reasons.append("subject_enrollment_or_exec_unconfirmed")
        if record["cleanup"]["residual_at_command_return"] is True:
            reasons.append("background_work_outlived_command")
        if last is None or last["population"] != 0:
            reasons.append("boundary_not_empty")
        if record["cpu_delta_usec"] is None:
            reasons.append("cpu_accounting_incomplete")
        if record["capabilities"]["memory_peak"]["supported"] and record["peak_charged_bytes"] is None:
            reasons.append("peak_accounting_incomplete")
        events = record["memory_events_delta"]
        if events and any(events.get(key, 0) for key in ("oom", "oom_kill", "oom_group_kill")):
            reasons.append("oom_observed")
    if record["sampling"]["truncated"]:
        reasons.append("sampling_truncated")
    return sorted(reasons)


def _status(record):
    if record["errors"] or _failures(record):
        return "failed"
    if not record["run_attempted"]:
        return "unsupported"
    return ("observed_unqualified" if all(item["supported"] for item in record["capabilities"].values())
            else "partial_unsupported")


def _derive(record):
    first, last = record["snapshots"]["initial"], record["snapshots"]["final"]
    readings = [item["memory_current_bytes"] for item in record["sampling"]["observations"]]
    readings.extend(value["memory_current"] for value in record["snapshots"].values()
                    if record["run_attempted"] and value is not None and value["memory_current"] is not None)
    record["sampled_current_max_bytes"] = max(readings) if readings else None
    if record["run_attempted"] and first is not None and last is not None:
        keys = sorted(set(first["memory_events"] or {}) | set(last["memory_events"] or {}))
        for field, calculate in (
            ("cpu_delta_usec", lambda: _counter_delta(record, "cpu_stat", CPU_KEYS)),
            ("memory_events_delta", lambda: _counter_delta(record, "memory_events", keys)),
            ("peak_charged_bytes", lambda: _peak(record)),
        ):
            try:
                record[field] = calculate()
            except ValueError as exc:
                record["errors"].append({"stage": "derivation", "error": str(exc)})
    record["failure_reasons"] = _failures(record)
    record["status"] = _status(record)
    record["whole_boundary_accounting_complete"] = record["status"] == "observed_unqualified"


def _control(raw):
    if raw == b"enrolled\n":
        return {"status": "confirmed", "control": raw.decode("ascii")}
    return {"status": "failed", "control": raw.decode("ascii", errors="replace")}


def _settle(group, record):
    """One recursive kill if needed; bounded observation, no replay or kill retries."""
    if not record["run_attempted"]:
        return
    returned = record["snapshots"]["command_return"]
    populated = returned["population"] if returned is not None else None
    record["cleanup"]["residual_at_command_return"] = None if populated is None else populated == 1
    deadline = time.monotonic_ns() + record["configuration"]["cleanup_grace_ns"]
    try:
        while populated == 1 and time.monotonic_ns() < deadline:
            time.sleep(0.01)
            populated = counters(group.read("cgroup.events"), ("populated",))["populated"]
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        populated = None
        record["errors"].append({"stage": "cleanup", "error": f"{type(exc).__name__}: {exc}"})
    if populated != 0:
        record["cleanup"]["kill_requested"] = True
        try:
            group.kill()
            deadline = time.monotonic() + 2
            while counters(group.read("cgroup.events"), ("populated",))["populated"] != 0:
                if time.monotonic() >= deadline:
                    raise ValueError("cgroup remained populated after kill deadline; group retained")
                time.sleep(0.01)
        except (OSError, ValueError, KeyboardInterrupt) as exc:
            record["errors"].append({"stage": "cleanup", "error": f"{type(exc).__name__}: {exc}"})


def validate_settings(timeout, allow_missing_peak, sample_interval, cleanup_grace):
    """Shared pre-work validation for standalone and paired diagnostic requests."""
    for name, value, low, high in (("timeout", timeout, 0, 86400), ("sample interval", sample_interval, 0.001, 1),
                                   ("cleanup grace", cleanup_grace, 0, 10)):
        if (type(value) not in (int, float) or not math.isfinite(value)
                or value < low or value > high or (name == "timeout" and value == 0)):
            raise ValueError(f"invalid resource {name}")
    if type(allow_missing_peak) is not bool:
        raise ValueError("allow_missing_peak must be a boolean")


def observe_resources(argv, cwd, timeout, *, cgroup_parent=None, allow_missing_peak=False,
                      sample_interval=0.02, cleanup_grace=0.1):
    """Observe exactly one fresh invocation/session; never silently downgrade peak.

    The subject is exec'd only after isolated enrollment, with its environment
    unchanged. An already-running daemon/service cannot be adopted into this scope.
    """
    start = time.monotonic_ns()
    if (not isinstance(argv, list) or not argv or not argv[0]
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
            or len(json.dumps(argv).encode()) > MAX_RECORD_BYTES):
        raise ValueError("resource command must be a bounded nonempty argv of strings")
    validate_settings(timeout, allow_missing_peak, sample_interval, cleanup_grace)
    root = Path(cwd).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("resource cwd must be a directory")
    parent = str(Path(os.path.abspath(cgroup_parent))) if cgroup_parent is not None else None
    record = {
        "schema_version": 1, "kind": "cgroup_resource_observation", "mode": "exploratory_unqualified",
        "confirmatory_eligible": False, "endpoint": ENDPOINT, "scope": SCOPE, "memory_metric": MEMORY_METRIC,
        "configuration": {"argv": argv.copy(), "cwd": str(root), "timeout_seconds": timeout,
                          "cgroup_parent": parent, "allow_missing_peak": allow_missing_peak,
                          "sample_interval_ns": round(sample_interval * 1_000_000_000),
                          "cleanup_grace_ns": round(cleanup_grace * 1_000_000_000)},
        "launcher": {"path": str(LAUNCHER), "sha256": hashlib.sha256(LAUNCHER.read_bytes()).hexdigest()},
        "host_metadata": collect_metadata(), "group": None,
        "capabilities": {key: {"supported": False, "reason": "not probed"} for key in CAPABILITIES},
        "run_attempted": False, "process": None, "enrollment": {"status": "not_started", "control": None},
        "snapshots": {key: None for key in ("initial", "command_return", "final")},
        "sampling": {"interval_ns": round(sample_interval * 1_000_000_000), "observations": [], "truncated": False},
        "cleanup": {"residual_at_command_return": None, "kill_requested": False},
        "cpu_delta_usec": None, "peak_charged_bytes": None, "sampled_current_max_bytes": None,
        "memory_events_delta": None, "errors": [], "failure_reasons": [], "limitations": LIMITATIONS.copy(),
    }
    group = sampler = None
    descriptors = []
    try:
        try:
            group = CgroupDirectory(parent)
        except (OSError, ValueError) as exc:
            record["capabilities"] = {key: {"supported": False, "reason": f"{type(exc).__name__}: {exc}"}
                                      for key in CAPABILITIES}
        if group is not None:
            record["group"] = {"path": str(group.path), "identity": group.identity, "removed": False}
            record["capabilities"] = capabilities(group)
            if any(name.startswith("LD_") or name == "GLIBC_TUNABLES" for name in os.environ):
                # Do not load project-supplied dynamic-loader code in the observer
                # bootstrap before enrollment, or silently strip it from the subject.
                record["capabilities"]["enrollment"] = {
                    "supported": False,
                    "reason": "dynamic-loader environment is outside the isolated pre-exec enrollment profile",
                }
            record["snapshots"]["initial"] = snapshot(group, record["capabilities"], record["errors"], "initial")
            if (not record["errors"] and _fresh(record["snapshots"]["initial"])
                    and all(record["capabilities"][key]["supported"] for key in _required(record))):
                procs = group.open("cgroup.procs", write=True)
                descriptors.append(procs)
                read_fd, control_fd = os.pipe()
                descriptors.extend((read_fd, control_fd))
                os.set_blocking(read_fd, False)
                sampler = CurrentMemorySampler(group, record["configuration"]["sample_interval_ns"])
                sampler.start()
                record["run_attempted"] = True
                command = [sys.executable, "-I", "-S", str(LAUNCHER), str(procs), str(control_fd), "--", *argv]
                try:
                    record["process"] = timer.measure(command, str(root), timeout, _pass_fds=(procs, control_fd))
                except (OSError, ValueError, KeyboardInterrupt) as exc:
                    record["errors"].append({"stage": "measurement", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    for fd in (procs, control_fd):
                        os.close(fd)
                        descriptors.remove(fd)
                raw = bytearray()
                while len(raw) <= 512:
                    try:
                        chunk = os.read(read_fd, 513 - len(raw))
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    raw.extend(chunk)
                if len(raw) > 512:
                    raise ValueError("oversized enrollment control message")
                record["enrollment"] = _control(bytes(raw))
    except (OSError, ValueError, RuntimeError) as exc:
        record["errors"].append({"stage": "setup_or_control", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        for fd in descriptors:
            os.close(fd)
        if group is not None:
            try:
                if record["run_attempted"]:
                    record["snapshots"]["command_return"] = snapshot(group, record["capabilities"], record["errors"], "command_return")
                _settle(group, record)
            finally:
                if sampler is not None:
                    record["sampling"] = sampler.stop()
                    record["errors"].extend(sampler.errors)
                record["snapshots"]["final"] = snapshot(group, record["capabilities"], record["errors"], "final")
                try:
                    group.remove()
                    record["group"]["removed"] = True
                except (OSError, ValueError) as exc:
                    record["errors"].append({"stage": "cleanup", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    group.close()
    _derive(record)
    record["clock"] = timer._timing(start)
    inspect_resource_record(record)
    return record


def inspect_resource_record(record):
    """Historical type/arithmetic/scope consistency, never authenticate the kernel."""
    _shape(record)
    if (record["endpoint"] != ENDPOINT or record["scope"] != SCOPE or record["memory_metric"] != MEMORY_METRIC
            or record["limitations"] != LIMITATIONS):
        raise ValueError("unsupported resource endpoint, scope, metric or limitations")
    clock = record["clock"]

    def interval(value):
        start, end = value["monotonic_start_ns"], value["monotonic_end_ns"]
        if end < start or start < clock["monotonic_start_ns"] or end > clock["monotonic_end_ns"]:
            raise ValueError("resource interval is inconsistent or outside observation")

    interval(clock)
    if clock["elapsed_ns"] != clock["monotonic_end_ns"] - clock["monotonic_start_ns"]:
        raise ValueError("resource elapsed time is inconsistent")
    for name, value in record["snapshots"].items():
        if value is None:
            continue
        interval(value)
        for key in ("cpu_stat", "memory_current", "memory_peak", "memory_events", "population"):
            if value[key] is not None and not record["capabilities"][key]["supported"]:
                raise ValueError("unsupported resource capability contains a counter")
            if value[key] is None and record["capabilities"][key]["supported"] and not any(item["stage"] == name for item in record["errors"]):
                raise ValueError("missing resource counter without read failure evidence")
    first, returned, last = (record["snapshots"][key] for key in ("initial", "command_return", "final"))
    present = [value for value in (first, returned, last) if value is not None]
    if any(right["monotonic_start_ns"] < left["monotonic_end_ns"] for left, right in zip(present, present[1:])):
        raise ValueError("resource snapshots overlap or are out of order")
    if record["group"] is None and present:
        raise ValueError("resource snapshots without an owned group")
    if record["group"] is not None:
        path = Path(record["group"]["path"])
        parent = record["configuration"]["cgroup_parent"]
        if parent is None or path.parent != Path(parent) or re.fullmatch(r"pt-bench-[0-9a-f]{32}", path.name) is None:
            raise ValueError("owned resource group is not a private child of the declared parent")
    attempted, process = record["run_attempted"], record["process"]
    if not attempted:
        if (process is not None or returned is not None or record["enrollment"] != {"status": "not_started", "control": None}
                or record["cpu_delta_usec"] is not None or record["peak_charged_bytes"] is not None
                or record["memory_events_delta"] is not None or record["sampling"]["observations"]):
            raise ValueError("unsupported/non-invoked resource record invents observations")
        if not record["errors"] and all(record["capabilities"][key]["supported"] for key in _required(record)) and _fresh(first):
            raise ValueError("resource run omitted without unsupported capability or failure")
    else:
        if first is None or last is None or returned is None:
            raise ValueError("resource invocation is missing boundary snapshots")
        if not _fresh(first):
            raise ValueError("resource work began with an unverified or non-fresh boundary")
        if any(not record["capabilities"][key]["supported"] for key in _required(record)):
            raise ValueError("resource work ran despite required unsupported capabilities")
        if record["cleanup"]["residual_at_command_return"] != (None if returned["population"] is None else returned["population"] == 1):
            raise ValueError("resource residual-work flag contradicts cgroup population")
        if record["enrollment"]["status"] == "confirmed" and record["enrollment"]["control"] != "enrolled\n":
            raise ValueError("resource enrollment is not confirmed by control evidence")
        if process is not None:
            interval(process)
            if (process["elapsed_ns"] != process["monotonic_end_ns"] - process["monotonic_start_ns"]
                    or process["cwd"] != record["configuration"]["cwd"]
                    or process["argv"][:4] != [record["host_metadata"]["harness_python_executable"], "-I", "-S", record["launcher"]["path"]]
                    or process["argv"][6:] != ["--", *record["configuration"]["argv"]]
                    or process["monotonic_start_ns"] < first["monotonic_end_ns"]
                    or process["monotonic_end_ns"] > returned["monotonic_start_ns"]):
                raise ValueError("resource process differs from command, enrollment profile or interval")
            if any(re.fullmatch(r"[0-9]+", value) is None for value in process["argv"][4:6]) or process["argv"][4] == process["argv"][5]:
                raise ValueError("invalid private enrollment descriptor arguments")
        keys = sorted(set(first["memory_events"] or {}) | set(last["memory_events"] or {}))
        for field, calculate in (
            ("cpu_delta_usec", lambda: _counter_delta(record, "cpu_stat", CPU_KEYS)),
            ("memory_events_delta", lambda: _counter_delta(record, "memory_events", keys)),
            ("peak_charged_bytes", lambda: _peak(record)),
        ):
            try:
                expected = calculate()
            except ValueError:
                if record[field] is not None or not any(item["stage"] == "derivation" for item in record["errors"]):
                    raise ValueError("invalid resource counters without failure evidence")
            else:
                if not timer._same_json(expected, record[field]):
                    raise ValueError("resource metrics contradict raw kernel snapshots")
    if record["sampling"]["interval_ns"] != record["configuration"]["sample_interval_ns"]:
        raise ValueError("resource sampling interval differs from request")
    prior_end, readings = None, []
    for sample in record["sampling"]["observations"]:
        interval(sample)
        if first is None or last is None or sample["monotonic_start_ns"] < first["monotonic_end_ns"] or sample["monotonic_end_ns"] > last["monotonic_start_ns"]:
            raise ValueError("resource sample is outside the counter interval")
        if prior_end is not None and sample["monotonic_start_ns"] < prior_end:
            raise ValueError("resource memory samples overlap or are out of order")
        prior_end = sample["monotonic_end_ns"]
        readings.append(sample["memory_current_bytes"])
    readings.extend(value["memory_current"] for value in present if attempted and value["memory_current"] is not None)
    if record["sampled_current_max_bytes"] != (max(readings) if readings else None):
        raise ValueError("sampled current-memory maximum contradicts raw readings")
    if (record["peak_charged_bytes"] is not None and readings and record["peak_charged_bytes"] < max(readings)
            and not any(item["stage"] == "derivation" for item in record["errors"])):
        raise ValueError("kernel peak is below observed current memory without failure evidence")
    if (record["status"] != _status(record) or record["failure_reasons"] != _failures(record)
            or record["whole_boundary_accounting_complete"] != (record["status"] == "observed_unqualified")):
        raise ValueError("resource status conflicts with capabilities, failures or incomplete accounting")
    return {"record_consistency": "checked_unqualified", "status": record["status"], "run_attempted": attempted,
            "scope": SCOPE, "memory_metric": MEMORY_METRIC,
            "whole_boundary_accounting_complete": record["whole_boundary_accounting_complete"],
            "cpu_delta_usec": record["cpu_delta_usec"], "peak_charged_bytes": record["peak_charged_bytes"],
            "sampled_current_max_bytes": record["sampled_current_max_bytes"],
            "unsupported_capabilities": {key: value["reason"] for key, value in record["capabilities"].items() if not value["supported"]},
            "failure_reasons": record["failure_reasons"], "confirmatory_eligible": False}


def publish_resource_record(path, record):
    inspect_resource_record(record)
    raw = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("resource observer record exceeds byte limit; observation unconfirmed")
    timer.write_record(str(path), record)
    observed, _ = inspect_file(path.parent, path.name, limit=len(raw))
    if observed["bytes"] != len(raw) or observed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("resource observer publication did not commit expected bytes")
    return {"name": path.name, "bytes": observed["bytes"], "sha256": observed["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private JSON resource observation")
    parser.add_argument("--cgroup-parent", type=Path, help="explicit existing delegated cgroup-v2 parent; never reconfigured")
    parser.add_argument("--allow-missing-peak", action="store_true", help="explicit partial diagnostic; never invent a memory peak")
    parser.add_argument("--sample-interval", type=float, default=0.02)
    parser.add_argument("--cleanup-grace", type=float, default=0.1)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        if os.path.lexists(args.output):
            raise FileExistsError("resource output already exists; refusing execution")
        fd = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
        record = observe_resources(command, args.cwd, args.timeout, cgroup_parent=args.cgroup_parent,
                                   allow_missing_peak=args.allow_missing_peak, sample_interval=args.sample_interval,
                                   cleanup_grace=args.cleanup_grace)
        publish_resource_record(args.output, record)
    except (AttributeError, OSError, ValueError) as exc:
        parser.exit(2, f"resource-run: {exc}\n")
    print(json.dumps({"output": str(args.output), **inspect_resource_record(record)}, sort_keys=True))
    if record["status"] == "unsupported":
        return 3
    if record["status"] == "failed":
        return 2
    return 0 if record["whole_boundary_accounting_complete"] and record["process"]["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
