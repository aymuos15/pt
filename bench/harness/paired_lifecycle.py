"""Publication-inclusive exploratory paired observations, never qualification."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from evidence import validate_v2
from finalization import MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, inspect_file, read_json, requirements, require_safe_lookup
from guards import check_observation, validate_expectations
from metadata import collect_metadata
from pt_bench import LIFECYCLE_ENDPOINT, _same_json, inspect_lifecycle, measure_and_publish, write_record
from schedule import paired_schedule


STAGES = ("preparation", "probe", "measurement")
PREFIX = {"preparation": "preparation", "probe": "probe", "measurement": "block"}
ARMS = ("baseline", "candidate")


class PairedLifecycleAborted(RuntimeError):
    pass


def _command(value):
    if not isinstance(value, list) or not value or not all(isinstance(arg, str) for arg in value) or not value[0]:
        raise ValueError("commands must be nonempty argv arrays of strings")
    return value.copy()


def _publish(path: Path, value: dict, *, kind: str, limit: int = MAX_RECEIPT_BYTES) -> None:
    """Persist observer metadata and verify it, outside the subject interval."""
    validate_v2(kind, value)
    expected = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(expected) > limit:
        raise ValueError("paired observer record exceeds byte limit")
    write_record(str(path), value)
    actual, _ = inspect_file(path.parent, path.name, limit=len(expected))
    if actual["bytes"] != len(expected) or actual["sha256"] != hashlib.sha256(expected).hexdigest():
        raise ValueError("paired observer publication did not commit expected bytes")


def _filename(stage, number, arm):
    return f"{PREFIX[stage]}-{number:06d}-{arm}.json"


def _context(stage, number, position, arm):
    return {"stage": stage, "block": number, "position": position, "arm": arm}


def _safe_to_continue(receipt):
    result = receipt["result"]
    if receipt["errors"] or result is None:
        return False
    if result["status"] != "launch_error" and (result.get("process_reaped") is not True or result.get("output_complete") is not True):
        return False
    for evidence in (receipt["required_finalization"]["before_publication"],
                     receipt["required_finalization"]["after_publication"]):
        if any(not item["matched"] and item["kind"] not in ("process", "expected_exit_code")
               for item in evidence["checks"]):
            return False
    return True


def _stage_ok(receipt):
    return (receipt["lifecycle"]["status"] == "finalized_unqualified"
            and receipt["result"]["returncode"] == 0
            and (receipt["observation_guard"] is None
                 or receipt["observation_guard"]["matched_expected_observations"]))


def stage_configuration(cwd: Path, baseline: list[str], candidate: list[str], options: dict):
    """Canonical shared stage requests; performs no invocation or publication."""
    cwd = cwd.resolve(strict=True)
    arm_cwds = {arm: Path(options.get(f"{arm}_cwd") or cwd).resolve(strict=True) for arm in ARMS}
    if not cwd.is_dir() or not all(path.is_dir() for path in arm_cwds.values()):
        raise ValueError("each cwd must be a directory")
    commands, contracts, guards = {}, {}, {}
    for arm, command in (("baseline", baseline), ("candidate", candidate)):
        commands[arm], contracts[arm], guards[arm] = {}, {}, {}
        for stage in STAGES:
            raw_command = command if stage == "measurement" else options.get(f"{arm}_{'prepare' if stage == 'preparation' else 'probe'}")
            commands[arm][stage] = _command(raw_command) if raw_command is not None else None
            key = arm if stage == "measurement" else f"{arm}_{'prepare' if stage == 'preparation' else 'probe'}"
            requested = options.get(f"{key}_finalization")
            expectation = options.get(f"{arm}_guard" if stage == "measurement" else f"{arm}_probe_guard" if stage == "probe" else "unused")
            if raw_command is None:
                if requested is not None or expectation is not None:
                    raise ValueError("finalization/guard requires the corresponding stage command")
                contracts[arm][stage], guards[arm][stage] = None, None
                continue
            expectation = validate_expectations(expectation) if expectation is not None else None
            contract = requirements(requested)
            expected_exit = 0 if stage != "measurement" else expectation["expected_exit_code"] if expectation is not None else None
            if expected_exit is not None:
                if contract["expected_exit_code"] not in (None, expected_exit):
                    raise ValueError("stage guard and required exit expectations conflict")
                contract["expected_exit_code"] = expected_exit
            if stage == "probe" and expectation is not None and expectation["expected_exit_code"] != 0:
                raise ValueError("state-probe guard requires expected exit zero")
            contracts[arm][stage], guards[arm][stage] = contract, expectation
    return cwd, arm_cwds, commands, contracts, guards


def run_pairs(output: Path, cwd: Path, baseline: list[str], candidate: list[str],
              blocks: int, seed: int, timeout: float, **options) -> None:
    """New format v2; retain receipts before any subsequent stage may run."""
    require_safe_lookup()
    schedule = paired_schedule(blocks, seed)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    capture_raw, limit = options.get("capture_raw", False), options.get("raw_limit_bytes", 10 * 1024 * 1024)
    if type(capture_raw) is not bool or type(limit) is not int or limit < 0:
        raise ValueError("invalid raw capture configuration")
    cwd, arm_cwds, commands, contracts, guards = stage_configuration(cwd, baseline, candidate, options)
    output = Path(os.path.abspath(output))
    bundle = output / "blobs"
    plan = {"schema_version": 2, "mode": "exploratory_unqualified", "timing_endpoint": LIFECYCLE_ENDPOINT,
            "schedule": schedule, "seed": seed, "cwd": str(cwd), "timeout_seconds": timeout,
            "arm_cwds": {arm: str(path) for arm, path in arm_cwds.items()},
            "commands": commands, "finalization": contracts, "guards": guards,
            "bundle_directory": "blobs", "capture_raw": capture_raw, "raw_limit_bytes": limit,
            "host_metadata": collect_metadata(),
            "limitations": ["historical file/absence observations only", "receipt persistence outside subject interval",
                            "no semantic, generation, resource or confirmatory qualification"]}
    validate_v2("paired-plan", plan)
    output.mkdir(mode=0o700)
    bundle.mkdir(mode=0o700)
    _publish(output / "schedule.json", plan, kind="paired-plan", limit=MAX_RECORD_BYTES)

    def abort(context, reason, error, receipt=None):
        _publish(output / "abort.json", {"schema_version": 2, "mode": "exploratory_unqualified",
                                        "context": context, "reason": reason, "error": error, "receipt": receipt},
                 kind="paired-abort")
        raise PairedLifecycleAborted(f"{context}: {reason}: {error}; remaining arms not run")

    for block in schedule:
        for position, arm in enumerate(block["order"], 1):
            skipped = None
            for stage in STAGES:
                context = _context(stage, block["block"], position, arm)
                if skipped is not None:
                    if stage == "measurement":
                        _publish(output / _filename(stage, block["block"], arm), {
                            "schema_version": 2, "mode": "exploratory_unqualified", "context": context,
                            "result": {"status": skipped}}, kind="sample", limit=MAX_RECORD_BYTES)
                    continue
                command = commands[arm][stage]
                if command is None:
                    continue
                filename = _filename(stage, block["block"], arm)
                try:
                    receipt = measure_and_publish(
                        command, str(arm_cwds[arm]), timeout, output / filename,
                        required_finalization=contracts[arm][stage], context=context,
                        guard_expectations=guards[arm][stage], archive_bundle=bundle,
                        raw_bundle=bundle if capture_raw else None, raw_limit_bytes=limit,
                    )
                except (ValueError, OSError) as exc:
                    abort(context, "harness_error", str(exc))
                try:
                    _publish(output / f"receipt-{filename}", receipt, kind="receipt")
                except (ValueError, OSError) as exc:
                    abort(context, "receipt_publication_failed", str(exc), receipt)
                if not _safe_to_continue(receipt):
                    abort(context, "required_finalization_failed", "publication or cleanup evidence uncertain", receipt)
                if stage != "measurement" and not _stage_ok(receipt):
                    skipped = "not_run_preparation_failed" if stage == "preparation" else "not_run_probe_failed"


def validate_stage_configuration(plan: dict) -> None:
    """Cross-field stage contracts after envelope/schema validation."""
    for arm in ARMS:
        for stage in STAGES:
            command, contract, guard = (plan[key][arm][stage] for key in ("commands", "finalization", "guards"))
            if command is None:
                if stage == "measurement" or contract is not None or guard is not None:
                    raise ValueError("missing command or unexpected stage requirements")
            else:
                _command(command)
                if not _same_json(requirements(contract), contract):
                    raise ValueError("noncanonical stage finalization contract")
                if guard is not None:
                    validate_expectations(guard)
                    if contract["expected_exit_code"] != guard["expected_exit_code"]:
                        raise ValueError("stage guard and finalization exit expectations conflict")
                if stage != "measurement" and contract["expected_exit_code"] != 0:
                    raise ValueError("preparation/probe requires expected exit zero")


def inspect_pairs(directory: Path, plan: dict, *, observations: list | None = None) -> dict:
    """Historical inspection requires retained artifact bytes, not live cwd files."""
    from inspect_run import _measurement

    validate_v2("paired-plan", plan)
    if not _same_json(plan["schedule"], paired_schedule(len(plan["schedule"]), plan["seed"])):
        raise ValueError("paired schedule differs from seed or block numbering")
    validate_stage_configuration(plan)
    bundle = directory / "blobs"
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("missing or unsafe paired artifact bundle")
    expected, referenced = {"schedule.json", "blobs"}, set()
    abort = None
    if (directory / "abort.json").exists():
        abort, _ = read_json(directory / "abort.json", limit=MAX_RECEIPT_BYTES)
        validate_v2("paired-abort", abort)
        expected.add("abort.json")
    stopped, found_abort, last_end = False, False, None
    counts, lifecycle_counts, guard_counts = Counter(), Counter(), Counter()
    observed_arms = 0

    def read(path, *, kind="receipt"):
        value, _ = read_json(directory / path, limit=MAX_RECORD_BYTES if kind == "sample" else MAX_RECEIPT_BYTES)
        validate_v2(kind, value)
        expected.add(path)
        return value

    def register_blobs(receipt):
        archive = receipt.get("artifact_archive")
        if archive is not None:
            referenced.update(item["sha256"] for item in archive["artifacts"])
        capture = (receipt["result"] or {}).get("raw_capture")
        if capture is not None:
            referenced.update(capture[stream]["sha256"] for stream in ("stdout", "stderr"))

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            result, guard, timing, finalized = {"status": "not_run_run_aborted"}, None, None, False
            reasons, skipped = [], None
            attempted = False
            if not stopped:
                for stage in STAGES:
                    context = _context(stage, block["block"], position, arm)
                    filename = _filename(stage, block["block"], arm)
                    is_abort = abort is not None and _same_json(abort["context"], context)
                    if skipped is not None:
                        if stage == "measurement":
                            record = read(filename, kind="sample")
                            if not _same_json(record, {"schema_version": 2, "mode": "exploratory_unqualified",
                                                       "context": context, "result": {"status": skipped}}):
                                raise ValueError("invalid skipped-arm evidence")
                            result = record["result"]
                        continue
                    command = plan["commands"][arm][stage]
                    if command is None:
                        if is_abort:
                            raise ValueError("abort names an unrequested stage")
                        continue
                    if is_abort and abort["reason"] == "harness_error":
                        if abort["receipt"] is not None:
                            raise ValueError("unexpected receipt for pre-return harness error")
                        stopped, found_abort = True, True
                        result = {"status": "harness_error", "error": abort["error"]}
                        reasons.append("harness_error")
                        break
                    receipt_name = f"receipt-{filename}"
                    if is_abort and abort["reason"] == "receipt_publication_failed":
                        receipt = abort["receipt"]
                        if (directory / receipt_name).exists():
                            saved = read(receipt_name)
                            if not _same_json(saved, receipt):
                                raise ValueError("failed receipt publication differs from diagnostic copy")
                    else:
                        receipt = read(receipt_name)
                    if (not _same_json(receipt.get("context"), context)
                            or not _same_json(receipt.get("required_finalization", {}).get("requirements"), plan["finalization"][arm][stage])
                            or not _same_json(receipt.get("guard_expectations"), plan["guards"][arm][stage])
                            or receipt.get("cwd") != plan["arm_cwds"][arm]
                            or (receipt.get("raw_bundle") is not None) != plan["capture_raw"]):
                        raise ValueError("receipt differs from paired stage plan")
                    verdict = inspect_lifecycle(directory / filename, receipt, archived_bundle=bundle)
                    if receipt["sample"] is not None:
                        expected.add(filename)
                    elif (directory / filename).exists():
                        # A failed publication can leave a visible, unconfirmed
                        # regular sample. It is diagnostic only, never approved.
                        inspect_file(directory, filename, limit=1024 * 1024)
                        expected.add(filename)
                    inner = receipt["result"]
                    if inner is not None:
                        _measurement(inner, command, plan["arm_cwds"][arm])
                        capture = inner.get("raw_capture")
                        if capture is not None and capture["limit_per_stream_bytes"] != plan["raw_limit_bytes"]:
                            raise ValueError("raw capture limit differs from plan")
                    register_blobs(receipt)
                    interval = receipt["lifecycle"]
                    if last_end is not None and interval["monotonic_start_ns"] < last_end:
                        raise ValueError("recorded lifecycle intervals overlap or are out of order")
                    last_end = interval["monotonic_end_ns"]
                    lifecycle_counts[interval["status"]] += 1
                    if stage == "measurement":
                        attempted = True
                        result = inner or {"status": "harness_error", "error": "measurement did not return"}
                        guard, timing, finalized = receipt["observation_guard"], interval, verdict["lifecycle_finalized"]
                    if is_abort:
                        if not _same_json(abort["receipt"], receipt):
                            raise ValueError("abort receipt differs from stage receipt")
                        if abort["reason"] == "required_finalization_failed" and _safe_to_continue(receipt):
                            raise ValueError("abort has no observed publication/cleanup cause")
                        stopped, found_abort = True, True
                        reasons.append(abort["reason"])
                        if stage != "measurement":
                            result = {"status": "not_run_finalization_failed"}
                        break
                    if not _safe_to_continue(receipt):
                        raise ValueError("unsafe finalization without required abort record")
                    if stage != "measurement" and not _stage_ok(receipt):
                        skipped = "not_run_preparation_failed" if stage == "preparation" else "not_run_probe_failed"
            else:
                reasons.append("run_aborted")
            counts[result["status"]] += 1
            observed_arms += int(attempted)
            if guard is None and plan["guards"][arm]["measurement"] is not None:
                guard = check_observation(result, **plan["guards"][arm]["measurement"])
            guard_counts["not_requested" if guard is None else "matched" if guard["matched_expected_observations"] else "mismatched"] += 1
            if observations is not None:
                observations.append({"block": str(block["block"]), "arm": arm, "result": result,
                                     "guard": guard, "timing": timing, "lifecycle_finalized": finalized,
                                     "failure_reasons": reasons})
    if abort is not None and not found_abort:
        raise ValueError("abort does not name an observed stage")
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("unexpected or missing paired lifecycle files")
    if {path.name for path in bundle.iterdir()} != referenced:
        raise ValueError("unexpected or missing paired artifact blobs")
    return {"record_consistency": "aborted" if stopped else "complete", "mode": "exploratory_unqualified",
            "timing_endpoint": LIFECYCLE_ENDPOINT, "blocks": len(plan["schedule"]),
            "planned_arm_count": 2 * len(plan["schedule"]), "observed_arm_count": observed_arms,
            "arm_status_counts": dict(sorted(counts.items())), "stage_lifecycle_status_counts": dict(sorted(lifecycle_counts.items())),
            "observation_guard_counts": dict(sorted(guard_counts.items())), "recorded_interval_order": "nonoverlapping",
            "confirmatory_eligible": False,
            "limitations": ["historical observations are not authenticated", "only retained declared bytes checked",
                            "no work, generation, reset, current-state or resource qualification"]}
