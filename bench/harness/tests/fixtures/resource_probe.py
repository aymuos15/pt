"""Test-owned CPU/anonymous-memory sentinels, not PT or benchmark workloads."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def worker(root, name, mib, cpu_ms, linger):
    allocation = bytearray(mib * 1024 * 1024)
    for offset in range(0, len(allocation), 4096):
        allocation[offset] = 1
    start = time.process_time_ns()
    while time.process_time_ns() - start < cpu_ms * 1_000_000:
        pass
    temporary = root / f"{name}.tmp"
    temporary.write_text(json.dumps({"pid": os.getpid(), "allocated_bytes": len(allocation),
                                     "cpu_ns": time.process_time_ns() - start}))
    temporary.replace(root / f"{name}.json")
    if linger:
        time.sleep(30)
    # The allocation is retained until this function exits, not freed at the sentinel.
    return len(allocation) > 0


def main():
    root, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "worker":
        if len(sys.argv) > 7:
            # This worker was born inside the fresh boundary, then moves only to
            # its own descendant cgroup. No existing external process is adopted.
            (Path(sys.argv[7]) / "cgroup.procs").write_text("0\n")
        worker(root, sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6] == "linger")
        return
    subgroup = None
    if mode == "subgroup_detached":
        own = Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1].lstrip("/")
        subgroup = own / "fixture-child"
        subgroup.mkdir()
    detached = mode in ("detached", "subgroup_detached")
    runs = 2 if mode == "sequential" else 1
    for index in range(runs):
        name = f"worker-{index}"
        command = [sys.executable, __file__, str(root), "worker", name,
                   "80" if mode == "sequential" else "64", "50" if mode == "sequential" else "200",
                   "linger" if detached else "exit"]
        if subgroup is not None:
            command.append(str(subgroup))
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 10
        while not (root / f"{name}.json").exists():
            if child.poll() is not None:
                raise RuntimeError(f"worker exited without a sentinel: {child.returncode}")
            if time.monotonic() >= deadline:
                child.kill()
                child.wait()
                raise RuntimeError("resource worker failed to become ready")
            time.sleep(0.005)
        if not detached:
            if child.wait(timeout=10) != 0:
                raise RuntimeError("resource worker failed")
        else:
            # Deliberately broken command: return zero with closed pipes while a
            # detached worker retains memory. Only the private cgroup owns it now.
            print("ready")


if __name__ == "__main__":
    main()
