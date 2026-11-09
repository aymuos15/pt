"""Pair fresh whole-session resource diagnostics, never relabel latency replays."""

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
import sys
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
import finalization as files
import managed_replay as replay
from metadata import collect_metadata
import paired_replay as workflow
import pt_bench as timer
import replay_resources as diagnostic
import resource_run as resources
from schedule import paired_schedule


KIND = "paired_replay_resource_campaign"
ARMS = workflow.ARMS
MAX_BLOCKS = workflow.MAX_BLOCKS
MAX_CAMPAIGN_FILES = 8192
MAX_CAMPAIGN_BYTES = 1024 * 1024 * 1024
FAILURES = (OSError, ValueError, RuntimeError, KeyboardInterrupt)
LIMITATIONS = [
    "separate whole-session resource diagnostics, never a rerun or relabelling of retained latency samples",
    "one fresh cgroup per considered session includes preparation, idle/background descendants, shutdown and driver reporting",
    "driver overhead is included; outer observer and paired publication are not in cgroup CPU/memory totals; no subtraction",
    "clean unsupported checks continue; failed or unconfirmed sessions stop all later work without retry",
    "all planned unsupported, failed, not-run and unknown sessions remain in the denominator; missing metrics are never zero",
    "observed CPU sums include failed-unit costs; memory maxima are per observed session, not a campaign peak",
    "shared workflow declarations are not verified edits, inputs, resets, equivalent resource budgets, work or generations",
    "driver clocks remain distinct from coordinator/outer-observer clocks; recorded order does not prove external isolation",
    "unknown native peak, idle-only attribution and independence remain unknown; no ratio, bootstrap or confirmatory claim",
    "historical bindings are unauthenticated; fingerprints are not atomic or a hostile-path boundary; publication is not power-loss durable",
]


@lru_cache(maxsize=1)
def _validators():
    root = Path(__file__).resolve().parent
    schemas = [json.loads((root / name).read_text()) for name in (
        "paired-replay-resource-v1.schema.json", "replay-resource-v1.schema.json", "paired-replay-v1.schema.json",
        "managed-replay-v1.schema.json", "resource-observation-v1.schema.json", "lifecycle-v2.schema.json",
        "result-card-v1.schema.json", "paired-resource-v1.schema.json",
    )]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry)
            for kind in ("plan", "session", "abort")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"paired replay resource {kind} schema at {path}: violates {error.validator}")
    if kind == "abort":
        if value["diagnostic_receipt"] is not None:
            diagnostic.validate("receipt", value["diagnostic_receipt"])
        if value["diagnostic_session"] is not None:
            validate("session", value["diagnostic_session"])


