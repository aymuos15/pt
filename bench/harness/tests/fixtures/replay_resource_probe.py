"""Test-owned background residency through idle and charged shutdown, not a PT daemon."""

import json
import os
from pathlib import Path
import sys
import time


def burn(seconds):
    start = time.process_time_ns()
    while time.process_time_ns() - start < seconds * 1e9:
        sum(range(1000))
    return time.process_time_ns() - start


def worker(root):
    memory = bytearray(64 * 1024 * 1024)
    for offset in range(0, len(memory), 4096):
        memory[offset] = 1
    start, deadline = time.process_time_ns(), time.monotonic() + 25
    (root / "worker.started").touch()
    while not (root / "worker.stop").exists():
        burn(0.02)
        # Atomic test-owned state, not a harness measurement or authenticated record.
        temp = root / "worker.progress.tmp"
        temp.write_text(json.dumps({"cpu_ns": time.process_time_ns() - start, "allocated_bytes": len(memory), "pid": os.getpid()}))
        temp.replace(root / "worker.progress")
        if time.monotonic() > deadline:
            raise RuntimeError("fixture worker was not stopped within its finite safety deadline")
    (root / "worker.finished").write_text(json.dumps({"cpu_ns": time.process_time_ns() - start, "allocated_bytes": len(memory)}))


def main():
    root, role, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if role == "worker":
        worker(root)
        return 0
    with (root / "events").open("a") as events:
        events.write(f"{role}:{os.getpid()}\n")
    if role == "preparation":
        (root / "lease").touch()
        pid = os.fork()
        if pid == 0:
            os.setsid()
            fd = os.open(os.devnull, os.O_RDWR)
            for target in (0, 1, 2):
                os.dup2(fd, target)
            if fd > 2:
                os.close(fd)
            os.execv(sys.executable, [sys.executable, __file__, str(root), "worker", mode])
        # Detach this test-owned future descendant with closed pipes. Cgroup
        # accounting must keep it even though command/PG clocks cannot. It is
        # stopped by declared shutdown, or the outer native cgroup kill.
        deadline = time.monotonic() + 10
        while not (root / "worker.progress").exists():
            if os.waitpid(pid, os.WNOHANG)[0] or time.monotonic() > deadline:
                raise RuntimeError("fixture worker failed to become ready")
            time.sleep(0.005)
        (root / "preparation.progress").write_bytes((root / "worker.progress").read_bytes())
    elif role == "interaction":
        (root / "interaction.progress").write_bytes((root / "worker.progress").read_bytes())
        if mode == "fail":
            return 7
    elif role == "shutdown":
        memory = bytearray(32 * 1024 * 1024)
        for offset in range(0, len(memory), 4096):
            memory[offset] = 1
        (root / "shutdown.cpu").write_text(str(burn(0.15)))
        if mode != "leave_worker":
            (root / "worker.stop").touch()
            deadline = time.monotonic() + 10
            while not (root / "worker.finished").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("fixture shutdown did not release worker")
                time.sleep(0.005)
        (root / "lease").unlink(missing_ok=True)
    (root / ("report-" + role)).write_text("ready\n")
    print("ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
