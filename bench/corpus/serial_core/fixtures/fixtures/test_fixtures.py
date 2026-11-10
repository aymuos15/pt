from conftest import record
import pytest


@pytest.fixture(autouse=True)
def automatic():
    record("autouse setup")
    yield
    record("autouse teardown")


@pytest.fixture
def target(target):
    record("override setup")
    yield target + "-override"
    record("override teardown")


def test_dynamic_lookup(request):
    assert request.getfixturevalue("target") == "base-override"
    record("call")
