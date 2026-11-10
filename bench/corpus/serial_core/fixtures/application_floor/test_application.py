"""Application-dominated negative control; no speed or representativeness claim."""

import hashlib


def test_application_work():
    data = b"PT serial core application floor\n" * 2048
    actual = [hashlib.sha256(data + str(index).encode()).hexdigest() for index in range(2000)]
    assert len(actual) == 2000
    assert len(set(actual)) == 2000
    assert actual[0] == hashlib.sha256(data + b"0").hexdigest()
