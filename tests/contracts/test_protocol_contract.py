"""Synthetic ledger tests, not product, transport, or WP03 qualification."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import protocol_contract as contract
from protocol_examples import TRACE_CASES, event, trace_fixture


def messages(events, kind):
    return [message for message in events if message["kind"] == kind]


def renumber(events, result):
    """Keep mutation tests about their intended defect, not a sequence gap."""
    sequences = {"coordinator": 0, "bridge": 0}
    for message in events:
        role = message["producer_role"]
        message["sequence"] = sequences[role]
        sequences[role] += 1
    result["terminal_sequences"] = {role: value - 1 if value else None
                                    for role, value in sequences.items()}


def model_for(events):
    ledger = contract.Ledger()
    for message in events:
        ledger.apply(message)
    return ledger.final_model()


class ProtocolContractTests(unittest.TestCase):
    def assert_rejected(self, events, result, code, *, resequence=True):
        if resequence:
            renumber(events, result)
        with self.assertRaisesRegex(contract.ContractError, code):
            contract.validate_trace(events, result)

    def test_hand_constructed_scenarios_are_consistent_not_qualified(self):
        for case in TRACE_CASES:
            for artifact in (False, True):
                with self.subTest(case=case, artifact=artifact):
                    events, result = trace_fixture(case, deselect=True, artifact=artifact)
                    evidence = contract.validate_trace(events, result)
                    self.assertEqual(evidence["events_checked"], len(events))
                    self.assertTrue(evidence["contract_consistent"])
                    for field in ("qualified", "artifact_bytes_checked", "environment_evidence_checked",
                                  "generation_evidence_checked"):
                        self.assertIs(evidence[field], False)

    def test_selected_scope_and_collect_only_never_certify_a_full_run(self):
        for scope, case in (("explicit", "pass"), ("affected", "pass"), ("full", "collect_only")):
            with self.subTest(scope=scope, case=case):
                events, result = trace_fixture(case, scope=scope)
                self.assertEqual(result["cli_exit_code"], 0)
                self.assertIs(result["current_full_success"], False)
                contract.validate_trace(events, result)
                result["current_full_success"] = True
                self.assert_rejected(events, result, "schema:")

    def test_duplicate_unicode_node_ids_remain_distinct_ordered_occurrences(self):
        events, result = trace_fixture(deselect=True)
        items = messages(events, "item_collected")
        self.assertEqual([item["payload"]["ordinal"] for item in items], [0, 1, 2])
        self.assertEqual(len({item["payload"]["nodeid"] for item in items}), 1)
        self.assertIn("λ", items[0]["payload"]["nodeid"])
        self.assertEqual(messages(events, "items_selected")[0]["payload"]["ordinals"], [1, 0])
        self.assertEqual(result["accounting"]["executed_count"], 2)
        contract.validate_trace(events, result)

    def test_chunking_preserves_selected_order_across_messages(self):
        events, result = trace_fixture(deselect=True)
        chosen = messages(events, "items_selected")[0]
        chosen["payload"]["ordinals"] = [1]
        events.insert(events.index(chosen) + 1, event("items_selected", {"chunk": 1, "ordinals": [0]}))
        renumber(events, result)
        contract.validate_trace(events, result)

    def test_partial_or_interrupted_collection_is_never_a_complete_inventory(self):
        for case in ("collection_failure_partial", "collection_interrupted"):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                contract.validate_trace(events, result)
                self.assertEqual(result["backend_exit_code"], 2)
                self.assertEqual(result["accounting"]["collected_count"], 2)
                self.assertEqual(result["accounting"]["not_run_count"], 2)
                self.assertIs(result["inventory_complete"], False)
                self.assertIs(result["work_complete"], False)

    def test_xfail_xpass_and_teardown_failure_keep_raw_phase_semantics(self):
        for case, expected in (("xfail", "skipped"), ("xpass", "passed"), ("strict_xpass", "failed")):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                contract.validate_trace(events, result)
                call = next(m["payload"] for m in messages(events, "phase_report")
                            if m["payload"]["phase"] == "call" and m["payload"]["ordinal"] == 1)
                self.assertEqual(call["outcome"], expected)
                self.assertEqual(call["strict_xpass"], case == "strict_xpass")
                if case != "strict_xpass":
                    self.assertEqual(call["was_xfail"], "synthetic expected failure")
        events, result = trace_fixture("teardown_failure")
        self.assertEqual(result["phase_counts"]["call"]["failed"], 0)
        self.assertEqual(result["phase_counts"]["teardown"]["failed"], 1)
        self.assertEqual(result["cli_exit_code"], 1)
        contract.validate_trace(events, result)

    def test_identity_and_producer_changes_are_rejected(self):
        for field, value, code in (
            ("request_id", "other", "identity_mismatch"), ("run_id", "other", "identity_mismatch"),
            ("generation_id", "other", "identity_mismatch"), ("session_id", "other", "identity_mismatch"),
            ("producer_id", "other", "producer_changed"),
        ):
            with self.subTest(field=field):
                events, result = trace_fixture()
                messages(events, "phase_report")[0][field] = value
                self.assert_rejected(events, result, code)

    def test_sequences_detect_loss_duplicate_and_conflicting_redelivery(self):
        for mutation in ("lost", "duplicate", "conflict", "first_nonzero"):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture()
                target = messages(events, "phase_report")[0]
                index = events.index(target)
                if mutation == "lost":
                    events.pop(index)
                elif mutation == "first_nonzero":
                    messages(events, "session_started")[0]["sequence"] = 1
                else:
                    duplicate = deepcopy(target)
                    if mutation == "conflict":
                        duplicate["payload"]["outcome"] = "failed"
                    events.insert(index + 1, duplicate)
                self.assert_rejected(events, result, "sequence_gap_or_duplicate", resequence=False)

    def test_lost_and_duplicate_occurrences_are_not_deduplicated_by_nodeid(self):
        for mutation in ("lost", "duplicate", "late_inventory"):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture(deselect=True)
                item = messages(events, "item_collected")[1]
                if mutation == "lost":
                    events.remove(item)
                    code = "occurrence_ordinal_gap_or_duplicate"
                elif mutation == "duplicate":
                    events.insert(events.index(item), deepcopy(item))
                    code = "occurrence_ordinal_gap_or_duplicate"
                else:
                    late = messages(events, "item_collected")[2]
                    events.remove(late)
                    events.insert(events.index(messages(events, "items_selected")[0]) + 1, late)
                    code = "inventory_after_selection"
                self.assert_rejected(events, result, code)

    def test_selection_is_a_disjoint_exhaustive_partition(self):
        for mutation in ("overlap", "unknown", "omission", "repeat_chunk", "bad_chunk"):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture(deselect=True)
                chosen = messages(events, "items_selected")[0]
                excluded = messages(events, "items_deselected")[0]
                code = "selection_duplicate_or_unknown"
                if mutation == "overlap":
                    excluded["payload"]["ordinals"] = [0]
                elif mutation == "unknown":
                    chosen["payload"]["ordinals"] = [9, 0]
                elif mutation == "omission":
                    chosen["payload"]["ordinals"] = [1]
                    code = "selection_partition"
                elif mutation == "repeat_chunk":
                    duplicate = deepcopy(chosen)
                    duplicate["payload"].update(chunk=1, ordinals=[0])
                    events.insert(events.index(excluded), duplicate)
                else:
                    chosen["payload"]["chunk"] = 1
                    code = "selection_chunk_gap_or_duplicate"
                self.assert_rejected(events, result, code)

    def test_collection_and_terminal_totals_are_checked_separately(self):
        for kind, field, code in (
            ("collection_finished", "selected_count", "collection_count_mismatch"),
            ("session_terminated", "executed_count", "terminal_count_mismatch"),
            ("session_terminated", "attempts_completed", "terminal_count_mismatch"),
        ):
            with self.subTest(kind=kind, field=field):
                events, result = trace_fixture()
                payload = messages(events, kind)[0]["payload"]
                target = payload if kind == "collection_finished" else payload["accounting"]
                target[field] += 1
                self.assert_rejected(events, result, code)

    def test_failed_collectors_cannot_be_hidden_or_detached_from_error_reports(self):
        for mutation in ("missing_error", "false_complete", "unknown_report", "duplicate_error"):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture("collection_failure")
                error = messages(events, "collection_error")[0]
                if mutation == "missing_error":
                    events.remove(error)
                    code = "collection_error_accounting"
                elif mutation == "false_complete":
                    messages(events, "collection_finished")[0]["payload"].update(status="complete", inventory_complete=True)
                    code = "hidden_collection_failure"
                elif mutation == "unknown_report":
                    error["payload"]["report_id"] = 999
                    code = "unmatched_collection_error"
                else:
                    events.insert(events.index(error), deepcopy(error))
                    code = "duplicate_collection_error"
                self.assert_rejected(events, result, code)

    def test_execution_follows_authoritative_selection_not_collection_order(self):
        events, result = trace_fixture(deselect=True)
        messages(events, "item_started")[0]["payload"]["ordinal"] = 0
        self.assert_rejected(events, result, "selected_execution_order")
        events, result = trace_fixture(deselect=True)
        messages(events, "item_started")[0]["payload"]["ordinal"] = 2
        self.assert_rejected(events, result, "execution_of_unselected_item")
        events, result = trace_fixture()
        boundary = messages(events, "collection_finished")[0]
        events.remove(boundary)
        self.assert_rejected(events, result, "execution_before_collection_barrier")

    def test_missing_duplicate_and_out_of_order_phases_are_rejected(self):
        for phase in ("setup", "call", "teardown"):
            for mutation in ("lost", "duplicate"):
                with self.subTest(phase=phase, mutation=mutation):
                    events, result = trace_fixture()
                    target = next(m for m in messages(events, "phase_report") if m["payload"]["phase"] == phase)
                    if mutation == "lost":
                        events.remove(target)
                    else:
                        events.insert(events.index(target), deepcopy(target))
                    self.assert_rejected(events, result, "phase_order_or_duplicate|incomplete_phase_accounting")

    def test_setup_skip_or_failure_omits_call_but_never_hides_teardown(self):
        for case in ("setup_skip", "setup_failure"):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                first = [m for m in messages(events, "phase_report") if m["payload"]["ordinal"] == 1]
                self.assertEqual([m["payload"]["phase"] for m in first], ["setup", "teardown"])
                contract.validate_trace(events, result)
                events.remove(first[-1])
                self.assert_rejected(events, result, "incomplete_phase_accounting")

    def test_reports_without_an_active_attempt_and_overlapping_attempts_fail(self):
        for mutation in ("no_start", "overlap", "wrong_attempt"):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture()
                start = messages(events, "item_started")[0]
                if mutation == "no_start":
                    events.remove(start)
                    code = "report_without_active_attempt"
                elif mutation == "overlap":
                    events.insert(events.index(start) + 1, deepcopy(start))
                    code = "duplicate_or_overlapping_attempt"
                else:
                    messages(events, "phase_report")[0]["payload"]["attempt"] = 1
                    code = "report_without_active_attempt"
                self.assert_rejected(events, result, code)

    def test_retry_requires_explicit_backend_policy_and_preserves_failed_attempt(self):
        events, result = trace_fixture("retry")
        contract.validate_trace(events, result)
        self.assertEqual(result["accounting"]["executed_count"], 2)
        self.assertEqual(result["accounting"]["attempts_started"], 3)
        self.assertEqual(result["phase_counts"]["call"]["failed"], 1)
        messages(events, "request_accepted")[0]["payload"].update(retry_policy="disabled", retry_plugin=None, max_attempts=1)
        self.assert_rejected(events, result, "unrequested_replay")
        events, result = trace_fixture("retry")
        messages(events, "attempt_finished")[0]["payload"]["disposition"] = "completed"
        self.assert_rejected(events, result, "unrequested_replay")

    def test_retry_ordinal_cannot_jump_and_successful_attempt_cannot_request_retry(self):
        events, result = trace_fixture("retry")
        messages(events, "item_started")[1]["payload"]["attempt"] = 2
        self.assert_rejected(events, result, "unrequested_replay")
        events, result = trace_fixture("retry")
        first_failure = next(m for m in messages(events, "phase_report") if m["payload"]["outcome"] == "failed")
        first_failure["payload"]["outcome"] = "passed"
        self.assert_rejected(events, result, "unrequested_replay")

    def test_started_work_cannot_be_relabelled_not_run(self):
        events, result = trace_fixture()
        target = messages(events, "attempt_finished")[0]
        events.insert(events.index(target) + 1, event("item_not_run", {"ordinal": 1, "reason": "fail_fast"}))
        self.assert_rejected(events, result, "not_run_after_effects_or_duplicate")

    def test_fail_fast_is_incomplete_work_not_a_missing_occurrence(self):
        events, result = trace_fixture("fail_fast")
        contract.validate_trace(events, result)
        self.assertEqual(result["accounting"]["not_run_count"], 1)
        self.assertEqual(result["incomplete_ordinals"], [])
        self.assertIs(result["work_complete"], False)
        events.remove(messages(events, "item_not_run")[0])
        self.assert_rejected(events, result, "terminal_count_mismatch")

    def test_phase_counts_and_incomplete_inventory_are_not_inferred_from_exit(self):
        events, result = trace_fixture()
        messages(events, "session_terminated")[0]["payload"]["phase_counts"]["call"]["passed"] -= 1
        self.assert_rejected(events, result, "terminal_phase_count_mismatch")
        events, result = trace_fixture()
        messages(events, "session_terminated")[0]["payload"]["incomplete_ordinals"] = [0]
        self.assert_rejected(events, result, "terminal_incomplete_mismatch")

    def test_artifacts_require_declaration_writer_reap_and_group_cleanup(self):
        for mutation, code in (("undeclared", "undeclared_artifact"), ("writer", "artifact_before_writer_reap"),
                               ("cleanup", "artifact_before_group_cleanup"), ("downgrade", "required_artifact_downgrade")):
            with self.subTest(mutation=mutation):
                events, result = trace_fixture()
                if mutation == "undeclared":
                    events.remove(messages(events, "artifact_declared")[0])
                elif mutation == "downgrade":
                    messages(events, "artifact_declared")[0]["payload"]["required"] = False
                else:
                    commit = messages(events, "artifact_committed")[0]
                    events.remove(commit)
                    before = "worker_exited" if mutation == "writer" else "cleanup_finished"
                    events.insert(events.index(messages(events, before)[0]), commit)
                self.assert_rejected(events, result, code)

    def test_artifact_commit_must_match_ready_identity_bytes_and_completeness(self):
        for field, value in (("sha256", "b" * 64), ("bytes", 124), ("complete", False)):
            with self.subTest(field=field):
                events, result = trace_fixture()
                messages(events, "artifact_committed")[0]["payload"][field] = value
                self.assert_rejected(events, result, "artifact_commit_mismatch")
        events, result = trace_fixture()
        events.remove(messages(events, "artifact_ready")[0])
        self.assert_rejected(events, result, "artifact_commit_mismatch")

    def test_optional_artifact_failure_is_visible_without_changing_required_success(self):
        events, result = trace_fixture(artifact=False)
        declaration = event("artifact_declared")
        declaration["payload"]["required"] = False
        events.insert(events.index(messages(events, "session_started")[0]), declaration)
        failure = event("artifact_failed")
        events.append(failure)
        result["artifacts"] = [{"artifact_id": "coverage", "required": False, "status": "failed",
                                "sha256": None, "bytes": None, "complete": False, "verified": False,
                                "failure": {key: failure["payload"][key] for key in ("code", "message")}}]
        renumber(events, result)
        contract.validate_trace(events, result)
        self.assertIs(result["current_full_success"], True)
        self.assertEqual(result["artifacts"][0]["failure"]["code"], "write_failed")

    def test_committed_artifacts_and_bridge_terminal_are_immutable(self):
        events, result = trace_fixture()
        commit = messages(events, "artifact_committed")[0]
        events.insert(events.index(commit) + 1, deepcopy(commit))
        self.assert_rejected(events, result, "artifact_terminal_mutation")
        events, result = trace_fixture()
        terminal = messages(events, "session_terminated")[0]
        events.insert(events.index(terminal) + 1, deepcopy(terminal))
        self.assert_rejected(events, result, "event_after_bridge_terminal")

    def test_worker_exit_must_match_bridge_exit_and_cleanup_reap(self):
        events, result = trace_fixture()
        messages(events, "worker_exited")[0]["payload"]["exit_code"] = 1
        self.assert_rejected(events, result, "backend_status_mismatch")
        events, result = trace_fixture()
        messages(events, "worker_exited")[0]["payload"]["reaped"] = False
        self.assert_rejected(events, result, "cleanup_before_reap")

    def test_timeout_and_cancellation_do_not_turn_later_zero_into_success(self):
        for case, code in (("timeout_after_zero", 3), ("interrupted_after_zero", 2)):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                contract.validate_trace(events, result)
                self.assertEqual(result["backend_exit_code"], 0)
                self.assertEqual(result["cli_exit_code"], code)
                result.update(outcome="backend_completed", cli_exit_code=0, current_full_success=True)
                self.assert_rejected(events, result, "schema:|result_mismatch:")

    def test_first_stop_cause_wins_and_secondary_requests_remain_in_the_trace(self):
        for case, secondary in (("timeout_after_zero", "cancellation_requested"),
                                ("interrupted_after_zero", "deadline_exceeded")):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                events.insert(events.index(messages(events, "worker_exited")[0]), event(secondary))
                renumber(events, result)
                contract.validate_trace(events, result)
                self.assertEqual(len(messages(events, "cancellation_requested")), 1)
                self.assertEqual(len(messages(events, "deadline_exceeded")), 1)

    def test_cleanup_and_protocol_failures_override_stop_but_preserve_raw_causes(self):
        for case, inject in (("timeout_after_zero", "protocol"), ("teardown_failure", "cleanup")):
            with self.subTest(case=case):
                events, result = trace_fixture(case, artifact=False)
                result.update(outcome="infrastructure_error", cli_exit_code=3, infrastructure_status="failed", current_full_success=False)
                if inject == "protocol":
                    error = event("infrastructure_error")
                    events.append(error)
                    result["errors"].append({"producer_role": "coordinator", "category": "infrastructure", **error["payload"]})
                    self.assertEqual(result["stop_cause"], "timeout")
                else:
                    status = {"status": "uncertain", "leader_reaped": True, "live_members": None, "reason": "synthetic cleanup fault"}
                    messages(events, "cleanup_finished")[0]["payload"] = deepcopy(status)
                    result["cleanup"] = status
                    self.assertEqual(result["backend_exit_code"], 1)
                    self.assertEqual(result["phase_counts"]["teardown"]["failed"], 1)
                renumber(events, result)
                contract.validate_trace(events, result)

    def test_invalid_generation_overrides_timeout_without_erasing_it(self):
        events, result = trace_fixture("timeout_after_zero")
        messages(events, "generation_checked")[0]["payload"]["status"] = "superseded"
        result["generation"]["status"] = "superseded"
        result.update(outcome="generation_invalid", cli_exit_code=3)
        contract.validate_trace(events, result)
        self.assertEqual(result["stop_cause"], "timeout")
        self.assertEqual(result["backend_exit_code"], 0)

    def test_known_death_explains_missing_terminal_without_inventing_a_new_error(self):
        for case, outcome in (("timeout", "timeout"), ("interrupted", "interrupted"), ("crash", "backend_terminated")):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                contract.validate_trace(events, result)
                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(result["incomplete_ordinals"], [1, 0])
                self.assertEqual(result["backend_signal"], 9)
                self.assertIs(result["reporting_complete"], False)
                self.assertEqual(result["infrastructure_status"], "ok")
        events, result = trace_fixture("missing_terminal")
        self.assertEqual(result["outcome"], "infrastructure_error")
        contract.validate_trace(events, result)

    def test_known_stop_explains_a_partial_trace_even_if_the_child_exits_zero(self):
        for case, code in (("timeout_zero_exit", 3), ("interrupted_zero_exit", 2)):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                contract.validate_trace(events, result)
                self.assertEqual(result["backend_exit_code"], 0)
                self.assertEqual(result["cli_exit_code"], code)
                self.assertEqual(result["infrastructure_status"], "ok")
                self.assertEqual(result["incomplete_ordinals"], [1, 0])
                self.assertIs(result["work_complete"], False)
                self.assertIs(result["reporting_complete"], False)
                self.assertIs(result["current_full_success"], False)

    def test_generation_environment_and_terminal_claims_must_match_the_trace(self):
        for case, field, value in (("generation_stale", "generation", {"status": "current"}),
                                   ("environment_unverified", "environment_verified", True),
                                   ("missing_terminal", "reporting_complete", True)):
            with self.subTest(case=case):
                events, result = trace_fixture(case)
                if isinstance(value, dict):
                    result[field].update(value)
                else:
                    result[field] = value
                self.assert_rejected(events, result, f"result_mismatch:{field}")

    def test_final_result_cannot_rewrite_counts_errors_artifacts_or_last_sequences(self):
        for case, field in (("pass", "accounting"), ("pass", "phase_counts"),
                            ("collection_failure", "collection_error_ids"), ("pass", "artifacts"),
                            ("pass", "terminal_sequences")):
            with self.subTest(field=field):
                events, result = trace_fixture(case)
                if field == "accounting":
                    result[field]["executed_count"] += 1
                elif field == "phase_counts":
                    result[field]["setup"]["passed"] += 1
                elif field == "terminal_sequences":
                    result[field]["bridge"] -= 1
                else:
                    result[field] = []
                self.assert_rejected(events, result, f"result_mismatch:{field}", resequence=False)

    def test_prelaunch_rejection_never_allows_bridge_execution(self):
        events, result = trace_fixture("unsupported_profile")
        events.append(event("session_started"))
        self.assert_rejected(events, result, "project_execution_after_request_rejection")

    def test_prelaunch_rejection_cannot_hide_a_real_worker_exit(self):
        events, result = trace_fixture("unsupported_profile")
        events.append(event("worker_exited"))
        self.assert_rejected(events, result, "worker_after_request_rejection")

    def test_internal_and_usage_errors_cannot_return_zero_even_with_full_phase_counts(self):
        for category in ("internal", "usage", "infrastructure", "unsupported"):
            with self.subTest(category=category):
                events, result = trace_fixture()
                error = event("session_error")
                error["payload"]["category"] = category
                events.insert(events.index(messages(events, "session_terminated")[0]), error)
                renumber(events, result)
                observed = model_for(events)
                self.assertEqual(observed["outcome"], "infrastructure_error")
                self.assertEqual(observed["cli_exit_code"], 3)
                self.assertIs(observed["current_full_success"], False)

    def test_an_incomplete_attempt_is_not_excused_by_an_ordinary_test_failure_exit(self):
        events, result = trace_fixture("setup_failure")
        finish = messages(events, "attempt_finished")[0]
        finish["payload"]["disposition"] = "interrupted"
        terminal = messages(events, "session_terminated")[0]["payload"]
        terminal["accounting"].update(completed_count=1, attempts_completed=1)
        terminal["incomplete_ordinals"] = [1]
        renumber(events, result)
        observed = model_for(events)
        self.assertEqual(observed["outcome"], "infrastructure_error")
        self.assertEqual(observed["backend_exit_code"], 1)

    def test_a_pending_retry_cannot_be_abandoned_to_start_another_occurrence(self):
        events, result = trace_fixture("retry")
        second_start = messages(events, "item_started")[1]
        second_start["payload"].update(ordinal=0, attempt=0)
        self.assert_rejected(events, result, "pending_retry_must_resolve")

    def test_not_run_reasons_need_matching_context(self):
        events, result = trace_fixture("fail_fast")
        messages(events, "item_not_run")[0]["payload"]["reason"] = "collection_failed"
        self.assert_rejected(events, result, "not_run_collection_context")
        events, result = trace_fixture("fail_fast")
        failure = next(m for m in messages(events, "phase_report") if m["payload"]["outcome"] == "failed")
        failure["payload"]["outcome"] = "passed"
        self.assert_rejected(events, result, "not_run_fail_fast_context")

    def test_terminal_causes_and_zero_exit_must_not_contradict_each_other(self):
        events, result = trace_fixture()
        messages(events, "session_terminated")[0]["payload"]["termination"] = "interrupted"
        renumber(events, result)
        self.assertEqual(model_for(events)["cli_exit_code"], 3)

    def test_generation_observation_follows_worker_and_cleanup_not_early_preflight(self):
        events, result = trace_fixture()
        generation = messages(events, "generation_checked")[0]
        events.remove(generation)
        events.insert(events.index(messages(events, "session_started")[0]), generation)
        self.assert_rejected(events, result, "generation_check_before_cleanup")

    def test_cross_producer_interleaving_preserves_each_producer_not_a_global_clock(self):
        events, result = trace_fixture()
        # waitpid can be observed while the bridge's already-written terminal
        # is still buffered. Reaping is not permission to drop buffered frames.
        terminal = messages(events, "session_terminated")[0]
        events.remove(terminal)
        events.insert(events.index(messages(events, "cleanup_finished")[0]), terminal)
        contract.validate_trace(events, result)
        permission = messages(events, "capability_decision")[0]
        events.remove(permission)
        events.insert(events.index(messages(events, "item_started")[0]), permission)
        contract.validate_trace(events, result)

    def test_unknown_adapters_and_resource_execution_fail_closed(self):
        for kind, code in (("extension_event", "extension_adapter_unsupported"),
                           ("resource_event", "resource_execution_unsupported")):
            with self.subTest(kind=kind):
                events, result = trace_fixture()
                extra = event(kind)
                if kind == "resource_event":
                    extra["payload"]["state"] = "acquired"
                events.insert(events.index(messages(events, "item_started")[0]), extra)
                self.assert_rejected(events, result, code)

    def test_resource_denial_and_output_references_do_not_grant_execution_capabilities(self):
        events, result = trace_fixture(artifact=False)
        declaration = event("artifact_declared", {"artifact_id": "stdout", "artifact_kind": "stdout", "required": False})
        requested = event("resource_event")
        requested["payload"]["state"] = "requested"
        denied = event("resource_event")
        at = events.index(messages(events, "session_started")[0])
        events[at:at] = [declaration, requested, denied]
        at = events.index(messages(events, "phase_report")[0])
        reference = event("output_reference")
        reference["payload"]["ordinal"] = 1
        events.insert(at, reference)
        result["artifacts"] = [{"artifact_id": "stdout", "required": False, "status": "pending",
                                "sha256": None, "bytes": None, "complete": False, "verified": False, "failure": None}]
        renumber(events, result)
        contract.validate_trace(events, result)
        reference["payload"]["stream"] = "stderr"
        self.assert_rejected(events, result, "output_artifact_kind_mismatch")

    def test_bounded_synthetic_ledger_and_noninteger_numbers_are_rejected(self):
        for constant, value, code in (("MAX_EVENTS", 2, "trace_limit_exceeded"),
                                      ("MAX_TRACE_BYTES", 2, "trace_limit_exceeded"),
                                      ("MAX_ITEMS", 1, "inventory_limit_exceeded"),
                                      ("MAX_NODEID_BYTES", 1, "inventory_limit_exceeded")):
            with self.subTest(constant=constant), patch.object(contract, constant, value):
                events, result = trace_fixture()
                self.assert_rejected(events, result, code)
        events, result = trace_fixture()
        permission = messages(events, "capability_decision")[0]
        permission["payload"]["invalidation_conditions"] = ["x" * 65536] * 17
        self.assert_rejected(events, result, "trace_limit_exceeded")
        events, result = trace_fixture()
        messages(events, "phase_report")[0]["payload"]["duration_ns"] = 1.0
        self.assert_rejected(events, result, "non_integer_json_number")


if __name__ == "__main__":
    unittest.main()
