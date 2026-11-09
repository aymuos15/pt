"""Trusted observer launcher: join a fresh cgroup before exec, never import PT.

Invoked only by resource_run with isolated Python (-I -S). No project imports,
fork, shell, environment mutation or test work precedes enrollment. Its bootstrap
is observer work outside the resource boundary; post-enrollment overhead is not
subtracted. Both private descriptors are closed on subject exec.
"""

import os
import sys


def main():
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        return 125
    procs, control = int(sys.argv[1]), int(sys.argv[2])
    os.set_inheritable(control, False)
    try:
        if os.write(procs, b"0\n") != 2:  # Move this launcher only, never another PID.
            raise OSError("short cgroup enrollment write")
        os.close(procs)
    except OSError as exc:
        os.write(control, f"enrollment_error:{exc.errno}\n".encode("ascii"))
        return 125
    os.write(control, b"enrolled\n")
    try:
        os.execvpe(sys.argv[4], sys.argv[4:], os.environ)
    except (OSError, ValueError) as exc:
        number = exc.errno if isinstance(exc, OSError) else 0
        os.write(control, f"exec_error:{number}\n".encode("ascii"))
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
