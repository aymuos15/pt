"""Independent bounded reader/comparator for real-pytest occurrence and phase traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


MAX_TRACE_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 128 * 1024
MAX_EVENTS = 25000
MAX_ITEMS = 256
KINDS = {
    "start": {"python", "pytest", "pid", "implementation", "platform", "machine", "gil_disabled",
              "collect_only", "maxfail", "continue_on_collection_errors", "argv"},
    "collection_report": {"nodeid", "outcome", "result_count", "failure_message", "diagnostic_longrepr"},
    "inventory": {"collected", "selected", "deselected"},
    "protocol_start": {"ordinal", "nodeid"}, "protocol_finish": {"ordinal", "nodeid"},
    "phase": {"ordinal", "nodeid", "when", "outcome", "wasxfail", "failure_message", "diagnostic_longrepr", "sections", "duration"},
    "warning": {"category", "message", "when", "nodeid"}, "observer_error": {"reason"},
    "backend_error": {"exception_type", "message"}, "interruption": {"exception_type", "message"},
    "terminal": {"exit_status", "reports", "executed", "stop_reason", "observer_errors"},
}


class TraceError(ValueError):
    pass


def _pairs(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise TraceError("duplicate trace JSON key")
        value[key] = item
    return value


def _fingerprint(item):
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def _raw(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_TRACE_BYTES:
            raise TraceError("trace must be a bounded regular file")
        chunks, count = [], 0
        while chunk := os.read(fd, 65536):
            count += len(chunk)
            if count > MAX_TRACE_BYTES:
                raise TraceError("trace grew beyond its byte limit")
            chunks.append(chunk)
        if _fingerprint(before) != _fingerprint(os.fstat(fd)) or _fingerprint(before) != _fingerprint(os.stat(path, follow_symlinks=False)):
            raise TraceError("trace changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _json(value, depth=0):
    if depth > 32:
        raise TraceError("trace JSON depth limit")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TraceError("trace keys must be strings")
            _json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json(item, depth + 1)
    elif type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise TraceError("unsupported surrogate in trace string") from exc
    elif type(value) is float:
        if not math.isfinite(value):
            raise TraceError("nonfinite trace value")
    elif type(value) not in (str, int, bool, type(None)):
        raise TraceError("unsupported trace JSON value")


def _integer(value):
    return type(value) is int and value >= 0


def _request_argv(argv):
    """Remove only this observer's explicit trace destination, never user paths."""
    result, index, removed = [], 0, 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--pt-reference-trace":
            if index + 1 >= len(argv) or not argv[index + 1]:
                raise TraceError("missing observer trace destination")
            index += 2
            removed += 1
        elif arg.startswith("--pt-reference-trace=") and arg != "--pt-reference-trace=":
            index += 1
            removed += 1
        else:
            result.append(arg)
            index += 1
    if removed != 1:
        raise TraceError("expected exactly one observer transport argument")
    return result


