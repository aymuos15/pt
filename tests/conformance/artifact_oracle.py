"""Independent, bounded declared-file/absence checks for correctness experiments."""

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_PATHS = 256


class ArtifactError(ValueError):
    pass


def relative_path(value):
    if (type(value) is not str or not value or len(value) > 4096 or "\\" in value or "\0" in value
            or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
            or str(PurePosixPath(value)) != value or value == "."):
        raise ArtifactError("artifact path must be a normalized relative POSIX path")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ArtifactError("unsupported surrogate artifact path") from exc
    return value


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _parent(stack, root, name):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    stack.callback(os.close, fd)
    parts = PurePosixPath(relative_path(name)).parts
    for part in parts[:-1]:
        fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        stack.callback(os.close, fd)
    return fd, parts[-1]


def read_file(root, name):
    """Reject linked components and changed/nonregular files; ancestors are caller-owned."""
    with ExitStack() as stack:
        parent, leaf = _parent(stack, root, name)
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise ArtifactError("required artifact must be a bounded regular file")
        chunks, total = [], 0
        while chunk := os.read(fd, 65536):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise ArtifactError("required artifact grew beyond the byte limit")
            chunks.append(chunk)
        if (_identity(before) != _identity(os.fstat(fd))
                or _identity(before) != _identity(os.stat(leaf, dir_fd=parent, follow_symlinks=False))):
            raise ArtifactError("required artifact changed during read")
        return b"".join(chunks)


def check_artifacts(root, required, *, absent=()):
    """Check externally declared bytes, not an untrusted producer's verified flag."""
    if type(required) is not list or type(absent) not in (tuple, list) or len(required) + len(absent) > MAX_PATHS:
        raise ArtifactError("required artifacts/absences must be bounded explicit lists")
    names, size = [], 0
    for item in required:
        if (type(item) is not dict or set(item) != {"path", "bytes", "sha256"}
                or type(item["bytes"]) is not int or not 0 <= item["bytes"] <= MAX_FILE_BYTES
                or type(item["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ArtifactError("invalid required artifact byte descriptor")
        names.append(relative_path(item["path"]))
        size += item["bytes"]
    names += [relative_path(name) for name in absent]
    if len(set(names)) != len(names) or size > MAX_TOTAL_BYTES:
        raise ArtifactError("duplicate/conflicting artifact paths or aggregate byte bound")
    observed = []
    for item in required:
        raw = read_file(Path(root), item["path"])
        value = {"path": item["path"], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if value != item:
            raise ArtifactError("required artifact bytes differ from the external expectation")
        observed.append(value)
    for name in absent:
        with ExitStack() as stack:
            try:
                parent, leaf = _parent(stack, root, name)
                os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
        raise ArtifactError("required cleanup path is still present")
    return {"status": "matched_declared_artifact_bytes_and_absences", "files": observed, "absent": list(absent),
            "limitations": ["bounded declared files only, not an atomic snapshot, disk quota or proof of all external cleanup"],
            "confirmatory_eligible": False}
