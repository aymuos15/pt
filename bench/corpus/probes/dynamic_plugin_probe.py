"""Explicit pytest plugin that registers another plugin during collection."""

import os
from pathlib import Path


def record(event):
    with Path(os.environ["PT_PROBE_DYNAMIC_EVENTS"]).open("a", encoding="utf-8") as output:
        output.write(event + "\n")


class LatePlugin:
    def pytest_runtest_setup(self, item):
        record("late setup " + item.name)

    def pytest_runtest_teardown(self, item):
        record("late teardown " + item.name)


def pytest_collection_modifyitems(session, config, items):
    record("collection hook")
    config.pluginmanager.register(LatePlugin(), name="pt-probe-late-plugin")
    record("late plugin registered")
