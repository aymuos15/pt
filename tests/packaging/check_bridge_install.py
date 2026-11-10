"""Local before/after installation smoke check, not WP03/WP05 conformance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import zipfile


ROOT = Path(__file__).resolve().parents[2]
if not __debug__:
    raise RuntimeError("packaging assertions require Python without -O")


def run(argv, *, cwd, env, expected=0, pass_fds=()):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=120, pass_fds=pass_fds)
    if result.returncode != expected:
        raise AssertionError(f"command exit {result.returncode}, expected {expected}: "
                             f"{result.stdout}\n{result.stderr}")
    return result


def check(wheel, binary, parent, base_python="3.12.12"):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "pt_bridge/__init__.py" in names
        assert "pt_bridge/_wire.py" in names
        assert "pt_bridge/_observer.py" in names and "pt_bridge/pytest_observer.py" in names
        assert "pt_bridge/_artifacts.py" in names
        assert not any(name == "pytest.py" or name.startswith("pytest/") for name in names)
        assert not any(name.endswith("entry_points.txt") for name in names)
    environment = parent / "environment"
    project = parent / "project"
    project.mkdir()
    env = os.environ.copy()
    env["UV_LINK_MODE"] = "copy"
    # Explicit symmetric smoke-only bytecode policy, not a production flag or
    # permission to delete/ignore pre-existing startup caches.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
    run(["uv", "venv", "--offline", "--python", base_python, str(environment)], cwd=parent, env=env)
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
    # The harness profile includes coverage's startup .pth and can have pycs
    # from its isolated metadata commands. Do not remove/disable them to make
    # this guard pass: they are explicitly unreviewed startup inputs.
    for profile in ("pytest_module", "pytest_console"):
        checked = run([str(binary), "doctor", "--python", str(python), "--startup-profile", profile], cwd=project, env=env, expected=4)
        startup = json.loads(checked.stdout)["startup"]
        assert "startup_pth_unreviewed:a1_coverage.pth" in startup["errors"]
        assert startup["qualified"] is False
        assert all(value is None for value in startup["assurance"].values())

    # Positive static/observer checks use a separate declared minimal environment,
    # not a repaired or silently reduced version of the harness profile above.
    startup_environment = parent / "startup-environment"
    startup_env = {**env, "VIRTUAL_ENV": str(startup_environment)}
    run(["uv", "venv", "--offline", "--python", str(python), str(startup_environment)], cwd=parent, env=startup_env)
    run(["uv", "sync", "--offline", "--locked", "--active", "--project", str(ROOT / "bench/corpus/serial_core")], cwd=parent, env=startup_env)
    startup_python = startup_environment / "bin/python"
    run(["uv", "pip", "install", "--offline", "--no-index", "--no-deps", "--python", str(startup_python), str(wheel)], cwd=parent, env=startup_env)
    for profile in ("pytest_module", "pytest_console"):
        checked = run([str(binary), "doctor", "--python", str(startup_python), "--startup-profile", profile], cwd=project, env=startup_env)
        startup = json.loads(checked.stdout)["startup"]
        assert startup["status"] == "static_startup_inputs_checked_unqualified"
        assert startup["qualified"] is False
        assert all(value is None for value in startup["assurance"].values())

    (project / "test_installed_observer.py").write_text(
        "import json,os\nfrom pathlib import Path\nimport pytest\n"
        "profile=os.environ['PT_PACKAGING_PROFILE']\n"
        "with Path('import-'+profile).open('x') as output: output.write('one import')\n"
        "@pytest.fixture\ndef observed_fixture():\n"
        "    yield\n"
        "    Path('cleanup-'+profile).write_text('actually finalized')\n"
        "def test_installed_component(observed_fixture):\n"
        "    assert not os.get_inheritable(json.loads(os.environ['PT_BRIDGE_CONTROL'])['fd'])\n"
        "    print('CONTROL-LOOKING STDOUT IS NOT IPC')\n")
    for profile, readiness in (("pytest_module", False), ("pytest_console", False),
                               ("pytest_module", True), ("pytest_console", True)):
        receiving, sending = socket.socketpair()
        frames, faults = [], []

        def read_observer():
            try:
                receiving.settimeout(35)

                def exact(length):
                    raw = bytearray()
                    while len(raw) < length:
                        chunk = receiving.recv(length-len(raw))
                        if not chunk:
                            if not raw:
                                return None
                            raise ValueError("truncated installed-observer frame")
                        raw.extend(chunk)
                    return bytes(raw)

                total = 0
                while (prefix := exact(4)) is not None:
                    size = struct.unpack("!I", prefix)[0]
                    total += 4 + size
                    if not 1 <= size <= 1024*1024 or total > 1024*1024 or len(frames) >= 256:
                        raise ValueError("installed observer exceeded explicit smoke bounds")
                    raw = exact(size)
                    if raw is None:
                        raise ValueError("missing installed-observer payload")
                    frames.append(json.loads(raw))
            except BaseException as exc:
                faults.append(type(exc).__name__ + ": " + str(exc))

        reader = threading.Thread(target=read_observer)
        reader.start()
        settings = {"schema_version": 1, "fd": sending.fileno(),
                    "identity": {"request_id": "installed-request", "run_id": "installed-run", "generation_id": "installed-generation",
                                 "session_id": "installed-session", "producer_id": "installed-bridge"},
                    "invocation_profile": profile, "mode": "run", "max_items": 256, "max_collection_reports": 1024,
                     "max_nodeid_bytes": 1024*1024, "byte_budget": 1024*1024, "event_budget": 256, "timeout_seconds": 30}
        token = profile + ("-junit" if readiness else "")
        report = project / ("installed-junit-" + profile + ".xml")
        if readiness:
            settings.update(schema_version=2, junit_artifact={"artifact_id": "installed-junit", "source": report.name,
                            "max_bytes": 1024*1024, "required": True})
            with report.open("xb"):
                pass
            report.chmod(0o600)  # Only this explicitly new test-owned output.
        argv = ([str(startup_python), "-m", "pytest"] if profile == "pytest_module" else [str(startup_environment / "bin/pytest")])
        argv += ["-q", "-p", "pt_bridge.pytest_observer", "test_installed_observer.py"]
        if readiness:
            argv += ["--junitxml=" + report.name]
        try:
            run(argv, cwd=project, env={**startup_env, "PT_PACKAGING_PROFILE": token, "PT_BRIDGE_CONTROL": json.dumps(settings)}, pass_fds=(sending.fileno(),))
        finally:
            sending.close()
            reader.join(40)
            if reader.is_alive():
                receiving.shutdown(socket.SHUT_RDWR)
                reader.join()
            receiving.close()
        assert not faults, faults
        assert frames[0]["kind"] == "session_started" and frames[-1]["kind"] == "session_terminated"
        assert all(frame["sequence"] == sequence for sequence, frame in enumerate(frames))
        terminal = frames[-1]["payload"]
        assert terminal["backend_exit_code"] == 0 and terminal["reporting_complete"] is True
        assert terminal["accounting"]["completed_count"] == 1 and terminal["accounting"]["not_run_count"] == 0
        assert sum(frame["kind"] == "phase_report" for frame in frames) == 3
        assert not any(frame["kind"] == "session_error" for frame in frames)
        claims = [frame["payload"] for frame in frames if frame["kind"] == "artifact_ready"]
        if readiness:
            raw = report.read_bytes()
            assert claims == [{"artifact_id": "installed-junit", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "complete": True}]
        else:
            assert claims == []
        assert (project / ("cleanup-"+token)).read_text() == "actually finalized"
    run(ordinary, cwd=project, env=env)  # No autoload or process-state leak after explicit sessions.

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
    # The optional static guard rejects rather than imports or disables the
    # project path and unknown .pth. Metadata-only doctor remains distinct.
    pth.write_text(f"import pathlib; pathlib.Path({str(project / 'site-imported')!r}).touch()\n")
    rejected = run([str(binary), "doctor", "--python", str(python), "--startup-profile", "pytest_module"],
                   cwd=project, env=env, expected=4)
    startup = json.loads(rejected.stdout)["startup"]
    assert "startup_environment_input_unreviewed:PYTHONPATH" in startup["errors"]
    assert "startup_pth_unreviewed:pt_doctor_sentinel.pth" in startup["errors"]
    assert not (project / "project-imported").exists() and not (project / "site-imported").exists()
    assert pth.exists(), "guard must not delete an unknown startup input"
    pth.unlink()  # Only this explicitly test-created sentinel is removed.
    run([str(python), "-I", "-c", "import pt_bridge,pt_bridge._artifacts,sys; assert pt_bridge.__version__ == '0.0.0'; assert 'pytest' not in sys.modules"],
        cwd=project, env=env)

    # This explicitly imports only the installed framing component. It is not
    # a pytest session, handshake/catalog ledger or full-result qualification.
    parent, child = socket.socketpair()
    with parent, child:
        parent.settimeout(2)
        fd = child.fileno()
        framed = run([str(python), "-I", "-c", """
