"""Deterministic, intentionally failing pytest phase probe; not a product test."""

import pytest


@pytest.fixture
def setup_failure():
    raise RuntimeError("PT_PROBE_SETUP_FAILURE")


@pytest.fixture
def teardown_failure():
    yield
    raise RuntimeError("PT_PROBE_TEARDOWN_FAILURE")


def test_pass():
    pass


def test_setup_failure(setup_failure):
    pass


def test_teardown_failure(teardown_failure):
    pass


@pytest.mark.xfail(strict=True, reason="PT_PROBE_STRICT_XPASS")
def test_strict_xpass():
    pass
