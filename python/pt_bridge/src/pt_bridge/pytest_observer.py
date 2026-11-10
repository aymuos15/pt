"""Explicit -p pt_bridge.pytest_observer hooks; no auto-plugin or launcher.

Normal pytest owns collection, selection, execution, reports and cleanup. The
bridge records observations only; a valid stream cannot certify a full result.
"""

import pytest

from ._observer import Observer, ObserverError


try:
    _OBSERVER = Observer.from_environment()
except (OSError, ValueError, ObserverError) as exc:
    raise pytest.UsageError("PT observer bootstrap unavailable: " + str(exc)) from exc


def pytest_configure(config):
    _OBSERVER.configure(config)


def pytest_sessionstart(session):
    _OBSERVER.session_start(session)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection(session):
    _OBSERVER.collection_start()
    result = yield
    _OBSERVER.collection_finish(session)
    return result


def pytest_itemcollected(item):
    _OBSERVER.collected(item)


def pytest_deselected(items):
    if len(_OBSERVER.deselected) + len(items) > _OBSERVER.settings["max_items"]:
        _OBSERVER.error("deselection_bound", "deselection notifications exceed the explicit inventory bound")
    _OBSERVER.deselected.extend(items)


def pytest_collectreport(report):
    _OBSERVER.collect_report(report)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    _OBSERVER.attempt_start(item)
    interrupted = True
    try:
        result = yield
        interrupted = False
        return result
    finally:
        _OBSERVER.attempt_finish(interrupted=interrupted)


def pytest_runtest_logreport(report):
    _OBSERVER.phase_report(report)


def pytest_warning_recorded(warning_message, when, nodeid, location):
    _OBSERVER.warning(warning_message, when, nodeid)


def pytest_keyboard_interrupt(excinfo):
    _OBSERVER.interrupted = True


def pytest_internalerror(excrepr, excinfo):
    observer_fault = issubclass(excinfo.type, (ObserverError, UnicodeError))
    _OBSERVER.error("observer_metadata_unsupported" if observer_fault else "pytest_internal_error",
                    "pytest reported an observer metadata failure" if observer_fault else "pytest reported an internal error; native stderr retains its diagnostic",
                    abort=False, category="unsupported" if observer_fault else "internal")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    result = yield
    _OBSERVER.exit_code = int(session.exitstatus)
    return result


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_unconfigure(config):
    hooks_completed = False
    try:
        # A later outer wrapper can still run after this bridge's terminal. It
        # must not silently inherit a reporting-complete assertion.
        wrappers = [hook for hook in reversed(config.hook.pytest_unconfigure.get_hookimpls()) if hook.wrapper or hook.hookwrapper]
        if not wrappers or wrappers[0].function is not pytest_unconfigure:
            _OBSERVER.error("unconfigure_wrapper_order_unsupported", "an outer unconfigure wrapper requires an explicit finalization adapter", abort=False)
        result = yield
        hooks_completed = True
        return result
    finally:
        # Config.add_cleanup callbacks run after this hook, even on an exception.
        # The pinned ExitStack adapter observes their actual completion later.
        _OBSERVER.unconfigure_completed = hooks_completed
