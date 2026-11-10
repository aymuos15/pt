"""Explicit async/property/SQLite correctness references, not PT backend qualification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VERSIONS = {"hypothesis": "6.170.15", "iniconfig": "2.3.1", "packaging": "26.3", "pluggy": "1.7.0", "pygments": "2.21.0",
            "pytest": "8.4.2", "pytest-asyncio": "1.4.1.post1", "sortedcontainers": "2.4.0", "typing-extensions": "4.16.0"}
PLUGINS = [["asyncio", "pytest_asyncio.plugin"], ["hypothesispytest", "_hypothesis_pytestplugin"]]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sources(tools):
    source = {}
    for name in ("profile.json", "pyproject.toml", "uv.lock", "check_references.py"):
        source[name] = tools._read(HERE / name)[1]
    declaration = tools.files.parse_json(source["profile.json"])
    if (set(declaration) != {"schema_version", "profile", "status", "allocation", "cases", "controls"}
            or type(declaration.get("schema_version")) is not int or declaration["schema_version"] != 1
            or declaration.get("profile") != "linux-cpython31212-pytest842-serial-ecosystem-v1"
            or declaration.get("status") != "development_training_mechanisms_unqualified"
            or declaration.get("allocation") != "training_only_before_optimization"
            or [row["id"] for row in declaration["cases"]] != ["async_cases", "property_cases", "database_cases"]
            or len(declaration["controls"]) != 3):
        raise ValueError("unsupported ecosystem mechanism declaration")
    for case in declaration["cases"]:
        if (set(case) != {"id", "exit", "occurrences", "phases", "junit", "expected_events"}
                or type(case["exit"]) is not int or not 0 <= case["exit"] <= 5
                or type(case["occurrences"]) is not int or not 1 <= case["occurrences"] <= 256
                or type(case["phases"]) is not int or not 1 <= case["phases"] <= 768
                or type(case["junit"]) is not list or len(case["junit"]) != case["occurrences"]
                or case["expected_events"] is not None and (type(case["expected_events"]) is not list
                    or any(type(value) is not str for value in case["expected_events"]))):
            raise ValueError("invalid ecosystem request/work declaration")
        for item in case["junit"]:
            if (type(item) is not dict or set(item) != {"name", "kind", "marker"} or type(item["name"]) is not str
                    or type(item["marker"]) is not str or item["kind"] not in ("passed", "failure", "error", "skipped")):
                raise ValueError("invalid ecosystem JUnit expectation")
    if declaration["controls"] != [{"case": "async_cases", "target": "test_async.py::test_awaited_body", "fault": "skip_call"},
                                    {"case": "property_cases", "target": "test_properties.py::test_boolean_domain", "fault": "skip_call"},
                                    {"case": "database_cases", "target": "test_database.py::test_write", "fault": "skip_teardown"}]:
        raise ValueError("unsupported ecosystem fault-control plan")
    lock = tomllib.loads(source["uv.lock"].decode())
    versions = {row["name"]: row["version"] for row in lock["package"] if row.get("source", {}).get("registry")}
    if lock["requires-python"] != "==3.12.12" or any(versions.get(name) != version for name, version in VERSIONS.items()):
        raise ValueError("ecosystem lock differs from its exact development versions")
    for row in tools.tree(HERE / "fixtures"):
        name = "fixtures/" + row["path"]
        if Path(row["path"]).parts[0] not in {case["id"] for case in declaration["cases"]}:
            raise ValueError("unlisted ecosystem fixture directory")
        source[name] = tools._read(HERE / name)[1]
    return declaration, source


def _property_effects(events):
    expected = {"boolean False", "boolean True", "pair False False", "pair False True", "pair True False", "pair True True"}
    if events is None or events[:1] != ["property import"] or len(events) != 7 or set(events[1:]) != expected:
        raise ValueError("Hypothesis did not execute each declared finite-domain example exactly once")


def check(prepared, output, *, execute=False, prepare_artifacts=False):
    if execute is not True:
        raise ValueError("--execute is required for two new environments and 24 planned pytest requests")
    prepared = Path(prepared).resolve(strict=True)
    output = Path(os.path.abspath(output))
    output = output.parent.resolve(strict=True) / output.name
    if output.is_relative_to(ROOT) or output.is_relative_to(prepared) or prepared.is_relative_to(output):
        raise ValueError("ecosystem evidence must be separate from repository/private interpreter inputs")
    tools = _module("ecosystem_outer_process_tools", HERE.parent / "serial_core/materialize.py")
    preparation = _module("ecosystem_private_interpreter_tools", HERE.parent / "interpreter/materialize.py")
    bases = _module("ecosystem_private_base_checks", HERE.parent / "interpreter/check_serial_core.py")
    pin, manifest, before = bases.verify_preparation(prepared, preparation, tools)
    declaration, source = load_sources(tools)
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("an explicitly installed uv and locked artifacts are required")
    cache = subprocess.check_output([uv, "--no-config", "cache", "dir"], text=True, timeout=10).strip()
    if not Path(cache).is_absolute() or "\n" in cache:
        raise ValueError("uv cache must be one explicit absolute path")
    output.mkdir(mode=0o700)
    tools._freeze(output / "frozen", source)
    observer_sources = {name: tools._read(ROOT / "tests/conformance" / name)[1] for name in
                        ("pt_reference_observer.py", "trace_oracle.py", "broken_reference_runner.py", "artifact_oracle.py")}
    tools._freeze(output / "oracle", observer_sources)
    oracle = _module("frozen_ecosystem_trace_reader", output / "oracle/trace_oracle.py")
    artifacts = _module("frozen_ecosystem_artifact_reader", output / "oracle/artifact_oracle.py")
    for name in ("home", "tmp"):
        (output / name).mkdir(mode=0o700)
    env = {"PATH": os.defpath, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "UV_CACHE_DIR": cache, "UV_NO_CONFIG": "1", "UV_LINK_MODE": "copy", "UV_PYTHON_DOWNLOADS": "never",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0"}
    rows = [{"id": f"env-{index}-{case['id']}-{layer}", "environment": index, "case": case["id"], "layer": layer,
             "status": "not_run_prior_failure", "observation": None} for index in (1, 2) for case in declaration["cases"]
            for layer in ("plain", "reference-1", "reference-2")]
    rows += [{"id": f"control-{index}-{arm}", "environment": 1, "case": control["case"], "layer": arm,
              "status": "not_run_prior_failure", "observation": None} for index, control in enumerate(declaration["controls"], 1)
             for arm in ("reference", "broken")]
    report = {"kind": "serial_ecosystem_reference_controls", "status": "aborted", "planned_requests": rows, "comparisons": [],
              "environments": [], "base_before": before, "base_after": None, "errors": [], "confirmatory_eligible": False,
              "network_preparation_requested": bool(prepare_artifacts),
              "sources": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(source.items())},
              "qualification": {key: None for key in ("representative_corpus", "artifact_provenance", "complete_environment", "reset",
                                                      "production_backend", "ecosystem_support", "generation", "release")},
              "limitations": ["training mechanisms, not representative/holdout repositories, backend parity or timing samples",
                              "property-domain coverage is checked separately; exact raw effect order is still compared without sorting",
                              "database fixture is owned local SQLite state, not a general external-service reset adapter",
                              "prefix/site/source end checks are not immutable snapshots or host-library identity"]}

    def command(name, argv, cwd=output, environment=env):
        return tools._command(output, name, argv, cwd, environment)

    def setup(name, argv, **kwargs):
        observation, raw = command(name, argv, **kwargs)
        if observation["returncode"] != 0:
            raise ValueError(name + " failed; retained result is not retried or repaired")
        return raw

    def request(row, *, target=None, fault=None):
        case = next(case for case in declaration["cases"] if case["id"] == row["case"])
        work = output / "work"
        row["status"] = "preparation_failed"
        work.mkdir(mode=0o700)
        copied = {name.removeprefix("fixtures/" + case["id"] + "/"): raw for name, raw in source.items()
                  if name.startswith("fixtures/" + case["id"] + "/")}
        copied["pyproject.toml"] = source["pyproject.toml"]
        tools._freeze(work, copied)
        events, trace = work / "events.txt", output / (row["id"] + ".jsonl")
        venv = output / f"environment-{row['environment']}"
        argv = [str(venv / "bin/python"), "-m", "pytest", "-q", "--junitxml=pytest-junit.xml", "--basetemp=pytest-tmp"]
        instrumented = row["layer"] != "plain"
        if instrumented:
            argv += ["-p", "pt_reference_observer", "--pt-reference-trace=" + str(trace)]
        control_args = ["-p", "broken_reference_runner", "--pt-broken-runner=" + fault] if fault else []
        argv += control_args
        argv += [target] if target is not None else ["."]
        row["status"] = "unknown_execution_return"
        observation, raw = command(row["id"], argv, work, {**env, "PATH": str(venv / "bin") + os.pathsep + os.defpath,
            "PYTHONPATH": str(output / "oracle"), "PT_CORE_EVENTS": str(events), "HYPOTHESIS_STORAGE_DIRECTORY": str(work / ".hypothesis")})
        row.update(status="returned_unqualified", observation=observation)
        row["effects"] = tools._read(events)[1].decode("utf-8").splitlines() if events.exists() else None
        if target is None:
            if observation["returncode"] != case["exit"]:
                raise ValueError("actual ecosystem backend exit differs from its declared adverse outcome")
            row["junit"] = tools.normalize_junit(tools._read(work / "pytest-junit.xml")[1], case["junit"])
            if row["junit"] != case["junit"]:
                raise ValueError("ecosystem JUnit occurrence/adverse markers differ from their declaration")
            if case["expected_events"] is not None and row["effects"] != case["expected_events"]:
                raise ValueError("actual async/database effect sequence differs from its declaration")
            if case["id"] == "property_cases":
                _property_effects(row["effects"])
        elif observation["returncode"] != 0:
            raise ValueError("explicit equal-phase fault control did not retain its expected zero backend exit")
        if instrumented:
            checked = oracle.read_trace(trace, observation["returncode"])
            row["trace_sha256"] = checked["trace_sha256"]
            row["occurrences"] = len(checked["normalized"]["completed"])
            row["phases"] = len(checked["normalized"]["phases"])
            if row["occurrences"] != (case["occurrences"] if target is None else 1) or row["phases"] != (case["phases"] if target is None else 3):
                raise ValueError("ecosystem reference occurrence/phase accounting differs from its declaration")
        if case["id"] == "database_cases":
            try:
                row["cleanup"] = artifacts.check_artifacts(work, [], absent=["database.lease"])
            except artifacts.ArtifactError as exc:
                row["cleanup"] = {"status": "cleanup_mismatch", "error": str(exc)}
                if fault != "skip_teardown":
                    raise
            if fault == "skip_teardown" and row["cleanup"]["status"] != "cleanup_mismatch":
                raise ValueError("independent artifact oracle missed the omitted database cleanup")
        if any(tools._read(work / name)[1] != raw for name, raw in copied.items()):
            raise ValueError("ecosystem tracked source changed during a request")
        row["status"] = "matched_declared_development_observation" if fault is None else "returned_deliberately_broken_control"
        work.rename(output / ("retained-work-" + row["id"]))
        return {"path": trace, "exit": observation["returncode"], "effects": row["effects"], "control_args": control_args}

    try:
        for index in (1, 2):
            venv = output / f"environment-{index}"
            setup(f"venv-{index}", [uv, "--no-config", "venv", "--offline", "--python", str(prepared / f"prefix-{index}" / pin["executable"]["path"]), str(venv)])
            setup(f"install-{index}", [uv, "--no-config", "sync", *([] if prepare_artifacts and index == 1 else ["--offline"]),
                "--locked", "--no-build", "--active", "--project", str(output / "frozen")], environment={**env, "VIRTUAL_ENV": str(venv)})
            code = "import importlib.metadata as m,json,sys; print(json.dumps({'python':list(sys.version_info[:3]),'packages':sorted((d.metadata['Name'].lower().replace('_','-'),d.version) for d in m.distributions()),'plugins':sorted((e.name,e.value) for e in m.entry_points(group='pytest11'))}))"
            runtime = tools.files.parse_json(setup(f"runtime-{index}", [str(venv / "bin/python"), "-c", code])["stdout"])
            if runtime != {"python": [3, 12, 12], "packages": [list(row) for row in sorted(VERSIONS.items())], "plugins": PLUGINS}:
                raise ValueError("actual ecosystem versions/plugin autoload entries differ from the explicit locked profile")
            site = venv / "lib/python3.12/site-packages"
            installed = tools.tree(site)
            entry = {"environment": index, "runtime": runtime, "before": installed, "after": None}
            report["environments"].append(entry)
            for case in declaration["cases"]:
                requests = [row for row in rows if row["environment"] == index and row["case"] == case["id"] and row["layer"] in ("plain", "reference-1", "reference-2")]
                observed = [request(row) for row in requests]
                if any(row["junit"] != requests[0]["junit"] or row["effects"] != requests[0]["effects"] for row in requests[1:]):
                    raise ValueError("observer changed the declared uninstrumented JUnit/effect baseline")
                comparison = oracle.compare_traces(observed[1]["path"], observed[2]["path"],
                    baseline_exit=observed[1]["exit"], candidate_exit=observed[2]["exit"],
                    baseline_effects=observed[1]["effects"], candidate_effects=observed[2]["effects"])
                report["comparisons"].append({"environment": index, "case": case["id"], "comparison": comparison})
                if comparison["status"] != "matched_instrumented_trace_contract":
                    report["status"] = "baseline_uncertain"
                    raise ValueError("repeated ecosystem references are unstable or inconsistent")
            entry["after"] = tools.tree(site)
            if entry["after"] != installed:
                raise ValueError("ecosystem installed files changed during reference execution")
        for index, control in enumerate(declaration["controls"], 1):
            left = request(next(row for row in rows if row["id"] == f"control-{index}-reference"), target=control["target"])
            right = request(next(row for row in rows if row["id"] == f"control-{index}-broken"), target=control["target"], fault=control["fault"])
            comparison = oracle.compare_traces(left["path"], right["path"], baseline_exit=left["exit"], candidate_exit=right["exit"],
                baseline_effects=left["effects"], candidate_effects=right["effects"], candidate_control_args=right["control_args"])
            report["comparisons"].append({"control": control, "comparison": comparison})
            if comparison["status"] != "mismatch" or comparison["differences"] != ["declared_effect_observations"]:
                raise ValueError("equal-phase broken ecosystem work was not detected solely by independent effects")
        for index, entry in enumerate(report["environments"], 1):
            if tools.tree(output / f"environment-{index}/lib/python3.12/site-packages") != entry["before"]:
                raise ValueError("ecosystem installed files changed during fault controls")
        comparable = lambda entry: [row for row in entry["before"] if not row["path"].endswith(".dist-info/RECORD")]
        if comparable(report["environments"][0]) != comparable(report["environments"][1]):
            raise ValueError("clean ecosystem installations differ outside the explicit RECORD exclusion")
        report["compared_installed_files"] = len(comparable(report["environments"][0]))
        report["base_after"] = [preparation.verify_prefix(prepared / f"prefix-{index}", manifest) for index in (1, 2)]
        if any(row["status"] != "matched_exact_prefix" for row in report["base_after"]):
            raise ValueError("pinned base prefix changed during ecosystem preparation/execution")
        if load_sources(tools) != (declaration, source) or any(tools._read(output / "frozen" / name)[1] != raw for name, raw in source.items()):
            raise ValueError("original/frozen ecosystem inputs changed")
        if any(tools._read(output / "oracle" / name)[1] != raw or tools._read(ROOT / "tests/conformance" / name)[1] != raw for name, raw in observer_sources.items()):
            raise ValueError("reference observer/comparator inputs changed")
        report["status"] = "matched_finite_ecosystem_references_and_detected_controls_unqualified"
    except (OSError, EOFError, ValueError, RuntimeError, ImportError, KeyboardInterrupt, tarfile.TarError) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    tools._save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prepare-artifacts", action="store_true", help="explicitly allow first-environment locked wheel downloads only")
    args = parser.parse_args()
    try:
        report = check(args.prepared, args.output, execute=args.execute, prepare_artifacts=args.prepare_artifacts)
    except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
        parser.exit(2, f"ecosystem-references: {exc}\n")
    print(json.dumps({"status": report["status"], "requests": {status: sum(row["status"] == status for row in report["planned_requests"])
                      for status in sorted({row["status"] for row in report["planned_requests"]})}, "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "matched_finite_ecosystem_references_and_detected_controls_unqualified")


if __name__ == "__main__":
    raise SystemExit(main())
