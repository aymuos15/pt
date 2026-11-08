"""Check draft local corpus file identities; does not qualify corpus behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


class InventoryError(ValueError):
    pass


def check_inventory(manifest: Path) -> dict[str, Any]:
    """Verify declared local files; not a secure snapshot or full tree audit."""
    try:
        with manifest.open("rb") as file:
            data = tomllib.load(file)
        root = manifest.parent.resolve(strict=True)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise InventoryError(str(exc)) from exc
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise InventoryError("unsupported schema_version")
    if data.get("status") != "draft_unqualified":
        raise InventoryError("only draft_unqualified inventories are supported")
    probes = data.get("probes")
    if not isinstance(probes, list) or not probes:
        raise InventoryError("at least one probe is required")
    ids, paths = set(), set()
    for probe in probes:
        if not isinstance(probe, dict):
            raise InventoryError("probe must be a table")
        identifier, path, digest = (probe.get(field) for field in ("id", "path", "sha256"))
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise InventoryError("probe IDs must be unique nonempty strings")
        if not isinstance(path, str) or not path or path in paths:
            raise InventoryError("probe paths must be unique nonempty strings")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InventoryError(f"{identifier}: invalid SHA-256")
        if type(probe.get("expected_exit_code")) is not int or not 0 <= probe["expected_exit_code"] <= 255:
            raise InventoryError(f"{identifier}: invalid expected exit")
        if probe.get("allocation") != "unassigned":
            raise InventoryError(f"{identifier}: only unassigned probes are supported")
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != path:
            raise InventoryError(f"{identifier}: path must be normalized and relative")
        candidate = root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise InventoryError(f"{identifier}: path is not a file within corpus root")
            with resolved.open("rb") as file:
                actual = hashlib.sha256()
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    actual.update(chunk)
        except OSError as exc:
            raise InventoryError(f"{identifier}: {exc}") from exc
        if actual.hexdigest() != digest:
            raise InventoryError(f"{identifier}: SHA-256 mismatch")
        ids.add(identifier)
        paths.add(path)
    return {"status": "draft_unqualified", "declared_probes_verified": len(ids),
            "behavior_qualified": False, "complete_tree_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = check_inventory(args.manifest)
    except InventoryError as exc:
        print(f"corpus inventory: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
