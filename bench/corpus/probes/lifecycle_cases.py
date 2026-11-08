"""Deterministic dynamic collection and fixture-lifecycle corpus probe."""

import os
from pathlib import Path

import pytest


def record(event):
    with Path(os.environ["PT_PROBE_EVENT_FILE"]).open("a", encoding="utf-8") as output:
        output.write(event + "\n")


def pytest_generate_tests(metafunc):
    if "item" in metafunc.fixturenames:
        metafunc.parametrize("item", ["alpha", "beta"], ids=["α", "β"])


@pytest.fixture(scope="session", autouse=True)
def shared_lifecycle():
    record("session setup")
    yield
    record("session teardown")


@pytest.fixture
def per_item(item):
    record(f"setup {item}")
    yield
    record(f"teardown {item}")


def test_lifecycle(item, per_item):
    record(f"call {item}")
