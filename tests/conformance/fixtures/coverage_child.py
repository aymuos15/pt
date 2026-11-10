"""An actual subprocess that can omit coverage while preserving application work."""

import json
import os
from pathlib import Path
import sys

import coverage


root = Path(os.environ["PT_COVERAGE_OUTPUT"])
fault = os.environ["PT_COVERAGE_FAULT"]
collector = None
if fault != "omit_subprocess":
    collector = coverage.Coverage(config_file=False, data_file=str(root / "shards/data.child"),
                                  source=[str(Path.cwd() / "source")], branch=fault != "omit_branch",
                                  context="parent" if fault == "omit_context" else "child")
    collector.set_option("run:core", "ctrace")
    collector.start()
    (root / "child-runtime.json").write_text(json.dumps({"version": coverage.__version__, "branch": collector.get_option("run:branch"),
                                                       "effective_core": collector._collector.core.tracer_class.__name__}))
sys.path.insert(0, str(Path.cwd() / "source"))
import payload

Path(os.environ["PT_CORE_EVENTS"]).write_text(f"child={payload.child()}\n")
if collector is not None:
    collector.stop()
    collector.save()
