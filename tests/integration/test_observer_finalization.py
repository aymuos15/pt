"""Pinned cleanup ordering/exception controls, not startup or runner qualification."""
from collections import deque
from contextlib import ExitStack
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/pt_bridge/src"))
from pt_bridge._finalization import ConfigCleanupBoundary, FinalizationBoundaryError
from pt_bridge._observer import Observer
sys.path.pop(0)


class ConfigCleanupControls(unittest.TestCase):
    def test_callback_order_and_nested_registrations_match_unmodified_exitstack(self):
        def run(observed):
            effects = []
            config = SimpleNamespace(_cleanup_stack=ExitStack())
            add = config._cleanup_stack.callback

            def register_during_cleanup(name):
                effects.append(name)
                add(effects.append, name + "-nested")

            add(effects.append, "old-first")
            add(register_during_cleanup, "old-second")
            if observed:
                ConfigCleanupBoundary(config, lambda **facts: effects.append(facts))
            add(effects.append, "new-first")
            add(register_during_cleanup, "new-second")
            config._cleanup_stack.close()
            return effects

        plain, observed = run(False), run(True)
        self.assertEqual(plain, ["new-second", "new-second-nested", "new-first", "old-second", "old-second-nested", "old-first"])
        self.assertEqual(observed[:-1], plain)
        self.assertEqual(observed[-1], {"cleanup_failed": False, "boundary_complete": True})

    def test_pending_exception_identity_and_lifo_cleanup_are_not_suppressed_or_replaced(self):
        config, effects, facts = SimpleNamespace(_cleanup_stack=ExitStack()), [], []
        error = RuntimeError("PT_CLEANUP_EXCEPTION")

        def failure():
            effects.append("failure")
            raise error

        config._cleanup_stack.callback(effects.append, "oldest")
        ConfigCleanupBoundary(config, lambda **value: facts.append((value, effects.copy())))
        config._cleanup_stack.callback(failure)
        with self.assertRaises(RuntimeError) as observed:
            config._cleanup_stack.close()
        self.assertIs(observed.exception, error)
        self.assertEqual(effects, ["failure", "oldest"])
        self.assertEqual(facts, [({"cleanup_failed": True, "boundary_complete": True}, effects)])

    def test_original_exception_suppression_semantics_remain_owned_by_original_callbacks(self):
        config, effects, facts = SimpleNamespace(_cleanup_stack=ExitStack()), [], []
        config._cleanup_stack.push(lambda *details: effects.append(details[0]) or True)
        ConfigCleanupBoundary(config, lambda **value: facts.append(value))

        def failure():
            raise ValueError("suppressed by the test-owned original exit callback")

        config._cleanup_stack.callback(failure)
        config._cleanup_stack.close()
        self.assertEqual(effects, [ValueError])
        self.assertEqual(facts, [{"cleanup_failed": False, "boundary_complete": True}])

    def test_unknown_stack_types_are_not_inspected_executed_or_changed(self):
        effects = []

        class ProjectStack:
            def __getattr__(self, name):
                effects.append(name)
                raise AssertionError("project callback introspection")

        stack = ProjectStack()
        config = SimpleNamespace(_cleanup_stack=stack)
        with self.assertRaises(FinalizationBoundaryError):
            ConfigCleanupBoundary(config, mock.Mock())
        self.assertIs(config._cleanup_stack, stack)
        self.assertEqual(effects, [])
        stack = ExitStack()
        stack._exit_callbacks = []
        with self.assertRaises(FinalizationBoundaryError):
            ConfigCleanupBoundary(SimpleNamespace(_cleanup_stack=stack), mock.Mock())
        self.assertEqual(stack._exit_callbacks, [])

    def test_replaced_stack_or_transferred_callbacks_cannot_inherit_complete_observation(self):
        for transfer in (False, True):
            config, facts, effects = SimpleNamespace(_cleanup_stack=ExitStack()), [], []
            original = config._cleanup_stack
            original.callback(effects.append, "actual callback")
            ConfigCleanupBoundary(config, lambda **value: facts.append(value))
            if transfer:
                moved = original.pop_all()
                moved.close()
            else:
                config._cleanup_stack = ExitStack()
                original.close()
            self.assertEqual(effects, ["actual callback"])
            self.assertEqual(facts, [{"cleanup_failed": False, "boundary_complete": False}])

    def test_missing_boundary_callback_does_not_recover_or_invent_completion(self):
        config, facts = SimpleNamespace(_cleanup_stack=ExitStack()), []
        boundary = ConfigCleanupBoundary(config, lambda **value: facts.append(value))
        original = config._cleanup_stack._exit_callbacks
        config._cleanup_stack._exit_callbacks = deque()
        config._cleanup_stack.close()
        self.assertFalse(boundary.finished)
        self.assertEqual(facts, [])
        # The deliberate test substitution is retained; no reattachment/close of
        # the old queue is performed to manufacture a complete observation.
        self.assertEqual(len(original), 1)

    def test_finished_boundary_is_single_use_and_a_second_stack_close_does_not_replay(self):
        config, facts = SimpleNamespace(_cleanup_stack=ExitStack()), []
        boundary = ConfigCleanupBoundary(config, lambda **value: facts.append(value))
        config._cleanup_stack.close()
        config._cleanup_stack.close()
        self.assertEqual(facts, [{"cleanup_failed": False, "boundary_complete": True}])
        with self.assertRaises(FinalizationBoundaryError):
            boundary._exit(None, None, None)
        self.assertEqual(len(facts), 1)

    def test_observer_preserves_cleanup_error_without_calling_its_string_or_repr(self):
        settings = {"schema_version": 1, "timeout_seconds": 30, "mode": "run"}
        channel = mock.Mock()
        channel.failed = False
        observer = Observer(settings, channel)
        observer.exit_code, observer.unconfigure_completed = 0, True
        observer.after_config_cleanup(cleanup_failed=True, boundary_complete=True)
        messages = [call.args for call in channel.send.call_args_list]
        self.assertEqual([message[0] for message in messages], ["session_error", "session_terminated"])
        self.assertEqual(messages[0][1]["code"], "config_cleanup_failed")
        self.assertFalse(messages[1][1]["reporting_complete"])
        self.assertEqual(messages[1][1]["backend_exit_code"], 0)
        channel.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
