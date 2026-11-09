"""Paired resource diagnostics: bound units, no replay or latency promotion."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
from finalization import (
    MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, archive, archived_check, check, inspect_file,
    read_json, require_safe_lookup, validate_observed,
)
from guards import check_observation
from metadata import collect_metadata
from paired_lifecycle import ARMS, STAGES, _context, _filename, stage_configuration, validate_stage_configuration
from pt_bench import _same_json, _timing, write_record
import resource_run as resources
from schedule import paired_schedule


KIND = "paired_resource_campaign"
LIMITATIONS = [
    "resource diagnostic units, never unmodified-product or paired lifecycle latency samples",
    "file checks, archival and observer publication follow the resource endpoint",
    "no semantic, generation, reset, resource-budget, native-peak or confirmatory qualification",
    "unknown resources remain unknown; failed and not-run arms remain in the planned denominator",
]


class PairedResourceAborted(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _validators():
    root = Path(__file__).resolve().parent
    schemas = [json.loads((root / name).read_text()) for name in
               ("paired-resource-v1.schema.json", "resource-observation-v1.schema.json", "lifecycle-v2.schema.json")]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry)
            for kind in ("plan", "stage", "skipped", "abort")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"paired resource {kind} schema at {path}: violates {error.validator}")
    if kind == "abort" and value["diagnostic_resource"] is not None:
        # Validate with the strict root validator too: following a reference to
        # another dialect root must not relax integer-token or semantic checks.
        resources.inspect_resource_record(value["diagnostic_resource"])


def _publish(path, value, kind, *, limit=MAX_RECORD_BYTES):
    validate(kind, value)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > limit:
        raise ValueError("paired resource metadata exceeds byte limit")
    write_record(str(path), value)
    actual, _ = inspect_file(path.parent, path.name, limit=len(raw))
    if actual["bytes"] != len(raw) or actual["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("paired resource metadata publication did not commit expected bytes")


def _subject_observed(resource):
    return resource["enrollment"]["status"] == "confirmed" and resource["process"] is not None


def _stage_safe(resource, stage):
    if resource["status"] == "failed" or stage["errors"]:
        return False
    observed = stage["required_finalization"]["observed"]
    if observed is not None and any(not item["matched"] and item["kind"] not in ("process", "expected_exit_code")
                                    for item in observed["checks"]):
        return False
    return not (stage["artifact_archive"] and stage["artifact_archive"]["errors"])


def _preparation_ok(resource, stage):
    return (_stage_safe(resource, stage) and _subject_observed(resource)
            and resource["process"]["status"] == "exited_unqualified" and resource["process"]["returncode"] == 0
            and stage["required_finalization"]["observed"]["matched"]
            and (stage["observation_guard"] is None or stage["observation_guard"]["matched_expected_observations"]))


def _skipped(context, status):
    return {"schema_version": 1, "kind": "paired_resource_not_run", "mode": "exploratory_unqualified",
            "context": context, "result": {"status": status}}


def _stage_record(context, binding, resource, contract, expectation, cwd, bundle):
    start = time.monotonic_ns()
    observed = archived = guard = None
    errors = []
    if _subject_observed(resource):
        if expectation is not None:
            guard = check_observation(resource["process"], **expectation)
        try:
            observed = check(resource["process"], cwd, contract)
        except (OSError, ValueError) as exc:
            errors.append({"stage": "finalization_observation", "error": f"{type(exc).__name__}: {exc}"})
        if observed is not None:
            try:
                archived = archive(cwd, observed, bundle)
                if archived["errors"]:
                    errors.append({"stage": "artifact_archive", "error": "declared artifact archival failed"})
            except (OSError, ValueError) as exc:
                errors.append({"stage": "artifact_archive", "error": f"{type(exc).__name__}: {exc}"})
    return {"schema_version": 1, "kind": "paired_resource_stage", "mode": "exploratory_unqualified",
            "context": context, "resource": binding, "observer_clock": _timing(start),
            "guard_expectations": expectation, "observation_guard": guard,
            "required_finalization": {"requirements": contract, "observed": observed},
            "artifact_archive": archived, "errors": errors}


def run_pairs(output, cwd, baseline, candidate, blocks, seed, timeout, **options):
    require_safe_lookup()
    if (options.get("capture_raw", False) is not False
            or options.get("raw_limit_bytes", 10 * 1024 * 1024) != 10 * 1024 * 1024):
        raise ValueError("raw capture options are unsupported in paired resource diagnostics")
    allow = options.get("resource_allow_missing_peak", False)
    interval, grace = options.get("resource_sample_interval", 0.02), options.get("resource_cleanup_grace", 0.1)
    resources.validate_settings(timeout, allow, interval, grace)
    schedule = paired_schedule(blocks, seed)
    cwd, arm_cwds, commands, contracts, guards = stage_configuration(cwd, baseline, candidate, options)
    shared = options.get("resource_cgroup_parent")
    parents = {arm: options.get(f"{arm}_resource_cgroup_parent", shared) for arm in ARMS}
    parents = {arm: str(Path(os.path.abspath(parent))) if parent is not None else None for arm, parent in parents.items()}
    plan = {"schema_version": 1, "kind": KIND, "mode": "exploratory_unqualified", "measurement_layer": "resource_diagnostic",
            "timing_endpoint": resources.ENDPOINT, "schedule": schedule, "seed": seed, "cwd": str(cwd),
            "timeout_seconds": timeout, "arm_cwds": {arm: str(path) for arm, path in arm_cwds.items()},
            "commands": commands, "finalization": contracts, "guards": guards,
            "resources": {"parents": parents, "allow_missing_peak": allow,
                          "sample_interval_ns": round(interval * 1e9), "cleanup_grace_ns": round(grace * 1e9)},
            "bundle_directory": "blobs", "host_metadata": collect_metadata(), "limitations": LIMITATIONS.copy()}
    validate("plan", plan)
    validate_stage_configuration(plan)
    output = Path(os.path.abspath(output))
    output.mkdir(mode=0o700)
    bundle = output / "blobs"
    bundle.mkdir(mode=0o700)
    _publish(output / "schedule.json", plan, "plan")

    def abort(context, reason, error, *, resource=None, stage=None, skipped_record=None):
        _publish(output / "abort.json", {"schema_version": 1, "kind": "paired_resource_abort", "mode": "exploratory_unqualified",
                                        "context": context, "reason": reason, "error": error,
                                        "diagnostic_resource": resource, "diagnostic_stage": stage,
                                        "diagnostic_skipped": skipped_record},
                 "abort", limit=MAX_RECEIPT_BYTES)
        raise PairedResourceAborted(f"{context}: {reason}: {error}; remaining planned work not run")

    for block in schedule:
        for position, arm in enumerate(block["order"], 1):
            skipped = None
            for stage in STAGES:
                context = _context(stage, block["block"], position, arm)
                filename = _filename(stage, block["block"], arm)
                if skipped is not None:
                    if stage == "measurement":
                        record = _skipped(context, skipped)
                        try:
                            _publish(output / filename, record, "skipped")
                        except (OSError, ValueError) as exc:
                            abort(context, "skipped_publication_failed", f"{type(exc).__name__}: {exc}", skipped_record=record)
                    continue
                command = commands[arm][stage]
                if command is None:
                    continue
                try:
                    resource = resources.observe_resources(command, str(arm_cwds[arm]), timeout,
                                                          cgroup_parent=parents[arm], allow_missing_peak=allow,
                                                          sample_interval=interval, cleanup_grace=grace)
                except (OSError, ValueError) as exc:
                    abort(context, "harness_error", f"{type(exc).__name__}: {exc}")
                try:
                    binding = resources.publish_resource_record(output / f"resource-{filename}", resource)
                except (OSError, ValueError) as exc:
                    abort(context, "resource_publication_failed", f"{type(exc).__name__}: {exc}", resource=resource)
                record = _stage_record(context, binding, resource, contracts[arm][stage], guards[arm][stage], arm_cwds[arm], bundle)
                try:
                    _publish(output / filename, record, "stage")
                except (OSError, ValueError) as exc:
                    abort(context, "stage_publication_failed", f"{type(exc).__name__}: {exc}", stage=record)
                if not _stage_safe(resource, record):
                    reason = "resource_observation_failed" if resource["status"] == "failed" else "required_finalization_failed"
                    abort(context, reason, "resource or declared finalization evidence failed")
                if stage != "measurement" and not _preparation_ok(resource, record):
                    name = "preparation" if stage == "preparation" else "probe"
                    skipped = f"not_run_{name}_resource_unsupported" if resource["status"] == "unsupported" else f"not_run_{name}_failed"
    return inspect_pairs(output, plan)


def _thin(context, resource=None, stage=None, *, not_run="not_run_run_aborted", committed=False,
          stage_committed=False, not_run_committed=False):
    archive_complete = None
    if stage is not None and stage["artifact_archive"] is not None:
        archived = stage["artifact_archive"]
        archive_complete = (not archived["errors"] and {item["path"] for item in archived["artifacts"]}
                            == {item["path"] for item in stage["required_finalization"]["requirements"]["artifacts"]})
    return {"context": context, "resource_status": resource["status"] if resource is not None else not_run,
            "resource_record_committed": committed,
            "run_attempted": resource["run_attempted"] if resource is not None else None if not_run == "harness_error" else False,
            "stage_record_committed": stage_committed,
            "not_run_record_committed": not_run_committed,
            "whole_boundary_accounting_complete": resource["whole_boundary_accounting_complete"] if resource is not None else False,
            "cpu_delta_usec": resource["cpu_delta_usec"] if resource is not None else None,
            "peak_charged_bytes": resource["peak_charged_bytes"] if resource is not None else None,
            "sampled_current_max_bytes": resource["sampled_current_max_bytes"] if resource is not None else None,
            "unsupported_capabilities": {key: value["reason"] for key, value in resource["capabilities"].items() if not value["supported"]} if resource is not None else {},
            "resource_failure_reasons": resource["failure_reasons"] if resource is not None else [],
            "resource_errors": resource["errors"] if resource is not None else [],
            "stage_errors": stage["errors"] if stage is not None else [],
            "archive_complete": archive_complete,
            "process_status": resource["process"]["status"] if resource is not None and resource["process"] is not None else None,
            "returncode": resource["process"].get("returncode") if resource is not None and resource["process"] is not None else None,
            "guard_matched": stage["observation_guard"]["matched_expected_observations"] if stage and stage["observation_guard"] is not None else None,
            "finalization_matched": stage["required_finalization"]["observed"]["matched"] if stage and stage["required_finalization"]["observed"] is not None else None}


def _reasons(resource, stage, stage_name):
    reasons = []
    if resource["status"] != "observed_unqualified":
        reasons.append(f"resource_{resource['status']}")
    if not resource["whole_boundary_accounting_complete"]:
        reasons.append("whole_boundary_accounting_incomplete")
    if stage is None:
        reasons.append("stage_observer_metadata_missing")
    else:
        observed = stage["required_finalization"]["observed"]
        if stage["errors"] or observed is None or not observed["matched"] or (stage["artifact_archive"] and stage["artifact_archive"]["errors"]):
            reasons.append("required_finalization_not_verified")
        guard = stage["observation_guard"]
        if stage_name == "measurement" and stage["guard_expectations"] is None:
            reasons.append("guard_not_requested")
        elif stage["guard_expectations"] is not None and (guard is None or not guard["matched_expected_observations"]):
            reasons.append("guard_not_matched")
    return reasons


def _inspect_stage(record, resource, plan, context, bundle):
    validate("stage", record)
    arm, stage = context["arm"], context["stage"]
    evidence = record["required_finalization"]
    if (not _same_json(record["context"], context) or not _same_json(evidence["requirements"], plan["finalization"][arm][stage])
            or not _same_json(record["guard_expectations"], plan["guards"][arm][stage])):
        raise ValueError("resource stage metadata differs from campaign plan")
    clock = record["observer_clock"]
    if (clock["monotonic_start_ns"] < resource["clock"]["monotonic_end_ns"]
            or clock["monotonic_end_ns"] < clock["monotonic_start_ns"]
            or clock["elapsed_ns"] != clock["monotonic_end_ns"] - clock["monotonic_start_ns"]):
        raise ValueError("resource stage observer interval is inconsistent")
    observed, archived = evidence["observed"], record["artifact_archive"]
    expectation = record["guard_expectations"]
    guard = check_observation(resource["process"], **expectation) if _subject_observed(resource) and expectation is not None else None
    if not _same_json(guard, record["observation_guard"]):
        raise ValueError("resource stage guard differs from bound process observations")
    observation_error = any(item["stage"] == "finalization_observation" for item in record["errors"])
    archive_error = any(item["stage"] == "artifact_archive" for item in record["errors"])
    if not _subject_observed(resource):
        if observed is not None or archived is not None or record["errors"]:
            raise ValueError("non-invoked subject invents finalization evidence")
    elif observed is None:
        if not observation_error or archived is not None or archive_error:
            raise ValueError("missing finalization observation without failure evidence")
    else:
        if observation_error:
            raise ValueError("finalization observation contradicts error evidence")
        validate_observed(resource["process"], evidence["requirements"], observed, capture_raw=False)
        if archived is None:
            if not archive_error:
                raise ValueError("missing artifact archive without failure evidence")
        else:
            if bool(archived["errors"]) != archive_error:
                raise ValueError("resource archive errors contradict stage errors")
            historical = archived_check(resource["process"], evidence["requirements"], observed, archived, bundle, capture_raw=False)
            if not _same_json(historical, observed):
                raise ValueError("resource historical finalization differs from retained bytes")


def inspect_pairs(directory, plan, *, observations=None):
    validate("plan", plan)
    if plan["limitations"] != LIMITATIONS or not _same_json(plan["schedule"], paired_schedule(len(plan["schedule"]), plan["seed"])):
        raise ValueError("paired resource schedule, seed or limitations differ from contract")
    validate_stage_configuration(plan)
    bundle = directory / "blobs"
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("missing or unsafe paired resource artifact bundle")
    expected, referenced, groups = {"schedule.json", "blobs"}, set(), set()
    abort = None
    if (directory / "abort.json").exists():
        abort, _ = read_json(directory / "abort.json", limit=MAX_RECEIPT_BYTES)
        validate("abort", abort)
        expected.add("abort.json")
    stopped = found_abort = False
    last_end = None
    arms, stages, blockers = [], [], []

    def read(name, kind):
        value, metadata = read_json(directory / name, limit=MAX_RECEIPT_BYTES if kind == "resource" else MAX_RECORD_BYTES)
        if kind == "resource":
            resources.inspect_resource_record(value)
        else:
            validate(kind, value)
        expected.add(name)
        return value, metadata

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            measurement = _thin(_context("measurement", block["block"], position, arm))
            skipped = None
            for stage_name in STAGES:
                context = _context(stage_name, block["block"], position, arm)
                filename = _filename(stage_name, block["block"], arm)
                command = plan["commands"][arm][stage_name]
                is_abort = abort is not None and _same_json(abort["context"], context)
                if skipped is not None or stopped:
                    state = skipped or "not_run_run_aborted"
                    skip_committed = False
                    if skipped is not None and not stopped and stage_name == "measurement":
                        if is_abort:
                            if abort["reason"] != "skipped_publication_failed":
                                raise ValueError("resource abort contradicts skipped measurement")
                            value = abort["diagnostic_skipped"]
                            if (directory / filename).exists():
                                visible, _ = read(filename, "skipped")
                                if not _same_json(value, visible):
                                    raise ValueError("failed skipped publication differs from diagnostic metadata")
                            stopped = found_abort = True
                            blockers.append({"context": context, "reasons": [abort["reason"]]})
                        else:
                            value, _ = read(filename, "skipped")
                            skip_committed = True
                        if not _same_json(value, _skipped(context, skipped)):
                            raise ValueError("resource skipped-arm evidence contradicts earlier stage")
                    if command is not None:
                        item = _thin(context, not_run=state, not_run_committed=skip_committed)
                        stages.append(item)
                        if stage_name == "measurement":
                            measurement = item
                    continue
                if command is None:
                    if is_abort:
                        raise ValueError("resource abort names an unrequested stage")
                    continue
                resource = record = None
                committed = False
                raw_name = f"resource-{filename}"
                if is_abort and abort["reason"] == "harness_error":
                    item = _thin(context, not_run="harness_error")
                else:
                    if is_abort and abort["reason"] == "resource_publication_failed":
                        resource = abort["diagnostic_resource"]
                        resources.inspect_resource_record(resource)
                        if (directory / raw_name).exists():
                            visible, _ = read(raw_name, "resource")
                            if not _same_json(visible, resource):
                                raise ValueError("failed resource publication differs from diagnostic observation")
                    else:
                        resource, raw_metadata = read(raw_name, "resource")
                        committed = True
                        if is_abort and abort["reason"] == "stage_publication_failed":
                            record = abort["diagnostic_stage"]
                            if (directory / filename).exists():
                                visible, _ = read(filename, "stage")
                                if not _same_json(visible, record):
                                    raise ValueError("failed stage publication differs from diagnostic metadata")
                        else:
                            record, _ = read(filename, "stage")
                        binding = record["resource"]
                        if binding["name"] != raw_name or binding["bytes"] != raw_metadata["bytes"] or binding["sha256"] != raw_metadata["sha256"]:
                            raise ValueError("paired resource byte binding differs from retained observation")
                    settings = {"argv": command, "cwd": plan["arm_cwds"][arm], "timeout_seconds": plan["timeout_seconds"],
                                "cgroup_parent": plan["resources"]["parents"][arm],
                                **{key: plan["resources"][key] for key in ("allow_missing_peak", "sample_interval_ns", "cleanup_grace_ns")}}
                    if not _same_json(settings, resource["configuration"]):
                        raise ValueError("bound resource observation differs from paired stage configuration")
                    group = resource["group"]
                    if group is not None:
                        if group["path"] in groups:
                            raise ValueError("private resource group reused across campaign units")
                        groups.add(group["path"])
                    clock = resource["clock"]
                    if clock["elapsed_ns"] <= 0 or (last_end is not None and clock["monotonic_start_ns"] < last_end):
                        raise ValueError("paired resource intervals overlap, are out of order or are empty")
                    last_end = clock["monotonic_end_ns"]
                    if record is not None:
                        _inspect_stage(record, resource, plan, context, bundle)
                        if record["artifact_archive"] is not None:
                            referenced.update(entry["sha256"] for entry in record["artifact_archive"]["artifacts"])
                        last_end = record["observer_clock"]["monotonic_end_ns"]
                    item = _thin(context, resource, record, committed=committed,
                                 stage_committed=record is not None and not (is_abort and abort["reason"] == "stage_publication_failed"))
                    reasons = _reasons(resource, record, stage_name)
                    if reasons:
                        blockers.append({"context": context, "reasons": reasons})
                stages.append(item)
                if stage_name == "measurement":
                    measurement = item
                if is_abort:
                    if abort["reason"] == "skipped_publication_failed":
                        raise ValueError("skipped-publication abort names an invoked stage")
                    if abort["reason"] == "resource_observation_failed" and resource["status"] != "failed":
                        raise ValueError("resource abort lacks an observed resource failure")
                    if abort["reason"] == "required_finalization_failed" and (resource["status"] == "failed" or _stage_safe(resource, record)):
                        raise ValueError("resource abort lacks a declared finalization failure")
                    blockers.append({"context": context, "reasons": [abort["reason"]]})
                    stopped = found_abort = True
                elif not _stage_safe(resource, record):
                    raise ValueError("unsafe resource/finalization outcome without required abort record")
                elif stage_name != "measurement" and not _preparation_ok(resource, record):
                    name = "preparation" if stage_name == "preparation" else "probe"
                    skipped = f"not_run_{name}_resource_unsupported" if resource["status"] == "unsupported" else f"not_run_{name}_failed"
            arms.append(measurement)
            if measurement["resource_status"].startswith("not_run"):
                blockers.append({"context": measurement["context"], "reasons": [measurement["resource_status"]]})
    if abort is not None and not found_abort:
        raise ValueError("resource abort does not name an observed requested stage")
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("unexpected or missing paired resource campaign files")
    if {path.name for path in bundle.iterdir()} != referenced:
        raise ValueError("unexpected or missing paired resource artifact blobs")
    if observations is not None:
        observations.extend(arms)
    resource_counts = dict(sorted(Counter(item["resource_status"] for item in arms).items()))
    guard_counts = Counter("not_observed" if item["guard_matched"] is None else "matched" if item["guard_matched"] else "mismatched" for item in arms)
    return {"record_consistency": "aborted" if stopped else "complete", "mode": "exploratory_unqualified",
            "measurement_layer": "resource_diagnostic", "timing_endpoint": resources.ENDPOINT,
            "resource_unit": "one_requested_stage",
            "blocks": len(plan["schedule"]), "planned_arm_count": len(arms),
            "observed_arm_count": sum(item["run_attempted"] is True for item in arms),
            "unknown_invocation_arm_count": sum(item["run_attempted"] is None for item in arms),
            "measurement_resource_record_count": sum(item["resource_status"] in ("observed_unqualified", "partial_unsupported", "unsupported", "failed") for item in arms),
            "arm_status_counts": resource_counts, "resource_status_counts": resource_counts,
            "observation_guard_counts": dict(sorted(guard_counts.items())), "recorded_interval_order": "nonoverlapping",
            "planned_stage_count": len(stages), "stage_resource_status_counts": dict(sorted(Counter(item["resource_status"] for item in stages).items())),
            "unknown_invocation_stage_count": sum(item["run_attempted"] is None for item in stages),
            "stage_resource_observations": stages, "blockers": blockers, "diagnostic_complete": not stopped and not blockers,
            "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def summarize(inspection, observations):
    summary = dict(inspection)
    summary.update(status="diagnostic_resource_observations" if inspection["diagnostic_complete"] else "blocked",
                   ratio=None, absolute_latency_ns=None, bootstrap=None, resource_observations=observations,
                   resource_scope=resources.SCOPE, memory_metric=resources.MEMORY_METRIC,
                   per_arm_resources_unit="measurement_stage_only")
    per_arm = {}
    for arm in ARMS:
        units = [item for item in observations if item["context"]["arm"] == arm]
        cpu = [item["cpu_delta_usec"]["usage_usec"] for item in units if item["cpu_delta_usec"] is not None]
        peaks = [item["peak_charged_bytes"] for item in units if item["peak_charged_bytes"] is not None]
        currents = [item["sampled_current_max_bytes"] for item in units if item["sampled_current_max_bytes"] is not None]
        per_arm[arm] = {"planned_units": len(units), "invocations_attempted": sum(item["run_attempted"] is True for item in units),
                        "invocations_unknown": sum(item["run_attempted"] is None for item in units),
                        "complete_accounting_units": sum(item["whole_boundary_accounting_complete"] for item in units),
                        "cpu_usage_usec": {"observed_units": len(cpu), "unknown_units": len(units) - len(cpu), "observed_sum": sum(cpu) if cpu else None},
                        "peak_charged_bytes": {"observed_units": len(peaks), "unknown_units": len(units) - len(peaks), "maximum_observed_per_unit": max(peaks) if peaks else None},
                        "sampled_current_max_bytes": {"observed_units": len(currents), "unknown_units": len(units) - len(currents), "maximum_observed_per_unit": max(currents) if currents else None}}
    summary["per_arm_resources"] = per_arm
    return summary
