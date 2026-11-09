"""Pair complete managed sessions once, retaining every failed and not-run unit."""

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

from analysis import guarded_exploratory_bootstrap, guarded_exploratory_ratio
from evidence import StrictValidator, validate_json_types
import finalization as files
import managed_replay as replay
from metadata import collect_metadata
import pt_bench as timer
from result_card import capture_run
from schedule import paired_schedule


KIND = "paired_managed_replay_campaign"
ARMS = ("baseline", "candidate")
MAX_BLOCKS = 64
MAX_CAMPAIGN_FILES = 8192
MAX_CAMPAIGN_BYTES = 1024 * 1024 * 1024
MAX_DECLARED_BYTES = 512 * 1024 * 1024
PAIRING_FIELDS = ("input_seed", "edit_sequence_sha256", "external_state_sha256")
LIMITATIONS = [
    "exploratory complete-session pairs; interactions never become independent latency or bootstrap samples",
    "matched workflow declarations are not verified edit application, input identity, reset equivalence or equal work",
    "fresh command processes do not establish independent sessions, daemon reuse, generations or qualified support",
    "comparison uses the managed-session endpoint; campaign publication, receipt persistence and inspection are separate observer costs",
    "all planned sessions remain in the denominator; no failed, missing or unconfirmed session is retried or excluded",
    "CPU, memory, idle residency, external-resource release and complete resource budgets remain unknown",
    "hashes and historical observations are unauthenticated; fingerprint checks are not an atomic or hostile-directory boundary",
    "no confirmatory, release, tail-latency or break-even claim is established by exploratory estimates",
]
FAILURES = (OSError, ValueError, RuntimeError, KeyboardInterrupt)


