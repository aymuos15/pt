"""Compare a pytest corpus probe across two clean, locked local environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from corpus_inventory import check_inventory


HARNESS = Path(__file__).resolve().parent
CORPUS = HARNESS.parent / "corpus"
PROBE = CORPUS / "probes" / "phase_cases.py"
EXPECTED = [
    {"name": "test_pass", "kind": "passed", "marker": ""},
    {"name": "test_setup_failure", "kind": "error", "marker": "PT_PROBE_SETUP_FAILURE"},
    {"name": "test_teardown_failure", "kind": "error", "marker": "PT_PROBE_TEARDOWN_FAILURE"},
    {"name": "test_strict_xpass", "kind": "failure", "marker": "PT_PROBE_STRICT_XPASS"},
]


def normalize_report(path: Path) -> list[dict[str, str]]:
    """Retain occurrence order and adverse markers, not timestamps or paths."""
    result = []
    for case in ET.parse(path).getroot().findall(".//testcase"):
        children = [child for child in case if child.tag in ("failure", "error", "skipped")]
        if len(children) > 1:
            raise ValueError("ambiguous testcase outcome")
        kind = children[0].tag if children else "passed"
        message = children[0].get("message", "") if children else ""
        marker = next((item["marker"] for item in EXPECTED if item["marker"] in message
                       and item["marker"]), "")
        result.append({"name": case.get("name", ""), "kind": kind, "marker": marker})
    return result


def _run(command: list[str], *, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=120, check=True)


def materialize_and_probe(root: Path) -> dict:
    """Use only local uv caches; this is not a benchmark or secure snapshot."""
    before = check_inventory(CORPUS / "manifest.toml")
    lock_sha256 = hashlib.sha256((HARNESS / "uv.lock").read_bytes()).hexdigest()
    observations = []
    for index in (1, 2):
        environment = root / f"environment-{index}"
        base_env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME",
                    "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            base_env.pop(key, None)
        base_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        _run(["uv", "venv", "--offline", "--python", "3.12.12", str(environment)],
             env=base_env, cwd=root)
        base_env["VIRTUAL_ENV"] = str(environment)
        _run(["uv", "sync", "--offline", "--locked", "--active", "--project", str(HARNESS)],
             env=base_env, cwd=root)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        with python.open("rb") as binary:
            interpreter_sha256 = hashlib.file_digest(binary, "sha256").hexdigest()
        identity_code = (
            "import importlib.metadata as m,json,sys; "
            "print(json.dumps({'python':list(sys.version_info[:3]),"
            "'distributions':sorted((d.metadata['Name'],d.version) for d in m.distributions())}))"
        )
        identity = json.loads(_run([str(python), "-c", identity_code], env=base_env, cwd=root).stdout)
        installed = json.loads(_run([str(python), str(HARNESS / "installed_inventory.py")],
                                    env=base_env, cwd=root).stdout)
        report = root / f"phase-{index}.xml"
        pytest = subprocess.run(
            [str(python), "-m", "pytest", "-p", "no:cacheprovider", "-q", str(PROBE),
             f"--junitxml={report}"], cwd=root, env=base_env, text=True, capture_output=True,
            timeout=120,
        )
        if pytest.returncode != 1 or not report.is_file():
            raise ValueError(f"probe {index}: expected pytest exit 1 and JUnit report")
        observed = normalize_report(report)
        if observed != EXPECTED:
            raise ValueError(f"probe {index}: unexpected occurrences or adverse outcomes")
        if identity["python"] != [3, 12, 12]:
            raise ValueError(f"probe {index}: unexpected Python version")
        suite_run = subprocess.run(
            [str(python), str(HARNESS / "corpus_smoke_suite.py")], cwd=root, env=base_env,
            text=True, capture_output=True, timeout=120,
        )
        if suite_run.returncode != 0:
            raise ValueError(f"environment {index}: corpus smoke suite failed: "
                             f"{suite_run.stdout}\n{suite_run.stderr}")
        suite = json.loads(suite_run.stdout)
        if suite.get("status") != "passed" or not suite.get("outcomes"):
            raise ValueError(f"environment {index}: corpus smoke suite incomplete")
        installed_after = json.loads(_run([str(python), str(HARNESS / "installed_inventory.py")],
                                          env=base_env, cwd=root).stdout)
        if installed != installed_after:
            raise ValueError(f"probe {index}: installed-file inventory changed during execution")
        observations.append({"identity": identity, "interpreter_sha256": interpreter_sha256,
                             "installed_file_check": installed,
                             "exit_code": pytest.returncode, "corpus_smoke_suite": suite,
                             "occurrences": observed})
    if observations[0] != observations[1]:
        raise ValueError("clean environments produced different inventories or outcomes")
    after = check_inventory(CORPUS / "manifest.toml")
    if before != after or hashlib.sha256((HARNESS / "uv.lock").read_bytes()).hexdigest() != lock_sha256:
        raise ValueError("inventory or lock changed during materialization")
    return {"status": "local_smoke_only", "environments": len(observations),
            "lock_sha256": lock_sha256, "observation": observations[0],
            "confirmatory_eligible": False,
            "limitations": ["no immutable source or environment snapshot", "RECORD provenance not verified",
                            "unhashed and unlisted files not verified",
                            "only current synthetic smoke cases", "no representative corpus or platform qualification"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-root", type=Path, help="existing directory for temporary environments")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="pt-materialize-", dir=args.temp_root) as directory:
            result = materialize_and_probe(Path(directory))
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as exc:
        print(f"materialize-check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
