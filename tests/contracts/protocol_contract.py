"""Test-only WP00 ledger checker. NOT a production protocol or WP03 oracle.

Checks assertions in synthetic decoded traces; it cannot authenticate producers,
inspect artifact bytes, or verify the environment/source generation those traces
claim. It deliberately never returns qualification or benchmark eligibility.
"""

import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource


DOCS = Path(__file__).resolve().parents[2] / "docs"
EVENT_SCHEMA = json.loads((DOCS / "protocol-v0.schema.json").read_text())
RESULT_SCHEMA = json.loads((DOCS / "final-result-v0.schema.json").read_text())
REGISTRY = Registry().with_resources([
    (schema["$id"], Resource.from_contents(schema)) for schema in (EVENT_SCHEMA, RESULT_SCHEMA)
])
EVENT_VALIDATOR = jsonschema.Draft202012Validator(EVENT_SCHEMA, registry=REGISTRY)
RESULT_VALIDATOR = jsonschema.Draft202012Validator(RESULT_SCHEMA, registry=REGISTRY)
MAX_EVENTS = 1000000
MAX_EVENT_BYTES = 1024 * 1024
MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_ITEMS = 100000
MAX_NODEID_BYTES = 16 * 1024 * 1024
PHASES = ("setup", "call", "teardown")
OUTCOMES = ("passed", "failed", "skipped")


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def check_shape(value, validator):
    pending = [value]
    while pending:
        item = pending.pop()
        require(not isinstance(item, float), "non_integer_json_number")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    error = next(validator.iter_errors(value), None)
    if error:
        location = ".".join(map(str, error.absolute_path))
        raise ContractError(f"schema:{location}")


