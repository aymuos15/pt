"""Synthetic WP00 contract examples, never observed product/benchmark evidence."""

from copy import deepcopy


DIGEST = "a" * 64


def phase_counts():
    return {phase: {outcome: 0 for outcome in ("passed", "failed", "skipped")}
            for phase in ("setup", "call", "teardown")}


def accounting():
    return dict.fromkeys(("collected_count", "selected_count", "deselected_count", "executed_count",
                          "completed_count", "not_run_count", "attempts_started", "attempts_completed"), 0)


COORDINATOR = {
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
