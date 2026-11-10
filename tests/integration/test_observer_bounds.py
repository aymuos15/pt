"""Observer metadata and bootstrap controls, not execution qualification."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/pt_bridge/src"))
from pt_bridge._observer import Observer, ObserverError, configuration, failure_reason, text
sys.path.pop(0)


def settings():
    return {"schema_version": 1, "fd": 3, "identity": {"request_id": "r", "run_id": "r", "generation_id": "g", "session_id": "s", "producer_id": "b"},
            "invocation_profile": "pytest_module", "mode": "run", "max_items": 256, "max_collection_reports": 1024,
            "max_nodeid_bytes": 1024*1024, "byte_budget": 8*1024*1024, "event_budget": 25000, "timeout_seconds": 30}


class ObserverMetadataControls(unittest.TestCase):
    def test_bootstrap_is_closed_and_requires_every_nullable_or_nonnullable_request_field(self):
        original = settings()
        self.assertEqual(configuration(json.dumps(original)), original)
        for key in original:
            value = original.copy()
            del value[key]
            with self.subTest(key=key), self.assertRaises((ValueError, ObserverError)):
                configuration(json.dumps(value))
        with self.assertRaises(ObserverError):
            configuration(json.dumps({**original, "unknown": None}))
        with self.assertRaises((ValueError, ObserverError)):
            configuration(json.dumps(original).replace('"fd": 3', '"fd": 3, "fd": 3'))

    def test_boolean_negative_and_excessive_bounds_are_not_coerced_into_valid_integers(self):
        for key in ("max_items", "max_collection_reports", "max_nodeid_bytes", "byte_budget", "event_budget", "timeout_seconds"):
            for value in (True, 0, -1, 2**64, 1.0):
                with self.subTest(key=key, value=value), self.assertRaises((ValueError, ObserverError)):
                    configuration(json.dumps({**settings(), key: value}))
        for value in (None, "", "x"*8193, "{}"):
            with self.assertRaises((ValueError, ObserverError)):
                configuration(value)

    def test_report_metadata_never_calls_custom_str_repr_or_attribute_hooks(self):
        effects = []

        class ProjectRepresentation:
            def __repr__(self):
                effects.append("repr")
                return "project"

            def __str__(self):
                effects.append("str")
                return "project"

            def __getattr__(self, name):
                effects.append("getattr:" + name)
                raise AttributeError(name)

        with self.assertRaises(ObserverError):
            failure_reason(SimpleNamespace(longrepr=ProjectRepresentation()))
        self.assertEqual(effects, [])
        self.assertEqual(failure_reason(SimpleNamespace(longrepr=("x.py", 1, "PT_SKIP"))), "PT_SKIP")
        self.assertEqual(failure_reason(SimpleNamespace(longrepr="[XPASS(strict)] PT_EXPECTED")), "[XPASS(strict)] PT_EXPECTED")

    def test_text_does_not_normalize_or_truncate_unicode_or_accept_arbitrary_string_subclasses(self):
        value = "λ 🐍 [a/b]"
        self.assertEqual(text(value), value)
        self.assertEqual(len(text("🐍"*65536)), 65536)
        with self.assertRaises(ObserverError):
            text("🐍"*65537)
        with self.assertRaises(UnicodeError):
            text("\ud800")

        class ProjectString(str):
            pass

        with self.assertRaises(ObserverError):
            text(ProjectString("not plain"))

    def test_warning_with_project_str_is_classified_without_executing_that_str(self):
        effects = []

        class ProjectWarning(UserWarning):
            def __str__(self):
                effects.append("str")
                return "changed"

        channel = mock.Mock()
        observer = Observer(settings(), channel)
        message = SimpleNamespace(message=ProjectWarning("PT_WARNING"), category=ProjectWarning, lineno=1, filename="x.py")
        with self.assertRaises(ObserverError):
            observer.warning(message, "runtest", "")
        self.assertEqual(effects, [])
        self.assertTrue(observer.unsupported)
        self.assertEqual(channel.send.call_args.args[0], "session_error")


if __name__ == "__main__":
    unittest.main()
