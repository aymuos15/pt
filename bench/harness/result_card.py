"""Evidence-bound exploratory result cards; no qualification or subject execution."""

from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import stat

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import StrictValidator, validate_json_types
from finalization import (
    MAX_ARTIFACT_BYTES, MAX_RECEIPT_BYTES, MAX_TOTAL_BYTES,
    _fingerprint, inspect_file, read_json, relative_path, require_safe_lookup,
)
from pt_bench import COMMAND_ENDPOINT, LIFECYCLE_ENDPOINT, RESOURCE_ENDPOINT, _same_json, write_record
from summarize_run import summarize_run


HARNESS = Path(__file__).resolve().parent
MAX_EVIDENCE_FILES = 4096
MAX_CARD_BYTES = MAX_RECEIPT_BYTES
INVENTORY_FORMAT = "sha256_canonical_relative_path_bytes_digest_inventory_v1"
UNRESOLVED_FIELDS = (
    "candidate_revision", "baseline_revision", "candidate_binary_sha256", "baseline_binary_sha256",
    "arm_python_pytest_plugin_identities", "repository_revision", "scenario_and_cache_state",
    "machine_profile_and_resource_budget", "semantic_contract_and_equal_work",
    "collection_occurrences", "execution_occurrences", "independent_session_count",
    "generation_validity", "reset_policy_compliance", "coverage_configuration_and_artifacts",
    "fallback_accounting", "exclusion_policy_and_accounting", "full_session_and_idle_cost",
    "observer_effects", "corpus_eligibility_and_partitions", "preregistration_and_review",
)
SOURCE_FILES = tuple(sorted((
    "result_card.py", "inspect_result_card.py", "result-card-v1.schema.json",
    "summarize_run.py", "inspect_run.py", "analysis.py", "paired_lifecycle.py", "paired_resources.py",
    "resource_run.py", "cgroup_accounting.py", "artifact_check.py", "manifest.py", "metadata.py",
    "evidence.py", "finalization.py", "guards.py", "pt_bench.py", "schedule.py",
    "sample.schema.json", "lifecycle-v2.schema.json", "paired-plan-v2.schema.json", "sample-v2.schema.json",
    "receipt-v2.schema.json", "paired-abort-v2.schema.json", "resource-observation-v1.schema.json",
    "paired-resource-v1.schema.json", "pyproject.toml", "uv.lock",
)))
LIMITATIONS = [
    "exploratory observations only; no test-pass, equal-work, generation or release qualification",
    "source and evidence hashes bind bytes read, not authenticity, provenance or executed-code identity",
    "before/after fingerprint checks are not an atomic snapshot or a hostile-directory security boundary",
    "generator runtime and plan host metadata are not identities of the measured arm environments",
    "all planned measurement arms are retained; unknown work, exclusions, fallbacks and independence remain unknown",
    "resource diagnostics are separate observations, never latency samples or inferred native peaks",
    "card generation and publication are offline observer work, outside every subject endpoint",
    "card publication is no-overwrite metadata publication, not a power-loss-durability guarantee",
]


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _inventory(directories, files):
    content = {"directories": sorted(directories), "files": sorted(files, key=lambda item: item["path"])}
    digest = hashlib.sha256(b"pt:result-card:inventory:v1\n" + _canonical(content)).hexdigest()
    return {"format": INVENTORY_FORMAT, "sha256": digest, "total_bytes": sum(item["bytes"] for item in files), **content}


def _files(root, names):
    files, identities, total = [], {}, 0
    if len(names) > MAX_EVIDENCE_FILES:
        raise ValueError("result-card source file count exceeds limit")
    for name in sorted(names):
        relative_path(name)
        limit = MAX_ARTIFACT_BYTES if name.startswith("blobs/") else MAX_RECEIPT_BYTES
        metadata, _ = inspect_file(root, name, limit=min(limit, MAX_TOTAL_BYTES - total))
        files.append({"path": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]})
        identities[name] = metadata["identity"]
        total += metadata["bytes"]
    return files, identities


