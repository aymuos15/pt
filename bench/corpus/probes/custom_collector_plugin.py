"""Explicitly loaded pytest collector probe; not an auto-registered plugin."""

import pytest


def pytest_collect_file(file_path, parent):
    if file_path.suffix == ".ptcase":
        return CaseFile.from_parent(parent, path=file_path)
    return None


class CaseFile(pytest.File):
    def collect(self):
        for line in self.path.read_text(encoding="utf-8").splitlines():
            outcome, name = line.split(":", 1)
            if outcome not in ("pass", "fail") or not name:
                raise ValueError("invalid custom collector probe input")
            yield CaseItem.from_parent(self, name=name, expected_outcome=outcome)


class CaseItem(pytest.Item):
    def __init__(self, *, expected_outcome, **kwargs):
        super().__init__(**kwargs)
        self.expected_outcome = expected_outcome

    def runtest(self):
        if self.expected_outcome == "fail":
            raise AssertionError("PT_CUSTOM_COLLECTOR_EXPECTED_FAILURE")

    def reportinfo(self):
        return self.path, 0, self.name