def _publish(path, value, kind):
    (diagnostic.validate if kind == "receipt" else validate)(kind, value)
    raw = diagnostic._raw(value)
    limit = files.MAX_RECEIPT_BYTES if kind in ("receipt", "abort") else files.MAX_RECORD_BYTES
    if len(raw) > limit:
        raise ValueError("paired replay resource record exceeds byte limit; no session may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=len(raw))
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("paired replay resource publication did not commit expected bytes")
    return diagnostic._binding(path.name, metadata), metadata


def _names(number, arm):
    return f"unit-{number:06d}-{arm}", f"receipt-{number:06d}-{arm}.json", f"block-{number:06d}-{arm}.json"


def validate_plan(plan):
    validate("plan", plan)
    # Reuse the fixed matched-workflow declaration contract, not its execution
    # or latency analysis. No resource observation is converted into that kind.
    workflow.validate_plan({**{key: plan[key] for key in ("schema_version", "mode", "schedule", "seed", "sessions", "pairing", "host_metadata")},
                            "kind": workflow.KIND, "measurement_layer": "managed_replay", "sample_unit": replay.UNIT,
                            "timing_endpoint": replay.ENDPOINT, "limitations": workflow.LIMITATIONS.copy()})
    options = plan["resources"]
    resources.validate_settings(options["outer_timeout_seconds"], options["allow_missing_peak"],
                                options["sample_interval_ns"] / 1e9, options["cleanup_grace_ns"] / 1e9)
    for session in plan["sessions"].values():
        minimum = session["execution_timeout_seconds"] + session["shutdown"]["timeout_seconds"] + diagnostic.WATCHDOG_SLACK_SECONDS
        if options["outer_timeout_seconds"] < minimum:
            raise ValueError("paired replay resource watchdog must cover execution, reserved shutdown and five seconds slack")
    if plan["limitations"] != LIMITATIONS or len(diagnostic._raw(plan)) > files.MAX_RECORD_BYTES:
        raise ValueError("paired replay resource plan limitations or byte limit differ")


def _snapshot(directory):
    files.require_safe_lookup()
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = files._fingerprint(os.fstat(fd))
        regular, units, count, total = {}, {}, 0, 0
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(regular) + len(units) >= 2 + 6 * MAX_BLOCKS:
                    raise ValueError("paired replay resource root entry count exceeds limit")
                files.relative_path(entry.name)
                if entry.is_file(follow_symlinks=False):
                    metadata, _ = files.inspect_file(directory, entry.name, limit=files.MAX_RECEIPT_BYTES)
                    regular[entry.name] = metadata
                    count, total = count + 1, total + metadata["bytes"]
                elif entry.is_dir(follow_symlinks=False) and re.fullmatch(r"unit-[0-9]{6}-(baseline|candidate)", entry.name):
                    captured = diagnostic._capture(directory / entry.name)
                    units[entry.name] = captured
                    count += len(captured[0]["files"])
                    total += captured[0]["total_bytes"]
                else:
                    raise ValueError("paired replay resource evidence contains nonregular input or an unexpected directory")
                if count > MAX_CAMPAIGN_FILES or total > MAX_CAMPAIGN_BYTES:
                    raise ValueError("paired replay resource evidence exceeds aggregate file/byte limit")
        named = os.stat(directory, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode) or files._fingerprint(named) != identity
                or files._fingerprint(os.fstat(fd)) != identity):
            raise ValueError("paired replay resource directory changed during read")
        return regular, units, identity
    finally:
        os.close(fd)


