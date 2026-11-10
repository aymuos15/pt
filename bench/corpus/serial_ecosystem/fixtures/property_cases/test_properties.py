import os
from pathlib import Path

from hypothesis import given, settings, strategies as st


def record(message):
    with Path(os.environ["PT_CORE_EVENTS"]).open("a") as output:
        output.write(message + "\n")


record("property import")


@settings(max_examples=2, database=None, derandomize=True, deadline=None)
@given(st.booleans())
def test_boolean_domain(value):
    record("boolean " + str(value))
    assert (not not value) is value


@settings(max_examples=4, database=None, derandomize=True, deadline=None)
@given(st.tuples(st.booleans(), st.booleans()))
def test_pair_domain(value):
    first, second = value
    record("pair " + str(first) + " " + str(second))
    assert (first and second) == (second and first)