@lru_cache(maxsize=1)
def _validators():
    root = Path(__file__).resolve().parent
    names = ("paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json",
             "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
    schemas = [json.loads((root / name).read_text()) for name in names]
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
        raise ValueError(f"paired replay {kind} schema at {path}: violates {error.validator}")
    if kind == "abort":
        if value["diagnostic_receipt"] is not None:
            replay.validate("receipt", value["diagnostic_receipt"])
        if value["diagnostic_session"] is not None:
            validate("session", value["diagnostic_session"])


def _raw(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _binding(name, metadata):
    return {"name": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]}


def _publish(path, value, kind):
    (replay.validate if kind == "receipt" else validate)(kind, value)
    raw = _raw(value)
    limit = files.MAX_RECEIPT_BYTES if kind in ("receipt", "abort") else files.MAX_RECORD_BYTES
    if len(raw) > limit:
        raise ValueError("paired replay record exceeds byte limit; no sessions may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=len(raw))
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("paired replay publication did not commit expected bytes")
    return _binding(path.name, metadata), metadata


def _names(number, arm):
    return f"session-{number:06d}-{arm}", f"receipt-{number:06d}-{arm}.json", f"block-{number:06d}-{arm}.json"


def _context(number, position, arm):
    return {"block": number, "position": position, "arm": arm}


def validate_plan(plan):
    validate("plan", plan)
    schedule = plan["schedule"]
    if plan["limitations"] != LIMITATIONS or not timer._same_json(schedule, paired_schedule(len(schedule), plan["seed"])):
        raise ValueError("paired replay schedule, seed or limitations differ from contract")
    declared_bytes = 0
    for arm in ARMS:
        session = plan["sessions"][arm]
        replay.validate_plan(session)
        if os.path.normpath(session["cwd"]) != session["cwd"]:
            raise ValueError("paired replay cwd must be normalized")
        contracts = [step["required_finalization"] for _, step in replay._steps(session)] + [session["finalization"]]
        declared_bytes += sum(item["bytes"] for contract in contracts for item in contract["artifacts"])
        if session["capture_raw"]:
            declared_bytes += 2 * session["raw_limit_bytes"] * len(replay._steps(session))
    if declared_bytes * len(schedule) > MAX_DECLARED_BYTES:
        raise ValueError("paired replay aggregate declared artifact/raw budget exceeds limit")
    baseline, candidate = (plan["sessions"][arm] for arm in ARMS)
    first, second = (Path(session["cwd"]) for session in (baseline, candidate))
    if first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError("paired replay requires separate nonnested arm working directories")
    for field in ("execution_timeout_seconds", "capture_raw", "raw_limit_bytes"):
        if baseline[field] != candidate[field]:
            raise ValueError("paired replay execution budget and instrumentation policies must match")
    for (role, left), (other_role, right) in zip(replay._steps(baseline), replay._steps(candidate)):
        if (role != other_role or left["id"] != right["id"] or left["idle_before_seconds"] != right["idle_before_seconds"]
                or left["timeout_seconds"] != right["timeout_seconds"]
                or left["required_finalization"]["expected_exit_code"] != right["required_finalization"]["expected_exit_code"]):
            raise ValueError("paired replay phase identities, order, idle waits, timeouts and expected exits must match")
    if len(baseline["interactions"]) != len(candidate["interactions"]):
        raise ValueError("paired replay interaction counts must match")
    for field in ("edit_sequence_sha256", "external_state_sha256"):
        value = plan["pairing"][field]
        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("paired replay identity declaration must be a full SHA-256 digest")
    if len(_raw(plan)) > files.MAX_RECORD_BYTES:
        raise ValueError("paired replay plan exceeds byte limit")


def _snapshot(directory):
    """Bound root metadata and each private managed-session tree; never ignore extras."""
    files.require_safe_lookup()
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = files._fingerprint(os.fstat(fd))
        regular, sessions, count, total = {}, {}, 0, 0
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(regular) + len(sessions) >= 2 + 6 * MAX_BLOCKS:
                    raise ValueError("paired replay root entry count exceeds limit")
                files.relative_path(entry.name)
                if entry.is_file(follow_symlinks=False):
                    metadata, _ = files.inspect_file(directory, entry.name, limit=files.MAX_RECEIPT_BYTES)
                    regular[entry.name] = metadata
                    count, total = count + 1, total + metadata["bytes"]
                elif entry.is_dir(follow_symlinks=False) and re.fullmatch(r"session-[0-9]{6}-(baseline|candidate)", entry.name):
                    captured = capture_run(directory / entry.name)
                    sessions[entry.name] = captured
                    count += len(captured[0]["files"])
                    total += captured[0]["total_bytes"]
                else:
                    raise ValueError("paired replay contains nonregular input or an unexpected directory")
                if count > MAX_CAMPAIGN_FILES or total > MAX_CAMPAIGN_BYTES:
                    raise ValueError("paired replay evidence exceeds aggregate file/byte limit")
        named = os.stat(directory, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode) or files._fingerprint(named) != identity
                or files._fingerprint(os.fstat(fd)) != identity):
            raise ValueError("paired replay directory changed during inspection")
        return regular, sessions, identity
    finally:
        os.close(fd)


def run_pairs(output, baseline, candidate, blocks, seed, *, pairing=None):
    """Each scheduled arm is one new managed replay, not a new interaction sample."""
    files.require_safe_lookup()
    if type(blocks) is not int or not 1 <= blocks <= MAX_BLOCKS:
        raise ValueError(f"paired replay requires 1 to {MAX_BLOCKS} integer blocks")
    sessions = {}
    for arm, requested in (("baseline", baseline), ("candidate", candidate)):
        replay.validate_plan(requested)
        session = copy.deepcopy(requested)
        session["cwd"] = str(Path(session["cwd"]).resolve(strict=True))
        fd = os.open(session["cwd"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
        sessions[arm] = session
    plan = {"schema_version": 1, "kind": KIND, "mode": "exploratory_unqualified",
            "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT, "sample_unit": replay.UNIT,
            "schedule": paired_schedule(blocks, seed), "seed": seed, "sessions": sessions,
            "pairing": copy.deepcopy(pairing) if pairing is not None else {field: None for field in PAIRING_FIELDS},
            "host_metadata": collect_metadata(), "limitations": LIMITATIONS.copy()}
    validate_plan(plan)
    output = Path(os.path.abspath(output))
    output.mkdir(mode=0o700)
    plan_binding, plan_identity = _publish(output / "schedule.json", plan, "plan")

    def abort(context, reason, error, *, call_clock=None, receipt=None, record=None):
        directory = output / _names(context["block"], context["arm"])[0]
        inputs = capture_run(directory)[0] if reason == "harness_error" and os.path.lexists(directory) else None
        value = {"schema_version": 1, "kind": "paired_managed_replay_abort", "mode": "exploratory_unqualified",
                 "campaign_plan": plan_binding, "context": context, "reason": reason, "error": error,
                 "call_clock": call_clock, "diagnostic_receipt": receipt, "diagnostic_session": record,
                 "diagnostic_inputs": inputs}
        _publish(output / "abort.json", value, "abort")
        return inspect_pairs(output)

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = _context(block["block"], position, arm)
            directory, receipt_name, record_name = _names(block["block"], arm)
            try:
                current, _ = files.inspect_file(output, "schedule.json", limit=files.MAX_RECORD_BYTES)
                if current != plan_identity:
                    raise ValueError("frozen paired replay plan changed before a later session")
            except FAILURES as exc:
                return abort(context, "plan_binding_failed", f"{type(exc).__name__}: {exc}")
            start = time.monotonic_ns()
            try:
                receipt = replay.run_replay(output / directory, sessions[arm])
            except FAILURES as exc:
                return abort(context, "harness_error", f"{type(exc).__name__}: {exc}", call_clock=timer._timing(start))
            call_clock = timer._timing(start)
            publication_start = time.monotonic_ns()
            try:
                binding, _ = _publish(output / receipt_name, receipt, "receipt")
            except FAILURES as exc:
                return abort(context, "receipt_publication_failed", f"{type(exc).__name__}: {exc}",
                             call_clock=call_clock, receipt=receipt)
            record = {"schema_version": 1, "kind": "paired_managed_replay_session", "mode": "exploratory_unqualified",
                      "context": context, "campaign_plan": plan_binding, "call_clock": call_clock,
                      "receipt_publication_clock": timer._timing(publication_start), "receipt": binding}
            try:
                _inspect_session(output / directory, receipt, record, sessions[arm])
            except FAILURES as exc:
                return abort(context, "session_validation_failed", f"{type(exc).__name__}: {exc}", record=record)
            try:
                _publish(output / record_name, record, "session")
            except FAILURES as exc:
                return abort(context, "session_publication_failed", f"{type(exc).__name__}: {exc}", record=record)
            if receipt["outcome"]["status"] != "completed_unqualified":
                return abort(context, "session_failed", "managed replay did not complete its declared sequence and shutdown")
    return inspect_pairs(output)


def _inspect_session(directory, receipt, record, expected):
    inner = replay.inspect_replay(directory, receipt)
    plan, _ = files.read_json(directory / "plan.json", limit=replay.MAX_PLAN_BYTES)
    if not timer._same_json(plan, expected):
        raise ValueError("managed session plan differs from paired arm declaration")
    replay._interval(record["call_clock"])
    replay._interval(receipt["clock"], record["call_clock"])
    publication = record["receipt_publication_clock"]
    if publication is not None:
        replay._interval(publication)
        if publication["monotonic_start_ns"] < record["call_clock"]["monotonic_end_ns"]:
            raise ValueError("paired replay receipt publication precedes session return")
    sample = (files.read_json(directory / "unit.json", limit=replay.MAX_UNIT_BYTES)[0]
              if receipt["sample"] is not None else receipt["diagnostic_sample"])
    guards = Counter()
    for row in sample["steps"]:
        phase = row["receipt"]
        state = ("not_observed" if phase is None else "not_requested" if phase["guard_expectations"] is None else
                 "matched" if phase["observation_guard"] and phase["observation_guard"]["matched_expected_observations"] else "mismatched")
        guards[state] += 1
    return inner, dict(sorted(guards.items()))


def _thin(context, *, status="not_run_run_aborted", receipt=None, summary=None, guards=None,
          receipt_committed=False, session_committed=False, reasons=None):
    return {"context": context, "measurement_layer": "managed_replay", "sample_unit": replay.UNIT,
            "status": summary["status"] if summary is not None else status,
            "invocation_attempted": True if summary is not None else None if status == "harness_error" else False,
            "receipt_record_committed": receipt_committed, "session_record_committed": session_committed,
            "elapsed_ns": receipt["clock"]["elapsed_ns"] if receipt is not None else None,
            "phase_guard_counts": guards, "replay_summary": summary, "failure_reasons": reasons or []}


def inspect_pairs(directory, plan=None, *, observations=None):
    directory = Path(directory)
    snapshot = _snapshot(directory)
    actual_plan, metadata = files.read_json(directory / "schedule.json")
    validate_plan(actual_plan)
    if plan is not None and not timer._same_json(plan, actual_plan):
        raise ValueError("paired replay inspection plan differs from retained bytes")
    plan, plan_binding = actual_plan, _binding("schedule.json", metadata)
    expected = {"schedule.json"}
    abort = None
    if "abort.json" in snapshot[0]:
        abort, _ = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)
        validate("abort", abort)
        if not timer._same_json(abort["campaign_plan"], plan_binding):
            raise ValueError("paired replay abort plan byte binding differs")
        expected.add("abort.json")
    rows, last_end, stopped, found_abort = [], None, False, False
    infrastructure = False

    def read(name, kind):
        value, meta = files.read_json(directory / name, limit=files.MAX_RECEIPT_BYTES if kind == "receipt" else files.MAX_RECORD_BYTES)
        (replay.validate if kind == "receipt" else validate)(kind, value)
        expected.add(name)
        return value, meta

    for block in plan["schedule"]:
        for position, arm in enumerate(block["order"], 1):
            context = _context(block["block"], position, arm)
            row = _thin(context)
            directory_name, receipt_name, record_name = _names(block["block"], arm)
            is_abort = abort is not None and timer._same_json(abort["context"], context)
            if stopped:
                row["failure_reasons"] = ["run_aborted"]
                rows.append(row)
                continue
            reason = abort["reason"] if is_abort else None
            receipt = record = None
            receipt_committed = session_committed = False
            if reason in ("harness_error", "plan_binding_failed"):
                if abort["diagnostic_receipt"] is not None or abort["diagnostic_session"] is not None:
                    raise ValueError("paired replay no-return abort invents returned observations")
                if reason == "harness_error":
                    if abort["call_clock"] is None:
                        raise ValueError("paired replay missing-return call has no interval")
                    replay._interval(abort["call_clock"])
                    if last_end is not None and abort["call_clock"]["monotonic_start_ns"] < last_end:
                        raise ValueError("paired replay call intervals overlap or are out of order")
                    captured = snapshot[1].get(directory_name)
                    if not timer._same_json(abort["diagnostic_inputs"], captured[0] if captured is not None else None):
                        raise ValueError("paired replay missing-return diagnostic inputs differ from retained bytes")
                    if captured is not None:
                        expected.add(directory_name)
                elif abort["call_clock"] is not None or abort["diagnostic_inputs"] is not None:
                    raise ValueError("paired replay pre-call abort invents session evidence")
                row = _thin(context, status="harness_error" if reason == "harness_error" else "not_run_plan_changed", reasons=[reason])
            else:
                if reason == "receipt_publication_failed":
                    receipt = abort["diagnostic_receipt"]
                    if receipt is None or abort["call_clock"] is None or abort["diagnostic_session"] is not None or abort["diagnostic_inputs"] is not None:
                        raise ValueError("paired replay missing receipt publication failure evidence")
                    if receipt_name in snapshot[0]:
                        visible, _ = read(receipt_name, "receipt")
                        if not timer._same_json(visible, receipt):
                            raise ValueError("failed paired replay receipt publication contradicts diagnostic copy")
                    record = {"call_clock": abort["call_clock"], "receipt_publication_clock": None}
                else:
                    receipt, receipt_metadata = read(receipt_name, "receipt")
                    receipt_committed = True
                    if reason in ("session_publication_failed", "session_validation_failed"):
                        record = abort["diagnostic_session"]
                        if record is None:
                            raise ValueError("paired replay missing diagnostic session metadata")
                        validate("session", record)
                        if record_name in snapshot[0]:
                            visible, _ = read(record_name, "session")
                            if not timer._same_json(visible, record):
                                raise ValueError("failed paired replay session publication contradicts diagnostic copy")
                    else:
                        record, _ = read(record_name, "session")
                        session_committed = True
                    if is_abort and (abort["call_clock"] is not None or abort["diagnostic_receipt"] is not None or abort["diagnostic_inputs"] is not None):
                        raise ValueError("paired replay session abort contains unrelated diagnostic evidence")
                    if reason == "session_failed" and abort["diagnostic_session"] is not None:
                        raise ValueError("paired replay completed publication invents diagnostic metadata")
                    if (not timer._same_json(record["context"], context) or not timer._same_json(record["campaign_plan"], plan_binding)
                            or not timer._same_json(record["receipt"], _binding(receipt_name, receipt_metadata))):
                        raise ValueError("paired replay session context or byte bindings differ from fixed plan")
                inner, guards = _inspect_session(directory / directory_name, receipt, record, plan["sessions"][arm])
                expected.add(directory_name)
                if last_end is not None and record["call_clock"]["monotonic_start_ns"] < last_end:
                    raise ValueError("paired complete-session intervals overlap or are out of order")
                last_end = (record["receipt_publication_clock"] or record["call_clock"])["monotonic_end_ns"]
                if reason == "session_failed" and inner["status"] == "completed_unqualified":
                    raise ValueError("paired replay abort lacks an observed session failure")
                if reason not in ("session_failed", "receipt_publication_failed", "session_publication_failed", "session_validation_failed") and inner["status"] != "completed_unqualified":
                    raise ValueError("failed paired replay session lacks the required abort record")
                row = _thin(context, receipt=receipt, summary=inner, guards=guards,
                            receipt_committed=receipt_committed, session_committed=session_committed,
                            reasons=[reason] if reason is not None else [])
                infrastructure |= receipt["outcome"]["infrastructure_failure"]
            if is_abort:
                infrastructure |= reason != "session_failed"
                stopped = found_abort = True
            rows.append(row)
    if abort is not None and not found_abort:
        raise ValueError("paired replay abort does not name a planned session")
    if set(snapshot[0]) | set(snapshot[1]) != expected:
        raise ValueError("unexpected or missing paired replay records or session directories")
    if _snapshot(directory) != snapshot:
        raise ValueError("paired replay evidence changed during inspection")
    if observations is not None:
        observations.extend(rows)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    phase_counts = Counter()
    for row in rows:
        if row["replay_summary"] is not None:
            phase_counts.update(row["replay_summary"]["phase_status_counts"])
    return {"record_consistency": "aborted" if stopped else "complete", "mode": "exploratory_unqualified", "kind": KIND,
            "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT, "sample_unit": replay.UNIT,
            "blocks": len(plan["schedule"]), "planned_arm_count": len(rows), "observed_arm_count": sum(row["replay_summary"] is not None for row in rows),
            "planned_session_count": len(rows), "observed_session_count": sum(row["replay_summary"] is not None for row in rows),
            "known_session_invocations": sum(row["invocation_attempted"] is True for row in rows),
            "unknown_session_invocations": sum(row["invocation_attempted"] is None for row in rows),
            "known_not_invoked_sessions": sum(row["invocation_attempted"] is False for row in rows),
            "arm_status_counts": counts, "session_status_counts": counts, "session_observations": rows,
            "planned_phase_count": sum(len(replay._steps(plan["sessions"][row["context"]["arm"]])) for row in rows),
            "observed_phase_status_counts": dict(sorted(phase_counts.items())),
            "not_run_phase_count": sum(len(replay._steps(plan["sessions"][row["context"]["arm"]])) for row in rows if row["invocation_attempted"] is False),
            "unknown_phase_count": sum(len(replay._steps(plan["sessions"][row["context"]["arm"]])) for row in rows if row["invocation_attempted"] is None),
            "verified_independent_sessions": None, "verified_independent_blocks": None, "pairing": plan["pairing"],
            "pairing_identity_status": "declared_only_unverified" if all(plan["pairing"][field] is not None for field in PAIRING_FIELDS) else "unresolved",
            "recorded_interval_order": "nonoverlapping", "infrastructure_failure": infrastructure,
            "resource_observation": None, "whole_boundary_resource_accounting_complete": False,
            "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def summarize(inspection, observations, *, bootstrap_resamples=None, bootstrap_seed=None):
    expected = {(number, arm) for number in range(1, inspection["blocks"] + 1) for arm in ARMS}
    identities = [(row["context"]["block"], row["context"]["arm"]) for row in observations]
    if (len(observations) != inspection["planned_session_count"] or len(observations) != len(expected)
            or set(identities) != expected or any(row["sample_unit"] != replay.UNIT or row["measurement_layer"] != "managed_replay"
                or (row["replay_summary"] is not None and (row["replay_summary"]["sample_unit"] != replay.UNIT
                    or row["replay_summary"]["observed_session_count"] != 1)) for row in observations)):
        raise ValueError("paired replay summary requires exactly every planned whole-session observation")
    if bootstrap_resamples is not None and bootstrap_resamples * inspection["blocks"] > 10_000_000:
        raise ValueError("bootstrap exceeds the exploratory computation limit")
    blockers, samples = [], []
    if inspection["record_consistency"] != "complete":
        blockers.append({"context": None, "reasons": ["campaign_aborted"]})
    if inspection["pairing_identity_status"] != "declared_only_unverified":
        blockers.append({"context": None, "reasons": ["pairing_identity_unresolved"]})
    if bootstrap_resamples is not None and inspection["blocks"] < 2:
        blockers.append({"context": None, "reasons": ["bootstrap_requires_two_paired_sessions"]})
    for row in observations:
        reasons = row["failure_reasons"].copy()
        inner = row["replay_summary"]
        if row["status"] != "completed_unqualified":
            reasons.append("session_not_completed")
        if not row["receipt_record_committed"] or not row["session_record_committed"]:
            reasons.append("observer_publication_unconfirmed")
        if inner is None or row["phase_guard_counts"] != {"matched": inner["planned_phase_count"]}:
            reasons.append("phase_guards_not_all_matched")
        if inner is not None and inner["raw_capture_truncated_phase_count"]:
            reasons.append("raw_capture_truncated")
        if type(row["elapsed_ns"]) is not int or row["elapsed_ns"] <= 0:
            reasons.append("missing_positive_session_elapsed_time")
        if reasons:
            blockers.append({"context": row["context"], "reasons": reasons})
        else:
            samples.append({"block": str(row["context"]["block"]), "arm": row["context"]["arm"],
                            "status": "guard_matched_unqualified", "elapsed_ns": row["elapsed_ns"],
                            "sample_unit": replay.UNIT, "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT})
    result = {**inspection, "status": "blocked" if blockers else "exploratory_point_estimate", "blockers": blockers,
              "latency_unit": "complete_managed_session_replay", "resampling_unit": "whole_paired_complete_sessions",
              "ratio_direction": "baseline_over_candidate", "ratio": None, "absolute_latency_ns": None, "bootstrap": None}
    if not blockers:
        result["ratio"] = guarded_exploratory_ratio(samples)
        totals = {arm: sum(sample["elapsed_ns"] for sample in samples if sample["arm"] == arm) for arm in ARMS}
        count = inspection["blocks"]
        result["absolute_latency_ns"] = {"baseline_mean": totals["baseline"] / count, "candidate_mean": totals["candidate"] / count,
                                         "mean_paired_baseline_minus_candidate": (totals["baseline"] - totals["candidate"]) / count}
        if bootstrap_resamples is not None:
            result["bootstrap"] = guarded_exploratory_bootstrap(samples, seed=bootstrap_seed, resamples=bootstrap_resamples)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-plan", type=Path, required=True)
    parser.add_argument("--candidate-plan", type=Path, required=True)
    parser.add_argument("--blocks", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--pairing-json", help="shared declared input_seed, edit_sequence_sha256 and external_state_sha256; not verified identities")
    args = parser.parse_args()
    try:
        baseline, _ = files.read_json(args.baseline_plan, limit=replay.MAX_PLAN_BYTES)
        candidate, _ = files.read_json(args.candidate_plan, limit=replay.MAX_PLAN_BYTES)
        pairing = files.parse_json(args.pairing_json) if args.pairing_json is not None else None
        report = run_pairs(args.output, baseline, candidate, args.blocks, args.seed, pairing=pairing)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"paired-replay: {exc}\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report["infrastructure_failure"] else 1 if report["record_consistency"] != "complete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
