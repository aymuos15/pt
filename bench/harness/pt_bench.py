"""Independent exploratory command timer; not a confirmatory benchmark harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Sequence


def measure(argv: Sequence[str], cwd: str, timeout: float) -> dict[str, Any]:
    """Measure one process through exit and pipe drainage, retaining all outcomes."""
    if not argv or not all(isinstance(arg, str) for arg in argv) or not argv[0]:
        raise ValueError("command must have a nonempty executable and string arguments")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    cwd_path = Path(cwd).resolve(strict=True)
    if not cwd_path.is_dir():
        raise ValueError("cwd must be a directory")

    start = time.monotonic_ns()
    try:
        process = subprocess.Popen(
            list(argv), cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return {
            "status": "launch_error", "error": str(exc), "argv": list(argv),
            "cwd": str(cwd_path), "elapsed_ns": time.monotonic_ns() - start,
        }

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()

    return {
        "status": "timeout" if timed_out else "exited_unqualified",
        "argv": list(argv), "cwd": str(cwd_path),
        "elapsed_ns": time.monotonic_ns() - start,
        "returncode": process.returncode,
        "stdout_bytes": len(stdout), "stderr_bytes": len(stderr),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def write_record(path: str, record: dict[str, Any]) -> None:
    """Create a record once; never overwrite earlier evidence."""
    with open(path, "x", encoding="utf-8") as output:
        json.dump(record, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output", required=True, help="new JSON file; never overwritten")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not argv:
        parser.error("a command is required after --")
    try:
        result = measure(argv, args.cwd, args.timeout)
        record = {"schema_version": 1, "mode": "exploratory", "result": result}
        write_record(args.output, record)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"pt-bench: {exc}\n")
    return 0 if result["status"] == "exited_unqualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
