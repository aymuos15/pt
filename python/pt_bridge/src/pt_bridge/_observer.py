"""Bounded fresh-serial observation state; no scheduler or result certifier.

The public explicitly loaded hook module is pytest_observer. This module does
not start a session on import and never imports the independent reference oracle.
"""

import json
import math
import os
import platform
import sys
import sysconfig
import time

import pytest
from _pytest._code.code import ExceptionChainRepr, ReprExceptionInfo, ReprFileLocation

from . import __version__
from ._wire import ControlStream, _identity, _no_float, _pairs


class ObserverError(RuntimeError):
    pass


def text(value):
    if type(value) is not str or len(value) > 65536:
        raise ObserverError("observer metadata requires an ordinary bounded string")
    value.encode("utf-8", errors="strict")
    return value


def configuration(raw):
    if type(raw) is not str or len(raw) > 8192:
        raise ObserverError("explicit PT_BRIDGE_CONTROL configuration is required and bounded")
    if len(raw.encode("utf-8", errors="strict")) > 8192:
        raise ObserverError("explicit PT_BRIDGE_CONTROL UTF-8 bytes exceed the bootstrap bound")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_float=_no_float, parse_constant=_no_float)
    fields = {"schema_version", "fd", "identity", "invocation_profile", "mode", "max_items", "max_collection_reports",
              "max_nodeid_bytes", "byte_budget", "event_budget", "timeout_seconds"}
    if (type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] not in (1, 2)
            or set(value) != (fields if value["schema_version"] == 1 else fields | {"junit_artifact"})
            or value["invocation_profile"] not in ("pytest_module", "pytest_console") or value["mode"] not in ("run", "collect_only")
            or type(value["fd"]) is not int or value["fd"] < 3):
        raise ObserverError("unsupported closed observer bootstrap configuration")
    for key, maximum in (("max_items", 100000), ("max_collection_reports", 100000), ("max_nodeid_bytes", 16*1024*1024),
                         ("byte_budget", 64*1024*1024), ("event_budget", 1000000), ("timeout_seconds", 3600)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ObserverError("invalid explicit observer bound: " + key)
    value["identity"] = _identity(value["identity"])
    if value["schema_version"] == 2:
        from ._artifacts import declaration
        value["junit_artifact"] = declaration(value["junit_artifact"])
    return value


def failure_reason(report):
    """Only already-rendered supported pytest fields, never arbitrary project repr."""
    value = report.longrepr
    if value is None:
        return None
    if type(value) is str:
        return text(value)
    if type(value) is tuple and len(value) == 3 and type(value[2]) is str:
        return text(value[2])
    if type(value) in (ExceptionChainRepr, ReprExceptionInfo) and type(value.reprcrash) is ReprFileLocation:
        return text(value.reprcrash.message)
    raise ObserverError("unsupported report representation; no arbitrary repr was requested")


class Observer:
    def __init__(self, settings, channel):
        self.settings, self.channel = settings, channel
        self.deadline = time.monotonic() + settings["timeout_seconds"]
        self.junit_artifact = None
        if settings["schema_version"] == 2:
            from ._artifacts import DeclaredJunit
            self.junit_artifact = DeclaredJunit(settings["junit_artifact"], os.getcwd(), self.deadline)
        self.session = self.config = None
        self.finalization = None
        self.unconfigure_completed = False
        self.items, self.deselected, self.selected, self.nodeids = [], [], [], []
        self.ordinals, self.attempts, self.not_run = {}, {}, {}
        self.next_selected = 0
        self.active = self.last_ordinal = self.exit_code = None
        self.collection_started = self.collection_finished = self.collection_failed = self.interrupted = False
        self.collector_reports = self.errors = 0
        self.unsupported = False
        self.phase_counts = {phase: {outcome: 0 for outcome in ("passed", "failed", "skipped")} for phase in ("setup", "call", "teardown")}

    @classmethod
    def from_environment(cls):
        settings = configuration(os.environ.get("PT_BRIDGE_CONTROL"))
        channel = ControlStream.take_fd(settings["fd"], settings["identity"], byte_budget=settings["byte_budget"], event_budget=settings["event_budget"])
        try:
            observer = cls(settings, channel)
            if (sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 12) or sys.platform != "linux"
                    or platform.machine() != "x86_64" or sysconfig.get_config_var("Py_GIL_DISABLED")
                    or pytest.__version__ != "8.4.2" or __version__ != "0.0.0"):
                raise ObserverError("observer requires the exact Linux x86-64 CPython 3.12.12 / pytest 8.4.2 / bridge 0.0.0 target")
            observer.emit("session_started", {"python_version": "3.12.12", "pytest_version": pytest.__version__,
                "bridge_version": __version__, "invocation_profile": settings["invocation_profile"]})
            return observer
        except BaseException:
            if "observer" in locals():
                observer.close_artifacts()
            channel.close()
            raise

    def emit(self, kind, payload):
        self.channel.send(kind, payload, deadline=self.deadline)

    def error(self, code, message, *, abort=True, category="unsupported"):
        self.unsupported = self.unsupported or category in ("unsupported", "infrastructure")
        if self.errors >= 1024:
            raise ObserverError("observer error-summary bound exceeded")
        self.errors += 1
        self.emit("session_error", {"category": category, "code": code, "message": text(message)})
        if abort:
            raise ObserverError(message)

    def configure(self, config):
        self.config = config
        from ._finalization import ConfigCleanupBoundary, FinalizationBoundaryError
        try:
            if type(config) is not pytest.Config:
                raise FinalizationBoundaryError("unsupported Config implementation")
            self.finalization = ConfigCleanupBoundary(config, self.after_config_cleanup)
        except FinalizationBoundaryError:
            try:
                self.error("config_cleanup_boundary_unsupported", "the pinned finalization boundary is unavailable; callbacks were not suppressed or replayed")
            finally:
                self.close_artifacts()
                self.channel.close()
        if bool(config.option.collectonly) != (self.settings["mode"] == "collect_only"):
            self.error("request_mode_mismatch", "actual pytest collection mode differs from the explicit request")
        if getattr(config.option, "numprocesses", None) not in (None, 0) or hasattr(config, "workerinput"):
            self.error("parallel_adapter_unsupported", "this observer has no parallel or worker adapter")
        if getattr(config.option, "reruns", 0):
            self.error("retry_adapter_unsupported", "this observer has no retry-plugin adapter; plugins were not disabled")

    def close_artifacts(self):
        if self.junit_artifact is not None:
            self.junit_artifact.close()

    def after_config_cleanup(self, *, cleanup_failed, boundary_complete):
        try:
            if not boundary_complete:
                self.error("config_cleanup_boundary_unavailable", "the original Config cleanup stack was replaced or did not drain before observation", abort=False)
            if cleanup_failed:
                self.error("config_cleanup_failed", "a Config cleanup exception remains pending; native stderr and the actual process return retain its diagnostic", abort=False, category="infrastructure")
        finally:
            self.terminal(hooks_completed=self.unconfigure_completed and boundary_complete and not cleanup_failed)

    def session_start(self, session):
        self.session = session
        if self.junit_artifact is not None:
            from _pytest.junitxml import LogXML, xml_key
            actual = session.config.stash.get(xml_key, None)
            if type(actual) is not LogXML or type(actual.logfile) is not str or os.fsencode(actual.logfile) != self.junit_artifact.expected_path:
                self.error("junit_artifact_request_mismatch", "the explicit JUnit artifact does not match the actual enabled pytest formatter destination; no option or plugin was changed")

    def collection_start(self):
        if self.collection_started:
            self.error("duplicate_collection", "another collection pass in this execution session is unsupported")
        self.collection_started = True
        self.emit("collection_started", {})

    def collected(self, item):
        if len(self.items) >= self.settings["max_items"]:
            self.error("inventory_bound", "observed item inventory exceeds the explicit bound; no truncation or replay")
        self.items.append(item)

    def collect_report(self, report):
        if self.collector_reports >= self.settings["max_collection_reports"]:
            self.error("collector_report_bound", "collector report bound exceeded")
        report_id = self.collector_reports
        self.collector_reports += 1
        outcome = text(report.outcome)
        if outcome not in ("passed", "failed", "skipped"):
            self.error("collector_outcome_unsupported", "collector outcome is outside the serial contract")
        nodeid, reason = text(report.nodeid), failure_reason(report)
        self.emit("collection_report", {"report_id": report_id, "nodeid": nodeid, "outcome": outcome, "reason": reason})
        if outcome == "failed":
            self.collection_failed = True
            if self.errors >= 1024:
                raise ObserverError("combined collector/session error-summary bound exceeded")
            self.errors += 1
            self.emit("collection_error", {"report_id": report_id, "nodeid": nodeid, "reason": reason if reason is not None else ""})

    def collection_finish(self, session):
        if len({id(item) for item in self.items}) != len(self.items):
            self.error("repeated_live_item", "repeated live Item objects require an adapter; node-ID duplicates remain allowed")
        self.ordinals = {id(item): ordinal for ordinal, item in enumerate(self.items)}
        self.nodeids = [text(item.nodeid) for item in self.items]
        if sum(len(value.encode("utf-8")) for value in self.nodeids) > self.settings["max_nodeid_bytes"]:
            self.error("nodeid_byte_bound", "aggregate node-ID bytes exceed the explicit request bound")
        try:
            self.selected = [self.ordinals[id(item)] for item in session.items]
            deselected = [self.ordinals[id(item)] for item in self.deselected]
        except KeyError:
            self.error("unobserved_item", "a collection hook introduced an Item outside the observed collection")
        if (len(self.selected) + len(deselected) != len(self.items)
                or len(set(self.selected + deselected)) != len(self.items)):
            self.error("selection_partition", "selected/deselected occurrences are not an exhaustive disjoint partition")
        for ordinal, nodeid in enumerate(self.nodeids):
            self.emit("item_collected", {"ordinal": ordinal, "nodeid": nodeid})
        for kind, values in (("items_selected", self.selected), ("items_deselected", deselected)):
            # Empty selection is a real explicit chunk, never hidden no-tests success.
            for chunk, start in enumerate(range(0, max(len(values), 1), 4096)):
                payload = {"chunk": chunk, "ordinals": values[start:start+4096]}
                if kind == "items_deselected":
                    payload["reason"] = None
                self.emit(kind, payload)
        self.emit("collection_finished", {"status": "failed" if self.collection_failed else "complete",
            "inventory_complete": not self.collection_failed, "collected_count": len(self.items),
            "selected_count": len(self.selected), "deselected_count": len(deselected)})
        self.collection_finished = True

    def attempt_start(self, item):
        ordinal = self.ordinals.get(id(item))
        expected = self.selected[self.next_selected] if self.next_selected < len(self.selected) else None
        if not self.collection_finished or self.active is not None or ordinal is None or ordinal != expected or ordinal in self.attempts:
            self.error("attempt_order_unsupported", "unobserved, replayed, overlapping or reordered attempt")
        if text(item.nodeid) != self.nodeids[ordinal]:
            self.error("nodeid_changed_after_collection", "node ID changed after the collection barrier")
        self.active = ordinal
        self.next_selected += 1
        self.attempts[ordinal] = {"phases": [], "disposition": None}
        self.emit("item_started", {"ordinal": ordinal, "attempt": 0})

    def phase_report(self, report):
        if self.active is None or text(report.nodeid) != self.nodeids[self.active]:
            self.error("unowned_phase", "phase report is outside its active observed occurrence")
        phase, outcome = text(report.when), text(report.outcome)
        phases = self.attempts[self.active]["phases"]
        expected = "setup" if not phases else "call" if len(phases) == 1 and phases[0][1] == "passed" else "teardown"
        if phase != expected or any(value[0] == phase for value in phases) or outcome not in ("passed", "failed", "skipped"):
            self.error("phase_order_unsupported", "nonstandard, repeated or reordered phase reporting requires an adapter")
        reason = failure_reason(report)
        xfail = getattr(report, "wasxfail", None)
        if xfail is not None:
            xfail = text(xfail)
        duration = report.duration
        if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0 or duration*1000000000 >= 2**64:
            self.error("phase_duration_unsupported", "invalid bounded elapsed phase duration")
        self.emit("phase_report", {"ordinal": self.active, "attempt": 0, "phase": phase, "outcome": outcome,
            "reason": reason, "was_xfail": xfail, "strict_xpass": phase == "call" and outcome == "failed"
                and type(report.longrepr) is str and report.longrepr.startswith("[XPASS(strict)] "),
            "duration_ns": int(duration*1000000000), "artifact_ids": []})
        phases.append((phase, outcome))
        self.phase_counts[phase][outcome] += 1

    def attempt_finish(self, *, interrupted):
        ordinal = self.active
        if ordinal is None:
            return
        attempt = self.attempts[ordinal]
        observed = [value[0] for value in attempt["phases"]]
        expected = ["setup", "call", "teardown"] if attempt["phases"] and attempt["phases"][0][1] == "passed" else ["setup", "teardown"]
        complete = observed == expected
        if not complete and not interrupted:
            self.error("missing_applicable_phases", "normal runtest protocol omitted applicable phases", abort=False)
        disposition = "completed" if complete else "interrupted"
        self.emit("attempt_finished", {"ordinal": ordinal, "attempt": 0, "disposition": disposition,
            "reason": None if complete else "runtest protocol ended with incomplete applicable phases"})
        attempt["disposition"] = disposition
        self.last_ordinal, self.active = ordinal, None

    def warning(self, warning_message, when, nodeid):
        value, category = warning_message.message, warning_message.category
        # Do not invoke a project-defined __str__/repr merely for control metadata.
        if (type(category) is not type or type(value).__str__ is not BaseException.__str__
                or type(value.args) is not tuple or len(value.args) != 1 or type(value.args[0]) is not str):
            self.error("warning_representation_unsupported", "warning needs an explicit representation adapter; no custom str/repr was called")
        ordinal = self.active if self.active is not None else self.last_ordinal
        if ordinal is not None and (not nodeid or nodeid != self.nodeids[ordinal]):
            ordinal = None
        # pytest delivers runtest warnings after its warning-capture context, not
        # at their originating setup/call/teardown instant. 'finalize' names this
        # delivery boundary; it does not invent an originating test phase.
        boundary = {"config": "configure", "collect": "collect", "runtest": "finalize"}.get(when)
        if boundary is None:
            self.error("warning_boundary_unsupported", "unknown pytest warning delivery boundary")
        line = warning_message.lineno
        if type(line) is not int or line < 1:
            self.error("warning_location_unsupported", "warning location is not an ordinary one-based line")
        self.emit("warning", {"ordinal": ordinal, "category": text(category.__module__ + "." + category.__name__),
            "message": text(value.args[0]), "filename": text(warning_message.filename), "line": line, "when": boundary})

    def terminal(self, *, hooks_completed):
        try:
            if self.exit_code is None or self.channel.failed:
                return  # No fabricated return for --help, early abort or transport loss.
            if self.active is not None:
                self.attempt_finish(interrupted=True)
            for ordinal in self.selected:
                if ordinal in self.attempts:
                    continue
                if self.settings["mode"] == "collect_only":
                    reason = "collect_only"
                elif self.collection_failed and not self.config.option.continue_on_collection_errors:
                    reason = "collection_failed"
                elif self.config.option.maxfail and self.session.testsfailed >= self.config.option.maxfail:
                    reason = "fail_fast"
                else:
                    reason = "interrupted"
                self.emit("item_not_run", {"ordinal": ordinal, "reason": reason})
                self.not_run[ordinal] = reason
            completed = sum(value["disposition"] == "completed" for value in self.attempts.values())
            accounting = {"collected_count": len(self.nodeids), "selected_count": len(self.selected),
                "deselected_count": len(self.nodeids)-len(self.selected), "executed_count": len(self.attempts),
                "completed_count": completed, "not_run_count": len(self.not_run), "attempts_started": len(self.attempts), "attempts_completed": completed}
            incomplete = [ordinal for ordinal in self.selected if ordinal not in self.not_run and
                           (ordinal not in self.attempts or self.attempts[ordinal]["disposition"] != "completed")]
            if self.junit_artifact is not None:
                try:
                    self.emit("artifact_ready", self.junit_artifact.ready(complete=hooks_completed and not self.unsupported
                        and not (self.interrupted and not self.collection_failed)))
                except (OSError, ValueError) as exc:
                    if not self.channel.failed:
                        self.error("junit_artifact_observation_failed", text(str(exc)), abort=False, category="infrastructure")
            self.emit("session_terminated", {"termination": "interrupted" if self.interrupted and not self.collection_failed else "backend_exited",
                "backend_exit_code": self.exit_code, "reporting_complete": hooks_completed and not self.unsupported,
                "accounting": accounting, "phase_counts": self.phase_counts, "incomplete_ordinals": incomplete})
        finally:
            self.close_artifacts()
            self.channel.close()