def read_trace(path, process_exit_code):
    raw = _raw(Path(path))
    lines = raw.splitlines()
    if not raw.endswith(b"\n") or not 2 <= len(lines) <= MAX_EVENTS or type(process_exit_code) is not int:
        raise TraceError("missing/truncated trace or absent actual process status")
    events, session, last_clock = [], None, None
    for seq, line in enumerate(lines, 1):
        if len(line) > MAX_EVENT_BYTES:
            raise TraceError("trace event exceeds byte limit")
        try:
            event = json.loads(line.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
            _json(event)
        except (ValueError, RecursionError) as exc:
            raise TraceError("invalid strict trace JSON") from exc
        if (type(event) is not dict or set(event) != {"schema_version", "session", "seq", "monotonic_ns", "kind", "payload"}
                or type(event["schema_version"]) is not int or event["schema_version"] != 1
                or type(event["seq"]) is not int or event["seq"] != seq or type(event["session"]) is not str
                or re.fullmatch(r"[0-9a-f]{32}", event["session"]) is None or not _integer(event["monotonic_ns"])
                or type(event["kind"]) is not str or event["kind"] not in KINDS or type(event["payload"]) is not dict
                or set(event["payload"]) != KINDS[event["kind"]]):
            raise TraceError("trace event type, sequence or closed shape differs")
        if session is None:
            session = event["session"]
        if event["session"] != session or last_clock is not None and event["monotonic_ns"] < last_clock:
            raise TraceError("mixed sessions or decreasing trace clock")
        last_clock = event["monotonic_ns"]
        events.append(event)
    if events[0]["kind"] != "start" or events[-1]["kind"] != "terminal":
        raise TraceError("trace is missing its start/terminal boundary")
    header, terminal = events[0]["payload"], events[-1]["payload"]
    if (type(header["python"]) is not list or any(type(part) is not int for part in header["python"])
            or header["python"] != [3, 12, 12] or header["pytest"] != "8.4.2" or not _integer(header["pid"]) or header["pid"] == 0
            or header["implementation"] != "cpython" or header["platform"] != "linux" or header["machine"] != "x86_64" or header["gil_disabled"] is not False
            or type(header["collect_only"]) is not bool or type(header["argv"]) is not list or any(type(arg) is not str for arg in header["argv"])
            or not _integer(header["maxfail"]) or type(header["continue_on_collection_errors"]) is not bool
            or type(terminal["exit_status"]) is not int or terminal["exit_status"] != process_exit_code
            or not 0 <= process_exit_code <= 5 or terminal["stop_reason"] is not None and type(terminal["stop_reason"]) is not str
            or not _integer(terminal["reports"]) or not _integer(terminal["executed"]) or terminal["observer_errors"] != []):
        raise TraceError("trace runtime, terminal or actual process return is inconsistent")
    inventories = [event["payload"] for event in events if event["kind"] == "inventory"]
    if len(inventories) != 1:
        raise TraceError("trace needs one authoritative same-session inventory")
    inventory = inventories[0]
    items, selected, deselected = (inventory[key] for key in ("collected", "selected", "deselected"))
    if type(items) is not list or len(items) > MAX_ITEMS or type(selected) is not list or type(deselected) is not list:
        raise TraceError("invalid occurrence inventory type or bound")
    for ordinal, item in enumerate(items):
        if (type(item) is not dict or set(item) != {"ordinal", "nodeid"} or type(item["ordinal"]) is not int
                or item["ordinal"] != ordinal or type(item["nodeid"]) is not str or not item["nodeid"]):
            raise TraceError("occurrence identities must retain exact ordinals and node IDs")
    if (any(not _integer(ordinal) or ordinal >= len(items) for ordinal in [*selected, *deselected])
            or len(set([*selected, *deselected])) != len(selected) + len(deselected)
            or set(selected) | set(deselected) != set(range(len(items)))):
        raise TraceError("collection/selection/deselection partition is incomplete or duplicated")
    phases, collection, warnings, starts, finishes, errors, interruptions = [], [], [], [], [], [], []
    active, inventory_seen = None, False
    for event in events[1:-1]:
        kind, value = event["kind"], event["payload"]
        if kind == "inventory":
            inventory_seen = True
        elif kind in ("start", "terminal", "observer_error"):
            raise TraceError("duplicate boundary or reported observer failure")
        elif kind == "collection_report":
            if (inventory_seen or type(value["nodeid"]) is not str or value["outcome"] not in ("passed", "failed", "skipped")
                    or not _integer(value["result_count"]) or value["failure_message"] is not None and type(value["failure_message"]) is not str
                    or value["diagnostic_longrepr"] is not None and type(value["diagnostic_longrepr"]) is not str):
                raise TraceError("invalid collection report")
            collection.append({key: value[key] for key in ("nodeid", "outcome", "result_count", "failure_message")})
        elif kind in ("protocol_start", "protocol_finish", "phase"):
            ordinal = value["ordinal"]
            if (not inventory_seen or not _integer(ordinal) or ordinal not in selected or value["nodeid"] != items[ordinal]["nodeid"]):
                raise TraceError("execution identity differs from selected live occurrence")
            if kind == "protocol_start":
                if active is not None or starts != selected[:len(starts)] or len(starts) >= len(selected) or ordinal != selected[len(starts)]:
                    raise TraceError("nested, repeated or reordered serial protocol")
                active = ordinal
                starts.append(ordinal)
            elif kind == "protocol_finish":
                if active != ordinal:
                    raise TraceError("protocol finish does not close its active occurrence")
                finishes.append(ordinal)
                active = None
            else:
                if (active != ordinal or value["when"] not in ("setup", "call", "teardown")
                        or value["outcome"] not in ("passed", "failed", "skipped")
                        or any(value[key] is not None and type(value[key]) is not str for key in ("wasxfail", "failure_message", "diagnostic_longrepr"))
                        or type(value["sections"]) is not list or any(type(section) is not list or len(section) != 2
                            or any(type(part) is not str for part in section) for section in value["sections"])
                        or type(value["duration"]) not in (int, float) or value["duration"] < 0):
                    raise TraceError("invalid or unassociated phase report")
                phases.append({key: value[key] for key in ("ordinal", "nodeid", "when", "outcome", "wasxfail", "failure_message", "sections")})
        elif kind == "warning":
            if any(type(value[key]) is not str for key in KINDS["warning"]):
                raise TraceError("invalid warning observation")
            warnings.append(value)
        elif kind in ("backend_error", "interruption"):
            if any(type(value[key]) is not str for key in ("exception_type", "message")):
                raise TraceError("invalid backend failure/interrupt observation")
            (errors if kind == "backend_error" else interruptions).append(value)
    if active is not None or starts != finishes or terminal["executed"] != len(starts) or terminal["reports"] != len(phases):
        raise TraceError("unclosed or incomplete execution/report counts")
    completed, incomplete = [], []
    for ordinal in starts:
        rows = [phase for phase in phases if phase["ordinal"] == ordinal]
        if not rows or rows[0]["when"] != "setup":
            raise TraceError("executed occurrence lacks setup")
        expected = ["setup", "call", "teardown"] if rows[0]["outcome"] == "passed" else ["setup", "teardown"]
        actual = [row["when"] for row in rows]
        if actual != expected:
            if (process_exit_code not in (2, 3) or not (errors or interruptions)
                    or actual != expected[:len(actual)]):
                raise TraceError("missing, duplicate or impossible setup/call/teardown sequence")
            incomplete.append(ordinal)
        else:
            completed.append(ordinal)
    if header["collect_only"] and starts:
        raise TraceError("collect-only request unexpectedly executed tests")
    failed = sum(row["outcome"] == "failed" for row in [*collection, *phases])
    not_run = selected[len(starts):]
    if process_exit_code == 0:
        if (errors or interruptions or any(row["outcome"] == "failed" for row in [*collection, *phases])
                or not header["collect_only"] and (not selected or starts != selected)):
            raise TraceError("zero exit contradicts failure, empty or incomplete execution")
    elif process_exit_code == 1:
        if (not failed or errors or interruptions or header["collect_only"] and not any(row["outcome"] == "failed" for row in collection)
                or not_run and not (header["maxfail"] > 0 and failed >= header["maxfail"] and terminal["stop_reason"])):
            raise TraceError("test-failure exit lacks failed work or a declared fail-fast stop")
    elif process_exit_code == 2:
        if not interruptions or errors:
            raise TraceError("interrupted exit lacks an observed backend interruption")
    elif process_exit_code == 3:
        if not errors:
            raise TraceError("internal-error exit lacks an observed backend error")
    elif process_exit_code == 4:
        raise TraceError("precollection usage errors have no supported authoritative inventory")
    elif selected or starts or failed or errors or interruptions:
        raise TraceError("no-tests exit contradicts selected, executed or failed work")
    return {"consistency": "checked_instrumented_reference_only", "trace_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_event_count": len(events), "events": events,
            "normalized": {"pytest_argv": _request_argv(header["argv"]), "collect_only": header["collect_only"],
                           "maxfail": header["maxfail"], "continue_on_collection_errors": header["continue_on_collection_errors"],
                           "collected": items, "selected": selected, "deselected": deselected,
                           "started": starts, "completed": completed, "incomplete": incomplete, "not_run": not_run,
                           "stop_reason": terminal["stop_reason"],
                           "collection_reports": collection, "phases": phases, "warnings": warnings, "backend_errors": errors,
                           "interruptions": interruptions, "process_exit_code": process_exit_code},
            "confirmatory_eligible": False}


def _without_control(argv, control):
    if not control:
        return argv
    if type(control) not in (tuple, list) or any(type(arg) is not str for arg in control):
        raise TraceError("control arguments must be an explicit string sequence")
    indices = [index for index in range(len(argv) - len(control) + 1) if argv[index:index + len(control)] == list(control)]
    if len(indices) != 1:
        raise TraceError("declared test control arguments must occur exactly once")
    index = indices[0]
    return argv[:index] + argv[index + len(control):]


def compare_traces(baseline, candidate, *, baseline_exit, candidate_exit, baseline_effects=None, candidate_effects=None,
                   baseline_control_args=(), candidate_control_args=()):
    for effects in (baseline_effects, candidate_effects):
        if effects is not None:
            if type(effects) is not list or len(effects) > MAX_EVENTS or any(type(value) is not str for value in effects):
                raise TraceError("external effect observations must be a bounded string list or unknown")
            _json(effects)
            if len(json.dumps(effects, allow_nan=False).encode("utf-8")) > MAX_TRACE_BYTES:
                raise TraceError("external effect observations exceed their byte limit")
    left, right = read_trace(baseline, baseline_exit), read_trace(candidate, candidate_exit)
    for value, control in ((left, baseline_control_args), (right, candidate_control_args)):
        value["normalized"]["pytest_argv"] = _without_control(value["normalized"]["pytest_argv"], control)
    differences = [key for key in left["normalized"] if left["normalized"][key] != right["normalized"][key]]
    if (baseline_effects is None) != (candidate_effects is None) or baseline_effects != candidate_effects:
        differences.append("declared_effect_observations")
    return {"status": "mismatch" if differences else "matched_instrumented_trace_contract", "differences": differences,
            "baseline_trace_sha256": left["trace_sha256"], "candidate_trace_sha256": right["trace_sha256"],
            "selected_occurrences": {"baseline": len(left["normalized"]["selected"]), "candidate": len(right["normalized"]["selected"])},
            "declared_test_control_args": {"baseline": list(baseline_control_args), "candidate": list(candidate_control_args)},
            "limitations": ["instrumented finite reference contract, not universal semantic proof or unmodified-product timing",
                            "raw diagnostics/argv/clocks/PIDs are retained; traceback locations, durations and the exact trace transport option are not compared",
                            "test-body and fixture-effect proof needs declared external sentinels; phase reports alone cannot prove body execution",
                            "source/environment/coverage/generation/protocol and actual backend qualification remain separate gates"],
            "confirmatory_eligible": False, "ratio": None}


def compare_against_references(references, candidate):
    """A disagreeing repeated baseline is uncertainty, not a candidate speed/result win."""
    if type(references) is not list or not 2 <= len(references) <= 16:
        raise TraceError("baseline stability needs two to sixteen explicitly supplied fresh observations")
    for value in [*references, candidate]:
        if type(value) is not dict or set(value) != {"path", "exit", "effects", "control_args"}:
            raise TraceError("reference/candidate observation has an unsupported closed shape")

    def compare(left, right):
        return compare_traces(left["path"], right["path"], baseline_exit=left["exit"], candidate_exit=right["exit"],
                              baseline_effects=left["effects"], candidate_effects=right["effects"],
                              baseline_control_args=left["control_args"], candidate_control_args=right["control_args"])

    stability = [compare(references[0], value) for value in references[1:]]
    uncertain = any(value["status"] != "matched_instrumented_trace_contract" for value in stability)
    comparison = None if uncertain else compare(references[0], candidate)
    return {"status": "baseline_uncertain" if uncertain else comparison["status"], "baseline_stability": stability,
            "candidate_comparison": comparison, "reference_count": len(references), "confirmatory_eligible": False,
            "limitations": ["finite repeated-reference stability check; repetitions do not prove determinism or independent samples"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline-exit", type=int, required=True)
    parser.add_argument("--candidate-exit", type=int, required=True)
    args = parser.parse_args()
    try:
        report = compare_traces(args.baseline, args.candidate, baseline_exit=args.baseline_exit, candidate_exit=args.candidate_exit)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"trace-oracle: {exc}\n")
    print(json.dumps(report, sort_keys=True))
    return int(report["status"] == "mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
