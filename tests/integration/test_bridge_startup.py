"""Actual startup/entrypoint adverse controls, not an approved production launcher.

The explicitly loaded test plugin adopts the framing component only after Python
startup. These controls expose the earlier window; they never suppress those
hooks, retry work, or treat a later complete frame as proof of safe startup.
"""

import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {"request_id": "startup-request", "run_id": "startup-run", "generation_id": "startup-generation",
            "session_id": "startup-session", "producer_id": "startup-bridge"}
PLUGIN = '''import json,os,time
from pathlib import Path
from pt_bridge._wire import ControlStream

stream=ControlStream.take_fd(int(os.environ['PT_STARTUP_FD']),json.loads(os.environ['PT_STARTUP_IDENTITY']),byte_budget=4096,event_budget=1)
with Path(os.environ['PT_STARTUP_EVENTS']).open('a') as output:
    output.write(json.dumps({'stage':'adopted','inheritable':os.get_inheritable(stream.stream.fileno())})+'\\n')

def pytest_sessionfinish(session):
    stream.send('warning',{'ordinal':None,'category':'builtins.UserWarning','message':'TEST_ONLY_STARTUP_COMPONENT','filename':'startup_plugin.py','line':1,'when':'finalize'},deadline=time.monotonic()+2)
    stream.close()
'''
EARLY = '''import json,os
from pathlib import Path

fd=int(os.environ['PT_STARTUP_FD'])
with Path(os.environ['PT_STARTUP_EVENTS']).open('a') as output:
    output.write(json.dumps({'stage':os.environ['PT_STARTUP_STAGE'],'inheritable':os.get_inheritable(fd)})+'\\n')
if os.environ.get('PT_STARTUP_EARLY_EXEC') == '1':
    import subprocess,sys
    code="import os,pathlib,sys; pathlib.Path(sys.argv[2]).write_text(str(os.get_inheritable(int(sys.argv[1]))))"
    # Isolated/no-site flags belong only to this deliberate exec-leak probe, not
    # the real parent pytest entrypoint or its early startup hooks.
    subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(fd),os.environ['PT_STARTUP_EXEC_RESULT']],close_fds=False,check=True,timeout=5)
if os.environ.get('PT_STARTUP_EARLY_ABORT') == '1':
    raise SystemExit(41)
'''


@unittest.skipUnless(sys.platform == "linux" and sys.implementation.name == "cpython" and sys.version_info[:3] == (3, 12, 12),
                     "startup controls pin Linux CPython 3.12.12")
class BridgeStartupControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pt-startup-environment-", dir="/tmp/opencode")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.venv = cls.root / "environment"
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("explicitly installed uv and cached serial-core artifacts are required")
        cache = subprocess.check_output([uv, "--no-config", "cache", "dir"], text=True, timeout=10).strip()
        cls.setup_env = {"PATH": os.defpath, "HOME": str(cls.root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                         "UV_CACHE_DIR": cache, "UV_LINK_MODE": "copy", "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never",
                         "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        base = os.environ.get("PT_STARTUP_TEST_PYTHON", sys.executable)
        for command in ([uv, "--no-config", "venv", "--offline", "--python", base, str(cls.venv)],
                        [uv, "--no-config", "sync", "--offline", "--locked", "--active", "--project", str(ROOT / "bench/corpus/serial_core")]):
            observed = subprocess.run(command, cwd=cls.root, env={**cls.setup_env, "VIRTUAL_ENV": str(cls.venv)},
                                      capture_output=True, text=True, timeout=120)
            if observed.returncode != 0:
                raise RuntimeError("startup fixture offline environment setup failed without fallback: " + observed.stderr)
        cls.python, cls.console = cls.venv / "bin/python", cls.venv / "bin/pytest"
        cls.site = cls.venv / "lib/python3.12/site-packages"

    def setUp(self):
        evidence = os.environ.get("PT_STARTUP_CASE_ROOT")
        if evidence is None:
            temporary = tempfile.TemporaryDirectory(prefix="case-", dir=self.root)
            self.addCleanup(temporary.cleanup)
            self.case = Path(temporary.name)
        else:
            self.case = Path(evidence) / self.id()
            self.case.mkdir(mode=0o700)
        self.project = self.case / "project"
        self.plugins = self.case / "plugins"
        self.project.mkdir(mode=0o700)
        self.plugins.mkdir(mode=0o700)
        (self.plugins / "startup_plugin.py").write_text(PLUGIN)
        (self.project / "conftest.py").write_text(
            "import json,os\nfrom pathlib import Path\n"
            "with Path(os.environ['PT_STARTUP_EVENTS']).open('a') as output:\n"
            "    output.write(json.dumps({'stage':'conftest','inheritable':os.get_inheritable(int(os.environ['PT_STARTUP_FD']))})+'\\n')\n")
        (self.project / "test_body.py").write_text(
            "import json,os\nfrom pathlib import Path\n"
            "def test_body():\n"
            "    assert not os.get_inheritable(int(os.environ['PT_STARTUP_FD']))\n"
            "    with Path(os.environ['PT_STARTUP_EVENTS']).open('a') as output: output.write(json.dumps({'stage':'body'})+'\\n')\n")
        self.counter = 0

    def early_module(self, name):
        (self.plugins / (name + ".py")).write_text(EARLY)

    def pth(self):
        self.early_module("early_startup_control")
        path = self.site / "zz_pt_test_owned_startup.pth"
        with path.open("x") as output:
            output.write("import early_startup_control\n")
        self.addCleanup(path.unlink)

    def run_profile(self, profile, **options):
        self.counter += 1
        event_file = self.case / f"events-{self.counter}.jsonl"
        executable = self.python if profile == "module" else self.console
        argv = [str(executable), *(["-m", "pytest"] if profile == "module" else []), "-q", "-p", "startup_plugin", "test_body.py"]
        parent, child = socket.socketpair()
        with parent, child:
            parent.settimeout(2)
            fd = child.fileno()
            env = {"PATH": str(self.venv / "bin") + os.pathsep + os.defpath, "HOME": str(self.case), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                   "PYTHONPATH": str(self.plugins) + os.pathsep + str(ROOT / "python/pt_bridge/src"),
                   "PT_STARTUP_FD": str(fd), "PT_STARTUP_EVENTS": str(event_file), "PT_STARTUP_STAGE": "early",
                   "PT_STARTUP_IDENTITY": json.dumps(IDENTITY), "PT_STARTUP_EXEC_RESULT": str(self.case / "exec-descendant"), **options}
            result = subprocess.run(argv, cwd=self.project, env=env, pass_fds=(fd,), capture_output=True, text=True, timeout=30)
            child.close()
            raw = bytearray()
            while data := parent.recv(4096):
                raw.extend(data)
                self.assertLessEqual(len(raw), 4096, "test-only control channel must remain bounded")
        events = [json.loads(line) for line in event_file.read_text().splitlines()] if event_file.exists() else []
        observed = {"argv": argv, "returncode": result.returncode, "events": events, "confirmed_control_frame": False,
                    "production_startup_qualified": False}
        if raw:
            self.assertGreaterEqual(len(raw), 4)
            self.assertEqual(struct.unpack("!I", raw[:4])[0], len(raw) - 4)
            message = json.loads(raw[4:])
            self.assertEqual(message["payload"]["message"], "TEST_ONLY_STARTUP_COMPONENT")
            observed["confirmed_control_frame"] = True
        (self.case / f"process-{self.counter}.json").write_text(json.dumps(observed, sort_keys=True, indent=2))
        (self.case / f"stdout-{self.counter}").write_text(result.stdout)
        (self.case / f"stderr-{self.counter}").write_text(result.stderr)
        return observed

    def assert_normal_after_adoption(self, observed):
        self.assertEqual(observed["returncode"], 0, observed)
        self.assertTrue(observed["confirmed_control_frame"])
        self.assertFalse(observed["production_startup_qualified"])
        stages = observed["events"]
        index = next(index for index, value in enumerate(stages) if value["stage"] == "adopted")
        self.assertFalse(stages[index]["inheritable"])
        self.assertEqual([value["stage"] for value in stages[index:]], ["adopted", "conftest", "body"])
        self.assertFalse(stages[index + 1]["inheritable"])

    def test_explicit_component_adopts_before_conftest_in_both_real_entrypoints(self):
        for profile in ("module", "console"):
            observed = self.run_profile(profile)
            self.assert_normal_after_adoption(observed)
            self.assertEqual(observed["events"][0]["stage"], "adopted")

    def test_pth_project_import_precedes_component_adoption_and_still_sees_inheritable_capability(self):
        self.pth()
        for profile in ("module", "console"):
            observed = self.run_profile(profile, PT_STARTUP_STAGE="pth")
            self.assert_normal_after_adoption(observed)
            early = [value for value in observed["events"] if value["stage"] == "pth"]
            self.assertTrue(early, observed)
            self.assertTrue(all(value["inheritable"] for value in early))
            self.assertEqual(observed["events"][0]["stage"], "pth")

    def test_pythonpath_sitecustomize_precedes_explicit_adoption_without_being_suppressed(self):
        self.early_module("sitecustomize")
        for profile in ("module", "console"):
            observed = self.run_profile(profile, PT_STARTUP_STAGE="sitecustomize")
            self.assert_normal_after_adoption(observed)
            self.assertEqual(observed["events"][0], {"stage": "sitecustomize", "inheritable": True})

    def test_early_hook_can_leak_capability_across_exec_before_a_later_successful_frame(self):
        self.pth()
        observed = self.run_profile("module", PT_STARTUP_STAGE="pth-exec", PT_STARTUP_EARLY_EXEC="1")
        self.assert_normal_after_adoption(observed)
        self.assertEqual((self.case / "exec-descendant").read_text(), "True")
        self.assertEqual(observed["events"][0]["stage"], "pth-exec")
        self.assertFalse(observed["production_startup_qualified"])

    def test_early_abort_remains_nonzero_without_plugin_adoption_body_or_retry(self):
        self.pth()
        observed = self.run_profile("module", PT_STARTUP_STAGE="pth-abort", PT_STARTUP_EARLY_ABORT="1")
        self.assertNotEqual(observed["returncode"], 0)
        self.assertFalse(observed["confirmed_control_frame"])
        self.assertTrue(observed["events"])
        self.assertTrue(all(value["stage"] == "pth-abort" for value in observed["events"]))
        self.assertEqual(self.counter, 1)

    def test_project_pytest_module_shadow_is_not_hidden_by_console_substitution(self):
        (self.project / "pytest.py").write_text(
            "import json,os\nfrom pathlib import Path\n"
            "with Path(os.environ['PT_STARTUP_EVENTS']).open('a') as output: output.write(json.dumps({'stage':'shadow-pytest','inheritable':os.get_inheritable(int(os.environ['PT_STARTUP_FD']))})+'\\n')\n"
            "raise SystemExit(42)\n")
        module = self.run_profile("module")
        self.assertEqual(module["returncode"], 42)
        self.assertEqual(module["events"], [{"stage": "shadow-pytest", "inheritable": True}])
        self.assertFalse(module["confirmed_control_frame"])
        console = self.run_profile("console")
        self.assert_normal_after_adoption(console)
        self.assertNotEqual(module["argv"][0], console["argv"][0])
        self.assertEqual(self.counter, 2)  # Two explicit profiles, not failure fallback.


if __name__ == "__main__":
    unittest.main()
