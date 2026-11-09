"""Campaign structure and bounded declaration checks; never qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import jsonschema
import yaml
from yaml.events import AliasEvent

from evidence import StrictValidator, validate_json_types
from finalization import MAX_JSON_DEPTH, inspect_file


MAX_MANIFEST_BYTES = 1024 * 1024
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "benchmark-campaign.schema.json"


class ManifestError(ValueError):
    """The input cannot be structurally checked as a campaign manifest."""


class StrictLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate keys and aliases before schema validation."""

    def __init__(self, stream: Any):
        super().__init__(stream)
        self._node_depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        self._node_depth += 1
        try:
            if self._node_depth > MAX_JSON_DEPTH + 1:
                raise ManifestError("manifest exceeds YAML nesting limit")
            if self.check_event(AliasEvent):
                raise ManifestError("YAML aliases are not supported")
            return super().compose_node(parent, index)
        finally:
            self._node_depth -= 1

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ManifestError("mapping keys must be strings")
            if key in result:
                raise ManifestError(f"duplicate mapping key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _const(validator, expected, instance, schema):
    # The historical schema has numeric/boolean constants without an explicit
    # type. Python equality (True == 1 == 1.0) must not relax their token types.
    if type(expected) in (int, bool) and type(instance) is not type(expected):
        yield jsonschema.ValidationError("constant has the wrong JSON type")
    else:
        yield from jsonschema.Draft202012Validator.VALIDATORS["const"](validator, expected, instance, schema)


ManifestValidator = jsonschema.validators.extend(StrictValidator, {"const": _const})


def _pin_and_command_types(data):
    """Close regex end-anchor/NUL ambiguities without changing the v1 schema."""
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        for field, value in values.items():
            if value is None:
                continue
            if field.endswith("_sha256") and re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ManifestError(f"{section}.{field}: invalid SHA-256 declaration")
            if field in ("revision", "source_revision") and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
                raise ManifestError(f"{section}.{field}: invalid revision declaration")
            if field in ("cwd", "argv"):
                strings = value if isinstance(value, list) else [value]
                if any("\0" in text for text in strings):
                    raise ManifestError(f"{section}.{field}: NUL in command declaration")


def load_structural_manifest(path: Path) -> tuple[dict[str, Any], Any]:
    """Load one schema-valid manifest, without validating referenced artifacts."""
    try:
        _, raw = inspect_file(path.parent, path.name, limit=MAX_MANIFEST_BYTES, retain=True)
        data = yaml.load(raw.decode("utf-8"), Loader=StrictLoader)
        validate_json_types(data)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = ManifestValidator(schema)
        errors = sorted(validator.iter_errors(data),
                        key=lambda error: list(map(str, error.absolute_path)))
    except (OSError, ValueError, RecursionError, yaml.YAMLError, jsonschema.SchemaError) as exc:
        raise ManifestError(str(exc)) from exc
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.absolute_path)) or "<root>"
        # A rejected argv or other declaration may contain a secret. Report the
        # field/rule, never the offending instance or full schema error message.
        raise ManifestError(f"{location}: violates {error.validator}")
    _pin_and_command_types(data)
    return data, validator


def declaration_conflicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Check a schema-validated declaration, not actual work, budgets or pins.

    Only direct contradictions with the named contract/units are rejected. An
    unknown contract is not interpreted as serial; equal hashes do not establish
    matching dependencies, provenance, or real execution.
    """
    findings = []

    def conflict(code, *fields):
        findings.append({"code": code, "fields": list(fields)})

    scenario, experiment, analysis = (data[key] for key in ("scenario", "experiment", "analysis"))
    if data["claim_family"] == "equal_work":
        if scenario["scope"] == "affected":
            conflict("affected_scope_is_not_equal_work", "claim_family", "scenario.scope")
        candidate, baseline = (data[arm]["interpreter_sha256"] for arm in ("candidate", "baseline"))
        if candidate is not None and baseline is not None and candidate != baseline:
            conflict("equal_work_interpreter_pins_differ", "candidate.interpreter_sha256", "baseline.interpreter_sha256")
    if data["claim_family"] == "prepared_session_amortization":
        if experiment["sample_unit"] != "complete_session_replay":
            conflict("amortization_requires_session_replay", "claim_family", "experiment.sample_unit")
        if data["primary_endpoint"] != "complete_session_cost":
            conflict("amortization_requires_complete_session_cost", "claim_family", "primary_endpoint")
    if data["primary_endpoint"] == "complete_session_cost" and experiment["sample_unit"] != "complete_session_replay":
        conflict("session_endpoint_requires_session_unit", "primary_endpoint", "experiment.sample_unit")
    if analysis["resampling_unit"] != "higher_level_cluster" and analysis["resampling_unit"] != experiment["analysis_unit"]:
        conflict("resampling_unit_differs_from_analysis_unit", "analysis.resampling_unit", "experiment.analysis_unit")
    if scenario["contract_id"] == "serial-pytest-v1" and scenario["workers"] != 1:
        conflict("serial_contract_requires_one_worker", "scenario.contract_id", "scenario.workers")
    return sorted(findings, key=lambda item: item["code"])


def check_structure(path: Path) -> dict[str, Any]:
    """Check syntax/types and report bounded declaration consistency separately."""
    data, validator = load_structural_manifest(path)
    hypothetical_frozen = dict(data, status="frozen")
    freeze_errors = sorted({".".join(map(str, error.absolute_path)) or "<root>"
                            for error in validator.iter_errors(hypothetical_frozen)})
    conflicts = declaration_conflicts(data)
    return {"structure": "valid", "declared_status": data["status"],
            "frozen_structure_error_paths": freeze_errors,
            "declaration_consistency": "conflicts_found" if conflicts else "checked_unqualified",
            "declaration_conflicts": conflicts,
            "contract_recognized_for_declaration_checks": data["scenario"]["contract_id"] == "serial-pytest-v1",
            "confirmatory_eligible": False,
            "unchecked_requirements": ["artifact provenance and semantic content", "source and environment identities",
                                       "actual test-work and generation validity", "reset and resource-budget equivalence",
                                       "corpus eligibility and independence", "campaign freeze and independent review"],
            "reason": "bounded declaration checks do not establish semantic or confirmatory qualification"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = check_structure(args.manifest)
    except ManifestError as exc:
        print(f"manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result["declaration_conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
