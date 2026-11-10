"""Explicit test-only pytest observer; not the PT bridge, a scheduler or a timing backend."""

import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import time
import uuid

import pytest


MAX_ITEMS = 1024
PROFILES = {"serial-core-v1": 256, "serial-repository-v1": 1024}
MAX_EVENTS = 25000
MAX_EVENT_BYTES = 128 * 1024
MAX_TRACE_BYTES = 8 * 1024 * 1024


class Writer:
    def __init__(self, path, profile):
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.session = uuid.uuid4().hex
        self.profile = profile
        self.seq = self.size = self.reports = self.executed = 0
        self.collected = []
        self.deselected = []
        self.ordinals = {}
        self.active = None
        self.exit_status = None
        self.stop_reason = None
        self.errors = []

    def emit(self, kind, payload):
        self.seq += 1
        event = {"schema_version": 2, "session": self.session, "seq": self.seq,
                 "monotonic_ns": time.monotonic_ns(), "kind": kind, "payload": payload}
        raw = (json.dumps(event, sort_keys=True, allow_nan=False) + "\n").encode()
        self.size += len(raw)
        if self.seq > MAX_EVENTS or len(raw) > MAX_EVENT_BYTES or self.size > MAX_TRACE_BYTES:
            raise RuntimeError("reference trace exceeds its declared bound; no event may be dropped")
        view = memoryview(raw)
        while view:
            count = os.write(self.fd, view)
            if count <= 0:
                raise OSError("short reference trace write")
            view = view[count:]

    def error(self, reason):
        self.errors.append(reason)
        self.emit("observer_error", {"reason": reason})


def _writer(config):
    return config._pt_reference_writer


def _message(report):
    value = report.longrepr
    if value is None:
        return None
    if type(value) is str:
        return value
    if type(value) is tuple and len(value) == 3 and type(value[2]) is str:
        return value[2]
    crash = getattr(value, "reprcrash", None)
    message = getattr(crash, "message", None)
    if type(message) is not str:
        if _ACTIVE is not None:
            _ACTIVE.error("unsupported_reference_failure_representation")
        raise RuntimeError("unsupported reference report failure representation")
    return message


def pytest_addoption(parser):
    group = parser.getgroup("pt-reference-test-observer")
    group.addoption("--pt-reference-trace", required=True, help="new private test-only JSONL trace outside source")
    group.addoption("--pt-reference-profile", choices=tuple(PROFILES), default="serial-core-v1",
                    help="explicit finite occurrence ceiling; never inferred from collected work")


