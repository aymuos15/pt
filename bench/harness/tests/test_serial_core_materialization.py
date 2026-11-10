"""Corpus source/reset/materialization controls, not a phase oracle or PT backend."""

from contextlib import contextmanager
import copy
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "bench/corpus/serial_core"
materializer = None
if sys.version_info[:3] == (3, 12, 12):
    spec = importlib.util.spec_from_file_location("serial_core_materializer", PROFILE / "materialize.py")
    materializer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(materializer)


SUPPORTED = materializer is not None and sys.platform == "linux" and platform.machine() == "x86_64" and sys.implementation.name == "cpython"


@unittest.skipUnless(SUPPORTED, "serial-core explicitly targets Linux x86-64 CPython 3.12.12")
class SerialCoreMaterializationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = self.root / "profile"
        shutil.copytree(PROFILE, self.profile, ignore=shutil.ignore_patterns("__pycache__"))
        self.output = self.root / "run"
        self.data = json.loads((self.profile / "corpus.json").read_text())
        self.calls = []

    def save_manifest(self):
        (self.profile / "corpus.json").write_text(json.dumps(self.data))

    def _fake_command(self, output, name, argv, cwd, environment):
        self.calls.append(name)
        if name.startswith("venv-"):
            index = int(name.split("-")[1])
            venv = output / f"environment-{index}"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin/python").write_bytes(b"explicit synthetic interpreter, never executed")
            purelib = venv / "lib/python3.12/site-packages"
            (purelib / "fake.dist-info").mkdir(parents=True)
            (purelib / "package.py").write_bytes(b"same synthetic installed bytes\n")
            (purelib / "fake.dist-info/RECORD").write_text(f"synthetic environment-specific record {index}\n")
        elif name.startswith("case-"):
            case = next(case for case in self.data["cases"] if case["id"] == name.split("-", 2)[2])
            report = ET.Element("testsuites")
            suite = ET.SubElement(report, "testsuite")
            for expectation in case["junit"]:
                row = ET.SubElement(suite, "testcase", name=expectation["name"])
                if expectation["kind"] != "passed":
                    ET.SubElement(row, expectation["kind"], message=expectation["marker"])
            Path(argv[-1].removeprefix("--junitxml=")).write_bytes(ET.tostring(report))
            if case["expected_events"] is not None:
                Path(environment["PT_CORE_EVENTS"]).write_text("\n".join(case["expected_events"]) + "\n")
            return {"returncode": case["expected_exit_code"], "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}
        return {"returncode": 0, "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}

    @contextmanager
    def synthetic(self, effect=None):
        def runtime(python, output, name, environment):
            return {"python": [3, 12, 12], "pytest": "8.4.2", "pytest_plugins": [],
                    "distributions": [], "purelib": str(python.parent.parent / "lib/python3.12/site-packages")}

        with mock.patch.object(materializer, "_command", side_effect=effect or self._fake_command), mock.patch.object(materializer, "_runtime", side_effect=runtime):
            yield

    def produce(self):
        return materializer.materialize(self.output, execute=True, profile_root=self.profile)

    def assert_ledger(self, report):
        self.assertEqual(len(report["cases"]), 20)
        self.assertEqual(report["planned_environments"], 2)
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(report["qualification"], {key: None for key in materializer.QUALIFICATION})
        self.assertEqual([(row["environment"], row["case"]) for row in report["cases"]],
                         [(index, case["id"]) for index in (1, 2) for case in self.data["cases"]])

    def test_declared_source_and_lock_inventory_is_complete_and_keeps_adverse_outcomes(self):
        data, captured = materializer.load_profile(self.profile)
        self.assertEqual(data, self.data)
        self.assertEqual(len(captured), 15)
        self.assertIn("corpus.json", captured)
        self.assertEqual({case["expected_exit_code"] for case in data["cases"]}, {0, 1, 2, 5})
        self.assertTrue(any(case["id"] == "application_floor" for case in data["cases"]))

    def test_explicit_execution_and_separate_nonnested_output_roots_are_required(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            materializer.materialize(self.output, profile_root=self.profile)
        for output in (self.profile / "output", self.root):
            with self.assertRaisesRegex(ValueError, "separate"):
                materializer.materialize(output, execute=True, profile_root=self.profile)
        self.assertFalse(self.output.exists())

    def test_complete_synthetic_control_retains_twenty_units_and_only_record_cross_exclusions(self):
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "reproduced_declared_mechanism_profile")
        self.assertEqual(report["compared_installed_files"], 1)
        self.assertEqual(report["record_exclusions_per_environment"], 1)
        self.assertTrue(all(row["status"] == "matched_declared_process_and_probe_outcomes" for row in report["cases"]))
        self.assertEqual((self.output / "frozen/corpus.json").read_bytes(), (self.profile / "corpus.json").read_bytes())
        self.assertEqual(json.loads((self.output / "result.json").read_text()), report)

    def test_corrupt_missing_or_unlisted_source_stops_before_installation(self):
        path = self.profile / "fixtures/basic/test_basic.py"
        raw = path.read_bytes()
        for mode in ("corrupt", "missing", "extra"):
            if mode == "corrupt":
                path.write_bytes(b"bad")
            elif mode == "missing":
                path.unlink()
            else:
                path.write_bytes(raw)
                (path.parent / "extra.py").write_text("unexpected")
            with self.synthetic(), self.assertRaises((OSError, ValueError)):
                self.produce()
            self.assertEqual(self.calls, [])
            self.assertFalse(self.output.exists())
            if mode == "corrupt":
                path.write_bytes(raw)

    def test_bad_lock_or_pyproject_hash_fails_before_any_installer(self):
        for name in ("uv.lock", "pyproject.toml"):
            path = self.profile / name
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            with self.synthetic(), self.assertRaisesRegex(ValueError, "pin differs"):
                self.produce()
            self.assertFalse(self.output.exists())
            path.write_bytes(original)

    def test_duplicate_traversal_boolean_exit_and_untracked_case_declarations_are_rejected(self):
        original = copy.deepcopy(self.data)
        for mode in ("duplicate", "traversal", "boolean", "unknown_case", "argv_nul", "missing_case", "digest_type"):
            self.data = copy.deepcopy(original)
            if mode == "duplicate":
                self.data["cases"].append(copy.deepcopy(self.data["cases"][0]))
            elif mode == "traversal":
                self.data["files"][0]["path"] = "../escape"
            elif mode == "boolean":
                self.data["cases"][0]["expected_exit_code"] = True
            elif mode == "unknown_case":
                self.data["cases"][0]["id"] = "other"
            elif mode == "argv_nul":
                self.data["cases"][0]["argv"] = ["nul\0"]
            elif mode == "missing_case":
                self.data["cases"].pop()
            else:
                self.data["files"][0]["sha256"] = True
            self.save_manifest()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                materializer.load_profile(self.profile)

    def test_symlink_fifo_and_aggregate_tree_limits_fail_closed(self):
        directory = self.root / "tree"
        directory.mkdir()
        target = self.root / "target"
        target.write_text("known")
        (directory / "alias").symlink_to(target)
        with self.assertRaises(ValueError):
            materializer.tree(directory)
        (directory / "alias").unlink()
        os.mkfifo(directory / "fifo")
        with self.assertRaises(ValueError):
            materializer.tree(directory)
        (directory / "fifo").unlink()
        (directory / "one").write_text("one")
        with mock.patch.object(materializer, "MAX_TREE_BYTES", 1), self.assertRaisesRegex(ValueError, "aggregate"):
            materializer.tree(directory)

    def test_junit_preserves_duplicate_occurrences_and_refuses_entity_or_ambiguous_outcomes(self):
        expected = [{"name": "same", "kind": "passed", "marker": ""}] * 2
        self.assertEqual(materializer.normalize_junit(b'<testsuites><testsuite><testcase name="same"/><testcase name="same"/></testsuite></testsuites>', expected), expected)
        expectation = [{"name": "test_collection", "kind": "error", "marker": "PT_CORE_COLLECTION_FAILURE"}]
        raw = b'<testsuites><testcase name="test_collection"><error message="collection failure">PT_CORE_COLLECTION_FAILURE</error></testcase></testsuites>'
        self.assertEqual(materializer.normalize_junit(raw, expectation), expectation)
        self.assertNotEqual(materializer.normalize_junit(raw.replace(b'>PT_CORE_COLLECTION_FAILURE<', b'>unrelated import failure<'), expectation), expectation)
        for raw in (b'<testsuites><testcase name="x"><error/><failure/></testcase></testsuites>',
                    b'<!DOCTYPE testsuites [<!ENTITY x "bad">]><testsuites/>'):
            with self.assertRaises(ValueError):
                materializer.normalize_junit(raw, [])

    def test_wrong_expected_exit_stops_later_work_without_retry_or_success_subset(self):
        original = self._fake_command

        def fail(*args):
            result, raw = original(*args)
            if args[1].startswith("case-"):
                result["returncode"] = 99
            return result, raw

        with self.synthetic(fail):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["cases"][0]["status"], "mismatch")
        self.assertIs(report["cases"][0]["invocation_attempted"], True)
        self.assertTrue(all(row["status"] == "not_run_prior_failure" for row in report["cases"][1:]))
        self.assertEqual(sum(name.startswith("case-") for name in self.calls), 1)

    def test_lost_return_after_complete_looking_junit_stays_unknown_without_recovery(self):
        original = self._fake_command

        def lost(*args):
            result = original(*args)
            if args[1].startswith("case-"):
                raise OSError("explicit synthetic API return loss after JUnit commit")
            return result

        with self.synthetic(lost):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["cases"][0]["status"], "unknown_return")
        self.assertIsNone(report["cases"][0]["observation"])
        self.assertIsNone(report["cases"][0]["invocation_attempted"])
        self.assertTrue((self.output / "junit-1-basic.xml").exists())
        self.assertEqual(sum(name.startswith("case-") for name in self.calls), 1)

    def test_unlisted_installed_file_mutation_aborts_before_second_environment(self):
        original = self._fake_command

        def mutate(*args):
            result = original(*args)
            if args[1] == "case-1-application_floor":
                (self.output / "environment-1/lib/python3.12/site-packages/unlisted.py").write_text("changed")
            return result

        with self.synthetic(mutate):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertNotIn("venv-2", self.calls)
        self.assertTrue(all(row["status"] == "not_run_prior_failure" for row in report["cases"][10:]))

    def test_cross_environment_file_difference_is_not_erased_as_a_generic_path_difference(self):
        original = self._fake_command

        def different(*args):
            result = original(*args)
            if args[1] == "venv-2":
                (self.output / "environment-2/lib/python3.12/site-packages/package.py").write_text("different bytes")
            return result

        with self.synthetic(different):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertTrue(all(row["status"] == "matched_declared_process_and_probe_outcomes" for row in report["cases"]))
        self.assertIn("differ outside", report["errors"][0]["error"])

    def test_changed_frozen_archive_is_not_silently_repaired_or_accepted(self):
        original = self._fake_command

        def different(*args):
            result = original(*args)
            if args[1] == "case-2-application_floor":
                (self.output / "frozen/uv.lock").write_text("changed")
            return result

        with self.synthetic(different):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertIn("frozen inputs changed", report["errors"][0]["error"])
        self.assertEqual((self.output / "frozen/uv.lock").read_text(), "changed")

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with self.synthetic(), self.assertRaises(FileExistsError):
            self.produce()
        self.assertEqual((self.output / "user-work").read_text(), "keep")
        self.assertEqual(self.calls, [])

    def test_output_publication_failure_does_not_return_a_successful_materialization(self):
        original = materializer._save

        def fail(path, value):
            original(path, value)
            if path == self.output / "result.json":
                raise OSError("explicit synthetic result publication return loss")

        with self.synthetic(), mock.patch.object(materializer, "_save", side_effect=fail), self.assertRaises(OSError):
            self.produce()
        self.assertTrue((self.output / "result.json").exists())


@unittest.skipUnless(SUPPORTED, "serial-core explicitly targets Linux x86-64 CPython 3.12.12")
class NativeSerialCoreMaterializationTests(unittest.TestCase):
    def test_two_clean_offline_installs_run_every_case_once_and_preserve_all_expected_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            report = materializer.materialize(Path(temp) / "run", execute=True)
            self.assertEqual(report["status"], "reproduced_declared_mechanism_profile", report["errors"])
            self.assertEqual(len(report["environments"]), 2)
            self.assertEqual(len(report["cases"]), 20)
            self.assertTrue(all(row["status"] == "matched_declared_process_and_probe_outcomes" for row in report["cases"]))
            self.assertGreater(report["compared_installed_files"], 100)
            self.assertFalse(report["confirmatory_eligible"])
            self.assertTrue(all(value is None for value in report["qualification"].values()))


if __name__ == "__main__":
    unittest.main()
