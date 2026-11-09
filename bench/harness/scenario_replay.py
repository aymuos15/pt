"""Explicit file reset/edit/input validation; not a pytest oracle or latency benchmark."""

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
import sys
import time

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
import finalization as files
from guards import validate_expectations
from inspect_run import _measurement
import managed_replay as replay
import pt_bench as timer
from result_card import capture_run, _inventory
import scenario_inputs as inputs


HARNESS = Path(__file__).resolve().parent
LAYER = "scenario_validation"
UNIT = "complete_scenario_edit_replay"
ENDPOINT = "scenario_api_entry_through_explicit_reset_edits_requests_shutdown_and_evidence_publication_v1"
MAX_PLAN_BYTES = 256 * 1024
MAX_UNIT_BYTES = 3 * 1024 * 1024
UNSUPPORTED = {"S6", "S7", "S9"}
QUALIFICATION = ("complete_input_domain", "actual_loaded_code", "semantic_equal_work", "reset_equivalence", "generation_validity", "independent_units")
LIMITATIONS = [
    "correctness-instrumented declared-file scenario validation, not product request/edit latency or a semantic oracle",
    "reset and edits affect only explicit regular files; other files, caches, services and environment inputs remain unverified",
    "input bytes and seed are delivered as a declared file; this does not prove the subject consumed them or loaded intended code",
    "cache-state axes are declarations, not observed native cache/service/coordinator state or cold-host qualification",
    "file effects are sequential and nontransactional; failure can leave partial state, without rollback or automatic retry",
    "required shutdown is attempted once after plan publication; host loss, SIGKILL and repeated interruption cannot guarantee cleanup",
    "snapshots and before/after fingerprints are not atomic, authenticated or a hostile-directory boundary; ancestors are caller-owned",
    "retained absence and clock assertions are unauthenticated; no complete program-input or resource-budget qualification",
    "post-endpoint receipt construction is observer work; private no-overwrite evidence is not power-loss durable",
]
FAILURES = inputs.FAILURES


