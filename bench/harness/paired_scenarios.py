"""Paired declared-file scenario validation; no retries, inferred resets or timing claims."""

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
import stat
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
import finalization as files
from metadata import collect_metadata
import paired_replay as workflow
import pt_bench as timer
from result_card import capture_run, _canonical
import scenario_replay as scenario
from schedule import paired_schedule


KIND = "paired_scenario_replay_campaign"
ARMS = ("baseline", "candidate")
MAX_BLOCKS = 64
MAX_FILES = 8192
MAX_BYTES = 1024 * 1024 * 1024
MAX_DECLARED_BYTES = 512 * 1024 * 1024
FAILURES = scenario.FAILURES
LIMITATIONS = [
    "paired correctness-instrumented declared-file scenarios, never unmodified-product latency or native resource observations",
    "every scheduled arm is a fresh explicit reset/edit/request/shutdown unit; commands are serial and never automatically retried",
    "frozen input bytes, seeds and guarded edits are bound; consumption, loaded code, complete inputs and reset equivalence remain unverified",
    "clean unsupported profiles continue without effects; failed or unconfirmed units stop all later sessions without rollback",
    "all failed, unknown and not-run sessions, requests, phases and file effects remain in the planned denominator",
    "complete-looking files after a lost whole-unit return are bound diagnostics, never recovered observations or successful resets",
    "scenario observers run in the coordinator process; only declared same-process call/publication order is checked",
    "paired receipt and metadata publication are observer work outside the scenario endpoint; no overhead is subtracted",
    "host/cache declarations and matching file states do not qualify independence, external services, environments, budgets or semantic work",
    "history is unauthenticated; fingerprints are not atomic or a hostile-path boundary; private publication is not power-loss durable",
]


