"""Offline source-bound resource-replay cards; observations never become qualification."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
import finalization as files
import managed_replay as replay
import paired_replay_resources as pairs
import result_card as common
from pt_bench import _same_json


KIND = "paired_replay_resource_exploratory_result_card"
TOKEN_KIND = "paired_replay_resource_result_card"
HARNESS = Path(__file__).resolve().parent
INVENTORY_FORMAT = "sha256_canonical_recursive_resource_replay_inventory_v1"
UNRESOLVED_FIELDS = (*common.UNRESOLVED_FIELDS, "matched_replay_inputs_and_external_state",
                     "independent_block_count", "whole_session_resource_accounting")
SOURCE_FILES = tuple(sorted(set(common.SOURCE_FILES) | {
    "replay_resource_card.py", "replay-resource-card-v1.schema.json", "paired_replay_resources.py", "paired-replay-resource-v1.schema.json",
    "replay_resources.py", "replay-resource-v1.schema.json", "replay_resource_driver.py", "cgroup_exec.py",
    "paired_replay.py", "paired-replay-v1.schema.json", "managed_replay.py", "managed-replay-v1.schema.json",
    "replay-result-card-v1.schema.json", "raw_capture.py", "blob_store.py",
}))
LIMITATIONS = [
    "offline exploratory whole-session resource report; no subject invocation, latency comparison or qualification",
    "all planned combined diagnostic and managed replay outcomes remain visible, including unsupported, failed, not-run and unknown",
    "observed counters and complete-accounting flags do not qualify native peak, equal budgets, resets, semantic work or generations",
    "failed-unit costs remain in observed sums; missing metrics remain null and are not imputed as zero",
    "memory maxima are per observed session, never a campaign-wide simultaneous peak or sum of process peaks",
    "driver overhead is charged; outer observer and offline card work are excluded from cgroup totals without subtraction",
    "shared pins, generator runtime and host observations are declarations, not verified arm identities or independence",
    "source and evidence hashes bind bytes read, not authenticity, provenance or executed-code identity",
    "driver and outer-observer clocks remain separate; no cross-process clock arithmetic or isolated idle attribution",
    "fingerprints are not an atomic or hostile-directory boundary; private no-overwrite publication is not power-loss durable",
]
DENOMINATOR_FIELDS = (
    "unit_observation_count", "known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions",
    "known_boundary_invocations", "unknown_boundary_invocations", "known_not_invoked_boundaries", "session_status_counts",
    "replay_session_status_counts", "planned_phase_count", "phase_status_counts", "known_phase_invocation_attempts",
    "known_not_invoked_phases", "unknown_phase_invocations", "planned_interaction_count", "interaction_status_counts",
    "verified_independent_sessions", "verified_independent_blocks",
)
ROW_FIELDS = (
    "context", "measurement_layer", "sample_unit", "status", "resource_status", "session_status", "session_invocation_attempted",
    "boundary_run_attempted", "unit_observation_returned", "receipt_record_committed", "session_record_committed", "phase_guard_counts",
    "elapsed_ns", "planned_phase_count", "planned_interaction_count", "phase_status_counts", "interaction_status_counts",
    "known_phase_invocation_attempts", "known_not_invoked_phases", "unknown_phase_invocations", "shutdown_status",
    "driver_completion_confirmed", "resource_record_confirmed", "counter_boundary_accounting_complete", "whole_session_accounting_complete",
    "observer_process", "driver_process", "cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes", "memory_events_delta",
    "unsupported_capabilities", "resource_failure_reasons", "failure_reasons",
)
STATISTIC_FIELDS = (
    "status", "per_arm_resources", "per_arm_resources_unit", "memory_metric", "whole_campaign_peak_charged_bytes",
    "idle_only_resource_metrics", "per_phase_resource_metrics", "ratio", "absolute_latency_ns", "bootstrap",
)


def _inventory(directories, entries):
    content = {"directories": sorted(directories), "files": sorted(entries, key=lambda item: item["path"])}
    return {"format": INVENTORY_FORMAT,
            "sha256": hashlib.sha256(b"pt:replay-resource-card:inventory:v1\n" + common._canonical(content)).hexdigest(),
            "total_bytes": sum(item["bytes"] for item in entries), **content}


def capture_evidence(directory):
    snapshot = pairs._snapshot(directory)
    entries = [{"path": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]} for name, metadata in snapshot[0].items()]
    directories = []
    for name, (inventory, _identities) in snapshot[1].items():
        directories.extend([name, *[name + "/" + path for path in inventory["directories"]]])
        entries.extend({**item, "path": name + "/" + item["path"]} for item in inventory["files"])
    return _inventory(directories, entries), snapshot


def capture_implementation():
    entries, identities = common._files(HARNESS, SOURCE_FILES)
    return _inventory([], entries), identities


@lru_cache(maxsize=1)
def _validator():
    names = ("replay-resource-card-v1.schema.json", "paired-replay-resource-v1.schema.json", "replay-resource-v1.schema.json",
             "paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "resource-observation-v1.schema.json",
             "lifecycle-v2.schema.json", "result-card-v1.schema.json", "replay-result-card-v1.schema.json", "paired-resource-v1.schema.json")
    schemas = [json.loads((HARNESS / name).read_text()) for name in names]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return StrictValidator(schemas[0], registry=registry)


def validate_card(card):
    """Structural/size checks only; independent source reconstruction is mandatory."""
    validate_json_types(card)
    error = next(_validator().iter_errors(card), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"resource replay card schema at {path}: violates {error.validator}")
    if len(common._serialized(card)) > common.MAX_CARD_BYTES:
        raise ValueError("resource replay card exceeds byte limit; no outcome or evidence entry may be truncated")


def _details(directory, row, abort):
    result = {key: None for key in ("resource_group", "resource_enrollment", "resource_cleanup", "resource_errors", "observer_errors", "driver_error")}
    if not row["unit_observation_returned"]:
        # Even complete-looking raw records after a lost API return are only
        # bound diagnostics. Do not manufacture confirmed metrics or observations.
        return result
    unit_name, receipt_name, _ = pairs._names(row["context"]["block"], row["context"]["arm"])
    receipt = (files.read_json(directory / receipt_name, limit=files.MAX_RECEIPT_BYTES)[0] if row["receipt_record_committed"] else
               abort["diagnostic_receipt"])
    resource = (files.read_json(directory / unit_name / "resource.json", limit=files.MAX_RECEIPT_BYTES)[0]
                if receipt["resource"] is not None else receipt["diagnostic_resource"])
    result["observer_errors"] = receipt["errors"]
    if resource is not None:
        result.update(resource_group=resource["group"], resource_enrollment=resource["enrollment"],
                      resource_cleanup=resource["cleanup"], resource_errors=resource["errors"])
    if receipt["driver"] is not None:
        driver, _ = files.read_json(directory / unit_name / "driver.json", limit=files.MAX_RECEIPT_BYTES)
        result["driver_error"] = driver["error"]
    return result


def build(directory, *, bootstrap_resamples=None, bootstrap_seed=None):
    if bootstrap_resamples is not None or bootstrap_seed is not None:
        raise ValueError("bootstrap is unsupported for resource replay cards")
    directory = Path(directory)
    evidence, evidence_identity = capture_evidence(directory)
    implementation = capture_implementation()
    observations = []
    summary = common.summarize_run(directory, _observations=observations)
    plan, _ = files.read_json(directory / "schedule.json")
    pairs.validate_plan(plan)
    if summary.get("kind") != pairs.KIND or not _same_json(observations, summary["session_observations"]):
        raise ValueError("resource replay card requires one consistently inspected diagnostic campaign")
    contexts = [pairs.workflow._context(block["block"], position, arm) for block in plan["schedule"] for position, arm in enumerate(block["order"], 1)]
    if (not _same_json([row["context"] for row in observations], contexts)
            or len(observations) != summary["planned_session_count"] or len(observations) != 2 * len(plan["schedule"])):
        raise ValueError("resource replay card must retain every planned whole session in order")
    abort_source = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)[0] if "abort.json" in evidence_identity[0] else None
    abort = None
    if abort_source is not None:
        abort = {**{key: abort_source[key] for key in ("context", "reason", "error")},
                 **{field + "_present": abort_source[field] is not None for field in ("diagnostic_receipt", "diagnostic_session", "diagnostic_inputs")}}
    rows = []
    for source in observations:
        inner = source["replay_summary"]
        rows.append({**{key: source[key] for key in ROW_FIELDS}, **_details(directory, source, abort_source),
                     "replay_outcome": ({key: inner[key] for key in ("status", "outcome_reasons", "raw_capture_truncated_phase_count",
                                                                    "unconfirmed_diagnostic_fragment_count")} if inner is not None else None)})
    if dict(sorted(Counter(row["status"] for row in rows).items())) != summary["session_status_counts"]:
        raise ValueError("resource replay card denominators contradict the inspected summary")
    card = {
        "schema_version": 1, "kind": KIND, "classification": "exploratory", "confirmatory_eligible": False,
        "sample_unit": replay.UNIT, "measurement_layer": "resource_diagnostic",
        **{key: summary[key] for key in ("resource_endpoint", "resource_scope", "overhead_policy", "clock_alignment")},
        "qualification": {"status": "not_established", "qualified_session_count": 0, "unresolved_fields": {field: None for field in UNRESOLVED_FIELDS}},
        "denominators": {"planned_blocks": summary["blocks"], "planned_sessions": len(rows), "observed_sessions": summary["observed_session_count"],
                         **{key: summary[key] for key in DENOMINATOR_FIELDS}},
        "session_observations": rows,
        "campaign": {**{key: summary[key] for key in ("record_consistency", "recorded_interval_order", "all_session_accounting_complete")}, "abort": abort},
        "blockers": summary["blockers"], "analysis_request": {"bootstrap_resamples": None, "bootstrap_seed": None},
        "statistics": {key: summary[key] for key in STATISTIC_FIELDS},
        "context": {"schedule": plan["schedule"], "schedule_seed": plan["seed"], "sessions": plan["sessions"], "pairing": plan["pairing"],
                    "pairing_identity_status": summary["pairing_identity_status"], "resources": plan["resources"], "driver": plan["driver"],
                    "observer_process": plan["observer_process"], "original_output_root": plan["output_root"], "host_observations": plan["host_metadata"]},
        "evidence": evidence, "generator": {"implementation": implementation[0], "runtime": common._runtime()}, "limitations": LIMITATIONS.copy(),
    }
    card["reconstruction_sha256"] = hashlib.sha256(b"pt:replay-resource-card:reconstruction:v1\n" + common._canonical({
        "evidence_sha256": evidence["sha256"], "implementation_sha256": implementation[0]["sha256"],
        "runtime": card["generator"]["runtime"], "analysis_request": card["analysis_request"],
    })).hexdigest()
    validate_card(card)
    token = (directory, (evidence, evidence_identity), implementation, TOKEN_KIND)
    unchanged(token)
    return card, token


def unchanged(token):
    directory, evidence, implementation, kind = token
    if kind != TOKEN_KIND or capture_evidence(directory) != evidence or capture_implementation() != implementation:
        raise ValueError("resource replay card evidence or implementation changed during generation/publication")


def inspect_card(card, directory):
    validate_card(card)
    expected = common.generate_result_card(directory, **card["analysis_request"])
    if not _same_json(expected, card):
        raise ValueError("resource replay card differs from reconstructed evidence, outcomes, metrics or qualification fields")
    return {"card_consistency": "checked_unqualified", "classification": "exploratory", "confirmatory_eligible": False,
            "measurement_layer": "resource_diagnostic", "sample_unit": replay.UNIT, "status": card["statistics"]["status"],
            "planned_session_count": card["denominators"]["planned_sessions"], "session_status_counts": card["denominators"]["session_status_counts"],
            "replay_session_status_counts": card["denominators"]["replay_session_status_counts"],
            "unknown_session_invocations": card["denominators"]["unknown_session_invocations"],
            "evidence_sha256": card["evidence"]["sha256"], "reconstruction_sha256": card["reconstruction_sha256"]}
