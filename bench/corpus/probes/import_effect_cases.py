"""Probe to detect extra pytest collection sessions by import side effects."""

import os
from pathlib import Path


def record(event):
    with Path(os.environ["PT_PROBE_IMPORT_EVENTS"]).open("a", encoding="utf-8") as output:
        output.write(event + "\n")


record("module import")


def test_import_effect():
    record("test call")
