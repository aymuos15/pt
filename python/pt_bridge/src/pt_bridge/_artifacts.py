"""Explicit required-JUnit readiness, not completeness or generation proof.

Only stdlib/native file operations; no discovery, installer, project imports,
format conversion, output repair, permission changes or saved-return recovery.
The Rust coordinator must still independently verify owned bytes and context.
"""

from contextlib import ExitStack
import hashlib
import math
import os
import stat
import time


class ArtifactObservationError(ValueError):
    pass


def declaration(value):
    fields = {"artifact_id", "source", "max_bytes", "required"}
    if type(value) is not dict or set(value) != fields:
        raise ArtifactObservationError("closed explicit required-JUnit declaration is required")
    identity = value["artifact_id"]
    if (type(identity) is not str or not 1 <= len(identity) <= 128 or not identity.isascii()
            or not identity[0].isalnum() or any(not (part.isalnum() or part in "._:-") for part in identity)):
        raise ArtifactObservationError("invalid JUnit artifact ID")
    source = value["source"]
    if type(source) is not str:
        raise ArtifactObservationError("JUnit source must be an ordinary canonical relative path")
    raw = source.encode("utf-8", errors="strict")
    parts = raw.split(b"/")
    if not 1 <= len(raw) <= 4096 or b"\0" in raw or len(parts) > 24 or any(part in (b"", b".", b"..") for part in parts):
        raise ArtifactObservationError("JUnit source must be an ordinary bounded canonical relative path")
    if type(value["max_bytes"]) is not int or not 1 <= value["max_bytes"] <= 128 * 1024 * 1024:
        raise ArtifactObservationError("explicit positive JUnit byte bound must be at most 128 MiB")
    if value["required"] is not True:
        raise ArtifactObservationError("only explicitly required JUnit readiness is implemented")
    return value


def _deadline(deadline):
    if type(deadline) not in (float, int) or not math.isfinite(deadline):
        raise ArtifactObservationError("JUnit observation needs a finite absolute deadline")
    if time.monotonic() >= deadline:
        raise ArtifactObservationError("absolute JUnit observation deadline expired")


def _binding(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _stamp(info):
    return _binding(info) + (info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class DirectoryPin:
    """Owned no-follow directory chain; unrelated ancestor entries are not input."""

    def __init__(self, root, deadline):
        raw = os.fsencode(root)
        names = raw.split(b"/")[1:]
        if (not raw.startswith(b"/") or len(raw) > 4096 or b"\0" in raw
                or len(names) > 24 or any(part in (b"", b".", b"..") for part in names) and raw != b"/"):
            raise ArtifactObservationError("unsupported canonical JUnit root path")
        self.path, self.links, self.closed = raw, [], False
        self.owned = ExitStack()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            _deadline(deadline)
            self.anchor = os.open(b"/", flags)
            self.owned.callback(os.close, self.anchor)
            parent = self.anchor
            for name in ([] if raw == b"/" else names):
                _deadline(deadline)
                child = os.open(name, flags, dir_fd=parent)
                self.owned.callback(os.close, child)
                self.links.append((parent, name, child, _binding(os.fstat(child))))
                parent = child
            self.tail = parent
            self.validate(deadline)
        except BaseException:
            self.close()
            raise

    def validate(self, deadline):
        if self.closed:
            raise ArtifactObservationError("closed JUnit root cannot be resumed")
        for parent, name, child, expected in self.links:
            _deadline(deadline)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if _binding(named) != expected or _binding(os.fstat(child)) != expected:
                raise ArtifactObservationError("JUnit root directory binding changed")
        _deadline(deadline)

    def close(self):
        if not self.closed:
            self.closed = True
            self.owned.close()


class DeclaredJunit:
    def __init__(self, value, root, deadline):
        self.value, self.deadline = dict(declaration(value)), deadline
        self.root = DirectoryPin(root, deadline)
        self.expected_path = self.root.path.rstrip(b"/") + b"/" + self.value["source"].encode("utf-8")

    def close(self):
        self.root.close()

    def ready(self, *, complete):
        """One bounded producer assertion. No file presence implies valid XML."""
        if type(complete) is not bool:
            raise ArtifactObservationError("JUnit completeness assertion must be boolean")
        self.root.validate(self.deadline)
        with ExitStack() as owned:
            parent, bindings = self.root.tail, []
            parts = self.value["source"].encode("utf-8").split(b"/")
            for name in parts[:-1]:
                _deadline(self.deadline)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                owned.callback(os.close, child)
                bindings.append((parent, name, child, _binding(os.fstat(child))))
                parent = child
            _deadline(self.deadline)
            name = parts[-1]
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(named.st_mode) or named.st_nlink != 1 or named.st_uid != os.geteuid()
                    or named.st_mode & 0o022 or not 0 <= named.st_size <= self.value["max_bytes"]):
                raise ArtifactObservationError("JUnit output must be owned, non-other-writable, singly linked regular bytes within its bound")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            owned.callback(os.close, fd)
            before = _stamp(named)
            if _stamp(os.fstat(fd)) != before:
                raise ArtifactObservationError("JUnit output binding changed before read")
            digest, count = hashlib.sha256(), 0
            while True:
                _deadline(self.deadline)
                raw = os.read(fd, min(65536, named.st_size - count + 1))
                _deadline(self.deadline)
                if not raw:
                    break
                count += len(raw)
                if count > named.st_size:
                    raise ArtifactObservationError("JUnit output grew during bounded read")
                digest.update(raw)
            if count != named.st_size or _stamp(os.fstat(fd)) != before or _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) != before:
                raise ArtifactObservationError("JUnit output length, bytes or binding changed during read")
            for ancestor, component, child, expected in bindings:
                _deadline(self.deadline)
                if _binding(os.fstat(child)) != expected or _binding(os.stat(component, dir_fd=ancestor, follow_symlinks=False)) != expected:
                    raise ArtifactObservationError("JUnit output parent binding changed during read")
            self.root.validate(self.deadline)
            return {"artifact_id": self.value["artifact_id"], "bytes": count, "sha256": digest.hexdigest(), "complete": complete}
