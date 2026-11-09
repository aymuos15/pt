"""Synthetic WP00 contract examples, never observed product/benchmark evidence."""

from copy import deepcopy


DIGEST = "a" * 64
TRACE_CASES = (
    "pass", "setup_skip", "setup_failure", "call_skip", "call_failure", "xfail", "xpass",
    "teardown_failure", "strict_xpass", "collection_failure", "collection_failure_partial", "collection_interrupted", "no_tests", "all_deselected",
    "collect_only", "fail_fast", "retry", "timeout", "interrupted", "timeout_zero_exit", "interrupted_zero_exit", "backend_interrupted", "crash",
    "missing_terminal", "reporting_incomplete", "artifact_missing", "artifact_failed", "artifact_partial",
    "cleanup_uncertain", "environment_unverified", "generation_stale", "generation_live",
    "generation_uncertain", "generation_unverified", "timeout_after_zero", "interrupted_after_zero",
    "configuration_error", "unsupported_profile", "launch_error", "internal_error", "usage_error", "undocumented_exit",
)


def phase_counts():
    return {phase: {outcome: 0 for outcome in ("passed", "failed", "skipped")}
            for phase in ("setup", "call", "teardown")}


def accounting():
    return dict.fromkeys(("collected_count", "selected_count", "deselected_count", "executed_count",
                          "completed_count", "not_run_count", "attempts_started", "attempts_completed"), 0)


COORDINATOR = {
    "request_rejected": {"outcome": "unsupported_profile", "code": "unsupported_interpreter", "message": "synthetic unsupported version"},
    "request_accepted": {"mode": "run", "scope": "full", "invocation_profile": "pytest_console",
                         "required_artifact_ids": [], "retry_policy": "disabled", "retry_plugin": None,
                         "max_attempts": 1},
    "environment_resolved": {"profile_id": "linux-x86_64-cpython312-pytest842", "invocation_profile": "pytest_console",
                             "interpreter_sha256": DIGEST, "installed_inventory_sha256": DIGEST, "verified": True},
    "capability_decision": {"capability": "execution.reorder", "decision": "unknown", "scope": "session",
                            "issuer": "pt-policy", "issuer_version": "0.0.0", "evidence_digest": None,
                            "input_domain": "this request only", "reason": "no permission evidence",
                            "invalidation_conditions": ["any profile or plugin change"]},
    "artifact_declared": {"artifact_id": "coverage", "artifact_kind": "coverage", "required": True},
    "artifact_committed": {"artifact_id": "coverage", "sha256": DIGEST, "bytes": 123, "complete": True, "verified": True},
    "artifact_failed": {"artifact_id": "coverage", "code": "write_failed", "message": "synthetic disk-full example"},
    "infrastructure_error": {"code": "protocol_eof", "message": "synthetic missing terminal example"},
    "cancellation_requested": {"origin": "signal", "signal": 2},
    "deadline_exceeded": {"phase": "call", "timeout_ns": 1000000000},
    "resource_event": {"resource_id": "service", "state": "denied", "reason": "reuse unavailable in serial v0"},
    "worker_exited": {"exit_code": 0, "signal": None, "core_dumped": False, "reaped": True},
    "cleanup_finished": {"status": "complete", "leader_reaped": True, "live_members": 0, "reason": None},
    "generation_checked": {"status": "current", "assurance": "immutable_snapshot", "identity_sha256": DIGEST,
                           "declared_inputs_complete": True},
}

BRIDGE = {
    "session_started": {"python_version": "3.12.12", "pytest_version": "8.4.2", "bridge_version": "0.0.0",
                        "invocation_profile": "pytest_console"},
    "collection_started": {},
    "collection_report": {"report_id": 0, "nodeid": "tests/test_λ.py", "outcome": "passed", "reason": None},
    "collection_error": {"report_id": 0, "nodeid": "", "reason": "synthetic root collector failure"},
    "item_collected": {"ordinal": 0, "nodeid": "tests/test_λ.py::test_x[α]"},
    "items_selected": {"chunk": 0, "ordinals": [0]},
    "items_deselected": {"chunk": 0, "ordinals": [1], "reason": None},
    "collection_finished": {"status": "complete", "inventory_complete": True, "collected_count": 1,
                            "selected_count": 1, "deselected_count": 0},
    "item_started": {"ordinal": 0, "attempt": 0},
    "phase_report": {"ordinal": 0, "attempt": 0, "phase": "setup", "outcome": "passed", "reason": None,
                     "was_xfail": None, "strict_xpass": False, "duration_ns": None, "artifact_ids": []},
    "attempt_finished": {"ordinal": 0, "attempt": 0, "disposition": "completed", "reason": None},
    "item_not_run": {"ordinal": 0, "reason": "collect_only"},
    "warning": {"ordinal": None, "category": "UserWarning", "message": "synthetic warning", "filename": "tests/test_λ.py",
                "line": 1, "when": "collect"},
    "output_reference": {"artifact_id": "stdout", "stream": "stdout", "ordinal": 0, "attempt": 0},
    "artifact_ready": {"artifact_id": "coverage", "sha256": DIGEST, "bytes": 123, "complete": True},
    "session_error": {"category": "internal", "code": "pytest_internal_error", "message": "synthetic failure"},
    "extension_event": {"extension_id": "subtests", "extension_version": 1, "artifact_id": "extension",
                        "ordinal": 0, "attempt": 0},
    "session_terminated": {"termination": "backend_exited", "backend_exit_code": 0, "reporting_complete": True,
                           "accounting": accounting(), "phase_counts": phase_counts(), "incomplete_ordinals": []},
}


