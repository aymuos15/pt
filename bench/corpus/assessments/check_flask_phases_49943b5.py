"""Four fresh instrumented Flask references in existing isolated environments."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tests/conformance"))
from trace_oracle import compare_traces, read_trace
sys.path.pop(0)
REVISION = "49943b5a94413a530761350f04e896f76e8d620e"
ARCHIVE_SHA256 = "45107dac10ad06be68dded8df209003460603461b8f2ca769f2e69b6c28ee678"


def check(materialization, output, *, execute=False):
    if execute is not True:
        raise ValueError("--execute is required for four separately planned real-pytest references")
    materialization, output = Path(materialization).resolve(strict=True), Path(os.path.abspath(output))
    if (output.parent.resolve(strict=True).is_relative_to(ROOT) or output.parent.resolve(strict=True).is_relative_to(materialization)
            or materialization.is_relative_to(output)):
        raise ValueError("phase evidence must be separate from repository/materialization inputs")
    spec = importlib.util.spec_from_file_location("flask_reference_process_tools", HERE.parent / "serial_core/materialize.py")
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    original, _ = tools.files.read_json(materialization / "result.json")
    archive = materialization / "source.tar"
    if (original.get("status") != "reproduced_pytest_only_observations_unqualified" or original.get("revision") != REVISION
            or tools._read(archive)[0]["sha256"] != ARCHIVE_SHA256 or original.get("source_archive_sha256") != ARCHIVE_SHA256):
        raise ValueError("the exact completed Flask-only materialization/source archive is required")
    output.mkdir(mode=0o700)
    captured = {name: (ROOT / "tests/conformance" / name).read_bytes() for name in ("pt_reference_observer.py", "trace_oracle.py")}
    captured["check_flask_phases_49943b5.py"] = Path(__file__).read_bytes()
    tools._freeze(output / "observer", captured)
    for name in ("home", "tmp"):
        (output / name).mkdir(mode=0o700)
    env = {"PATH": os.defpath, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(output / "observer")}
    rows = [{"environment": index, "repeat": repeat, "status": "not_run_prior_failure", "observation": None}
            for index in (1, 2) for repeat in (1, 2)]
    report = {"kind": "flask_instrumented_reference_stability", "status": "aborted", "planned_references": rows,
              "comparisons": [], "errors": [], "confirmatory_eligible": False, "profile": "serial-repository-v1",
              "source_archive_sha256": ARCHIVE_SHA256, "sources": {name: hashlib.sha256(raw).hexdigest() for name, raw in captured.items()},
              "limitations": ["real-pytest reference only, not a PT candidate, shipping timing or test-body effect proof",
                              "same literal cwd is reset by archiving each owned work copy and creating a fresh copy; no retries or recovery",
                              "captured text, warning reasons and application paths are not stripped to force reference stability",
                              "installed-file observations do not establish complete environment or immutable-generation assurance"],
              "qualification": {key: None for key in ("semantic_support", "body_effects", "environment", "generation", "pt_backend", "release")}}
    try:
        for index in (1, 2):
            site = materialization / f"environment-{index}/lib/python3.12/site-packages"
            installed = tools.tree(site)
            if installed != original["runtime_environments"][index - 1]["after"]:
                raise ValueError("installed environment changed since the retained reference materialization")
            python = materialization / f"environment-{index}/bin/python"
            if hashlib.sha256(python.read_bytes()).hexdigest() != original["runtime_environments"][index - 1]["interpreter_sha256"]:
                raise ValueError("selected interpreter changed since the original materialization")
            for repeat in (1, 2):
                row = next(value for value in rows if value["environment"] == index and value["repeat"] == repeat)
                work = output / "work"
                work.mkdir(mode=0o700)
                with tarfile.open(archive) as tar:
                    tar.extractall(work, filter="data")
                inputs = tools.tree(work)
                trace = output / f"trace-{index}-{repeat}.jsonl"
                row["status"] = "unknown_execution_return"
                argv = [str(python), "-m", "pytest", "-q", "-p", "pt_reference_observer", "--pt-reference-profile=serial-repository-v1",
                        "--pt-reference-trace=" + str(trace), "--junitxml=pt-junit.xml", "--basetemp=pt-tmp"]
                observation, raw = tools._command(output, f"pytest-{index}-{repeat}", argv, work,
                                                 {**env, "PATH": str(python.parent) + os.pathsep + os.defpath})
                row.update(status="returned_unqualified", observation=observation)
                checked = read_trace(trace, observation["returncode"])
                row.update(trace_sha256=checked["trace_sha256"], selected=len(checked["normalized"]["selected"]),
                           completed=len(checked["normalized"]["completed"]), phases=len(checked["normalized"]["phases"]))
                if observation["returncode"] != 0 or row["selected"] != 494 or row["completed"] != 494 or row["phases"] != 1482:
                    raise ValueError("instrumented reference differs from the complete expected 494-occurrence / 1482-phase profile")
                if (any(tools._read(work / item["path"])[0]["sha256"] != item["sha256"] for item in inputs) or tools.tree(site) != installed):
                    raise ValueError("source or installed environment changed during the reference request")
                row["status"] = "matched_expected_reference_accounting_unqualified"
                # Preserve every work/output copy without deleting or overwriting
                # it, while keeping exactly the same literal cwd for the next run.
                work.rename(output / f"retained-work-{index}-{repeat}")
            comparison = compare_traces(output / f"trace-{index}-1.jsonl", output / f"trace-{index}-2.jsonl", baseline_exit=0, candidate_exit=0)
            comparison.update(environment=index, stability="baseline_uncertain" if comparison["status"] == "mismatch" else "matched_repeated_reference_contract")
            report["comparisons"].append(comparison)
        if any(tools._read(output / "observer" / name)[1] != raw for name, raw in captured.items()):
            raise ValueError("frozen reference instrumentation changed during the checks")
        if any((ROOT / "tests/conformance" / name).read_bytes() != captured[name] for name in ("pt_reference_observer.py", "trace_oracle.py")):
            raise ValueError("original observer/reader changed during the reference checks")
        report["status"] = "baseline_uncertain" if any(value["status"] == "mismatch" for value in report["comparisons"]) else "matched_four_instrumented_references_unqualified"
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt, tarfile.TarError) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    tools._save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        report = check(args.materialization, args.output, execute=args.execute)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"flask-phase-reference: {exc}\n")
    print(json.dumps({"status": report["status"], "references": [{key: row.get(key) for key in ("environment", "repeat", "status", "selected", "phases")}
                      for row in report["planned_references"]], "comparisons": [row["stability"] for row in report["comparisons"]],
                      "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "matched_four_instrumented_references_unqualified")


if __name__ == "__main__":
    raise SystemExit(main())
