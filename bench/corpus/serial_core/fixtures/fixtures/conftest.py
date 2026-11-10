import os
from pathlib import Path

import pytest


def record(event):
    with Path(os.environ["PT_CORE_EVENTS"]).open("a", encoding="utf-8") as stream:
        stream.write(event + "\n")


@pytest.fixture
def target():
    record("base setup")
    yield "base"
    record("base teardown")
