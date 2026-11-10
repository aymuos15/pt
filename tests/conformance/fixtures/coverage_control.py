"""Test-only explicit coverage collector and deliberately broken merge controls."""

import json
import os
from pathlib import Path
import shutil

import coverage


def pytest_sessionstart(session):
    global COLLECTOR
    root = Path(os.environ["PT_COVERAGE_OUTPUT"])
    (root / "shards").mkdir()
    COLLECTOR = coverage.Coverage(config_file=False, data_file=str(root / "shards/data.parent"),
                                 source=[str(Path.cwd() / "source")],
                                 branch=os.environ["PT_COVERAGE_FAULT"] != "omit_branch", context="parent")
    COLLECTOR.set_option("run:core", "ctrace")
    COLLECTOR.start()
    (root / "runtime.json").write_text(json.dumps({"version": coverage.__version__, "branch": COLLECTOR.get_option("run:branch"),
                                                 "effective_core": COLLECTOR._collector.core.tracer_class.__name__}))


def pytest_sessionfinish(session):
    COLLECTOR.stop()
    COLLECTOR.save()
    root = Path(os.environ["PT_COVERAGE_OUTPUT"])
    if os.environ["PT_COVERAGE_FAULT"] == "omit_merge":
        shutil.copyfile(root / "shards/data.parent", root / "merged.coverage")
    else:
        merger = coverage.Coverage(config_file=False, data_file=str(root / "merged.coverage"))
        merger.combine(data_paths=[str(path) for path in sorted((root / "shards").iterdir())], keep=True, strict=True)
        merger.save()
