"""Offline, closed v2 evidence schemas; never semantic qualification."""

from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, validators
from referencing import Registry, Resource

from finalization import MAX_JSON_DEPTH


SCHEMAS = ("paired-plan", "sample", "receipt", "paired-abort")
SCHEMA_DIRECTORY = Path(__file__).resolve().parent
StrictValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _checker, value: type(value) is int,
    ).redefine(
        "number", lambda _checker, value: type(value) is int or (type(value) is float and math.isfinite(value)),
    ),
)


def validate_json_types(value: Any) -> None:
    """Reject non-JSON objects/nonfinite values before traversing schemas.

    The depth bound also rejects cyclic API inputs without unbounded recursion.
    JSON Schema normally permits 1.0 for an integer; raw evidence does not.
    """
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("evidence exceeds JSON nesting limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("evidence requires string JSON keys")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("evidence contains non-finite JSON number")
        elif item is not None and type(item) not in (str, int, bool):
            raise ValueError("evidence contains a non-JSON value")


@lru_cache(maxsize=1)
def _validators():
    schemas = {}
    for name in ("lifecycle", *SCHEMAS):
        schema = json.loads((SCHEMA_DIRECTORY / f"{name}-v2.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        schemas[name] = schema
    # Only these bundled URNs resolve. There is no filesystem/HTTP retrieval.
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {name: StrictValidator(schemas[name], registry=registry) for name in SCHEMAS}


def validate_v2(kind: str, value: Any) -> None:
    """Validate a full record before semantic checks or publication."""
    if kind not in SCHEMAS:
        raise ValueError(f"unknown v2 evidence kind: {kind}")
    validate_json_types(value)
    error = next(_validators()[kind].iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        # Do not echo raw commands, metadata or report contents in diagnostics.
        raise ValueError(f"v2 {kind} schema at {path}: violates {error.validator}")


def validate_context(value: Any) -> None:
    validate_json_types(value)
    validator = _validators()["receipt"].evolve(schema={"$ref": "urn:pt:bench:lifecycle-v2#/$defs/nullable_context"})
    if not validator.is_valid(value):
        raise ValueError("invalid v2 lifecycle context")
