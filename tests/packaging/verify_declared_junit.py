"""Explicit offline development reproduction with read-only interpreter inputs.

Use readonly_interpreter_setup.py to establish the private test-only mount view.
This is not a product launcher, performance campaign or release qualification.
The output is exclusive; failed/unknown commands are never resumed or retried.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    with path.open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix-one", type=Path, required=True)
    parser.add_argument("--prefix-two", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; commands create only new disposable test environments")
    if (args.prefix_one == args.prefix_two or not args.output.is_absolute() or args.output.is_relative_to(ROOT)
            or any(args.output.is_relative_to(path) for path in (args.prefix_one,args.prefix_two))):
        parser.error("distinct prefixes and a new absolute output outside source/interpreter inputs are required")
    for path in (args.prefix_one, args.prefix_two):
        if not path.is_absolute() or not os.statvfs(path).f_flag & os.ST_RDONLY:
            parser.error("explicit interpreter inputs must already be read-only in the private setup view")
    fd = os.open(args.manifest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd,"rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            parser.error("archive-derived manifest must be a regular input")
        raw_manifest = stream.read(4*1024*1024+1)
    if len(raw_manifest) > 4*1024*1024:
        parser.error("archive-derived manifest exceeds the explicit test bound")
    if hashlib.sha256(raw_manifest).hexdigest() != args.manifest_sha256:
        parser.error("explicit archive-manifest identity mismatch; no preparation attempted")
    out = args.output
    out.mkdir(mode=0o700)
    paths = [ROOT / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "support-matrix.toml",
                                    "bench/harness/pyproject.toml", "bench/harness/uv.lock", "bench/corpus/candidates.toml",
                                    "docs/protocol-v0.schema.json", "docs/final-result-v0.schema.json")]
    for base, pattern in (("crates", "*.rs"), ("crates", "Cargo.toml"), ("crates", "*.py"),
                          ("python/pt_bridge", "*.py"), ("python/pt_bridge", "pyproject.toml"),
                          ("tests", "*.py"), ("tests", "*.json"),
                          ("bench/corpus", "*.py"), ("bench/corpus", "*.toml"),
                          ("bench/corpus", "*.json"), ("bench/corpus", "uv.lock")):
        paths.extend((ROOT / base).rglob(pattern))
    paths.extend((ROOT / "bench/harness").glob("*.py"))
    sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    for name in sources:
        target = out / "frozen" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    for name in ("coordinator-cases", "session-cases", "junit-cases", "observer-cases", "wheel"):
        (out / name).mkdir(mode=0o700)
    python = ROOT / "bench/harness/.venv/bin/python"
    base_python = args.prefix_one / "bin/python3.12"
    native_environment = out / "native-subject"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "UV_PYTHON_DOWNLOADS": "never", "UV_LINK_MODE": "copy",
           "PT_TEST_PYTHON": str(python), "PT_OBSERVER_TEST_PYTHON": str(native_environment / "bin/python"),
           "PT_OBSERVER_BASE_PYTHON": str(base_python), "PT_COORDINATOR_CASE_ROOT": str(out / "coordinator-cases"),
           "PT_SESSION_CASE_ROOT": str(out / "session-cases"), "PT_JUNIT_CASE_ROOT": str(out / "junit-cases"),
           "PT_OBSERVER_CASE_ROOT": str(out / "observer-cases"), "PT_SESSION_TEST_INHERITED": "read-only-setup-nonsecret-control",
           "PT_IDENTITY_PREFIX_MANIFEST": str(args.manifest), "PT_IDENTITY_PREFIX_MANIFEST_SHA256": args.manifest_sha256,
           "PT_IDENTITY_PREFIX_ONE": str(args.prefix_one), "PT_IDENTITY_PREFIX_TWO": str(args.prefix_two),
           "PT_IDENTITY_PROOF_OUTPUT": str(out / "native-prefix-proof.json")}
    specifications = [
        (["uv", "--no-config", "venv", "--offline", "--python", str(base_python), str(native_environment)], {}),
        (["uv", "--no-config", "sync", "--offline", "--locked", "--no-build", "--active", "--project", str(ROOT / "bench/corpus/serial_core")], {"VIRTUAL_ENV": str(native_environment)}),
        (["cargo", "test", "--locked", "--offline", "--release", "--workspace", "--", "--include-ignored"], {}),
        (["cargo", "clippy", "--locked", "--offline", "--workspace", "--all-targets", "--", "-D", "warnings"], {}),
        (["cargo", "fmt", "--all", "--check"], {}),
    ]
    for folder in ("integration", "conformance", "contracts"):
        specifications.append(([str(python), "-B", "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", "tests/" + folder, "-v"], {}))
    specifications += [
        (["cargo", "build", "--locked", "--offline", "--release", "-p", "pt-cli"], {}),
        (["uv", "--no-config", "build", "--offline", "--wheel", "--python", str(base_python), "--out-dir", str(out / "wheel"), "python/pt_bridge"], {}),
        ([str(python), "-B", "tests/packaging/check_bridge_install.py", "--wheel", str(out / "wheel/pt_bridge-0.0.0-py3-none-any.whl"), "--binary", str(ROOT / "target/release/pt"), "--base-python", str(base_python), "--output", str(out / "packaging")], {}),
        (["cargo", "test", "--locked", "--offline", "--release", "-p", "pt-identity", "--test", "private_prefix", "--", "--ignored"], {"PT_IDENTITY_PROOF_OUTPUT": str(out / "native-prefix-after-setup.json")}),
    ]
    save(out / "plan.json", {"commands": [{"argv": argv, "explicit_test_overrides": overrides, "status": "not_run"} for argv, overrides in specifications],
                            "readonly_setup_only": True, "immutable_generation_verified": False, "qualified": False})
    records = []
    for index, (argv, overrides) in enumerate(specifications, 1):
        save(out / f"{index}.requested.json", {"argv": argv, "status": "unknown_execution_return", "qualified": False})
        try:
            result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, timeout=360, env={**env, **overrides})
            stdout, stderr = result.stdout, result.stderr
            record = {"argv": argv, "returncode": result.returncode, "status": "returned_unqualified",
                      "test_summaries": re.findall(r"test result: [^\n]+", stdout.decode(errors="replace")),
                      "python_summaries": re.findall(r"Ran [0-9]+ tests[^\n]*", stderr.decode(errors="replace"))}
        except (OSError, subprocess.TimeoutExpired) as error:
            stdout, stderr = getattr(error, "stdout", None) or b"", getattr(error, "stderr", None) or b""
            record = {"argv": argv, "returncode": None, "status": "unknown_execution_return", "error": type(error).__name__ + ": " + str(error)}
        (out / f"{index}.stdout").write_bytes(stdout)
        (out / f"{index}.stderr").write_bytes(stderr)
        save(out / f"{index}.returned.json", record)
        records.append(record)
        if record["returncode"] != 0:
            print(stdout.decode(errors="replace") + stderr.decode(errors="replace"), flush=True)
            break
    source = ROOT / "bench/corpus/interpreter/materialize.py"
    spec = importlib.util.spec_from_file_location("independent_read_only_prefix_verifier", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    independent = []
    for path in (args.prefix_one, args.prefix_two):
        try:
            observation = module.verify_prefix(path, json.loads(raw_manifest)["entries"])
        except (OSError, ValueError) as error:
            observation = {"status": "unavailable", "error": type(error).__name__ + ": " + str(error)}
        independent.append({"root": str(path), **observation})
    packages = lambda value: {(row["name"], row["version"], row.get("source"), row.get("checksum")) for row in value["package"]}
    before = packages(tomllib.loads((out / "frozen/Cargo.lock").read_text()))
    after = packages(tomllib.loads((ROOT / "Cargo.lock").read_text()))
    inputs = [json.loads(path.read_bytes()) for path in (out / "coordinator-cases").rglob("native-records.json")]
    not_run = [{"index": index, "argv": argv, "status": "not_run"}
               for index, (argv, _) in enumerate(specifications, 1) if index > len(records)]
    report = {"status": "failed_or_not_run_readonly_setup_checks", "records": records, "not_run": not_run, "sources": sources,
              "sources_unchanged": all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in sources.items()),
              "cargo_package_identities_unchanged": len(before) if before == after else False, "independent_prefixes_after_setup": independent,
              "python_observer_subject_requests": len(list((out / "observer-cases").rglob("*.process.json"))),
              "coordinator_pytest_requests": len(list((out / "coordinator-cases").rglob("invocation.json"))),
              "all_coordinator_results_nonzero_unqualified": bool(inputs) and all(row["final_result"]["cli_exit_code"] > 0 and not row["final_result"]["current_full_success"] and not row["final_result"]["environment_verified"] for row in inputs),
              "immutable_generation_verified": False, "qualified": False}
    wheel = out / "wheel/pt_bridge-0.0.0-py3-none-any.whl"
    report["wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest() if wheel.exists() else None
    if (out / "packaging/result.json").exists():
        report["packaging"] = json.loads((out / "packaging/result.json").read_bytes())
    if (len(records) == len(specifications) and all(row["returncode"] == 0 for row in records) and before == after
            and report["sources_unchanged"] and report["all_coordinator_results_nonzero_unqualified"]
            and all(row["status"] == "matched_exact_prefix" for row in independent)):
        report["status"] = "passed_development_readonly_setup_checks"
    save(out / "result.json", report)
    print(json.dumps({"root": str(out), **{key: value for key, value in report.items() if key != "sources"}}, sort_keys=True), flush=True)
    raise SystemExit(int(report["status"] != "passed_development_readonly_setup_checks"))


if __name__ == "__main__":
    main()
