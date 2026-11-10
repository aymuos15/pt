"""Explicit Linux test-setup wrapper, NOT a supported PT launcher or snapshot.

Run the supplied setup/check command in a new user+private mount namespace with
only explicitly selected /tmp/opencode interpreter inputs bind-mounted read-only.
This prevents isolated tool probes (-I ignores PYTHONDONTWRITEBYTECODE) from
silently rewriting those test inputs. No parent mount/permission/input repair.
Writable host aliases, namespace capabilities and undeclared inputs remain:
this is not immutable-generation, sandbox, environment or release qualification.
"""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys


def guarded_prefix(value):
    raw = os.fsencode(value)
    if (not raw.startswith(b"/tmp/opencode/") or len(raw) > 4096 or b"\0" in raw
            or len(raw.split(b"/")) > 25 or any(part in (b"", b".", b"..") for part in raw.split(b"/")[1:])):
        raise ValueError("test prefix must be an explicit canonical /tmp/opencode directory")
    owned = []
    try:
        parent = os.open(b"/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        owned.append(parent)
        for component in raw.split(b"/")[1:]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            owned.append(parent)
    finally:
        for fd in reversed(owned):
            os.close(fd)
    return value


def run_mount(argv):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout + result.stderr)
        raise SystemExit("private read-only setup mount failed; command not started; no repair/retry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly allow this test-only namespace setup and command")
    parser.add_argument("--prefix", action="append", required=True, help="already prepared test input, never adopted as expected truth")
    parser.add_argument("--_inside", nargs=2, type=int, help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.execute or not command or not command[0] or not 1 <= len(args.prefix) <= 8 or len(set(args.prefix)) != len(args.prefix):
        parser.error("--execute, 1–8 distinct explicit prefixes and -- COMMAND are required")
    if sys.platform != "linux":
        parser.error("this test-only namespace wrapper targets Linux")
    for prefix in args.prefix:
        guarded_prefix(prefix)
    if args._inside is None:
        with ExitStack() as owned:
            descriptors = []
            for name in ("/proc/self/ns/mnt", "/proc/self/ns/user"):
                fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC)
                owned.callback(os.close, fd)
                descriptors.append(fd)
                os.set_inheritable(fd, True)  # Only across the explicit setup bootstrap.
            argv = ["/usr/bin/unshare", "--user", "--map-root-user", "--mount", "--propagation", "private", "--",
                    sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve()), "--execute", "--_inside", *map(str, descriptors)]
            for prefix in args.prefix:
                argv += ["--prefix", prefix]
            argv += ["--", *command]
            os.execv(argv[0], argv)
    for fd, name in zip(args._inside, ("mnt", "user")):
        if fd < 3 or not os.readlink(f"/proc/self/fd/{fd}").startswith(name + ":["):
            parser.error("original namespace descriptor missing; no mount attempted")
        before, current = os.fstat(fd), os.stat("/proc/self/ns/" + name)
        if (before.st_dev, before.st_ino) == (current.st_dev, current.st_ino):
            parser.error("not in distinct private setup namespaces; no mount attempted")
        os.close(fd)
    with open("/proc/self/mountinfo", "rb") as source:
        mountinfo = source.read(4*1024*1024+1)
    if len(mountinfo) > 4*1024*1024 or any(part.startswith((b"shared:", b"master:")) for line in mountinfo.splitlines() for part in line.split()):
        parser.error("mount propagation is not private/bounded; no mount attempted")
    for prefix in args.prefix:
        run_mount(["/usr/bin/mount", "--no-mtab", "--bind", prefix, prefix])
        run_mount(["/usr/bin/mount", "--no-mtab", "--options", "remount,bind,ro,nosuid,nodev", prefix])
        if not os.statvfs(prefix).f_flag & os.ST_RDONLY:
            raise SystemExit("read-only test input mount not observed; command not started")
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
