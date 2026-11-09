"""Offline evidence-bound whole-session cards; declarations never become qualification."""

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
import paired_replay as pairs
import result_card as common
from pt_bench import _same_json


KIND = "paired_replay_exploratory_result_card"
TOKEN_KIND = "paired_replay_result_card"
HARNESS = Path(__file__).resolve().parent
INVENTORY_FORMAT = "sha256_canonical_recursive_replay_inventory_v1"
UNRESOLVED_FIELDS = (*common.UNRESOLVED_FIELDS, "matched_replay_inputs_and_external_state",
                     "independent_block_count", "whole_session_resource_accounting")
SOURCE_FILES = tuple(sorted(set(common.SOURCE_FILES) | {
    "replay_result_card.py", "replay-result-card-v1.schema.json", "paired_replay.py", "paired-replay-v1.schema.json",
    "managed_replay.py", "managed-replay-v1.schema.json", "inspect_replay.py",
}))
LIMITATIONS = [
    "exploratory whole-session report only; no test-pass, equal-work, generation, support or release qualification",
    "all planned completed, aborted, not-run and unknown sessions remain visible; interactions are not independent samples",
    "shared input/edit/state pins are declarations, not verified identities or evidence that edits or seeds were applied",
    "source and evidence hashes bind bytes read, not authenticity, provenance or executed-code identity",
    "generator runtime and plan host observations are not measured-arm environment identities",
    "known wall intervals do not establish full-session resource, idle, reset or work equivalence; unknown metrics remain null",
    "exploratory bootstrap draws whole paired sessions; actual independent session and block counts remain unknown",
    "before/after fingerprints are not an atomic snapshot or a hostile-directory security boundary",
    "card generation and publication are offline observer work outside all session endpoints; no estimated tax is subtracted",
    "private no-overwrite publication is not authentication or a power-loss-durability guarantee",
]


def _inventory(directories, entries):
    content = {"directories": sorted(directories), "files": sorted(entries, key=lambda item: item["path"])}
    return {"format": INVENTORY_FORMAT,
            "sha256": hashlib.sha256(b"pt:replay-result-card:inventory:v1\n" + common._canonical(content)).hexdigest(),
            "total_bytes": sum(item["bytes"] for item in entries), **content}


def capture_evidence(directory):
    snapshot = pairs._snapshot(directory)
    entries = [{"path": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]}
               for name, metadata in snapshot[0].items()]
    directories = []
    for name, (inventory, _identities) in snapshot[1].items():
        directories.append(name)
        directories.extend(name + "/" + path for path in inventory["directories"])
        entries.extend({**item, "path": name + "/" + item["path"]} for item in inventory["files"])
    return _inventory(directories, entries), snapshot


def capture_implementation():
    entries, identities = common._files(HARNESS, SOURCE_FILES)
    return _inventory([], entries), identities


