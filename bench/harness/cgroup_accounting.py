"""Fresh cgroup-v2 counters, not RSS estimates or a hostile-process sandbox."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import platform
import re
import stat
import sys
import threading
import time
import uuid


MAX_COUNTER_BYTES = 16384
MAX_SAMPLES = 4096
CPU_KEYS = ("usage_usec", "user_usec", "system_usec")
CAPABILITIES = ("cpu_stat", "memory_current", "memory_peak", "memory_events", "population", "kill", "enrollment")


class UnsupportedAccounting(ValueError):
    pass


class AccountingSetupError(RuntimeError):
    pass


def _cgroup2(fd):
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise UnsupportedAccounting("initial resource backend requires Linux x86-64")
    try:
        fstatfs = ctypes.CDLL(None, use_errno=True).fstatfs
    except (AttributeError, OSError) as exc:
        raise UnsupportedAccounting("libc fstatfs unavailable") from exc
    fstatfs.argtypes, fstatfs.restype = [ctypes.c_int, ctypes.c_void_p], ctypes.c_int
    # Linux x86-64 struct statfs is smaller than this correctly aligned buffer.
    buffer = (ctypes.c_long * 32)()
    if fstatfs(fd, ctypes.byref(buffer)) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    if buffer[0] != 0x63677270:  # CGROUP2_SUPER_MAGIC; reject ordinary/fake filesystems.
        raise UnsupportedAccounting("supplied parent is not a cgroup-v2 filesystem")


def uint(raw):
    if re.fullmatch(r"[0-9]+\n?", raw) is None:
        raise ValueError("invalid unsigned kernel counter")
    value = int(raw)
    if value > 2**64 - 1:
        raise ValueError("kernel counter exceeds uint64")
    return value


def counters(raw, required=()):
    result = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2 or re.fullmatch(r"[a-z_]+", fields[0]) is None or fields[0] in result:
            raise ValueError("invalid or duplicate kernel counter key")
        result[fields[0]] = uint(fields[1])
    if not set(required).issubset(result):
        raise ValueError("required kernel counters are missing")
    if len(result) > 64:
        raise ValueError("too many kernel counters")
    return result


def delta(before, after, keys):
    if before is None or after is None:
        return None
    if any(key not in before or key not in after or after[key] < before[key] for key in keys):
        raise ValueError("kernel counters decreased or lost required fields")
    return {key: after[key] - before[key] for key in keys}


class CgroupDirectory:
    """Own only a newly created child of an explicitly supplied delegated parent.

    Never enable controllers, change limits, adopt existing tasks/groups or tune
    the host. Ancestors of the parent remain caller-owned, not a security boundary.
    """

    def __init__(self, parent):
        self.parent_fd = self.fd = None
        if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW"):
            raise UnsupportedAccounting("safe Linux cgroup access unavailable")
        if parent is None:
            raise UnsupportedAccounting("an explicit writable delegated --cgroup-parent is required")
        self.parent = Path(os.path.abspath(parent))
        self.name = f"pt-bench-{uuid.uuid4().hex}"
        self.path = self.parent / self.name
        created = False
        try:
            self.parent_fd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            _cgroup2(self.parent_fd)
            os.mkdir(self.name, mode=0o700, dir_fd=self.parent_fd)
            created = True
            self.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.parent_fd)
            _cgroup2(self.fd)
            item = os.fstat(self.fd)
            self.identity = [item.st_dev, item.st_ino]
        except BaseException as original:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            try:
                if created:
                    os.rmdir(self.name, dir_fd=self.parent_fd)
            except OSError as cleanup:
                raise AccountingSetupError(f"owned cgroup setup failed and {self.path} could not be removed: {cleanup}") from original
            finally:
                self.close()
            raise

    def verify(self):
        named = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(named.st_mode) or [named.st_dev, named.st_ino] != self.identity:
            raise ValueError("owned cgroup identity changed")

    def open(self, name, *, write=False):
        self.verify()
        return os.open(name, (os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=self.fd)

    def read(self, name):
        fd = self.open(name)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("kernel counter is not a regular cgroup interface")
            raw = os.read(fd, MAX_COUNTER_BYTES + 1)
            if len(raw) > MAX_COUNTER_BYTES:
                raise ValueError("oversized cgroup counter file")
            self.verify()
            return raw.decode("ascii")
        finally:
            os.close(fd)

    def reader(self):
        """Independent observer descriptors; a late sampler cannot reuse closed FDs."""
        self.verify()
        reader = object.__new__(CgroupDirectory)
        reader.parent, reader.name, reader.path = self.parent, self.name, self.path
        reader.identity = self.identity.copy()
        reader.parent_fd, reader.fd = os.dup(self.parent_fd), None
        try:
            reader.fd = os.dup(self.fd)
        except BaseException:
            reader.close()
            raise
        return reader

    def kill(self):
        fd = self.open("cgroup.kill", write=True)
        try:
            if os.write(fd, b"1\n") != 2:
                raise OSError("short cgroup.kill write")
        finally:
            os.close(fd)

    def remove(self):
        if counters(self.read("cgroup.events"), ("populated",))["populated"] != 0:
            raise ValueError("cannot remove a populated cgroup")
        remaining = [1000]

        def empty_children(fd, depth=0):
            if depth > 64:
                raise ValueError("cgroup cleanup nesting exceeds bound")
            with os.scandir(fd) as entries:
                names = [entry.name for entry in entries if entry.is_dir(follow_symlinks=False)]
            for name in names:
                remaining[0] -= 1
                if remaining[0] < 0:
                    raise ValueError("too many child cgroups to remove safely")
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    _cgroup2(child)
                    empty_children(child, depth + 1)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=fd)  # Only empty cgroups under this private owned child.

        empty_children(self.fd)
        self.verify()
        os.rmdir(self.name, dir_fd=self.parent_fd)

    def close(self):
        for name in ("fd", "parent_fd"):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


def read_capability(group, name):
    if name == "cpu_stat":
        counters(group.read("cpu.stat"), CPU_KEYS)
    elif name in ("memory_current", "memory_peak"):
        uint(group.read("memory.current" if name == "memory_current" else "memory.peak"))
    elif name == "memory_events":
        counters(group.read("memory.events"), ("oom", "oom_kill"))
    elif name == "population":
        value = counters(group.read("cgroup.events"), ("populated",))["populated"]
        if value not in (0, 1):
            raise ValueError("invalid cgroup population flag")
    else:
        fd = group.open("cgroup.kill" if name == "kill" else "cgroup.procs", write=True)
        os.close(fd)  # Permission check only; never move or kill a task during preflight.


def capabilities(group):
    result = {}
    for name in CAPABILITIES:
        try:
            read_capability(group, name)
            result[name] = {"supported": True, "reason": None}
        except (ValueError, OSError) as exc:
            result[name] = {"supported": False, "reason": f"{type(exc).__name__}: {exc}"}
    return result


def snapshot(group, supported, errors, stage):
    result = {"monotonic_start_ns": time.monotonic_ns()}
    for key, name, parser in (
        ("cpu_stat", "cpu.stat", lambda raw: counters(raw, CPU_KEYS)),
        ("memory_current", "memory.current", uint), ("memory_peak", "memory.peak", uint),
        ("memory_events", "memory.events", lambda raw: counters(raw, ("oom", "oom_kill"))),
        ("population", "cgroup.events", lambda raw: counters(raw, ("populated",))["populated"]),
    ):
        result[key] = None
        if supported[key]["supported"]:
            try:
                result[key] = parser(group.read(name))
                if key == "population" and result[key] not in (0, 1):
                    raise ValueError("invalid cgroup population flag")
            except (OSError, ValueError, KeyboardInterrupt) as exc:
                result[key] = None
                errors.append({"stage": stage, "error": f"{type(exc).__name__}: {exc}"})
    result["monotonic_end_ns"] = time.monotonic_ns()
    return result


class CurrentMemorySampler:
    """Bounded raw current-memory readings. Their maximum is only a lower bound."""

    def __init__(self, group, interval_ns):
        self.group, self.interval_ns = group.reader(), interval_ns
        self.observations, self.errors = [], []
        self.truncated = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="pt-bench-current-memory", daemon=True)

    def _run(self):
        try:
            while True:
                if len(self.observations) >= MAX_SAMPLES:
                    self.truncated = True
                    return
                start = time.monotonic_ns()
                value = uint(self.group.read("memory.current"))
                self.observations.append({"monotonic_start_ns": start, "monotonic_end_ns": time.monotonic_ns(),
                                          "memory_current_bytes": value})
                if self.stop_event.wait(self.interval_ns / 1_000_000_000):
                    return
        except (OSError, ValueError) as exc:
            self.errors.append({"stage": "sampling", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            self.group.close()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread.ident is not None:
            try:
                self.thread.join(timeout=2)
            except KeyboardInterrupt:
                self.errors.append({"stage": "sampling", "error": "memory sampler join interrupted; observation uncertain"})
        else:
            self.group.close()
        if self.thread.is_alive():
            self.errors.append({"stage": "sampling", "error": "memory sampler did not stop within deadline"})
        return {"interval_ns": self.interval_ns, "observations": self.observations.copy(),
                "truncated": self.truncated}
