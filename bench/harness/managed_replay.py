"""Execute one explicit session sequence once; never automatically retry failed work."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types, validate_v2
import finalization as files
from guards import validate_expectations
from inspect_run import _measurement
import pt_bench as timer
from result_card import capture_run, _inventory


ENDPOINT = "managed_session_api_entry_through_shutdown_unit_publication_and_declared_finalization_v1"
UNIT = "complete_managed_session_replay"
MAX_PLAN_BYTES = 256 * 1024
MAX_UNIT_BYTES = 3 * 1024 * 1024
FILE_SCOPE = "declared_files_and_absences_only"
LIMITATIONS = [
    "one exploratory session unit; interactions are correlated steps, not independent samples",
    "fresh serial commands and declared state only; no daemon, service-lease or execution-interpreter reuse qualification",
    "same-session pytest semantics, source generations, reset equivalence and equal work are not verified",
    "shutdown is attempted once after plan publication, even if the execution budget prevents preparation; SIGKILL, host loss and repeated interrupts cannot guarantee cleanup",
    "process-group observations and file absences do not prove descendant containment or external-resource release",
    "CPU, memory, idle residency and complete resource budgets are not established by wall-clock replay",
    "post-endpoint receipt construction and transport are observer work; no power-loss durability or authenticity claim",
    "caller-owned paths and before/after checks are not an authenticated atomic snapshot",
]


@lru_cache(maxsize=1)
def _validators():
    root = Path(__file__).resolve().parent
    schemas = [json.loads((root / name).read_text()) for name in (
        "managed-replay-v1.schema.json", "lifecycle-v2.schema.json", "result-card-v1.schema.json",
        "paired-resource-v1.schema.json", "resource-observation-v1.schema.json",
    )]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry)
            for kind in ("plan", "sample", "receipt")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"managed replay {kind} schema at {path}: violates {error.validator}")
    if kind == "sample":
        for step in value["steps"]:
            if step["receipt"] is not None:
                validate_v2("receipt", step["receipt"])
    if kind == "receipt" and value["diagnostic_sample"] is not None:
        validate("sample", value["diagnostic_sample"])


def _steps(plan):
    return [("preparation", plan["preparation"]), *[("interaction", step) for step in plan["interactions"]],
            ("shutdown", plan["shutdown"])]


def validate_plan(plan):
    validate("plan", plan)
    ids, contracts = set(), [plan["finalization"]]
    for role, step in _steps(plan):
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", step["id"]) is None:
            raise ValueError("managed replay IDs must be bounded normalized labels")
        if step["id"] in ids or (role == "interaction" and step["id"] in ("preparation", "shutdown")):
            raise ValueError("managed replay step IDs must be unique and nonreserved")
        ids.add(step["id"])
        contract = files.requirements(step["required_finalization"])
        if not timer._same_json(contract, step["required_finalization"]):
            raise ValueError("managed replay step contract must be canonical")
        if role != "interaction" and contract["expected_exit_code"] != 0:
            raise ValueError("preparation and shutdown require expected exit zero")
        guard = step["guard_expectations"]
        if guard is not None:
            validate_expectations(guard)
            if guard["expected_exit_code"] != contract["expected_exit_code"]:
                raise ValueError("managed replay guard and declared exit conflict")
        contracts.append(contract)
    if not timer._same_json(files.requirements(plan["finalization"]), plan["finalization"]):
        raise ValueError("managed replay final file contract must be canonical")
    raw_budget = 2 * plan["raw_limit_bytes"] * len(_steps(plan)) if plan["capture_raw"] else 0
    if (sum(len(contract["artifacts"]) for contract in contracts) > 1000
            or raw_budget + sum(item["bytes"] for contract in contracts for item in contract["artifacts"]) > 384 * 1024 * 1024):
        raise ValueError("managed replay aggregate declared artifact/raw budget exceeds limit")
    if len(_serialize(plan)) > MAX_PLAN_BYTES:
        raise ValueError("managed replay plan exceeds byte limit")


def _serialize(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _publish(path, value, kind, limit):
    validate(kind, value)
    raw = _serialize(value)
    if len(raw) > limit:
        raise ValueError("managed replay record exceeds byte limit; no planned steps may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=len(raw))
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("managed replay publication did not commit expected bytes")
    return {"name": path.name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]}, metadata


def _error(stage, exc):
    return {"stage": stage, "error": f"{type(exc).__name__}: {exc}"}


def _file_observation(root, contract):
    observed = files.check(None, root, contract)
    checks = [item for item in observed["checks"] if item["kind"] != "process"]
    return {"scope": FILE_SCOPE, "matched": all(item["matched"] for item in checks), "checks": checks}


def _with_process(observed):
    # Reuse existing file-contract validation without inventing a session process
    # or return code. This internal process check is explicitly false, not evidence.
    return {"scope": files.SCOPE, "matched": False,
            "checks": [{"kind": "process", "matched": False}, *observed["checks"]]}


def _check_file_observation(contract, observed):
    files.validate_observed({}, contract, _with_process(observed), capture_raw=False)
    if observed["scope"] != FILE_SCOPE or observed["matched"] != all(item["matched"] for item in observed["checks"]):
        raise ValueError("managed replay final file verdict contradicts checks")


def _row(index, role, step, status):
    return {"index": index, "role": role, "id": step["id"], "status": status,
            "measurement_layer": "managed_replay_step", "sample_unit": "replay_step",
            "invocation_attempted": False, "effective_timeout_seconds": None, "timeout_computed_at_ns": None,
            "clock": None, "idle_clock": None, "receipt": None, "error": None}


def _ok(row):
    receipt = row["receipt"]
    return (row["error"] is None and receipt is not None
            and receipt["lifecycle"]["status"] == "finalized_unqualified"
            and (receipt["observation_guard"] is None or receipt["observation_guard"]["matched_expected_observations"]))


def _observe(index, role, step, plan, output, deadline):
    row = _row(index, role, step, "harness_error")
    start = time.monotonic_ns()
    try:
        if role != "shutdown" and start >= deadline:
            row["status"] = "not_run_execution_deadline"
            return row
        idle_start = time.monotonic_ns()
        try:
            delay = step["idle_before_seconds"]
            if delay:
                time.sleep(min(delay, max(0, deadline - idle_start) / 1e9))
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
            row.update(status="not_run_interrupted" if isinstance(exc, KeyboardInterrupt) else "not_run_idle_error",
                       error=_error("idle", exc))
            return row
        finally:
            row["idle_clock"] = timer._timing(idle_start)
        computed_at = time.monotonic_ns()
        left = (deadline - computed_at) / 1e9
        if role != "shutdown" and left <= 0:
            row["status"] = "not_run_execution_deadline"
            return row
        row["effective_timeout_seconds"] = step["timeout_seconds"] if role == "shutdown" else min(left, step["timeout_seconds"])
        row["timeout_computed_at_ns"] = computed_at
        row["invocation_attempted"] = None  # An exception after entry cannot prove no launch.
        try:
            receipt = timer.measure_and_publish(
                step["argv"], plan["cwd"], row["effective_timeout_seconds"], output / f"step-{index:04d}.json",
                required_finalization=step["required_finalization"], guard_expectations=step["guard_expectations"],
                archive_bundle=output / "blobs", raw_bundle=output / "blobs" if plan["capture_raw"] else None,
                raw_limit_bytes=plan["raw_limit_bytes"],
            )
            row["receipt"] = receipt
            row["invocation_attempted"] = True if receipt["result"] is not None else None
            try:
                timer.inspect_lifecycle(output / f"step-{index:04d}.json", receipt, archived_bundle=output / "blobs")
            except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
                row["error"] = _error("step_validation", exc)
            row["status"] = "observed_unqualified" if _ok(row) else "failed"
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
            row["error"] = _error("observation", exc)
    finally:
        row["clock"] = timer._timing(start)
    return row


def _inputs(output):
    inventory, identities = capture_run(output)
    inputs = [item for item in inventory["files"] if item["path"] != "unit.json"]
    return _inventory(inventory["directories"], inputs), {item["path"]: identities[item["path"]] for item in inputs}


def _references(steps, archived):
    references = {"plan.json"}
    for row in steps:
        receipt = row["receipt"]
        if receipt is None:
            continue
        if receipt["sample"] is not None:
            references.add(receipt["sample"]["name"])
        if receipt["artifact_archive"] is not None:
            references.update("blobs/" + item["sha256"] for item in receipt["artifact_archive"]["artifacts"])
        capture = (receipt["result"] or {}).get("raw_capture")
        if capture is not None:
            references.update("blobs/" + capture[stream]["sha256"] for stream in ("stdout", "stderr"))
    if archived is not None:
        references.update("blobs/" + item["sha256"] for item in archived["artifacts"])
    return references


def _fragments(sample):
    references = _references(sample["steps"], sample["artifact_archive"])
    unknown = {f"step-{row['index']:04d}.json" for row in sample["steps"]
               if row["receipt"] is None and row["error"] is not None and row["error"]["stage"] == "observation"}
    unconfirmed = {f"step-{row['index']:04d}.json" for row in sample["steps"]
                   if row["receipt"] is not None and row["receipt"]["sample"] is None}
    extra_blobs_allowed = bool(unknown) or any(item["stage"] == "artifact_archive" for item in sample["errors"])
    result = []
    for item in sample["retained_inputs"]["files"]:
        name = item["path"]
        if name in references:
            continue
        if (name in unknown or name in unconfirmed
                or (extra_blobs_allowed and re.fullmatch(r"blobs/[0-9a-f]{64}", name) is not None)):
            result.append(item)
        else:
            raise ValueError("unexpected replay evidence is not an attributable diagnostic fragment")
    return result


def _outcome(sample, binding, after, errors):
    reasons = []
    if any(not _ok(row) for row in sample["steps"]):
        reasons.append("planned_steps_incomplete_or_failed")
    if not _ok(sample["steps"][-1]):
        reasons.append("required_shutdown_not_completed")
    if sample["required_finalization"]["observed"] is None or not sample["required_finalization"]["observed"]["matched"] or after is None or not after["matched"]:
        reasons.append("declared_finalization_not_matched")
    if binding is None:
        reasons.append("unit_publication_unconfirmed")
    if sample["diagnostic_fragments"]:
        reasons.append("unconfirmed_diagnostic_fragments")
    if sample["errors"] or errors:
        reasons.append("observer_or_finalization_error")
    infrastructure = bool(sample["errors"] or errors or any(
        row["error"] is not None or (row["receipt"] is not None and row["receipt"]["errors"]) for row in sample["steps"]))
    return {"status": "aborted" if reasons else "completed_unqualified", "reasons": reasons, "infrastructure_failure": infrastructure}


def run_replay(output, requested):
    start = time.monotonic_ns()
    files.require_safe_lookup()
    validate_plan(requested)
    plan = copy.deepcopy(requested)
    plan["cwd"] = str(Path(plan["cwd"]).resolve(strict=True))
    cwd_fd = os.open(plan["cwd"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(cwd_fd)
    output = Path(os.path.abspath(output))
    output.mkdir(mode=0o700)
    (output / "blobs").mkdir(mode=0o700)
    plan_publication_start = time.monotonic_ns()
    binding, plan_identity = _publish(output / "plan.json", plan, "plan", MAX_PLAN_BYTES)
    plan_publication_clock = timer._timing(plan_publication_start)
    deadline = start + round(plan["execution_timeout_seconds"] * 1e9)
    rows, stopped = [], False
    sequence = _steps(plan)
    try:
        for index, (role, step) in enumerate(sequence[:-1], 1):
            if stopped:
                rows.append(_row(index, role, step, "not_run_prior_failure"))
                continue
            check_start = time.monotonic_ns()
            try:
                current, _ = files.inspect_file(output, "plan.json", limit=MAX_PLAN_BYTES)
                if current != plan_identity:
                    raise ValueError("frozen replay plan changed before a later command")
            except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
                row = _row(index, role, step, "not_run_plan_changed")
                row.update(clock=timer._timing(check_start), error=_error("plan_binding", exc))
                rows.append(row)
                stopped = True
                continue
            row = _observe(index, role, step, plan, output, deadline)
            rows.append(row)
            stopped = not _ok(row)
    finally:
        # Cleanup is a distinct explicit command, not a replay of failed work.
        # Its own finite budget is reserved even when the execution budget expired.
        role, step = sequence[-1]
        rows.append(_observe(len(sequence), role, step, plan, output, deadline))
    post_shutdown_start = time.monotonic_ns()
    errors, observed, archived = [], None, None
    try:
        observed = _file_observation(Path(plan["cwd"]), plan["finalization"])
        archived = files.archive(Path(plan["cwd"]), observed, output / "blobs")
        if archived["errors"]:
            errors.append({"stage": "artifact_archive", "error": "required final artifact archival failed"})
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        errors.append(_error("finalization_observation" if observed is None else "artifact_archive", exc))
    retained, retained_identities = _inputs(output)
    sample = {"schema_version": 1, "kind": "managed_session_replay_sample", "mode": "exploratory_unqualified",
              "sample_unit": UNIT, "measurement_layer": "managed_replay", "plan": binding, "steps": rows,
              "required_finalization": {"requirements": plan["finalization"], "observed": observed},
              "artifact_archive": archived, "errors": errors, "retained_inputs": retained, "diagnostic_fragments": [],
              "post_shutdown_clock": None}
    sample["diagnostic_fragments"] = _fragments(sample)
    sample["post_shutdown_clock"] = timer._timing(post_shutdown_start)
    post_errors, unit_binding, unit_identity = [], None, None
    publication_start = time.monotonic_ns()
    try:
        unit_binding, unit_identity = _publish(output / "unit.json", sample, "sample", MAX_UNIT_BYTES)
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        post_errors.append(_error("unit_publication", exc))
    unit_publication_clock = timer._timing(publication_start)
    finalization_start = time.monotonic_ns()
    after = None
    try:
        after = _file_observation(Path(plan["cwd"]), plan["finalization"])
        if not timer._same_json(observed, after):
            post_errors.append({"stage": "finalization_recheck", "error": "declared final files changed across unit publication"})
        current_plan, _ = files.inspect_file(output, "plan.json", limit=MAX_PLAN_BYTES)
        if current_plan != plan_identity:
            raise ValueError("replay plan changed after publication")
        if _inputs(output) != (retained, retained_identities):
            raise ValueError("retained replay inputs changed across unit publication")
        if unit_binding is not None:
            current_unit, _ = files.inspect_file(output, "unit.json", limit=MAX_UNIT_BYTES)
            if current_unit != unit_identity:
                raise ValueError("replay unit changed after publication")
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        post_errors.append(_error("retained_input_binding", exc))
    finalization_clock = timer._timing(finalization_start)
    receipt = {"schema_version": 1, "kind": "managed_session_replay_receipt", "mode": "exploratory_unqualified",
               "confirmatory_eligible": False, "timing_endpoint": ENDPOINT, "sample_unit": UNIT,
               "clock": timer._timing(start), "plan_publication_clock": plan_publication_clock,
               "unit_publication_clock": unit_publication_clock, "finalization_clock": finalization_clock,
               "plan": binding, "sample": unit_binding,
               "diagnostic_sample": sample if unit_binding is None else None,
               "finalization_after_publication": after, "errors": post_errors,
               "outcome": _outcome(sample, unit_binding, after, post_errors), "limitations": LIMITATIONS.copy()}
    validate("receipt", receipt)
    if len(_serialize(receipt)) > files.MAX_RECEIPT_BYTES:
        raise ValueError("managed replay receipt exceeds byte limit; the unit remains unconfirmed")
    return receipt


def _interval(value, outer=None):
    if value["elapsed_ns"] != value["monotonic_end_ns"] - value["monotonic_start_ns"] or value["elapsed_ns"] < 0:
        raise ValueError("managed replay interval arithmetic is inconsistent")
    if outer is not None and (value["monotonic_start_ns"] < outer["monotonic_start_ns"] or value["monotonic_end_ns"] > outer["monotonic_end_ns"]):
        raise ValueError("managed replay step or idle interval is outside its session")


def inspect_replay(output, receipt):
    """Validate one historical whole-session unit; never rerun steps or current-state checks."""
    output = Path(output)
    validate("receipt", receipt)
    if len(_serialize(receipt)) > files.MAX_RECEIPT_BYTES:
        raise ValueError("managed replay receipt exceeds byte limit")
    if receipt["limitations"] != LIMITATIONS:
        raise ValueError("managed replay limitations differ from the supported contract")
    _interval(receipt["clock"])
    _interval(receipt["plan_publication_clock"], receipt["clock"])
    _interval(receipt["unit_publication_clock"], receipt["clock"])
    _interval(receipt["finalization_clock"], receipt["clock"])
    if any(item["stage"] not in ("unit_publication", "finalization_recheck", "retained_input_binding") for item in receipt["errors"]):
        raise ValueError("managed replay receipt error belongs to a different observation stage")
    snapshot = capture_run(output)
    plan, plan_metadata = files.read_json(output / "plan.json", limit=MAX_PLAN_BYTES)
    validate_plan(plan)
    expected_plan = {"name": "plan.json", "bytes": plan_metadata["bytes"], "sha256": plan_metadata["sha256"]}
    if not timer._same_json(receipt["plan"], expected_plan):
        raise ValueError("managed replay plan byte binding does not match")
    if receipt["sample"] is not None:
        sample, metadata = files.read_json(output / "unit.json", limit=MAX_UNIT_BYTES)
        if not timer._same_json(receipt["sample"], {"name": "unit.json", "bytes": metadata["bytes"], "sha256": metadata["sha256"]}):
            raise ValueError("managed replay unit byte binding does not match")
    else:
        sample = receipt["diagnostic_sample"]
        if not any(item["stage"] == "unit_publication" for item in receipt["errors"]):
            raise ValueError("missing replay unit without publication failure evidence")
        if (output / "unit.json").exists():
            visible, _ = files.read_json(output / "unit.json", limit=MAX_UNIT_BYTES)
            if not timer._same_json(visible, sample):
                raise ValueError("failed replay unit publication contradicts diagnostic copy")
    validate("sample", sample)
    if any(item["stage"] not in ("finalization_observation", "artifact_archive") for item in sample["errors"]):
        raise ValueError("managed replay unit error belongs to a different observation stage")
    if not timer._same_json(sample["plan"], expected_plan) or not timer._same_json(sample["required_finalization"]["requirements"], plan["finalization"]):
        raise ValueError("managed replay sample differs from plan or final file contract")
    sequence = _steps(plan)
    if len(sample["steps"]) != len(sequence):
        raise ValueError("managed replay omitted a planned phase")
    stopped, previous_end = False, receipt["plan_publication_clock"]["monotonic_end_ns"]
    deadline = receipt["clock"]["monotonic_start_ns"] + round(plan["execution_timeout_seconds"] * 1e9)
    for index, ((role, step), row) in enumerate(zip(sequence, sample["steps"]), 1):
        if row["index"] != index or row["role"] != role or row["id"] != step["id"]:
            raise ValueError("managed replay step order or identity differs from plan")
        if stopped and role != "shutdown":
            if row != _row(index, role, step, "not_run_prior_failure"):
                raise ValueError("managed replay interaction ran after an earlier failure")
            continue
        if row["clock"] is None:
            raise ValueError("managed replay considered phase is missing its interval")
        _interval(row["clock"], receipt["clock"])
        if row["clock"]["monotonic_start_ns"] < previous_end:
            raise ValueError("managed replay phase intervals overlap or are out of order")
        previous_end = row["clock"]["monotonic_end_ns"]
        if row["idle_clock"] is not None:
            _interval(row["idle_clock"], row["clock"])
        inner = row["receipt"]
        if inner is not None:
            if row["error"] is not None and row["error"]["stage"] != "step_validation":
                raise ValueError("managed replay returned phase has an unrelated observation error")
            validate_v2("receipt", inner)
            if (inner["context"] is not None or inner["cwd"] != plan["cwd"]
                    or not timer._same_json(inner["required_finalization"]["requirements"], step["required_finalization"])
                    or not timer._same_json(inner["guard_expectations"], step["guard_expectations"])
                    or (inner["raw_bundle"] is not None) != plan["capture_raw"]):
                raise ValueError("replay phase receipt differs from its declared command contract")
            timer.inspect_lifecycle(output / f"step-{index:04d}.json", inner, archived_bundle=output / "blobs")
            _interval(inner["lifecycle"], row["clock"])
            if row["idle_clock"] is None or inner["lifecycle"]["monotonic_start_ns"] < row["idle_clock"]["monotonic_end_ns"]:
                raise ValueError("managed replay invocation precedes its idle interval")
            if inner["result"] is not None:
                _measurement(inner["result"], step["argv"], plan["cwd"])
                capture = inner["result"].get("raw_capture")
                if capture is not None and capture["limit_per_stream_bytes"] != plan["raw_limit_bytes"]:
                    raise ValueError("managed replay raw capture limit differs from plan")
            if row["invocation_attempted"] is not (True if inner["result"] is not None else None):
                raise ValueError("managed replay invocation certainty contradicts returned result")
            if row["status"] != ("observed_unqualified" if _ok(row) else "failed"):
                raise ValueError("managed replay phase status contradicts observed receipt")
        else:
            if row["status"] == "not_run_execution_deadline":
                if role == "shutdown" or row["clock"]["monotonic_end_ns"] < deadline or row["error"] is not None:
                    raise ValueError("managed replay deadline skip lacks an exhausted execution budget")
            elif row["status"] in ("not_run_interrupted", "not_run_idle_error"):
                if row["error"] is None or row["error"]["stage"] != "idle" or row["idle_clock"] is None:
                    raise ValueError("managed replay interrupted idle lacks evidence")
            elif row["status"] == "not_run_plan_changed":
                if role == "shutdown" or row["error"] is None or row["error"]["stage"] != "plan_binding":
                    raise ValueError("managed replay plan skip lacks a binding failure")
            elif row["status"] != "harness_error" or row["error"] is None or row["error"]["stage"] != "observation":
                raise ValueError("managed replay missing phase receipt without observation error")
            expected_attempt = None if row["status"] == "harness_error" else False
            if row["invocation_attempted"] is not expected_attempt:
                raise ValueError("managed replay absent observation has invented invocation certainty")
        effective = row["effective_timeout_seconds"]
        computed_at = row["timeout_computed_at_ns"]
        if inner is not None or row["status"] == "harness_error":
            if (computed_at is None or row["idle_clock"] is None
                    or not row["idle_clock"]["monotonic_end_ns"] <= computed_at <= row["clock"]["monotonic_end_ns"]
                    or (inner is not None and computed_at > inner["lifecycle"]["monotonic_start_ns"])):
                raise ValueError("managed replay command budget timestamp is outside its phase boundary")
            expected = step["timeout_seconds"] if role == "shutdown" else min((deadline - computed_at) / 1e9, step["timeout_seconds"])
            if effective is None or not 0 < effective == expected:
                raise ValueError("managed replay effective command timeout differs from budget")
            if row["idle_clock"]["elapsed_ns"] < round(step["idle_before_seconds"] * 1e9):
                raise ValueError("managed replay omitted a requested idle interval")
        elif effective is not None or computed_at is not None:
            raise ValueError("managed replay non-invoked phase invents a command timeout")
        if role != "shutdown":
            stopped = not _ok(row)
    _interval(sample["post_shutdown_clock"], receipt["clock"])
    if (sample["post_shutdown_clock"]["monotonic_start_ns"] < previous_end
            or receipt["unit_publication_clock"]["monotonic_start_ns"] < sample["post_shutdown_clock"]["monotonic_end_ns"]
            or receipt["finalization_clock"]["monotonic_start_ns"] < receipt["unit_publication_clock"]["monotonic_end_ns"]):
        raise ValueError("managed replay publication/finalization precedes required shutdown or reporting")
    before, after = sample["required_finalization"]["observed"], receipt["finalization_after_publication"]
    archived = sample["artifact_archive"]
    if before is None:
        if archived is not None or not any(item["stage"] == "finalization_observation" for item in sample["errors"]):
            raise ValueError("managed replay missing final file observation without error")
    else:
        _check_file_observation(plan["finalization"], before)
        if archived is None:
            if not any(item["stage"] == "artifact_archive" for item in sample["errors"]):
                raise ValueError("managed replay missing final archive without error")
        else:
            historical = files.archived_check({}, plan["finalization"], _with_process(before), archived, output / "blobs", capture_raw=False)
            if not timer._same_json(historical, _with_process(before)):
                raise ValueError("managed replay final files contradict retained historical bytes")
            if bool(archived["errors"]) != any(item["stage"] == "artifact_archive" for item in sample["errors"]):
                raise ValueError("managed replay final archive errors contradict status")
    if after is not None:
        _check_file_observation(plan["finalization"], after)
    if not timer._same_json(before, after) and not any(item["stage"] in ("finalization_recheck", "retained_input_binding") for item in receipt["errors"]):
        raise ValueError("managed replay changed finalization has no failure evidence")
    if not timer._same_json(_inputs(output)[0], sample["retained_inputs"]):
        raise ValueError("managed replay retained input inventory differs from bound bytes")
    if sample["diagnostic_fragments"] != _fragments(sample):
        raise ValueError("managed replay diagnostic fragments differ from attributable retained bytes")
    if not timer._same_json(receipt["outcome"], _outcome(sample, receipt["sample"], after, receipt["errors"])):
        raise ValueError("managed replay terminal outcome contradicts failures or missing work")
    if capture_run(output) != snapshot:
        raise ValueError("managed replay evidence changed during inspection")
    interactions = [row for row in sample["steps"] if row["role"] == "interaction"]
    return {"record_consistency": "checked_unqualified", "status": receipt["outcome"]["status"], "timing_endpoint": ENDPOINT,
            "sample_unit": UNIT, "observed_session_count": 1, "verified_independent_units": None,
            "planned_interaction_count": len(interactions), "interaction_status_counts": dict(sorted(Counter(row["status"] for row in interactions).items())),
            "planned_phase_count": len(sequence), "phase_status_counts": dict(sorted(Counter(row["status"] for row in sample["steps"]).items())),
            "known_phase_invocation_attempts": sum(row["invocation_attempted"] is True for row in sample["steps"]),
            "unknown_phase_invocations": sum(row["invocation_attempted"] is None for row in sample["steps"]),
            "known_not_invoked_phases": sum(row["invocation_attempted"] is False for row in sample["steps"]),
            "raw_capture_truncated_phase_count": sum(bool(row["receipt"] and (row["receipt"]["result"] or {}).get("raw_capture")
                and any(row["receipt"]["result"]["raw_capture"][stream]["truncated"] for stream in ("stdout", "stderr"))) for row in sample["steps"]),
            "unconfirmed_diagnostic_fragment_count": len(sample["diagnostic_fragments"]),
            "shutdown_status": sample["steps"][-1]["status"], "session_elapsed_ns": receipt["clock"]["elapsed_ns"],
            "interaction_analysis": "correlated_step_diagnostics_only", "ratio": None, "absolute_latency_comparison_ns": None, "bootstrap": None,
            "resource_observation": None, "whole_boundary_resource_accounting_complete": False,
            "confirmatory_eligible": False, "evidence_inventory_sha256": sample["retained_inputs"]["sha256"],
            "outcome_reasons": receipt["outcome"]["reasons"], "limitations": LIMITATIONS.copy()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="closed fixed replay JSON plan")
    parser.add_argument("--output", type=Path, required=True, help="new private evidence directory; receipt is emitted on stdout")
    args = parser.parse_args()
    try:
        plan, _ = files.read_json(args.plan, limit=MAX_PLAN_BYTES)
        receipt = run_replay(args.output, plan)
        print(json.dumps(receipt, sort_keys=True, allow_nan=False), flush=True)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"managed-replay: {exc}\n")
    if receipt["outcome"]["infrastructure_failure"]:
        return 2
    return 0 if receipt["outcome"]["status"] == "completed_unqualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
