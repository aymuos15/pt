import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import coverage

import coverage_oracle as oracle
from trace_oracle import compare_traces
from test_support import case_root, save_execution


HERE = Path(__file__).resolve().parent


@unittest.skipUnless(sys.version_info[:3] == (3, 12, 12) and coverage.__version__ == "7.17.2", "pins CPython 3.12.12 / coverage 7.17.2")
class CoverageOracleTests(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        self.counter = 0
        self.digest = hashlib.sha256((HERE / "fixtures/coverage_payload.py").read_bytes()).hexdigest()

    def run_case(self, fault="none"):
        self.counter += 1
        cwd, output = self.root / f"work-{self.counter}", self.root / f"output-{self.counter}"
        (cwd / "source").mkdir(parents=True)
        output.mkdir()
        for original, name in (("coverage_payload.py", "source/payload.py"), ("coverage_case.py", "test_case.py"),
                               ("coverage_control.py", "coverage_control.py"), ("coverage_child.py", "coverage_child.py")):
            shutil.copyfile(HERE / "fixtures" / original, cwd / name)
        env = {"PATH": os.defpath, "HOME": str(self.root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(HERE), "PT_CORE_EVENTS": str(output / "events"),
               "PT_COVERAGE_OUTPUT": str(output), "PT_COVERAGE_FAULT": fault}
        command = [sys.executable, "-m", "pytest", "-q", "-p", "pt_reference_observer", "-p", "coverage_control",
                   "--pt-reference-trace=" + str(output / "trace.jsonl"), "test_case.py"]
        result = subprocess.run(command,
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
        save_execution(output / "trace.jsonl", command, result)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((output / "events").read_text(), "child=8\n")
        return cwd, output

    def read(self, value, **options):
        cwd, output = value
        policy = {"data_name": "merged.coverage", "runtime_name": "runtime.json", "source_root": cwd / "source",
                  "sources": {"payload.py": self.digest}, "branch": True, "contexts": ["child", "parent"], "effective_core": "CTracer"}
        return oracle.read_coverage(output, **{**policy, **options})

    def traces_match(self, left, right):
        report = compare_traces(left[1] / "trace.jsonl", right[1] / "trace.jsonl", baseline_exit=0, candidate_exit=0,
                                baseline_effects=["child=8"], candidate_effects=["child=8"])
        self.assertEqual(report["status"], "matched_instrumented_trace_contract", report)

    def test_real_subprocess_branch_and_context_sets_match_across_explicit_root_mapping(self):
        left, right = self.run_case(), self.run_case()
        self.traces_match(left, right)
        first, second = self.read(left), self.read(right)
        report = oracle.compare_coverage(first, second)
        self.assertEqual(report["status"], "matched_declared_coverage_sets", report)
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(first["contexts"], ["child", "parent"])
        self.assertTrue(first["files"]["payload.py"]["arcs"])
        self.assertIn("8", first["files"]["payload.py"]["contexts_by_line"])

    def test_omitted_subprocess_measurement_and_merge_are_detected_with_same_pytest_phases_and_effects(self):
        left = self.run_case()
        first = self.read(left)
        for fault in ("omit_subprocess", "omit_merge"):
            right = self.run_case(fault)
            self.traces_match(left, right)
            report = oracle.compare_coverage(first, self.read(right))
            self.assertEqual(report["status"], "mismatch")
            self.assertIn("files", report["differences"])
            self.assertIn("required_coverage_policy", report["differences"])

    def test_omitted_branch_mode_is_rejected_even_though_application_and_pytest_match(self):
        left, right = self.run_case(), self.run_case("omit_branch")
        self.traces_match(left, right)
        with self.assertRaisesRegex(oracle.CoverageError, "branch policy"):
            self.read(right)

    def test_omitted_child_context_is_not_hidden_by_identical_line_and_arc_sets(self):
        left, right = self.run_case(), self.run_case("omit_context")
        self.traces_match(left, right)
        first, second = self.read(left), self.read(right)
        for key in ("lines", "arcs"):
            self.assertEqual(first["files"]["payload.py"][key], second["files"]["payload.py"][key])
        self.assertEqual(oracle.compare_coverage(first, second)["status"], "mismatch")

    def test_changed_source_foreign_paths_missing_data_and_wrong_effective_core_fail_closed(self):
        result = self.run_case()
        cwd, output = result
        with self.assertRaisesRegex(oracle.CoverageError, "source"):
            self.read(result, sources={"payload.py": "0" * 64})
        with self.assertRaises(oracle.CoverageError):
            self.read(result, source_root=cwd, sources={"source/payload.py": self.digest, "test_case.py": "0" * 64})
        shadow = self.root / "unrelated-source-root"
        shadow.mkdir()
        shutil.copyfile(cwd / "source/payload.py", shadow / "payload.py")
        with self.assertRaisesRegex(oracle.CoverageError, "outside"):
            self.read(result, source_root=shadow)
        with self.assertRaisesRegex(oracle.CoverageError, "effective tracer"):
            self.read(result, effective_core="PyTracer")
        (output / "merged.coverage").unlink()
        with self.assertRaises(FileNotFoundError):
            self.read(result)

    def test_duplicate_runtime_key_and_corrupt_coverage_data_are_not_verified_artifacts(self):
        result = self.run_case()
        output = result[1]
        raw = (output / "runtime.json").read_bytes()
        (output / "runtime.original.json").write_bytes(raw)
        (output / "merged.original.coverage").write_bytes((output / "merged.coverage").read_bytes())
        (output / "runtime.json").write_bytes(raw.replace(b'"branch": true', b'"branch": true, "branch": true'))
        with self.assertRaises(oracle.CoverageError):
            self.read(result)
        (output / "runtime.json").write_bytes(raw)
        (output / "merged.coverage").write_bytes(b"not a coverage database")
        with self.assertRaises(oracle.CoverageError):
            self.read(result)

    def test_two_equally_incomplete_coverage_records_cannot_satisfy_required_sources(self):
        result = self.run_case()
        (result[0] / "source/never_loaded.py").write_text("UNLOADED = 1\n")
        sources = {"payload.py": self.digest, "never_loaded.py": hashlib.sha256(b"UNLOADED = 1\n").hexdigest()}
        checked = self.read(result, sources=sources)
        self.assertEqual(checked["missing_required_files"], ["never_loaded.py"])
        self.assertEqual(oracle.compare_coverage(checked, checked)["status"], "mismatch")


if __name__ == "__main__":
    unittest.main()
