"""Synthetic failure controls for the explicit pinned Flask assessment tool."""

from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "bench/corpus/assessments/check_flask_49943b5.py"
spec = importlib.util.spec_from_file_location("flask_assessment_controls", PATH)
assessment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assessment)
SUPPORTED = sys.platform == "linux" and platform.machine() == "x86_64" and sys.version_info[:3] == (3, 12, 12)


@unittest.skipUnless(SUPPORTED, "assessment explicitly pins Linux x86-64 CPython 3.12.12")
class FlaskAssessmentControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "run"
        self.tools = assessment._materializer()
        self.calls = []
        self.codes = {1: 0, 2: 0}

    def git(self, source, *args):
        if args == ("rev-parse", "HEAD"):
            return assessment.REVISION
        if args == ("rev-parse", "HEAD^{tree}"):
            return assessment.TREE
        return ""

    def fake_command(self, output, name, argv, cwd, env):
        self.calls.append((name, argv))
        if name == "archive":
            archive = output / "source.tar"
            with tarfile.open(archive, "w") as tar:
                raw = b"explicit synthetic candidate input; no application executed\n"
                info = tarfile.TarInfo("input.txt")
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
        elif name.startswith(("builder-", "venv-")):
            directory = Path(argv[-1])
            (directory / "bin").mkdir(parents=True)
            (directory / "bin/python").write_bytes(b"explicit synthetic interpreter bytes")
            site = directory / "lib/python3.12/site-packages"
            (site / "package.dist-info").mkdir(parents=True)
            (site / "package.py").write_text("same synthetic installed bytes\n")
            (site / "package.dist-info/RECORD").write_text("environment-specific " + name)
        elif name.startswith("wheel-"):
            directory = output / ("wheels-" + name.split("-")[1])
            (directory / "flask-3.2.0.dev0-py3-none-any.whl").write_bytes(b"explicit synthetic wheel, never installed")
        elif name.startswith("runtime-") and not name.startswith("runtime-deps-"):
            value = {"python": [3, 12, 12], "pytest": "8.4.2", "flask": "3.2.0.dev0", "pytest11": [], "distributions": []}
            return {"returncode": 0, "synthetic_test_control": True}, {"stdout": json.dumps(value).encode(), "stderr": b""}
        elif name.startswith("pytest-"):
            index = int(name.split("-")[1])
            child = '<failure message="EXPLICIT_SYNTHETIC_FAILURE"/>' if self.codes[index] else ""
            (output / f"junit-{index}.xml").write_text('<testsuites><testsuite><testcase classname="synthetic" name="same">' + child +
                                                       '</testcase><testcase classname="synthetic" name="same"/></testsuite></testsuites>')
            return {"returncode": self.codes[index], "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}
        return {"returncode": 0, "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}

    @contextmanager
    def synthetic(self, effect=None):
        with (mock.patch.object(assessment, "_git", side_effect=self.git),
              mock.patch.object(assessment, "_materializer", return_value=self.tools),
              mock.patch.object(assessment.shutil, "which", return_value="/explicit-synthetic/uv"),
              mock.patch.object(assessment.subprocess, "check_output", return_value=str(self.root).encode()),
              mock.patch.object(self.tools, "_command", side_effect=effect or self.fake_command)):
            yield

    def produce(self, **kwargs):
        return assessment.assess(self.source, self.output, execute=True, **kwargs)

    def assert_ledger(self, report):
        self.assertEqual([row["environment"] for row in report["planned_runs"]], [1, 2])
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(len(report["qualification"]), 8)
        self.assertTrue(all(value is None for value in report["qualification"].values()))

    def test_requires_explicit_execution_exact_pristine_revision_and_separate_outputs(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            assessment.assess(self.source, self.output)
        with self.assertRaisesRegex(ValueError, "outside"):
            assessment.assess(self.source, self.source / "output", execute=True)
        with self.synthetic(), mock.patch.object(assessment, "_git", return_value="wrong"), self.assertRaisesRegex(ValueError, "pristine"):
            self.produce()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_changed_lock_refuses_any_install_build_or_execution(self):
        wrong = {**assessment.LOCKS, "flask-49943b5-build.requirements.txt": "0" * 64}
        with self.synthetic(), mock.patch.object(assessment, "LOCKS", wrong), self.assertRaisesRegex(ValueError, "frozen bytes"):
            self.produce()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_two_complete_synthetic_materializations_preserve_duplicates_and_all_nulls(self):
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "reproduced_pytest_only_observations_unqualified")
        self.assertEqual(report["compared_installed_files"], 1)
        self.assertEqual(len(report["builds"]), 2)
        self.assertTrue(all(len(row["junit"]) == 2 for row in report["planned_runs"]))
        self.assertTrue(all(row["observation"]["synthetic_test_control"] for row in report["planned_runs"]))
        self.assertEqual(json.loads((self.output / "result.json").read_text()), report)

    def test_online_preparation_is_explicit_and_only_first_environment_dependencies_can_download(self):
        with self.synthetic():
            self.produce(prepare_artifacts=True)
        commands = dict(self.calls)
        for name in ("build-deps-1", "runtime-deps-1"):
            self.assertNotIn("--offline", commands[name])
            self.assertIn("--require-hashes", commands[name])
            self.assertIn("--only-binary", commands[name])
        for name in ("build-deps-2", "runtime-deps-2", "wheel-1", "wheel-2", "install-flask-1", "install-flask-2"):
            self.assertIn("--offline", commands[name])

    def test_known_test_failures_are_not_called_passes_or_erased_by_reproducibility(self):
        self.codes = {1: 1, 2: 1}
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual([row["observation"]["returncode"] for row in report["planned_runs"]], [1, 1])
        self.assertEqual([row["junit"][0]["kind"] for row in report["planned_runs"]], ["failure", "failure"])
        self.assertTrue(report["repeated_reference_outcomes_match"])
        self.assertEqual(sum(name.startswith("pytest-") for name, argv in self.calls), 2)

    def test_different_reference_outcomes_remain_an_explicit_mismatch(self):
        self.codes = {1: 0, 2: 1}
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "reference_outcomes_differ_unqualified")
        self.assertFalse(report["repeated_reference_outcomes_match"])

    def test_lost_pytest_return_is_not_recovered_from_complete_looking_junit(self):
        def lost(*args):
            result = self.fake_command(*args)
            if args[1] == "pytest-1":
                raise OSError("explicit synthetic return loss after artifact creation")
            return result

        with self.synthetic(lost):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_runs"][0]["status"], "unknown_execution_return")
        self.assertIsNone(report["planned_runs"][0]["observation"])
        self.assertTrue((self.output / "junit-1.xml").exists())
        self.assertEqual(report["planned_runs"][1]["status"], "not_run_prior_failure")
        self.assertEqual(sum(name.startswith("pytest-") for name, argv in self.calls), 1)

    def test_unlisted_installed_file_mutation_stops_later_work_and_keeps_actual_return(self):
        def mutate(*args):
            result = self.fake_command(*args)
            if args[1] == "pytest-1":
                (self.output / "environment-1/lib/python3.12/site-packages/unlisted.py").write_text("changed")
            return result

        with self.synthetic(mutate):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_runs"][0]["observation"]["returncode"], 0)
        self.assertEqual(report["planned_runs"][1]["status"], "not_run_prior_failure")
        self.assertIn("site-packages", report["errors"][0]["error"])

    def test_different_builds_are_not_path_normalized_or_used_for_partial_test_work(self):
        def mutate(*args):
            result = self.fake_command(*args)
            if args[1] == "wheel-2":
                (self.output / "wheels-2/flask-3.2.0.dev0-py3-none-any.whl").write_bytes(b"different")
            return result

        with self.synthetic(mutate):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(len(report["builds"]), 2)
        self.assertNotEqual(report["builds"][0]["sha256"], report["builds"][1]["sha256"])
        self.assertFalse(any(name.startswith("pytest-") for name, argv in self.calls))

    def test_existing_evidence_is_never_repaired_or_overwritten(self):
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with self.synthetic(), self.assertRaises(FileExistsError):
            self.produce()
        self.assertEqual((self.output / "user-work").read_text(), "keep")
        self.assertEqual(self.calls, [])

    def test_junit_retains_adverse_occurrences_and_rejects_ambiguous_entity_payloads(self):
        expected = [{"classname": "", "name": "same", "kind": "passed", "message": ""},
                    {"classname": "", "name": "same", "kind": "error", "message": "setup failure"}]
        raw = b'<testsuites><testcase name="same"/><testcase name="same"><error message="setup failure"/></testcase></testsuites>'
        self.assertEqual(assessment._junit(raw), expected)
        for bad in (b'<!DOCTYPE x [<!ENTITY y "bad">]><testsuites/>', b'<testsuites><testcase><failure/><error/></testcase></testsuites>'):
            with self.assertRaises(ValueError):
                assessment._junit(bad)


if __name__ == "__main__":
    unittest.main()
