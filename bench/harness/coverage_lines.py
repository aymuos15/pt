"""Compare limited coverage.py line reports; not a coverage conformance oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


MAX_REPORT_BYTES = 64 * 1024 * 1024


class CoverageReportError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoverageReportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _line_set(value: Any, field: str) -> list[int]:
    if (not isinstance(value, list) or any(type(item) is not int or item < 1 for item in value)
            or len(set(value)) != len(value)):
        raise CoverageReportError(f"invalid {field} line set")
    return sorted(value)


def read_line_report(path: Path) -> dict[str, Any]:
    """Read exact file paths and line sets, excluding nondeterministic metadata."""
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise CoverageReportError("coverage report exceeds size limit")
        data = json.loads(raw, object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              CoverageReportError("non-finite JSON value")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoverageReportError(str(exc)) from exc
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
        raise CoverageReportError("missing coverage metadata")
    meta = data["meta"]
    if (type(meta.get("format")) is not int or not isinstance(meta.get("version"), str)
            or not meta["version"] or meta.get("branch_coverage") is not False
            or meta.get("show_contexts") is not False):
        raise CoverageReportError("only explicit no-context line coverage reports are supported")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise CoverageReportError("coverage file inventory is empty or invalid")
    records = []
    for name in sorted(files):
        item = files[name]
        if not isinstance(name, str) or not name or not isinstance(item, dict):
            raise CoverageReportError("invalid coverage file record")
        executed = _line_set(item.get("executed_lines"), "executed")
        missing = _line_set(item.get("missing_lines"), "missing")
        excluded = _line_set(item.get("excluded_lines"), "excluded")
        if set(executed) & set(missing) or set(executed) & set(excluded) or set(missing) & set(excluded):
            raise CoverageReportError(f"overlapping coverage line categories for {name}")
        records.append([name, executed, missing, excluded])
    canonical = json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return {"mode": "limited_line_coverage_observation", "coverage_format": meta["format"],
            "coverage_version": meta["version"], "files": len(records), "records": records,
            "line_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
            "limitations": ["coverage core and effective configuration not verified",
                            "no branch, context, or subprocess coverage qualification",
                            "source contents and generation not verified"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    try:
        first, second = read_line_report(args.first), read_line_report(args.second)
    except CoverageReportError as exc:
        print(f"coverage-lines: {exc}", file=sys.stderr)
        return 2
    match = all(first[key] == second[key] for key in ("coverage_format", "coverage_version", "records"))
    result = {"mode": "limited_line_coverage_observation", "matched": match,
              "first": {key: value for key, value in first.items() if key != "records"},
              "second": {key: value for key, value in second.items() if key != "records"},
              "confirmatory_eligible": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
