import copy
import json
from pathlib import Path
import unittest

import jsonschema


SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                     "protocol-v0.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def event(kind, payload):
    return {"protocol_version": 0, "run_id": "run", "generation_id": "gen",
            "session_id": "session", "producer_id": "producer", "sequence": 0,
            "kind": kind, "payload": payload}


class DraftProtocolTests(unittest.TestCase):
    def test_schema_is_well_formed(self):
        jsonschema.Draft202012Validator.check_schema(SCHEMA)

    def test_duplicate_node_ids_are_distinct_occurrences(self):
        first = event("item_collected", {"ordinal": 0, "nodeid": "tests/test_x.py::test_x"})
        second = event("item_collected", {"ordinal": 1, "nodeid": "tests/test_x.py::test_x"})
        VALIDATOR.validate(first)
        VALIDATOR.validate(second)
        self.assertNotEqual(first["payload"]["ordinal"], second["payload"]["ordinal"])
        self.assertEqual(first["payload"]["nodeid"], second["payload"]["nodeid"])

    def test_phase_collection_and_terminal_shapes(self):
        samples = [
            event("session_started", {}),
            event("phase_report", {"ordinal": 0, "attempt": 0, "phase": "setup",
                                   "outcome": "failed", "reason": "fixture failed", "was_xfail": None}),
            event("phase_report", {"ordinal": 0, "attempt": 0, "phase": "teardown",
                                   "outcome": "failed", "reason": "finalizer failed", "was_xfail": None}),
            event("collection_error", {"nodeid": "test_bad.py", "reason": "syntax error"}),
            event("session_terminated", {"termination": "backend_exited", "backend_exit_code": 1}),
            event("session_terminated", {"termination": "infrastructure_failed", "backend_exit_code": None}),
        ]
        for sample in samples:
            with self.subTest(kind=sample["kind"]):
                VALIDATOR.validate(sample)

    def test_malformed_or_ambiguous_messages_are_rejected(self):
        valid = event("phase_report", {"ordinal": 0, "attempt": 0, "phase": "call",
                                       "outcome": "passed", "reason": None, "was_xfail": None})
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
        invalid.append(event("session_terminated", {"termination": "backend_exited", "backend_exit_code": None}))
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(jsonschema.ValidationError):
                VALIDATOR.validate(message)


if __name__ == "__main__":
    unittest.main()
