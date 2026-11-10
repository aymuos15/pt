"""Pinned CPython ExitStack boundary for pytest Config cleanup observation.

Only the new observer exit callback is placed below the existing callbacks.
User/pytest callbacks retain their own LIFO order, including callbacks added
during cleanup, and their exception/suppression semantics. No callback is run
early, skipped, serialized, retried or treated as environment/generation proof.
"""
from collections import deque
from contextlib import ExitStack


class FinalizationBoundaryError(RuntimeError):
    pass


class ConfigCleanupBoundary:
    """Private adapter, not a deserializable completion/authorization token.

    Relies on exact CPython 3.12 ExitStack and pytest 8.4.2's Config cleanup
    implementation. Unknown/replaced internals cannot inherit completion.
    """

    def __init__(self, config, finish):
        stack = config._cleanup_stack
        if type(stack) is not ExitStack or type(stack._exit_callbacks) is not deque:
            raise FinalizationBoundaryError("unsupported Config cleanup stack; no callback was changed")
        self.config, self.stack, self.callbacks = config, stack, stack._exit_callbacks
        self.finish, self.finished = finish, False
        callback = self._exit
        before = len(self.callbacks)
        stack.push(callback)
        added = self.callbacks[-1]
        if (stack._exit_callbacks is not self.callbacks or len(self.callbacks) != before + 1
                or type(added) is not tuple or len(added) != 2 or added[0] is not True or added[1] is not callback):
            raise FinalizationBoundaryError("Config cleanup stack changed during observer registration")
        # ExitStack pops from the right. Move only our newly appended entry to
        # the left: the previous entries keep exactly their relative order, and
        # callbacks registered later/during cleanup still use the original queue.
        self.callbacks.rotate(1)

    def _exit(self, exception_type, exception, traceback):
        if self.finished:
            raise FinalizationBoundaryError("Config cleanup observation cannot be resumed or repeated")
        self.finished = True
        complete = (self.config._cleanup_stack is self.stack
                    and self.stack._exit_callbacks is self.callbacks and not self.callbacks)
        self.finish(cleanup_failed=exception_type is not None, boundary_complete=complete)
        return False  # Never suppress a pending pytest/user cleanup exception.
