"""Bounded, immutable local blob publication for exploratory evidence."""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, BinaryIO


CHUNK_BYTES = 1024 * 1024
AT_FDCWD = -100
RENAME_NOREPLACE = 1


class BlobError(ValueError):
    """Blob input or an existing content-addressed entry is invalid."""


def _publish_noreplace(source: Path, destination: Path) -> None:
    """Atomically move the only staging name, never replace a destination.

    Python 3.12's os.rename cannot request no-replace semantics on Linux.
    A link/unlink handoff is not equivalent: its later unlink changes ctime
    underneath readers verifying the newly visible inode. Fail closed if the
    libc/kernel/filesystem primitive is unavailable; never emulate with links
    or a check-then-overwriting rename.
    """
    if sys.platform != "linux":
        raise BlobError("blob publication requires Linux renameat2(RENAME_NOREPLACE)")
    source_bytes, destination_bytes = os.fsencode(source), os.fsencode(destination)
    if b"\0" in source_bytes or b"\0" in destination_bytes:
        raise ValueError("embedded null byte in blob path")
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as exc:
        raise BlobError("blob publication requires libc renameat2(RENAME_NOREPLACE)") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(AT_FDCWD, source_bytes, AT_FDCWD, destination_bytes, RENAME_NOREPLACE) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(destination))


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

    Uses a same-directory temporary file and Linux renameat2(RENAME_NOREPLACE).
    The visible inode has no staging hardlink that cleanup can later unlink.
    Existing entries still require unchanged metadata and a matching digest;
    no retries discard evidence of mutation. Unsupported native operations fail
    rather than falling back to a weaker publication. It never silently
    truncates. The caller owns the source stream and destination directory.
    Directory entries are not fsynced: this is not power-loss durability or a
    race-resistant, hostile-directory store.
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
            _publish_noreplace(temporary, destination)
            temporary = None
            publication = "created"
        except FileExistsError:
            _verify_existing(destination, sha256, size)
            publication = "already_present"
        return {"sha256": sha256, "stored_bytes": size, "publication": publication}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
