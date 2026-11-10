import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio


def record(message):
    with Path(os.environ["PT_CORE_EVENTS"]).open("a") as output:
        output.write(message + "\n")


record("async import")


@pytest_asyncio.fixture
async def resource():
    loop = asyncio.get_running_loop()
    record("async setup")
    await asyncio.sleep(0)
    yield "ready"
    assert asyncio.get_running_loop() is loop
    await asyncio.sleep(0)
    record("async release")


@pytest_asyncio.fixture
async def broken_resource():
    record("async broken setup")
    await asyncio.sleep(0)
    raise RuntimeError("PT_ECOSYSTEM_ASYNC_SETUP")
    yield  # The fixture is intentionally an async generator with a setup failure.


@pytest.mark.asyncio
async def test_awaited_body(resource):
    assert resource == "ready"
    await asyncio.sleep(0)
    record("async awaited body")


@pytest.mark.asyncio
async def test_failure_after_await(resource):
    await asyncio.sleep(0)
    record("async failing body")
    assert False, "PT_ECOSYSTEM_ASYNC_FAILURE"


@pytest.mark.asyncio
async def test_setup_error_has_no_body(broken_resource):
    record("must not run after async setup error")
