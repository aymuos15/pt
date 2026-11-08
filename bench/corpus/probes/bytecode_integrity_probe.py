"""Isolated CPython stale-bytecode negative control; not a PT implementation."""

import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile


OLD = "VALUE = 'old'\n"
NEW = "VALUE = 'new'\n"
FIXED_TIME_NS = 1_700_000_000_000_000_000


def write_source(path, text):
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(FIXED_TIME_NS, FIXED_TIME_NS))


def observed_value(directory):
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONPYCACHEPREFIX"):
        environment.pop(name, None)
    # Retain the prebuilt pyc but prevent this subprocess updating it.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", "import probe_module; print(probe_module.VALUE)"],
        cwd=directory, env=environment, capture_output=True, text=True,
        timeout=10, check=True,
    )
    return result.stdout.strip()


def run_probe():
    with tempfile.TemporaryDirectory(prefix="pt-bytecode-probe-") as directory:
        source = Path(directory) / "probe_module.py"
        results = {}
        for label, mode in (
            ("timestamp_pyc", py_compile.PycInvalidationMode.TIMESTAMP),
            ("checked_hash_pyc", py_compile.PycInvalidationMode.CHECKED_HASH),
        ):
            write_source(source, OLD)
            old_stat = source.stat()
            py_compile.compile(str(source), doraise=True, invalidation_mode=mode)
            write_source(source, NEW)
            new_stat = source.stat()
            results[label] = {
                "same_size": old_stat.st_size == new_stat.st_size,
                "same_mtime_ns": old_stat.st_mtime_ns == new_stat.st_mtime_ns,
                "source_value": "new",
                "observed_value": observed_value(directory),
            }
        return results


if __name__ == "__main__":
    print(json.dumps(run_probe(), sort_keys=True))