@lru_cache(maxsize=1)
def _validators():
    root = Path(__file__).resolve().parent
    schemas = [json.loads((root / name).read_text()) for name in (
        "paired-scenario-v1.schema.json", "scenario-replay-v1.schema.json", "paired-replay-v1.schema.json",
        "managed-replay-v1.schema.json", "lifecycle-v2.schema.json", "result-card-v1.schema.json",
        "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry) for kind in ("plan", "session", "abort")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"paired scenario {kind} schema at {path}: violates {error.validator}")


def _publish(path, value, kind):
    (scenario.validate if kind == "receipt" else validate)(kind, value)
    raw = scenario._raw(value)
    limit = files.MAX_RECEIPT_BYTES if kind in ("receipt", "abort") else files.MAX_RECORD_BYTES
    if len(raw) > limit:
        raise ValueError("paired scenario record exceeds byte limit; no planned outcome may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=limit)
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("paired scenario publication did not commit expected bytes")
    return scenario._binding(path.name, metadata), metadata


def _declaration(plan):
    return {**{key: plan[key] for key in ("scenario", "input_seed", "reset", "execution_timeout_seconds")},
            "requests": [{**{key: request[key] for key in ("id", "edits", "input")},
                          "timeout_seconds": request["command"]["timeout_seconds"],
                          "expected_exit_code": request["command"]["required_finalization"]["expected_exit_code"]}
                         for request in plan["requests"]],
            "shutdown_policy": {"timeout_seconds": plan["shutdown"]["timeout_seconds"],
                                "expected_exit_code": plan["shutdown"]["required_finalization"]["expected_exit_code"]}}


def _digest(value):
    return hashlib.sha256(b"pt:paired-scenario:declared-workflow:v1\n" + _canonical(value)).hexdigest()


def _payload_entries(plan):
    values = {value["sha256"]: value for state in scenario._states(plan) for value in state.values() if value is not None}
    return [{"path": digest, "bytes": values[digest]["bytes"], "sha256": digest} for digest in sorted(values)]


def validate_plan(plan):
    validate("plan", plan)
    if plan["limitations"] != LIMITATIONS or not timer._same_json(plan["schedule"], paired_schedule(len(plan["schedule"]), plan["seed"])):
        raise ValueError("paired scenario schedule, seed or limitations differ from contract")
    declared = 0
    for arm in ARMS:
        session = plan["sessions"][arm]
        scenario.validate_plan(session)
        commands = [request["command"] for request in session["requests"]] + [session["shutdown"]]
        declared += sum(item["bytes"] for item in _payload_entries(session))
        declared += sum(item["bytes"] for command in commands for item in command["required_finalization"]["artifacts"])
    if declared * len(plan["schedule"]) > MAX_DECLARED_BYTES:
        raise ValueError("paired scenario repeated declared input/artifact budget exceeds limit")
    first, second = (Path(plan["sessions"][arm]["cwd"]) for arm in ARMS)
    if first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError("paired scenario requires separate nonnested arm working directories")
    baseline, candidate = (_declaration(plan["sessions"][arm]) for arm in ARMS)
    if not timer._same_json(baseline, candidate) or plan["workflow_sha256"] != _digest(baseline):
        raise ValueError("paired scenario reset/edit/input/seed/cache/budget declarations must match exactly")
    entries = _payload_entries(plan["sessions"]["baseline"])
    if not timer._same_json(plan["frozen_payloads"]["files"], entries) or plan["frozen_payloads"]["directories"]:
        raise ValueError("paired scenario frozen payload inventory differs from exact declared input bytes")
    if len(scenario._raw(plan)) > files.MAX_RECORD_BYTES:
        raise ValueError("paired scenario plan exceeds byte limit")


def _snapshot(directory):
    files.require_safe_lookup()
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = files._fingerprint(os.fstat(fd))
        regular, units, payloads, count, total = {}, {}, None, 0, 0
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(regular) + len(units) >= 3 + 6 * MAX_BLOCKS:
                    raise ValueError("paired scenario root entry count exceeds limit")
                if entry.is_file(follow_symlinks=False):
                    metadata, _ = files.inspect_file(directory, entry.name, limit=files.MAX_RECEIPT_BYTES)
                    regular[entry.name] = metadata
                    count += 1
                    total += metadata["bytes"]
                elif entry.is_dir(follow_symlinks=False) and (entry.name == "payloads" or re.fullmatch(r"session-[0-9]{6}-(baseline|candidate)", entry.name)):
                    captured = capture_run(directory / entry.name)
                    if entry.name == "payloads":
                        payloads = captured
                    else:
                        units[entry.name] = captured
                    count += len(captured[0]["files"])
                    total += captured[0]["total_bytes"]
                else:
                    raise ValueError("paired scenario contains nonregular input or an unexpected directory")
                if count > MAX_FILES or total > MAX_BYTES:
                    raise ValueError("paired scenario evidence exceeds aggregate file/byte limit")
        named = os.stat(directory, follow_symlinks=False)
        if not stat.S_ISDIR(named.st_mode) or files._fingerprint(named) != identity or files._fingerprint(os.fstat(fd)) != identity:
            raise ValueError("paired scenario directory changed during inspection")
        return regular, units, payloads, identity
    finally:
        os.close(fd)


def run_pairs(output, baseline, candidate, payload_root, blocks, seed, *, apply=False):
    if type(apply) is not bool or not apply:
        raise ValueError("explicit --apply is required for paired scenario reset/edit effects")
    files.require_safe_lookup()
    if type(blocks) is not int or not 1 <= blocks <= MAX_BLOCKS:
        raise ValueError("paired scenario blocks must be an integer from 1 to 64")
    sessions = copy.deepcopy({"baseline": baseline, "candidate": candidate})
    for session in sessions.values():
        scenario.validate_plan(session)
        session["cwd"] = str(Path(session["cwd"]).resolve(strict=True))
    payload_root = Path(payload_root).resolve(strict=True)
    output = Path(os.path.abspath(output))
    roots = [*[Path(session["cwd"]) for session in sessions.values()], payload_root, output.parent.resolve(strict=True) / output.name]
    if any(left.is_relative_to(right) or right.is_relative_to(left) for index, left in enumerate(roots) for right in roots[index + 1:]):
        raise ValueError("paired scenario worktrees, payload source and evidence must be separate nonnested roots")
    for root in roots[:-1]:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
    # A declaration-only provisional inventory lets all plan conflicts and all
    # source payload bytes be rejected before a reset, edit or subject starts.
    from result_card import _inventory
    frozen = _inventory([], _payload_entries(sessions["baseline"]))
    plan = {"schema_version": 1, "kind": KIND, "mode": "exploratory_unqualified", "measurement_layer": scenario.LAYER,
            "sample_unit": scenario.UNIT, "timing_endpoint": scenario.ENDPOINT, "schedule": paired_schedule(blocks, seed), "seed": seed,
            "sessions": sessions, "workflow_sha256": _digest(_declaration(sessions["baseline"])), "frozen_payloads": frozen,
            "clock_policy": "coordinator_process_scenario_api_calls_only", "host_metadata": collect_metadata(), "limitations": LIMITATIONS.copy()}
    validate_plan(plan)
    for session in sessions.values():
        scenario._payloads(session, payload_root)
    output.mkdir(mode=0o700)
    (output / "payloads").mkdir(mode=0o700)
    for session in sessions.values():
        scenario._payloads(session, payload_root, output / "payloads")
    frozen_capture = capture_run(output / "payloads")
    if not timer._same_json(frozen_capture[0], frozen):
        raise ValueError("paired scenario payload freezing differs from declared bytes")
    binding, identity = _publish(output / "schedule.json", plan, "plan")

    def abort(context, reason, exc, *, call_clock=None, receipt=None, record=None):
        unit = output / workflow._names(context["block"], context["arm"])[0]
        retained = capture_run(unit)[0] if reason == "observation_error" and os.path.lexists(unit) else None
        value = {"schema_version": 1, "kind": "paired_scenario_abort", "mode": "exploratory_unqualified", "context": context,
                 "campaign_plan": binding, "reason": reason, "error": f"{type(exc).__name__}: {exc}", "call_clock": call_clock,
                 "diagnostic_receipt": receipt, "diagnostic_session": record, "diagnostic_inputs": retained}
        _publish(output / "abort.json", value, "abort")
        return inspect_pairs(output)

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = workflow._context(block["block"], position, arm)
            unit_name, receipt_name, record_name = workflow._names(block["block"], arm)
            try:
                current, _ = files.inspect_file(output, "schedule.json", limit=files.MAX_RECORD_BYTES)
                if current != identity or capture_run(output / "payloads") != frozen_capture:
                    raise ValueError("frozen paired scenario plan or input payloads changed before a later session")
            except FAILURES as exc:
                return abort(context, "plan_binding_failed", exc)
            started = time.monotonic_ns()
            try:
                receipt = scenario.run_scenario(output / unit_name, sessions[arm], output / "payloads", apply=True)
            except FAILURES as exc:
                return abort(context, "observation_error", exc, call_clock=timer._timing(started))
            clock = timer._timing(started)
            publication_start = time.monotonic_ns()
            try:
                receipt_binding, _ = _publish(output / receipt_name, receipt, "receipt")
            except FAILURES as exc:
                return abort(context, "receipt_publication_failed", exc, call_clock=clock, receipt=receipt)
            record = {"schema_version": 1, "kind": "paired_scenario_session", "mode": "exploratory_unqualified", "context": context,
                      "campaign_plan": binding, "receipt": receipt_binding, "call_clock": clock, "receipt_publication_clock": timer._timing(publication_start)}
            try:
                _inspect_session(output / unit_name, receipt, record, sessions[arm])
            except FAILURES as exc:
                return abort(context, "session_validation_failed", exc, record=record)
            try:
                _publish(output / record_name, record, "session")
            except FAILURES as exc:
                return abort(context, "session_publication_failed", exc, record=record)
            if receipt["status"] == "aborted":
                return abort(context, "session_failed", RuntimeError("scenario reset, edit, request, shutdown or observation failed"))
    return inspect_pairs(output)


def _inspect_session(directory, receipt, record, expected):
    summary = scenario.inspect_scenario(directory, receipt)
    actual, _ = files.read_json(directory / "plan.json", limit=scenario.MAX_PLAN_BYTES)
    if not timer._same_json(actual, expected):
        raise ValueError("scenario session plan differs from its exact paired arm declaration")
    scenario.replay._interval(record["call_clock"])
    scenario.replay._interval(receipt["clock"], record["call_clock"])
    publication = record["receipt_publication_clock"]
    if publication is not None:
        scenario.replay._interval(publication)
        if publication["monotonic_start_ns"] < record["call_clock"]["monotonic_end_ns"]:
            raise ValueError("paired scenario receipt publication precedes its returned observation")
    unit = files.read_json(directory / "unit.json", limit=scenario.MAX_UNIT_BYTES)[0] if receipt["unit"] is not None else receipt["diagnostic_unit"]
    return summary, unit


def _operation_counts(plan):
    return len(plan["reset"]) + sum(len(request["edits"]) + 1 for request in plan["requests"])


def _row(context, plan, *, status="not_run_campaign_aborted", called=False, summary=None, unit=None, receipt_committed=False, record_committed=False, reasons=None):
    unobserved = status == "harness_error"
    unknown = "unknown_unobserved" if unobserved else status
    request_count, phase_count, operations = len(plan["requests"]), len(scenario._sequence(plan)), _operation_counts(plan)
    row = {"context": context, "measurement_layer": scenario.LAYER, "sample_unit": scenario.UNIT, "status": status,
           "unit_call_attempted": called, "unit_observation_returned": summary is not None,
           "receipt_record_committed": receipt_committed, "session_record_committed": record_committed,
           "planned_request_count": request_count, "request_status_counts": {unknown: request_count},
           "known_request_invocations": 0, "unknown_request_invocations": request_count if unobserved else 0,
           "known_not_invoked_requests": 0 if unobserved else request_count,
           "planned_phase_count": phase_count, "phase_status_counts": {unknown: phase_count},
           "planned_file_effect_count": operations, "file_effect_status_counts": {"unknown_unobserved" if unobserved else "not_run": operations},
           "reset_status": unknown, "reset_evidence": None, "shutdown_status": unknown,
           "shutdown_invocation_attempted": None if unobserved else False,
           "request_observations": [{"id": request["id"], "status": unknown, "invocation_attempted": None if unobserved else False,
                                      "input_path": request["input"]["path"], "expected_input": request["input"]["value"],
                                      "input_delivery_status": "unknown_unobserved" if unobserved else "not_run", "observed_input": None}
                                     for request in plan["requests"]], "failure_reasons": reasons or [], "scenario_summary": summary}
    if summary is None:
        return row
    for key in ("status", "request_status_counts", "known_request_invocations", "unknown_request_invocations", "known_not_invoked_requests", "phase_status_counts", "reset_status", "shutdown_status"):
        row[key] = summary[key]
    phases = unit["phases"]
    row.update(reset_evidence=phases[0], shutdown_invocation_attempted=phases[-1]["command_invocation_attempted"])
    counts = Counter()
    for phase in phases:
        if phase["role"] in ("reset", "transition"):
            expected = len(plan["reset"]) if phase["role"] == "reset" else len(next(request for request in plan["requests"] if request["id"] == phase["id"])["edits"]) + 1
            counts.update(op["status"] for op in phase["operations"])
            if not phase["operations"]:
                counts["not_run"] += expected
    row["file_effect_status_counts"] = dict(sorted(counts.items()))
    for request, observed in zip(plan["requests"], row["request_observations"]):
        phase = next(phase for phase in phases if phase["role"] == "request" and phase["id"] == request["id"])
        transition = next(phase for phase in phases if phase["role"] == "transition" and phase["id"] == request["id"])
        operation = next((op for op in transition["operations"] if op["path"] == request["input"]["path"]), None)
        actual = next((item for item in phase["before"]["files"] if item["path"] == request["input"]["path"]), None) if phase["before"] is not None else None
        observed.update(status=phase["status"], invocation_attempted=phase["command_invocation_attempted"],
                        input_delivery_status=operation["status"] if operation is not None else "not_run", observed_input=actual)
    if sum(counts.values()) != operations:
        raise ValueError("paired scenario file-effect denominator differs from complete plan")
    return row


def inspect_pairs(directory, plan=None, *, observations=None):
    directory = Path(directory)
    snapshot = _snapshot(directory)
    actual, metadata = files.read_json(directory / "schedule.json")
    validate_plan(actual)
    if plan is not None and not timer._same_json(plan, actual):
        raise ValueError("paired scenario inspection plan differs from retained bytes")
    plan, binding = actual, scenario._binding("schedule.json", metadata)
    if snapshot[2] is None or not timer._same_json(snapshot[2][0], plan["frozen_payloads"]):
        raise ValueError("paired scenario frozen payload bytes differ from the campaign binding")
    for session in plan["sessions"].values():
        scenario._payloads(session, directory / "payloads")
    expected, abort = {"schedule.json", "payloads"}, None
    if "abort.json" in snapshot[0]:
        abort, _ = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)
        validate("abort", abort)
        if not timer._same_json(abort["campaign_plan"], binding):
            raise ValueError("paired scenario abort plan byte binding differs")
        expected.add("abort.json")
    stopped = found_abort = False
    rows, last = [], None

    def read(name, kind):
        value, meta = files.read_json(directory / name, limit=files.MAX_RECEIPT_BYTES if kind == "receipt" else files.MAX_RECORD_BYTES)
        (scenario.validate if kind == "receipt" else validate)(kind, value)
        expected.add(name)
        return value, meta

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = workflow._context(block["block"], position, arm)
            unit_name, receipt_name, record_name = workflow._names(block["block"], arm)
            row = _row(context, plan["sessions"][arm])
            if stopped:
                row["failure_reasons"] = ["campaign_aborted"]
                rows.append(row)
                continue
            is_abort = abort is not None and timer._same_json(abort["context"], context)
            reason = abort["reason"] if is_abort else None
            if reason in ("observation_error", "plan_binding_failed"):
                if abort["diagnostic_receipt"] is not None or abort["diagnostic_session"] is not None:
                    raise ValueError("paired scenario no-return abort invents a returned observation")
                if reason == "observation_error":
                    if abort["call_clock"] is None:
                        raise ValueError("paired scenario missing-return call has no clock")
                    scenario.replay._interval(abort["call_clock"])
                    if last is not None and abort["call_clock"]["monotonic_start_ns"] < last:
                        raise ValueError("paired scenario call intervals overlap or are out of order")
                    captured = snapshot[1].get(unit_name)
                    if not timer._same_json(abort["diagnostic_inputs"], captured[0] if captured is not None else None):
                        raise ValueError("paired scenario lost-return diagnostic inventory differs")
                    if captured is not None:
                        expected.add(unit_name)
                elif abort["call_clock"] is not None or abort["diagnostic_inputs"] is not None:
                    raise ValueError("paired scenario pre-call abort invents invocation evidence")
                row = _row(context, plan["sessions"][arm], status="harness_error" if reason == "observation_error" else "not_run_plan_changed",
                           called=reason == "observation_error", reasons=[reason])
            else:
                receipt_committed = record_committed = False
                if reason == "receipt_publication_failed":
                    receipt = abort["diagnostic_receipt"]
                    if receipt is None or abort["call_clock"] is None or abort["diagnostic_session"] is not None or abort["diagnostic_inputs"] is not None:
                        raise ValueError("paired scenario receipt-publication abort lacks matching evidence")
                    if receipt_name in snapshot[0]:
                        visible, _ = read(receipt_name, "receipt")
                        if not timer._same_json(visible, receipt):
                            raise ValueError("unconfirmed paired scenario receipt contradicts diagnostic copy")
                    record = {"call_clock": abort["call_clock"], "receipt_publication_clock": None}
                else:
                    receipt, receipt_metadata = read(receipt_name, "receipt")
                    receipt_committed = True
                    if reason in ("session_validation_failed", "session_publication_failed"):
                        record = abort["diagnostic_session"]
                        if record is None:
                            raise ValueError("paired scenario metadata abort lacks a diagnostic session")
                        validate("session", record)
                        if record_name in snapshot[0]:
                            visible, _ = read(record_name, "session")
                            if not timer._same_json(visible, record):
                                raise ValueError("unconfirmed paired scenario metadata contradicts diagnostic copy")
                    else:
                        record, _ = read(record_name, "session")
                        record_committed = True
                    if (not timer._same_json(record["context"], context) or not timer._same_json(record["campaign_plan"], binding)
                            or not timer._same_json(record["receipt"], scenario._binding(receipt_name, receipt_metadata))):
                        raise ValueError("paired scenario session context, plan or receipt binding differs")
                    if is_abort and (abort["call_clock"] is not None or abort["diagnostic_receipt"] is not None or abort["diagnostic_inputs"] is not None
                                     or reason == "session_failed" and abort["diagnostic_session"] is not None):
                        raise ValueError("paired scenario abort contains unrelated observation evidence")
                summary, unit = _inspect_session(directory / unit_name, receipt, record, plan["sessions"][arm])
                expected.add(unit_name)
                if last is not None and record["call_clock"]["monotonic_start_ns"] < last:
                    raise ValueError("paired scenario call intervals overlap or are out of order")
                last = (record["receipt_publication_clock"] or record["call_clock"])["monotonic_end_ns"]
                if reason == "session_failed" and summary["status"] != "aborted":
                    raise ValueError("paired scenario failure abort lacks an observed failed unit")
                if reason is None and summary["status"] == "aborted":
                    raise ValueError("failed paired scenario unit lacks its required abort")
                row = _row(context, plan["sessions"][arm], called=True, summary=summary, unit=unit,
                           receipt_committed=receipt_committed, record_committed=record_committed, reasons=[reason] if reason else [])
            if is_abort:
                stopped = found_abort = True
            rows.append(row)
    if abort is not None and not found_abort:
        raise ValueError("paired scenario abort does not name a planned session")
    if set(snapshot[0]) | set(snapshot[1]) | {"payloads"} != expected:
        raise ValueError("unexpected or missing paired scenario evidence, including work after abort")
    if _snapshot(directory) != snapshot:
        raise ValueError("paired scenario evidence changed during inspection")
    if observations is not None:
        observations.extend(rows)
    requests, phases, effects = Counter(), Counter(), Counter()
    for row in rows:
        requests.update(row["request_status_counts"])
        phases.update(row["phase_status_counts"])
        effects.update(row["file_effect_status_counts"])
    return {"kind": KIND, "record_consistency": "aborted" if stopped else "complete", "mode": "exploratory_unqualified",
            "measurement_layer": scenario.LAYER, "sample_unit": scenario.UNIT, "timing_endpoint": scenario.ENDPOINT,
            "blocks": len(plan["schedule"]), "schedule": plan["schedule"], "workflow_sha256": plan["workflow_sha256"],
            "planned_session_count": len(rows), "observed_session_count": sum(row["unit_observation_returned"] for row in rows),
            "attempted_unit_calls": sum(row["unit_call_attempted"] for row in rows),
            "known_not_called_units": sum(not row["unit_call_attempted"] for row in rows),
            "unconfirmed_unit_calls": sum(row["unit_call_attempted"] and not row["unit_observation_returned"] for row in rows),
            "session_status_counts": dict(sorted(Counter(row["status"] for row in rows).items())), "session_observations": rows,
            "planned_request_count": sum(row["planned_request_count"] for row in rows), "request_status_counts": dict(sorted(requests.items())),
            **{key: sum(row[key] for row in rows) for key in ("known_request_invocations", "unknown_request_invocations", "known_not_invoked_requests")},
            "planned_phase_count": sum(row["planned_phase_count"] for row in rows), "phase_status_counts": dict(sorted(phases.items())),
            "planned_file_effect_count": sum(row["planned_file_effect_count"] for row in rows), "file_effect_status_counts": dict(sorted(effects.items())),
            "reset_status_counts": dict(sorted(Counter(row["reset_status"] for row in rows).items())),
            "known_shutdown_invocations": sum(row["shutdown_invocation_attempted"] is True for row in rows),
            "unknown_shutdown_invocations": sum(row["shutdown_invocation_attempted"] is None for row in rows),
            "known_not_invoked_shutdowns": sum(row["shutdown_invocation_attempted"] is False for row in rows),
            "declared_pairing_status": "exact_declared_workflow_and_frozen_bytes_bound_unqualified",
            "recorded_interval_order": "nonoverlapping_single_coordinator_scenario_api_calls",
            "qualification": {key: None for key in scenario.QUALIFICATION}, "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def summarize(inspection, observations):
    contexts = [workflow._context(block["block"], position, arm) for block in inspection["schedule"] for position, arm in enumerate(block["order"], 1)]
    if (not timer._same_json(observations, inspection["session_observations"]) or len(observations) != 2 * inspection["blocks"]
            or len(observations) != inspection["planned_session_count"] or not timer._same_json([row["context"] for row in observations], contexts)
            or any(row["measurement_layer"] != scenario.LAYER or row["sample_unit"] != scenario.UNIT for row in observations)):
        raise ValueError("paired scenario summary requires every inspected session in schedule order")
    blockers = []
    if inspection["record_consistency"] != "complete":
        blockers.append({"context": None, "reasons": ["campaign_aborted"]})
    for row in observations:
        reasons = row["failure_reasons"].copy()
        if row["status"] != "completed_unqualified":
            reasons.append("scenario_validation_not_complete")
        if not row["receipt_record_committed"] or not row["session_record_committed"]:
            reasons.append("paired_publication_unconfirmed")
        if reasons:
            blockers.append({"context": row["context"], "reasons": list(dict.fromkeys(reasons))})
    per_arm = {}
    for arm in ARMS:
        rows = [row for row in observations if row["context"]["arm"] == arm]
        per_arm[arm] = {"planned_sessions": len(rows), "observed_sessions": sum(row["unit_observation_returned"] for row in rows),
                        "completed_scenarios": sum(row["status"] == "completed_unqualified" for row in rows),
                        "matched_declared_resets": sum(row["reset_status"] == "observed_unqualified" for row in rows),
                        "observed_input_payloads": sum(request["observed_input"] is not None and request["observed_input"]["status"] == "present"
                                                       and timer._same_json(request["observed_input"]["value"], request["expected_input"])
                                                       for row in rows for request in row["request_observations"])}
    return {**inspection, "status": "blocked" if blockers else "declared_file_scenario_observations", "blockers": blockers,
            "per_arm": per_arm, "all_declared_scenario_observations_complete": not blockers,
            "ratio": None, "absolute_latency_ns": None, "bootstrap": None, "resource_observation": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-plan", type=Path, required=True)
    parser.add_argument("--candidate-plan", type=Path, required=True)
    parser.add_argument("--payloads", type=Path, required=True)
    parser.add_argument("--blocks", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        baseline, _ = files.read_json(args.baseline_plan, limit=scenario.MAX_PLAN_BYTES)
        candidate, _ = files.read_json(args.candidate_plan, limit=scenario.MAX_PLAN_BYTES)
        inspection = run_pairs(args.output, baseline, candidate, args.payloads, args.blocks, args.seed, apply=args.apply)
        value = summarize(inspection, inspection["session_observations"])
    except (OSError, ValueError) as exc:
        parser.exit(2, f"paired-scenarios: {exc}\n")
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return 2 if value["record_consistency"] == "aborted" else 3 if all(row["status"] == "unsupported" for row in value["session_observations"]) else 1 if value["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
