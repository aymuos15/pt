"""Structural campaign checks only; confirmatory qualification is unavailable."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import jsonschema
import yaml
from yaml.events import AliasEvent


MAX_MANIFEST_BYTES = 1024 * 1024
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "benchmark-campaign.schema.json"


class ManifestError(ValueError):
    """The input cannot be structurally checked as a campaign manifest."""


class StrictLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate keys and aliases before schema validation."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ManifestError("YAML aliases are not supported")
        return super().compose_node(parent, index)

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


def _reject_nonfinite(value: Any) -> None:
    """Reject YAML numeric values that cannot be represented in JSON records."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ManifestError("non-finite numeric values are not permitted")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def load_structural_manifest(path: Path) -> tuple[dict[str, Any], Any]:
    """Load one schema-valid manifest, without validating referenced artifacts."""
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ManifestError("manifest exceeds size limit")
        data = yaml.load(raw.decode("utf-8"), Loader=StrictLoader)
        _reject_nonfinite(data)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data),
                        key=lambda error: list(map(str, error.absolute_path)))
    except (OSError, UnicodeError, RecursionError, yaml.YAMLError,
            json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise ManifestError(str(exc)) from exc
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.absolute_path)) or "<root>"
        raise ManifestError(f"{location}: {error.message}")
    return data, validator


def check_structure(path: Path) -> dict[str, Any]:
    """Check syntax and JSON Schema structure, without validating real artifacts."""
    data, validator = load_structural_manifest(path)
    hypothetical_frozen = dict(data, status="frozen")
    freeze_errors = sorted({".".join(map(str, error.absolute_path)) or "<root>"
                            for error in validator.iter_errors(hypothetical_frozen)})
    return {"structure": "valid", "declared_status": data["status"],
            "frozen_structure_error_paths": freeze_errors,
            "confirmatory_eligible": False,
            "reason": "semantic, artifact, reset, eligibility and independence checks are not implemented"}


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
