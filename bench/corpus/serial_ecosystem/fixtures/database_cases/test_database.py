import os
from pathlib import Path
import sqlite3

import pytest


def record(message):
    with Path(os.environ["PT_CORE_EVENTS"]).open("a") as output:
        output.write(message + "\n")


with sqlite3.connect("test-state.sqlite") as connection:
    connection.execute("CREATE TABLE IF NOT EXISTS imports (value INTEGER)")
    connection.execute("CREATE TABLE IF NOT EXISTS work (value INTEGER)")
    assert connection.execute("SELECT count(*) FROM imports").fetchone() == (0,), "PT_ECOSYSTEM_EXTRA_COLLECTION_IMPORT"
    connection.execute("INSERT INTO imports VALUES (1)")
connection.close()
record("database import")


@pytest.fixture
def database():
    connection = sqlite3.connect("test-state.sqlite")
    assert connection.execute("SELECT count(*) FROM imports").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM work").fetchone() == (0,)
    lease = Path("database.lease")
    with lease.open("x") as output:
        output.write("test-owned fixture lease\n")
    record("database setup")
    yield connection
    connection.execute("DELETE FROM work")
    connection.commit()
    connection.close()
    lease.unlink()
    record("database release")


def test_write(database):
    database.execute("INSERT INTO work VALUES (7)")
    database.commit()
    assert database.execute("SELECT value FROM work").fetchall() == [(7,)]
    record("database write")


def test_isolated_after_previous_fixture(database):
    assert database.execute("SELECT count(*) FROM work").fetchone() == (0,)
    record("database isolated")
