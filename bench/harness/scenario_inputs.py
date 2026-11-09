"""Bounded declared-file observations and explicit nontransactional reset/edit effects."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import io
import os
from pathlib import Path
import secrets
import stat
import time

import blob_store
import finalization as files
import pt_bench as timer


MAX_FILE_BYTES = 1024 * 1024
MAX_BLOB_BYTES = 128 * 1024 * 1024
MAX_BLOBS = 2048
FAILURES = (OSError, ValueError, RuntimeError, KeyboardInterrupt)


@contextmanager
def parent(root, path):
    files.require_safe_lookup()
    files.relative_path(path)
    with ExitStack() as stack:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        parts = Path(path).parts
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd, parts[-1]


def read(root, path):
    """Parents must exist. Only a missing final name is known absent, never a missing root."""
    with parent(root, path) as (directory, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None, b"", None
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_BYTES
                    or stat.S_IMODE(before.st_mode) > 0o777):
                raise ValueError("scenario input is not a single-link ordinary file within the byte/mode limit")
            chunks, count = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_FILE_BYTES - count + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                if count > MAX_FILE_BYTES:
                    raise ValueError("scenario input grew beyond byte limit")
            after, named = os.fstat(fd), os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (files._fingerprint(before) != files._fingerprint(after) or files._fingerprint(after) != files._fingerprint(named)
                    or count != after.st_size or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1):
                raise ValueError("scenario input changed during observation")
            raw = b"".join(chunks)
            return {"bytes": count, "sha256": hashlib.sha256(raw).hexdigest(), "mode": stat.S_IMODE(after.st_mode)}, raw, files._fingerprint(after)
        finally:
            os.close(fd)


def check_limits(bundle):
    total, count = 0, 0
    with os.scandir(bundle) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                raise ValueError("scenario blob store contains nonregular evidence")
            total += entry.stat(follow_symlinks=False).st_size
            count += 1
    if total > MAX_BLOB_BYTES or count > MAX_BLOBS:
        raise ValueError("scenario blob evidence exceeds aggregate byte/file limit")
    return total, count


def store(raw, bundle):
    total, count = check_limits(bundle)
    digest = hashlib.sha256(raw).hexdigest()
    if not os.path.lexists(bundle / digest):
        total += len(raw)
        count += 1
    if total > MAX_BLOB_BYTES or count > MAX_BLOBS:
        raise ValueError("scenario blob evidence exceeds aggregate byte/file limit")
    stored = blob_store.publish(io.BytesIO(raw), bundle, max_bytes=MAX_FILE_BYTES)
    if stored["sha256"] != digest or stored["stored_bytes"] != len(raw):
        raise ValueError("scenario blob publication differs from observed input")


def snapshot(root, paths, bundle):
    start, rows = time.monotonic_ns(), []
    for path in paths:
        row = {"path": path, "status": "unknown", "value": None, "identity": None, "error": None}
        try:
            value, raw, identity = read(root, path)
            if value is not None:
                store(raw, bundle)
            row.update(status="present" if value is not None else "absent", value=value, identity=identity)
        except FAILURES as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return {"files": rows, "clock": timer._timing(start)}


def values(snapshot):
    if snapshot is None or any(row["status"] == "unknown" for row in snapshot["files"]):
        return None
    return {row["path"]: row["value"] for row in snapshot["files"]}


def _target(directory, name, expected):
    try:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        if expected is not None:
            raise ValueError("scenario target disappeared before mutation")
        return
    if expected is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or files._fingerprint(info) != expected:
        raise ValueError("scenario target changed before mutation")


def _create(directory, source, destination):
    """No-overwrite creation; never replace a concurrently appeared final name."""
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as exc:
        raise ValueError("scenario creation requires Linux renameat2(RENAME_NOREPLACE)") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory, os.fsencode(source), directory, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def mutate(root, observed, desired, bundle):
    """One explicit file effect. No retry, rollback, directory creation or multi-file atomicity."""
    path = observed["path"]
    current, _raw, identity = read(root, path)
    if not timer._same_json(current, observed["value"]) or identity != observed["identity"]:
        raise ValueError("scenario precondition changed before mutation")
    if timer._same_json(current, desired):
        return "unchanged"
    raw = None
    if desired is not None:
        metadata, raw = files.inspect_file(bundle, desired["sha256"], limit=MAX_FILE_BYTES, retain=True)
        if metadata["bytes"] != desired["bytes"] or metadata["sha256"] != desired["sha256"]:
            raise ValueError("scenario edit payload differs from bound bytes")
    with parent(root, path) as (directory, name):
        _target(directory, name, identity)
        if desired is None:
            os.unlink(name, dir_fd=directory)
            return "applied"
        temporary = ".pt-scenario-" + secrets.token_hex(16) + ".tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise OSError("short scenario mutation write")
                    view = view[count:]
                os.fchmod(fd, desired["mode"])
                os.fsync(fd)
            finally:
                os.close(fd)
            _target(directory, name, identity)
            if identity is None:
                _create(directory, temporary, name)
            else:
                os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return "applied"
