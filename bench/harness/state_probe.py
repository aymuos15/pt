"""Hash explicitly listed regular files for exploratory state comparison."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any


class StateProbeError(ValueError):
    pass


def probe(root: Path, files: list[str], *, max_file_bytes: int) -> dict[str, Any]:
    """Reject symlinks in listed paths and the root's final component.

    Ancestors of the user-supplied root can be symlinks. This is neither a
    sandbox nor an atomic or complete source snapshot.
    """
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd:
        raise StateProbeError("safe relative lookup is unsupported on this platform")
    if type(max_file_bytes) is not int or max_file_bytes < 0:
        raise StateProbeError("max_file_bytes must be a nonnegative integer")
    if not isinstance(files, list) or not files or len(files) > 10000:
        raise StateProbeError("supply between 1 and 10000 file paths")
    paths = []
    for value in files:
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            raise StateProbeError("file paths must be nonempty POSIX-style strings")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
            raise StateProbeError("file paths must be normalized and relative")
        paths.append(value)
    if len(set(paths)) != len(paths):
        raise StateProbeError("duplicate file paths are not allowed")

    records = []
    try:
        with ExitStack() as stack:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root_fd)
            for value in sorted(paths):
                with ExitStack() as file_stack:
                    directory_fd = root_fd
                    components = PurePosixPath(value).parts
                    for component in components[:-1]:
                        directory_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                               dir_fd=directory_fd)
                        file_stack.callback(os.close, directory_fd)
                    fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory_fd)
                    file_stack.callback(os.close, fd)
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode):
                        raise StateProbeError(f"{value}: not a regular file")
                    if before.st_size > max_file_bytes:
                        raise StateProbeError(f"{value}: file exceeds configured limit")
                    digest, size = hashlib.sha256(), 0
                    while True:
                        chunk = os.read(fd, 1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_file_bytes:
                            raise StateProbeError(f"{value}: file exceeds configured limit")
                        digest.update(chunk)
                    after = os.fstat(fd)
                    identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                             item.st_mtime_ns, item.st_ctime_ns)
                    if identity(before) != identity(after) or size != after.st_size:
                        raise StateProbeError(f"{value}: file changed during read")
                    records.append({"path": value, "bytes": size, "sha256": digest.hexdigest()})
    except OSError as exc:
        raise StateProbeError(f"cannot safely read declared file: {exc.strerror or type(exc).__name__}") from exc

    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"schema_version": 1, "scope": "explicitly_listed_files_only", "files": records,
            "state_sha256": hashlib.sha256(canonical).hexdigest(), "atomic_snapshot": False,
            "confirmatory_eligible": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--file", action="append", required=True, dest="files")
    parser.add_argument("--max-file-bytes", type=int, default=128 * 1024 * 1024)
    args = parser.parse_args()
    try:
        result = probe(args.root, args.files, max_file_bytes=args.max_file_bytes)
    except StateProbeError as exc:
        print(f"state-probe: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
