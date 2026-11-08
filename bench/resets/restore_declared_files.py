"""Restore explicitly declared existing files from hash-pinned local seeds."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from typing import Any


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILES = 128


class ResetError(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResetError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def load_manifest(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ResetError("manifest exceeds size limit")
        data = json.loads(raw, object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResetError(f"invalid manifest: {exc}") from exc
    if (not isinstance(data, dict) or set(data) != {"schema_version", "files"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise ResetError("unsupported manifest envelope")
    return _validate_files(data["files"])


def _validate_files(files: Any) -> list[dict[str, str]]:
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ResetError(f"manifest must declare between 1 and {MAX_FILES} files")
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ResetError("each file must contain exactly path and sha256")
        value, digest = item["path"], item["sha256"]
        if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
                or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
                or str(PurePosixPath(value)) != value or value == "." or value in seen):
            raise ResetError("file paths must be unique, normalized, and relative")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ResetError(f"{value}: invalid SHA-256")
        seen.add(value)
    return sorted(files, key=lambda item: item["path"])


def _parent_fd(root_fd: int, parts: tuple[str, ...], stack: ExitStack) -> int:
    directory = root_fd
    try:
        for component in parts[:-1]:
            next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            if directory != root_fd:
                os.close(directory)
            directory = next_directory
    except BaseException:
        if directory != root_fd:
            os.close(directory)
        raise
    if directory != root_fd:
        stack.callback(os.close, directory)
    return directory


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def restore(seed_root: Path, target_root: Path, files: list[dict[str, str]], *,
            max_file_bytes: int) -> dict[str, Any]:
    """Stage verified seeds, then replace only existing declared target files.

    Staging is all-before-apply, but multiple renames are not transactional. A
    failure during apply may leave a partial reset; the caller must not run the
    measurement. This is not a sandbox or a guarantee against concurrent edits.
    """
    if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or any(function not in os.supports_dir_fd for function in (os.open, os.stat, os.rename, os.unlink))):
        raise ResetError("safe relative reset operations are unsupported on this platform")
    if type(max_file_bytes) is not int or max_file_bytes < 0:
        raise ResetError("max_file_bytes must be a nonnegative integer")
    # Library callers get the same validation as CLI manifests.
    files = _validate_files(files)
    try:
        seed_path, target_path = seed_root.resolve(strict=True), target_root.resolve(strict=True)
    except OSError as exc:
        raise ResetError(f"cannot resolve reset roots: {exc}") from exc
    if seed_path == target_path or seed_path in target_path.parents or target_path in seed_path.parents:
        raise ResetError("seed and target roots must not overlap")

    staged = []
    applied = 0
    try:
        with ExitStack() as stack:
            seed_fd = os.open(seed_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, seed_fd)
            target_fd = os.open(target_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, target_fd)
            try:
                for item in files:
                    parts = PurePosixPath(item["path"]).parts
                    seed_parent = _parent_fd(seed_fd, parts, stack)
                    target_parent = _parent_fd(target_fd, parts, stack)
                    source_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                        dir_fd=seed_parent)
                    try:
                        before = os.fstat(source_fd)
                        target_before = os.stat(parts[-1], dir_fd=target_parent, follow_symlinks=False)
                        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(target_before.st_mode):
                            raise ResetError(f"{item['path']}: source and target must be regular files")
                        if before.st_size > max_file_bytes:
                            raise ResetError(f"{item['path']}: seed exceeds size limit")
                        temp_name = ".pt-reset-" + secrets.token_hex(16) + ".tmp"
                        destination_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                                 target_before.st_mode & 0o777, dir_fd=target_parent)
                        staged.append({"parent": target_parent, "temp": temp_name, "name": parts[-1],
                                       "target_identity": _identity(target_before), "path": item["path"],
                                       "sha256": item["sha256"]})
                        try:
                            os.fchmod(destination_fd, target_before.st_mode & 0o777)
                            digest, size = hashlib.sha256(), 0
                            while True:
                                chunk = os.read(source_fd, 1024 * 1024)
                                if not chunk:
                                    break
                                size += len(chunk)
                                if size > max_file_bytes:
                                    raise ResetError(f"{item['path']}: seed exceeds size limit")
                                digest.update(chunk)
                                view = memoryview(chunk)
                                while view:
                                    written = os.write(destination_fd, view)
                                    if written <= 0:
                                        raise OSError("short reset write")
                                    view = view[written:]
                            os.fsync(destination_fd)
                        finally:
                            os.close(destination_fd)
                        after = os.fstat(source_fd)
                        if _identity(before) != _identity(after) or size != after.st_size:
                            raise ResetError(f"{item['path']}: seed changed while read")
                        if digest.hexdigest() != item["sha256"]:
                            raise ResetError(f"{item['path']}: seed digest mismatch")
                        staged[-1]["bytes"] = size
                    finally:
                        os.close(source_fd)
                for item in staged:
                    target_now = os.stat(item["name"], dir_fd=item["parent"], follow_symlinks=False)
                    if not stat.S_ISREG(target_now.st_mode) or _identity(target_now) != item["target_identity"]:
                        raise ResetError(f"{item['path']}: target changed before replacement")
                    os.rename(item["temp"], item["name"], src_dir_fd=item["parent"], dst_dir_fd=item["parent"])
                    applied += 1
            finally:
                for item in staged:
                    try:
                        os.unlink(item["temp"], dir_fd=item["parent"])
                    except FileNotFoundError:
                        pass
    except (OSError, ResetError) as exc:
        raise ResetError(f"reset failed after {applied} replacements; target may be partial: {exc}") from exc
    return {"status": "applied_unqualified", "atomic_multi_file": False,
            "confirmatory_eligible": False,
            "files": [{"path": item["path"], "sha256": item["sha256"], "bytes": item["bytes"]}
                      for item in staged]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="explicitly authorize replacing declared target files")
    parser.add_argument("--max-file-bytes", type=int, default=128 * 1024 * 1024)
    args = parser.parse_args()
    try:
        if not args.apply:
            raise ResetError("--apply is required to replace target files")
        files = load_manifest(args.manifest)
        result = restore(args.seed_root, args.target_root, files, max_file_bytes=args.max_file_bytes)
    except ResetError as exc:
        print(f"restore-declared-files: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
