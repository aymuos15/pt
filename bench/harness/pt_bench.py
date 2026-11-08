"""Independent exploratory command timer; not a confirmatory benchmark harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Any, Sequence


def _stream_posix(process: subprocess.Popen, timeout: float) -> dict[str, Any]:
    """Drain both pipes without retaining output, with bounded timeout cleanup."""
    deadline = time.monotonic() + timeout
    cleanup_deadline = None
    timed_out = False
    complete = True
    digests = {name: hashlib.sha256() for name in ("stdout", "stderr")}
    sizes = {name: 0 for name in digests}
    with selectors.DefaultSelector() as selector:
        for name in digests:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        try:
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if not timed_out and now >= deadline:
                    timed_out = True
                    cleanup_deadline = now + 1.0
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if timed_out and now >= cleanup_deadline:
                    complete = False
                    break
                limit = cleanup_deadline if timed_out else deadline
                if not selector.get_map():
                    try:
                        process.wait(timeout=max(0, limit - now))
                    except subprocess.TimeoutExpired:
                        pass
                    continue
                for key, _ in selector.select(timeout=max(0, limit - now)):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    else:
                        digests[key.data].update(chunk)
                        sizes[key.data] += len(chunk)
        finally:
            for key in list(selector.get_map().values()):
                selector.unregister(key.fileobj)
                key.fileobj.close()
        # Even when descendant-held pipes outlive the deadline, reap the leader
        # if it has exited; a closed pipe is not itself proof of process exit.
        process.poll()
    return {
        "timed_out": timed_out, "output_complete": complete,
        "process_reaped": process.returncode is not None,
        "stdout_bytes": sizes["stdout"], "stderr_bytes": sizes["stderr"],
        "stdout_sha256": digests["stdout"].hexdigest(),
        "stderr_sha256": digests["stderr"].hexdigest(),
    }


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

    if os.name == "posix":
        output = _stream_posix(process, timeout)
    else:
        # The original prototype path does not provide bounded memory or
        # process-tree cleanup on non-POSIX systems.
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
        output = {
            "timed_out": timed_out, "output_complete": True,
            "process_reaped": process.returncode is not None,
            "stdout_bytes": len(stdout), "stderr_bytes": len(stderr),
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        }

    return {
        "status": "timeout" if output.pop("timed_out") else "exited_unqualified",
        "argv": list(argv), "cwd": str(cwd_path),
        "elapsed_ns": time.monotonic_ns() - start,
        "returncode": process.returncode,
        **output,
    }


def write_record(path: str, record: dict[str, Any]) -> None:
    """Publish a complete record without replacing an existing destination.

    The temporary file is on the destination filesystem so a hard link can
    atomically publish it. A crash may leave a hidden temporary file, but never
    exposes it as the destination before serialization and file synchronization.
    Filesystems without hard-link support fail closed rather than overwriting.
    This does not promise persistence across a power loss (no directory fsync).
    """
    destination = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{destination.name}.",
            suffix=".tmp", dir=destination.parent, delete=False,
        ) as output:
            temp_path = Path(output.name)
            json.dump(record, output, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


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
