"""Two isolated Flask baseline builds/runs at a pinned revision; no PT qualification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
REVISION = "49943b5a94413a530761350f04e896f76e8d620e"
TREE = "6751ab7eae06e6f97a157860470fd588920a734b"
SOURCE_DATE_EPOCH = "1793372720"
LOCKS = {
    "flask-49943b5-build.requirements.in": "c41c83e3e952b6380a3002f3beef7c9127d83d8a80c8cc360ef977d207b71c9c",
    "flask-49943b5-build.requirements.txt": "15474c26171aabab9fe8ef5770ec96e46a21a5a391b84729633c87ddb0b40867",
    "flask-49943b5-pytest842.requirements.in": "f0cf760033c1e7fcb8dd2b17e5d26c152843cfc97f98a756685079041eff97b4",
    "flask-49943b5-pytest842.requirements.txt": "81b367ecd058e0e67efd4aa093db1a59e25da92908fb3a0356e774cdeaf2df91",
}


def _materializer():
    spec = importlib.util.spec_from_file_location("flask_assessment_process_tools", HERE.parent / "serial_core/materialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE, timeout=20).decode().strip()


def _junit(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unexpected entity/DTD in reference JUnit")
    rows = []
    for item in ET.fromstring(raw).findall(".//testcase"):
        children = [child for child in item if child.tag in ("error", "failure", "skipped")]
        if len(children) > 1:
            raise ValueError("ambiguous reference JUnit outcome")
        rows.append({"classname": item.get("classname", ""), "name": item.get("name", ""),
                     "kind": children[0].tag if children else "passed",
                     "message": children[0].get("message", "") if children else ""})
    return rows


def assess(source, output, *, execute=False, prepare_artifacts=False):
    if execute is not True:
        raise ValueError("--execute is required for isolated builds and the two planned pytest runs")
    if (sys.platform != "linux" or platform.machine() != "x86_64" or sys.implementation.name != "cpython"
            or sys.version_info[:3] != (3, 12, 12) or sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise ValueError("Flask assessment pins Linux x86-64, GIL-enabled CPython 3.12.12")
    source, output = Path(source).resolve(strict=True), Path(os.path.abspath(output))
    if (output.parent.resolve(strict=True).is_relative_to(source) or source.is_relative_to(output)
            or output.parent.resolve(strict=True).is_relative_to(HERE.parents[2])):
        raise ValueError("assessment output must be outside and nonnested with repository/source inputs")
    if (_git(source, "rev-parse", "HEAD") != REVISION or _git(source, "rev-parse", "HEAD^{tree}") != TREE
            or _git(source, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("exact pristine candidate revision/tree required; no source repair or substitution")
    captured = {name: (HERE / name).read_bytes() for name in LOCKS}
    if any(hashlib.sha256(raw).hexdigest() != LOCKS[name] for name, raw in captured.items()):
        raise ValueError("adapted runtime/build lock or declaration differs from its frozen bytes")
    tools = _materializer()
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("an explicitly installed uv is required")
    cache = subprocess.check_output([uv, "--no-config", "cache", "dir"], timeout=10).decode().strip()
    if not Path(cache).is_absolute() or "\n" in cache:
        raise ValueError("uv cache must be an explicit single absolute path")
    output.mkdir(mode=0o700)
    tools._freeze(output / "frozen", captured)
    tools._freeze(output / "frozen", {"check_flask_49943b5.py": Path(__file__).read_bytes()})
    for name in ("home", "tmp", "artifacts"):
        (output / name).mkdir(mode=0o700)
    env = {"PATH": os.defpath, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "UV_CACHE_DIR": cache, "UV_NO_CONFIG": "1", "UV_LINK_MODE": "copy", "UV_PYTHON_DOWNLOADS": "never",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}
    rows = [{"environment": index, "status": "not_run_prior_failure", "observation": None, "junit": None} for index in (1, 2)]
    report = {"kind": "flask_pytest_only_two_materializations", "revision": REVISION, "tree": TREE, "status": "aborted",
              "profile": "adapted-pytest-8.4.2-not-upstream-uv-lock", "network_artifact_preparation_requested": bool(prepare_artifacts),
              "planned_runs": rows, "builds": [], "runtime_environments": [], "errors": [], "locks": LOCKS,
              "confirmatory_eligible": False, "qualification": {key: None for key in ("representative_corpus", "artifact_provenance",
                  "complete_environment", "reset_equivalence", "semantic_oracle", "pt_backend", "generation", "release")}}

    def command(name, argv, cwd=output, environment=env):
        return tools._command(output, name, argv, cwd, environment)

    def require_zero(name, argv, **kwargs):
        observation, raw = command(name, argv, **kwargs)
        if observation["returncode"] != 0:
            raise ValueError(f"{name} failed; retained raw output is authoritative, no fallback/retry")
        return raw

    try:
        archive = output / "source.tar"
        require_zero("archive", ["git", "-C", str(source), "archive", "--format=tar", "--output=" + str(archive), REVISION])
        report["source_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        for index in (1, 2):
            build_source = output / f"build-source-{index}"
            build_source.mkdir(mode=0o700)
            with tarfile.open(archive) as tar:
                tar.extractall(build_source, filter="data")
            original = tools.tree(build_source)
            builder = output / f"builder-{index}"
            require_zero(f"builder-{index}", [uv, "--no-config", "venv", "--offline", "--python", str(Path(sys.executable).resolve()), str(builder)])
            require_zero(f"build-deps-{index}", [uv, "--no-config", "pip", "sync", *([] if prepare_artifacts and index == 1 else ["--offline"]),
                                                 "--only-binary", ":all:", "--require-hashes", "--python", str(builder / "bin/python"),
                                                 str(output / "frozen/flask-49943b5-build.requirements.txt")])
            wheel_dir = output / f"wheels-{index}"
            wheel_dir.mkdir(mode=0o700)
            require_zero(f"wheel-{index}", [uv, "--no-config", "build", "--offline", "--no-build-isolation", "--wheel", "--python", str(builder / "bin/python"),
                                            "--out-dir", str(wheel_dir), str(build_source)])
            wheels = list(wheel_dir.glob("*.whl"))
            if len(wheels) != 1 or tools.tree(build_source) != original:
                raise ValueError("build changed candidate source inputs or did not produce exactly one wheel")
            raw = tools._read(wheels[0])[1]
            report["builds"].append({"build": index, "wheel_name": wheels[0].name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            if index == 1:
                tools._freeze(output / "artifacts", {wheels[0].name: raw})
            elif report["builds"][0]["sha256"] != report["builds"][1]["sha256"]:
                raise ValueError("two separate local builds differed; no path or archive normalization")
        canonical_wheel = output / "artifacts" / report["builds"][0]["wheel_name"]
        for row in rows:
            index = row["environment"]
            row["status"] = "preparation_failed"
            venv = output / f"environment-{index}"
            python = venv / "bin/python"
            require_zero(f"venv-{index}", [uv, "--no-config", "venv", "--offline", "--python", str(Path(sys.executable).resolve()), str(venv)])
            require_zero(f"runtime-deps-{index}", [uv, "--no-config", "pip", "sync", *([] if prepare_artifacts and index == 1 else ["--offline"]),
                                                   "--only-binary", ":all:", "--require-hashes", "--python", str(python),
                                                   str(output / "frozen/flask-49943b5-pytest842.requirements.txt")])
            require_zero(f"install-flask-{index}", [uv, "--no-config", "pip", "install", "--offline", "--no-index", "--no-deps", "--python", str(python), str(canonical_wheel)])
            code = ("import importlib.metadata as m,json,sys; print(json.dumps({'python':list(sys.version_info[:3]),'pytest':m.version('pytest'),"
                    "'flask':m.version('flask'),'distributions':sorted((d.metadata['Name'],d.version) for d in m.distributions()),"
                    "'pytest11':sorted((e.name,e.value) for e in m.entry_points(group='pytest11'))}))")
            runtime = json.loads(require_zero(f"runtime-{index}", [str(python), "-c", code])["stdout"])
            if runtime["python"] != [3, 12, 12] or runtime["pytest"] != "8.4.2" or runtime["flask"] != "3.2.0.dev0" or runtime["pytest11"]:
                raise ValueError("actual runtime, Flask version or autoload entries differ from the explicit assessment profile")
            site = venv / "lib/python3.12/site-packages"
            before = tools.tree(site)
            report["runtime_environments"].append({"environment": index, "runtime": runtime, "before": before, "after": None,
                                                     "interpreter_sha256": hashlib.sha256(python.read_bytes()).hexdigest()})
            work = output / f"work-{index}"
            work.mkdir(mode=0o700)
            with tarfile.open(archive) as tar:
                tar.extractall(work, filter="data")
            source_inputs = tools.tree(work)
            row["status"] = "unknown_execution_return"
            observation, raw = command(f"pytest-{index}", [str(python), "-m", "pytest", "-q", "--junitxml=" + str(output / f"junit-{index}.xml"),
                                                           "--basetemp=" + str(output / f"pytest-tmp-{index}")], cwd=work,
                                       environment={**env, "PATH": str(venv / "bin") + os.pathsep + os.defpath})
            row.update(status="returned_reference_unqualified", observation=observation)
            row["junit"] = _junit(tools._read(output / f"junit-{index}.xml")[1])
            for item in source_inputs:
                if tools._read(work / item["path"])[0]["sha256"] != item["sha256"]:
                    raise ValueError("tracked source input changed during reference tests")
            after = tools.tree(site)
            report["runtime_environments"][-1]["after"] = after
            if after != before:
                raise ValueError("installed site-packages files changed during reference execution")
        first, second = report["runtime_environments"]
        comparable = lambda value: [item for item in value["before"] if not item["path"].endswith(".dist-info/RECORD")]
        if (comparable(first) != comparable(second) or first["runtime"] != second["runtime"]
                or first["interpreter_sha256"] != second["interpreter_sha256"]):
            raise ValueError("two clean installations differ outside the explicit RECORD exclusion")
        report["compared_installed_files"] = len(comparable(first))
        report["repeated_reference_outcomes_match"] = (rows[0]["junit"] == rows[1]["junit"] and rows[0]["observation"]["returncode"] == rows[1]["observation"]["returncode"])
        report["status"] = "reproduced_pytest_only_observations_unqualified" if report["repeated_reference_outcomes_match"] else "reference_outcomes_differ_unqualified"
        if any((HERE / name).read_bytes() != raw or tools._read(output / "frozen" / name)[1] != raw for name, raw in captured.items()):
            raise ValueError("original or frozen requirements changed during the assessment")
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt, ET.ParseError, tarfile.TarError) as exc:
        report["status"] = "aborted"
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    tools._save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prepare-artifacts", action="store_true", help="explicitly allow wheel downloads into uv's cache during first-environment setup only")
    args = parser.parse_args()
    try:
        report = assess(args.source, args.output, execute=args.execute, prepare_artifacts=args.prepare_artifacts)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"flask-assessment: {exc}\n")
    print(json.dumps({"status": report["status"], "planned_runs": [{"environment": row["environment"], "status": row["status"],
                      "exit": None if row["observation"] is None else row["observation"]["returncode"],
                      "outcomes": None if row["junit"] is None else {kind: sum(item["kind"] == kind for item in row["junit"]) for kind in sorted({item["kind"] for item in row["junit"]})}}
                     for row in report["planned_runs"]], "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "reproduced_pytest_only_observations_unqualified")


if __name__ == "__main__":
    raise SystemExit(main())