import os,sys,time
from pt_bridge._wire import ControlStream
identity={'request_id':'packaging-request','run_id':'packaging-run','generation_id':'packaging-generation','session_id':'packaging-session','producer_id':'packaging-bridge'}
with ControlStream.take_fd(int(sys.argv[1]),identity,byte_budget=4096,event_budget=1) as stream:
    assert not os.get_inheritable(int(sys.argv[1]))
    assert 'pytest' not in sys.modules
    stream.send('warning',{'ordinal':None,'category':'builtins.UserWarning','message':'PT_PACKAGING_CONTROL','filename':'packaging-probe','line':1,'when':'configure'},deadline=time.monotonic()+2)
""", str(fd)], cwd=project, env=env, pass_fds=(fd,))
        child.close()

        def exact(size):
            result = bytearray()
            while len(result) < size:
                data = parent.recv(size - len(result))
                assert data, "installed component returned a truncated control frame"
                result.extend(data)
            return bytes(result)

        size = struct.unpack("!I", exact(4))[0]
        assert 1 <= size <= 4096
        message = json.loads(exact(size))
        assert message["protocol_version"] == 0 and message["contract_revision"] == 1
        assert message["producer_role"] == "bridge" and message["sequence"] == 0
        assert message["request_id"] == "packaging-request"
        assert message["kind"] == "warning" and message["payload"]["message"] == "PT_PACKAGING_CONTROL"
        assert parent.recv(1) == b""
        assert framed.stdout == "", "control messages must not be carried on stdout"
        assert not (project / "project-imported").exists()

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
            "installed_private_framing_component_passed": True,
            "installed_explicit_observer_both_profiles_passed": True,
            "installed_explicit_junit_readiness_both_profiles_passed": True,
            "framing_component_imports_no_pytest": True,
            "static_startup_inputs_checked_unqualified": True,
            "unreviewed_harness_startup_inputs_rejected_not_removed": True,
            "static_startup_rejects_unknown_hooks_without_import_or_suppression": True,
            "doctor_does_not_import_project_modules": True, "qualified": False,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/pt")
    parser.add_argument("--temp-root", type=Path, default=Path("/tmp/opencode"))
    parser.add_argument("--base-python", default="3.12.12", help="explicit interpreter for new disposable environments; no dependency repair")
    parser.add_argument("--output", type=Path, help="new exclusive directory retaining the smoke environments and fixtures")
    args = parser.parse_args()
    if args.output is not None:
        args.output.mkdir(mode=0o700)
        report = check(args.wheel.resolve(strict=True), args.binary.resolve(strict=True), args.output.resolve(strict=True), args.base_python)
        with (args.output / "result.json").open("x") as output:
            json.dump(report, output, sort_keys=True, indent=2)
    else:
        with tempfile.TemporaryDirectory(prefix="pt-packaging-", dir=args.temp_root) as directory:
            report = check(args.wheel.resolve(strict=True), args.binary.resolve(strict=True), Path(directory), args.base_python)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
