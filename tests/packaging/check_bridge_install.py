"""Local before/after installation smoke check, not WP03/WP05 conformance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
if not __debug__:
    raise RuntimeError("packaging assertions require Python without -O")


def run(argv, *, cwd, env, expected=0):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != expected:
        raise AssertionError(f"command exit {result.returncode}, expected {expected}: "
                             f"{result.stdout}\n{result.stderr}")
    return result


def check(wheel, binary, parent):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "pt_bridge/__init__.py" in names
        assert not any(name == "pytest.py" or name.startswith("pytest/") for name in names)
        assert not any(name.endswith("entry_points.txt") for name in names)
    environment = parent / "environment"
    project = parent / "project"
    project.mkdir()
    env = os.environ.copy()
    env["UV_LINK_MODE"] = "copy"
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
    run(["uv", "venv", "--offline", "--python", "3.12.12", str(environment)], cwd=parent, env=env)
    env["VIRTUAL_ENV"] = str(environment)
    run(["uv", "sync", "--offline", "--locked", "--active", "--project", str(ROOT / "bench/harness")],
        cwd=parent, env=env)
    python = environment / "bin/python"
    pytest = environment / "bin/pytest"
    (project / "test_baseline.py").write_text(
        "import sys\n"
        "def test_ordinary_pytest_remains_unmodified(pytestconfig):\n"
        "    assert 'pt_bridge' not in sys.modules\n"
        "    assert pytestconfig.pluginmanager.getplugin('pt_bridge') is None\n"
        "    assert not any(name.startswith('pt_bridge') for name in sys.modules)\n"
    )
    ordinary = [str(pytest), "-q", "-p", "no:cacheprovider", "test_baseline.py"]
    run(ordinary, cwd=project, env=env)
    before = run([str(binary), "doctor", "--python", str(python)], cwd=project, env=env, expected=4)
    before_report = json.loads(before.stdout)
    assert "pt-bridge:missing_or_duplicate_distribution" in before_report["errors"]
    entries = "import importlib.metadata as m,json; print(json.dumps(sorted((e.name,e.value) for e in m.entry_points(group='pytest11'))))"
    before_entries = run([str(python), "-I", "-c", entries], cwd=project, env=env).stdout
    run(["uv", "pip", "install", "--offline", "--no-index", "--no-deps", "--python", str(python), str(wheel)],
        cwd=parent, env=env)
    after_entries = run([str(python), "-I", "-c", entries], cwd=project, env=env).stdout
    assert before_entries == after_entries, "installation changed pytest auto-plugin entries"
    run(ordinary, cwd=project, env=env)

    # Doctor is explicit, isolated metadata inspection: hostile-looking module
    # names in cwd/PYTHONPATH must not be imported by the probe.
    (project / "pytest.py").write_text("from pathlib import Path\nPath('project-imported').touch()\nraise RuntimeError('cwd import')\n")
    (project / "pt_bridge.py").write_text("from pathlib import Path\nPath('project-imported').touch()\nraise RuntimeError('cwd import')\n")
    env["PYTHONPATH"] = str(project)
    pth = environment / "lib/python3.12/site-packages/pt_doctor_sentinel.pth"
    pth.write_text(f"import pathlib; pathlib.Path({str(project / 'site-imported')!r}).touch()\n")
    after = run([str(binary), "doctor", "--python", str(python)], cwd=project, env=env)
    after_report = json.loads(after.stdout)
    assert not (project / "project-imported").exists()
    assert not (project / "site-imported").exists()
    assert after_report["pth_files_present"] is True
    pth.unlink()
    assert after_report["status"] == "installed_profile_present_unqualified"
    assert after_report["qualified"] is False
    assert after_report["packages"] == {"pt-bridge": "0.0.0", "pytest": "8.4.2"}
    run([str(python), "-I", "-c", "import pt_bridge,sys; assert pt_bridge.__version__ == '0.0.0'; assert 'pytest' not in sys.modules"],
        cwd=project, env=env)

    # Mismatched installed metadata must fail closed, not inherit qualification.
    metadata = environment / "lib/python3.12/site-packages/pt_bridge-0.0.0.dist-info/METADATA"
    entry_points = metadata.with_name("entry_points.txt")
    with entry_points.open("x") as output:
        output.write("[pytest11]\npt_bridge = pt_bridge\n")
    autoload = run([str(binary), "doctor", "--python", str(python)], cwd=project, env=env, expected=4)
    assert "bridge_must_not_autoload" in json.loads(autoload.stdout)["errors"]
    entry_points.unlink()
    original = metadata.read_bytes()
    # Never edit an installed file in-place: some installers hard-link to a
    # shared cache even when the environment itself is disposable.
    replacement = metadata.with_name(".pt-wrong-version.tmp")
    with replacement.open("xb") as output:
        output.write(original.replace(b"Version: 0.0.0", b"Version: 9.9.9", 1))
    replacement.replace(metadata)
    assert metadata.stat().st_nlink == 1, "fault injection must not mutate a shared hardlink"
    mismatch = run([str(binary), "doctor", "--python", str(python)], cwd=project, env=env, expected=4)
    assert "pt-bridge:unsupported_version" in json.loads(mismatch.stdout)["errors"]
    return {"status": "local_packaging_smoke_only", "ordinary_pytest_passed_before_and_after": True,
            "pytest11_entries_unchanged": True, "doctor_rejects_missing_and_wrong_bridge": True,
            "doctor_rejects_bridge_autoload": True,
            "doctor_does_not_import_project_modules": True, "qualified": False,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/pt")
    parser.add_argument("--temp-root", type=Path, default=Path("/tmp/opencode"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pt-packaging-", dir=args.temp_root) as directory:
        report = check(args.wheel.resolve(strict=True), args.binary.resolve(strict=True), Path(directory))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
