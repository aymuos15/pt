"""Actual explicit bridge/reference controls, not a qualified launcher or full result.

Each arm is requested independently in a new real pytest process and frozen work
copy. The independent reference observer/oracle never enters product imports.
"""

import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "bench/corpus/serial_core"
ECOSYSTEM = ROOT / "bench/corpus/serial_ecosystem"
SOURCE = ROOT / "python/pt_bridge/src"
REFERENCE = ROOT / "tests/conformance"
spec = importlib.util.spec_from_file_location("independent_bridge_test_reference_reader", REFERENCE / "trace_oracle.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
SCHEMA = json.loads((ROOT / "docs/protocol-v0.schema.json").read_bytes())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def junit_projection(raw, process_code):
    if len(raw) > 4*1024*1024 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("test JUnit input is unsupported or exceeds its explicit bound")
    result = []
    for item in ET.fromstring(raw).iter("testcase"):
        adverse = [child.tag for child in item if child.tag in ("failure", "error", "skipped")]
        if len(adverse) > 1:
            raise ValueError("ambiguous test JUnit outcome")
        name = item.attrib.get("name")
        if name is None and process_code not in (2, 3):
            raise ValueError("unidentified JUnit row cannot establish an ordinary completed test")
        # Pytest can leave <testcase time="..."/> after an interrupted setup /
        # call boundary. Preserve the missing identity/outcome as unknown, never
        # fabricate a named occurrence or infer pass from absence of <failure>.
        result.append([name, adverse[0] if adverse else "unknown" if name is None else "passed"])
    return result


class JunitProjectionControls(unittest.TestCase):
    def test_interrupted_unnamed_rows_remain_unknown_not_passed_or_reconstructed(self):
        raw = b'<testsuites><testsuite tests="0"><testcase time="0.000"/></testsuite></testsuites>'
        self.assertEqual(junit_projection(raw, 2), [[None, "unknown"]])
        self.assertEqual(junit_projection(raw, 3), [[None, "unknown"]])
        with self.assertRaises(ValueError):
            junit_projection(raw, 0)

    def test_ambiguous_entity_and_oversize_junit_are_rejected_without_omitting_rows(self):
        for raw in (b'<testsuite><testcase name="x"><failure/><error/></testcase></testsuite>',
                    b'<!DOCTYPE testsuite><testsuite/>', b' '*(4*1024*1024+1)):
            with self.assertRaises(ValueError):
                junit_projection(raw, 1)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate observed bridge key")
        result[key] = value
    return result


def read_socket(stream, destination, frames, faults):
    """Test-owned framing reader, deliberately not importing product _wire."""
    size = 0
    try:
        stream.settimeout(40)
        with destination.open("xb") as output:
            def exact(length, *, eof=False):
                raw = bytearray()
                while len(raw) < length:
                    chunk = stream.recv(length-len(raw))
                    if not chunk:
                        if eof and not raw:
                            return None
                        raise ValueError("truncated observed frame")
                    raw.extend(chunk)
                return bytes(raw)

            while (prefix := exact(4, eof=True)) is not None:
                length = struct.unpack("!I", prefix)[0]
                size += 4 + length
                if not 1 <= length <= 1024*1024 or size > 8*1024*1024 or len(frames) >= 25000:
                    raise ValueError("observed test stream exceeded its declared finite bound")
                raw = exact(length)
                output.write(prefix + raw)
                frames.append(json.loads(raw.decode("utf-8"), object_pairs_hook=unique))
    except BaseException as exc:
        faults.append(type(exc).__name__ + ": " + str(exc))


@unittest.skipUnless(sys.platform == "linux" and platform.machine() == "x86_64" and sys.version_info[:3] == (3, 12, 12),
                     "real bridge observations pin Linux x86-64 CPython 3.12.12")
class RealPytestObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pt-observer-environments-", dir="/tmp/opencode")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.environment_root = Path(cls.temporary.name)
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("explicit uv/offline subject setup is required; no dependency fallback")
        cache = subprocess.check_output([uv, "--no-config", "cache", "dir"], text=True, timeout=10).strip()
        cls.setup_env = {"PATH": os.defpath, "HOME": str(cls.environment_root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                         "UV_CACHE_DIR": cache, "UV_LINK_MODE": "copy", "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never",
                         "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        cls.environments = {}
        for name, project in (("core", CORE), ("ecosystem", ECOSYSTEM)):
            environment = cls.environment_root / name
            base = os.environ.get("PT_OBSERVER_BASE_PYTHON", sys.executable)
            for argv in ([uv, "--no-config", "venv", "--offline", "--python", base, str(environment)],
                         [uv, "--no-config", "sync", "--offline", "--locked", "--no-build", "--active", "--project", str(project)]):
                result = subprocess.run(argv, cwd=cls.environment_root, env={**cls.setup_env, "VIRTUAL_ENV": str(environment)},
                                        capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    raise RuntimeError("explicit offline observer subject setup failed without repair/retry: " + result.stderr)
            cls.environments[name] = environment

    def setUp(self):
        retained = os.environ.get("PT_OBSERVER_CASE_ROOT")
        if retained is None:
            temporary = tempfile.TemporaryDirectory(prefix="pt-observer-case-", dir="/tmp/opencode")
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        else:
            self.root = Path(retained) / self.id()
            self.root.mkdir(mode=0o700)
        (self.root / "home").mkdir()
        self.counter = 0

    def invoke(self, profile, case, arm, *, arguments=(".",), environment="core", extra_files=None, configure=None):
        self.counter += 1
        label = f"{self.counter:03}-{case}-{profile}-{arm}"
        work = self.root / "work"
        subject = CORE if environment == "core" else ECOSYSTEM
        shutil.copytree(subject / "fixtures" / case, work)
        shutil.copyfile(subject / "pyproject.toml", work / "pyproject.toml")
        for name, raw in (extra_files or {}).items():
            (work / name).write_text(raw)
        before = {str(path.relative_to(work)): path.read_bytes() for path in work.rglob("*") if path.is_file()}
        venv = self.environments[environment]
        command = ([str(venv / "bin/python"), "-m", "pytest"] if profile == "pytest_module" else [str(venv / "bin/pytest")])
        command += ["-q", "--junitxml=junit.xml", "--basetemp=pytest-tmp"]
        reference = self.root / (label + ".jsonl")
        if arm == "reference":
            command += ["-p", "pt_reference_observer", "--pt-reference-trace=" + str(reference)]
        elif arm == "bridge":
            command += ["-p", "pt_bridge.pytest_observer"]
        command += list(arguments)
        # Explicit symmetric correctness-only environment, never production policy.
        env = {"PATH": str(venv / "bin") + os.pathsep + os.defpath, "HOME": str(self.root / "home"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "PYTHONPATH": os.pathsep.join((str(work), str(SOURCE), str(REFERENCE))), "PYTHONHASHSEED": "0",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PT_CORE_EVENTS": str(work / "events.txt"),
               "HYPOTHESIS_STORAGE_DIRECTORY": str(work / ".hypothesis")}
        frames, faults, reader = [], [], None
        parent = child = None
        identity = {"request_id": "observer-request", "run_id": "observer-run", "generation_id": "observer-generation",
                    "session_id": "observer-session", "producer_id": "observer-bridge"}
        pass_fds = ()
        if arm == "bridge":
            parent, child = socket.socketpair()
            settings = {"schema_version": 1, "fd": child.fileno(), "identity": identity, "invocation_profile": profile,
                        "mode": "collect_only" if "--collect-only" in arguments else "run", "max_items": 256,
                        "max_collection_reports": 1024, "max_nodeid_bytes": 1024*1024,
                        "byte_budget": 8*1024*1024, "event_budget": 25000, "timeout_seconds": 30}
            if configure is not None:
                configure(settings)
            env["PT_BRIDGE_CONTROL"] = json.dumps(settings)
            pass_fds = (child.fileno(),)
            reader = threading.Thread(target=read_socket, args=(parent, self.root / (label + ".wire"), frames, faults))
            reader.start()
        observation = {"status": "unknown_execution_return", "argv": command, "returncode": None,
                       "full_result_qualified": False, "arm": arm, "profile": profile}
        try:
            result = subprocess.run(command, cwd=work, env=env, pass_fds=pass_fds, capture_output=True, text=True, timeout=35)
            observation.update(status="returned_unqualified", returncode=result.returncode)
            (self.root / (label + ".stdout")).write_text(result.stdout)
            (self.root / (label + ".stderr")).write_text(result.stderr)
        finally:
            if child is not None:
                child.close()
            if reader is not None:
                reader.join(40)
                if reader.is_alive():
                    parent.shutdown(socket.SHUT_RDWR)
                    reader.join()
                parent.close()
            (self.root / (label + ".process.json")).write_text(json.dumps(observation, sort_keys=True, indent=2))
        self.assertEqual(faults, [], label)
        junit = []
        if (work / "junit.xml").exists():
            junit = junit_projection((work / "junit.xml").read_bytes(), result.returncode)
        effects = (work / "events.txt").read_text().splitlines() if (work / "events.txt").exists() else None
        for name, raw in before.items():
            self.assertEqual((work / name).read_bytes(), raw, "test sources must not be changed by the observer")
        observed = {"process": observation, "junit": junit, "effects": effects, "frames": frames,
                    "work": self.root / ("retained-" + label), "label": label}
        work.rename(observed["work"])
        if arm == "reference":
            observed["reference"] = oracle.read_trace(reference, result.returncode)["normalized"]
        if arm == "bridge":
            for sequence, frame in enumerate(frames):
                VALIDATOR.validate(frame)
                self.assertEqual(frame["sequence"], sequence)
                self.assertEqual(frame["producer_role"], "bridge")
                self.assertEqual({name: frame[name] for name in identity}, identity)
        return observed

    def compare(self, case, *, arguments=(".",), environment="core", profile="pytest_module", expected_exit=None, extra_files=None):
        arms = [self.invoke(profile, case, arm, arguments=arguments, environment=environment, extra_files=extra_files)
                for arm in ("plain", "reference", "bridge")]
        plain, reference, bridge = arms
        for arm in arms[1:]:
            self.assertEqual(arm["process"]["returncode"], plain["process"]["returncode"], arm["label"])
            self.assertEqual(arm["junit"], plain["junit"], arm["label"])
            self.assertEqual(arm["effects"], plain["effects"], arm["label"])
        if expected_exit is not None:
            self.assertEqual(plain["process"]["returncode"], expected_exit)
        frames = bridge["frames"]
        self.assertTrue(frames)
        self.assertEqual(frames[0]["kind"], "session_started")
        self.assertEqual(frames[-1]["kind"], "session_terminated")
        terminal = frames[-1]["payload"]
        self.assertTrue(terminal["reporting_complete"], bridge["label"])
        self.assertEqual(terminal["backend_exit_code"], plain["process"]["returncode"])
        self.assertFalse(any(frame["kind"] == "session_error" for frame in frames), bridge["label"])
        ref = reference["reference"]
        inventory = [frame["payload"] for frame in frames if frame["kind"] == "item_collected"]
        self.assertEqual(inventory, ref["collected"])
        for kind, key in (("items_selected", "selected"), ("items_deselected", "deselected")):
            values = [ordinal for frame in frames if frame["kind"] == kind for ordinal in frame["payload"]["ordinals"]]
            self.assertEqual(values, ref[key])
        phase_projection = [{"ordinal": value["ordinal"], "nodeid": inventory[value["ordinal"]]["nodeid"], "when": value["phase"],
                             "outcome": value["outcome"], "wasxfail": value["was_xfail"], "failure_message": value["reason"]}
                            for frame in frames if frame["kind"] == "phase_report" for value in [frame["payload"]]]
        phase_keys = ("ordinal", "nodeid", "when", "outcome", "wasxfail", "failure_message")
        self.assertEqual(phase_projection, [{key: value[key] for key in phase_keys} for value in ref["phases"]])
        warning_projection = [{"category": value["category"], "message": value["message"],
                               "nodeid": inventory[value["ordinal"]]["nodeid"] if value["ordinal"] is not None else ""}
                              for frame in frames if frame["kind"] == "warning" for value in [frame["payload"]]]
        self.assertEqual(warning_projection, [{key: value[key] for key in ("category", "message", "nodeid")} for value in ref["warnings"]])
        self.assertEqual([frame["payload"]["ordinal"] for frame in frames if frame["kind"] == "item_started"], ref["started"])
        self.assertEqual([frame["payload"]["ordinal"] for frame in frames if frame["kind"] == "item_not_run"], ref["not_run"])
        collection = [{"nodeid": value["nodeid"], "outcome": value["outcome"], "failure_message": value["reason"]}
                      for frame in frames if frame["kind"] == "collection_report" for value in [frame["payload"]]]
        self.assertEqual(collection, [{key: value[key] for key in ("nodeid", "outcome", "failure_message")} for value in ref["collection_reports"]])
        (self.root / (bridge["label"] + ".comparison.json")).write_text(json.dumps({"status": "matched_finite_observer_projection",
            "full_result_qualified": False, "limitations": ["capture sections, required artifacts, environment and immutable generation are separate gates"],
            "occurrences": len(inventory), "phases": len(phase_projection)}, sort_keys=True))
        return arms

    def test_all_ten_core_cases_match_fresh_plain_and_independent_reference_requests(self):
        declaration = json.loads((CORE / "corpus.json").read_bytes())
        for case in declaration["cases"]:
            with self.subTest(case=case["id"]):
                self.compare(case["id"], arguments=case["argv"], expected_exit=case["expected_exit_code"])

    def test_selection_collect_only_fail_fast_and_no_tests_keep_explicit_scope_and_accounting(self):
        for case, arguments, code in (("basic", ["-k", "first", "."], 0), ("basic", ["--collect-only", "."], 0),
                                      ("phases", ["-x", "."], 1), ("basic", ["-k", "not_present", "."], 5)):
            with self.subTest(case=case, arguments=arguments):
                self.compare(case, arguments=arguments, expected_exit=code)

    def test_both_actual_entrypoint_profiles_preserve_session_import_and_fixture_effects(self):
        for profile in ("pytest_module", "pytest_console"):
            with self.subTest(profile=profile):
                self.compare("imports", profile=profile, expected_exit=0)

    def test_actual_async_property_and_sqlite_plugins_match_without_autoload_suppression(self):
        for case, code in (("async_cases", 1), ("property_cases", 0), ("database_cases", 0)):
            with self.subTest(case=case):
                arms = self.compare(case, environment="ecosystem", expected_exit=code)
                if case == "database_cases":
                    self.assertTrue(all(not (arm["work"] / "database.lease").exists() for arm in arms))

    def test_outer_finalizer_is_visible_unsupported_without_suppressing_its_cleanup(self):
        wrapper = "import pytest\nfrom pathlib import Path\n@pytest.hookimpl(wrapper=True,tryfirst=True)\ndef pytest_unconfigure(config):\n    result=yield\n    Path('outer-cleanup').write_text('actually finalized')\n    return result\n"
        bridge = self.invoke("pytest_module", "basic", "bridge", extra_files={"conftest.py": wrapper})
        self.assertEqual(bridge["process"]["returncode"], 0)
        self.assertEqual((bridge["work"] / "outer-cleanup").read_text(), "actually finalized")
        self.assertTrue(any(frame["kind"] == "session_error" and frame["payload"]["code"] == "unconfigure_wrapper_order_unsupported" for frame in bridge["frames"]))
        self.assertFalse(bridge["frames"][-1]["payload"]["reporting_complete"])

    def test_warning_delivery_and_warnings_as_errors_preserve_real_pytest_behavior(self):
        source = "import warnings\ndef test_warning():\n    warnings.warn('PT_OBSERVER_WARNING',UserWarning)\n"
        for arguments, code in ((["test_warning.py"], 0), (["-W", "error::UserWarning", "test_warning.py"], 1)):
            with self.subTest(arguments=arguments):
                self.compare("basic", arguments=arguments, expected_exit=code, extra_files={"test_warning.py": source})

    def test_collection_loaded_plugin_and_session_inventory_hook_are_not_disabled(self):
        conftest = "def pytest_collection_modifyitems(config,items):\n    config.pluginmanager.import_plugin('late_plugin')\n"
        plugin = "from pathlib import Path\nwith Path('late-import').open('x') as output: output.write('one import')\ndef pytest_sessionfinish(session,exitstatus):\n    Path('session-view').write_text(str(len(session.items)))\n"
        arms = self.compare("basic", expected_exit=0, extra_files={"conftest.py": conftest, "late_plugin.py": plugin})
        self.assertTrue(all((arm["work"] / "late-import").read_text() == "one import" for arm in arms))
        self.assertTrue(all((arm["work"] / "session-view").read_text() == "4" for arm in arms))

    def test_invalid_bootstrap_is_rejected_before_project_conftest_import(self):
        source = "from pathlib import Path\nPath('must-not-import-conftest').touch()\n"
        for mutation in (lambda value: value.update(schema_version=True), lambda value: value.update(unknown=None),
                         lambda value: value.update(max_items=0)):
            bridge = self.invoke("pytest_module", "basic", "bridge", extra_files={"conftest.py": source}, configure=mutation)
            self.assertEqual(bridge["process"]["returncode"], 4)
            self.assertEqual(bridge["frames"], [])
            self.assertFalse((bridge["work"] / "must-not-import-conftest").exists())

    def test_actual_keyboard_interrupt_retains_the_partial_attempt_and_exit_two(self):
        source = "import os\nfrom pathlib import Path\ndef test_interrupt():\n    with Path(os.environ['PT_CORE_EVENTS']).open('a') as output: output.write('started once\\n')\n    raise KeyboardInterrupt('PT_OBSERVER_INTERRUPT')\n"
        arms = self.compare("basic", arguments=["test_interrupt.py"], expected_exit=2, extra_files={"test_interrupt.py": source})
        terminal = arms[-1]["frames"][-1]["payload"]
        self.assertEqual(terminal["incomplete_ordinals"], [0])
        self.assertEqual(terminal["accounting"]["completed_count"], 0)
        self.assertEqual(terminal["termination"], "interrupted")

    def test_explicit_parameter_ids_never_request_extra_project_repr_and_fd_capture_stays_in_pytest(self):
        source = "import os,pytest\nfrom pathlib import Path\nclass Parameter:\n    def __repr__(self):\n        Path('extra-repr').touch()\n        return 'PT_PROJECT_REPR'\n@pytest.mark.parametrize('value',[Parameter()],ids=['exact-λ/a'])\ndef test_parameter_and_capture(value,capfd):\n    os.write(1,b'PT_FD_STDOUT')\n    os.write(2,b'PT_FD_STDERR')\n    out,err=capfd.readouterr()\n    assert out=='PT_FD_STDOUT' and err=='PT_FD_STDERR'\n"
        arms = self.compare("basic", arguments=["test_parameter_capture.py"], expected_exit=0, extra_files={"test_parameter_capture.py": source})
        self.assertTrue(all(not (arm["work"] / "extra-repr").exists() for arm in arms))


if __name__ == "__main__":
    unittest.main()
