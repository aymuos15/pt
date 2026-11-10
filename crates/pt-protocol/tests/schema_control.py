"""Independent schema adversaries; test data only, no product/runtime import."""

import copy
import json
from pathlib import Path
import sys

import jsonschema


if sys.version_info[:3] != (3, 12, 12):
    raise RuntimeError("schema controls require the explicitly prepared CPython 3.12.12 harness")

schema_path, fixtures_path, output_path = map(Path, sys.argv[1:])
schema = json.loads(schema_path.read_bytes())
validator = jsonschema.Draft202012Validator(schema)
fixtures = json.loads(fixtures_path.read_bytes())
cases = []


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate control key")
        value[key] = item
    return value


def noninteger(value):
    raise ValueError("protocol numbers must be integer lexical forms")


def append(label, value=None, *, raw=None):
    raw = raw if raw is not None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    try:
        parsed = json.loads(raw, object_pairs_hook=unique, parse_float=noninteger, parse_constant=noninteger)
        accepted = (validator.is_valid(parsed) and parsed["producer_role"] == "bridge"
                    and parsed["sequence"] < 1_000_000
                    and all(parsed[key] == expected for key, expected in {
                        "request_id": "request-1", "run_id": "run-1", "generation_id": "generation-1",
                        "session_id": "session-1", "producer_id": "bridge-1"}.items()))
    except (ValueError, RecursionError):
        accepted = False
    cases.append({"label": label, "raw": raw, "schema_and_wire_shape_accepted": accepted})


def objects(value, path=()):
    if type(value) is dict:
        yield path, value
        for key, child in value.items():
            yield from objects(child, path + (key,))


for index, fixture in enumerate(fixtures):
    envelope = {"protocol_version": 0, "contract_revision": 1, "request_id": "request-1", "run_id": "run-1",
                "generation_id": "generation-1", "session_id": "session-1", "producer_id": "bridge-1",
                "producer_role": "bridge", "sequence": index, **fixture}
    append(fixture["kind"] + ":valid", envelope)
    for path, obj in objects(envelope):
        for key in [*obj, "__unreviewed__"]:
            altered = copy.deepcopy(envelope)
            target = altered
            for component in path:
                target = target[component]
            if key == "__unreviewed__":
                target[key] = None
            else:
                del target[key]
            append(fixture["kind"] + ":closed:" + "/".join((*path, key)), altered)
        for key, item in obj.items():
            # Try independent wrong primitive/container types at every object
            # level, including nullable fields and nested terminal arithmetic.
            for replacement in (None, True, -1, 1.5, "unknown_value", [], {}):
                if type(replacement) is type(item) and replacement == item:
                    continue
                altered = copy.deepcopy(envelope)
                target = altered
                for component in path:
                    target = target[component]
                target[key] = replacement
                append(fixture["kind"] + ":type:" + "/".join((*path, key)), altered)
    raw = json.dumps(envelope, separators=(",", ":"))
    append(fixture["kind"] + ":duplicate_envelope", raw=raw.replace('"sequence":' + str(index), '"sequence":0,"sequence":' + str(index)))
    append(fixture["kind"] + ":trailing_data", raw=raw + " {}")

# Schema counts are uint64 and protocol forbids exponent/floating lexical forms.
base = {"protocol_version": 0, "contract_revision": 1, "request_id": "request-1", "run_id": "run-1",
        "generation_id": "generation-1", "session_id": "session-1", "producer_id": "bridge-1",
        "producer_role": "bridge", "sequence": 0, "kind": "item_collected", "payload": {"ordinal": 0, "nodeid": "x"}}
for ordinal in (2**64-1, 2**64, -1, True):
    altered = copy.deepcopy(base)
    altered["payload"]["ordinal"] = ordinal
    append("ordinal-bound:" + str(ordinal), altered)
for literal in ("1e0", "NaN", "Infinity"):
    append("ordinal-lexical:" + literal, raw=json.dumps(base).replace('"ordinal": 0', '"ordinal": ' + literal))

result = {"mode": "independent_schema_and_wire_shape_controls", "qualified": False,
          "bridge_shapes": len(fixtures), "cases": cases}
raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
if len(raw) > 8 * 1024 * 1024:
    raise RuntimeError("schema fixture controls exceed their explicit retained byte bound")
with output_path.open("xb") as output:
    output.write(raw)
