"""Freeze and execute the finite oracle controls, retaining outcomes and raw evidence."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import unittest

from artifact_oracle import read_file


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAX_SOURCE_BYTES = 16 * 1024 * 1024


def _save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _source(root):
    result = {}
    paths = []
    for base in (root / "tests/conformance", root / "bench/corpus/serial_core"):
        paths.extend(base.rglob("*"))
    # Freeze the independent outer observer too, not generated venvs/results.
    paths.extend((root / "bench/harness").glob("*.py"))
    paths.extend(root / "bench/harness" / name for name in ("pyproject.toml", "uv.lock"))
    paths.extend((root / "bench/corpus/assessments").glob("check_flask*.py"))
    paths.extend((root / "bench/corpus/assessments").glob("flask-49943b5-*requirements.*"))
    for path in sorted(paths):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("oracle source cannot contain symbolic links")
        if path.is_dir():
            continue
        if path.suffix not in (".py", ".json", ".md", ".toml", ".lock", ".ptcase", ".in", ".txt"):
            raise ValueError("unexpected oracle/corpus source file")
        name = path.relative_to(root).as_posix()
        result[name] = read_file(root, name)
    if len(result) > 256 or sum(map(len, result.values())) > MAX_SOURCE_BYTES:
        raise ValueError("oracle frozen source inventory exceeds its bound")
    return result


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test.id()


def _child(case_root, destination):
    if os.environ.get("PT_ORACLE_CASE_ROOT") != str(case_root):
        raise ValueError("private child mode requires the explicitly owned case directory")
    suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py")
    planned = list(_flatten(suite))
    outcomes = {name: {"test": name, "status": "not_run", "details": [], "subtests": []} for name in planned}

    class Recorder(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            outcomes[test.id()]["status"] = "started_unknown"

        def addSuccess(self, test):
            super().addSuccess(test)
            outcomes[test.id()]["status"] = "passed"

        def addFailure(self, test, err):
            super().addFailure(test, err)
            outcomes[test.id()]["status"] = "failed"
            outcomes[test.id()]["details"].append(self._exc_info_to_string(err, test))

        def addError(self, test, err):
            super().addError(test, err)
            outcomes[test.id()]["status"] = "error"
            outcomes[test.id()]["details"].append(self._exc_info_to_string(err, test))

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            outcomes[test.id()]["status"] = "skipped"
            outcomes[test.id()]["details"].append(reason)

        def addExpectedFailure(self, test, err):
            super().addExpectedFailure(test, err)
            outcomes[test.id()]["status"] = "expected_failure"
            outcomes[test.id()]["details"].append(self._exc_info_to_string(err, test))

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            outcomes[test.id()]["status"] = "unexpected_success"

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            outcomes[test.id()]["subtests"].append({"test": subtest.id(), "status": "passed" if err is None else "failed",
                                                   "detail": None if err is None else self._exc_info_to_string(err, test)})
            if err is not None:
                outcomes[test.id()]["status"] = "failed"

    result = unittest.TextTestRunner(verbosity=2, resultclass=Recorder).run(suite)
    counts = {status: sum(row["status"] == status for row in outcomes.values()) for status in sorted({row["status"] for row in outcomes.values()})}
    _save(destination, {"kind": "development_oracle_controls", "planned": len(planned), "ran": result.testsRun,
                        "outcomes": list(outcomes.values()), "status_counts": counts, "successful": result.wasSuccessful(),
                        "confirmatory_eligible": False})
    return int(not result.wasSuccessful())


def check(output, *, execute=False, source_root=ROOT):
    if execute is not True:
        raise ValueError("--execute is required to run the real-pytest and deliberate broken controls")
    if (sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 12) or sys.platform != "linux"
            or platform.machine() != "x86_64" or sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise ValueError("oracle checks require Linux x86-64 and GIL-enabled CPython 3.12.12")
    versions = {name: metadata.version(name) for name in ("pytest", "coverage", "jsonschema")}
    if versions != {"pytest": "8.4.2", "coverage": "7.17.2", "jsonschema": "4.25.1"}:
        raise ValueError("oracle dependency versions differ from the locked development contract")
    source_root, output = Path(source_root).resolve(strict=True), Path(os.path.abspath(output))
    if output.parent.resolve(strict=True).is_relative_to(source_root) or source_root.is_relative_to(output):
        raise ValueError("oracle evidence and source roots must be separate and nonnested")
    source = _source(source_root)
    output.mkdir(mode=0o700)
    frozen = output / "frozen"
    for name, raw in source.items():
        path = frozen / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    manifest = [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(source.items())]
    _save(output / "source-manifest.json", {"files": manifest, "development_only": True})
    for name in ("cases", "raw", "home", "tmp"):
        (output / name).mkdir(mode=0o700)
    # The independent harness controls only this outer correctness experiment.
    # It is never imported into reference pytest children or the product.
    sys.path.insert(0, str(ROOT / "bench/harness"))
    try:
        import pt_bench as timer
        import raw_capture
        import finalization
    finally:
        sys.path.pop(0)
    environment = {"PATH": os.defpath, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PT_ORACLE_CASE_ROOT": str(output / "cases")}
    command = ["/usr/bin/env", "-i", *[key + "=" + value for key, value in sorted(environment.items())],
               sys.executable, "-W", "error::ResourceWarning", str(frozen / "tests/conformance/check_oracle.py"),
               "--_frozen-child", str(output / "cases"), str(output / "checks.json")]
    report = {"kind": "frozen_development_oracle_check", "status": "unknown_execution_return", "observation": None, "checks": None,
              "source_manifest_sha256": hashlib.sha256((output / "source-manifest.json").read_bytes()).hexdigest(),
              "runtime_versions": versions, "confirmatory_eligible": False, "errors": [],
              "qualification": {key: None for key in ("representative_corpus", "artifact_provenance", "complete_environment", "pt_backend",
                                                     "generation", "production_coverage", "release")}}
    try:
        observation = timer.measure(command, str(output), 300, raw_bundle=output / "raw", raw_limit_bytes=1024 * 1024)
        report["observation"] = observation
        _save(output / "observation.json", observation)
        report["status"] = "incomplete_oracle_check"
        if not finalization._process_ok(observation) or any(observation["raw_capture"][key]["truncated"] for key in ("stdout", "stderr")):
            raise ValueError("oracle process, cleanup or retained output was incomplete")
        checks, _ = finalization.read_json(output / "checks.json")
        report["checks"] = checks
        if (type(checks.get("planned")) is not int or checks["planned"] <= 0 or checks.get("ran") != checks["planned"]
                or type(checks.get("outcomes")) is not list or len(checks["outcomes"]) != checks["planned"]
                or len({row["test"] for row in checks["outcomes"]}) != checks["planned"]):
            raise ValueError("oracle test ledger is incomplete")
        if _source(source_root) != source or _source(frozen) != source:
            raise ValueError("oracle original or frozen source changed during the checks")
        all_passed = (checks["successful"] is True and checks["status_counts"] == {"passed": checks["planned"]}
                      and all(row["status"] == "passed" for row in checks["outcomes"]) and observation["returncode"] == 0)
        report["status"] = "passed_development_oracle_checks" if all_passed else "failed_or_unsupported_development_oracle_checks"
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    _save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--_frozen-child", nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._frozen_child is not None:
        return _child(*map(Path, args._frozen_child))
    if args.output is None:
        parser.error("--output is required")
    try:
        report = check(args.output, execute=args.execute)
    except (OSError, ValueError, metadata.PackageNotFoundError) as exc:
        parser.exit(2, f"oracle-check: {exc}\n")
    print(json.dumps({"status": report["status"], "checks": None if report["checks"] is None else report["checks"]["status_counts"],
                      "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "passed_development_oracle_checks")


if __name__ == "__main__":
    raise SystemExit(main())
