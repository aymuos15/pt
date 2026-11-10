"""Within-session state and runtime parametrization must remain intact."""

import pytest


state = []


def test_first():
    assert state == []
    state.append("first")


def test_second():
    assert state == ["first"]


@pytest.mark.parametrize("value", ["alpha", "beta"], ids=["alpha", "beta"])
def test_parameter(value):
    assert value in ("alpha", "beta")
