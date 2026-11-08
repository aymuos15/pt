"""Explicit plugin that records cwd presence in sys.path at pytest session start."""

import json
import os
from pathlib import Path
import sys


def pytest_sessionstart(session):
    cwd = os.path.abspath(os.getcwd())
    paths = [os.path.abspath(path) for path in sys.path if isinstance(path, str)]
    report = {"cwd_in_sys_path": cwd in paths,
              "first_path_is_cwd": bool(paths) and paths[0] == cwd}
    Path(os.environ["PT_PROBE_PROFILE_OUTPUT"]).write_text(json.dumps(report), encoding="utf-8")
