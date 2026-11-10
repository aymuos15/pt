"""Bind a campaign manifest to retained paired scenario evidence, offline and unqualified."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from evidence import validate_json_types
import finalization as files
import manifest as manifests
import paired_scenarios as pairs
import pt_bench as timer
import result_card as common
import scenario_replay as scenario


HARNESS = Path(__file__).resolve().parent
REPOSITORY = HARNESS.parents[1]
KIND = "campaign_manifest_scenario_evidence_binding"
POLICY = "exact_declared_fields_and_whole_session_validation_only_v1"
INVENTORY_FORMAT = "sha256_canonical_scenario_manifest_inventory_v1"
MAX_BINDING_BYTES = files.MAX_RECEIPT_BYTES
QUALIFICATION = (*scenario.QUALIFICATION, "manifest_preregistration", "artifact_provenance", "source_environment_identities",
                 "resource_budget_equivalence", "corpus_eligibility", "coverage_equivalence", "time_window_adequacy", "independent_review")
SOURCE_FILES = tuple(sorted({"bench/harness/" + name for name in common.SOURCE_FILES} | {
    "bench/benchmark-campaign.schema.json", "bench/harness/scenario_manifest.py", "bench/harness/scenario-manifest-v1.schema.json",
    "bench/harness/paired_scenarios.py", "bench/harness/paired-scenario-v1.schema.json", "bench/harness/scenario_replay.py",
    "bench/harness/scenario_inputs.py", "bench/harness/scenario-replay-v1.schema.json", "bench/harness/paired_replay.py",
    "bench/harness/paired-replay-v1.schema.json", "bench/harness/managed_replay.py", "bench/harness/managed-replay-v1.schema.json",
    "bench/harness/blob_store.py", "bench/harness/raw_capture.py",
}))
LIMITATIONS = [
    "offline manifest-to-scenario association only; no subject, reset, edit, dependency mutation or native resource invocation",
    "manifest bytes and all scheduled scenario outcomes are retained; null declarations and qualifications are never filled from plausible pins",
    "a post hoc association does not establish preregistration, campaign freeze, source identity, executed-code identity or independent review",
    "matched cache, command, cwd, budget and exit declarations are not observed runtime, loaded-input, semantic or reset equivalence",
    "the v1 manifest single argv and expected exit apply to every request; heterogeneous sequences are not represented by selecting one request",
    "complete_session_replay binds whole-session scope only, not the manifest shipping endpoint or qualified independent analysis units",
    "manifest timeout is compared only with declared execution dispatch budgets; filesystem work and reserved shutdown are not hard-wall bounded",
    "original scripts and artifact pins are unverified declarations; built-in file mutations are never identified as arbitrary reset/probe scripts",
    "all failures, unsupported, not-run and unknown outcomes remain visible; whole-unit return loss cannot be recovered from complete-looking files",
    "manifest analysis and publication policies are retained, never executed or used to authorize latency/resource estimates",
    "hashes bind bytes read, not authenticity or provenance; fingerprints are not an atomic snapshot or hostile-directory protection",
    "caller-owned ancestors and trusted local storage are required; private no-overwrite publication is not power-loss durable",
]
DENOMINATOR_FIELDS = (
    "planned_session_count", "observed_session_count", "attempted_unit_calls", "known_not_called_units", "unconfirmed_unit_calls",
    "session_status_counts", "planned_request_count", "request_status_counts", "known_request_invocations", "unknown_request_invocations",
    "known_not_invoked_requests", "planned_phase_count", "phase_status_counts", "planned_file_effect_count", "file_effect_status_counts",
    "reset_status_counts", "known_shutdown_invocations", "unknown_shutdown_invocations", "known_not_invoked_shutdowns",
)


@lru_cache(maxsize=1)
def _validator():
    names = ("scenario-manifest-v1.schema.json", "paired-scenario-v1.schema.json", "scenario-replay-v1.schema.json",
             "paired-replay-v1.schema.json", "managed-replay-v1.schema.json", "lifecycle-v2.schema.json",
             "result-card-v1.schema.json", "paired-resource-v1.schema.json", "resource-observation-v1.schema.json")
    schemas = [json.loads((HARNESS / name).read_text()) for name in names]
    campaign = json.loads(manifests.SCHEMA_PATH.read_text())
    for schema in [*schemas, campaign]:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources([(schema["$id"], Resource.from_contents(schema)) for schema in schemas] + [
        ("urn:pt:bench:benchmark-campaign-v1", Resource.from_contents(campaign))])
    return manifests.ManifestValidator(schemas[0], registry=registry)


def validate_binding(value):
    validate_json_types(value)
    error = next(_validator().iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"scenario manifest binding schema at {path}: violates {error.validator}")
    if len(scenario._raw(value)) > MAX_BINDING_BYTES:
        raise ValueError("scenario manifest binding exceeds byte limit; no declaration or planned outcome may be dropped")


def _inventory(directories, entries):
    content = {"directories": sorted(directories), "files": sorted(entries, key=lambda item: item["path"])}
    return {"format": INVENTORY_FORMAT, "total_bytes": sum(item["bytes"] for item in entries), **content,
            "sha256": hashlib.sha256(b"pt:scenario-manifest:inventory:v1\n" + common._canonical(content)).hexdigest()}


def capture_evidence(directory):
    snapshot = pairs._snapshot(directory)
    entries = [{"path": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]} for name, metadata in snapshot[0].items()]
    directories = []
    nested = {**snapshot[1], "payloads": snapshot[2]} if snapshot[2] is not None else snapshot[1]
    for name, (inventory, _identities) in nested.items():
        directories.extend([name, *[name + "/" + path for path in inventory["directories"]]])
        entries.extend({**item, "path": name + "/" + item["path"]} for item in inventory["files"])
    return _inventory(directories, entries), snapshot


def capture_implementation():
    entries, identities = common._files(REPOSITORY, SOURCE_FILES)
    return _inventory([], entries), identities


def _manifest(path):
    metadata, _ = files.inspect_file(path.parent, path.name, limit=manifests.MAX_MANIFEST_BYTES)
    declaration, validator = manifests.load_structural_manifest(path)
    after, _ = files.inspect_file(path.parent, path.name, limit=manifests.MAX_MANIFEST_BYTES)
    if metadata != after:
        raise ValueError("manifest changed during binding read; no retry")
    frozen_errors = sorted({".".join(map(str, error.absolute_path)) or "<root>"
                            for error in validator.iter_errors(dict(declaration, status="frozen"))})
    return {"bytes": metadata["bytes"], "sha256": metadata["sha256"], "declaration": declaration,
            "frozen_structure_error_paths": frozen_errors, "declaration_conflicts": manifests.declaration_conflicts(declaration)}, metadata


def _checks(data, plan):
    checks = []

    def check(field, evidence_field, expected, actual, *, relation="exact", unknown=False):
        status = ("not_observed_by_profile" if relation == "unverified" else "unresolved_manifest_declaration" if expected is None else
                  "unknown_evidence_declaration" if unknown else "matched_declaration" if timer._same_json(expected, actual) else "conflicting_declaration")
        checks.append({"manifest_field": field, "evidence_field": evidence_field, "relation": relation, "status": status})

    check("experiment.paired_blocks", "schedule.length", data["experiment"]["paired_blocks"], len(plan["schedule"]))
    check("experiment.random_seed", "seed", data["experiment"]["random_seed"], plan["seed"])
    check("experiment.sample_unit", "sample_unit", data["experiment"]["sample_unit"], "complete_session_replay", relation="whole_session_scope_only")
    for arm in pairs.ARMS:
        session = plan["sessions"][arm]
        prefix = "sessions." + arm
        check("scenario.id", prefix + ".scenario.id", data["scenario"]["id"], session["scenario"]["id"])
        for axis, actual in session["scenario"]["cache_state"].items():
            check("scenario.cache_state." + axis, prefix + ".scenario.cache_state." + axis, data["scenario"]["cache_state"][axis], actual, unknown=actual == "unknown")
        check(arm + ".cwd", prefix + ".cwd", data[arm]["cwd"], session["cwd"])
        check("experiment.timeout_seconds", prefix + ".execution_timeout_seconds", data["experiment"]["timeout_seconds"], session["execution_timeout_seconds"], relation="execution_dispatch_budget_only")
        for index, request in enumerate(session["requests"]):
            request_path = prefix + f".requests.{index}.command"
            check(arm + ".argv", request_path + ".argv", data[arm]["argv"], request["command"]["argv"])
            check("scenario.expected_exit_code", request_path + ".required_finalization.expected_exit_code",
                  data["scenario"]["expected_exit_code"], request["command"]["required_finalization"]["expected_exit_code"])
    # These policies/pins remain in the bound manifest, but this profile cannot
    # verify them. Never hash a file mutation list and call it a reset script.
    unverified = ["primary_endpoint", "scenario.scope", "scenario.contract_id", "scenario.workers", "scenario.generation_assurance",
                  "scenario.coverage", "scenario.repository", "scenario.source_revision", "scenario.expected_inventory_sha256",
                  "scenario.expected_outcome_artifact_sha256", "scenario.output_profile", "scenario.coverage_config_sha256",
                  "scenario.reset_policy_document_sha256", "scenario.snapshot_cost_inside_timer", "machine", "analysis", "publication",
                  "experiment.minimum_time_windows", "experiment.warmup_policy", "experiment.exclusion_policy_sha256",
                  "experiment.pilot_report_sha256", "experiment.fixed_sample_count_before_confirmation", "campaign_id", "status", "claim_family"]
    unverified.extend(arm + "." + field for arm in pairs.ARMS for field in (
        "kind", "revision", "binary_sha256", "environment_lock_sha256", "interpreter_sha256", "reset_script_sha256", "state_probe_sha256"))
    for field in unverified:
        check(field, None, None, None, relation="unverified")
    return sorted(checks, key=lambda item: (item["manifest_field"], item["evidence_field"] or ""))


def _build(manifest_path, directory):
    manifest_path, directory = Path(manifest_path), Path(directory)
    manifest, manifest_identity = _manifest(manifest_path)
    evidence = capture_evidence(directory)
    implementation = capture_implementation()
    observations = []
    inspection = pairs.inspect_pairs(directory, observations=observations)
    summary = pairs.summarize(inspection, observations)
    plan, metadata = files.read_json(directory / "schedule.json")
    pairs.validate_plan(plan)
    if not timer._same_json(observations, summary["session_observations"]):
        raise ValueError("scenario manifest binding must retain every inspected session in schedule order")
    checks = _checks(manifest["declaration"], plan)
    conflicts = bool(manifest["declaration_conflicts"]) or any(check["status"] == "conflicting_declaration" for check in checks)
    abort = files.read_json(directory / "abort.json", limit=files.MAX_RECEIPT_BYTES)[0] if "abort.json" in evidence[1][0] else None
    binding = {"schema_version": 1, "kind": KIND, "classification": "exploratory", "status": "blocked", "confirmatory_eligible": False,
               "association_policy": POLICY, "measurement_layer": scenario.LAYER, "sample_unit": scenario.UNIT,
               "declaration_consistency": "conflicts_found" if conflicts else "checked_unqualified", "manifest": manifest,
               "campaign": {"plan": plan, "schedule_binding": scenario._binding("schedule.json", metadata),
                            "record_consistency": summary["record_consistency"], "summary_status": summary["status"], "abort": abort},
               "declaration_checks": checks, "check_status_counts": dict(sorted(Counter(check["status"] for check in checks).items())),
               "denominators": {key: summary[key] for key in DENOMINATOR_FIELDS},
               "session_observations": [{key: value for key, value in row.items() if key != "scenario_summary"} for row in observations],
               "campaign_blockers": summary["blockers"], "qualification": {key: None for key in QUALIFICATION},
               "statistics": {"ratio": None, "absolute_latency_ns": None, "bootstrap": None, "resource_observation": None},
               "evidence": evidence[0], "generator": {"implementation": implementation[0], "runtime": common._runtime()},
               "limitations": LIMITATIONS.copy()}
    binding["reconstruction_sha256"] = _reconstruction(binding)
    validate_binding(binding)
    token = manifest_path, manifest_identity, directory, evidence, implementation
    unchanged(token)
    return binding, token


def _reconstruction(binding):
    return hashlib.sha256(b"pt:scenario-manifest:reconstruction:v1\n" + common._canonical({
        "manifest_sha256": binding["manifest"]["sha256"], "evidence_sha256": binding["evidence"]["sha256"],
        "implementation_sha256": binding["generator"]["implementation"]["sha256"], "runtime": binding["generator"]["runtime"],
        "association_policy": binding["association_policy"],
    })).hexdigest()


def unchanged(token):
    manifest_path, identity, directory, evidence, implementation = token
    current, _ = files.inspect_file(manifest_path.parent, manifest_path.name, limit=manifests.MAX_MANIFEST_BYTES)
    if current != identity or capture_evidence(directory) != evidence or capture_implementation() != implementation:
        raise ValueError("scenario manifest binding source, manifest or implementation changed; no retry")


def generate_binding(manifest_path, directory):
    return _build(manifest_path, directory)[0]


def inspect_binding(binding, manifest_path, directory):
    validate_binding(binding)
    expected = generate_binding(manifest_path, directory)
    if not timer._same_json(binding, expected):
        raise ValueError("scenario manifest binding differs from reconstructed declarations, evidence, outcomes or qualifications")
    return {"binding_consistency": "checked_unqualified", "status": "blocked", "classification": "exploratory", "confirmatory_eligible": False,
            "declaration_consistency": binding["declaration_consistency"], "manifest_sha256": binding["manifest"]["sha256"],
            "evidence_sha256": binding["evidence"]["sha256"], "reconstruction_sha256": binding["reconstruction_sha256"],
            "denominators": copy.deepcopy(binding["denominators"]), "qualification": binding["qualification"]}


def write_binding(manifest_path, directory, output):
    manifest_path, directory, output = (Path(os.path.abspath(path)) for path in (manifest_path, directory, output))
    if os.path.lexists(output):
        raise FileExistsError("scenario manifest binding output already exists")
    if output.parent.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
        raise ValueError("scenario manifest binding output must be outside the bound campaign")
    files.require_safe_lookup()
    fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    value, token = _build(manifest_path, directory)
    raw = scenario._raw(value)
    timer.write_record(str(output), value)
    observed, _ = files.inspect_file(output.parent, output.name, limit=MAX_BINDING_BYTES)
    if observed["bytes"] != len(raw) or observed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("scenario manifest binding publication did not commit expected bytes")
    unchanged(token)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("bind", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--output" if name == "bind" else "--binding", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "bind":
            binding = write_binding(args.manifest, args.run, args.output)
            value = {"binding_published": True, "status": binding["status"], "confirmatory_eligible": False,
                     "declaration_consistency": binding["declaration_consistency"], "denominators": binding["denominators"],
                     "reconstruction_sha256": binding["reconstruction_sha256"]}
            code = int(binding["declaration_consistency"] == "conflicts_found")
        else:
            binding, _ = files.read_json(args.binding, limit=MAX_BINDING_BYTES)
            value = inspect_binding(binding, args.manifest, args.run)
            code = 0
    except (OSError, ValueError) as exc:
        print(f"scenario-manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