@lru_cache(maxsize=1)
def _validator():
    names = ("replay-result-card-v1.schema.json", "paired-replay-v1.schema.json", "managed-replay-v1.schema.json",
             "result-card-v1.schema.json", "lifecycle-v2.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
    schemas = [json.loads((HARNESS / name).read_text()) for name in names]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return StrictValidator(schemas[0], registry=registry)


def validate_card(card):
    """Closed schema and size checks only; full source-bound reconstruction is mandatory."""
    validate_json_types(card)
    error = next(_validator().iter_errors(card), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"replay result-card schema at {path}: violates {error.validator}")
    if len(common._serialized(card)) > common.MAX_CARD_BYTES:
        raise ValueError("replay result card exceeds byte limit; no session or evidence entry may be truncated")


def _rows(observations, plan):
    contexts = [pairs._context(block["block"], position, arm)
                for block in plan["schedule"] for position, arm in enumerate(block["order"], 1)]
    if not _same_json([row["context"] for row in observations], contexts):
        raise ValueError("replay result card must retain exactly every planned session in schedule order")
    result = []
    for row in observations:
        inner = row["replay_summary"]
        session = plan["sessions"][row["context"]["arm"]]
        result.append({
            "context": row["context"], "sample_unit": replay.UNIT, "measurement_layer": "managed_replay",
            **{key: row[key] for key in ("status", "invocation_attempted", "receipt_record_committed", "session_record_committed",
                                        "elapsed_ns", "phase_guard_counts", "failure_reasons")},
            "planned_phase_count": len(replay._steps(session)), "planned_interaction_count": len(session["interactions"]),
            "observed_phase_status_counts": inner["phase_status_counts"] if inner is not None else None,
            "observed_interaction_status_counts": inner["interaction_status_counts"] if inner is not None else None,
            "phase_invocation_counts": ({"known_attempted": inner["known_phase_invocation_attempts"],
                                         "unknown": inner["unknown_phase_invocations"], "not_invoked": inner["known_not_invoked_phases"]}
                                        if inner is not None else None),
            "shutdown_status": inner["shutdown_status"] if inner is not None else None,
            "raw_capture_truncated_phase_count": inner["raw_capture_truncated_phase_count"] if inner is not None else None,
            "unconfirmed_diagnostic_fragment_count": inner["unconfirmed_diagnostic_fragment_count"] if inner is not None else None,
            "outcome_reasons": inner["outcome_reasons"] if inner is not None else None,
        })
    return result


def build(directory, *, bootstrap_resamples=None, bootstrap_seed=None):
    directory = Path(directory)
    evidence, evidence_identity = capture_evidence(directory)
    implementation = capture_implementation()
    observations = []
    summary = common.summarize_run(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed,
                                   _observations=observations)
    plan, _ = files.read_json(directory / "schedule.json")
    pairs.validate_plan(plan)
    if summary.get("kind") != pairs.KIND or not _same_json(observations, summary["session_observations"]):
        raise ValueError("replay result card requires one consistently inspected paired replay campaign")
    rows = _rows(observations, plan)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    if (counts != summary["session_status_counts"] or len(rows) != summary["planned_session_count"]
            or len(rows) != 2 * len(plan["schedule"])):
        raise ValueError("replay result-card denominators contradict inspected summary")
    interactions = Counter()
    for row in rows:
        if row["observed_interaction_status_counts"] is not None:
            interactions.update(row["observed_interaction_status_counts"])
    abort = None
    if "abort.json" in evidence_identity[0]:
        source, _ = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)
        abort = {**{key: source[key] for key in ("context", "reason", "error")},
                 **{field + "_present": source[field] is not None for field in
                    ("diagnostic_receipt", "diagnostic_session", "diagnostic_inputs")}}
    card = {
        "schema_version": 1, "kind": KIND, "classification": "exploratory", "confirmatory_eligible": False,
        "sample_unit": replay.UNIT, "measurement_layer": "managed_replay", "timing_endpoint": replay.ENDPOINT,
        "qualification": {"status": "not_established", "qualified_session_count": 0,
                          "unresolved_fields": {field: None for field in UNRESOLVED_FIELDS}},
        "denominators": {
            "planned_blocks": summary["blocks"], "planned_sessions": len(rows), "observed_sessions": summary["observed_session_count"],
            **{key: summary[key] for key in ("known_session_invocations", "unknown_session_invocations", "known_not_invoked_sessions",
                                            "session_status_counts", "observed_phase_status_counts", "not_run_phase_count", "unknown_phase_count",
                                            "verified_independent_sessions", "verified_independent_blocks")},
            "planned_phase_count": sum(row["planned_phase_count"] for row in rows),
            "planned_interaction_count": sum(row["planned_interaction_count"] for row in rows),
            "observed_interaction_status_counts": dict(sorted(interactions.items())),
            "not_run_interaction_count": sum(row["planned_interaction_count"] for row in rows if row["invocation_attempted"] is False),
            "unknown_interaction_count": sum(row["planned_interaction_count"] for row in rows if row["invocation_attempted"] is None),
        },
        "session_observations": rows,
        "campaign": {**{key: summary[key] for key in ("record_consistency", "recorded_interval_order", "infrastructure_failure")}, "abort": abort},
        "blockers": summary["blockers"], "analysis_request": {"bootstrap_resamples": bootstrap_resamples, "bootstrap_seed": bootstrap_seed},
        "statistics": {key: summary[key] for key in ("status", "ratio_direction", "ratio", "absolute_latency_ns", "bootstrap",
                                                     "latency_unit", "resampling_unit", "resource_observation", "whole_boundary_resource_accounting_complete")},
        "context": {"schedule": plan["schedule"], "schedule_seed": plan["seed"], "sessions": plan["sessions"], "pairing": plan["pairing"],
                    "pairing_identity_status": summary["pairing_identity_status"], "host_observations": plan["host_metadata"]},
        "evidence": evidence, "generator": {"implementation": implementation[0], "runtime": common._runtime()},
        "limitations": LIMITATIONS.copy(),
    }
    card["reconstruction_sha256"] = hashlib.sha256(b"pt:replay-result-card:reconstruction:v1\n" + common._canonical({
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
        raise ValueError("replay result-card evidence or implementation changed during generation/publication")


def inspect_card(card, directory):
    validate_card(card)
    expected = common.generate_result_card(directory, **card["analysis_request"])
    if not _same_json(expected, card):
        raise ValueError("replay result card differs from reconstructed evidence, sessions, analysis or qualification fields")
    return {"card_consistency": "checked_unqualified", "classification": "exploratory", "confirmatory_eligible": False,
            "sample_unit": replay.UNIT, "status": card["statistics"]["status"],
            "planned_session_count": card["denominators"]["planned_sessions"], "session_status_counts": card["denominators"]["session_status_counts"],
            "unknown_session_invocations": card["denominators"]["unknown_session_invocations"],
            "evidence_sha256": card["evidence"]["sha256"], "reconstruction_sha256": card["reconstruction_sha256"]}
