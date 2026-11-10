"""Optional private retention for oracle checks; never imported by project tests."""

import json
import os
from pathlib import Path
import tempfile


def case_root(test):
    destination = os.environ.get("PT_ORACLE_CASE_ROOT")
    if destination is None:
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        return Path(temporary.name)
    path = Path(destination) / test.id()
    path.mkdir(mode=0o700)
    return path


def save_execution(path, command, result):
    path.with_suffix(".stdout").write_text(result.stdout)
    path.with_suffix(".stderr").write_text(result.stderr)
    path.with_suffix(".process.json").write_text(json.dumps({"argv": command, "returncode": result.returncode}, indent=2))
