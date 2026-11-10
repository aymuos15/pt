"""Synthetic plan/failure checks; real plugin execution is a separate retained run."""

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_support import case_root


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ecosystem_plan_under_test", ROOT / "bench/corpus/serial_ecosystem/check_references.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
SOURCE = driver.HERE


class SyntheticEcosystemReferencePlanTests(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.source = self.root / "source"
        shutil.copytree(SOURCE, self.source, ignore=shutil.ignore_patterns("__pycache__"))
        self.output = self.root / "run"
        self.declaration = json.loads((self.source / "profile.json").read_text())
        self.tools = driver._module("ecosystem_test_outer_tools", ROOT / "bench/corpus/serial_core/materialize.py")
        self.calls = []
        self.verify_calls = 0
        self.oracle = SimpleNamespace(read_trace=self.read_trace, compare_traces=self.compare)
        self.preparation = SimpleNamespace(verify_prefix=lambda *args: {"status": "matched_exact_prefix", "synthetic_test_control": True})
        self.bases = SimpleNamespace(verify_preparation=lambda *args: ({"executable": {"path": "bin/python3.12"}}, [],
                                         [{"status": "matched_exact_prefix", "synthetic_test_control": True}] * 2))

    def read_trace(self, path, code):
        value = json.loads(Path(path).read_text())
        return {"trace_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                "normalized": {"completed": list(range(value["occurrences"])), "phases": [None] * value["phases"]}}

    def compare(self, *args, **kwargs):
        different = kwargs["baseline_effects"] != kwargs["candidate_effects"]
        return {"status": "mismatch" if different else "matched_instrumented_trace_contract",
                "differences": ["declared_effect_observations"] if different else [], "synthetic_test_control": True}

    def command(self, output, name, argv, cwd, env):
        self.calls.append({"name": name, "argv": argv, "env": env})
        if name.startswith("venv-"):
            venv = Path(argv[-1])
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").write_bytes(b"explicit synthetic interpreter, never executed")
            site = venv / "lib/python3.12/site-packages"
            (site / "synthetic.dist-info").mkdir(parents=True)
            (site / "package.py").write_text("same installed synthetic bytes\n")
            (site / "synthetic.dist-info/RECORD").write_text("synthetic path-specific " + name)
        elif name.startswith("runtime-"):
            value = {"python": [3, 12, 12], "packages": [list(row) for row in sorted(driver.VERSIONS.items())], "plugins": driver.PLUGINS}
            return {"returncode": 0, "synthetic_test_control": True}, {"stdout": json.dumps(value).encode(), "stderr": b""}
        elif name.startswith(("env-", "control-")):
            case = next(case for case in self.declaration["cases"] if (case["id"] in name or
                any((cwd / filename).exists() for filename in {"async_cases": ["test_async.py"], "property_cases": ["test_properties.py"],
                                                              "database_cases": ["test_database.py"]}[case["id"]])))
            subset = argv[-1] != "."
            fault = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--pt-broken-runner=")), None)
            events = copy.deepcopy(case["expected_events"])
            if events is None:
                events = ["property import", "boolean False", "boolean True", "pair False False", "pair False True", "pair True False", "pair True True"]
            if subset:
                events = {"async_cases": ["async import", "async setup", "async awaited body", "async release"],
                          "property_cases": ["property import", "boolean False", "boolean True"],
                          "database_cases": ["database import", "database setup", "database write", "database release"]}[case["id"]]
            if fault == "skip_call":
                events = [event for event in events if event not in ("async awaited body", "boolean False", "boolean True")]
            elif fault == "skip_teardown":
                events = events[:-1]
                (cwd / "database.lease").write_text("explicit synthetic missing cleanup")
            (cwd / "events.txt").write_text("\n".join(events) + "\n")
            expectations = case["junit"] if not subset else [{"name": "control", "kind": "passed", "marker": ""}]
            xml = ET.Element("testsuites")
            for expectation in expectations:
                item = ET.SubElement(xml, "testcase", name=expectation["name"])
                if expectation["kind"] != "passed":
                    ET.SubElement(item, expectation["kind"], message=expectation["marker"])
            (cwd / "pytest-junit.xml").write_bytes(ET.tostring(xml))
            trace = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--pt-reference-trace=")), None)
            if trace is not None:
                Path(trace).write_text(json.dumps({"synthetic_test_control": True, "occurrences": 1 if subset else case["occurrences"],
                                                  "phases": 3 if subset else case["phases"]}))
            return {"returncode": 0 if subset else case["exit"], "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}
        return {"returncode": 0, "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}

    @contextmanager
    def synthetic(self, command=None, compare=None):
        real_loader = driver._module

        def load(name, path):
            if name == "ecosystem_outer_process_tools":
                return self.tools
            if name == "ecosystem_private_interpreter_tools":
                return self.preparation
            if name == "ecosystem_private_base_checks":
                return self.bases
            if name == "frozen_ecosystem_trace_reader":
                return self.oracle
            return real_loader(name, path)

        with (mock.patch.object(driver, "HERE", self.source), mock.patch.object(driver, "_module", side_effect=load),
              mock.patch.object(self.tools, "_command", side_effect=command or self.command),
              mock.patch.object(driver.shutil, "which", return_value="/explicit-synthetic/uv"),
              mock.patch.object(driver.subprocess, "check_output", return_value=str(self.root)),
              mock.patch.object(self.oracle, "compare_traces", side_effect=compare or self.compare)):
            yield

    def produce(self, **kwargs):
        return driver.check(self.prepared, self.output, execute=True, **kwargs)

    def assert_ledger(self, report):
        self.assertEqual(len(report["planned_requests"]), 24)
        self.assertEqual(len({row["id"] for row in report["planned_requests"]}), 24)
        self.assertFalse(report["confirmatory_eligible"])
        self.assertTrue(all(value is None for value in report["qualification"].values()))

    def test_complete_synthetic_plan_retains_all_adverse_returns_and_all_24_units(self):
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "matched_finite_ecosystem_references_and_detected_controls_unqualified", report["errors"])
        self.assertEqual(sum(row["observation"]["returncode"] == 1 for row in report["planned_requests"]), 6)
        self.assertTrue(all(row["observation"]["synthetic_test_control"] for row in report["planned_requests"]))
        self.assertEqual(len(list(self.output.glob("retained-work-*"))), 24)
        self.assertFalse((self.output / "work").exists())
        broken = [row for row in report["planned_requests"] if row["layer"] == "broken"]
        self.assertEqual(len(broken), 3)
        self.assertEqual(broken[-1]["cleanup"]["status"], "cleanup_mismatch")

    def test_requires_permission_new_output_and_unmodified_exact_dependency_lock(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            driver.check(self.prepared, self.output)
        lock = self.source / "uv.lock"
        original = lock.read_bytes()
        lock.write_bytes(original.replace(b'8.4.2', b'8.4.1'))
        with self.synthetic(), self.assertRaisesRegex(ValueError, "lock differs"):
            self.produce()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])
        lock.write_bytes(original)
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with self.synthetic(), self.assertRaises(FileExistsError):
            self.produce()
        self.assertEqual((self.output / "user-work").read_text(), "keep")

    def test_boolean_work_counts_and_weakened_fault_plan_are_rejected_before_setup(self):
        original = copy.deepcopy(self.declaration)
        for mode in ("boolean", "fault"):
            value = copy.deepcopy(original)
            if mode == "boolean":
                value["cases"][0]["occurrences"] = True
            else:
                value["controls"][0]["fault"] = "suppress_warnings"
            (self.source / "profile.json").write_text(json.dumps(value))
            with self.synthetic(), self.assertRaises(ValueError):
                self.produce()
        self.assertEqual(self.calls, [])

    def test_lost_first_request_return_stays_unknown_despite_committed_junit_and_effects(self):
        def lost(*args):
            result = self.command(*args)
            if args[1].startswith("env-"):
                raise OSError("explicit synthetic loss after writing request artifacts")
            return result

        with self.synthetic(command=lost):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_requests"][0]["status"], "unknown_execution_return")
        self.assertIsNone(report["planned_requests"][0]["observation"])
        self.assertTrue(all(row["status"] == "not_run_prior_failure" for row in report["planned_requests"][1:]))
        self.assertTrue((self.output / "work/pytest-junit.xml").exists())
        self.assertEqual(sum(row["name"].startswith("env-") for row in self.calls), 1)

    def test_unequal_repeated_references_remain_baseline_uncertainty_without_retry(self):
        def unstable(*args, **kwargs):
            return {"status": "mismatch", "differences": ["phases"], "synthetic_test_control": True}

        with self.synthetic(compare=unstable):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "baseline_uncertain")
        self.assertEqual(sum(row["status"] == "matched_declared_development_observation" for row in report["planned_requests"]), 3)
        self.assertEqual(sum(row["status"] == "not_run_prior_failure" for row in report["planned_requests"]), 21)

    def test_explicit_online_preparation_is_first_environment_only_and_never_allows_sdist_builds(self):
        with self.synthetic():
            report = self.produce(prepare_artifacts=True)
        self.assert_ledger(report)
        installs = [row for row in self.calls if row["name"].startswith("install-")]
        self.assertNotIn("--offline", installs[0]["argv"])
        self.assertIn("--offline", installs[1]["argv"])
        self.assertTrue(all("--locked" in row["argv"] and "--no-build" in row["argv"] for row in installs))
        self.assertTrue(all("PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in row["env"] for row in self.calls))

    def test_finite_property_domain_check_does_not_sort_away_the_raw_effect_comparison_order(self):
        values = ["property import", "boolean False", "boolean True", "pair False False", "pair False True", "pair True False", "pair True True"]
        driver._property_effects(values)
        reordered = [values[0], *reversed(values[1:])]
        driver._property_effects(reordered)  # Domain coverage alone is not ordering evidence.
        self.assertEqual(self.compare(None, None, baseline_effects=values, candidate_effects=reordered)["status"], "mismatch")
        with self.assertRaises(ValueError):
            driver._property_effects(values[:-1] + [values[1]])

    def test_installed_mutation_is_not_excluded_as_an_environment_path_difference(self):
        def mutate(*args):
            result = self.command(*args)
            if args[1] == "env-1-database_cases-reference-2":
                (self.output / "environment-1/lib/python3.12/site-packages/unlisted.py").write_text("changed")
            return result

        with self.synthetic(command=mutate):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertTrue(any("installed files changed" in row["error"] for row in report["errors"]))
        self.assertFalse(any(row["name"] == "venv-2" for row in self.calls))


if __name__ == "__main__":
    unittest.main()
