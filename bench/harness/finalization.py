"""Bounded checks of declared finalization evidence, not semantic qualification."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any


MAX_RECORD_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 4 * MAX_RECORD_BYTES
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_JSON_DEPTH = 64
SCOPE = "declared_files_absences_and_process_observations_only"


def require_safe_lookup() -> None:
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd):
        raise ValueError("required-finalization checks need safe POSIX relative lookup")


def relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\\" in value or "\x00" in value:
        raise ValueError("finalization paths must be nonempty POSIX-style strings")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("finalization paths must be normalized and relative")
    return value


def requirements(value: Any = None) -> dict[str, Any]:
    """Freeze a small, explicit contract before work; never infer test success."""
    if value is None:
        value = {"expected_exit_code": None, "artifacts": [], "absent": []}
    if (not isinstance(value, dict)
            or set(value) != {"expected_exit_code", "artifacts", "absent"}
            or (value["expected_exit_code"] is not None and type(value["expected_exit_code"]) is not int)
            or not isinstance(value["artifacts"], list) or len(value["artifacts"]) > 1000
            or not isinstance(value["absent"], list) or len(value["absent"]) > 1000):
        raise ValueError("invalid required-finalization contract")
    artifacts = []
    for item in value["artifacts"]:
        if (not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}
                or type(item["bytes"]) is not int or not 0 <= item["bytes"] <= MAX_ARTIFACT_BYTES
                or not isinstance(item["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("artifacts require a relative path, bounded byte count and exact SHA-256")
        artifacts.append({**item, "path": relative_path(item["path"])})
    absent = [relative_path(path) for path in value["absent"]]
    paths = [item["path"] for item in artifacts] + absent
    if len(paths) != len(set(paths)) or sum(item["bytes"] for item in artifacts) > MAX_TOTAL_BYTES:
        raise ValueError("duplicate finalization paths or excessive total artifact bytes")
    for path in [item["path"] for item in artifacts]:
        if any(PurePosixPath(missing) in PurePosixPath(path).parents for missing in absent):
            raise ValueError("artifact cannot be below a required-absent path")
    return {"expected_exit_code": value["expected_exit_code"],
            "artifacts": sorted(artifacts, key=lambda item: item["path"]), "absent": sorted(absent)}


def _fingerprint(item: os.stat_result) -> list[int]:
    return [item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns]


@contextmanager
def open_file(root: Path, value: str):
    require_safe_lookup()
    relative_path(value)
    with ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        parts = PurePosixPath(value).parts
        for component in parts[:-1]:
            directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stack.callback(os.close, fd)
        yield fd, directory, parts[-1]


def inspect_file(root: Path, value: str, *, limit: int, retain: bool = False) -> tuple[dict, bytes]:
    """No symlinks within the listed path/root's last component; no snapshot claim.

    Ancestors of the supplied root are caller-owned and may be symlinks. Reads
    reject identity/size/mtime/ctime changes and replacement of the final name.
    Only bounded JSON reads retain bytes; large required artifacts are streamed.
    """
    require_safe_lookup()
    relative_path(value)
    if type(limit) is not int or limit < 0 or (retain and limit > MAX_RECEIPT_BYTES):
        raise ValueError("invalid finalization read limit")
    with open_file(root, value) as (fd, directory, name):
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError(f"{value}: not a regular file within the byte limit")
        digest, size, chunks = hashlib.sha256(), 0, []
        while True:
            chunk = os.read(fd, min(1024 * 1024, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError(f"{value}: grew beyond the byte limit")
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or _fingerprint(before) != _fingerprint(after)
                or _fingerprint(after) != _fingerprint(named) or size != after.st_size):
            raise ValueError(f"{value}: changed during finalization read")
        return {"bytes": size, "sha256": digest.hexdigest(), "identity": _fingerprint(after)}, b"".join(chunks)


def _absent(root: Path, value: str) -> bool:
    with ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        parts = PurePosixPath(value).parts
        try:
            for component in parts[:-1]:
                directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=directory)
                stack.callback(os.close, directory)
            os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return True
        return False


def _process_ok(result: dict) -> bool:
    return (result.get("status") == "exited_unqualified"
            and result.get("process_reaped") is True and result.get("output_complete") is True
            and type(result.get("returncode")) is int
            and all(type(result.get(f"{stream}_bytes")) is int and result[f"{stream}_bytes"] >= 0
                    and isinstance(result.get(f"{stream}_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", result[f"{stream}_sha256"]) is not None
                    for stream in ("stdout", "stderr")))


def check(result: dict[str, Any] | None, root: Path, contract: dict[str, Any],
          raw_bundle: Path | None = None) -> dict[str, Any]:
    """Observe all declared checks without repairing/retrying any mismatch."""
    require_safe_lookup()
    contract = requirements(contract)
    result = result or {}
    process_ok = _process_ok(result)
    checks = [{"kind": "process", "matched": process_ok}]
    expected = contract["expected_exit_code"]
    if expected is not None:
        checks.append({"kind": "expected_exit_code", "matched": process_ok and result.get("returncode") == expected})

    def artifact(directory, item, kind):
        entry = {"kind": kind, "path": item["path"], "matched": False}
        try:
            observed, _ = inspect_file(directory, item["path"], limit=item["bytes"])
            entry.update(observed)
            entry["matched"] = observed["bytes"] == item["bytes"] and observed["sha256"] == item["sha256"]
        except (OSError, ValueError) as exc:
            entry["error"] = str(exc)
        checks.append(entry)

    for item in contract["artifacts"]:
        artifact(root, item, "artifact")
    for path in contract["absent"]:
        entry = {"kind": "absent", "path": path, "matched": False}
        try:
            entry["matched"] = _absent(root, path)
        except OSError as exc:
            entry["error"] = str(exc)
        checks.append(entry)
    capture = result.get("raw_capture")
    if raw_bundle is not None and result.get("status") != "launch_error":
        try:
            if (not isinstance(capture, dict)
                    or set(capture) != {"capture_mode", "limit_per_stream_bytes", "stdout", "stderr"}
                    or capture["capture_mode"] != "bounded_prefix"
                    or type(capture["limit_per_stream_bytes"]) is not int
                    or capture["limit_per_stream_bytes"] < 0):
                raise ValueError("missing or invalid required raw capture")
            for stream in ("stdout", "stderr"):
                item, total = capture[stream], result.get(f"{stream}_bytes")
                if (not isinstance(item, dict) or set(item) != {"sha256", "stored_bytes", "publication", "truncated"}
                        or type(total) is not int or total < 0
                        or type(item["stored_bytes"]) is not int
                        or item["stored_bytes"] != min(total, capture["limit_per_stream_bytes"])
                        or type(item["truncated"]) is not bool or item["truncated"] != (item["stored_bytes"] < total)
                        or item["publication"] not in ("created", "already_present")
                        or not isinstance(item["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
                        or (not item["truncated"] and item["sha256"] != result.get(f"{stream}_sha256"))):
                    raise ValueError("inconsistent required raw capture")
                artifact(raw_bundle, {"path": item["sha256"], "bytes": item["stored_bytes"],
                                      "sha256": item["sha256"]}, f"raw_{stream}")
        except ValueError as exc:
            checks.append({"kind": "raw_capture", "matched": False, "error": str(exc)})
    elif capture is not None:
        checks.append({"kind": "raw_capture", "matched": False, "error": "raw capture without required bundle"})
    return {"scope": SCOPE, "matched": all(item["matched"] for item in checks), "checks": checks}


def validate_observed(result: dict, contract: dict, observed: dict, *, capture_raw: bool) -> None:
    """Cross-check schema-validated historical facts without rereading a worktree.

    Failed checks are valid evidence; invented, duplicate, omitted or internally
    contradictory checks are not. Historical stat/absence claims remain unauthenticated.
    """
    expected = [("process", None)]
    process_ok = _process_ok(result)
    matches = {("process", None): process_ok}
    if contract["expected_exit_code"] is not None:
        expected.append(("expected_exit_code", None))
        matches[expected[-1]] = process_ok and result.get("returncode") == contract["expected_exit_code"]
    files = {("artifact", item["path"]): item for item in contract["artifacts"]}
    expected.extend(files)
    expected.extend(("absent", path) for path in contract["absent"])
    capture = result.get("raw_capture")
    if capture_raw and result["status"] != "launch_error":
        if capture is None:
            expected.append(("raw_capture", None))
        else:
            for stream in ("stdout", "stderr"):
                item, total = capture[stream], result[f"{stream}_bytes"]
                if (item["stored_bytes"] != min(total, capture["limit_per_stream_bytes"])
                        or item["truncated"] != (item["stored_bytes"] < total)
                        or (not item["truncated"] and item["sha256"] != result[f"{stream}_sha256"])):
                    raise ValueError("raw capture contradicts command byte counts or digests")
                key = (f"raw_{stream}", item["sha256"])
                expected.append(key)
                files[key] = {"bytes": item["stored_bytes"], "sha256": item["sha256"]}
    elif capture is not None:
        expected.append(("raw_capture", None))
    recorded = observed["checks"]
    if [(item["kind"], item.get("path")) for item in recorded] != expected:
        raise ValueError("historical finalization check references differ from contract")
    for item in recorded:
        key = item["kind"], item.get("path")
        if key in matches and item["matched"] != matches[key]:
            raise ValueError("historical process/exit check contradicts command result")
        if key in files and "bytes" in item:
            target = files[key]
            if item["bytes"] > target["bytes"] or item["identity"][2] != item["bytes"]:
                raise ValueError("historical file observation exceeds byte budget or conflicts with identity")
            matched = item["bytes"] == target["bytes"] and item["sha256"] == target["sha256"]
            if item["matched"] != matched:
                raise ValueError("historical file check contradicts observed bytes/digest")
    if observed["matched"] != all(item["matched"] for item in recorded):
        raise ValueError("historical finalization aggregate contradicts checks")


def archive(root: Path, observed: dict, bundle: Path) -> dict:
    """Retain bounded observed artifact bytes, including bounded mismatches.

    Files that could not be safely observed are not invented or read unboundedly.
    Fingerprints must remain unchanged across this additional publication step.
    """
    from blob_store import publish

    entries, errors = [], []
    for item in observed["checks"]:
        if item["kind"] != "artifact" or "identity" not in item:
            continue
        try:
            with open_file(root, item["path"]) as (fd, directory, name):
                if _fingerprint(os.fstat(fd)) != item["identity"]:
                    raise ValueError("artifact changed before archival")
                with os.fdopen(os.dup(fd), "rb") as source:
                    blob = publish(source, bundle, max_bytes=item["bytes"])
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(named.st_mode) or _fingerprint(os.fstat(fd)) != item["identity"]
                        or _fingerprint(named) != item["identity"] or blob["sha256"] != item["sha256"]
                        or blob["stored_bytes"] != item["bytes"]):
                    raise ValueError("artifact changed during archival")
                entries.append({"path": item["path"], **blob})
        except (OSError, ValueError) as exc:
            errors.append({"path": item["path"], "error": str(exc)})
    return {"bundle": str(bundle), "artifacts": entries, "errors": errors}


def archived_check(result: dict, contract: dict, observed: dict, archived: dict,
                   bundle: Path, *, capture_raw: bool) -> dict:
    """Validate retained bytes and typed historical observations, not live state.

    Original artifact/stat and absence observations cannot be authenticated or
    recreated. Do not reread later-mutated worktrees as if they were earlier arms.
    """
    if (not isinstance(observed, dict) or set(observed) != {"scope", "matched", "checks"}
            or observed["scope"] != SCOPE or type(observed["matched"]) is not bool
            or not isinstance(observed["checks"], list)
            or not isinstance(archived, dict) or set(archived) != {"bundle", "artifacts", "errors"}
            or not isinstance(archived["bundle"], str) or not Path(archived["bundle"]).is_absolute()
            or not isinstance(archived["artifacts"], list) or not isinstance(archived["errors"], list)):
        raise ValueError("invalid historical finalization evidence")
    declared = {item["path"]: item for item in contract["artifacts"]}
    references = {}
    for entry in archived["artifacts"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256", "stored_bytes", "publication"}
                or relative_path(entry["path"]) in references
                or type(entry["stored_bytes"]) is not int or not 0 <= entry["stored_bytes"] <= MAX_ARTIFACT_BYTES
                or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
                or entry["publication"] not in ("created", "already_present")):
            raise ValueError("invalid archived artifact reference")
        if entry["path"] not in declared or entry["stored_bytes"] > declared[entry["path"]]["bytes"]:
            raise ValueError("archived artifact reference exceeds declared paths/byte budget")
        blob, _ = inspect_file(bundle, entry["sha256"], limit=entry["stored_bytes"])
        if blob["sha256"] != entry["sha256"] or blob["bytes"] != entry["stored_bytes"]:
            raise ValueError("archived artifact bytes do not match reference")
        references[entry["path"]] = entry
    archive_errors = {}
    for entry in archived["errors"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "error"}
                or relative_path(entry["path"]) in archive_errors or entry["path"] in references
                or not isinstance(entry["error"], str) or not entry["error"]):
            raise ValueError("invalid artifact-archive failure evidence")
        archive_errors[entry["path"]] = entry["error"]
    recorded = observed["checks"]
    identities = {}
    for item in recorded:
        if (not isinstance(item, dict) or type(item.get("matched")) is not bool
                or not isinstance(item.get("kind"), str)):
            raise ValueError("invalid historical check")
        if "identity" in item:
            if (not isinstance(item["identity"], list) or len(item["identity"]) != 5
                    or any(type(value) is not int for value in item["identity"])):
                raise ValueError("invalid historical identity fingerprint")
            identities[(item["kind"], item.get("path"))] = item["identity"]
    base = check(result, bundle, {**contract, "artifacts": [], "absent": []},
                 bundle if capture_raw else None)["checks"]
    # Stat identities of retained blobs are not identities of past worktree
    # files; only original typed observations and current blob bytes are used.
    for item in base:
        key = (item["kind"], item.get("path"))
        if "identity" in item and key in identities:
            item["identity"] = identities[key]
    checks = [item for item in base if not item["kind"].startswith("raw_")]
    if not set(references).union(archive_errors).issubset(declared):
        raise ValueError("undeclared archived artifact")
    by_path = {(item["kind"], item.get("path")): item for item in recorded}
    if any("identity" not in by_path.get(("artifact", path), {}) for path in archive_errors):
        raise ValueError("artifact-archive error names an unobserved file")
    for expected in contract["artifacts"]:
        path = expected["path"]
        item = by_path.get(("artifact", path))
        if not isinstance(item, dict):
            raise ValueError("missing historical artifact check")
        if path in references:
            ref = references[path]
            checks.append({"kind": "artifact", "path": path,
                           "matched": ref["stored_bytes"] == expected["bytes"] and ref["sha256"] == expected["sha256"],
                           "bytes": ref["stored_bytes"], "sha256": ref["sha256"],
                           "identity": identities.get(("artifact", path))})
        elif path in archive_errors or (item.get("matched") is False and isinstance(item.get("error"), str)):
            checks.append(item)
        else:
            raise ValueError("missing required artifact archive")
    for path in contract["absent"]:
        item = by_path.get(("absent", path))
        if (not isinstance(item, dict) or set(item) not in ({"kind", "path", "matched"}, {"kind", "path", "matched", "error"})
                or ("error" in item and (item["matched"] is not False or not isinstance(item["error"], str)))):
            raise ValueError("missing or invalid historical absence check")
        checks.append(item)
    checks.extend(item for item in base if item["kind"].startswith("raw_"))
    return {"scope": SCOPE, "matched": all(item["matched"] for item in checks), "checks": checks}


def parse_json(raw: str | bytes) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError(f"non-finite JSON value: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant, parse_float=finite_float)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds decoder limit") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting exceeds record limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def read_json(path: Path, *, limit: int = MAX_RECORD_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata, raw = inspect_file(path.parent, path.name, limit=limit, retain=True)
    return parse_json(raw), metadata
