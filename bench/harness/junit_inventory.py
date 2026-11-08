"""Compare limited JUnit testcase observations; not a semantic oracle."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


MAX_XML_BYTES = 32 * 1024 * 1024


class JUnitError(ValueError):
    pass


def read_inventory(path: Path) -> dict:
    """Retain ordered classname/name and outcome tag/type/message occurrences."""
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_XML_BYTES + 1)
        if len(raw) > MAX_XML_BYTES:
            raise JUnitError("JUnit document exceeds size limit")
        text = raw.decode("utf-8")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.IGNORECASE):
            raise JUnitError("DTD and entity declarations are not supported")
        root = ET.fromstring(text)
    except (OSError, UnicodeError, ET.ParseError) as exc:
        raise JUnitError(str(exc)) from exc
    if root.tag not in ("testsuite", "testsuites"):
        raise JUnitError("unexpected JUnit root")
    records = []
    counts: Counter[str] = Counter()
    for case in root.findall(".//testcase"):
        classname, name = case.get("classname"), case.get("name")
        if not isinstance(classname, str) or not isinstance(name, str) or not name:
            raise JUnitError("testcase is missing classname or name")
        outcomes = [[child.tag, child.get("type", ""), child.get("message", "")]
                    for child in case if child.tag in ("error", "failure", "skipped")]
        records.append([classname, name, outcomes])
        if not outcomes:
            counts["no_junit_failure_or_skip"] += 1
        for tag, kind, _ in outcomes:
            counts[f"{tag}:{kind}"] += 1
    canonical = json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return {"schema_version": 1, "mode": "limited_junit_observation",
            "occurrences": len(records), "outcome_tags": dict(sorted(counts.items())),
            "ordered_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
            "records": records,
            "limitations": ["not authoritative pytest node IDs", "phase reports not preserved",
                            "tracebacks and output not compared", "no source or environment qualification"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    try:
        first, second = read_inventory(args.first), read_inventory(args.second)
    except JUnitError as exc:
        print(f"junit-inventory: {exc}", file=sys.stderr)
        return 2
    match = first["records"] == second["records"]
    result = {"mode": "limited_junit_observation", "matched": match,
              "first": {key: value for key, value in first.items() if key != "records"},
              "second": {key: value for key, value in second.items() if key != "records"},
              "confirmatory_eligible": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
