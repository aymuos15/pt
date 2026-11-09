"""Bounded scenario/reset/edit/input controls; no qualification from matching files."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import scenario_replay as scenario
    import scenario_inputs as inputs
    import pt_bench as timer
    import blob_store
    from analysis import guarded_exploratory_ratio, paired_geometric_ratio
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == "linux", "initial Linux safe blob/reset profile")
class ScenarioReplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cwd, self.payloads, self.output = self.root / "work", self.root / "payloads", self.root / "run"
        self.cwd.mkdir()
        self.payloads.mkdir()
        self.old, self.new = self.value(b"old\n"), self.value(b"new\n")
        (self.cwd / "source.txt").write_text("dirty\n")
        (self.cwd / "gone.txt").write_text("dirty\n")
        (self.cwd / "unlisted").write_text("not reset\n")
        self.plan = {"schema_version": 1, "kind": "scenario_edit_replay_plan", "mode": "exploratory_unqualified",
                     "measurement_layer": scenario.LAYER, "sample_unit": scenario.UNIT, "timing_endpoint": scenario.ENDPOINT,
                     "cwd": str(self.cwd), "input_seed": 17, "execution_timeout_seconds": 20,
                     "scenario": {"id": "S3", "cache_state": {key: "unknown" for key in (
                         "coordinator", "framework_seed", "pt_metadata", "python_bytecode", "filesystem_cache",
                         "application_service", "dependency_observations", "source")}},
                     "reset": [{"path": "created.txt", "value": None}, {"path": "gone.txt", "value": self.old},
                               {"path": "request.json", "value": None}, {"path": "source.txt", "value": self.old}],
                     "requests": [
                         {"id": "first", "edits": [{"path": "created.txt", "before": None, "after": self.new},
                                                   {"path": "gone.txt", "before": self.old, "after": None},
                                                   {"path": "source.txt", "before": self.old, "after": self.new}],
                          "input": self.payload("first", {"created.txt": "new\n", "gone.txt": None, "source.txt": "new\n"}),
                          "command": self.command("request", "first")},
                         {"id": "second", "edits": [{"path": "created.txt", "before": self.new, "after": None},
                                                    {"path": "gone.txt", "before": None, "after": self.new},
                                                    {"path": "source.txt", "before": self.new, "after": self.old}],
                          "input": self.payload("second", {"created.txt": None, "gone.txt": "new\n", "source.txt": "old\n"}),
                          "command": self.command("request", "second")}],
                     "shutdown": self.command("shutdown", "shutdown"), "limitations": scenario.LIMITATIONS.copy()}

    def value(self, raw, mode=0o600):
        digest = hashlib.sha256(raw).hexdigest()
        (self.payloads / digest).write_bytes(raw)
        return {"bytes": len(raw), "sha256": digest, "mode": mode}

    def payload(self, name, data, seed=17):
        value = self.value(json.dumps({"schema_version": 1, "request_id": name, "input_seed": seed, "data": data}).encode())
        return {"path": "request.json", "value": value}

    def command(self, role, name):
        return {"argv": [sys.executable, str(HARNESS / "tests/fixtures/scenario_probe.py"), role, name, "normal"],
                "timeout_seconds": 5,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": hashlib.sha256(b"ready\n").hexdigest()},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [{"path": "report-" + name, "bytes": 6, "sha256": hashlib.sha256(b"ready\n").hexdigest()}],
                                          "absent": ["lease"] if role == "shutdown" else []}}

    def observe(self):
        self.receipt = scenario.run_scenario(self.output, self.plan, self.payloads, apply=True)
        self.summary = scenario.inspect_scenario(self.output, self.receipt)
        self.assert_counts(self.summary)
        return self.summary

    def assert_counts(self, summary):
        self.assertEqual(summary["planned_request_count"], sum(summary["request_status_counts"].values()))
        self.assertEqual(summary["planned_request_count"], sum(summary[key] for key in (
            "known_request_invocations", "unknown_request_invocations", "known_not_invoked_requests")))
        self.assertEqual(summary["planned_phase_count"], sum(summary["phase_status_counts"].values()))
        self.assertEqual(summary["qualification"], {key: None for key in scenario.QUALIFICATION})
        self.assertFalse(summary["confirmatory_eligible"])
        self.assertIsNone(summary["ratio"])
        self.assertIsNone(summary["bootstrap"])

    def unit(self):
        return json.loads((self.output / "unit.json").read_text())

    def rebind(self, unit):
        unit["retained_inputs"] = scenario._inputs(self.output)[0]
        path = self.output / "unit.json"
        path.write_text(json.dumps(unit))
        self.receipt["unit"] = {"name": "unit.json", "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def inspect(self):
        return scenario.inspect_scenario(self.output, self.receipt)

    def events(self):
        path = self.cwd / "events"
        return path.read_text().splitlines() if path.exists() else []

    def test_reset_create_replace_delete_and_delivered_seed_inputs_are_retained_for_each_request(self):
        summary = self.observe()
        self.assertEqual(summary["status"], "completed_unqualified")
        self.assertEqual(summary["planned_request_count"], 2)
        self.assertEqual(summary["phase_status_counts"], {"observed_unqualified": 6})
        self.assertEqual(len({line.split(":")[-1] for line in self.events()}), 3)
        self.assertEqual((self.cwd / "source.txt").read_bytes(), b"old\n")
        self.assertEqual((self.cwd / "unlisted").read_text(), "not reset\n")
        self.assertFalse((self.cwd / "created.txt").exists())
        self.assertFalse((self.cwd / "lease").exists())
        unit = self.unit()
        self.assertEqual(inputs.values(unit["phases"][0]["after"]), scenario._states(self.plan)[0])
        for index, request in zip((2, 4), self.plan["requests"]):
            row = unit["phases"][index]
            delivered = next(item["value"] for item in row["before"]["files"] if item["path"] == "request.json")
            self.assertEqual(delivered, request["input"]["value"])
            raw = (self.output / "blobs" / delivered["sha256"]).read_bytes()
            self.assertEqual(json.loads(raw)["input_seed"], 17)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def test_wrong_seed_request_identity_and_corrupt_later_payload_fail_before_any_effect(self):
        for mode in ("seed", "id", "bytes"):
            changed = copy.deepcopy(self.plan)
            request = changed["requests"][-1]
            if mode in ("seed", "id"):
                request["input"] = self.payload("wrong" if mode == "id" else "second", {}, seed=18 if mode == "seed" else 17)
            else:
                (self.payloads / request["input"]["value"]["sha256"]).write_bytes(b"corrupt")
            with mock.patch.object(inputs, "mutate") as mutated, mock.patch.object(timer, "measure_and_publish") as invoked:
                with self.assertRaises(ValueError):
                    scenario.run_scenario(self.output, changed, self.payloads, apply=True)
                mutated.assert_not_called()
                invoked.assert_not_called()
            self.assertFalse(self.output.exists())
        self.assertEqual((self.cwd / "source.txt").read_text(), "dirty\n")

    def test_edit_precondition_chain_mismatch_noop_or_payload_overlap_fail_before_work(self):
        for mode in ("chain", "noop", "payload", "duplicate", "outside"):
            changed = copy.deepcopy(self.plan)
            edits = changed["requests"][1]["edits"]
            if mode == "chain":
                edits[-1]["before"] = self.old
            elif mode == "noop":
                edits[-1]["after"] = self.new
            elif mode == "payload":
                edits[-1]["path"] = "request.json"
            elif mode == "duplicate":
                edits.append(copy.deepcopy(edits[-1]))
            else:
                edits[-1]["path"] = "unlisted"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                scenario.run_scenario(self.output, changed, self.payloads, apply=True)
            self.assertFalse(self.output.exists())

    def test_explicit_apply_and_separate_safe_roots_are_required(self):
        for apply in (False, 1, None):
            with self.assertRaisesRegex(ValueError, "apply"):
                scenario.run_scenario(self.output, self.plan, self.payloads, apply=apply)
        with self.assertRaisesRegex(ValueError, "separate"):
            scenario.run_scenario(self.cwd / "output", self.plan, self.payloads, apply=True)
        with self.assertRaisesRegex(ValueError, "separate"):
            scenario.run_scenario(self.output, self.plan, self.cwd, apply=True)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten_and_no_reset_runs(self):
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with mock.patch.object(inputs, "mutate") as mutated:
            with self.assertRaises(FileExistsError):
                scenario.run_scenario(self.output, self.plan, self.payloads, apply=True)
            mutated.assert_not_called()
        self.assertEqual((self.output / "user-work").read_text(), "keep")

    def test_partial_reset_failure_stops_requests_keeps_effects_and_attempts_shutdown_once(self):
        original = inputs.mutate

        def fail(root, observed, desired, bundle):
            if observed["path"] == "source.txt":
                raise OSError("fixture-only partial reset failure")
            return original(root, observed, desired, bundle)

        with mock.patch.object(inputs, "mutate", side_effect=fail):
            summary = self.observe()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(summary["unknown_file_effect_returns"], 1)
        self.assertEqual((self.cwd / "gone.txt").read_bytes(), b"old\n")
        self.assertEqual((self.cwd / "source.txt").read_text(), "dirty\n")
        self.assertEqual([line.split(":")[:2] for line in self.events()], [["shutdown", "shutdown"]])

    def test_mutation_return_lost_after_install_remains_unknown_not_retried_or_rolled_back(self):
        original, calls = inputs.mutate, []

        def lost(root, observed, desired, bundle):
            result = original(root, observed, desired, bundle)
            calls.append(observed["path"])
            if observed["path"] == "source.txt":
                raise OSError("fixture-only mutation return lost after installation")
            return result

        with mock.patch.object(inputs, "mutate", side_effect=lost):
            summary = self.observe()
        self.assertEqual(summary["unknown_file_effect_returns"], 1)
        self.assertEqual(calls.count("source.txt"), 1)
        self.assertEqual((self.cwd / "source.txt").read_bytes(), b"old\n")
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(self.unit()["phases"][0]["status"], "failed")

    def test_failed_edit_does_not_invoke_request_or_later_edits_and_preserves_partial_state(self):
        original, calls = inputs.mutate, []

        def fail(root, observed, desired, bundle):
            calls.append(observed["path"])
            if len(calls) > 4 and observed["path"] == "gone.txt":
                raise OSError("fixture-only edit failure after create")
            return original(root, observed, desired, bundle)

        with mock.patch.object(inputs, "mutate", side_effect=fail):
            summary = self.observe()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual((self.cwd / "created.txt").read_bytes(), b"new\n")
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(len(self.events()), 1)

    def test_subject_changes_to_declared_inputs_fail_even_with_matching_stdout(self):
        self.plan["requests"][0]["command"]["argv"][-1] = "mutate"
        summary = self.observe()
        self.assertEqual(summary["request_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual((self.cwd / "source.txt").read_text(), "changed by subject\n")
        self.assertEqual(self.unit()["phases"][2]["errors"][0]["stage"], "postcondition")
        self.assertEqual(len(self.events()), 2)

    def test_unexpected_same_size_same_mtime_change_before_request_is_detected_by_hash(self):
        original = scenario._phase

        def change(output, plan, index, role, *args):
            if role == "request":
                path = self.cwd / "source.txt"
                metadata = path.stat()
                path.write_bytes(b"bad\n")
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            return original(output, plan, index, role, *args)

        with mock.patch.object(scenario, "_phase", side_effect=change):
            summary = self.observe()
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(self.unit()["phases"][2]["errors"][0]["stage"], "precondition")
        self.assertEqual(len(self.events()), 1)

    def test_same_size_edit_and_revert_observations_preserve_distinct_exact_bytes(self):
        original = inputs.mutate

        def preserve_mtime(root, observed, desired, bundle):
            result = original(root, observed, desired, bundle)
            if observed["path"] == "source.txt" and observed["identity"] is not None and desired is not None:
                os.utime(self.cwd / "source.txt", ns=(observed["identity"][3], observed["identity"][3]))
            return result

        with mock.patch.object(inputs, "mutate", side_effect=preserve_mtime):
            self.assertEqual(self.observe()["status"], "completed_unqualified")
        unit = self.unit()
        values = [next(item["value"] for item in unit["phases"][index]["before"]["files"] if item["path"] == "source.txt") for index in (2, 4)]
        self.assertEqual(values, [self.new, self.old])
        self.assertEqual(self.new["bytes"], self.old["bytes"])

    def test_failed_and_expected_nonzero_requests_remain_distinct(self):
        self.plan["requests"][0]["command"]["argv"][-1] = "fail"
        self.assertEqual(self.observe()["request_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.output = self.root / "expected-nonzero"
        command = self.plan["requests"][0]["command"]
        command["guard_expectations"]["expected_exit_code"] = command["required_finalization"]["expected_exit_code"] = 7
        self.assertEqual(self.observe()["status"], "completed_unqualified")

    def test_shutdown_failure_hang_or_unreleased_file_keeps_whole_scenario_aborted(self):
        for mode in ("fail", "hang", "unreleased"):
            self.output = self.root / mode
            self.plan["shutdown"]["argv"][-1] = mode
            self.plan["shutdown"]["timeout_seconds"] = 0.05 if mode == "hang" else 5
            summary = self.observe()
            self.assertEqual(summary["status"], "aborted")
            self.assertEqual(summary["shutdown_status"], "failed")
            self.assertEqual(summary["known_request_invocations"], 2)

    def test_execution_deadline_still_attempts_original_reserved_shutdown(self):
        self.plan["execution_timeout_seconds"] = 0.001
        summary = self.observe()
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")
        self.assertEqual(len(self.events()), 1)

    def test_command_return_lost_before_or_after_commit_keeps_unknown_request_without_recovery(self):
        original = timer.measure_and_publish
        for mode in ("before", "after"):
            self.output = self.root / mode
            calls = []

            def lost(*args, **kwargs):
                calls.append(1)
                if len(calls) == 1:
                    if mode == "after":
                        original(*args, **kwargs)
                    raise OSError("fixture-only missing request return")
                return original(*args, **kwargs)

            with mock.patch.object(timer, "measure_and_publish", side_effect=lost):
                summary = self.observe()
            self.assertEqual(summary["request_status_counts"], {"not_run_prior_failure": 1, "unknown": 1})
            self.assertEqual(summary["unknown_request_invocations"], 1)
            self.assertEqual(summary["shutdown_status"], "observed_unqualified")
            self.assertEqual((self.output / "command-0003.json").exists(), mode == "after")

    def test_interrupt_after_effects_preserves_unknowns_and_shutdown_without_retry(self):
        original = inputs.mutate

        def cancel(root, observed, desired, bundle):
            original(root, observed, desired, bundle)
            raise KeyboardInterrupt("fixture-only cancellation after explicit file effect")

        with mock.patch.object(inputs, "mutate", side_effect=cancel):
            summary = self.observe()
        self.assertEqual(summary["unknown_file_effect_returns"], 1)
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")

    def test_symlink_hardlink_fifo_and_missing_parent_are_unknown_not_absent_or_reset_success(self):
        target = self.cwd / "source.txt"
        for mode in ("symlink", "hardlink", "fifo"):
            self.output = self.root / mode
            target.unlink()
            if mode == "symlink":
                target.symlink_to(self.cwd / "unlisted")
            elif mode == "hardlink":
                os.link(self.cwd / "unlisted", target)
            else:
                os.mkfifo(target)
            summary = self.observe()
            self.assertEqual(summary["reset_status"], "failed")
            self.assertEqual(summary["known_not_invoked_requests"], 2)
            self.assertEqual(self.unit()["phases"][0]["before"]["files"][-1]["status"], "unknown")
        self.assertEqual((self.cwd / "unlisted").read_text(), "not reset\n")
        root = self.root / "empty-parent"
        root.mkdir()
        observed = inputs.snapshot(root, ["missing/child"], self.output / "blobs")
        self.assertEqual(observed["files"][0]["status"], "unknown")

    def test_concurrent_create_is_not_overwritten_by_input_delivery(self):
        original = inputs._create

        def compete(directory, source, destination):
            if destination == "request.json":
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
                os.write(fd, b"user concurrent file")
                os.close(fd)
            return original(directory, source, destination)

        with mock.patch.object(inputs, "_create", side_effect=compete):
            summary = self.observe()
        self.assertEqual((self.cwd / "request.json").read_bytes(), b"user concurrent file")
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["known_not_invoked_requests"], 2)
        self.assertEqual(list(self.cwd.glob(".pt-scenario-*.tmp")), [])

    def test_unsupported_environment_watch_and_os_cold_profiles_never_start_work(self):
        for label in ("S6", "S7", "S9"):
            self.output = self.root / label
            self.plan["scenario"]["id"] = label
            with mock.patch.object(inputs, "mutate") as mutated, mock.patch.object(timer, "measure_and_publish") as invoked:
                summary = self.observe()
                mutated.assert_not_called()
                invoked.assert_not_called()
            self.assertEqual(summary["status"], "unsupported")
            self.assertEqual(summary["request_status_counts"], {"not_run_unsupported": 2})
            self.assertEqual(summary["shutdown_status"], "not_run_unsupported")

    def test_unchanged_scenarios_reject_edit_claims_and_can_validate_explicit_inputs_without_edits(self):
        for label in ("S0", "S1", "S2"):
            self.plan["scenario"]["id"] = label
            with self.assertRaisesRegex(ValueError, "scenario class"):
                scenario.validate_plan(self.plan)
        for request in self.plan["requests"]:
            request["edits"] = []
            request["input"] = self.payload(request["id"], {"source.txt": "old\n", "gone.txt": "old\n", "created.txt": None})
        self.assertEqual(self.observe()["status"], "completed_unqualified")

    def test_request_input_and_file_modes_are_part_of_exact_state(self):
        self.plan["reset"][-1]["value"] = {**self.old, "mode": 0o640}
        self.plan["requests"][0]["edits"][-1]["before"] = {**self.old, "mode": 0o640}
        self.plan["requests"][0]["edits"][-1]["after"] = {**self.new, "mode": 0o640}
        self.plan["requests"][1]["edits"][-1]["before"] = {**self.new, "mode": 0o640}
        self.assertEqual(self.observe()["status"], "completed_unqualified")
        value = next(item["value"] for item in self.unit()["phases"][2]["before"]["files"] if item["path"] == "source.txt")
        self.assertEqual(value["mode"], 0o640)

    def test_offline_inspection_and_relocation_do_not_read_or_repair_current_worktree(self):
        expected = self.observe()
        moved = self.root / "moved"
        shutil.copytree(self.output, moved)
        (self.cwd / "source.txt").write_bytes(b"later mutation")
        with mock.patch.object(inputs, "read", side_effect=AssertionError("live input read")), mock.patch.object(inputs, "mutate") as mutated, mock.patch.object(timer, "measure_and_publish") as invoked:
            self.assertEqual(scenario.inspect_scenario(moved, self.receipt), expected)
            mutated.assert_not_called()
            invoked.assert_not_called()

    def test_omitted_reset_edit_request_or_shutdown_and_reordered_operations_fail_after_rebinding(self):
        self.observe()
        original = self.unit()
        for index in (0, 1, 2, 5):
            changed = copy.deepcopy(original)
            changed["phases"].pop(index)
            self.rebind(changed)
            with self.assertRaisesRegex(ValueError, "omitted planned"):
                self.inspect()
        changed = copy.deepcopy(original)
        changed["phases"][1]["operations"].reverse()
        self.rebind(changed)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_rebound_wrong_inputs_or_missing_reset_state_checks_cannot_be_reported_successful(self):
        self.observe()
        original = self.unit()
        for mode in ("pre", "post", "omit", "unknown"):
            changed = copy.deepcopy(original)
            row = changed["phases"][2 if mode == "pre" else 0]
            value = row["before" if mode == "pre" else "after"]
            if mode == "omit":
                value["files"].pop()
            elif mode == "unknown":
                value["files"][-1].update(status="unknown", value=None, identity=None, error="injected unknown")
            else:
                value["files"][-1]["value"] = dict(self.old if mode == "pre" else self.new)
            self.rebind(changed)
            with self.assertRaises(ValueError):
                self.inspect()

    def test_corrupt_or_missing_blob_and_extra_record_do_not_become_favorable_subsets(self):
        self.observe()
        extra = self.output / "extra.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            self.inspect()
        extra.unlink()
        (self.output / "blobs" / self.old["sha256"]).write_bytes(b"bad")
        self.rebind(self.unit())
        with self.assertRaises(ValueError):
            self.inspect()

    def test_unknown_and_unconfirmed_outcomes_cannot_be_promoted_after_unit_digest_rebinding(self):
        original = timer.measure_and_publish
        calls = []

        def lose(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                original(*args, **kwargs)
                raise OSError("fixture-only lost return after complete command")
            return original(*args, **kwargs)

        with mock.patch.object(timer, "measure_and_publish", side_effect=lose):
            self.observe()
        changed = self.unit()
        changed["phases"][2].update(status="observed_unqualified", command_invocation_attempted=True, errors=[])
        self.rebind(changed)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_unit_publication_omitted_or_failed_after_commit_keeps_diagnostic_not_confirmed(self):
        original = timer.write_record
        for mode in ("omit", "committed_then_error", "wrong"):
            self.output = self.root / mode

            def fail(path, value):
                if Path(path) == self.output / "unit.json":
                    if mode == "committed_then_error":
                        original(path, value)
                    elif mode == "wrong":
                        Path(path).write_text("{}")
                    if mode != "omit":
                        raise OSError("fixture-only unit publication failure")
                    return
                return original(path, value)

            with mock.patch.object(timer, "write_record", side_effect=fail):
                if mode == "wrong":
                    with self.assertRaises(ValueError):
                        self.observe()
                    continue
                self.assertEqual(self.observe()["status"], "aborted")
            self.assertIsNone(self.receipt["unit"])
            self.assertIsNotNone(self.receipt["diagnostic_unit"])

    def test_closed_schema_strict_tokens_and_qualification_nulls_cannot_be_upgraded(self):
        self.observe()
        for mutation in (lambda value: value.update(confirmatory_eligible=True), lambda value: value.update(schema_version=True),
                         lambda value: value.update(extra=0), lambda value: value["qualification"].update(reset_equivalence=True),
                         lambda value: value["qualification"].pop("actual_loaded_code")):
            changed = copy.deepcopy(self.receipt)
            mutation(changed)
            with self.assertRaises(ValueError):
                scenario.inspect_scenario(self.output, changed)
        for mutation in (lambda value: value.update(input_seed=True), lambda value: value["reset"][-1]["value"].update(bytes=4.0),
                         lambda value: value["reset"][-1]["value"].update(mode=True), lambda value: value["requests"][0]["command"].update(timeout_seconds=float("nan"))):
            changed = copy.deepcopy(self.plan)
            mutation(changed)
            with self.assertRaises(ValueError):
                scenario.validate_plan(changed)

    def test_exact_path_and_digest_validation_rejects_traversal_nul_and_nested_file_domains(self):
        for path in ("../escape", "a/../b", "nul\0", "/absolute", "a\\b"):
            changed = copy.deepcopy(self.plan)
            changed["reset"][0]["path"] = path
            with self.assertRaises(ValueError):
                scenario.validate_plan(changed)
        changed = copy.deepcopy(self.plan)
        changed["reset"].insert(0, {"path": "created.txt/child", "value": None})
        changed["reset"].sort(key=lambda item: item["path"])
        with self.assertRaises(ValueError):
            scenario.validate_plan(changed)

    def test_phase_clock_endpoints_and_command_contract_are_validated(self):
        self.observe()
        original = self.unit()
        changed = copy.deepcopy(original)
        clock = changed["phases"][2]["after"]["clock"]
        clock["monotonic_end_ns"] = clock["monotonic_start_ns"] = 0
        clock["elapsed_ns"] = 0
        self.rebind(changed)
        with self.assertRaises(ValueError):
            self.inspect()
        self.rebind(original)
        self.receipt["unit_publication_clock"]["monotonic_start_ns"] = self.receipt["clock"]["monotonic_start_ns"]
        self.receipt["unit_publication_clock"]["elapsed_ns"] = self.receipt["unit_publication_clock"]["monotonic_end_ns"] - self.receipt["unit_publication_clock"]["monotonic_start_ns"]
        with self.assertRaisesRegex(ValueError, "before shutdown"):
            self.inspect()

    def test_scenario_validation_layer_is_never_a_latency_or_independent_sample(self):
        for estimator in (guarded_exploratory_ratio, paired_geometric_ratio):
            for label in ({"measurement_layer": scenario.LAYER}, {"sample_unit": scenario.UNIT}):
                with self.assertRaisesRegex(ValueError, "scenario input/edit validation"):
                    estimator([{"block": "1", "arm": "baseline", "elapsed_ns": 1, "status": "guard_matched_unqualified", **label}])

    def test_schema_and_all_references_resolve_offline(self):
        names = ("scenario-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json", "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
        schemas = [json.loads((HARNESS / name).read_text()) for name in names]
        registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
        pending = []
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            pending.append((schema, schema["$id"]))
        while pending:
            value, base = pending.pop()
            if isinstance(value, dict):
                if "$ref" in value:
                    registry.resolver(base_uri=base).lookup(value["$ref"])
                pending.extend((child, base) for child in value.values())
            elif isinstance(value, list):
                pending.extend((child, base) for child in value)

    def test_comparison_binds_exact_resets_edits_seed_inputs_and_separate_arm_roots(self):
        self.observe()
        baseline, baseline_receipt = self.output, copy.deepcopy(self.receipt)
        self.cwd = self.root / "candidate"
        self.cwd.mkdir()
        self.plan["cwd"] = str(self.cwd)
        self.output = self.root / "candidate-run"
        self.observe()
        matched = scenario.compare_scenarios(baseline, baseline_receipt, self.output, self.receipt)
        self.assertEqual(matched["status"], "declared_file_inputs_matched_unqualified")
        self.assertIsNone(matched["reset_equivalence"])
        self.assertIsNone(matched["semantic_equal_work"])
        self.assertFalse(matched["confirmatory_eligible"])
        reused = scenario.compare_scenarios(baseline, baseline_receipt, baseline, baseline_receipt)
        self.assertIn("arm_worktrees_not_separate", reused["reasons"])
        self.output = self.root / "different-edit"
        different = self.value(b"alt\n")
        self.plan["requests"][1]["edits"][-1]["after"] = different
        self.plan["requests"][1]["input"] = self.payload("second", {"source.txt": "alt\n", "created.txt": None, "gone.txt": "new\n"})
        self.observe()
        mismatched = scenario.compare_scenarios(baseline, baseline_receipt, self.output, self.receipt)
        self.assertEqual(mismatched["status"], "blocked")
        self.assertIn("declared_scenario_reset_edits_or_inputs_differ", mismatched["reasons"])

    def test_comparison_retains_failed_and_not_run_requests_without_subsetting(self):
        self.observe()
        baseline, receipt = self.output, copy.deepcopy(self.receipt)
        self.cwd = self.root / "candidate"
        self.cwd.mkdir()
        self.plan["cwd"] = str(self.cwd)
        self.output = self.root / "candidate-run"
        self.plan["requests"][0]["command"]["argv"][-1] = "fail"
        self.observe()
        compared = scenario.compare_scenarios(baseline, receipt, self.output, self.receipt)
        self.assertEqual(compared["status"], "blocked")
        self.assertEqual(compared["observations"][1]["request_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual(sum(report["planned_request_count"] for report in compared["observations"]), 4)

    def test_real_pytest_requests_use_one_collection_and_execution_per_fresh_requested_process(self):
        raw = (b"import json\nfrom pathlib import Path\n"
               b"with Path('imports').open('a') as stream: stream.write('import\\n')\n"
               b"def test_explicit_input():\n"
               b"    p=json.loads(Path('request.json').read_text())\n"
               b"    assert Path('source.txt').read_text()==p['data']['source.txt']\n"
               b"    with Path('calls').open('a') as stream: stream.write(p['request_id']+'\\n')\n")
        self.plan["reset"].append({"path": "test_case.py", "value": self.value(raw)})
        self.plan["reset"].sort(key=lambda item: item["path"])
        for request in self.plan["requests"]:
            request["command"].update(argv=[sys.executable, "-m", "pytest", "-q", "test_case.py"], guard_expectations=None,
                                      required_finalization={"expected_exit_code": 0, "artifacts": [], "absent": []})
        with mock.patch.dict(os.environ, {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}):
            summary = self.observe()
        self.assertEqual(summary["status"], "completed_unqualified")
        self.assertEqual((self.cwd / "imports").read_text().splitlines(), ["import", "import"])
        self.assertEqual((self.cwd / "calls").read_text().splitlines(), ["first", "second"])
        self.assertIsNone(summary["qualification"]["actual_loaded_code"])

    def test_input_and_blob_limits_fail_without_dropping_files_or_executing_requests(self):
        with mock.patch.object(inputs, "MAX_BLOB_BYTES", 1), mock.patch.object(timer, "measure_and_publish") as invoked:
            with self.assertRaises(ValueError):
                scenario.run_scenario(self.output, self.plan, self.payloads, apply=True)
            invoked.assert_not_called()
        self.assertFalse(self.output.exists())
        self.observe()
        for setting in ("MAX_BLOBS", "MAX_BLOB_BYTES"):
            with mock.patch.object(inputs, setting, 1):
                with self.assertRaisesRegex(ValueError, "aggregate byte/file limit"):
                    self.inspect()
        changed = copy.deepcopy(self.plan)
        changed["reset"][-1]["value"]["bytes"] = inputs.MAX_FILE_BYTES + 1
        with self.assertRaises(ValueError):
            scenario.validate_plan(changed)

    def test_observed_evidence_fingerprint_changes_are_not_retried(self):
        self.observe()
        original, calls = scenario.capture_run, []

        def changed(path):
            captured = original(path)
            calls.append(1)
            if len(calls) > 1:
                captured[1]["plan.json"][-1] += 1  # Explicit synthetic identity-only mutation.
            return captured

        with mock.patch.object(scenario, "capture_run", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during inspection"):
                self.inspect()
        self.assertEqual(len(calls), 3)

    def test_missing_command_receipt_cannot_invent_known_noninvocation_with_available_budget(self):
        self.observe()
        unit = self.unit()
        unit["phases"][2].update(receipt=None, command_invocation_attempted=False, errors=[], status="failed",
                                  timeout_computed_at_ns=None, effective_timeout_seconds=None)
        self.rebind(unit)
        with self.assertRaisesRegex(ValueError, "neither a returned observation"):
            self.inspect()

    def test_unknown_return_does_not_permit_unattributed_later_command_files(self):
        original, calls = timer.measure_and_publish, []

        def lost(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("fixture-only missing return")
            return original(*args, **kwargs)

        with mock.patch.object(timer, "measure_and_publish", side_effect=lost):
            self.observe()
        (self.output / "command-9999.json").write_text("{}")
        self.rebind(self.unit())
        with self.assertRaisesRegex(ValueError, "not an attributable"):
            self.inspect()

    def test_deadline_exhausted_during_input_observation_prevents_launch_but_keeps_shutdown(self):
        original, calls = inputs.snapshot, []
        self.plan["execution_timeout_seconds"] = 0.15

        def delayed(*args, **kwargs):
            calls.append(1)
            if len(calls) == 5:
                time.sleep(0.2)
            return original(*args, **kwargs)

        with mock.patch.object(inputs, "snapshot", side_effect=delayed):
            summary = self.observe()
        self.assertEqual(summary["request_status_counts"], {"not_run_execution_deadline": 1, "not_run_prior_failure": 1})
        self.assertEqual(summary["shutdown_status"], "observed_unqualified")
        self.assertEqual(summary["known_not_invoked_requests"], 2)

    def test_subject_arguments_environment_and_no_harness_imports_are_preserved(self):
        code = ("import json,os,sys; from pathlib import Path; "
                "Path('transport').write_text(json.dumps([sys.argv[1:],os.getcwd(),os.environ['PT_SCENARIO_CONTROL'],"
                "[name for name in ('scenario_replay','scenario_inputs','pt_bench') if name in sys.modules]])); "
                "Path('report-first').write_text('ready\\n'); print('ready')")
        self.plan["requests"][0]["command"]["argv"] = [sys.executable, "-c", code, "with space", "", "λ"]
        with mock.patch.dict(os.environ, {"PT_SCENARIO_CONTROL": "fixture-only"}):
            self.assertEqual(self.observe()["status"], "completed_unqualified")
        self.assertEqual(json.loads((self.cwd / "transport").read_text()), [["with space", "", "λ"], str(self.cwd), "fixture-only", []])

    def test_command_publication_return_failure_preserves_known_attempt_without_confirmed_sample(self):
        original = timer.write_record

        def fail(path, value):
            original(path, value)
            if Path(path) == self.output / "command-0003.json":
                raise OSError("fixture-only unconfirmed command sample publication")

        with mock.patch.object(timer, "write_record", side_effect=fail):
            summary = self.observe()
        self.assertEqual(summary["request_status_counts"], {"failed": 1, "not_run_prior_failure": 1})
        self.assertEqual(summary["known_request_invocations"], 1)
        self.assertIsNone(self.unit()["phases"][2]["receipt"]["sample"])
        self.assertTrue((self.output / "command-0003.json").exists())

    def test_cli_run_inspect_and_missing_apply_keep_explicit_mutation_boundary(self):
        path = self.root / "plan.json"
        path.write_text(json.dumps(self.plan))
        command = [sys.executable, str(HARNESS / "scenario_replay.py"), "run", "--plan", str(path), "--payloads", str(self.payloads), "--output", str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        result = subprocess.run([*command, "--apply"], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.root / "receipt.json"
        receipt.write_text(result.stdout)
        result = subprocess.run([sys.executable, str(HARNESS / "scenario_replay.py"), "inspect", "--directory", str(self.output), "--receipt", str(receipt)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_counts(json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
