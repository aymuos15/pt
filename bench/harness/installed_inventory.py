"""Verify RECORD-listed distribution files in one local Python environment."""

from __future__ import annotations

import base64
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


class InventoryError(ValueError):
    pass


def scan(root: Path, distributions: Iterable[Any]) -> dict[str, Any]:
    """Verify hashed RECORD entries and summarize comparable installed files.

    This does not discover unlisted files, authenticate RECORD, or provide an
    immutable environment snapshot. Generated entrypoint hashes are verified
    locally but excluded from cross-directory comparison because their shebangs
    can contain the absolute virtual-environment path.
    """
    root = root.resolve(strict=True)
    claimed = set()
    comparable = []
    unhashed = []
    entrypoints = []
    verified = 0
    for distribution in distributions:
        name = distribution.metadata.get("Name")
        if not isinstance(name, str) or not name:
            raise InventoryError("distribution is missing its name")
        name = re.sub(r"[-_.]+", "-", name).lower()
        entries = distribution.files
        if entries is None:
            raise InventoryError(f"{name}: missing installed-file inventory")
        for entry in entries:
            try:
                path = Path(distribution.locate_file(entry)).resolve(strict=True)
            except OSError as exc:
                raise InventoryError(f"{name}: missing or unreadable listed file") from exc
            if not path.is_relative_to(root) or not path.is_file():
                raise InventoryError(f"{name}: listed path is outside the environment or not a file")
            relative = path.relative_to(root).as_posix()
            if relative in claimed:
                raise InventoryError(f"duplicate installed-file path: {relative}")
            claimed.add(relative)
            label = f"{name}:{relative}"
            recorded = entry.hash
            if recorded is None:
                unhashed.append(label)
                continue
            if recorded.mode != "sha256":
                raise InventoryError(f"{label}: unsupported RECORD hash algorithm")
            digest = hashlib.sha256()
            size = 0
            try:
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
            except OSError as exc:
                raise InventoryError(f"{label}: cannot read listed file") from exc
            encoded = base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")
            if encoded != recorded.value or (entry.size is not None and size != entry.size):
                raise InventoryError(f"{label}: installed content disagrees with RECORD")
            verified += 1
            if Path(relative).parts[0] in ("bin", "Scripts"):
                entrypoints.append(label)
            else:
                comparable.append({"distribution": name, "path": relative,
                                   "sha256": digest.hexdigest(), "bytes": size})
    comparable.sort(key=lambda item: (item["distribution"], item["path"]))
    if not claimed or not verified:
        raise InventoryError("no hashed installed files were verified")
    canonical = json.dumps(comparable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"record_hashed_files_verified": verified,
            "comparable_files": len(comparable),
            "comparable_inventory_sha256": hashlib.sha256(canonical).hexdigest(),
            "unhashed_record_entries": sorted(unhashed),
            "verified_noncomparable_entrypoints": sorted(entrypoints),
            "unlisted_files_checked": False, "record_provenance_verified": False}


def main() -> int:
    try:
        result = scan(Path(sys.prefix), metadata.distributions())
    except (InventoryError, OSError) as exc:
        print(f"installed-inventory: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