def pytest_configure(config):
    global _ACTIVE
    if (pytest.__version__ != "8.4.2" or sys.version_info[:3] != (3, 12, 12) or sys.implementation.name != "cpython"
            or sys.platform != "linux" or platform.machine() != "x86_64" or sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise pytest.UsageError("reference observer requires Linux x86-64, GIL-enabled CPython 3.12.12 / pytest 8.4.2")
    if getattr(config.option, "numprocesses", None) not in (None, 0):
        raise pytest.UsageError("reference observer has no parallel/worker contract")
    writer = Writer(Path(config.getoption("--pt-reference-trace")), config.getoption("--pt-reference-profile"))
    config._pt_reference_writer = writer
    writer.emit("start", {"python": list(sys.version_info[:3]), "pytest": pytest.__version__, "pid": os.getpid(),
                          "implementation": sys.implementation.name, "platform": sys.platform, "machine": platform.machine(),
                          "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
                          "profile": writer.profile,
                          "collect_only": bool(config.option.collectonly), "maxfail": config.option.maxfail,
                          "continue_on_collection_errors": bool(config.option.continue_on_collection_errors),
                          "argv": list(config.invocation_params.args)})
    _ACTIVE = writer
    for warning in _PENDING_WARNINGS:
        writer.emit("warning", warning)
    _PENDING_WARNINGS.clear()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    writer = _writer(config)
    writer.collected = list(items)
    yield


def pytest_deselected(items):
    if items:
        _writer(items[0].config).deselected.extend(items)


def pytest_collectreport(report):
    # Hook receives no config; pytest's active session is supplied by the
    # companion session-start hook, never inferred from a project import.
    if _ACTIVE is not None:
        _ACTIVE.emit("collection_report", {"nodeid": report.nodeid, "outcome": report.outcome,
                                           "result_count": len(report.result), "failure_message": _message(report),
                                           "diagnostic_longrepr": report.longreprtext if report.failed else None})


_ACTIVE = None
_PENDING_WARNINGS = []


def pytest_sessionstart(session):
    global _ACTIVE
    _ACTIVE = _writer(session.config)


def pytest_collection_finish(session):
    writer = _writer(session.config)
    if not writer.collected:
        writer.collected = list(session.items)
    if len(writer.collected) > min(MAX_ITEMS, PROFILES[writer.profile]) or len({id(item) for item in writer.collected}) != len(writer.collected):
        raise RuntimeError("unsupported reference inventory size or repeated live item object")
    writer.ordinals = {id(item): ordinal for ordinal, item in enumerate(writer.collected)}
    writer.emit("inventory", {"collected": [{"ordinal": ordinal, "nodeid": item.nodeid} for ordinal, item in enumerate(writer.collected)],
                              "selected": [writer.ordinals[id(item)] for item in session.items],
                              "deselected": [writer.ordinals[id(item)] for item in writer.deselected]})


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    writer = _writer(item.config)
    ordinal = writer.ordinals[id(item)]
    if writer.active is not None:
        raise RuntimeError("nested reference runtest protocol is unsupported")
    writer.active = ordinal
    writer.executed += 1
    writer.emit("protocol_start", {"ordinal": ordinal, "nodeid": item.nodeid})
    try:
        yield
    finally:
        writer.emit("protocol_finish", {"ordinal": ordinal, "nodeid": item.nodeid})
        writer.active = None


def pytest_runtest_logreport(report):
    writer = _ACTIVE
    if writer is None or writer.active is None:
        if writer is not None:
            writer.error("phase_report_outside_active_occurrence")
        return
    writer.reports += 1
    writer.emit("phase", {"ordinal": writer.active, "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                          "wasxfail": getattr(report, "wasxfail", None), "failure_message": _message(report),
                          "diagnostic_longrepr": report.longreprtext if report.longrepr is not None else None,
                          "sections": [list(section) for section in report.sections],
                          "duration": report.duration})


def pytest_warning_recorded(warning_message, when, nodeid, location):
    observation = {"category": warning_message.category.__module__ + "." + warning_message.category.__name__,
                   "message": str(warning_message.message), "when": when, "nodeid": nodeid}
    if _ACTIVE is None:
        _PENDING_WARNINGS.append(observation)
    else:
        _ACTIVE.emit("warning", observation)


def pytest_internalerror(excrepr, excinfo):
    if _ACTIVE is not None:
        _ACTIVE.emit("backend_error", {"exception_type": excinfo.type.__module__ + "." + excinfo.type.__name__, "message": str(excinfo.value)})


def pytest_keyboard_interrupt(excinfo):
    if _ACTIVE is not None:
        # Pytest also uses Interrupted for an ordinary collection error. It is
        # an observed backend outcome, not an observer infrastructure failure.
        _ACTIVE.emit("interruption", {"exception_type": excinfo.type.__module__ + "." + excinfo.type.__name__, "message": str(excinfo.value)})


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    yield
    writer = _writer(session.config)
    writer.exit_status = int(session.exitstatus)
    reason = session.shouldstop or session.shouldfail
    writer.stop_reason = str(reason) if reason else None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_unconfigure(config):
    global _ACTIVE
    yield
    writer = getattr(config, "_pt_reference_writer", None)
    if writer is not None:
        try:
            writer.emit("terminal", {"exit_status": writer.exit_status, "reports": writer.reports,
                                     "executed": writer.executed, "stop_reason": writer.stop_reason, "observer_errors": writer.errors})
            os.fsync(writer.fd)
        finally:
            os.close(writer.fd)
            _ACTIVE = None
