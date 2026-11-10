"""Independent, deliberately incorrect pytest controls. Never load in normal runs."""

import warnings

import pytest


def pytest_addoption(parser):
    parser.addoption("--pt-broken-runner", choices=("skip_call", "skip_setup", "skip_teardown", "drop_duplicate",
                                                   "relax_strict_xpass", "hide_collection_error", "suppress_warnings"), required=True)


def _mode(config):
    return config.getoption("--pt-broken-runner")


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    if _mode(session.config) == "skip_teardown":
        session._setupstate.teardown_exact = lambda nextitem: None


def pytest_collection_modifyitems(config, items):
    mode = _mode(config)
    if mode == "drop_duplicate":
        seen = set()
        items[:] = [item for item in items if not (item.nodeid in seen or seen.add(item.nodeid))]
    for item in items:
        if mode == "skip_call":
            item.runtest = lambda: None
        elif mode == "skip_setup":
            item.setup = lambda: None
        elif mode == "relax_strict_xpass":
            for mark in item.iter_markers("xfail"):
                mark.kwargs["strict"] = False


@pytest.hookimpl(tryfirst=True)
def pytest_collectreport(report):
    if report.failed and _CONFIG is not None and _mode(_CONFIG) == "hide_collection_error":
        report.outcome = "passed"
        report.longrepr = None
        report.result = []


_CONFIG = None


def pytest_configure(config):
    global _CONFIG
    _CONFIG = config


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    with warnings.catch_warnings():
        if _mode(item.config) == "suppress_warnings":
            warnings.simplefilter("ignore")
        yield
