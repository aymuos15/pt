"""Read-only stdlib content oracle for native JUnit controls; no PT imports.

This is test evidence, not a production format adapter or execution proof.
"""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

if sys.version_info[:3] != (3, 12, 12):
    raise RuntimeError("JUnit oracle pins CPython 3.12.12")
source, output = map(Path, sys.argv[1:])
if source.stat().st_size > 4*1024*1024:
    raise ValueError("explicit test JUnit byte bound")
raw = source.read_bytes()
if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
    raise ValueError("no DTD/entity resolution is part of this test oracle")
root = ET.fromstring(raw)
suites = list(root.iter("testsuite"))
if len(suites) != 1:
    raise ValueError("test oracle expects exactly one pinned formatter suite")
rows = []
for item in root.iter("testcase"):
    rows.append({"classname": item.get("classname"), "name": item.get("name"),
                 "adverse": [{"kind": child.tag, "attributes": child.attrib, "text": child.text}
                             for child in item if child.tag in ("failure", "error", "skipped")],
                 "extensions": [child.tag for child in item if child.tag not in ("failure", "error", "skipped")]})
with output.open("x") as destination:
    json.dump({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "suite": suites[0].attrib,
               "rows": rows, "qualified": False}, destination, ensure_ascii=False, sort_keys=True)