def run_pairs(output, baseline, candidate, blocks, seed, outer_timeout, *, pairing=None, cgroup_parent=None,
              baseline_cgroup_parent=None, candidate_cgroup_parent=None, allow_missing_peak=False,
              sample_interval=0.02, cleanup_grace=0.1):
    files.require_safe_lookup()
    if type(blocks) is not int or not 1 <= blocks <= MAX_BLOCKS:
        raise ValueError("paired replay resource blocks must be an integer from 1 to 64")
    resources.validate_settings(outer_timeout, allow_missing_peak, sample_interval, cleanup_grace)
    sessions = {}
    for arm, requested in (("baseline", baseline), ("candidate", candidate)):
        replay.validate_plan(requested)
        session = copy.deepcopy(requested)
        session["cwd"] = str(Path(session["cwd"]).resolve(strict=True))
        fd = os.open(session["cwd"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
        sessions[arm] = session
    parents = {"baseline": baseline_cgroup_parent, "candidate": candidate_cgroup_parent}
    parents = {arm: parent if parent is not None else cgroup_parent for arm, parent in parents.items()}
    parents = {arm: str(Path(os.path.abspath(parent))) if parent is not None else None for arm, parent in parents.items()}
    output = Path(os.path.abspath(output))
    driver = {"path": str(diagnostic.DRIVER), "sha256": hashlib.sha256(diagnostic.DRIVER.read_bytes()).hexdigest(),
              "python_executable": sys.executable}
    plan = {"schema_version": 1, "kind": KIND, "mode": "exploratory_unqualified", "measurement_layer": "resource_diagnostic",
            "sample_unit": replay.UNIT, "resource_endpoint": resources.ENDPOINT, "scope": diagnostic.SCOPE,
            "overhead_policy": diagnostic.OVERHEAD, "clock_alignment": diagnostic.CLOCK_ALIGNMENT,
            "schedule": paired_schedule(blocks, seed), "seed": seed, "sessions": sessions,
            "pairing": copy.deepcopy(pairing) if pairing is not None else {field: None for field in workflow.PAIRING_FIELDS},
            "resources": {"parents": parents, "outer_timeout_seconds": outer_timeout, "allow_missing_peak": allow_missing_peak,
                          "sample_interval_ns": round(sample_interval * 1e9), "cleanup_grace_ns": round(cleanup_grace * 1e9)},
            "output_root": str(output), "driver": driver, "observer_process": diagnostic.process_clock(),
            "host_metadata": collect_metadata(), "limitations": LIMITATIONS.copy()}
    validate_plan(plan)
    output.mkdir(mode=0o700)
    plan_binding, plan_identity = _publish(output / "schedule.json", plan, "plan")

    def abort(context, reason, error, *, call_clock=None, receipt=None, record=None):
        directory = output / _names(context["block"], context["arm"])[0]
        inputs = diagnostic._capture(directory)[0] if reason == "observation_error" and os.path.lexists(directory) else None
        value = {"schema_version": 1, "kind": "paired_replay_resource_abort", "mode": "exploratory_unqualified",
                 "context": context, "campaign_plan": plan_binding, "reason": reason, "error": error,
                 "call_clock": call_clock, "diagnostic_receipt": receipt, "diagnostic_session": record, "diagnostic_inputs": inputs}
        _publish(output / "abort.json", value, "abort")
        return inspect_pairs(output)

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = workflow._context(block["block"], position, arm)
            directory, receipt_name, record_name = _names(block["block"], arm)
            try:
                current, _ = files.inspect_file(output, "schedule.json", limit=files.MAX_RECORD_BYTES)
                if current != plan_identity or hashlib.sha256(diagnostic.DRIVER.read_bytes()).hexdigest() != driver["sha256"] or str(diagnostic.DRIVER) != driver["path"]:
                    raise ValueError("frozen paired resource plan or driver changed before a later session")
            except FAILURES as exc:
                return abort(context, "plan_binding_failed", f"{type(exc).__name__}: {exc}")
            start = time.monotonic_ns()
            try:
                receipt = diagnostic.run_observation(output / directory, sessions[arm], outer_timeout, cgroup_parent=parents[arm],
                                                      allow_missing_peak=allow_missing_peak, sample_interval=sample_interval, cleanup_grace=cleanup_grace)
            except FAILURES as exc:
                return abort(context, "observation_error", f"{type(exc).__name__}: {exc}", call_clock=timer._timing(start))
            call_clock = timer._timing(start)
            publication_start = time.monotonic_ns()
            try:
                binding, _ = _publish(output / receipt_name, receipt, "receipt")
            except FAILURES as exc:
                return abort(context, "receipt_publication_failed", f"{type(exc).__name__}: {exc}", call_clock=call_clock, receipt=receipt)
            record = {"schema_version": 1, "kind": "paired_replay_resource_session", "mode": "exploratory_unqualified",
                      "context": context, "campaign_plan": plan_binding, "receipt": binding,
                      "call_clock": call_clock, "receipt_publication_clock": timer._timing(publication_start)}
            try:
                summary, _guards, _request, _resource = _inspect_unit(output / directory, receipt, record, plan, context)
            except FAILURES as exc:
                return abort(context, "session_validation_failed", f"{type(exc).__name__}: {exc}", record=record)
            try:
                _publish(output / record_name, record, "session")
            except FAILURES as exc:
                return abort(context, "session_publication_failed", f"{type(exc).__name__}: {exc}", record=record)
            if summary["status"] == "failed":
                return abort(context, "session_failed", "whole-session resource observation, replay or required cleanup failed")
    return inspect_pairs(output)


def _inspect_unit(directory, receipt, record, plan, context):
    summary = diagnostic.inspect_observation(directory, receipt)
    request, _ = files.read_json(directory / "request.json")
    options = plan["resources"]
    expected = {"outer_timeout_seconds": options["outer_timeout_seconds"], "cgroup_parent": options["parents"][context["arm"]],
                **{key: options[key] for key in ("allow_missing_peak", "sample_interval_ns", "cleanup_grace_ns")}}
    if (not timer._same_json(request["replay_plan"], plan["sessions"][context["arm"]])
            or not timer._same_json(request["configuration"], expected) or not timer._same_json(request["driver"], plan["driver"])
            or request["output_root"] != str(Path(plan["output_root"]) / directory.name)):
        raise ValueError("whole-session resource request differs from paired arm plan, driver or settings")
    if not timer._same_json(receipt["observer_process"], plan["observer_process"]):
        raise ValueError("paired resource clocks do not share the declared coordinator/outer-observer process")
    replay._interval(record["call_clock"])
    replay._interval(receipt["observer_clock"], record["call_clock"])
    publication = record["receipt_publication_clock"]
    if publication is not None:
        replay._interval(publication)
        if publication["monotonic_start_ns"] < record["call_clock"]["monotonic_end_ns"]:
            raise ValueError("paired resource receipt publication precedes observation return")
    guards = None
    if summary["replay_summary"] is not None:
        driver, _ = files.read_json(directory / "driver.json", limit=files.MAX_RECEIPT_BYTES)
        inner = driver["receipt"]
        sample = files.read_json(directory / "session/unit.json", limit=replay.MAX_UNIT_BYTES)[0] if inner["sample"] is not None else inner["diagnostic_sample"]
        guards = Counter()
        for row in sample["steps"]:
            phase = row["receipt"]
            state = ("not_observed" if phase is None else "not_requested" if phase["guard_expectations"] is None else
                     "matched" if phase["observation_guard"] and phase["observation_guard"]["matched_expected_observations"] else "mismatched")
            guards[state] += 1
        guards = dict(sorted(guards.items()))
    raw = (files.read_json(directory / "resource.json", limit=files.MAX_RECEIPT_BYTES)[0]
           if receipt["resource"] is not None else receipt["diagnostic_resource"])
    return summary, guards, request, raw


def _thin(context, session, summary=None, guards=None, *, status="not_run_run_aborted", receipt_committed=False, record_committed=False, reasons=None, raw=None):
    count, interactions = len(replay._steps(session)), len(session["interactions"])
    row = {"context": context, "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT,
           "status": status, "resource_status": None, "session_status": "unknown" if status == "harness_error" else status,
           "session_invocation_attempted": None if status == "harness_error" else False,
           "boundary_run_attempted": None if status == "harness_error" else False,
           "unit_observation_returned": summary is not None, "receipt_record_committed": receipt_committed,
           "session_record_committed": record_committed, "phase_guard_counts": guards, "elapsed_ns": None,
           "planned_phase_count": count, "planned_interaction_count": interactions,
           "phase_status_counts": {"unknown" if status == "harness_error" else status: count},
           "interaction_status_counts": {"unknown" if status == "harness_error" else status: interactions},
           "known_phase_invocation_attempts": 0, "known_not_invoked_phases": count if status != "harness_error" else 0,
           "unknown_phase_invocations": count if status == "harness_error" else 0, "shutdown_status": None,
           "driver_completion_confirmed": False, "resource_record_confirmed": False,
           "counter_boundary_accounting_complete": False, "whole_session_accounting_complete": False,
           "replay_summary": None, "observer_process": None, "driver_process": None,
           **{field: None for field in ("cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes", "memory_events_delta",
                                        "unsupported_capabilities", "resource_failure_reasons")}, "failure_reasons": reasons or []}
    if summary is not None:
        keys = ("status", "resource_status", "session_status", "session_invocation_attempted", "phase_status_counts", "interaction_status_counts",
                "known_phase_invocation_attempts", "known_not_invoked_phases", "unknown_phase_invocations", "shutdown_status",
                "driver_completion_confirmed", "resource_record_confirmed", "counter_boundary_accounting_complete", "whole_session_accounting_complete",
                "replay_summary", "observer_process", "driver_process", "cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes",
                "memory_events_delta", "unsupported_capabilities", "resource_failure_reasons")
        row.update({key: summary[key] for key in keys})
        row["failure_reasons"] = [*summary["failure_reasons"], *(reasons or [])]
        row["boundary_run_attempted"] = raw["run_attempted"] if raw is not None else None
    return row


def inspect_pairs(directory, plan=None, *, observations=None):
    directory = Path(directory)
    before = _snapshot(directory)
    actual, metadata = files.read_json(directory / "schedule.json")
    validate_plan(actual)
    if plan is not None and not timer._same_json(plan, actual):
        raise ValueError("paired resource inspection plan differs from retained bytes")
    plan, binding = actual, diagnostic._binding("schedule.json", metadata)
    expected, abort = {"schedule.json"}, None
    if "abort.json" in before[0]:
        abort, _ = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)
        validate("abort", abort)
        if not timer._same_json(abort["campaign_plan"], binding):
            raise ValueError("paired replay resource abort plan byte binding differs")
        expected.add("abort.json")
    stopped = found_abort = False
    rows, last_end, group_paths, invocation_ids = [], None, set(), set()

    def read(name, kind):
        value, meta = files.read_json(directory / name, limit=files.MAX_RECEIPT_BYTES if kind == "receipt" else files.MAX_RECORD_BYTES)
        (diagnostic.validate if kind == "receipt" else validate)(kind, value)
        expected.add(name)
        return value, meta

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = workflow._context(block["block"], position, arm)
            row = _thin(context, plan["sessions"][arm])
            unit_name, receipt_name, record_name = _names(block["block"], arm)
            is_abort = abort is not None and timer._same_json(abort["context"], context)
            if stopped:
                row["failure_reasons"] = ["run_aborted"]
                rows.append(row)
                continue
            reason = abort["reason"] if is_abort else None
            receipt = record = None
            receipt_committed = record_committed = False
            if reason in ("observation_error", "plan_binding_failed"):
                if abort["diagnostic_receipt"] is not None or abort["diagnostic_session"] is not None:
                    raise ValueError("paired resource no-return abort invents returned evidence")
                if reason == "observation_error":
                    if abort["call_clock"] is None:
                        raise ValueError("paired resource missing-return call lacks an interval")
                    replay._interval(abort["call_clock"])
                    if last_end is not None and abort["call_clock"]["monotonic_start_ns"] < last_end:
                        raise ValueError("paired resource call intervals overlap or are out of order")
                    captured = before[1].get(unit_name)
                    if not timer._same_json(abort["diagnostic_inputs"], captured[0] if captured is not None else None):
                        raise ValueError("paired resource missing-return diagnostic inputs differ")
                    if captured is not None:
                        expected.add(unit_name)
                elif abort["call_clock"] is not None or abort["diagnostic_inputs"] is not None:
                    raise ValueError("paired resource pre-call abort invents invocation evidence")
                row = _thin(context, plan["sessions"][arm], status="harness_error" if reason == "observation_error" else "not_run_plan_changed", reasons=[reason])
            else:
                if reason == "receipt_publication_failed":
                    receipt = abort["diagnostic_receipt"]
                    if receipt is None or abort["call_clock"] is None or abort["diagnostic_session"] is not None or abort["diagnostic_inputs"] is not None:
                        raise ValueError("paired resource receipt-publication abort lacks matching evidence")
                    if receipt_name in before[0]:
                        visible, _ = read(receipt_name, "receipt")
                        if not timer._same_json(visible, receipt):
                            raise ValueError("unconfirmed paired resource receipt contradicts diagnostic copy")
                    record = {"call_clock": abort["call_clock"], "receipt_publication_clock": None}
                else:
                    receipt, receipt_metadata = read(receipt_name, "receipt")
                    receipt_committed = True
                    if reason in ("session_publication_failed", "session_validation_failed"):
                        record = abort["diagnostic_session"]
                        if record is None:
                            raise ValueError("paired resource missing diagnostic session metadata")
                        validate("session", record)
                        if record_name in before[0]:
                            visible, _ = read(record_name, "session")
                            if not timer._same_json(visible, record):
                                raise ValueError("unconfirmed paired resource session contradicts diagnostic copy")
                    else:
                        record, _ = read(record_name, "session")
                        record_committed = True
                    if (not timer._same_json(record["context"], context) or not timer._same_json(record["campaign_plan"], binding)
                            or not timer._same_json(record["receipt"], diagnostic._binding(receipt_name, receipt_metadata))):
                        raise ValueError("paired resource session context or byte bindings differ from fixed plan")
                    if is_abort and (abort["call_clock"] is not None or abort["diagnostic_receipt"] is not None or abort["diagnostic_inputs"] is not None
                                     or (reason == "session_failed" and abort["diagnostic_session"] is not None)):
                        raise ValueError("paired resource session abort contains unrelated diagnostic evidence")
                summary, guards, request, raw = _inspect_unit(directory / unit_name, receipt, record, plan, context)
                expected.add(unit_name)
                if last_end is not None and record["call_clock"]["monotonic_start_ns"] < last_end:
                    raise ValueError("paired whole-session resource intervals overlap or are out of order")
                last_end = (record["receipt_publication_clock"] or record["call_clock"])["monotonic_end_ns"]
                if request["invocation_id"] in invocation_ids:
                    raise ValueError("resource replay invocation identity reused across sessions")
                invocation_ids.add(request["invocation_id"])
                group = raw["group"] if raw is not None else None
                if group is not None:
                    if group["path"] in group_paths:
                        raise ValueError("private resource group reused across whole-session units")
                    group_paths.add(group["path"])
                if reason == "session_failed" and summary["status"] != "failed":
                    raise ValueError("paired resource session-failed abort lacks an observed failure")
                if reason is None and summary["status"] == "failed":
                    raise ValueError("failed paired resource session lacks the required abort record")
                row = _thin(context, plan["sessions"][arm], summary, guards, receipt_committed=receipt_committed,
                            record_committed=record_committed, reasons=[reason] if reason is not None else [], raw=raw)
            if is_abort:
                stopped = found_abort = True
            rows.append(row)
    if abort is not None and not found_abort:
        raise ValueError("paired resource abort does not name a planned session")
    if set(before[0]) | set(before[1]) != expected:
        raise ValueError("unexpected or missing paired replay resource records or unit directories")
    if _snapshot(directory) != before:
        raise ValueError("paired replay resource evidence changed during inspection")
    if observations is not None:
        observations.extend(rows)
    phases, interactions = Counter(), Counter()
    for row in rows:
        phases.update(row["phase_status_counts"])
        interactions.update(row["interaction_status_counts"])
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    return {"record_consistency": "aborted" if stopped else "complete", "kind": KIND, "mode": "exploratory_unqualified",
            "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT, "resource_endpoint": resources.ENDPOINT,
            "resource_scope": diagnostic.SCOPE, "overhead_policy": diagnostic.OVERHEAD, "clock_alignment": diagnostic.CLOCK_ALIGNMENT,
            "blocks": len(plan["schedule"]), "schedule": plan["schedule"], "planned_arm_count": len(rows), "planned_session_count": len(rows),
            "unit_observation_count": sum(row["unit_observation_returned"] for row in rows),
            "observed_session_count": sum(row["replay_summary"] is not None for row in rows),
            "known_session_invocations": sum(row["session_invocation_attempted"] is True for row in rows),
            "unknown_session_invocations": sum(row["session_invocation_attempted"] is None for row in rows),
            "known_not_invoked_sessions": sum(row["session_invocation_attempted"] is False for row in rows),
            "known_boundary_invocations": sum(row["boundary_run_attempted"] is True for row in rows),
            "unknown_boundary_invocations": sum(row["boundary_run_attempted"] is None for row in rows),
            "known_not_invoked_boundaries": sum(row["boundary_run_attempted"] is False for row in rows),
            "arm_status_counts": counts, "session_status_counts": counts,
            "replay_session_status_counts": dict(sorted(Counter(row["session_status"] for row in rows).items())), "session_observations": rows,
            "planned_phase_count": sum(row["planned_phase_count"] for row in rows), "phase_status_counts": dict(sorted(phases.items())),
            **{key: sum(row[key] for row in rows) for key in ("known_phase_invocation_attempts", "known_not_invoked_phases", "unknown_phase_invocations")},
            "planned_interaction_count": sum(row["planned_interaction_count"] for row in rows), "interaction_status_counts": dict(sorted(interactions.items())),
            "pairing": plan["pairing"], "pairing_identity_status": "declared_only_unverified" if all(plan["pairing"][field] is not None for field in workflow.PAIRING_FIELDS) else "unresolved",
            "recorded_interval_order": "nonoverlapping_coordinator_and_outer_observer_only", "observer_process": plan["observer_process"],
            "all_session_accounting_complete": not stopped and all(row["whole_session_accounting_complete"] and row["receipt_record_committed"] and row["session_record_committed"] for row in rows),
            "verified_independent_sessions": None, "verified_independent_blocks": None, "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def summarize(inspection, observations):
    contexts = [workflow._context(block["block"], position, arm) for block in inspection["schedule"] for position, arm in enumerate(block["order"], 1)]
    if (not timer._same_json(observations, inspection["session_observations"])
            or len(observations) != inspection["planned_session_count"] or len(observations) != 2 * inspection["blocks"]
            or not timer._same_json([row["context"] for row in observations], contexts)
            or any(row["sample_unit"] != replay.UNIT or row["measurement_layer"] != "resource_diagnostic" for row in observations)):
        raise ValueError("paired resource summary requires every inspected whole-session observation in order")
    blockers = []
    if inspection["record_consistency"] != "complete":
        blockers.append({"context": None, "reasons": ["campaign_aborted"]})
    if inspection["pairing_identity_status"] != "declared_only_unverified":
        blockers.append({"context": None, "reasons": ["pairing_identity_unresolved"]})
    for row in observations:
        reasons = row["failure_reasons"].copy()
        if not row["whole_session_accounting_complete"]:
            reasons.append("whole_session_accounting_incomplete")
        if not row["receipt_record_committed"] or not row["session_record_committed"]:
            reasons.append("paired_publication_unconfirmed")
        if row["phase_guard_counts"] != {"matched": row["planned_phase_count"]}:
            reasons.append("phase_guards_not_all_matched")
        if row["replay_summary"] is not None and row["replay_summary"]["raw_capture_truncated_phase_count"]:
            reasons.append("raw_capture_truncated")
        if reasons:
            blockers.append({"context": row["context"], "reasons": list(dict.fromkeys(reasons))})
    per_arm = {}
    for arm in ARMS:
        units = [row for row in observations if row["context"]["arm"] == arm]
        metrics = {}
        for name, extract, result_name, aggregate in (
            ("cpu_usage_usec", lambda row: (row["cpu_delta_usec"] or {}).get("usage_usec"), "observed_sum", sum),
            ("peak_charged_bytes", lambda row: row["peak_charged_bytes"], "maximum_observed_per_session", max),
            ("sampled_current_max_bytes", lambda row: row["sampled_current_max_bytes"], "maximum_observed_per_session", max),
        ):
            values = [extract(row) for row in units if extract(row) is not None]
            metrics[name] = {"observed_units": len(values), "unknown_units": len(units) - len(values), result_name: aggregate(values) if values else None}
        per_arm[arm] = {"planned_sessions": len(units), "unit_observations": sum(row["unit_observation_returned"] for row in units),
                        "completed_replay_observations": sum(row["session_status"] == "completed_unqualified" for row in units),
                        "complete_accounting_sessions": sum(row["whole_session_accounting_complete"] for row in units), **metrics}
    return {**inspection, "status": "blocked" if blockers else "diagnostic_resource_observations", "blockers": blockers,
            "per_arm_resources": per_arm, "per_arm_resources_unit": "complete_session_including_driver_not_measurement_stage_only",
            "memory_metric": resources.MEMORY_METRIC, "whole_campaign_peak_charged_bytes": None,
            "idle_only_resource_metrics": None, "per_phase_resource_metrics": None, "ratio": None, "absolute_latency_ns": None, "bootstrap": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-plan", type=Path, required=True)
    parser.add_argument("--candidate-plan", type=Path, required=True)
    parser.add_argument("--blocks", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--outer-timeout", type=float, required=True)
    parser.add_argument("--pairing-json")
    parser.add_argument("--cgroup-parent", type=Path)
    parser.add_argument("--baseline-cgroup-parent", type=Path)
    parser.add_argument("--candidate-cgroup-parent", type=Path)
    parser.add_argument("--allow-missing-peak", action="store_true")
    parser.add_argument("--sample-interval", type=float, default=0.02)
    parser.add_argument("--cleanup-grace", type=float, default=0.1)
    args = parser.parse_args()
    try:
        baseline, _ = files.read_json(args.baseline_plan, limit=replay.MAX_PLAN_BYTES)
        candidate, _ = files.read_json(args.candidate_plan, limit=replay.MAX_PLAN_BYTES)
        pairing = files.parse_json(args.pairing_json) if args.pairing_json is not None else None
        report = run_pairs(args.output, baseline, candidate, args.blocks, args.seed, args.outer_timeout, pairing=pairing,
                           cgroup_parent=args.cgroup_parent, baseline_cgroup_parent=args.baseline_cgroup_parent,
                           candidate_cgroup_parent=args.candidate_cgroup_parent, allow_missing_peak=args.allow_missing_peak,
                           sample_interval=args.sample_interval, cleanup_grace=args.cleanup_grace)
        summary = summarize(report, report["session_observations"])
    except (OSError, ValueError) as exc:
        parser.exit(2, f"paired-replay-resources: {exc}\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report["record_consistency"] == "aborted" else 3 if all(row["status"] == "unsupported" for row in report["session_observations"]) else 0 if summary["status"] == "diagnostic_resource_observations" else 1


if __name__ == "__main__":
    raise SystemExit(main())