def capture_run(directory):
    """Bound all bytes, including failed/diagnostic fragments; never filter files."""
    require_safe_lookup()
    descriptors, identities, names, directories = [], {}, [], []
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)

        def entries(current, prefix=""):
            with os.scandir(current) as scanned:
                for entry in scanned:
                    name = prefix + entry.name
                    relative_path(name)
                    if not prefix and entry.name == "blobs":
                        child = os.open("blobs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                        descriptors.append(child)
                        identities["blobs/"] = _fingerprint(os.fstat(child))
                        directories.append("blobs")
                        entries(child, "blobs/")
                    else:
                        if len(names) >= MAX_EVIDENCE_FILES:
                            raise ValueError("result-card evidence file count exceeds limit")
                        if not entry.is_file(follow_symlinks=False):
                            raise ValueError("result-card evidence contains a non-regular file or unexpected directory")
                        names.append(name)

        identities["/"] = _fingerprint(os.fstat(fd))
        entries(fd)
        files, file_identities = _files(directory, names)
        identities.update(file_identities)
        for name, descriptor in zip(("/", "blobs/"), descriptors):
            path = directory if name == "/" else directory / "blobs"
            named = os.stat(path, follow_symlinks=False)
            if (not stat.S_ISDIR(named.st_mode) or _fingerprint(named) != identities[name]
                    or _fingerprint(os.fstat(descriptor)) != identities[name]):
                raise ValueError("result-card evidence directory changed during read")
        return _inventory(directories, files), identities
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def capture_implementation():
    files, identities = _files(HARNESS, SOURCE_FILES)
    return _inventory([], files), identities


def _runtime():
    try:
        return {"python_implementation": platform.python_implementation(), "python_version": platform.python_version(),
                "jsonschema_version": version("jsonschema"), "referencing_version": version("referencing"),
                "pyyaml_version": version("PyYAML")}
    except PackageNotFoundError as exc:
        raise ValueError("result-card generator dependency identity unavailable") from exc


@lru_cache(maxsize=1)
def _validator():
    schemas = []
    for name in ("result-card-v1.schema.json", "lifecycle-v2.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json"):
        schema = json.loads((HARNESS / name).read_text())
        Draft202012Validator.check_schema(schema)
        schemas.append(schema)
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    return StrictValidator(schemas[0], registry=registry)


def validate_card(card):
    """Structural/size checks only; source-bound reconstruction is mandatory."""
    validate_json_types(card)
    if isinstance(card, dict) and card.get("kind") == "paired_replay_resource_exploratory_result_card":
        from replay_resource_card import validate_card as validate_resource_replay_card
        return validate_resource_replay_card(card)
    if isinstance(card, dict) and card.get("kind") == "paired_replay_exploratory_result_card":
        from replay_result_card import validate_card as validate_replay_card
        return validate_replay_card(card)
    error = next(_validator().iter_errors(card), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"result-card schema at {path}: violates {error.validator}")
    if len(_serialized(card)) > MAX_CARD_BYTES:
        raise ValueError("result card exceeds byte limit; no arm or evidence entry may be truncated")


def _serialized(card):
    return (json.dumps(card, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _plan_context(plan, endpoint):
    if endpoint != COMMAND_ENDPOINT:
        commands, guards = plan["commands"], plan["guards"]
    else:
        commands = {arm: {"preparation": plan["preparation_argv"][arm],
                          "probe": plan.get("state_probe_argv", {}).get(arm),
                          "measurement": plan[f"{arm}_argv"]} for arm in ("baseline", "candidate")}
        guards = {arm: {"preparation": None, "probe": plan.get("state_probe_guards", {}).get(arm),
                        "measurement": plan.get("guard_expectations", {}).get(arm)} for arm in commands}
    return {"timing_endpoint": endpoint,
            "measurement_layer": {COMMAND_ENDPOINT: "exploratory_command_timing", LIFECYCLE_ENDPOINT: "exploratory_lifecycle_timing",
                                  RESOURCE_ENDPOINT: "resource_diagnostic"}[endpoint],
            "cwd": plan["cwd"], "arm_cwds": plan.get("arm_cwds", {arm: plan["cwd"] for arm in commands}),
            "commands": commands, "guards": guards, "seed": plan["seed"], "timeout_seconds": plan.get("timeout_seconds"),
            "host_observations": plan.get("host_metadata")}


RESOURCE_FIELDS = ("whole_boundary_accounting_complete", "cpu_delta_usec", "peak_charged_bytes", "sampled_current_max_bytes",
                   "unsupported_capabilities", "resource_errors", "stage_errors", "archive_complete",
                   "resource_record_committed", "stage_record_committed", "not_run_record_committed", "finalization_matched")


def _resource_row(source, context):
    expected_guard = context["guards"][source["context"]["arm"]][source["context"]["stage"]]
    matched = source["guard_matched"]
    return {"context": source["context"], "status": source["resource_status"], "invocation_attempted": source["run_attempted"],
            "process_status": source["process_status"], "returncode": source["returncode"], "elapsed_ns": None,
            "guard_status": "matched" if matched is True else "mismatched" if matched is False else
                            "not_requested" if expected_guard is None else "not_observed",
            "lifecycle_finalized": None, "failure_reasons": source["resource_failure_reasons"],
            "resources": {key: source[key] for key in RESOURCE_FIELDS}}


def _measurement_rows(observations, plan, context, directory):
    positions = {(str(block["block"]), arm): {"stage": "measurement", "block": block["block"], "position": position, "arm": arm}
                 for block in plan["schedule"] for position, arm in enumerate(block["order"], 1)}
    if context["timing_endpoint"] == RESOURCE_ENDPOINT:
        rows = [_resource_row(source, context) for source in observations]
    else:
        abort = read_json(directory / "abort.json", limit=MAX_RECEIPT_BYTES)[0] if (directory / "abort.json").exists() else None
        rows = []
        for source in observations:
            result, guard = source["result"], source["guard"]
            status = result["status"]
            attempted = True if status in ("exited_unqualified", "timeout", "launch_error") else None if status == "harness_error" else False
            if status == "harness_error" and abort is not None and abort["context"]["stage"] != "measurement":
                attempted = False
            timing = source.get("timing") if context["timing_endpoint"] == LIFECYCLE_ENDPOINT else result
            rows.append({"context": positions[(source["block"], source["arm"])], "status": status,
                         "invocation_attempted": attempted,
                         "process_status": status if status in ("exited_unqualified", "timeout", "launch_error") else None,
                         "returncode": result.get("returncode"), "elapsed_ns": (timing or {}).get("elapsed_ns"),
                         "guard_status": "not_requested" if guard is None else "matched" if guard["matched_expected_observations"] else "mismatched",
                         "lifecycle_finalized": source.get("lifecycle_finalized"),
                         "failure_reasons": source.get("failure_reasons", []), "resources": None})
    if [row["context"] for row in rows] != list(positions.values()):
        raise ValueError("result card must retain exactly the planned arms in schedule order")
    return rows


def _build(directory, *, bootstrap_resamples=None, bootstrap_seed=None):
    directory = Path(os.path.abspath(directory))
    declaration, _ = read_json(directory / "schedule.json")
    if declaration.get("kind") == "paired_replay_resource_campaign":
        from replay_resource_card import build
        return build(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)
    if declaration.get("kind") == "paired_managed_replay_campaign":
        from replay_result_card import build
        return build(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)
    evidence, evidence_identity = capture_run(directory)
    implementation, implementation_identity = capture_implementation()
    observations = []
    summary = summarize_run(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed, _observations=observations)
    plan, _ = read_json(directory / "schedule.json")
    context = _plan_context(plan, summary["timing_endpoint"])
    rows = _measurement_rows(observations, plan, context, directory)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    if (counts != summary["arm_status_counts"] or len(rows) != summary["planned_arm_count"]
            or len(rows) != 2 * len(plan["schedule"])):
        raise ValueError("result-card measurement denominators contradict inspected summary")
    positions = {(str(row["context"]["block"]), row["context"]["arm"]): row["context"] for row in rows}
    blockers = []
    for item in summary["blockers"]:
        blocker_context = item.get("context")
        if blocker_context is None and item.get("block") is not None:
            blocker_context = positions[(str(item["block"]), item["arm"])]
        blockers.append({"context": blocker_context, "reasons": item["reasons"]})
    card = {
        "schema_version": 1, "kind": "paired_exploratory_result_card", "classification": "exploratory", "confirmatory_eligible": False,
        "qualification": {"status": "not_established", "qualified_arm_count": 0,
                          "unresolved_fields": {field: None for field in UNRESOLVED_FIELDS}},
        "denominators": {"planned_blocks": summary["blocks"], "planned_arms": len(rows),
                         "source_summary_observed_arms": summary["observed_arm_count"],
                         "known_invocation_attempts": sum(row["invocation_attempted"] is True for row in rows),
                         "known_not_invoked_arms": sum(row["invocation_attempted"] is False for row in rows),
                         "unknown_invocation_arms": sum(row["invocation_attempted"] is None for row in rows),
                         "arm_status_counts": counts, "source_summary_guard_counts": summary["observation_guard_counts"],
                         "guard_status_counts": dict(sorted(Counter(row["guard_status"] for row in rows).items())),
                         "resource_status_counts": summary.get("resource_status_counts"),
                         "stage_lifecycle_status_counts": summary.get("stage_lifecycle_status_counts", {}),
                         "planned_resource_stage_count": summary.get("planned_stage_count"),
                         "stage_resource_status_counts": summary.get("stage_resource_status_counts")},
        "measurement_observations": rows,
        "stage_resource_observations": ([_resource_row(source, context) for source in summary["stage_resource_observations"]]
                                        if context["timing_endpoint"] == RESOURCE_ENDPOINT else None),
        "blockers": blockers,
        "analysis_request": {"bootstrap_resamples": bootstrap_resamples, "bootstrap_seed": bootstrap_seed},
        "statistics": {"status": summary["status"], "ratio_direction": summary.get("ratio_direction"),
                       "ratio": summary["ratio"], "absolute_latency_ns": summary["absolute_latency_ns"], "bootstrap": summary["bootstrap"],
                       "per_arm_resources": summary.get("per_arm_resources"),
                       "per_arm_resources_unit": summary.get("per_arm_resources_unit")},
        "context": context, "evidence": evidence,
        "generator": {"implementation": implementation, "runtime": _runtime()},
        "limitations": LIMITATIONS.copy(),
    }
    card["reconstruction_sha256"] = hashlib.sha256(b"pt:result-card:reconstruction:v1\n" + _canonical({
        "evidence_sha256": evidence["sha256"], "implementation_sha256": implementation["sha256"],
        "runtime": card["generator"]["runtime"], "analysis_request": card["analysis_request"],
    })).hexdigest()
    validate_card(card)
    token = (directory, (evidence, evidence_identity), (implementation, implementation_identity))
    _unchanged(token)
    return card, token


def _unchanged(token):
    if len(token) == 4:
        if token[3] == "paired_replay_resource_result_card":
            from replay_resource_card import unchanged
            return unchanged(token)
        from replay_result_card import unchanged
        return unchanged(token)
    directory, evidence, implementation = token
    if capture_run(directory) != evidence or capture_implementation() != implementation:
        raise ValueError("result-card evidence or implementation changed during generation/publication")


def generate_result_card(directory, *, bootstrap_resamples=None, bootstrap_seed=None):
    return _build(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)[0]


def inspect_result_card(card, directory):
    """Rebuild from bound evidence and exact options; matching hashes alone do not approve a card."""
    validate_card(card)
    if card.get("kind") == "paired_replay_resource_exploratory_result_card":
        from replay_resource_card import inspect_card
        return inspect_card(card, directory)
    if card.get("kind") == "paired_replay_exploratory_result_card":
        from replay_result_card import inspect_card
        return inspect_card(card, directory)
    expected = generate_result_card(directory, **card["analysis_request"])
    if not _same_json(expected, card):
        raise ValueError("result card differs from reconstructed evidence, generator, analysis or qualification fields")
    return {"card_consistency": "checked_unqualified", "classification": "exploratory", "confirmatory_eligible": False,
            "status": card["statistics"]["status"], "planned_arm_count": card["denominators"]["planned_arms"],
            "arm_status_counts": card["denominators"]["arm_status_counts"], "evidence_sha256": card["evidence"]["sha256"],
            "reconstruction_sha256": card["reconstruction_sha256"]}


def write_result_card(directory, output, *, bootstrap_resamples=None, bootstrap_seed=None):
    directory, output = Path(os.path.abspath(directory)), Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise FileExistsError("result-card output already exists")
    if output.parent.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
        raise ValueError("result card must be published outside the bound run directory")
    require_safe_lookup()
    fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    card, token = _build(directory, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)
    raw = _serialized(card)
    write_record(str(output), card)
    observed, _ = inspect_file(output.parent, output.name, limit=len(raw))
    if observed["bytes"] != len(raw) or observed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("result-card publication did not commit expected bytes")
    _unchanged(token)
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="one complete or explicitly accounted-aborted paired evidence bundle")
    parser.add_argument("--output", type=Path, required=True, help="new private JSON card outside the run directory")
    parser.add_argument("--bootstrap-resamples", type=int)
    parser.add_argument("--bootstrap-seed", type=int)
    args = parser.parse_args()
    try:
        card = write_result_card(args.directory, args.output, bootstrap_resamples=args.bootstrap_resamples, bootstrap_seed=args.bootstrap_seed)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"result-card: {exc}\n")
    count = ({"planned_session_count": card["denominators"]["planned_sessions"]}
             if card["kind"] in ("paired_replay_exploratory_result_card", "paired_replay_resource_exploratory_result_card")
             else {"planned_arm_count": card["denominators"]["planned_arms"]})
    print(json.dumps({"classification": "exploratory", "qualification": "not_established", "confirmatory_eligible": False,
                      "output": str(args.output), **count,
                      "status": card["statistics"]["status"], "reconstruction_sha256": card["reconstruction_sha256"]}, sort_keys=True))
    return 1 if card["statistics"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
