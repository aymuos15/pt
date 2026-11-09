"""Format/consistency controls, not semantic conformance or benchmark samples."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
try:
    import evidence
    import finalization
    import paired
    import paired_lifecycle as driver
    import pt_bench as timer
    import raw_capture  # Load optional lazy imports before restoring the test path.
    from inspect_run import inspect_run
    from summarize_run import summarize_run
finally:
    sys.path.pop(0)


def nodes(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from nodes(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, (*path, index))


def at(value, path):
    for key in path:
        value = value[key]
    return value


@unittest.skipUnless(sys.platform == "linux", "initial Linux lifecycle/blob profile")
class EvidenceV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "run"
        self.cwds = {arm: self.root / arm for arm in driver.ARMS}
        for path in self.cwds.values():
            path.mkdir()
        self.payload = b"done\n"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.command = [sys.executable, "-c", (
            "from pathlib import Path; Path('report').write_bytes(b'done\\n'); print('done')"
        )]
        self.contract = {"expected_exit_code": 0, "artifacts": [
            {"path": "report", "bytes": len(self.payload), "sha256": self.digest}], "absent": ["lease"]}
        self.guard = {"expected_exit_code": 0, "expected_stdout_bytes": len(self.payload),
                      "expected_stdout_sha256": self.digest}
        options = {f"{arm}_{key}": value for arm in driver.ARMS for key, value in
                   (("cwd", self.cwds[arm]), ("guard", self.guard), ("finalization", self.contract))}
        options.update(baseline_prepare=self.command, baseline_probe=self.command, baseline_probe_guard=self.guard,
                       baseline_prepare_finalization=self.contract, baseline_probe_finalization=self.contract)
        paired.run_pairs(self.output, self.root, self.command, self.command, 1, 3, 5, capture_raw=True, **options)
        self.sample_name = "block-000001-baseline.json"
        self.receipt_name = f"receipt-{self.sample_name}"
        self.records = {"paired-plan": self.read("schedule.json"), "sample": self.read(self.sample_name),
                        "receipt": self.read(self.receipt_name)}

    def read(self, name, *, output=None):
        return json.loads(((output or self.output) / name).read_text())

    def save(self, name, value):
        (self.output / name).write_text(json.dumps(value))

    def rewrite_receipt_and_bound_sample(self, receipt):
        """Keep byte bindings intact so they cannot mask the tested inconsistency."""
        sample = {"schema_version": 2, "mode": "exploratory", "result": receipt["result"],
                  "required_finalization": {"requirements": receipt["required_finalization"]["requirements"],
                                            "observed": receipt["required_finalization"]["before_publication"]}}
        sample.update({key: receipt[key] for key in
                       ("context", "guard_expectations", "observation_guard", "artifact_archive")})
        raw = (json.dumps(sample) + "\n").encode()
        (self.output / self.sample_name).write_bytes(raw)
        receipt["sample"] = {"name": self.sample_name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self.save(self.receipt_name, receipt)

    def test_all_schemas_and_references_are_valid_and_offline(self):
        schemas = [json.loads((HARNESS / f"{name}-v2.schema.json").read_text())
                   for name in ("lifecycle", *evidence.SCHEMAS)]
        registry = Registry().with_resources((item["$id"], Resource.from_contents(item)) for item in schemas)
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
            for _, item in nodes(schema):
                if isinstance(item, dict) and "$ref" in item:
                    registry.resolver(base_uri=schema["$id"]).lookup(item["$ref"])
        for kind, record in self.records.items():
            evidence.validate_v2(kind, record)
        self.assertFalse(inspect_run(self.output)["confirmatory_eligible"])

    def test_unknown_fields_at_every_observed_object_depth_are_rejected(self):
        for kind, original in self.records.items():
            for path, item in nodes(original):
                if isinstance(item, dict):
                    changed = copy.deepcopy(original)
                    at(changed, path)["unexpected"] = True
                    with self.subTest(kind=kind, path=path), self.assertRaisesRegex(ValueError, "schema"):
                        evidence.validate_v2(kind, changed)

    def test_required_fields_at_every_observed_object_depth_are_rejected(self):
        for kind, original in self.records.items():
            for path, item in nodes(original):
                if isinstance(item, dict):
                    for key in item:
                        # Raw capture is optional structurally, but its presence
                        # is enforced against the paired plan by semantic checks.
                        if key == "raw_capture":
                            continue
                        changed = copy.deepcopy(original)
                        del at(changed, path)[key]
                        with self.subTest(kind=kind, path=(*path, key)), self.assertRaisesRegex(ValueError, "schema"):
                            evidence.validate_v2(kind, changed)

    def test_integer_fields_reject_booleans_and_integral_float_tokens_through_refs(self):
        for kind, original in self.records.items():
            for path, item in nodes(original):
                if type(item) is int and path != ("timeout_seconds",):
                    for replacement in (True, float(item)):
                        changed = copy.deepcopy(original)
                        at(changed, path[:-1])[path[-1]] = replacement
                        with self.subTest(kind=kind, path=path, value=replacement), self.assertRaises(ValueError):
                            evidence.validate_v2(kind, changed)

    def test_boolean_fields_reject_integers_even_for_const_and_enum_values(self):
        for kind, original in self.records.items():
            for path, item in nodes(original):
                if type(item) is bool:
                    changed = copy.deepcopy(original)
                    at(changed, path[:-1])[path[-1]] = int(item)
                    with self.subTest(kind=kind, path=path), self.assertRaises(ValueError):
                        evidence.validate_v2(kind, changed)

    def test_wrong_null_and_container_types_are_rejected_before_semantic_access(self):
        paths = {
            "paired-plan": [("host_metadata",), ("commands", "baseline"), ("timeout_seconds",), ("cwd",), ("limitations",)],
            "sample": [("result",), ("required_finalization", "observed"), ("context", "block"), ("artifact_archive", "artifacts")],
            "receipt": [("lifecycle",), ("required_finalization", "after_publication"), ("errors",), ("sample", "name")],
        }
        for kind, targets in paths.items():
            for path in targets:
                for wrong in (None, [], {}, 0, ""):
                    if isinstance(at(self.records[kind], path), list) and isinstance(wrong, list):
                        continue
                    changed = copy.deepcopy(self.records[kind])
                    at(changed, path[:-1])[path[-1]] = wrong
                    with self.subTest(kind=kind, path=path, wrong=wrong), self.assertRaises(ValueError):
                        evidence.validate_v2(kind, changed)

    def test_nan_infinity_overflow_duplicate_keys_and_deep_inputs_fail_closed(self):
        for number in (float("nan"), float("inf"), -float("inf")):
            changed = copy.deepcopy(self.records["paired-plan"])
            changed["timeout_seconds"] = number
            with self.assertRaisesRegex(ValueError, "non-finite"):
                evidence.validate_v2("paired-plan", changed)
        for raw in ('{"value":1e999}', '{"value":NaN}', '{"value":1,"value":2}',
                    '{"value":' + '[' * 1200 + '0' + ']' * 1200 + '}'):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                finalization.parse_json(raw)
        cyclic = {}
        cyclic["cycle"] = cyclic
        with self.assertRaisesRegex(ValueError, "nesting"):
            evidence.validate_v2("paired-plan", cyclic)
        with self.assertRaisesRegex(ValueError, "non-JSON"):
            evidence.validate_v2("sample", {"not_json": (1, 2)})

    def test_negative_durations_bad_paths_digests_and_incomplete_clocks_are_rejected(self):
        mutations = [
            ("receipt", ("lifecycle", "elapsed_ns"), -1),
            ("sample", ("result", "cwd"), "relative"),
            ("sample", ("result", "stdout_sha256"), "z" * 64),
            ("sample", ("result", "stdout_sha256"), "a" * 64 + "\n"),
            ("receipt", ("sample", "name"), "../other.json"),
            ("receipt", ("sample", "bytes"), 1048577),
            ("receipt", ("artifact_archive", "artifacts", 0, "path"), "x/../report"),
            ("paired-plan", ("finalization", "baseline", "measurement", "absent"), ["./lease"]),
            ("paired-plan", ("finalization", "baseline", "measurement", "absent"), ["ok\n/../lease"]),
            ("paired-plan", ("commands", "baseline", "measurement"), [""]),
            ("paired-plan", ("commands", "baseline", "measurement"), ["bad\x00command"]),
            ("sample", ("result", "clock_domain"), "child_monotonic"),
        ]
        for kind, path, value in mutations:
            changed = copy.deepcopy(self.records[kind])
            at(changed, path[:-1])[path[-1]] = value
            with self.subTest(kind=kind, path=path, value=value), self.assertRaises(ValueError):
                evidence.validate_v2(kind, changed)

    def test_plan_inspection_enforces_metadata_timeout_and_unknown_field_contracts(self):
        original = self.records["paired-plan"]
        for key, value in (("host_metadata", None), ("timeout_seconds", 0), ("timeout_seconds", True),
                           ("timeout_seconds", "5"), ("limitations", []), ("unknown", True)):
            changed = {**original, key: value}
            self.save("schedule.json", changed)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                inspect_run(self.output)
        raw = json.dumps(original).replace('"timeout_seconds": 5', '"timeout_seconds": 1e999')
        (self.output / "schedule.json").write_text(raw)
        checked = subprocess.run([sys.executable, str(HARNESS / "inspect_run.py"), str(self.output)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertNotIn("Traceback", checked.stderr)

    def test_malformed_plan_production_stops_before_work_or_output_creation(self):
        for timeout in (True, "5"):
            output = self.root / f"invalid-{timeout}"
            with mock.patch.object(timer, "measure") as measured:
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    paired.run_pairs(output, self.root, self.command, self.command, 1, 3, timeout)
                measured.assert_not_called()
            self.assertFalse(output.exists())
        output = self.root / "invalid-host"
        with mock.patch.object(driver, "collect_metadata", return_value={}), mock.patch.object(timer, "measure") as measured:
            with self.assertRaisesRegex(ValueError, "schema"):
                paired.run_pairs(output, self.root, self.command, self.command, 1, 3, 5)
            measured.assert_not_called()
        self.assertFalse(output.exists())

    def test_invalid_context_stops_before_invocation(self):
        for context in ({"arm": "baseline"}, {"stage": "measurement", "block": True, "position": 1, "arm": "baseline"}):
            with mock.patch.object(timer, "measure") as measured:
                with self.subTest(context=context), self.assertRaisesRegex(ValueError, "context"):
                    timer.measure_and_publish(self.command, str(self.root), 5, self.root / "invalid-sample.json", context=context)
                measured.assert_not_called()

    def test_valid_skipped_preparation_and_probe_records_remain_in_denominator(self):
        failed = [sys.executable, "-c", "raise SystemExit(7)"]
        for stage in ("prepare", "probe"):
            output = self.root / f"skip-{stage}"
            paired.run_pairs(output, self.root, self.command, self.command, 1, 3, 5, **{f"baseline_{stage}": failed})
            record = self.read(self.sample_name, output=output)
            evidence.validate_v2("sample", record)
            self.assertEqual(record["result"]["status"], f"not_run_{'preparation' if stage == 'prepare' else 'probe'}_failed")
            self.assertFalse((output / self.receipt_name).exists())
            summary = summarize_run(output)
            self.assertEqual(summary["planned_arm_count"], 2)
            self.assertEqual(sum(summary["arm_status_counts"].values()), 2)
            self.assertEqual(summary["status"], "blocked")
            self.assertIsNone(summary["ratio"])
            record["context"]["stage"] = "probe"
            with self.assertRaises(ValueError):
                evidence.validate_v2("sample", record)

    def test_launch_timeout_and_unexpected_nonzero_records_are_valid_unqualified_failures(self):
        scenarios = [("launch", ["/nonexistent/pt-v2-schema-command"], 5, "launch_error"),
                     ("timeout", [sys.executable, "-c", "import time; time.sleep(5)"], 0.05, "timeout"),
                     ("nonzero", [sys.executable, "-c", "raise SystemExit(7)"], 5, "exited_unqualified")]
        for label, command, timeout, status in scenarios:
            output = self.root / label
            paired.run_pairs(output, self.root, command, command, 1, 3, timeout,
                             baseline_guard=self.guard, candidate_guard=self.guard)
            receipt = self.read(self.receipt_name, output=output)
            evidence.validate_v2("receipt", receipt)
            evidence.validate_v2("sample", self.read(self.sample_name, output=output))
            self.assertEqual(receipt["result"]["status"], status)
            summary = summarize_run(output)
            self.assertEqual(summary["planned_arm_count"], 2)
            self.assertEqual(summary["status"], "blocked")
            self.assertIsNone(summary["ratio"])
            self.assertFalse(summary["confirmatory_eligible"])

    def test_measurement_failure_without_result_or_binding_has_valid_abort_receipt(self):
        output = self.root / "measurement-failed"
        with mock.patch.object(timer, "measure", side_effect=OSError("injected measurement failure")) as measured:
            with self.assertRaises(paired.RunAbortedError):
                paired.run_pairs(output, self.root, self.command, self.command, 2, 0, 5)
            self.assertEqual(measured.call_count, 1)
        receipt = self.read(self.receipt_name, output=output)
        abort = self.read("abort.json", output=output)
        evidence.validate_v2("receipt", receipt)
        evidence.validate_v2("paired-abort", abort)
        self.assertIsNone(receipt["result"])
        self.assertIsNone(receipt["sample"])
        summary = summarize_run(output)
        self.assertEqual(summary["planned_arm_count"], 4)
        self.assertEqual(summary["observed_arm_count"], 1)
        self.assertEqual(summary["arm_status_counts"]["not_run_run_aborted"], 3)
        self.assertEqual(summary["status"], "blocked")
        self.assertIsNone(summary["bootstrap"])
        for missing in ("errors", "required_finalization"):
            changed = copy.deepcopy(receipt)
            del changed[missing]
            with self.assertRaises(ValueError):
                evidence.validate_v2("receipt", changed)
        receipt["errors"] = []
        with self.assertRaises(ValueError):
            evidence.validate_v2("receipt", receipt)

    def test_publication_failure_keeps_result_without_binding_and_blocks_analysis(self):
        output = self.root / "publication-failed"
        original = timer.write_record

        def fail(path, record):
            if Path(path).name == self.sample_name:
                raise OSError("injected sample publication failure")
            return original(path, record)

        with mock.patch.object(timer, "write_record", fail), self.assertRaises(paired.RunAbortedError):
            paired.run_pairs(output, self.root, self.command, self.command, 2, 0, 5)
        receipt = self.read(self.receipt_name, output=output)
        evidence.validate_v2("receipt", receipt)
        evidence.validate_v2("paired-abort", self.read("abort.json", output=output))
        self.assertIsNotNone(receipt["result"])
        self.assertIsNone(receipt["sample"])
        self.assertIsNone(summarize_run(output)["ratio"])
        receipt["errors"] = []
        with self.assertRaises(ValueError):
            evidence.validate_v2("receipt", receipt)

    def test_incomplete_timeout_cleanup_remains_valid_aborted_evidence(self):
        output = self.root / "incomplete-timeout"
        original = timer.measure

        def incomplete(*args, **kwargs):
            result = original(*args, **kwargs)
            # Explicitly synthetic record mutation, not evidence of a leaked child.
            result.update(status="timeout", process_reaped=False, output_complete=False, returncode=None)
            return result

        with mock.patch.object(timer, "measure", incomplete), self.assertRaises(paired.RunAbortedError):
            paired.run_pairs(output, self.root, self.command, self.command, 2, 0, 5)
        evidence.validate_v2("receipt", self.read(self.receipt_name, output=output))
        self.assertEqual(inspect_run(output)["record_consistency"], "aborted")
        self.assertEqual(summarize_run(output)["planned_arm_count"], 4)

    def test_receipt_and_sample_inspectors_enforce_schemas_despite_rebound_bytes(self):
        for mutate in (
            lambda value: value["required_finalization"]["after_publication"].update(unknown=True),
            lambda value: value["result"].update(stdout_bytes=True),
            lambda value: value["context"].update(block=1.0),
        ):
            changed = copy.deepcopy(self.records["receipt"])
            mutate(changed)
            self.rewrite_receipt_and_bound_sample(changed)
            with self.assertRaisesRegex(ValueError, "schema"):
                inspect_run(self.output)
        self.rewrite_receipt_and_bound_sample(copy.deepcopy(self.records["receipt"]))
        record = self.read(self.sample_name)
        record["unknown"] = True
        raw = json.dumps(record).encode()
        (self.output / self.sample_name).write_bytes(raw)
        changed = copy.deepcopy(self.records["receipt"])
        changed["sample"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.save(self.receipt_name, changed)
        with self.assertRaisesRegex(ValueError, "sample schema"):
            inspect_run(self.output)

    def test_schema_valid_reference_and_clock_contradictions_still_fail_semantic_checks(self):
        mutations = [
            lambda value: value["lifecycle"].update(elapsed_ns=value["lifecycle"]["elapsed_ns"] + 1),
            lambda value: value["sample"].update(name="other.json"),
            lambda value: value["context"].update(block=2),
            lambda value: value["artifact_archive"]["artifacts"][0].update(path="undeclared"),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(self.records["receipt"])
            mutate(changed)
            evidence.validate_v2("receipt", changed)
            self.save(self.receipt_name, changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                inspect_run(self.output)

    def test_failed_receipts_do_not_bypass_checks_of_either_observation(self):
        # Exit mismatch is a legitimate failed observation, not a schema error.
        failed = copy.deepcopy(self.records["receipt"])
        failed["lifecycle"]["status"] = "finalization_failed"
        failed["result"]["returncode"] = 7
        failed["observation_guard"]["matched_expected_observations"] = False
        failed["observation_guard"]["mismatches"] = ["exit_code"]
        for stage in ("before_publication", "after_publication"):
            observed = failed["required_finalization"][stage]
            observed["matched"] = False
            next(item for item in observed["checks"] if item["kind"] == "expected_exit_code")["matched"] = False
        self.rewrite_receipt_and_bound_sample(failed)
        self.assertEqual(summarize_run(self.output)["status"], "blocked")
        for stage in ("before_publication", "after_publication"):
            for mutation in ("aggregate", "omission", "reference", "digest_verdict", "identity", "process"):
                changed = copy.deepcopy(failed)
                observed = changed["required_finalization"][stage]
                item = next(item for item in observed["checks"] if item["kind"] == "artifact")
                if mutation == "aggregate":
                    observed["matched"] = True
                elif mutation == "omission":
                    observed["checks"].pop()
                elif mutation == "reference":
                    item["path"] = "undeclared"
                elif mutation == "digest_verdict":
                    item["matched"] = False
                elif mutation == "identity":
                    item["identity"][2] += 1
                else:
                    observed["checks"][0]["matched"] = False
                evidence.validate_v2("receipt", changed)
                self.rewrite_receipt_and_bound_sample(changed)
                with self.subTest(stage=stage, mutation=mutation), self.assertRaises(ValueError):
                    inspect_run(self.output)

    def test_raw_capture_contract_cannot_be_removed_or_contradicted(self):
        for mutation in ("omitted", "truncated", "digest"):
            changed = copy.deepcopy(self.records["receipt"])
            if mutation == "omitted":
                del changed["result"]["raw_capture"]
            elif mutation == "truncated":
                changed["result"]["raw_capture"]["stdout"]["truncated"] = True
            else:
                changed["result"]["raw_capture"]["stdout"]["sha256"] = "0" * 64
            evidence.validate_v2("receipt", changed)
            self.rewrite_receipt_and_bound_sample(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                inspect_run(self.output)

    def test_legacy_schema_is_separate_and_never_accepts_v2_samples(self):
        legacy = json.loads((HARNESS / "sample.schema.json").read_text())
        self.assertFalse(Draft202012Validator(legacy).is_valid(self.records["sample"]))
        changed = copy.deepcopy(self.records["sample"])
        changed["schema_version"] = 1
        with self.assertRaises(ValueError):
            evidence.validate_v2("sample", changed)
        plan = copy.deepcopy(self.records["paired-plan"])
        plan["timing_endpoint"] = timer.COMMAND_ENDPOINT
        with self.assertRaises(ValueError):
            evidence.validate_v2("paired-plan", plan)

    def test_abort_envelopes_and_nested_diagnostic_receipts_are_strict(self):
        abort = {"schema_version": 2, "mode": "exploratory_unqualified", "context": self.records["receipt"]["context"],
                 "reason": "receipt_publication_failed", "error": "injected failure", "receipt": self.records["receipt"]}
        evidence.validate_v2("paired-abort", abort)
        for path, value in ((('context', 'block'), True), (('receipt',), None), (('error',), ""),
                            (('receipt', 'result', 'stdout_bytes'), 5.0), (('reason',), "unknown")):
            changed = copy.deepcopy(abort)
            at(changed, path[:-1])[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                evidence.validate_v2("paired-abort", changed)
        harness_error = {**abort, "reason": "harness_error", "receipt": None}
        evidence.validate_v2("paired-abort", harness_error)
        harness_error["receipt"] = self.records["receipt"]
        with self.assertRaises(ValueError):
            evidence.validate_v2("paired-abort", harness_error)

    def test_extended_standalone_receipt_allows_null_context_guard_or_archive(self):
        for option in ("guard", "archive"):
            output = self.root / f"extended-{option}.json"
            receipt = timer.measure_and_publish(
                self.command, str(self.root), 5, output,
                guard_expectations=self.guard if option == "guard" else None,
                archive_bundle=self.output / "blobs" if option == "archive" else None,
            )
            evidence.validate_v2("receipt", receipt)
            self.assertIsNone(receipt["context"])
            self.assertTrue(timer.inspect_lifecycle(output, receipt)["lifecycle_finalized"])


if __name__ == "__main__":
    unittest.main()