@lru_cache(maxsize=1)
def _validators():
    schemas = [json.loads((HARNESS / name).read_text()) for name in (
        "scenario-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json",
        "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return {kind: StrictValidator({"$ref": f"{schemas[0]['$id']}#/$defs/{kind}"}, registry=registry) for kind in ("plan", "unit", "receipt")}


def validate(kind, value):
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"scenario {kind} schema at {path}: violates {error.validator}")


def _raw(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _binding(name, metadata):
    return {"name": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]}


def _publish(path, value, kind):
    validate(kind, value)
    raw = _raw(value)
    limit = MAX_PLAN_BYTES if kind == "plan" else MAX_UNIT_BYTES
    if len(raw) > limit:
        raise ValueError("scenario record exceeds byte limit; no planned work may be dropped")
    timer.write_record(str(path), value)
    metadata, _ = files.inspect_file(path.parent, path.name, limit=limit)
    if metadata["bytes"] != len(raw) or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("scenario publication did not commit expected bytes")
    return _binding(path.name, metadata), metadata


def _states(plan):
    state = {row["path"]: row["value"] for row in plan["reset"]}
    result = [copy.deepcopy(state)]
    for request in plan["requests"]:
        for edit in request["edits"]:
            if not timer._same_json(state[edit["path"]], edit["before"]):
                raise ValueError("scenario edit precondition contradicts the preceding declared input state")
            state[edit["path"]] = edit["after"]
        state[request["input"]["path"]] = request["input"]["value"]
        result.append(copy.deepcopy(state))
    return result


def validate_plan(plan):
    validate("plan", plan)
    if os.path.normpath(plan["cwd"]) != plan["cwd"] or "\0" in plan["cwd"]:
        raise ValueError("scenario cwd must be a normalized absolute path")
    paths = [row["path"] for row in plan["reset"]]
    if paths != sorted(set(paths)):
        raise ValueError("scenario reset paths must be sorted and unique")
    for path in paths:
        files.relative_path(path)
        if any(Path(other) in Path(path).parents for other in paths):
            raise ValueError("scenario input paths must not be nested below another declared file")
    ids, payload_paths, edits = set(), {request["input"]["path"] for request in plan["requests"]}, 0
    if len(payload_paths) != 1 or not payload_paths.issubset(paths):
        raise ValueError("scenario requests must deliver input through one declared tracked path")
    for request in plan["requests"]:
        if request["id"] in ids or request["id"] in ("reset", "shutdown") or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", request["id"]) is None:
            raise ValueError("scenario request IDs must be unique bounded nonreserved labels")
        ids.add(request["id"])
        names = [edit["path"] for edit in request["edits"]]
        if names != sorted(set(names)) or not set(names).issubset(paths) or set(names) & payload_paths:
            raise ValueError("scenario edits must be sorted unique declared paths separate from request input")
        for edit in request["edits"]:
            if timer._same_json(edit["before"], edit["after"]):
                raise ValueError("scenario edit must change content, presence or mode")
        edits += len(names)
    scenario = plan["scenario"]["id"]
    if scenario in ("S0", "S1", "S2") and edits or scenario in ("S3", "S4", "S5") and not edits:
        raise ValueError("scenario edit/unchanged declaration contradicts its scenario class")
    commands = [*[request["command"] for request in plan["requests"]], plan["shutdown"]]
    for command in commands:
        if any("\0" in arg for arg in command["argv"]):
            raise ValueError("scenario command arguments must not contain NUL")
        if not timer._same_json(files.requirements(command["required_finalization"]), command["required_finalization"]):
            raise ValueError("scenario command finalization must be canonical")
        guard = command["guard_expectations"]
        if guard is not None:
            validate_expectations(guard)
            if guard["expected_exit_code"] != command["required_finalization"]["expected_exit_code"]:
                raise ValueError("scenario guard and expected exit conflict")
    if plan["shutdown"]["required_finalization"]["expected_exit_code"] != 0:
        raise ValueError("scenario shutdown requires expected exit zero")
    states = _states(plan)
    descriptors = [value for state in states for value in state.values() if value is not None]
    sizes = {}
    for value in descriptors:
        if re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
            raise ValueError("scenario input digest must be an exact SHA-256")
        if value["sha256"] in sizes and sizes[value["sha256"]] != value["bytes"]:
            raise ValueError("scenario one input digest cannot have inconsistent byte counts")
        sizes[value["sha256"]] = value["bytes"]
    if (sum(sizes.values()) + sum(item["bytes"] for command in commands for item in command["required_finalization"]["artifacts"]) > inputs.MAX_BLOB_BYTES
            or sum(len(command["required_finalization"]["artifacts"]) for command in commands) > 1000):
        raise ValueError("scenario declared input/artifact budget exceeds limit")
    if plan["limitations"] != LIMITATIONS or len(_raw(plan)) > MAX_PLAN_BYTES:
        raise ValueError("scenario plan limitations or byte limit differ")


def _payloads(plan, source, bundle=None):
    values = [value for state in _states(plan) for value in state.values() if value is not None]
    for value in {item["sha256"]: item for item in values}.values():
        metadata, raw = files.inspect_file(source, value["sha256"], limit=inputs.MAX_FILE_BYTES, retain=True)
        if metadata["bytes"] != value["bytes"] or metadata["sha256"] != value["sha256"]:
            raise ValueError("scenario frozen input blob differs from its declared size/digest")
        if bundle is not None:
            inputs.store(raw, bundle)
    for request in plan["requests"]:
        value = request["input"]["value"]
        _, raw = files.inspect_file(source, value["sha256"], limit=inputs.MAX_FILE_BYTES, retain=True)
        payload = files.parse_json(raw)
        validate_json_types(payload)
        if (set(payload) != {"schema_version", "request_id", "input_seed", "data"} or type(payload["schema_version"]) is not int
                or payload["schema_version"] != 1 or payload["request_id"] != request["id"]
                or type(payload["input_seed"]) is not int or payload["input_seed"] != plan["input_seed"]):
            raise ValueError("scenario delivered input payload identity or seed differs from frozen request")


def _sequence(plan):
    return [("reset", "reset", None), *[phase for request in plan["requests"] for phase in
            (("transition", request["id"], request), ("request", request["id"], request["command"]))], ("shutdown", "shutdown", plan["shutdown"])]


def _row(index, role, name, status):
    return {"index": index, "role": role, "id": name, "status": status, "clock": None, "before": None, "after": None,
            "operations": [], "command_invocation_attempted": False, "effective_timeout_seconds": None,
            "timeout_computed_at_ns": None, "receipt": None, "errors": []}


def _error(stage, exc):
    return {"stage": stage, "error": f"{type(exc).__name__}: {exc}"}


def _ok(row):
    return row["status"] == "observed_unqualified"


def _phase(output, plan, index, role, name, definition, expected, target, deadline):
    start = time.monotonic_ns()
    row = _row(index, role, name, "failed")
    paths, bundle = [item["path"] for item in plan["reset"]], output / "blobs"
    try:
        if role != "shutdown" and start >= deadline:
            row["status"] = "not_run_execution_deadline"
            return row
        row["before"] = inputs.snapshot(plan["cwd"], paths, bundle)
        before = inputs.values(row["before"])
        precondition = before is not None and (expected is None or timer._same_json(before, expected))
        if not precondition:
            row["errors"].append({"stage": "precondition", "error": "declared input state is unknown or differs before the phase"})
        if role in ("reset", "transition"):
            changes = ({item["path"]: item["value"] for item in plan["reset"]} if role == "reset" else
                       {**{item["path"]: item["after"] for item in definition["edits"]}, definition["input"]["path"]: definition["input"]["value"]})
            stopped = not precondition
            for path in sorted(changes):
                operation = {"path": path, "status": "not_run", "error": None}
                if not stopped:
                    try:
                        observed = next(item for item in row["before"]["files"] if item["path"] == path)
                        operation["status"] = inputs.mutate(plan["cwd"], observed, changes[path], bundle)
                    except FAILURES as exc:
                        operation.update(status="unknown", error=f"{type(exc).__name__}: {exc}")
                        stopped = True
                row["operations"].append(operation)
        elif precondition or role == "shutdown":
            computed = time.monotonic_ns()
            effective = definition["timeout_seconds"] if role == "shutdown" else min(definition["timeout_seconds"], (deadline - computed) / 1e9)
            if effective <= 0:
                row["status"] = "not_run_execution_deadline"
                row["timeout_computed_at_ns"] = computed
            else:
                row.update(command_invocation_attempted=None, effective_timeout_seconds=effective, timeout_computed_at_ns=computed)
                try:
                    inner = timer.measure_and_publish(definition["argv"], plan["cwd"], effective, output / f"command-{index:04d}.json",
                                                      required_finalization=definition["required_finalization"], guard_expectations=definition["guard_expectations"],
                                                      archive_bundle=bundle)
                    row.update(receipt=inner, command_invocation_attempted=True if inner["result"] is not None else None)
                    try:
                        timer.inspect_lifecycle(output / f"command-{index:04d}.json", inner, archived_bundle=bundle)
                    except FAILURES as exc:
                        row["errors"].append(_error("command_validation", exc))
                except FAILURES as exc:
                    row["errors"].append(_error("observation", exc))
                    row["status"] = "unknown"
        row["after"] = inputs.snapshot(plan["cwd"], paths, bundle)
        after = inputs.values(row["after"])
        desired = before if role == "shutdown" else target
        if after is None or desired is None or not timer._same_json(after, desired):
            row["errors"].append({"stage": "postcondition", "error": "declared input state is unknown or differs after the phase"})
        if row["status"] not in ("unknown", "not_run_execution_deadline"):
            inner = row["receipt"]
            command_ok = role in ("reset", "transition") or (inner is not None and inner["lifecycle"]["status"] == "finalized_unqualified"
                         and (inner["observation_guard"] is None or inner["observation_guard"]["matched_expected_observations"]))
            row["status"] = "observed_unqualified" if not row["errors"] and command_ok and all(op["status"] in ("applied", "unchanged") for op in row["operations"]) else "failed"
    finally:
        row["clock"] = timer._timing(start)
    return row


def _inputs(output):
    inventory, identities = capture_run(output)
    entries = [item for item in inventory["files"] if item["path"] != "unit.json"]
    return _inventory(inventory["directories"], entries), {item["path"]: identities[item["path"]] for item in entries}


def _terminal(plan, rows, binding, errors):
    return ("aborted" if binding is None or errors else "unsupported" if plan["scenario"]["id"] in UNSUPPORTED else
            "completed_unqualified" if all(_ok(row) for row in rows) else "aborted")


def run_scenario(output, requested, payload_root, *, apply=False):
    start = time.monotonic_ns()
    if type(apply) is not bool or not apply:
        raise ValueError("explicit --apply is required for scenario file resets and edits")
    files.require_safe_lookup()
    validate_plan(requested)
    plan = copy.deepcopy(requested)
    plan["cwd"] = str(Path(plan["cwd"]).resolve(strict=True))
    payload_root = Path(payload_root).resolve(strict=True)
    output = Path(os.path.abspath(output))
    resolved_output = output.parent.resolve(strict=True) / output.name
    cwd = Path(plan["cwd"])
    if any(left.is_relative_to(right) or right.is_relative_to(left) for left, right in ((cwd, payload_root), (cwd, resolved_output), (payload_root, resolved_output))):
        raise ValueError("scenario worktree, payloads and evidence roots must be separate and nonnested")
    fd = os.open(cwd, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    _payloads(plan, payload_root)  # Validate all source bytes and seed identities before any subject/file effects.
    output.mkdir(mode=0o700)
    (output / "blobs").mkdir(mode=0o700)
    _payloads(plan, payload_root, output / "blobs")
    publication_start = time.monotonic_ns()
    binding, identity = _publish(output / "plan.json", plan, "plan")
    publication_clock = timer._timing(publication_start)
    deadline, states = start + round(plan["execution_timeout_seconds"] * 1e9), _states(plan)
    sequence, rows, stopped = _sequence(plan), [], False

    def observe(index, item):
        role, name, definition = item
        state_index = next((number for number, request in enumerate(plan["requests"]) if request["id"] == name), None)
        expected = None if role in ("reset", "shutdown") else states[state_index if role == "transition" else state_index + 1]
        target = states[0] if role == "reset" else states[state_index + 1] if role != "shutdown" else None
        return _phase(output, plan, index, role, name, definition, expected, target, deadline)

    if plan["scenario"]["id"] in UNSUPPORTED:
        rows = [_row(index, role, name, "not_run_unsupported") for index, (role, name, _) in enumerate(sequence, 1)]
    else:
        try:
            for index, item in enumerate(sequence[:-1], 1):
                if stopped:
                    rows.append(_row(index, *item[:2], "not_run_prior_failure"))
                    continue
                checked = time.monotonic_ns()
                try:
                    current, _ = files.inspect_file(output, "plan.json", limit=MAX_PLAN_BYTES)
                    if current != identity:
                        raise ValueError("frozen scenario plan changed before a later phase")
                except FAILURES as exc:
                    row = _row(index, *item[:2], "not_run_plan_changed")
                    row.update(clock=timer._timing(checked), errors=[_error("plan_binding", exc)])
                else:
                    row = observe(index, item)
                rows.append(row)
                stopped = not _ok(row)
        finally:
            rows.append(observe(len(sequence), sequence[-1]))
    retained, identities = _inputs(output)
    unit = {"schema_version": 1, "kind": "scenario_edit_replay_unit", "plan": binding, "phases": rows, "retained_inputs": retained}
    errors, unit_binding = [], None
    unit_start = time.monotonic_ns()
    try:
        unit_binding, _ = _publish(output / "unit.json", unit, "unit")
    except FAILURES as exc:
        errors.append(_error("unit_publication", exc))
    unit_clock = timer._timing(unit_start)
    try:
        if _inputs(output) != (retained, identities):
            raise ValueError("scenario retained bytes changed across unit publication")
    except FAILURES as exc:
        errors.append(_error("retained_input_binding", exc))
    receipt = {"schema_version": 1, "kind": "scenario_edit_replay_receipt", "mode": "exploratory_unqualified", "measurement_layer": LAYER,
               "sample_unit": UNIT, "timing_endpoint": ENDPOINT, "confirmatory_eligible": False, "plan": binding,
               "unit": unit_binding, "diagnostic_unit": unit if unit_binding is None else None,
               "clock": timer._timing(start), "plan_publication_clock": publication_clock, "unit_publication_clock": unit_clock,
               "status": _terminal(plan, rows, unit_binding, errors), "errors": errors, "qualification": {field: None for field in QUALIFICATION}, "limitations": LIMITATIONS.copy()}
    validate("receipt", receipt)
    if len(_raw(receipt)) > files.MAX_RECEIPT_BYTES:
        raise ValueError("scenario receipt exceeds limit; whole session remains unconfirmed")
    inspect_scenario(output, receipt)
    return receipt


def _inspect_snapshot(value, paths, directory, outer):
    replay._interval(value["clock"], outer)
    if [row["path"] for row in value["files"]] != paths:
        raise ValueError("scenario snapshot omitted or reordered a declared input")
    for row in value["files"]:
        observed = row["value"]
        if row["status"] == "present":
            if observed is None or row["identity"] is None or row["error"] is not None or row["identity"][2] != observed["bytes"]:
                raise ValueError("scenario present input lacks consistent retained byte/identity evidence")
            metadata, _ = files.inspect_file(directory / "blobs", observed["sha256"], limit=inputs.MAX_FILE_BYTES)
            if metadata["bytes"] != observed["bytes"] or metadata["sha256"] != observed["sha256"]:
                raise ValueError("scenario observed input blob is corrupt or missing")
        elif observed is not None or row["identity"] is not None or (row["status"] == "unknown") != (row["error"] is not None):
            raise ValueError("scenario absent/unknown input invents observed content or omits its error")


def inspect_scenario(output, receipt):
    """Reconstruct from historical bytes only; never read later worktree state or apply effects."""
    output = Path(output)
    validate("receipt", receipt)
    if receipt["limitations"] != LIMITATIONS or len(_raw(receipt)) > files.MAX_RECEIPT_BYTES:
        raise ValueError("scenario receipt limitations or size differ")
    before = capture_run(output)
    inputs.check_limits(output / "blobs")
    plan, metadata = files.read_json(output / "plan.json", limit=MAX_PLAN_BYTES)
    validate_plan(plan)
    if not timer._same_json(receipt["plan"], _binding("plan.json", metadata)):
        raise ValueError("scenario plan binding differs from retained bytes")
    _payloads(plan, output / "blobs")
    if receipt["unit"] is not None:
        unit, metadata = files.read_json(output / "unit.json", limit=MAX_UNIT_BYTES)
        if receipt["diagnostic_unit"] is not None or not timer._same_json(receipt["unit"], _binding("unit.json", metadata)):
            raise ValueError("scenario unit byte binding differs")
    else:
        unit = receipt["diagnostic_unit"]
        if unit is None or not any(error["stage"] == "unit_publication" for error in receipt["errors"]):
            raise ValueError("scenario missing unit without matching publication failure")
        if os.path.lexists(output / "unit.json"):
            visible, _ = files.read_json(output / "unit.json", limit=MAX_UNIT_BYTES)
            if not timer._same_json(visible, unit):
                raise ValueError("unconfirmed scenario unit contradicts visible bytes")
    validate("unit", unit)
    if any(error["stage"] not in ("unit_publication", "retained_input_binding") for error in receipt["errors"]):
        raise ValueError("scenario receipt contains an error from a different observation stage")
    if not timer._same_json(unit["plan"], receipt["plan"]) or not timer._same_json(_inputs(output)[0], unit["retained_inputs"]):
        raise ValueError("scenario unit plan or recursive inventory differs")
    replay._interval(receipt["clock"])
    for key in ("plan_publication_clock", "unit_publication_clock"):
        replay._interval(receipt[key], receipt["clock"])
    states, paths, sequence = _states(plan), [item["path"] for item in plan["reset"]], _sequence(plan)
    if len(unit["phases"]) != len(sequence):
        raise ValueError("scenario omitted planned reset, edit, request or shutdown work")
    stopped, last = False, receipt["plan_publication_clock"]["monotonic_end_ns"]
    references = {"plan.json"} | {"blobs/" + value["sha256"] for state in states for value in state.values() if value is not None}
    for index, (row, (role, name, definition)) in enumerate(zip(unit["phases"], sequence), 1):
        if (row["index"], row["role"], row["id"]) != (index, role, name):
            raise ValueError("scenario phase identity/order differs from frozen plan")
        if any(error["stage"] not in ("precondition", "postcondition", "observation", "command_validation", "plan_binding") for error in row["errors"]):
            raise ValueError("scenario phase contains an error from another observation stage")
        skip = "not_run_unsupported" if plan["scenario"]["id"] in UNSUPPORTED else "not_run_prior_failure" if stopped and role != "shutdown" else None
        if skip is not None:
            if not timer._same_json(row, _row(index, role, name, skip)):
                raise ValueError("scenario work ran after failure or in an unsupported profile")
            continue
        if row["clock"] is None:
            raise ValueError("scenario considered phase has no clock")
        replay._interval(row["clock"], receipt["clock"])
        if row["clock"]["monotonic_start_ns"] < last:
            raise ValueError("scenario phase order/clock overlaps")
        last = row["clock"]["monotonic_end_ns"]
        if row["status"] == "not_run_plan_changed":
            if role == "shutdown" or row["errors"] == [] or row["errors"][0]["stage"] != "plan_binding":
                raise ValueError("scenario pre-call plan failure has no cause")
            expected = _row(index, role, name, row["status"])
            expected.update(clock=row["clock"], errors=row["errors"])
            if not timer._same_json(row, expected):
                raise ValueError("scenario pre-call plan failure invents effects")
            stopped = True
            continue
        if row["before"] is None:
            deadline = receipt["clock"]["monotonic_start_ns"] + round(plan["execution_timeout_seconds"] * 1e9)
            expected = _row(index, role, name, "not_run_execution_deadline")
            expected["clock"] = row["clock"]
            if role == "shutdown" or row["clock"]["monotonic_start_ns"] < deadline or not timer._same_json(row, expected):
                raise ValueError("scenario missing snapshot without exhausted pre-start budget")
            stopped = True
            continue
        if row["after"] is None:
            raise ValueError("scenario considered phase omitted its post-state observation")
        for snapshot in (row["before"], row["after"]):
            _inspect_snapshot(snapshot, paths, output, row["clock"])
            references.update("blobs/" + item["value"]["sha256"] for item in snapshot["files"] if item["value"] is not None)
        if row["after"]["clock"]["monotonic_start_ns"] < row["before"]["clock"]["monotonic_end_ns"]:
            raise ValueError("scenario post-state precedes pre-state")
        number = next((number for number, request in enumerate(plan["requests"]) if request["id"] == name), None)
        previous = None if role in ("reset", "shutdown") else states[number if role == "transition" else number + 1]
        actual = inputs.values(row["before"])
        precondition = actual is not None and (previous is None or timer._same_json(actual, previous))
        desired = states[0] if role == "reset" else actual if role == "shutdown" else states[number + 1]
        postcondition = desired is not None and inputs.values(row["after"]) is not None and timer._same_json(inputs.values(row["after"]), desired)
        if (any(error["stage"] == "precondition" for error in row["errors"]) != (not precondition)
                or any(error["stage"] == "postcondition" for error in row["errors"]) != (not postcondition)):
            raise ValueError("scenario state mismatch lacks matching failure evidence")
        inner = row["receipt"]
        if role in ("reset", "transition"):
            changes = ({item["path"]: item["value"] for item in plan["reset"]} if role == "reset" else
                       {**{item["path"]: item["after"] for item in definition["edits"]}, definition["input"]["path"]: definition["input"]["value"]})
            if ([op["path"] for op in row["operations"]] != sorted(changes) or inner is not None or row["command_invocation_attempted"] is not False
                    or row["timeout_computed_at_ns"] is not None or row["effective_timeout_seconds"] is not None
                    or any(error["stage"] not in ("precondition", "postcondition") for error in row["errors"])):
                raise ValueError("scenario mutation omitted operations or invented a command")
            stopped_effects = not precondition
            for op in row["operations"]:
                if stopped_effects:
                    if op != {"path": op["path"], "status": "not_run", "error": None}:
                        raise ValueError("scenario mutation ran after partial/unknown effects")
                elif op["status"] == "unknown":
                    if op["error"] is None:
                        raise ValueError("unknown scenario file effect lacks error")
                    stopped_effects = True
                elif op["status"] not in ("applied", "unchanged") or op["error"] is not None:
                    raise ValueError("scenario file effect is missing or contradictory")
                elif (op["status"] == "unchanged") != timer._same_json(actual[op["path"]], changes[op["path"]]):
                    raise ValueError("scenario unchanged/applied effect contradicts its input precondition")
                elif not timer._same_json(next(item["value"] for item in row["after"]["files"] if item["path"] == op["path"]), changes[op["path"]]) and postcondition:
                    raise ValueError("scenario applied effect contradicts its post-state")
        else:
            if row["operations"]:
                raise ValueError("scenario command invents file operations")
            if inner is not None:
                timer.inspect_lifecycle(output / f"command-{index:04d}.json", inner, archived_bundle=output / "blobs")
                if (inner["cwd"] != plan["cwd"] or inner["context"] is not None
                        or not timer._same_json(inner["required_finalization"]["requirements"], definition["required_finalization"])
                        or not timer._same_json(inner["guard_expectations"], definition["guard_expectations"]) or inner["raw_bundle"] is not None):
                    raise ValueError("scenario command contract differs from frozen request")
                if inner["result"] is not None:
                    _measurement(inner["result"], definition["argv"], plan["cwd"])
                if row["command_invocation_attempted"] is not (True if inner["result"] is not None else None):
                    raise ValueError("scenario command invocation certainty differs from receipt")
                replay._interval(inner["lifecycle"], row["clock"])
                if (inner["lifecycle"]["monotonic_start_ns"] < row["before"]["clock"]["monotonic_end_ns"]
                        or inner["lifecycle"]["monotonic_end_ns"] > row["after"]["clock"]["monotonic_start_ns"]):
                    raise ValueError("scenario input observations do not enclose the request")
                if inner["sample"] is not None:
                    references.add(inner["sample"]["name"])
                elif os.path.lexists(output / f"command-{index:04d}.json"):
                    references.add(f"command-{index:04d}.json")
                if inner["artifact_archive"] is not None:
                    references.update("blobs/" + item["sha256"] for item in inner["artifact_archive"]["artifacts"])
            if inner is not None or row["command_invocation_attempted"] is None or row["status"] == "not_run_execution_deadline":
                computed, effective = row["timeout_computed_at_ns"], row["effective_timeout_seconds"]
                deadline = receipt["clock"]["monotonic_start_ns"] + round(plan["execution_timeout_seconds"] * 1e9)
                if computed is None or not row["before"]["clock"]["monotonic_end_ns"] <= computed <= row["after"]["clock"]["monotonic_start_ns"]:
                    raise ValueError("scenario effective timeout timestamp is outside its request")
                if row["status"] == "not_run_execution_deadline":
                    if role == "shutdown" or computed < deadline or effective is not None or row["command_invocation_attempted"] is not False:
                        raise ValueError("scenario exhausted command budget lacks its computation or invents invocation")
                else:
                    expected = definition["timeout_seconds"] if role == "shutdown" else min(definition["timeout_seconds"], (deadline - computed) / 1e9)
                    if effective is None or not 0 < effective == expected:
                        raise ValueError("scenario request budget differs from declared deadline")
            elif row["effective_timeout_seconds"] is not None or row["timeout_computed_at_ns"] is not None:
                raise ValueError("non-invoked scenario command invents timeout bookkeeping")
        command_ok = role in ("reset", "transition") or (inner is not None and inner["lifecycle"]["status"] == "finalized_unqualified"
                     and (inner["observation_guard"] is None or inner["observation_guard"]["matched_expected_observations"]))
        unknown = role in ("request", "shutdown") and inner is None and row["command_invocation_attempted"] is None
        if unknown != any(error["stage"] == "observation" for error in row["errors"]):
            raise ValueError("scenario missing command return lacks matching observation error")
        expired = (role == "request" and precondition and inner is None and row["command_invocation_attempted"] is False
                   and row["timeout_computed_at_ns"] is not None
                   and row["timeout_computed_at_ns"] >= receipt["clock"]["monotonic_start_ns"] + round(plan["execution_timeout_seconds"] * 1e9))
        if role in ("request", "shutdown"):
            if inner is None and not unknown and not expired and (precondition or role == "shutdown"):
                raise ValueError("scenario missing command is neither a returned observation, unknown return nor a justified non-invocation")
            if any(error["stage"] == "command_validation" for error in row["errors"]) and inner is None:
                raise ValueError("scenario command validation error lacks a returned receipt")
        expected_status = ("unknown" if unknown else "not_run_execution_deadline" if expired else
                           "observed_unqualified" if command_ok and not row["errors"] and all(op["status"] in ("applied", "unchanged") for op in row["operations"]) else "failed")
        if row["status"] != expected_status:
            raise ValueError("scenario phase status contradicts observations or file effects")
        if not precondition and role != "shutdown" and (inner is not None or row["command_invocation_attempted"] is not False):
            raise ValueError("scenario request ran with mismatched or unknown inputs")
        if role != "shutdown":
            stopped = not _ok(row)
    if receipt["unit_publication_clock"]["monotonic_start_ns"] < last:
        raise ValueError("scenario unit published before shutdown or final observation")
    # Lost command returns may leave attributable diagnostic files/blobs. Bind
    # them without recovering a command result from complete-looking files.
    unknown_names = {f"command-{row['index']:04d}.json" for row in unit["phases"] if any(error["stage"] == "observation" for error in row["errors"])}
    for entry in unit["retained_inputs"]["files"]:
        if entry["path"] not in references and not (entry["path"] in unknown_names or unknown_names and re.fullmatch(r"blobs/[0-9a-f]{64}", entry["path"])):
            raise ValueError("unexpected scenario evidence is not an attributable missing-return diagnostic")
    if receipt["status"] != _terminal(plan, unit["phases"], receipt["unit"], receipt["errors"]):
        raise ValueError("scenario terminal status contradicts retained outcomes")
    if capture_run(output) != before:
        raise ValueError("scenario evidence changed during inspection")
    requests = [row for row in unit["phases"] if row["role"] == "request"]
    return {"record_consistency": "checked_unqualified", "kind": "scenario_edit_replay_validation", "status": receipt["status"],
            "measurement_layer": LAYER, "sample_unit": UNIT, "timing_endpoint": ENDPOINT, "scenario": plan["scenario"],
            "planned_request_count": len(requests), "request_status_counts": dict(sorted(Counter(row["status"] for row in requests).items())),
            "known_request_invocations": sum(row["command_invocation_attempted"] is True for row in requests),
            "unknown_request_invocations": sum(row["command_invocation_attempted"] is None for row in requests),
            "known_not_invoked_requests": sum(row["command_invocation_attempted"] is False for row in requests),
            "planned_phase_count": len(sequence), "phase_status_counts": dict(sorted(Counter(row["status"] for row in unit["phases"]).items())),
            "reset_status": unit["phases"][0]["status"], "shutdown_status": unit["phases"][-1]["status"],
            "unknown_file_effect_returns": sum(op["status"] == "unknown" for row in unit["phases"] for op in row["operations"]),
            "declared_input_paths": paths, "input_seed": plan["input_seed"], "qualification": receipt["qualification"],
            "ratio": None, "bootstrap": None, "confirmatory_eligible": False, "limitations": LIMITATIONS.copy()}


def compare_scenarios(baseline, baseline_receipt, candidate, candidate_receipt):
    reports = [inspect_scenario(root, receipt) for root, receipt in ((baseline, baseline_receipt), (candidate, candidate_receipt))]
    plans = [files.read_json(Path(root) / "plan.json", limit=MAX_PLAN_BYTES)[0] for root in (baseline, candidate)]
    declarations = [{**{key: plan[key] for key in ("scenario", "input_seed", "reset", "execution_timeout_seconds")},
                     "requests": [{**{key: request[key] for key in ("id", "edits", "input")},
                                   "timeout_seconds": request["command"]["timeout_seconds"], "expected_exit_code": request["command"]["required_finalization"]["expected_exit_code"]}
                                  for request in plan["requests"]],
                     "shutdown_policy": {"timeout_seconds": plan["shutdown"]["timeout_seconds"], "expected_exit_code": plan["shutdown"]["required_finalization"]["expected_exit_code"]}} for plan in plans]
    reasons = []
    if not timer._same_json(declarations[0], declarations[1]):
        reasons.append("declared_scenario_reset_edits_or_inputs_differ")
    if any(report["status"] != "completed_unqualified" for report in reports):
        reasons.append("one_or_both_scenario_observations_incomplete")
    first, second = (Path(plan["cwd"]) for plan in plans)
    if first.is_relative_to(second) or second.is_relative_to(first):
        reasons.append("arm_worktrees_not_separate")
    return {"status": "blocked" if reasons else "declared_file_inputs_matched_unqualified", "reasons": reasons,
            "observations": reports, "semantic_equal_work": None, "reset_equivalence": None,
            "independent_units": None, "ratio": None, "bootstrap": None, "confirmatory_eligible": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--payloads", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--apply", action="store_true")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--directory", type=Path, required=True)
    inspect.add_argument("--receipt", type=Path, required=True)
    compare = commands.add_parser("compare")
    for arm in ("baseline", "candidate"):
        compare.add_argument("--" + arm, type=Path, required=True)
        compare.add_argument("--" + arm + "-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            plan, _ = files.read_json(args.plan, limit=MAX_PLAN_BYTES)
            value = run_scenario(args.output, plan, args.payloads, apply=args.apply)
            code = 3 if value["status"] == "unsupported" else 0 if value["status"] == "completed_unqualified" else 1
        elif args.command == "inspect":
            receipt, _ = files.read_json(args.receipt, limit=files.MAX_RECEIPT_BYTES)
            value, code = inspect_scenario(args.directory, receipt), 0
        else:
            baseline, _ = files.read_json(args.baseline_receipt, limit=files.MAX_RECEIPT_BYTES)
            candidate, _ = files.read_json(args.candidate_receipt, limit=files.MAX_RECEIPT_BYTES)
            value = compare_scenarios(args.baseline, baseline, args.candidate, candidate)
            code = int(value["status"] == "blocked")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"scenario-replay: {exc}\n")
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
