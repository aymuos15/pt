"""Explicitly loaded custom collector, with intentionally duplicate node IDs."""

import pytest


def pytest_collect_file(file_path, parent):
    if file_path.suffix == ".ptcase":
        return CaseFile.from_parent(parent, path=file_path)


class CaseFile(pytest.File):
    def collect(self):
        for line in self.path.read_text().splitlines():
            outcome, name = line.split(":", 1)
            yield CaseItem.from_parent(self, name=name, expected_outcome=outcome)


class CaseItem(pytest.Item):
    def __init__(self, *, expected_outcome, **kwargs):
        super().__init__(**kwargs)
        self.expected_outcome = expected_outcome

    def runtest(self):
        if self.expected_outcome == "fail":
            raise AssertionError("PT_CORE_CUSTOM_FAILURE")
