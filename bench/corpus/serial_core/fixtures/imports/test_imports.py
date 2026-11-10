"""A separate preflight collection would append an extra import sentinel."""

import os
from pathlib import Path

import pytest


def record(event):
    with Path(os.environ["PT_CORE_EVENTS"]).open("a", encoding="utf-8") as stream:
        stream.write(event + "\n")


record("import")


@pytest.fixture(scope="session", autouse=True)
def lifetime():
    record("session setup")
    yield
    record("session teardown")


def test_call():
    record("call")
