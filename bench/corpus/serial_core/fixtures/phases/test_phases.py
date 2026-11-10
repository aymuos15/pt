"""Intentional adverse outcomes, never successful performance samples."""

import pytest


@pytest.fixture
def broken_setup():
    raise RuntimeError("PT_CORE_SETUP_FAILURE")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("PT_CORE_TEARDOWN_FAILURE")


def test_pass():
    pass


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass


@pytest.mark.xfail(strict=True, reason="PT_CORE_STRICT_XPASS")
def test_strict_xpass():
    pass


@pytest.mark.skip(reason="PT_CORE_SKIP")
def test_skip():
    pass


@pytest.mark.xfail(strict=True, reason="PT_CORE_EXPECTED_FAILURE")
def test_xfail():
    assert False, "PT_CORE_EXPECTED_FAILURE"
