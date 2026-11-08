"""Validate the structure of the unqualified repository shortlist, offline."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class CandidateError(ValueError):
    pass


def check_shortlist(path: Path) -> dict:
    """Check declarations only; do not resolve revisions or qualify repositories."""
    try:
        with path.open("rb") as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise CandidateError("shortlist exceeds size limit")
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CandidateError(str(exc)) from exc
    if (set(data) != {"schema_version", "status", "observation_completed_at_utc", "observation_method", "candidates"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("status") != "unqualified_shortlist"):
        raise CandidateError("unsupported shortlist schema or status")
    try:
        datetime.strptime(data["observation_completed_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateError("invalid UTC observation timestamp") from exc
    if data.get("observation_method") != "git ls-remote --symref <url> HEAD":
        raise CandidateError("unsupported observation method")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CandidateError("candidate list is empty")
    seen = set()
    required = {"id", "url", "observed_head_ref", "revision", "anticipated_dimensions", "eligibility", "allocation"}
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != required:
            raise CandidateError("candidate fields do not match the draft schema")
        identifier = candidate["id"]
        if not isinstance(identifier, str) or re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", identifier) is None:
            raise CandidateError("invalid candidate ID")
        if identifier in seen:
            raise CandidateError(f"duplicate candidate: {identifier}")
        seen.add(identifier)
        url = candidate["url"]
        if not isinstance(url, str):
            raise CandidateError(f"{identifier}: invalid URL")
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise CandidateError(f"{identifier}: invalid URL") from exc
        if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment
                or parsed.path.lower() != "/" + identifier + ".git"):
            raise CandidateError(f"{identifier}: URL does not match candidate")
        ref = candidate["observed_head_ref"]
        if not isinstance(ref, str) or not ref.startswith("refs/heads/") or len(ref) <= len("refs/heads/"):
            raise CandidateError(f"{identifier}: invalid observed branch reference")
        if not isinstance(candidate["revision"], str) or re.fullmatch(r"[0-9a-f]{40}", candidate["revision"]) is None:
            raise CandidateError(f"{identifier}: invalid observed revision")
        dimensions = candidate["anticipated_dimensions"]
        if (not isinstance(dimensions, list) or not dimensions
                or any(not isinstance(item, str) or re.fullmatch(r"[a-z0-9-]+", item) is None for item in dimensions)
                or len(set(dimensions)) != len(dimensions)):
            raise CandidateError(f"{identifier}: invalid anticipated dimensions")
        if candidate["eligibility"] != "unassessed" or candidate["allocation"] != "unassigned":
            raise CandidateError(f"{identifier}: shortlist cannot assert eligibility or allocation")
    return {"status": "unqualified_shortlist", "candidates": len(candidates),
            "eligibility_unassessed": len(candidates), "allocations_assigned": 0,
            "remote_revisions_rechecked": False, "confirmatory_eligible": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shortlist", type=Path)
    args = parser.parse_args()
    try:
        result = check_shortlist(args.shortlist)
    except CandidateError as exc:
        print(f"candidate-inventory: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