def event(kind, payload=None, *, sequence=0):
    role = "coordinator" if kind in COORDINATOR else "bridge"
    if payload is None:
        payload = (COORDINATOR if role == "coordinator" else BRIDGE)[kind]
    return {"protocol_version": 0, "contract_revision": 1, "request_id": "request", "run_id": "run",
            "generation_id": "gen", "session_id": "session", "producer_id": role,
            "producer_role": role, "sequence": sequence, "kind": kind, "payload": deepcopy(payload)}


def trace_fixture(case="pass", *, scope="full", deselect=False, artifact=True):
    """Independent hand-constructed examples, not generated by the checker.

    All hashes/verification assertions are synthetic placeholders. No files,
    interpreter, pytest session, snapshot, or artifact are measured here.
    """
    if case not in TRACE_CASES:
        raise ValueError(f"unknown synthetic scenario: {case}")
    events, sequence = [], {"coordinator": 0, "bridge": 0}

    def emit(kind, payload=None):
        message = event(kind, payload)
        role = message["producer_role"]
        message["sequence"] = sequence[role]
        sequence[role] += 1
        events.append(message)
        return message["payload"]

    early = case in ("configuration_error", "unsupported_profile", "launch_error")
    interrupted = case in ("timeout", "interrupted", "timeout_zero_exit", "interrupted_zero_exit", "crash", "backend_interrupted")
    missing_terminal = case in ("timeout", "interrupted", "timeout_zero_exit", "interrupted_zero_exit", "crash", "missing_terminal")
    mode = "collect_only" if case == "collect_only" else "run"
    request = deepcopy(COORDINATOR["request_accepted"])
    request.update(scope=scope, mode=mode, required_artifact_ids=["coverage"] if artifact else [])
    if case == "retry":
        request.update(retry_policy="backend_plugin", retry_plugin="synthetic-rerun", max_attempts=2)
    emit("request_accepted", request)
    errors, capabilities, artifacts = [], [], []
    generation = {"status": "unverified", "assurance": "unverified", "identity_sha256": None, "declared_inputs_complete": False}
    cleanup = {"status": "not_started", "leader_reaped": False, "live_members": None, "reason": None}
    counts, phases, incomplete, collection_error_ids = accounting(), phase_counts(), [], []
    raw_code, raw_signal, stop_cause, interruption_signal = None, None, "none", None
    collection_status, inventory_complete = "not_started", False
    reporting_complete = accounting_verified = work_complete = environment_verified = False
    artifacts_verified = not artifact
    infrastructure = "not_started"

    if early:
        emit("request_rejected", {"outcome": case, "code": case, "message": "synthetic prelaunch failure"})
        category = {"configuration_error": "configuration", "unsupported_profile": "unsupported", "launch_error": "infrastructure"}[case]
        errors.append({"producer_role": "coordinator", "category": category, "code": case, "message": "synthetic prelaunch failure"})
        outcome, cli_exit = case, 3 if case == "launch_error" else 4
        infrastructure = "failed" if case == "launch_error" else "not_started"
    else:
        environment = deepcopy(COORDINATOR["environment_resolved"])
        if case == "environment_unverified":
            environment.update(verified=False, installed_inventory_sha256=None)
        emit("environment_resolved", environment)
        environment_verified = environment["verified"]
        if artifact:
            emit("artifact_declared")
            artifacts.append({"artifact_id": "coverage", "required": True, "status": "pending",
                              "sha256": None, "bytes": None, "complete": False, "verified": False, "failure": None})
        capabilities.append(emit("capability_decision"))
        emit("session_started")
        emit("collection_started")
        collection_status = ("failed" if case in ("collection_failure", "collection_failure_partial") else
                             "interrupted" if case == "collection_interrupted" else "complete")
        inventory_complete = collection_status == "complete"
        report = deepcopy(BRIDGE["collection_report"])
        if case in ("collection_failure", "collection_failure_partial"):
            report.update(nodeid="", outcome="failed", reason="synthetic root collector failure")
        emit("collection_report", report)
        if case in ("collection_failure", "collection_failure_partial"):
            emit("collection_error")
            collection_error_ids = [0]
        empty = case in ("collection_failure", "no_tests")
        selected = [] if empty or case == "all_deselected" else [1, 0]
        count = 0 if empty else 3 if deselect else 2
        for ordinal in range(count):
            emit("item_collected", {"ordinal": ordinal, "nodeid": "tests/test_λ.py::same[α]"})
        if selected:
            emit("items_selected", {"chunk": 0, "ordinals": selected})
        if case == "all_deselected" or deselect and not empty:
            emit("items_deselected", {"chunk": 0, "ordinals": list(range(count)) if case == "all_deselected" else [2], "reason": None})
        counts.update(collected_count=count, selected_count=len(selected), deselected_count=count - len(selected))
        emit("collection_finished", {"status": collection_status, "inventory_complete": inventory_complete,
                                      **{key: counts[key] for key in ("collected_count", "selected_count", "deselected_count")}})
        emit("warning")
        raw_code = (2 if case in ("collection_failure", "collection_failure_partial", "collection_interrupted", "backend_interrupted") else
                    5 if case in ("no_tests", "all_deselected") else
                    3 if case == "internal_error" else 4 if case == "usage_error" else
                    7 if case == "undocumented_exit" else 1 if case in (
                        "setup_failure", "call_failure", "teardown_failure", "strict_xpass", "fail_fast") else 0)
        for ordinal in selected:
            if case in ("collection_failure_partial", "collection_interrupted"):
                emit("item_not_run", {"ordinal": ordinal, "reason": "collection_failed" if collection_status == "failed" else "interrupted"})
                counts["not_run_count"] += 1
                continue
            if case == "collect_only" or (case == "fail_fast" and ordinal == 0):
                emit("item_not_run", {"ordinal": ordinal, "reason": "collect_only" if mode == "collect_only" else "fail_fast"})
                counts["not_run_count"] += 1
                continue
            if interrupted and ordinal == 0:
                continue
            counts["executed_count"] += 1
            attempts = (0, 1) if case == "retry" and ordinal == 1 else (0,)
            for attempt in attempts:
                emit("item_started", {"ordinal": ordinal, "attempt": attempt})
                counts["attempts_started"] += 1
                setup = "skipped" if case == "setup_skip" and ordinal == 1 else "failed" if case == "setup_failure" and ordinal == 1 else "passed"
                order = ["setup"] if interrupted else ["setup", "teardown"] if setup != "passed" else list(("setup", "call", "teardown"))
                for phase in order:
                    outcome = setup if phase == "setup" else "failed" if (
                        (case in ("call_failure", "strict_xpass", "fail_fast") and ordinal == 1 and phase == "call") or
                        (case == "teardown_failure" and ordinal == 1 and phase == "teardown") or
                        (case == "retry" and ordinal == 1 and attempt == 0 and phase == "call")) else "passed"
                    payload = deepcopy(BRIDGE["phase_report"])
                    payload.update(ordinal=ordinal, attempt=attempt, phase=phase, outcome=outcome,
                                   strict_xpass=case == "strict_xpass" and ordinal == 1 and phase == "call")
                    if phase == "call" and ordinal == 1 and case in ("call_skip", "xfail", "xpass"):
                        payload["outcome"] = "passed" if case == "xpass" else "skipped"
                        payload["reason"] = "synthetic marker"
                        if case in ("xfail", "xpass"):
                            payload["was_xfail"] = "synthetic expected failure"
                    if payload["strict_xpass"]:
                        payload["reason"] = "[XPASS(strict)] synthetic strict marker"
                    emit("phase_report", payload)
                    phases[phase][payload["outcome"]] += 1
                if not interrupted:
                    disposition = "retry" if len(attempts) == 2 and attempt == 0 else "completed"
                    emit("attempt_finished", {"ordinal": ordinal, "attempt": attempt, "disposition": disposition, "reason": None})
                    counts["attempts_completed"] += 1
            if not interrupted:
                counts["completed_count"] += 1
        if interrupted:
            incomplete = selected.copy()
        if case in ("internal_error", "usage_error"):
            emit("session_error", {"category": "internal" if case == "internal_error" else "usage",
                                    "code": case, "message": "synthetic pytest session error"})
            errors.append({"producer_role": "bridge", "category": "internal" if case == "internal_error" else "usage",
                           "code": case, "message": "synthetic pytest session error"})
        if artifact and not interrupted and case not in ("artifact_missing",):
            ready = deepcopy(BRIDGE["artifact_ready"])
            ready["complete"] = case != "artifact_partial"
            emit("artifact_ready", ready)
        if not missing_terminal:
            emit("session_terminated", {"termination": "interrupted" if case in ("backend_interrupted", "collection_interrupted") else "backend_exited", "backend_exit_code": raw_code,
                                         "reporting_complete": case != "reporting_incomplete", "accounting": counts,
                                         "phase_counts": phases, "incomplete_ordinals": incomplete})
        if case in ("timeout", "timeout_after_zero", "timeout_zero_exit"):
            emit("deadline_exceeded")
            stop_cause = "timeout"
        elif case in ("interrupted", "interrupted_after_zero", "interrupted_zero_exit"):
            emit("cancellation_requested")
            stop_cause, interruption_signal = "interrupted", 2
        if case in ("timeout_zero_exit", "interrupted_zero_exit"):
            raw_code, raw_signal = 0, None
        elif interrupted and case != "backend_interrupted":
            raw_code, raw_signal = None, 9
        emit("worker_exited", {"exit_code": raw_code, "signal": raw_signal, "core_dumped": False, "reaped": True})
        cleanup = deepcopy(COORDINATOR["cleanup_finished"])
        if case == "cleanup_uncertain":
            cleanup.update(status="uncertain", live_members=None, reason="synthetic unknown descendant state")
        emit("cleanup_finished", cleanup)
        if artifact and not interrupted and case not in ("artifact_missing", "cleanup_uncertain"):
            if case == "artifact_failed":
                emit("artifact_failed")
                artifacts[0]["status"] = "failed"
                artifacts[0]["failure"] = {field: COORDINATOR["artifact_failed"][field] for field in ("code", "message")}
            else:
                committed = deepcopy(COORDINATOR["artifact_committed"])
                committed["complete"] = case != "artifact_partial"
                emit("artifact_committed", committed)
                artifacts[0].update(status="committed", sha256=DIGEST, bytes=123, complete=committed["complete"], verified=True)
        generation = deepcopy(COORDINATOR["generation_checked"])
        if case == "generation_stale":
            generation["status"] = "superseded"
        elif case == "generation_live":
            generation["assurance"] = "live_tree"
        elif case == "generation_uncertain":
            generation["status"] = "uncertain"
        elif case == "generation_unverified":
            generation.update(status="unverified", assurance="unverified", identity_sha256=None, declared_inputs_complete=False)
        emit("generation_checked", generation)
        accounting_verified = not missing_terminal
        reporting_complete = not missing_terminal and case != "reporting_incomplete"
        work_complete = case not in ("collection_failure", "collection_failure_partial", "collection_interrupted", "fail_fast", "timeout", "interrupted", "timeout_zero_exit", "interrupted_zero_exit", "backend_interrupted", "crash", "missing_terminal")
        artifacts_verified = not artifact or artifacts[0]["status"] == "committed" and artifacts[0]["complete"]
        infrastructure = "failed" if (case in ("cleanup_uncertain", "missing_terminal", "reporting_incomplete", "environment_unverified")
                                       or artifact and case in ("artifact_missing", "artifact_failed", "artifact_partial", "backend_interrupted")) else "ok"
        if infrastructure == "failed":
            outcome, cli_exit = "infrastructure_error", 3
        elif case in ("generation_stale", "generation_live", "generation_uncertain", "generation_unverified"):
            outcome, cli_exit = "generation_invalid", 3
        elif stop_cause != "none":
            outcome, cli_exit = stop_cause, 2 if stop_cause == "interrupted" else 3
        elif case in ("crash", "undocumented_exit"):
            outcome, cli_exit = "backend_terminated", 137 if case == "crash" else 3
        else:
            outcome, cli_exit = "backend_completed", raw_code
    current_full_success = (outcome == "backend_completed" and cli_exit == 0 and scope == "full"
                            and mode == "run" and counts["selected_count"] > 0)
    result = {
        "protocol_version": 0, "contract_revision": 1, "request_id": "request", "run_id": "run", "generation_id": "gen", "session_id": "session",
        "mode": mode, "scope": scope, "outcome": outcome, "cli_exit_code": cli_exit, "backend_exit_code": raw_code, "backend_signal": raw_signal,
        "stop_cause": stop_cause, "interruption_signal": interruption_signal, "collection_status": collection_status,
        "inventory_complete": inventory_complete, "accounting": counts, "phase_counts": phases, "incomplete_ordinals": incomplete,
        "collection_error_ids": collection_error_ids, "errors": errors, "required_artifact_ids": request["required_artifact_ids"],
        "artifacts": artifacts, "capability_decisions": capabilities, "accounting_verified": accounting_verified,
        "work_complete": work_complete, "reporting_complete": reporting_complete, "artifacts_verified": artifacts_verified,
        "environment_verified": environment_verified, "infrastructure_status": infrastructure, "cleanup": cleanup, "generation": generation,
        "terminal_sequences": {role: value - 1 if value else None for role, value in sequence.items()}, "current_full_success": current_full_success,
    }
    return events, result
