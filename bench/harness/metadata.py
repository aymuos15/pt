"""Best-effort, non-secret host metadata for exploratory observations."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from typing import Any


def collect_metadata() -> dict[str, Any]:
    """Describe the harness host/runtime, not the benchmark commands' environments.

    This is not a complete machine profile and does not establish limits,
    isolation, artifact identity, or suitability for confirmatory measurements.
    No environment-variable names or values are collected.
    """
    executable_digest = None
    digest_error = None
    try:
        digest = hashlib.sha256()
        with open(sys.executable, "rb") as executable:
            for chunk in iter(lambda: executable.read(1024 * 1024), b""):
                digest.update(chunk)
        executable_digest = digest.hexdigest()
    except OSError as exc:
        digest_error = type(exc).__name__

    affinity = None
    affinity_error = None
    if hasattr(os, "sched_getaffinity"):
        try:
            affinity = sorted(os.sched_getaffinity(0))
        except OSError as exc:
            affinity_error = type(exc).__name__
    else:
        affinity_error = "unsupported"

    return {
        "status": "incomplete_unqualified",
        "os": platform.system(), "kernel_release": platform.release(),
        "architecture": platform.machine(), "logical_cpu_count": os.cpu_count(),
        "harness_affinity_cpus": affinity, "affinity_error": affinity_error,
        "harness_python_implementation": platform.python_implementation(),
        "harness_python_version": platform.python_version(),
        "harness_python_executable": sys.executable,
        "harness_python_executable_sha256": executable_digest,
        "harness_python_digest_error": digest_error,
        "limitations": ["not a full machine profile", "arm environments not inspected",
                        "CPU and memory limits not established"],
    }
