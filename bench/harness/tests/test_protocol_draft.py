import copy
import importlib.util
import json
from pathlib import Path
import unittest

import jsonschema


SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                     "protocol-v0.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
EXAMPLES = Path(__file__).resolve().parents[3] / "tests/contracts/protocol_examples.py"
spec = importlib.util.spec_from_file_location("protocol_examples", EXAMPLES)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


event = examples.event


class DraftProtocolTests(unittest.TestCase):
    def test_schema_is_well_formed(self):
        jsonschema.Draft202012Validator.check_schema(SCHEMA)

    def test_every_catalog_kind_has_a_typed_example(self):
        kinds = {branch["properties"]["kind"]["const"] for branch in SCHEMA["oneOf"]}
        self.assertEqual(kinds, examples.COORDINATOR.keys() | examples.BRIDGE.keys())
        self.assertEqual(len(kinds), 32)
        for kind in sorted(kinds):
            with self.subTest(kind=kind):
                VALIDATOR.validate(event(kind))
                wrong_role = event(kind)
                wrong_role["producer_role"] = "bridge" if wrong_role["producer_role"] == "coordinator" else "coordinator"
                with self.assertRaises(jsonschema.ValidationError):
                    VALIDATOR.validate(wrong_role)

    def test_duplicate_node_ids_are_distinct_occurrences(self):
        first = event("item_collected", {"ordinal": 0, "nodeid": "tests/test_x.py::test_x"})
        second = event("item_collected", {"ordinal": 1, "nodeid": "tests/test_x.py::test_x"})
        VALIDATOR.validate(first)
        VALIDATOR.validate(second)
        self.assertNotEqual(first["payload"]["ordinal"], second["payload"]["ordinal"])
        self.assertEqual(first["payload"]["nodeid"], second["payload"]["nodeid"])

    def test_phase_collection_and_terminal_shapes(self):
        samples = [
            event("session_started"), event("collection_report"), event("items_selected"),
            event("items_deselected"), event("phase_report"), event("collection_error"),
            event("session_terminated"), event("artifact_committed"),
        ]
        for sample in samples:
            with self.subTest(kind=sample["kind"]):
                VALIDATOR.validate(sample)

    def test_malformed_or_ambiguous_messages_are_rejected(self):
        valid = event("phase_report")
        invalid = []
        for field, value in (("protocol_version", 1), ("sequence", -1),
                             ("sequence", True), ("session_id", ""), ("kind", "unknown")):
            altered = copy.deepcopy(valid)
            altered[field] = value
            invalid.append(altered)
        missing_phase = copy.deepcopy(valid)
        del missing_phase["payload"]["phase"]
        invalid.append(missing_phase)
        extra = copy.deepcopy(valid)
        extra["payload"]["python_object"] = "not allowed"
        invalid.append(extra)
        bad_terminal = event("session_terminated")
        bad_terminal["payload"]["backend_exit_code"] = None
        invalid.append(bad_terminal)
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(jsonschema.ValidationError):
                VALIDATOR.validate(message)

    def test_strict_xpass_and_worker_status_cannot_be_ambiguous(self):
        strict = event("phase_report")
        strict["payload"].update(phase="call", outcome="failed", strict_xpass=True)
        VALIDATOR.validate(strict)
        strict["payload"]["outcome"] = "passed"
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(strict)
        worker = event("worker_exited")
        worker["payload"]["signal"] = 9
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(worker)

    def test_missing_accounting_and_unverified_artifact_commit_are_rejected(self):
        for kind, field in (("collection_finished", "deselected_count"),
                            ("session_terminated", "phase_counts"), ("phase_report", "was_xfail")):
            data = event(kind)
            del data["payload"][field]
            with self.subTest(kind=kind), self.assertRaises(jsonschema.ValidationError):
                VALIDATOR.validate(data)
        artifact = event("artifact_committed")
        artifact["payload"]["verified"] = False
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(artifact)
        artifact["payload"]["verified"] = True
        artifact["payload"]["path"] = "../../untrusted"
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(artifact)

    def test_serial_v0_cannot_grant_optimizations_or_accept_old_draft(self):
        permission = event("capability_decision")
        permission["payload"]["decision"] = "allow"
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(permission)
        old = event("session_started", {})
        del old["contract_revision"]
        with self.assertRaises(jsonschema.ValidationError):
            VALIDATOR.validate(old)

    def test_handshake_requires_the_exact_target_version_tuple(self):
        for field in ("python_version", "pytest_version", "bridge_version"):
            with self.subTest(field=field):
                message = event("session_started")
                message["payload"][field] = "9.9.9"
                with self.assertRaises(jsonschema.ValidationError):
                    VALIDATOR.validate(message)


if __name__ == "__main__":
    unittest.main()
