"""Opt-in fresh-cgroup diagnostics for one entire managed replay, never latency samples."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
import finalization as files
import managed_replay as replay
import pt_bench as timer
import resource_run as resources
from result_card import capture_run, _inventory


HARNESS = Path(__file__).resolve().parent
DRIVER = HARNESS / "replay_resource_driver.py"
SCOPE = "fresh_cgroup_replay_driver_and_all_future_inheriting_descendants"
OVERHEAD = "driver_bootstrap_replay_and_receipt_publication_included_outer_observer_excluded_no_subtraction"
CLOCK_ALIGNMENT = "distinct_process_domains_no_cross_process_arithmetic"
WATCHDOG_SLACK_SECONDS = 5
MAX_EVIDENCE_FILES = 4096
MAX_EVIDENCE_BYTES = files.MAX_TOTAL_BYTES
LIMITATIONS = [
    "one separate diagnostic replay, never a rerun or resource relabelling of a retained latency observation",
    "one fresh cgroup includes driver bootstrap, preparation, idle/background descendants, interactions, shutdown and driver reporting",
    "outer counter observer, sampler and resource-record publication are outside cgroup CPU/memory totals; no overhead is subtracted",
    "driver and outer observer clocks have distinct process provenance; no cross-process timestamp arithmetic is assumed",
    "the outer watchdog or cancellation can interrupt reserved shutdown; missing receipts leave work and cleanup unknown",
    "pre-existing services, cgroup escapes and precharged/shared memory outside the group are unsupported",
    "charged-memory peak is not RSS/PSS; sampled current-memory maximum never substitutes for missing memory.peak",
    "whole-session counters do not isolate idle-only costs or qualify resource budgets, resets, equal work, generations or independence",
    "historical byte bindings and clocks are unauthenticated; fingerprint checks are not an atomic or hostile-path boundary",
    "post-endpoint receipt construction and transport are observer work; no power-loss-durability or confirmatory claim",
]
FAILURES = (OSError, ValueError, RuntimeError, KeyboardInterrupt)


@lru_cache(maxsize=1)
def _validators():
    schemas = [json.loads((HARNESS / name).read_text()) for name in (
        "replay-resource-v1.schema.json", "managed-replay-v1.schema.json", "resource-observation-v1.schema.json",
        "lifecycle-v2.schema.json", "result-card-v1.schema.json", "paired-resource-v1.schema.json",
    )]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry)
            for kind in ("request", "driver", "receipt")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"replay resource {kind} schema at {path}: violates {error.validator}")
    if kind == "driver" and value["receipt"] is not None:
        replay.validate("receipt", value["receipt"])
    if kind == "receipt" and value["diagnostic_resource"] is not None:
        resources.inspect_resource_record(value["diagnostic_resource"])


def _raw(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _binding(name, metadata):
    return {"name": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]}


def _publish(path, value, kind):
    validate(kind, value)
    raw = _raw(value)
    limit = files.MAX_RECORD_BYTES if kind == "request" else files.MAX_RECEIPT_BYTES
    if len(raw) > limit:
        raise ValueError("replay resource record exceeds byte limit; no evidence may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=len(raw))
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("replay resource publication did not commit expected bytes")
    return _binding(path.name, metadata)


def process_clock():
    clock = time.get_clock_info("monotonic")
    return {"pid": os.getpid(), "implementation": clock.implementation, "resolution_ns": max(1, round(clock.resolution * 1e9)),
            "monotonic": clock.monotonic, "adjustable": clock.adjustable}


def validate_request(request):
    validate("request", request)
    replay.validate_plan(request["replay_plan"])
    options = request["configuration"]
    resources.validate_settings(options["outer_timeout_seconds"], options["allow_missing_peak"],
                                options["sample_interval_ns"] / 1e9, options["cleanup_grace_ns"] / 1e9)
    minimum = request["replay_plan"]["execution_timeout_seconds"] + request["replay_plan"]["shutdown"]["timeout_seconds"] + WATCHDOG_SLACK_SECONDS
    if options["outer_timeout_seconds"] < minimum:
        raise ValueError("outer watchdog must cover execution budget, reserved shutdown and five seconds of driver slack")
    if request["limitations"] != LIMITATIONS or re.fullmatch(r"[0-9a-f]{32}", request["invocation_id"]) is None:
        raise ValueError("replay resource request limitations or invocation identity differ")
    if len(_raw(request)) > files.MAX_RECORD_BYTES:
        raise ValueError("replay resource request exceeds byte limit")


def _command(request, binding):
    return [request["driver"]["python_executable"], "-I", request["driver"]["path"], "--root", request["output_root"],
            "--request-sha256", binding["sha256"]]


def _transport(request, driver_binding):
    return (f"pt-replay-resource-driver-v1 {request['invocation_id']} {driver_binding['sha256']}\n").encode("ascii")


def _exit_code(driver):
    if driver["error"] is not None or driver["receipt"]["outcome"]["infrastructure_failure"]:
        return 2
    return 0 if driver["receipt"]["outcome"]["status"] == "completed_unqualified" else 1


def _capture(output):
    """Only fixed root records and one managed session; every diagnostic byte is bound."""
    files.require_safe_lookup()
    fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = files._fingerprint(os.fstat(fd))
        entries, identities, directories, total = [], {"/": identity}, [], 0
        with os.scandir(fd) as scanned:
            for entry in scanned:
                if entry.name in ("request.json", "resource.json", "driver.json") and entry.is_file(follow_symlinks=False):
                    metadata, _ = files.inspect_file(output, entry.name, limit=files.MAX_RECEIPT_BYTES)
                    entries.append({"path": entry.name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]})
                    identities[entry.name] = metadata["identity"]
                    total += metadata["bytes"]
                elif entry.name == "session" and entry.is_dir(follow_symlinks=False):
                    inventory, nested = capture_run(output / "session")
                    directories.extend(["session", *["session/" + path for path in inventory["directories"]]])
                    entries.extend({**item, "path": "session/" + item["path"]} for item in inventory["files"])
                    identities["session/"] = nested
                    total += inventory["total_bytes"]
                else:
                    raise ValueError("unexpected or nonregular replay resource evidence")
                if len(entries) > MAX_EVIDENCE_FILES or total > MAX_EVIDENCE_BYTES:
                    raise ValueError("replay resource evidence exceeds aggregate file/byte limit")
        named = os.stat(output, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode) or files._fingerprint(named) != identity
                or files._fingerprint(os.fstat(fd)) != identity):
            raise ValueError("replay resource evidence changed during read")
        return _inventory(directories, entries), identities
    finally:
        os.close(fd)


def run_observation(output, requested, outer_timeout, *, cgroup_parent=None, allow_missing_peak=False,
                    sample_interval=0.02, cleanup_grace=0.1):
    start, provenance = time.monotonic_ns(), process_clock()
    files.require_safe_lookup()
    replay.validate_plan(requested)
    resources.validate_settings(outer_timeout, allow_missing_peak, sample_interval, cleanup_grace)
    plan = copy.deepcopy(requested)
    plan["cwd"] = str(Path(plan["cwd"]).resolve(strict=True))
    fd = os.open(plan["cwd"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    output = Path(os.path.abspath(output))
    fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    request = {"schema_version": 1, "kind": "managed_replay_resource_request", "mode": "exploratory_unqualified",
               "invocation_id": uuid.uuid4().hex, "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT,
               "resource_endpoint": resources.ENDPOINT, "replay_endpoint": replay.ENDPOINT, "scope": SCOPE, "overhead_policy": OVERHEAD,
               "output_root": str(output), "replay_plan": plan,
               "driver": {"path": str(DRIVER), "sha256": hashlib.sha256(DRIVER.read_bytes()).hexdigest(), "python_executable": sys.executable},
               "configuration": {"outer_timeout_seconds": outer_timeout, "cgroup_parent": str(Path(os.path.abspath(cgroup_parent))) if cgroup_parent is not None else None,
                                 "allow_missing_peak": allow_missing_peak, "sample_interval_ns": round(sample_interval * 1e9),
                                 "cleanup_grace_ns": round(cleanup_grace * 1e9)}, "limitations": LIMITATIONS.copy()}
    validate_request(request)
    output.mkdir(mode=0o700)
    binding = _publish(output / "request.json", request, "request")
    resource, resource_binding, errors = None, None, []
    try:
        resource = resources.observe_resources(_command(request, binding), plan["cwd"], outer_timeout,
                                               cgroup_parent=cgroup_parent, allow_missing_peak=allow_missing_peak,
                                               sample_interval=sample_interval, cleanup_grace=cleanup_grace)
    except FAILURES as exc:
        errors.append({"stage": "resource_observation", "error": f"{type(exc).__name__}: {exc}"})
    if resource is not None:
        try:
            resource_binding = resources.publish_resource_record(output / "resource.json", resource)
        except FAILURES as exc:
            errors.append({"stage": "resource_publication", "error": f"{type(exc).__name__}: {exc}"})
    inventory, identities = _capture(output)
    driver_binding = next((_binding("driver.json", item) for item in inventory["files"] if item["path"] == "driver.json"), None)
    receipt = {"schema_version": 1, "kind": "managed_replay_resource_receipt", "mode": "exploratory_unqualified",
               "confirmatory_eligible": False, "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT,
               "request": binding, "resource": resource_binding, "diagnostic_resource": resource if resource_binding is None else None,
               "driver": driver_binding, "retained_inputs": inventory, "observer_process": provenance,
               "clock_alignment": CLOCK_ALIGNMENT, "observer_clock": timer._timing(start), "errors": errors,
               "limitations": LIMITATIONS.copy()}
    validate("receipt", receipt)
    if len(_raw(receipt)) > files.MAX_RECEIPT_BYTES:
        raise ValueError("replay resource receipt exceeds byte limit; no evidence may be truncated")
    inspect_observation(output, receipt)
    if _capture(output) != (inventory, identities):
        raise ValueError("replay resource evidence changed before receipt return")
    return receipt


def driver_main(output, expected_sha256):
    """Called only by the trusted isolated driver, after cgroup enrollment and exec."""
    request, metadata = files.read_json(output / "request.json")
    validate_request(request)
    if (metadata["sha256"] != expected_sha256 or str(output) != request["output_root"]
            or hashlib.sha256(DRIVER.read_bytes()).hexdigest() != request["driver"]["sha256"]):
        raise ValueError("replay resource driver request or source binding differs")
    binding = _binding("request.json", metadata)
    start, provenance = time.monotonic_ns(), process_clock()
    receipt, error = None, None
    try:
        receipt = replay.run_replay(output / "session", request["replay_plan"])
    except FAILURES as exc:
        error = {"stage": "replay_observation", "error": f"{type(exc).__name__}: {exc}"}
    driver = {"schema_version": 1, "kind": "managed_replay_resource_driver", "mode": "exploratory_unqualified",
              "request": binding, "invocation_id": request["invocation_id"], "process": provenance,
              "call_clock": timer._timing(start), "receipt": receipt, "error": error}
    driver_binding = _publish(output / "driver.json", driver, "driver")
    sys.stdout.buffer.write(_transport(request, driver_binding))
    sys.stdout.buffer.flush()
    return _exit_code(driver)


def inspect_observation(output, receipt):
    """Reconstruct historical diagnostics without commands, worktree reads or cgroup access."""
    output = Path(output)
    validate("receipt", receipt)
    if len(_raw(receipt)) > files.MAX_RECEIPT_BYTES or receipt["limitations"] != LIMITATIONS:
        raise ValueError("unsupported replay resource receipt limits or limitations")
    replay._interval(receipt["observer_clock"])
    before = _capture(output)
    if not timer._same_json(before[0], receipt["retained_inputs"]):
        raise ValueError("replay resource retained inputs differ from bound bytes")
    request, metadata = files.read_json(output / "request.json")
    validate_request(request)
    binding = _binding("request.json", metadata)
    if not timer._same_json(binding, receipt["request"]):
        raise ValueError("replay resource request byte binding differs")
    resource = receipt["diagnostic_resource"]
    if receipt["resource"] is not None:
        resource, metadata = files.read_json(output / "resource.json", limit=files.MAX_RECEIPT_BYTES)
        if not timer._same_json(receipt["resource"], _binding("resource.json", metadata)) or receipt["diagnostic_resource"] is not None:
            raise ValueError("replay resource raw record byte binding differs")
    elif resource is not None and (output / "resource.json").exists():
        visible, _ = files.read_json(output / "resource.json", limit=files.MAX_RECEIPT_BYTES)
        if not timer._same_json(visible, resource):
            raise ValueError("replay resource unconfirmed publication contradicts diagnostic copy")
    stages = [item["stage"] for item in receipt["errors"]]
    expected_stage = ["resource_observation"] if resource is None else ["resource_publication"] if receipt["resource"] is None else []
    if stages != expected_stage:
        raise ValueError("replay resource missing observation or publication lacks matching failure evidence")
    if resource is None and any(item["path"] == "resource.json" for item in before[0]["files"]):
        raise ValueError("replay resource no-return observation invents an unbound raw record")
    if resource is not None:
        resources.inspect_resource_record(resource)
        replay._interval(resource["clock"], receipt["observer_clock"])
        options = request["configuration"]
        expected = {"argv": _command(request, binding), "cwd": request["replay_plan"]["cwd"],
                    "timeout_seconds": options["outer_timeout_seconds"], **{key: options[key] for key in
                        ("cgroup_parent", "allow_missing_peak", "sample_interval_ns", "cleanup_grace_ns")}}
        if not timer._same_json(resource["configuration"], expected):
            raise ValueError("replay resource boundary command or configuration differs from request")
    driver, inner, confirmed = None, None, False
    driver_present = any(item["path"] == "driver.json" for item in before[0]["files"])
    if (receipt["driver"] is not None) != driver_present:
        raise ValueError("replay resource receipt omits or invents driver evidence")
    if driver_present:
        driver, metadata = files.read_json(output / "driver.json", limit=files.MAX_RECEIPT_BYTES)
        validate("driver", driver)
        if (not timer._same_json(receipt["driver"], _binding("driver.json", metadata))
                or not timer._same_json(driver["request"], binding) or driver["invocation_id"] != request["invocation_id"]):
            raise ValueError("replay resource driver byte or invocation binding differs")
        if resource is not None and not resource["run_attempted"]:
            raise ValueError("non-invoked replay resource boundary contains a driver observation")
        if driver["process"]["pid"] == receipt["observer_process"]["pid"]:
            raise ValueError("replay resource clocks must name distinct observer and driver processes")
        replay._interval(driver["call_clock"])
        if (driver["receipt"] is None) == (driver["error"] is None):
            raise ValueError("replay resource driver must retain either a returned receipt or an observation error")
        if driver["receipt"] is not None:
            replay._interval(driver["receipt"]["clock"], driver["call_clock"])
            inner = replay.inspect_replay(output / "session", driver["receipt"])
            plan, _ = files.read_json(output / "session/plan.json", limit=replay.MAX_PLAN_BYTES)
            if not timer._same_json(plan, request["replay_plan"]):
                raise ValueError("replay resource actual session plan differs from frozen request")
        process = resource["process"] if resource is not None else None
        transport = _transport(request, receipt["driver"])
        confirmed = bool(process is not None and resource["enrollment"]["status"] == "confirmed"
                         and process["status"] == "exited_unqualified" and process.get("process_reaped") and process.get("output_complete")
                         and process.get("returncode") == _exit_code(driver) and process.get("stdout_bytes") == len(transport)
                         and process.get("stdout_sha256") == hashlib.sha256(transport).hexdigest() and process.get("stderr_bytes") == 0)
    if resource is not None and not resource["run_attempted"] and "session" in before[0]["directories"]:
        raise ValueError("non-invoked replay resource boundary contains session diagnostics")
    if _capture(output) != before:
        raise ValueError("replay resource evidence changed during inspection")
    attempted = (True if inner is not None else False if resource is not None and not resource["run_attempted"] else None)
    status = (inner["status"] if inner is not None else "not_run_unsupported" if attempted is False and resource["status"] == "unsupported"
              else "not_run_boundary_failed" if attempted is False else "unknown")
    count, interactions = len(replay._steps(request["replay_plan"])), len(request["replay_plan"]["interactions"])
    reasons = []
    if receipt["errors"]:
        reasons.append("outer_observer_or_publication_error")
    if resource is None:
        reasons.append("resource_observation_unconfirmed")
    elif resource["status"] in ("failed", "unsupported", "partial_unsupported"):
        reasons.append("resource_" + resource["status"])
    if attempted is not False and not confirmed:
        reasons.append("driver_completion_unconfirmed")
    if attempted is not False and inner is None:
        reasons.append("session_observation_unknown")
    if inner is not None and inner["status"] != "completed_unqualified":
        reasons.append("session_incomplete_or_failed")
    terminal = ("unsupported" if not receipt["errors"] and attempted is False and resource["status"] == "unsupported" else
                "failed" if any(reason != "resource_partial_unsupported" for reason in reasons) else
                "partial_unsupported" if reasons else "observed_unqualified")
    return {"record_consistency": "checked_unqualified", "kind": "managed_replay_resource_diagnostic", "mode": "exploratory_unqualified",
            "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT, "scope": SCOPE, "status": terminal,
            "resource_endpoint": resources.ENDPOINT, "replay_endpoint": replay.ENDPOINT, "overhead_policy": OVERHEAD,
            "clock_alignment": CLOCK_ALIGNMENT, "observer_process": receipt["observer_process"], "driver_process": driver["process"] if driver is not None else None,
            "resource_record_confirmed": receipt["resource"] is not None, "driver_completion_confirmed": confirmed,
            "resource_status": resource["status"] if resource is not None else None, "session_status": status,
            "planned_session_count": 1, "observed_session_count": int(inner is not None), "session_invocation_attempted": attempted,
            "planned_phase_count": count, "phase_status_counts": inner["phase_status_counts"] if inner is not None else {status: count},
            "known_phase_invocation_attempts": inner["known_phase_invocation_attempts"] if inner is not None else 0,
            "known_not_invoked_phases": inner["known_not_invoked_phases"] if inner is not None else count if attempted is False else 0,
            "unknown_phase_invocations": inner["unknown_phase_invocations"] if inner is not None else count if attempted is None else 0,
            "planned_interaction_count": interactions, "interaction_status_counts": inner["interaction_status_counts"] if inner is not None else {status: interactions},
            "shutdown_status": inner["shutdown_status"] if inner is not None else None, "replay_summary": inner,
            "memory_metric": resources.MEMORY_METRIC,
            **{field: resource[field] if resource is not None else None for field in
               ("cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes", "memory_events_delta")},
            "unsupported_capabilities": ({key: value["reason"] for key, value in resource["capabilities"].items() if not value["supported"]}
                                         if resource is not None else None),
            "counter_boundary_accounting_complete": bool(resource is not None and resource["whole_boundary_accounting_complete"]),
            "whole_session_accounting_complete": terminal == "observed_unqualified", "failure_reasons": reasons,
            "resource_failure_reasons": resource["failure_reasons"] if resource is not None else None,
            "per_phase_resource_metrics": None, "idle_only_resource_metrics": None, "verified_independent_units": None,
            "ratio": None, "bootstrap": None, "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private bundle; save stdout receipt outside it")
    parser.add_argument("--outer-timeout", type=float, required=True, help="separate watchdog including execution, reserved shutdown and at least five seconds slack")
    parser.add_argument("--cgroup-parent", type=Path)
    parser.add_argument("--allow-missing-peak", action="store_true")
    parser.add_argument("--sample-interval", type=float, default=0.02)
    parser.add_argument("--cleanup-grace", type=float, default=0.1)
    args = parser.parse_args()
    try:
        plan, _ = files.read_json(args.plan, limit=replay.MAX_PLAN_BYTES)
        receipt = run_observation(args.output, plan, args.outer_timeout, cgroup_parent=args.cgroup_parent,
                                  allow_missing_peak=args.allow_missing_peak, sample_interval=args.sample_interval, cleanup_grace=args.cleanup_grace)
        summary = inspect_observation(args.output, receipt)
        print(json.dumps(receipt, sort_keys=True, allow_nan=False), flush=True)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"replay-resources: {exc}\n")
    return 3 if summary["status"] == "unsupported" else 2 if summary["status"] == "failed" else 0 if summary["whole_session_accounting_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
