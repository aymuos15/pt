"""Schema-only checks: no real files, processes, or generation evidence."""

from copy import deepcopy
import unittest

import jsonschema

from protocol_contract import EVENT_SCHEMA, RESULT_SCHEMA, RESULT_VALIDATOR
from protocol_examples import trace_fixture


class FinalResultSchemaTests(unittest.TestCase):
    def test_both_schemas_are_well_formed_and_resolve_offline(self):
        for schema in (EVENT_SCHEMA, RESULT_SCHEMA):
            jsonschema.Draft202012Validator.check_schema(schema)
        RESULT_VALIDATOR.validate(trace_fixture()[1])

    def test_every_typed_terminal_outcome_has_an_example(self):
        seen = set()
        for case in ("pass", "configuration_error", "unsupported_profile", "launch_error", "crash",
                     "timeout", "interrupted", "artifact_failed", "generation_stale"):
            result = trace_fixture(case)[1]
            RESULT_VALIDATOR.validate(result)
            seen.add(result["outcome"])
        # Recovery is outside a live session's event stream; no executing-session
        # reattachment or recovery implementation is claimed by this example.
        abandoned = deepcopy(trace_fixture("timeout")[1])
        abandoned.update(outcome="abandoned", cli_exit_code=3)
        RESULT_VALIDATOR.validate(abandoned)
        seen.add("abandoned")
        self.assertEqual(seen, set(RESULT_SCHEMA["properties"]["outcome"]["enum"]))

    def test_false_full_success_is_rejected_for_each_necessary_gate(self):
        changes = (
            ("mode", "collect_only"), ("scope", "affected"), ("outcome", "infrastructure_error"),
            ("cli_exit_code", 1), ("backend_exit_code", 1), ("stop_cause", "timeout"),
            ("collection_status", "failed"), ("inventory_complete", False),
            ("accounting_verified", False), ("work_complete", False), ("reporting_complete", False),
            ("artifacts_verified", False), ("environment_verified", False), ("infrastructure_status", "failed"),
            ("incomplete_ordinals", [0]), ("collection_error_ids", [0]),
        )
        for field, value in changes:
            with self.subTest(field=field):
                result = trace_fixture()[1]
                result[field] = value
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        for field, value in (("selected_count", 0), ("executed_count", 0), ("completed_count", 0), ("not_run_count", 1)):
            with self.subTest(counter=field):
                result = trace_fixture()[1]
                result["accounting"][field] = value
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_stale_uncertain_live_or_unverified_generations_cannot_claim_full_success(self):
        for status, assurance in (("superseded", "immutable_snapshot"), ("uncertain", "immutable_snapshot"),
                                  ("unverified", "unverified"), ("current", "live_tree")):
            with self.subTest(status=status, assurance=assurance):
                result = trace_fixture()[1]
                result["generation"].update(status=status, assurance=assurance)
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture()[1]
        result["generation"]["declared_inputs_complete"] = False
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_pending_failed_partial_or_unverified_required_artifacts_cannot_be_full_success(self):
        for case in ("artifact_missing", "artifact_failed"):
            result = trace_fixture(case)[1]
            result.update(outcome="backend_completed", cli_exit_code=0, artifacts_verified=True, current_full_success=True)
            self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        for field, value in (("complete", False), ("verified", False), ("sha256", None), ("bytes", None)):
            with self.subTest(field=field):
                result = trace_fixture()[1]
                result["artifacts"][0][field] = value
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_missing_fields_are_not_zeros_and_process_only_reports_are_not_test_results(self):
        for field in RESULT_SCHEMA["required"]:
            with self.subTest(field=field):
                result = trace_fixture()[1]
                del result[field]
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        self.assertFalse(RESULT_VALIDATOR.is_valid({"schema_version": 1, "scope": "process_only",
                                                   "termination": {"kind": "process_exited"},
                                                   "leader_status": {"kind": "exited", "code": 0}}))

    def test_backend_completion_has_necessary_gates_even_without_a_full_success_claim(self):
        for field, value in (("cli_exit_code", 7), ("stop_cause", "timeout"),
                             ("accounting_verified", False), ("reporting_complete", False),
                             ("artifacts_verified", False), ("environment_verified", False),
                             ("infrastructure_status", "failed")):
            with self.subTest(field=field):
                result = trace_fixture()[1]
                result.update(scope="explicit", current_full_success=False)
                result[field] = value
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture()[1]
        result.update(scope="explicit", current_full_success=False)
        result["cleanup"].update(status="uncertain", live_members=None)
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_all_documented_pytest_exits_map_to_the_same_cli_code_when_completed(self):
        for code in range(6):
            with self.subTest(code=code):
                result = trace_fixture()[1]
                result.update(backend_exit_code=code, cli_exit_code=code, current_full_success=False)
                RESULT_VALIDATOR.validate(result)
                result["cli_exit_code"] = (code + 1) % 6
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_failure_and_stop_outcomes_require_nonzero_and_matching_causes(self):
        for case in ("timeout", "interrupted", "crash", "configuration_error", "unsupported_profile", "launch_error"):
            with self.subTest(case=case):
                result = trace_fixture(case)[1]
                result["cli_exit_code"] = 0
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        for case in ("timeout", "interrupted"):
            result = trace_fixture(case)[1]
            result.update(stop_cause="none", interruption_signal=None)
            self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_prelaunch_outcomes_cannot_contain_backend_status_or_executed_work(self):
        for case in ("configuration_error", "unsupported_profile", "launch_error"):
            for field, value in (("backend_exit_code", 0), ("backend_signal", 9)):
                with self.subTest(case=case, field=field):
                    result = trace_fixture(case)[1]
                    result[field] = value
                    self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_true_completion_flags_have_necessary_internal_conditions(self):
        result = trace_fixture()[1]
        result.update(current_full_success=False, inventory_complete=False)
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture("timeout")[1]
        result["work_complete"] = True
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture("artifact_failed")[1]
        result["artifacts_verified"] = True
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture("artifact_failed")[1]
        result["artifacts"][0]["failure"] = None
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))

    def test_invalid_numbers_raw_statuses_and_artifact_paths_are_rejected(self):
        for field, value in (("cli_exit_code", True), ("backend_exit_code", -1), ("backend_signal", 0)):
            with self.subTest(field=field):
                result = trace_fixture()[1]
                result[field] = value
                self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture()[1]
        result["accounting"]["executed_count"] = -1
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))
        result = trace_fixture()[1]
        result["artifacts"][0]["path"] = "../../project-file"
        self.assertFalse(RESULT_VALIDATOR.is_valid(result))


if __name__ == "__main__":
    unittest.main()
