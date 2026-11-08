"""Probe dynamic fixture lookup, autouse behavior, and fixture overriding."""

import os
from pathlib import Path

import pytest


def record(event):
    with Path(os.environ["PT_PROBE_FIXTURE_EVENTS"]).open("a", encoding="utf-8") as output:
        output.write(event + "\n")


@pytest.fixture(autouse=True)
def surrounding():
    record("autouse setup")
    yield
    record("autouse teardown")


@pytest.fixture
def target(target):
    record("override setup")
    yield target + "-override"
    record("override teardown")


def test_dynamic_fixture_lookup(request):
    value = request.getfixturevalue("target")
    record("call " + value)
    assert value == "base-override"
