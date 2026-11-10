"""Materialize the declared serial-core corpus twice, offline; not a semantic oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
HARNESS = HERE.parents[1] / "harness"
sys.path.insert(0, str(HARNESS))
import finalization as files
import pt_bench as timer
import raw_capture  # Load the timer's lazy capture dependency before restoring sys.path.
sys.path.pop(0)

MAX_FILE_BYTES = files.MAX_RECEIPT_BYTES
MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 8192
TIMEOUT = 120
QUALIFICATION = ("representative_corpus", "artifact_provenance", "complete_environment_identity", "semantic_oracle", "pt_backend", "release")


def _read(path, limit=MAX_FILE_BYTES):
    return files.inspect_file(path.parent, path.name, limit=limit, retain=True)


def tree(directory):
    """Include unlisted regular files too; never follow a symlink or trim an inventory."""
    result, total = [], 0

    def walk(root, prefix="", depth=0):
        nonlocal total
        if depth > 20:
            raise ValueError("serial-core tree exceeds depth limit")
        with os.scandir(root) as entries:
            for entry in sorted(entries, key=lambda entry: entry.name):
                name = prefix + entry.name
                if entry.is_dir(follow_symlinks=False):
                    walk(root / entry.name, name + "/", depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    metadata, _ = _read(root / entry.name)
                    total += metadata["bytes"]
                    if len(result) >= MAX_TREE_FILES or total > MAX_TREE_BYTES:
                        raise ValueError("serial-core tree exceeds aggregate file/byte limit")
                    result.append({"path": name, "bytes": metadata["bytes"], "sha256": metadata["sha256"]})
                else:
                    raise ValueError("serial-core tree contains nonregular or linked paths")

    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)
    walk(directory)
    return result


def load_profile(root=HERE):
    data, manifest_metadata = files.read_json(root / "corpus.json")
    expected_keys = {"schema_version", "profile", "status", "allocation", "pyproject_sha256", "uv_lock_sha256", "files", "cases"}
    if (set(data) != expected_keys or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["profile"] != "linux-cpython-3.12.12-pytest-8.4.2-serial-core-v1"
            or data["status"] != "development_mechanism_corpus" or data["allocation"] != "training_only_before_optimization"):
        raise ValueError("unsupported serial-core profile declaration")
    current, raw_manifest = _read(root / "corpus.json")
    if current != manifest_metadata:
        raise ValueError("serial-core manifest changed during validation")
    captured = {"corpus.json": raw_manifest}
    for name, key in (("pyproject.toml", "pyproject_sha256"), ("uv.lock", "uv_lock_sha256")):
        metadata, raw = _read(root / name)
        if metadata["sha256"] != data[key]:
            raise ValueError("serial-core environment pin differs from its declared bytes")
        captured[name] = raw
    lock = tomllib.loads(captured["uv.lock"].decode())
    packages = {item["name"]: item["version"] for item in lock["package"] if item["source"].get("registry")}
    if packages.get("pytest") != "8.4.2" or lock["requires-python"] != "==3.12.12":
        raise ValueError("serial-core exact Python/pytest lock differs")
    if not isinstance(data["files"], list) or not 1 <= len(data["files"]) <= 128:
        raise ValueError("serial-core requires a bounded explicit file inventory")
    paths = []
    for item in data["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("invalid serial-core source descriptor")
        path = files.relative_path(item["path"])
        if (not path.startswith("fixtures/") or not isinstance(item["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("invalid serial-core source path/digest")
        metadata, raw = _read(root / path)
        if metadata["sha256"] != item["sha256"]:
            raise ValueError("serial-core source bytes differ from declared hash")
        captured[path] = raw
        paths.append(path)
    if paths != sorted(set(paths)) or ["fixtures/" + item["path"] for item in tree(root / "fixtures")] != paths:
        raise ValueError("serial-core source inventory omits, duplicates or reorders actual files")
    if not isinstance(data["cases"], list) or not 1 <= len(data["cases"]) <= 64:
        raise ValueError("serial-core requires a bounded case list")
    ids = []
    for case in data["cases"]:
        if (not isinstance(case, dict) or set(case) != {"id", "argv", "expected_exit_code", "expected_events", "junit"}
                or not isinstance(case["id"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", case["id"]) is None
                or not any(path.startswith("fixtures/" + case["id"] + "/") for path in paths)
                or type(case["expected_exit_code"]) is not int or not 0 <= case["expected_exit_code"] <= 255
                or not isinstance(case["argv"], list) or not case["argv"] or len(case["argv"]) > 64
                or any(not isinstance(arg, str) or "\0" in arg for arg in case["argv"])
                or case["expected_events"] is not None and (not isinstance(case["expected_events"], list)
                    or not all(isinstance(event, str) for event in case["expected_events"]))
                or not isinstance(case["junit"], list) or len(case["junit"]) > 256):
            raise ValueError("invalid serial-core case declaration")
        for item in case["junit"]:
            if (not isinstance(item, dict) or set(item) != {"name", "kind", "marker"}
                    or not isinstance(item["name"], str) or not isinstance(item["marker"], str)
                    or item["kind"] not in ("passed", "error", "failure", "skipped")):
                raise ValueError("invalid serial-core JUnit expectation")
        ids.append(case["id"])
    if len(ids) != len(set(ids)) or {Path(path).parts[1] for path in paths} != set(ids):
        raise ValueError("serial-core cases must account for every declared fixture directory exactly once")
    return data, captured


def normalize_junit(raw, expected):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations are not allowed in serial-core JUnit")
    cases = ET.fromstring(raw).findall(".//testcase")
    result = []
    for index, case in enumerate(cases):
        outcomes = [child for child in case if child.tag in ("error", "failure", "skipped")]
        if len(outcomes) > 1:
            raise ValueError("ambiguous serial-core JUnit outcome")
        message = outcomes[0].get("message", "") + "\n" + "".join(outcomes[0].itertext()) if outcomes else ""
        marker = expected[index]["marker"] if index < len(expected) else ""
        result.append({"name": case.get("name", ""), "kind": outcomes[0].tag if outcomes else "passed",
                       "marker": marker if marker and marker in message else ""})
    return result


def _save(path, value):
    timer.write_record(str(path), value)


def _freeze(root, captured):
    for name, raw in captured.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(raw)


def _command(root, name, argv, cwd, environment):
    directory = root / "commands" / name
    directory.mkdir(parents=True, mode=0o700)
    actual = ["/usr/bin/env", "-i", *[key + "=" + environment[key] for key in sorted(environment)], *argv]
    result = timer.measure(actual, str(cwd), TIMEOUT, raw_bundle=directory, raw_limit_bytes=1024 * 1024)
    _save(directory / "observation.json", result)
    if not files._process_ok(result) or any(result["raw_capture"][stream]["truncated"] for stream in ("stdout", "stderr")):
        raise ValueError("serial-core command is incomplete, timed out or output was truncated")
    raw = {}
    for stream in ("stdout", "stderr"):
        item = result["raw_capture"][stream]
        metadata, raw[stream] = _read(directory / item["sha256"])
        if metadata["sha256"] != result[stream + "_sha256"] or metadata["bytes"] != result[stream + "_bytes"]:
            raise ValueError("serial-core retained command output differs from its observation")
    return result, raw


def _runtime(python, root, name, environment):
    code = ("import importlib.metadata as m,json,sys,sysconfig; "
            "print(json.dumps({'python':list(sys.version_info[:3]),'pytest':m.version('pytest'),"
            "'distributions':sorted((d.metadata['Name'].lower(),d.version) for d in m.distributions()),"
            "'pytest_plugins':sorted(e.name for e in m.entry_points(group='pytest11')),"
            "'purelib':sysconfig.get_path('purelib')}))")
    result, raw = _command(root, name, [str(python), "-c", code], root, environment)
    if result["returncode"] != 0:
        raise ValueError("serial-core runtime identity command failed")
    value = files.parse_json(raw["stdout"])
    expected = {"iniconfig": "2.3.1", "packaging": "26.3", "pluggy": "1.7.0", "pygments": "2.21.0", "pytest": "8.4.2"}
    if value["python"] != [3, 12, 12] or value["pytest"] != "8.4.2" or value["distributions"] != [list(item) for item in sorted(expected.items())] or value["pytest_plugins"]:
        raise ValueError("serial-core runtime versions, distributions or automatic plugins differ")
    return value


def materialize(output, *, execute=False, profile_root=HERE, interpreters=None):
    if execute is not True:
        raise ValueError("explicit --execute is required for isolated installs and corpus invocations")
    if (sys.platform != "linux" or platform.machine() != "x86_64" or sys.implementation.name != "cpython"
            or sys.version_info[:3] != (3, 12, 12)):
        raise ValueError("serial-core materialization requires Linux x86-64 and CPython 3.12.12")
    profile_root, output = Path(profile_root).resolve(strict=True), Path(os.path.abspath(output))
    if output.parent.resolve(strict=True).is_relative_to(profile_root) or profile_root.is_relative_to(output):
        raise ValueError("serial-core output and source roots must be separate and nonnested")
    data, captured = load_profile(profile_root)
    source_identity = tree(profile_root / "fixtures")
    if interpreters is None:
        interpreters = [Path(sys.executable).resolve()] * 2
    elif (type(interpreters) not in (list, tuple) or len(interpreters) != 2
            or any(not isinstance(path, (str, Path)) or not Path(path).is_absolute() for path in interpreters)):
        raise ValueError("serial-core requires exactly two explicit absolute base-interpreter paths")
    interpreters = [Path(path) for path in interpreters]
    if any(not path.is_file() or not os.access(path, os.X_OK) for path in interpreters):
        raise ValueError("serial-core selected base interpreter is not an executable file")
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("serial-core materialization requires an explicitly installed uv")
    cache = subprocess.run([uv, "--no-config", "cache", "dir"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if not Path(cache).is_absolute() or "\n" in cache:
        raise ValueError("uv cache path is not one absolute path")
    output.mkdir(mode=0o700)
    _freeze(output / "frozen", captured)
    (output / "home").mkdir(mode=0o700)
    (output / "tmp").mkdir(mode=0o700)
    environment = {"PATH": os.defpath, "HOME": str(output / "home"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "TMPDIR": str(output / "tmp"), "UV_CACHE_DIR": cache, "UV_LINK_MODE": "copy", "UV_NO_CONFIG": "1",
                   "UV_PYTHON_DOWNLOADS": "never", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    rows = [{"environment": index, "case": case["id"], "status": "not_run_prior_failure", "invocation_attempted": False, "observation": None}
            for index in (1, 2) for case in data["cases"]]
    report = {"kind": "serial_core_clean_materialization", "status": "aborted", "planned_environments": 2,
              "profile": data, "environments": [], "cases": rows, "errors": [], "confirmatory_eligible": False,
              "qualification": {key: None for key in QUALIFICATION}, "base_interpreters": [str(path) for path in interpreters],
              "limitations": ["test-owned training mechanisms, not a representative or holdout corpus",
                              "JUnit and sentinels are not authoritative phase traces or a semantic oracle",
                              "RECORD files are retained but excluded only from cross-environment byte comparison because entrypoint hashes vary",
                              "interpreter/stdlib/system libraries, artifact provenance and atomic snapshots remain unqualified",
                              "tool/command intervals are setup diagnostics, not shipping latency or independent benchmark samples"]}
    try:
        for index in (1, 2):
            venv = output / f"environment-{index}"
            for name, argv in ((f"venv-{index}", [uv, "--no-config", "venv", "--offline", "--python", str(interpreters[index - 1]), str(venv)]),
                               (f"install-{index}", [uv, "--no-config", "sync", "--offline", "--locked", "--active", "--project", str(output / "frozen")])):
                env = {**environment, **({"VIRTUAL_ENV": str(venv)} if name.startswith("install") else {})}
                result, _ = _command(output, name, argv, output, env)
                if result["returncode"] != 0:
                    raise ValueError("serial-core clean environment creation/install failed; raw output retained")
            python = venv / "bin/python"
            runtime = _runtime(python, output, f"runtime-{index}", environment)
            purelib = Path(runtime["purelib"])
            if purelib != venv / "lib/python3.12/site-packages":
                raise ValueError("serial-core runtime imports outside the declared environment library")
            installed_before = tree(purelib)
            observed = {"environment": index, "runtime": runtime, "interpreter_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
                        "installed_before": installed_before, "installed_after": None}
            report["environments"].append(observed)
            for case in data["cases"]:
                row = next(row for row in rows if row["environment"] == index and row["case"] == case["id"])
                row["status"] = "preparation_failed"
                cwd = output / f"work-{index}" / case["id"]
                sources = {name.removeprefix("fixtures/" + case["id"] + "/"): raw for name, raw in captured.items() if name.startswith("fixtures/" + case["id"] + "/")}
                _freeze(cwd, sources)
                junit, events = output / f"junit-{index}-{case['id']}.xml", output / f"events-{index}-{case['id']}.txt"
                row.update(status="unknown_return", invocation_attempted=None)
                result, raw = _command(output, f"case-{index}-{case['id']}", [str(python), "-m", "pytest", "-q", *case["argv"], "--junitxml=" + str(junit)],
                                       cwd, {**environment, "PT_CORE_EVENTS": str(events)})
                row["observation"] = result
                row["invocation_attempted"] = True
                row["status"] = "mismatch"
                _, junit_raw = _read(junit)
                actual = normalize_junit(junit_raw, case["junit"])
                event_rows = _read(events)[1].decode().splitlines() if events.exists() else None
                row.update(junit=actual, events=event_rows)
                if result["returncode"] != case["expected_exit_code"] or actual != case["junit"] or event_rows != case["expected_events"]:
                    raise ValueError("serial-core invocation disagrees with declared exit, occurrences, adverse marker or sentinel")
                for name, original in sources.items():
                    if _read(cwd / name)[1] != original:
                        raise ValueError("serial-core tracked case input changed during execution")
                row["status"] = "matched_declared_process_and_probe_outcomes"
            observed["installed_after"] = tree(purelib)
            if observed["installed_after"] != installed_before:
                raise ValueError("serial-core complete installed-file inventory changed during execution")
        first, second = report["environments"]
        comparable = lambda entry: not (entry["path"].endswith(".dist-info/RECORD"))
        first_files, second_files = ([entry for entry in environment["installed_before"] if comparable(entry)] for environment in (first, second))
        if first_files != second_files or first["interpreter_sha256"] != second["interpreter_sha256"]:
            raise ValueError("serial-core clean environments differ outside declared RECORD exclusions")
        if load_profile(profile_root) != (data, captured) or tree(profile_root / "fixtures") != source_identity:
            raise ValueError("serial-core profile/source changed during materialization")
        if any(_read(output / "frozen" / name)[1] != raw for name, raw in captured.items()):
            raise ValueError("serial-core frozen inputs changed during materialization")
        report["status"] = "reproduced_declared_mechanism_profile"
        report["compared_installed_files"] = len(first_files)
        report["record_exclusions_per_environment"] = len(first["installed_before"]) - len(first_files)
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt, ET.ParseError, ImportError) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    _save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--base-python", type=Path, nargs=2, metavar=("FIRST", "SECOND"), help="explicit base interpreters, one per new venv; no automatic substitution")
    args = parser.parse_args()
    try:
        report = materialize(args.output, execute=args.execute, interpreters=args.base_python)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"serial-core-materialize: {exc}\n")
    print(json.dumps({"status": report["status"], "planned_environments": 2, "planned_cases": len(report["cases"]),
                      "case_status_counts": {status: sum(row["status"] == status for row in report["cases"]) for status in sorted({row["status"] for row in report["cases"]})},
                      "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "reproduced_declared_mechanism_profile")


if __name__ == "__main__":
    raise SystemExit(main())
