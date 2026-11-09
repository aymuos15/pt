"""Cooperative, instrumented timing fixture; never a PT backend or oracle."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import time
import traceback

import coverage
import pytest


ROOT = Path(sys.argv[1])
TARGET = sys.argv[2]
MODE = sys.argv[3]
REPORTS = []


def record(event):
    with (ROOT / "events.txt").open("a", encoding="utf-8") as output:
        output.write(event + "\n")


@contextmanager
def stage(name):
    record(f"{name}:begin")
    if name == TARGET:
        (ROOT / "ready").write_text(name)
        if MODE != "omit-delay":
            deadline = time.monotonic() + 10
            while not (ROOT / "release").exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"parent did not release {name}")
                time.sleep(0.005)
    yield
    record(f"{name}:end")


@pytest.hookimpl(wrapper=True)
def pytest_collection(session):
    with stage("collection"):
        return (yield)


@pytest.fixture
def required_resource():
    (ROOT / "lease").write_text(str(os.getpid()))
    record("setup")
    yield
    with stage("teardown"):
        record("fixture-finalized")


def pytest_runtest_logreport(report):
    REPORTS.append({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome})


def pytest_sessionfinish(session, exitstatus):
    with stage("reporting"):
        (ROOT / "pytest-report.json").write_text(json.dumps({
            "exitstatus": int(exitstatus),
            "collected": [item.nodeid for item in session.items],
            "reports": REPORTS,
        }))


def main():
    # This is an isolated fixture policy, not a production plugin policy.
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        os.environ.pop(name, None)
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    sys.path.insert(0, str(ROOT))
    (ROOT / "pytest.ini").write_text("[pytest]\n")
    (ROOT / "payload.py").write_text(
        "def tested():\n    return 1\n\ndef companion():\n    return 2\n"
    )
    (ROOT / "test_work.py").write_text(
        "from pathlib import Path\nfrom payload import tested as workload\n"
        "def test_work(required_resource):\n"
        "    assert Path('lease').is_file()\n"
        "    with Path('events.txt').open('a') as output:\n"
        "        output.write('call\\n')\n"
        "    assert workload() == 1\n"
    )
    data_file = str(ROOT / ".coverage")
    measured = coverage.Coverage(
        data_file=data_file, data_suffix="pytest", config_file=False,
        include=[str(ROOT / "payload.py")],
    )
    measured.start()
    try:
        exitstatus = pytest.main(
            ["-c", str(ROOT / "pytest.ini"), "-p", "no:cacheprovider", "-q", "test_work.py"],
            plugins=[sys.modules[__name__]],
        )
    finally:
        measured.stop()
    measured.save()

    # A second, distinct diagnostic workload supplies a real second data shard.
    # It does not replay pytest or any test, and is not subprocess-coverage proof.
    import payload
    companion = coverage.Coverage(
        data_file=data_file, data_suffix="companion", config_file=False,
        include=[str(ROOT / "payload.py")],
    )
    companion.start()
    try:
        assert payload.companion() == 2
    finally:
        companion.stop()
    companion.save()

    merged = coverage.Coverage(data_file=data_file, config_file=False)
    with stage("coverage_merge"):
        merged.combine(data_paths=[str(ROOT)], strict=True)
        merged.save()
    with stage("coverage_report"):
        merged.json_report(outfile=str(ROOT / "coverage.json"))
    with stage("cleanup"):
        if MODE != "omit-cleanup":
            (ROOT / "lease").unlink()
            (ROOT / "cleanup.json").write_text(json.dumps({"released": True}))
    return int(exitstatus)


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:
        (ROOT / "failure.txt").write_text(traceback.format_exc())
        raise
    raise SystemExit(status)
