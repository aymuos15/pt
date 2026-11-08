"""Bounded, immutable local blob publication for exploratory evidence."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, BinaryIO


CHUNK_BYTES = 1024 * 1024


class BlobError(ValueError):
    """Blob input or an existing content-addressed entry is invalid."""


def _verify_existing(path: Path, expected: str, expected_bytes: int) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise BlobError("safe existing-blob verification is unsupported on this platform")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise BlobError("existing blob is not safely readable") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_bytes:
            raise BlobError("existing blob is not a regular file of the expected size")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                    item.st_mtime_ns, item.st_ctime_ns)
        if fingerprint(before) != fingerprint(after) or digest.hexdigest() != expected:
            raise BlobError("existing blob changed or does not match its digest")
    finally:
        os.close(fd)


def publish(source: BinaryIO, directory: Path, *, max_bytes: int) -> dict[str, Any]:
    """Publish source bytes under SHA-256, or verify an existing entry.

    Uses a same-directory temporary file and an atomic no-replace hard link.
    It never silently truncates. The caller owns the source stream and must
    create the destination directory. Directory entries are not fsynced, so
    this is not a guarantee of persistence through power loss.
    """
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a nonnegative integer")
    temporary = None
    digest = hashlib.sha256()
    size = 0
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".pt-blob-", suffix=".tmp",
                                         dir=directory, delete=False) as output:
            temporary = Path(output.name)
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not isinstance(chunk, bytes):
                    raise BlobError("blob source must return bytes")
                if not chunk:
                    break
                if len(chunk) > CHUNK_BYTES:
                    raise BlobError("blob source exceeded requested read size")
                size += len(chunk)
                if size > max_bytes:
                    raise BlobError("blob exceeds configured size limit")
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        sha256 = digest.hexdigest()
        destination = directory / sha256
        try:
            os.link(temporary, destination)
            publication = "created"
        except FileExistsError:
            _verify_existing(destination, sha256, size)
            publication = "already_present"
        return {"sha256": sha256, "stored_bytes": size, "publication": publication}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
