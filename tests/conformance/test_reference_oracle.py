"""Real same-session observer and independent malformed/broken-runner controls."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
CORPUS = HERE.parents[1] / "bench/corpus/serial_core"
sys.path.insert(0, str(HERE))
import trace_oracle as oracle
from test_support import case_root, save_execution
sys.path.pop(0)


@unittest.skipUnless(sys.version_info[:3] == (3, 12, 12), "reference contract pins CPython 3.12.12")
class ReferenceOracleTests(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        self.counter = 0
        self.forge_counter = 0
        self.comparison_counter = 0

    def run_case(self, name="basic", *, broken=None, content=None, directory=None, extra=(), effects=None, bytecode=False, observer=True, junit=False):
        self.counter += 1
        cwd = directory or self.root / f"work-{self.counter}"
        if directory is None:
            if content is None:
                shutil.copytree(CORPUS / "fixtures" / name, cwd)
            else:
                cwd.mkdir()
                (cwd / "test_case.py").write_text(content)
        trace, events = self.root / f"trace-{self.counter}.jsonl", effects or self.root / f"events-{self.counter}.txt"
        environment = {"PATH": os.defpath, "HOME": str(self.root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1",
                       "PYTHONDONTWRITEBYTECODE": "0" if bytecode else "1", "PYTHONPATH": str(HERE), "PT_CORE_EVENTS": str(events)}
        args = ["-p", "duplicate_plugin", "cases.ptcase"] if name == "duplicates" and content is None else ["--doctest-modules", "documentation.py"] if name == "doctest" and content is None else ["."]
        command = [sys.executable, "-m", "pytest", "-q"]
        if observer:
            command += ["-p", "pt_reference_observer", "--pt-reference-trace=" + str(trace)]
        junit_path = self.root / f"junit-{self.counter}.xml"
        if junit:
            command += ["--junitxml=" + str(junit_path)]
        control_args = ["-p", "broken_reference_runner", "--pt-broken-runner=" + broken] if broken else []
        command += control_args
        actual = [*command, *args, *extra]
        result = subprocess.run(actual, cwd=cwd, env=environment, capture_output=True, text=True, timeout=30)
        save_execution(trace, actual, result)
        rows = events.read_text().splitlines() if events.exists() else None
        return {"path": trace, "exit": result.returncode, "effects": rows, "stdout": result.stdout, "stderr": result.stderr,
                "cwd": cwd, "environment": environment, "control_args": control_args}

    def compare(self, left, right):
        report = oracle.compare_traces(left["path"], right["path"], baseline_exit=left["exit"], candidate_exit=right["exit"],
                                     baseline_effects=left["effects"], candidate_effects=right["effects"],
                                     baseline_control_args=left["control_args"], candidate_control_args=right["control_args"])
        self.comparison_counter += 1
        (self.root / f"comparison-{self.comparison_counter}.json").write_text(json.dumps(report, indent=2))
        return report

    def read(self, value):
        return oracle.read_trace(value["path"], value["exit"])

    def mutate(self, value, change):
        rows = [json.loads(line) for line in value["path"].read_text().splitlines()]
        change(rows)
        for index, row in enumerate(rows, 1):
            row["seq"] = index
        self.forge_counter += 1
        path = self.root / f"forged-{self.forge_counter}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_ten_serial_core_cases_have_real_same_session_inventories_and_phase_reports(self):
        declaration = json.loads((CORPUS / "corpus.json").read_text())
        for case in declaration["cases"]:
            with self.subTest(case=case["id"]):
                left, right = self.run_case(case["id"]), self.run_case(case["id"])
                self.assertEqual(left["exit"], case["expected_exit_code"], left["stdout"] + left["stderr"])
                self.assertEqual(right["exit"], case["expected_exit_code"], right["stdout"] + right["stderr"])
                self.assertEqual(left["effects"], case["expected_events"])
                self.assertEqual(self.compare(left, right)["status"], "matched_instrumented_trace_contract")
                self.assertFalse(self.compare(left, right)["confirmatory_eligible"])

    def test_observer_preserves_declared_uninstrumented_core_outcomes_and_external_effects(self):
        declaration = json.loads((CORPUS / "corpus.json").read_text())
        for case in declaration["cases"]:
            observed = []
            for observer in (False, True):
                with self.subTest(case=case["id"], observer=observer):
                    result = self.run_case(case["id"], observer=observer, junit=True)
                    self.assertEqual(result["exit"], case["expected_exit_code"], result["stdout"] + result["stderr"])
                    self.assertEqual(result["effects"], case["expected_events"])
                    raw = (self.root / f"junit-{self.counter}.xml").read_bytes()
                    self.assertLessEqual(len(raw), 4 * 1024 * 1024)
                    rows = []
                    for index, item in enumerate(ET.fromstring(raw).findall(".//testcase")):
                        adverse = [child for child in item if child.tag in ("failure", "error", "skipped")]
                        self.assertLessEqual(len(adverse), 1)
                        message = adverse[0].get("message", "") + "\n" + "".join(adverse[0].itertext()) if adverse else ""
                        marker = case["junit"][index]["marker"] if index < len(case["junit"]) else ""
                        self.assertIn(marker, message)
                        rows.append({"name": item.get("name"), "kind": adverse[0].tag if adverse else "passed", "marker": marker})
                    self.assertEqual(rows, case["junit"])
                    observed.append(rows)
            self.assertEqual(observed[0], observed[1])

    def test_setup_teardown_errors_strict_xpass_skip_and_xfail_are_distinct_raw_phases(self):
        result = self.run_case("phases")
        rows = self.read(result)["normalized"]["phases"]
        by_ordinal = {ordinal: [(row["when"], row["outcome"], row["wasxfail"]) for row in rows if row["ordinal"] == ordinal] for ordinal in range(6)}
        self.assertEqual(by_ordinal[1], [("setup", "failed", None), ("teardown", "passed", None)])
        self.assertEqual(by_ordinal[2], [("setup", "passed", None), ("call", "passed", None), ("teardown", "failed", None)])
        self.assertEqual(by_ordinal[3][1], ("call", "failed", None))
        self.assertEqual(by_ordinal[4], [("setup", "skipped", None), ("teardown", "passed", None)])
        self.assertEqual(by_ordinal[5][1], ("call", "skipped", "PT_CORE_EXPECTED_FAILURE"))

    def test_duplicate_node_ids_remain_distinct_occurrences(self):
        result = self.run_case("duplicates")
        trace = self.read(result)["normalized"]
        self.assertEqual([item["ordinal"] for item in trace["collected"]], [0, 1, 2])
        self.assertEqual(trace["collected"][0]["nodeid"], trace["collected"][1]["nodeid"])
        self.assertEqual(len(trace["phases"]), 9)

    def test_collection_error_is_a_backend_interruption_not_an_observer_error(self):
        result = self.run_case("collection_error")
        value = self.read(result)["normalized"]
        self.assertEqual(result["exit"], 2)
        self.assertTrue(value["interruptions"])
        self.assertEqual(value["phases"], [])
        self.assertTrue(any(report["outcome"] == "failed" for report in value["collection_reports"]))

    def test_no_tests_and_collect_only_never_invent_executed_occurrences(self):
        empty = self.run_case("no_tests")
        self.assertEqual(empty["exit"], 5)
        self.assertEqual(self.read(empty)["normalized"]["selected"], [])
        collected = self.run_case(extra=["--collect-only"])
        self.assertEqual(collected["exit"], 0)
        value = self.read(collected)["normalized"]
        self.assertTrue(value["collect_only"])
        self.assertEqual(value["phases"], [])
        self.assertEqual(len(value["selected"]), 4)

    def test_declared_selection_partition_preserves_all_deselected_occurrences(self):
        result = self.run_case(extra=["-k", "test_first"])
        value = self.read(result)["normalized"]
        self.assertEqual(value["selected"], [0])
        self.assertEqual(value["deselected"], [1, 2, 3])
        self.assertEqual(len(value["phases"]), 3)

    def test_fail_fast_preserves_selected_but_not_run_occurrences(self):
        code = "def test_first(): assert False, 'PT_CORE_FIRST_FAILURE'\ndef test_second(): pass\n"
        result = self.run_case(content=code, extra=["-x"])
        value = self.read(result)["normalized"]
        self.assertEqual(result["exit"], 1)
        self.assertEqual(value["selected"], [0, 1])
        self.assertEqual(value["completed"], [0])
        self.assertEqual(value["not_run"], [1])
        self.assertIn("1 failures", value["stop_reason"])
        forged = self.mutate(result, lambda rows: rows[0]["payload"].update(maxfail=0))
        with self.assertRaisesRegex(oracle.TraceError, "fail-fast"):
            oracle.read_trace(forged, 1)

    def test_real_interrupt_retains_incomplete_phases_and_unstarted_work(self):
        code = "def test_first(): raise KeyboardInterrupt('PT_CORE_INTERRUPT')\ndef test_second(): pass\n"
        result = self.run_case(content=code)
        value = self.read(result)["normalized"]
        self.assertEqual(result["exit"], 2, result["stdout"] + result["stderr"])
        self.assertEqual(value["started"], [0])
        self.assertEqual(value["completed"], [])
        self.assertEqual(value["incomplete"], [0])
        self.assertEqual(value["not_run"], [1])
        self.assertTrue(value["interruptions"])

    def test_warning_as_error_and_fd_capture_are_preserved_not_flattened_into_pass_counts(self):
        code = "import os,warnings\ndef test_one():\n    os.write(1,b'PT_CORE_STDOUT\\n')\n    os.write(2,b'PT_CORE_STDERR\\n')\n    warnings.warn('PT_CORE_WARNING',UserWarning)\n"
        result = self.run_case(content=code, extra=["-W", "error::UserWarning"])
        value = self.read(result)["normalized"]
        self.assertEqual(result["exit"], 1)
        call = next(phase for phase in value["phases"] if phase["when"] == "call")
        self.assertEqual(call["outcome"], "failed")
        self.assertIn("PT_CORE_WARNING", call["failure_message"])
        self.assertEqual(call["sections"], [["Captured stdout call", "PT_CORE_STDOUT\n"], ["Captured stderr call", "PT_CORE_STDERR\n"]])
        path = self.mutate(result, lambda rows: next(row for row in rows if row["kind"] == "phase" and row["payload"]["when"] == "call")["payload"].update(sections=[]))
        report = oracle.compare_traces(result["path"], path, baseline_exit=1, candidate_exit=1)
        self.assertIn("phases", report["differences"])

    def test_exact_user_arguments_are_compared_and_test_control_exclusions_are_explicit(self):
        left, right = self.run_case(), self.run_case(extra=["--tb=short"])
        self.assertEqual(self.compare(left, right)["differences"], ["pytest_argv"])
        with self.assertRaisesRegex(oracle.TraceError, "exactly once"):
            oracle.compare_traces(left["path"], right["path"], baseline_exit=0, candidate_exit=0, candidate_control_args=["--not-present"])

    def test_unstable_baseline_effects_are_uncertain_and_cannot_qualify_the_candidate(self):
        code = "import os\nfrom pathlib import Path\ndef test_one(): Path(os.environ['PT_CORE_EVENTS']).write_text(str(os.getpid())+'\\n')\n"
        observations = [self.run_case(content=code) for _ in range(3)]
        values = [{key: value[key] for key in ("path", "exit", "effects", "control_args")} for value in observations]
        report = oracle.compare_against_references(values[:2], values[2])
        (self.root / "baseline-stability.json").write_text(json.dumps(report, indent=2))
        self.assertEqual(report["status"], "baseline_uncertain")
        self.assertIsNone(report["candidate_comparison"])
        self.assertFalse(report["confirmatory_eligible"])

    def test_stable_references_keep_a_candidate_mismatch_and_reject_untyped_effect_claims(self):
        observations = [self.run_case("imports") for _ in range(2)] + [self.run_case("imports", broken="skip_call")]
        values = [{key: value[key] for key in ("path", "exit", "effects", "control_args")} for value in observations]
        report = oracle.compare_against_references(values[:2], values[2])
        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(report["candidate_comparison"]["differences"], ["declared_effect_observations"])
        for effects in ({"verified": True}, [True], [1], "asserted"):
            with self.assertRaises(oracle.TraceError):
                oracle.compare_traces(values[0]["path"], values[1]["path"], baseline_exit=0, candidate_exit=0,
                                      baseline_effects=effects, candidate_effects=effects)

    def test_unicode_node_ids_and_collection_registered_hook_wrappers_remain_exact(self):
        values = []
        for index in (1, 2):
            cwd = self.root / f"unicode-{index}"
            cwd.mkdir()
            (cwd / "pytest.ini").write_text("[pytest]\ndisable_test_id_escaping_and_forfeit_all_rights_to_community_support = True\n")
            (cwd / "test_é.py").write_text("import pytest\n@pytest.mark.parametrize('value',[1],ids=['🧪'])\ndef test_é(value): assert value==1\n")
            (cwd / "conftest.py").write_text(
                "import os,pytest\nfrom pathlib import Path\n"
                "def event(value):\n    with Path(os.environ['PT_CORE_EVENTS']).open('a') as f: f.write(value+'\\n')\n"
                "class Late:\n    @pytest.hookimpl(hookwrapper=True)\n    def pytest_runtest_call(self,item):\n        event('before')\n        yield\n        event('after')\n"
                "def pytest_collection_modifyitems(config,items):\n    event('inventory '+str(len(items)))\n    config.pluginmanager.register(Late(),name='late-control')\n")
            values.append(self.run_case(directory=cwd))
        self.assertEqual(values[0]["effects"], ["inventory 1", "before", "after"])
        normalized = self.read(values[0])["normalized"]
        self.assertEqual(normalized["collected"][0]["nodeid"], "test_é.py::test_é[🧪]")
        self.assertEqual(self.compare(*values)["status"], "matched_instrumented_trace_contract")

    def test_broken_skipped_call_with_unchanged_phase_counts_is_detected_by_external_effects(self):
        left, right = self.run_case("imports"), self.run_case("imports", broken="skip_call")
        self.assertEqual(left["exit"], right["exit"])
        self.assertEqual(self.read(left)["normalized"]["phases"], self.read(right)["normalized"]["phases"])
        self.assertEqual(self.compare(left, right)["differences"], ["declared_effect_observations"])

    def test_broken_skipped_setup_and_teardown_do_not_match_reference(self):
        content = ("import os\nfrom pathlib import Path\nimport pytest\n"
                   "def event(value):\n    with Path(os.environ['PT_CORE_EVENTS']).open('a') as stream: stream.write(value+'\\n')\n"
                   "@pytest.fixture(autouse=True)\ndef fixture():\n    event('setup')\n    yield\n    event('teardown')\n"
                   "def test_one(): event('one')\ndef test_two(): event('two')\n")
        for broken in ("skip_setup", "skip_teardown"):
            left, right = self.run_case(content=content), self.run_case(content=content, broken=broken)
            self.assertEqual(left["exit"], 0)
            self.assertEqual(self.compare(left, right)["status"], "mismatch")

    def test_broken_duplicate_drop_is_not_a_valid_collection_partition(self):
        result = self.run_case("duplicates", broken="drop_duplicate")
        with self.assertRaisesRegex(oracle.TraceError, "partition"):
            self.read(result)

    def test_relaxed_strict_xpass_is_detected_even_with_same_overall_exit(self):
        left, right = self.run_case("phases"), self.run_case("phases", broken="relax_strict_xpass")
        self.assertEqual(left["exit"], 1)
        self.assertEqual(right["exit"], 1)
        self.assertIn("phases", self.compare(left, right)["differences"])

    def test_hidden_collection_error_does_not_turn_into_equivalent_no_tests(self):
        left, right = self.run_case("collection_error"), self.run_case("collection_error", broken="hide_collection_error")
        self.assertEqual(left["exit"], 2)
        self.assertEqual(self.compare(left, right)["status"], "mismatch")

    def test_suppressed_warnings_are_detected_despite_identical_pass_counts(self):
        code = "import warnings\ndef test_warning(): warnings.warn('PT_CORE_WARNING', UserWarning)\n"
        left, right = self.run_case(content=code), self.run_case(content=code, broken="suppress_warnings")
        self.assertEqual(left["exit"], right["exit"])
        self.assertIn("warnings", self.compare(left, right)["differences"])

    def test_extra_preflight_collection_is_visible_in_import_sentinels(self):
        left = self.run_case("imports")
        cwd = self.root / "preflight"
        shutil.copytree(CORPUS / "fixtures/imports", cwd)
        events = self.root / "preflight.events"
        environment = {**left["environment"], "PT_CORE_EVENTS": str(events)}
        collected = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only", "."], cwd=cwd, env=environment, capture_output=True, timeout=30)
        self.assertEqual(collected.returncode, 0)
        right = self.run_case("imports", directory=cwd, effects=events)
        self.assertEqual(right["exit"], 0)
        self.assertEqual(self.compare(left, right)["differences"], ["declared_effect_observations"])

    def test_stale_same_size_same_mtime_bytecode_is_detected_by_loaded_value_effect(self):
        results = []
        for label, stale in (("current", False), ("stale", True)):
            cwd = self.root / label
            cwd.mkdir()
            source = cwd / "loaded.py"
            source.write_text("VALUE = 1\n")
            before = source.stat()
            if stale:
                py_compile.compile(str(source), cfile=str(Path(importlib.util.cache_from_source(str(source)))), doraise=True,
                                   invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            source.write_text("VALUE = 2\n")
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            (cwd / "test_loaded.py").write_text("import os,loaded\nfrom pathlib import Path\ndef test_value(): Path(os.environ['PT_CORE_EVENTS']).write_text(str(loaded.VALUE)+'\\n')\n")
            results.append(self.run_case(directory=cwd, bytecode=True))
        self.assertEqual([result["exit"] for result in results], [0, 0])
        self.assertEqual(results[0]["effects"], ["2"])
        self.assertEqual(results[1]["effects"], ["1"])
        self.assertEqual(self.compare(*results)["differences"], ["declared_effect_observations"])

    def test_missing_duplicate_or_reordered_phase_reports_fail_after_rebasing_sequences_and_counts(self):
        result = self.run_case()
        for mode in ("missing", "duplicate", "order"):
            def change(rows):
                indices = [index for index, row in enumerate(rows) if row["kind"] == "phase"]
                if mode == "missing":
                    rows.pop(indices[2])
                    rows[-1]["payload"]["reports"] -= 1
                elif mode == "duplicate":
                    rows.insert(indices[2], copy.deepcopy(rows[indices[2]]))
                    rows[-1]["payload"]["reports"] += 1
                else:
                    rows[indices[0]]["payload"], rows[indices[1]]["payload"] = rows[indices[1]]["payload"], rows[indices[0]]["payload"]
            path = self.mutate(result, change)
            with self.subTest(mode=mode), self.assertRaises(oracle.TraceError):
                oracle.read_trace(path, result["exit"])

    def test_missing_terminal_lost_events_mixed_sessions_and_actual_exit_mismatch_fail(self):
        result = self.run_case()
        original = result["path"].read_bytes()
        path = self.root / "bad.jsonl"
        for raw in (b"\n".join(original.splitlines()[:-1]) + b"\n", original.rstrip(b"\n"), original.replace(b'"seq": 2,', b'"seq": 1,', 1)):
            path.write_bytes(raw)
            with self.assertRaises(oracle.TraceError):
                oracle.read_trace(path, result["exit"])
        with self.assertRaises(oracle.TraceError):
            oracle.read_trace(result["path"], 1)
        path = self.mutate(result, lambda rows: rows[1].update(session="0" * 32))
        with self.assertRaises(oracle.TraceError):
            oracle.read_trace(path, result["exit"])

    def test_typed_closed_shapes_nonfinite_values_and_zero_success_contradictions_fail(self):
        result = self.run_case()
        for mutate in (lambda rows: rows[0].update(schema_version=True), lambda rows: rows[0]["payload"].update(python=[3, 12.0, 12]),
                       lambda rows: rows[0].update(extra=1), lambda rows: rows[-1]["payload"].update(reports=True),
                       lambda rows: next(row for row in rows if row["kind"] == "phase")["payload"].update(duration=float("nan")),
                       lambda rows: next(row for row in rows if row["kind"] == "phase")["payload"].update(outcome="failed")):
            path = self.mutate(result, mutate)
            with self.assertRaises(oracle.TraceError):
                oracle.read_trace(path, result["exit"])

    def test_undocumented_failure_exit_lost_inventory_utf16_and_duplicate_json_keys_fail(self):
        result = self.run_case()
        raw = result["path"].read_bytes()
        path = self.root / "bad-encoding.jsonl"
        for bad in (raw.decode().encode("utf-16"), raw.replace(b'"seq": 1,', b'"seq": 1, "seq": 1,', 1)):
            path.write_bytes(bad)
            with self.assertRaises(oracle.TraceError):
                oracle.read_trace(path, 0)
        for status in (1, 2, 3, 4, 5, 99):
            forged = self.mutate(result, lambda rows: rows[-1]["payload"].update(exit_status=status))
            with self.subTest(exit=status), self.assertRaises(oracle.TraceError):
                oracle.read_trace(forged, status)
        forged = self.mutate(result, lambda rows: rows.__setitem__(slice(None), [row for row in rows if row["kind"] != "inventory"]))
        with self.assertRaises(oracle.TraceError):
            oracle.read_trace(forged, 0)

    def test_canonical_event_schema_accepts_actual_closed_payloads(self):
        schema = json.loads((HERE / "reference-event-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        results = [self.run_case(), self.run_case("phases"), self.run_case("collection_error"),
                   self.run_case(content="import warnings\ndef test_one(): warnings.warn('PT_CORE_SCHEMA_WARNING')\n"),
                   self.run_case(content="def test_one(): raise KeyboardInterrupt('PT_CORE_SCHEMA_INTERRUPT')\n")]
        kinds = set()
        for result in results:
            for event in self.read(result)["events"]:
                validator.validate(event)
                kinds.add(event["kind"])
        self.assertTrue({"start", "inventory", "phase", "warning", "interruption", "terminal"} <= kinds)
        event = json.loads(results[0]["path"].read_text().splitlines()[0])
        event["payload"]["extra"] = "not allowed"
        self.assertTrue(list(validator.iter_errors(event)))

    def test_bounded_reader_refuses_oversize_traces_events_items_and_nonregular_files(self):
        result = self.run_case()
        for name, value in (("MAX_TRACE_BYTES", 1), ("MAX_EVENT_BYTES", 1), ("MAX_EVENTS", 2), ("MAX_ITEMS", 1)):
            with mock.patch.object(oracle, name, value), self.assertRaises(oracle.TraceError):
                self.read(result)
        (self.root / "linked.jsonl").symlink_to(result["path"])
        os.mkfifo(self.root / "fifo.jsonl")
        for path in (self.root / "linked.jsonl", self.root / "fifo.jsonl"):
            with self.assertRaises((OSError, oracle.TraceError)):
                oracle.read_trace(path, 0)

    def test_existing_trace_path_is_not_overwritten_or_reused(self):
        result = self.run_case()
        raw = result["path"].read_bytes()
        rerun = subprocess.run([sys.executable, "-m", "pytest", "-p", "pt_reference_observer", "--pt-reference-trace=" + str(result["path"]), "."],
                               cwd=result["cwd"], env=result["environment"], capture_output=True, timeout=30)
        self.assertNotEqual(rerun.returncode, 0)
        self.assertEqual(result["path"].read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