class Ledger:
    def __init__(self):
        self.identities = None
        self.producers = {}
        self.sequences = {"coordinator": -1, "bridge": -1}
        self.request = self.environment = self.collection = self.terminal = self.worker = None
        self.rejection = None
        self.cleanup = {"status": "not_started", "leader_reaped": False, "live_members": None, "reason": None}
        self.generation = {"status": "unverified", "assurance": "unverified", "identity_sha256": None,
                           "declared_inputs_complete": False}
        self.started = self.collecting = self.inventory_closed = self.generation_seen = self.cleanup_seen = False
        self.items, self.reports, self.collection_errors = {}, {}, {}
        self.selected, self.deselected = [], []
        self.chunks = {"items_selected": 0, "items_deselected": 0}
        self.attempts, self.last_attempt, self.not_run = {}, {}, {}
        self.active = None
        self.phase_counts = {phase: dict.fromkeys(OUTCOMES, 0) for phase in PHASES}
        self.artifacts, self.ready, self.capabilities, self.errors = {}, {}, [], []
        self.artifact_kinds = {}
        self.stop_cause, self.interruption_signal = "none", None
        self.nodeid_bytes = self.trace_bytes = self.event_count = 0
        self.resources = {}

    def counts(self):
        return {
            "collected_count": len(self.items), "selected_count": len(self.selected), "deselected_count": len(self.deselected),
            "executed_count": len(self.last_attempt),
            "completed_count": sum(self.attempts[(ordinal, attempt)]["disposition"] == "completed"
                                   for ordinal, attempt in self.last_attempt.items()),
            "not_run_count": len(self.not_run), "attempts_started": len(self.attempts),
            "attempts_completed": sum(item["disposition"] in ("completed", "retry") for item in self.attempts.values()),
        }

    def incomplete(self):
        return [ordinal for ordinal in self.selected if ordinal not in self.not_run
                and (ordinal not in self.last_attempt or
                     self.attempts[(ordinal, self.last_attempt[ordinal])]["disposition"] != "completed")]

    def apply(self, message):
        check_shape(message, EVENT_VALIDATOR)
        size = len(json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        self.trace_bytes += size
        self.event_count += 1
        require(size <= MAX_EVENT_BYTES and self.trace_bytes <= MAX_TRACE_BYTES
                and self.event_count <= MAX_EVENTS, "trace_limit_exceeded")
        role, producer, sequence, kind, payload = (message[key] for key in
                                                  ("producer_role", "producer_id", "sequence", "kind", "payload"))
        identity = {key: message[key] for key in ("request_id", "run_id", "generation_id", "session_id")}
        if self.identities is None:
            require(kind == "request_accepted", "request_must_be_first")
            self.identities = identity
        require(identity == self.identities, "identity_mismatch")
        if role not in self.producers:
            require(producer not in self.producers.values(), "producer_role_collision")
            self.producers[role] = producer
        require(self.producers[role] == producer, "producer_changed")
        require(sequence == self.sequences[role] + 1, "sequence_gap_or_duplicate")
        self.sequences[role] = sequence
        if role == "bridge":
            require(self.rejection is None, "project_execution_after_request_rejection")
            require(self.terminal is None, "event_after_bridge_terminal")
            require(self.started or kind == "session_started", "handshake_required")
        require(self.request is not None or kind == "request_accepted", "missing_request")
        self.dispatch(kind, payload)

    def dispatch(self, kind, p):
        if kind == "request_accepted":
            require(self.request is None, "duplicate_request")
            self.request = p
        elif kind == "request_rejected":
            require(self.rejection is None and not self.started and self.worker is None, "late_or_duplicate_request_rejection")
            self.rejection = p
            category = {"configuration_error": "configuration", "unsupported_profile": "unsupported", "launch_error": "infrastructure"}[p["outcome"]]
            self.errors.append({"producer_role": "coordinator", "category": category, "code": p["code"], "message": p["message"]})
        elif kind == "environment_resolved":
            require(self.environment is None and not self.started, "environment_resolution_order")
            require(p["invocation_profile"] == self.request["invocation_profile"], "invocation_profile_mismatch")
            self.environment = p
        elif kind == "session_started":
            require(not self.started and self.environment is not None, "handshake_order")
            require(p["invocation_profile"] == self.request["invocation_profile"], "invocation_profile_mismatch")
            self.started = True
        elif kind == "collection_started":
            require(not self.collecting and self.collection is None, "duplicate_collection_session")
            self.collecting = True
        elif kind in ("collection_report", "collection_error", "item_collected", "items_selected", "items_deselected"):
            require(self.collecting and self.collection is None, "collection_barrier")
            self.collect(kind, p)
        elif kind == "collection_finished":
            require(self.collecting and self.collection is None, "collection_barrier")
            require(len(self.selected) + len(self.deselected) == len(self.items), "selection_partition")
            for field in ("collected_count", "selected_count", "deselected_count"):
                require(p[field] == self.counts()[field], "collection_count_mismatch")
            failed = {key for key, value in self.reports.items() if value["outcome"] == "failed"}
            require(failed == self.collection_errors.keys(), "collection_error_accounting")
            require(not failed or p["status"] != "complete", "hidden_collection_failure")
            self.collection = p
        elif kind == "capability_decision":
            require(not self.attempts, "capability_decision_after_effects")
            require(not any(x["capability"] == p["capability"] for x in self.capabilities), "duplicate_capability")
            self.capabilities.append(p)
        elif kind in ("item_started", "phase_report", "attempt_finished", "item_not_run"):
            require(self.collection is not None, "execution_before_collection_barrier")
            self.execution(kind, p)
        elif kind in ("artifact_declared", "artifact_ready", "artifact_committed", "artifact_failed"):
            self.artifact(kind, p)
        elif kind == "warning":
            require(p["ordinal"] is None or p["ordinal"] in self.items, "unknown_warning_occurrence")
        elif kind == "output_reference":
            require(p["artifact_id"] in self.artifacts, "unknown_artifact_reference")
            require(self.artifact_kinds[p["artifact_id"]] == p["stream"], "output_artifact_kind_mismatch")
            if p["ordinal"] is not None:
                require((p["ordinal"], p["attempt"]) in self.attempts, "unknown_output_attempt")
        elif kind == "session_error":
            self.errors.append({"producer_role": "bridge", **p})
        elif kind == "infrastructure_error":
            self.errors.append({"producer_role": "coordinator", "category": "infrastructure", **p})
        elif kind in ("cancellation_requested", "deadline_exceeded"):
            if self.stop_cause == "none":
                self.stop_cause = "interrupted" if kind == "cancellation_requested" else "timeout"
                self.interruption_signal = p.get("signal")
        elif kind == "resource_event":
            require(p["state"] in ("requested", "denied"), "resource_execution_unsupported")
            previous = self.resources.get(p["resource_id"])
            require((previous is None and p["state"] == "requested") or
                    (previous == "requested" and p["state"] == "denied"), "resource_transition")
            self.resources[p["resource_id"]] = p["state"]
        elif kind == "extension_event":
            raise ContractError("extension_adapter_unsupported")
        elif kind == "session_terminated":
            require(p["accounting"] == self.counts(), "terminal_count_mismatch")
            require(p["phase_counts"] == self.phase_counts, "terminal_phase_count_mismatch")
            require(p["incomplete_ordinals"] == self.incomplete(), "terminal_incomplete_mismatch")
            self.terminal = p
        elif kind == "worker_exited":
            require(self.rejection is None, "worker_after_request_rejection")
            require(self.worker is None, "duplicate_worker_exit")
            self.worker = p
        elif kind == "cleanup_finished":
            require(not self.cleanup_seen, "duplicate_cleanup")
            if p["status"] == "complete":
                require(self.worker is not None and self.worker["reaped"], "cleanup_before_reap")
            self.cleanup_seen, self.cleanup = True, p
        elif kind == "generation_checked":
            require(not self.generation_seen, "duplicate_generation_check")
            require(self.worker is not None and self.cleanup_seen, "generation_check_before_cleanup")
            self.generation_seen, self.generation = True, p
        else:
            raise ContractError("unhandled_catalog_kind")

    def collect(self, kind, p):
        if kind == "collection_report":
            require(p["report_id"] not in self.reports, "duplicate_collection_report")
            self.reports[p["report_id"]] = p
        elif kind == "collection_error":
            report = self.reports.get(p["report_id"])
            require(report is not None and report["outcome"] == "failed"
                    and report["nodeid"] == p["nodeid"], "unmatched_collection_error")
            require(p["report_id"] not in self.collection_errors, "duplicate_collection_error")
            self.collection_errors[p["report_id"]] = p
        elif kind == "item_collected":
            require(not self.inventory_closed, "inventory_after_selection")
            require(p["ordinal"] == len(self.items), "occurrence_ordinal_gap_or_duplicate")
            self.nodeid_bytes += len(p["nodeid"].encode("utf-8", errors="surrogatepass"))
            require(len(self.items) < MAX_ITEMS and self.nodeid_bytes <= MAX_NODEID_BYTES, "inventory_limit_exceeded")
            self.items[p["ordinal"]] = p["nodeid"]
        else:
            self.inventory_closed = True
            require(p["chunk"] == self.chunks[kind], "selection_chunk_gap_or_duplicate")
            self.chunks[kind] += 1
            taken = set(self.selected) | set(self.deselected)
            require(all(ordinal in self.items and ordinal not in taken for ordinal in p["ordinals"]),
                    "selection_duplicate_or_unknown")
            (self.selected if kind == "items_selected" else self.deselected).extend(p["ordinals"])

    def execution(self, kind, p):
        ordinal = p["ordinal"]
        require(ordinal in self.selected, "execution_of_unselected_item")
        if kind == "item_not_run":
            require(ordinal not in self.last_attempt and ordinal not in self.not_run and self.active is None,
                    "not_run_after_effects_or_duplicate")
            require((p["reason"] == "collect_only") == (self.request["mode"] == "collect_only"), "not_run_mode_mismatch")
            if p["reason"] == "collection_failed":
                require(self.collection["status"] == "failed", "not_run_collection_context")
            elif p["reason"] == "fail_fast":
                require(any(any(phase["outcome"] == "failed" for phase in self.attempts[(item, attempt)]["phases"])
                            for item, attempt in self.last_attempt.items()), "not_run_fail_fast_context")
            self.not_run[ordinal] = p["reason"]
            return
        require(self.request["mode"] == "run", "execution_during_collect_only")
        key = (ordinal, p["attempt"])
        if kind == "item_started":
            require(self.active is None and ordinal not in self.not_run and key not in self.attempts,
                    "duplicate_or_overlapping_attempt")
            pending_retry = [item for item, attempt in self.last_attempt.items()
                             if self.attempts[(item, attempt)]["disposition"] == "retry"]
            require(not pending_retry or pending_retry == [ordinal], "pending_retry_must_resolve")
            previous = self.last_attempt.get(ordinal)
            if previous is None:
                expected = next((item for item in self.selected if item not in self.last_attempt and item not in self.not_run), None)
                require(ordinal == expected and p["attempt"] == 0, "selected_execution_order")
            else:
                require(self.request["retry_policy"] == "backend_plugin" and p["attempt"] == previous + 1
                        and self.attempts[(ordinal, previous)]["disposition"] == "retry", "unrequested_replay")
            require(p["attempt"] < self.request["max_attempts"], "attempt_limit")
            self.attempts[key] = {"phases": [], "disposition": None}
            self.last_attempt[ordinal], self.active = p["attempt"], key
        else:
            require(self.active == key, "report_without_active_attempt")
            attempt = self.attempts[key]
            phases = attempt["phases"]
            if kind == "phase_report":
                expected = "setup" if not phases else (
                    "call" if len(phases) == 1 and phases[0]["outcome"] == "passed" else "teardown")
                require(p["phase"] == expected and not any(x["phase"] == p["phase"] for x in phases), "phase_order_or_duplicate")
                require(all(artifact in self.artifacts for artifact in p["artifact_ids"]), "unknown_phase_artifact")
                phases.append(p)
                self.phase_counts[p["phase"]][p["outcome"]] += 1
            else:
                if p["disposition"] != "interrupted":
                    required = ["setup", "call", "teardown"] if phases and phases[0]["outcome"] == "passed" else ["setup", "teardown"]
                    require([x["phase"] for x in phases] == required, "incomplete_phase_accounting")
                if p["disposition"] == "retry":
                    require(self.request["retry_policy"] == "backend_plugin" and p["attempt"] + 1 < self.request["max_attempts"]
                            and any(x["outcome"] == "failed" for x in phases), "unrequested_replay")
                attempt["disposition"], self.active = p["disposition"], None

    def artifact(self, kind, p):
        identifier = p["artifact_id"]
        if kind == "artifact_declared":
            require(identifier not in self.artifacts, "duplicate_artifact_declaration")
            require(p["required"] == (identifier in self.request["required_artifact_ids"]), "required_artifact_downgrade")
            self.artifacts[identifier] = {"artifact_id": identifier, "required": p["required"], "status": "pending",
                                          "sha256": None, "bytes": None, "complete": False, "verified": False, "failure": None}
            self.artifact_kinds[identifier] = p["artifact_kind"]
            return
        require(identifier in self.artifacts, "undeclared_artifact")
        target = self.artifacts[identifier]
        require(target["status"] == "pending", "artifact_terminal_mutation")
        if kind == "artifact_ready":
            require(identifier not in self.ready, "duplicate_artifact_ready")
            self.ready[identifier] = p
        elif kind == "artifact_committed":
            require(self.worker is not None and self.worker["reaped"], "artifact_before_writer_reap")
            require(self.cleanup["status"] == "complete", "artifact_before_group_cleanup")
            ready = self.ready.get(identifier)
            require(ready is not None and all(ready[field] == p[field] for field in ("sha256", "bytes", "complete")),
                    "artifact_commit_mismatch")
            target.update(status="committed", **{field: p[field] for field in ("sha256", "bytes", "complete", "verified")})
        else:
            target["status"] = "failed"
            target["failure"] = {field: p[field] for field in ("code", "message")}

    def final_model(self):
        require(self.request is not None, "missing_request")
        if self.terminal and self.worker and self.worker["exit_code"] is not None:
            code = self.terminal["backend_exit_code"]
            require(code is None or code == self.worker["exit_code"], "backend_status_mismatch")
        failed_reports = {key for key, item in self.reports.items() if item["outcome"] == "failed"}
        require(failed_reports == self.collection_errors.keys(), "collection_error_accounting")
        counts, incomplete = self.counts(), self.incomplete()
        inventory_complete = bool(self.collection and self.collection["inventory_complete"])
        accounting_verified = bool(self.terminal and (self.collection or not self.collecting))
        reporting_complete = bool(self.terminal and self.terminal["reporting_complete"])
        work_complete = bool(inventory_complete and self.terminal and not incomplete and
                             (not self.not_run or self.request["mode"] == "collect_only"))
        required = self.request["required_artifact_ids"]
        artifacts_verified = all(identifier in self.artifacts and
                                 self.artifacts[identifier]["status"] == "committed" and
                                 self.artifacts[identifier]["complete"] for identifier in required)
        environment_verified = bool(self.environment and self.environment["verified"])
        independent_errors = [item for item in self.errors if item["category"] in ("infrastructure", "unsupported")]
        artifact_failed = any(item["required"] and item["status"] == "failed" for item in self.artifacts.values())
        raw_code = self.worker["exit_code"] if self.worker else None
        raw_signal = self.worker["signal"] if self.worker else None
        generation_valid = (self.generation["status"] == "current" and
                            self.generation["assurance"] == "immutable_snapshot" and
                            self.generation["declared_inputs_complete"])
        cleanup_bad = self.cleanup["status"] == "uncertain" or bool(self.worker and
                      (not self.worker["reaped"] or self.cleanup["status"] != "complete"))
        contradictory_error = self.stop_cause == "none" and any(item["category"] in ("internal", "usage") and raw_code is not None
                                  and raw_code != {"internal": 3, "usage": 4}[item["category"]]
                                  for item in self.errors)
        terminal_failed = bool(self.terminal and self.terminal["termination"] == "infrastructure_failed")
        terminal_contradiction = bool(self.stop_cause == "none" and self.terminal and self.terminal["termination"] == "interrupted"
                                      and raw_code is not None and raw_code != 2)
        # Documented pytest interruption/internal/usage exits can explain an
        # interrupted attempt. An ordinary assertion failure cannot stand in
        # for a missing or abandoned attempt, even if pass/fail totals agree.
        incomplete_unexplained = bool(self.stop_cause == "none" and raw_code in (0, 1, 5) and incomplete)
        not_run_unexplained = (any(reason == "interrupted" for reason in self.not_run.values())
                               and self.stop_cause == "none" and raw_signal is None and raw_code not in (2, 3, 4))
        resource_unresolved = "requested" in self.resources.values()
        infra = bool(independent_errors or cleanup_bad or artifact_failed or contradictory_error or
                     terminal_failed or terminal_contradiction or incomplete_unexplained or
                     not_run_unexplained or resource_unresolved)
        if self.rejection:
            outcome = self.rejection["outcome"]
            exit_code = 3 if outcome == "launch_error" else 4
            infra = outcome == "launch_error"
        elif infra:
            outcome, exit_code = "infrastructure_error", 3
        elif self.generation_seen and not generation_valid:
            outcome, exit_code = "generation_invalid", 3
        elif self.stop_cause != "none":
            outcome, exit_code = self.stop_cause, 2 if self.stop_cause == "interrupted" else 3
        elif raw_signal is not None:
            outcome, exit_code = "backend_terminated", 128 + raw_signal
        elif raw_code is not None and raw_code > 5:
            outcome, exit_code = "backend_terminated", 3
        elif (self.worker is None or not accounting_verified or not reporting_complete or
              not artifacts_verified or not environment_verified or
               (raw_code == 0 and (not work_complete or failed_reports or
               any(any(p["outcome"] == "failed" for p in self.attempts[(ordinal, attempt)]["phases"])
                   for ordinal, attempt in self.last_attempt.items())))):
            outcome, exit_code, infra = "infrastructure_error", 3, True
        elif not generation_valid:
            outcome, exit_code = "generation_invalid", 3
        else:
            outcome, exit_code = "backend_completed", raw_code
        current_full_success = (outcome == "backend_completed" and exit_code == 0 and self.request["scope"] == "full"
                                and self.request["mode"] == "run" and counts["selected_count"] > 0
                                and work_complete and not self.errors)
        return {
            "protocol_version": 0, "contract_revision": 1, **self.identities,
            "mode": self.request["mode"], "scope": self.request["scope"], "outcome": outcome,
            "cli_exit_code": exit_code, "backend_exit_code": raw_code, "backend_signal": raw_signal,
            "stop_cause": self.stop_cause, "interruption_signal": self.interruption_signal,
            "collection_status": self.collection["status"] if self.collection else "unknown" if self.collecting else "not_started",
            "inventory_complete": inventory_complete, "accounting": counts, "phase_counts": self.phase_counts,
            "incomplete_ordinals": incomplete, "collection_error_ids": list(self.collection_errors), "errors": self.errors,
            "required_artifact_ids": required, "artifacts": list(self.artifacts.values()), "capability_decisions": self.capabilities,
            "accounting_verified": accounting_verified, "work_complete": work_complete, "reporting_complete": reporting_complete,
            "artifacts_verified": artifacts_verified, "environment_verified": environment_verified,
            "infrastructure_status": "failed" if infra else "ok" if self.started else "not_started",
            "cleanup": self.cleanup, "generation": self.generation,
            "terminal_sequences": {role: sequence if sequence >= 0 else None for role, sequence in self.sequences.items()},
            "current_full_success": bool(current_full_success),
        }


def validate_trace(events, result):
    """Verify internal assertions only; never promote a trace to qualification."""
    check_shape(result, RESULT_VALIDATOR)
    ledger = Ledger()
    for message in events:
        ledger.apply(message)
    expected = ledger.final_model()
    check_shape(expected, RESULT_VALIDATOR)
    for field, value in expected.items():
        require(result[field] == value, f"result_mismatch:{field}")
    return {"mode": "synthetic_contract_check", "contract_consistent": True, "qualified": False,
            "events_checked": ledger.event_count, "artifact_bytes_checked": False,
            "generation_evidence_checked": False, "environment_evidence_checked": False}
