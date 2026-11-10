"""Synthetic plan/failure checks, not the separately executed native Flask corpus."""

from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest import mock

from test_support import case_root


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("flask_phase_plan_control", ROOT / "bench/corpus/assessments/check_flask_phases_49943b5.py")
phase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase)


class FlaskReferencePlanControls(unittest.TestCase):
    def setUp(self):
        self.root = case_root(self)
        self.materialization = self.root / "materialization"
        self.materialization.mkdir()
        self.output = self.root / "run"
        self.calls = []
        spec = importlib.util.spec_from_file_location("flask_phase_test_process_tools", ROOT / "bench/corpus/serial_core/materialize.py")
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)
        archive = self.materialization / "source.tar"
        with tarfile.open(archive, "w") as tar:
            raw = b"explicit synthetic source, not Flask application code\n"
            item = tarfile.TarInfo("input.txt")
            item.size = len(raw)
            tar.addfile(item, io.BytesIO(raw))
        self.archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        environments = []
        for index in (1, 2):
            root = self.materialization / f"environment-{index}"
            (root / "bin").mkdir(parents=True)
            (root / "bin/python").write_bytes(b"explicit synthetic interpreter, never launched")
            site = root / "lib/python3.12/site-packages"
            site.mkdir(parents=True)
            (site / "package.py").write_text("explicit synthetic installed input\n")
            environments.append({"after": self.tools.tree(site), "interpreter_sha256": hashlib.sha256((root / "bin/python").read_bytes()).hexdigest()})
        (self.materialization / "result.json").write_text(json.dumps({
            "status": "reproduced_pytest_only_observations_unqualified", "revision": phase.REVISION,
            "source_archive_sha256": self.archive_digest, "runtime_environments": environments}))

    def fake_command(self, output, name, argv, work, env):
        self.calls.append({"name": name, "argv": argv, "cwd": str(work)})
        trace = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--pt-reference-trace="))
        Path(trace).write_bytes(b"explicit synthetic trace placeholder; reader is mocked\n")
        return {"returncode": 0, "synthetic_test_control": True}, {"stdout": b"", "stderr": b""}

    @contextmanager
    def synthetic(self, command=None, compare=None):
        original_loader = phase.importlib.util.spec_from_file_location
        # Only replace the already-tested independent process helper import.
        fake_spec = mock.Mock(loader=mock.Mock())
        with (mock.patch.object(phase, "ARCHIVE_SHA256", self.archive_digest),
              mock.patch.object(phase.importlib.util, "spec_from_file_location", return_value=fake_spec),
              mock.patch.object(phase.importlib.util, "module_from_spec", return_value=self.tools),
              mock.patch.object(self.tools, "_command", side_effect=command or self.fake_command),
              mock.patch.object(phase, "read_trace", return_value={"trace_sha256": "0" * 64,
                  "normalized": {"selected": list(range(494)), "completed": list(range(494)), "phases": [None] * 1482}}),
              mock.patch.object(phase, "compare_traces", side_effect=compare or (lambda *args, **kwargs: {
                  "status": "matched_instrumented_trace_contract", "differences": [], "synthetic_test_control": True}))):
            yield

    def produce(self):
        return phase.check(self.materialization, self.output, execute=True)

    def assert_ledger(self, report):
        self.assertEqual(len(report["planned_references"]), 4)
        self.assertFalse(report["confirmatory_eligible"])
        self.assertTrue(all(value is None for value in report["qualification"].values()))

    def test_requires_explicit_permission_exact_original_inputs_and_no_overwrite(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            phase.check(self.materialization, self.output)
        with self.synthetic():
            self.output.mkdir()
            (self.output / "user-work").write_text("keep")
            with self.assertRaises(FileExistsError):
                self.produce()
        self.assertEqual((self.output / "user-work").read_text(), "keep")
        self.assertEqual(self.calls, [])

    def test_four_predeclared_references_reset_same_literal_cwd_without_deleting_history(self):
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "matched_four_instrumented_references_unqualified")
        self.assertEqual(len(self.calls), 4)
        self.assertEqual({row["cwd"] for row in self.calls}, {str(self.output / "work")})
        self.assertEqual(len(list(self.output.glob("retained-work-*"))), 4)
        self.assertFalse((self.output / "work").exists())
        self.assertTrue(all(row["observation"]["synthetic_test_control"] for row in report["planned_references"]))

    def test_lost_return_is_not_recovered_from_a_trace_and_stops_later_requests(self):
        def lost(*args):
            self.fake_command(*args)
            raise OSError("explicit synthetic return loss after writing a trace")

        with self.synthetic(command=lost):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_references"][0]["status"], "unknown_execution_return")
        self.assertIsNone(report["planned_references"][0]["observation"])
        self.assertTrue((self.output / "trace-1-1.jsonl").exists())
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(row["status"] == "not_run_prior_failure" for row in report["planned_references"][1:]))

    def test_changed_installed_state_prevents_any_project_reference_execution(self):
        (self.materialization / "environment-1/lib/python3.12/site-packages/extra.py").write_text("unexpected")
        with self.synthetic():
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(self.calls, [])
        self.assertTrue(all(row["status"] == "not_run_prior_failure" for row in report["planned_references"]))

    def test_baseline_instability_is_not_rounded_into_a_candidate_match(self):
        def unstable(*args, **kwargs):
            return {"status": "mismatch", "differences": ["phases"], "synthetic_test_control": True}

        with self.synthetic(compare=unstable):
            report = self.produce()
        self.assert_ledger(report)
        self.assertEqual(report["status"], "baseline_uncertain")
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(row["stability"] == "baseline_uncertain" for row in report["comparisons"]))


if __name__ == "__main__":
    unittest.main()
