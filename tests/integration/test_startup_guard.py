"""Static necessary-condition checks, not immutable/safe-startup qualification."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("product_static_startup_guard", ROOT / "crates/pt-cli/src/startup_check.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class StaticStartupGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pt-static-startup-", dir="/tmp/opencode")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.venv = self.root / "environment"
        self.site = self.venv / "lib/python3.12/site-packages"
        self.site.mkdir(parents=True)
        (self.venv / "bin").mkdir()
        (self.venv / "bin/python").symlink_to(Path(sys.executable).resolve())
        (self.venv / "bin/python3").symlink_to(Path(sys.executable).resolve())
        (self.venv / "pyvenv.cfg").write_text("home = /explicit/test-owned/base\ninclude-system-site-packages = false\n")
        (self.venv / "bin/pytest").write_bytes(b"#!" + os.fsencode(self.venv / "bin/python3") + b"\n" + guard.PYTEST_CONSOLE_BODY)
        self.project = self.root / "project"
        self.project.mkdir()

    def inspect(self, profile="pytest_module", env=None):
        with mock.patch.dict(os.environ, env or {}, clear=True):
            return guard.inspect_startup(self.venv, self.site, profile, self.project)

    def shim(self):
        source = ROOT / "bench/harness/.venv/lib/python3.12/site-packages"
        for name in guard.VIRTUALENV_SHIM:
            shutil.copyfile(source / name, self.site / name)

    def test_empty_standard_venv_static_checks_never_become_a_launch_authorization(self):
        for profile in ("pytest_module", "pytest_console"):
            value = self.inspect(profile)
            self.assertEqual(value["status"], "static_startup_inputs_checked_unqualified")
            self.assertFalse(value["qualified"])
            self.assertTrue(all(item is None for item in value["assurance"].values()))
            self.assertFalse((self.project / "effect").exists())

    def test_unreviewed_pth_is_read_as_data_never_imported_deleted_or_suppressed(self):
        raw = b"import pathlib; pathlib.Path('effect').touch()\n"
        path = self.site / "unknown.pth"
        path.write_bytes(raw)
        value = self.inspect()
        self.assertIn("startup_pth_unreviewed:unknown.pth", value["errors"])
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.project / "effect").exists())

    def test_exact_uv_shim_is_recognized_but_changed_or_alternative_origins_fail(self):
        self.shim()
        self.assertEqual(self.inspect()["errors"], [])
        path = self.site / "_virtualenv.py"
        original = path.read_bytes()
        path.write_bytes(original + b"\n# different\n")
        self.assertIn("startup_virtualenv_shim_changed", self.inspect()["errors"])
        path.write_bytes(original)
        (self.site / "_virtualenv").mkdir()
        self.assertIn("startup_virtualenv_alternative_origin:_virtualenv", self.inspect()["errors"])

    def test_startup_bytecode_is_not_certified_by_matching_source_or_automatically_purged(self):
        self.shim()
        cache = self.site / "__pycache__"
        cache.mkdir()
        path = cache / "_virtualenv.cpython-312.pyc"
        raw = b"explicit potentially stale bytecode, never decoded or executed"
        path.write_bytes(raw)
        value = self.inspect()
        self.assertIn("startup_virtualenv_bytecode_unreviewed", value["errors"])
        self.assertEqual(path.read_bytes(), raw)

    def test_python_and_loader_inputs_fail_without_exporting_their_values(self):
        for name in guard.STARTUP_ENV_INPUTS:
            value = self.inspect(env={name: "secret-unknown-input-path-or-option"})
            self.assertIn("startup_environment_input_unreviewed:" + name, value["errors"])
            self.assertNotIn("secret-unknown-input", json.dumps(value))
            self.assertEqual(value["relevant_environment_names_present"], [name])

    def test_module_and_console_search_domains_are_not_silently_substituted(self):
        (self.project / "pytest.py").write_text("raise RuntimeError('must not execute')\n")
        self.assertIn("startup_search_shadowing:pytest", self.inspect("pytest_module")["errors"])
        self.assertEqual(self.inspect("pytest_console")["errors"], [])
        (self.venv / "bin/json.py").write_text("raise RuntimeError('must not execute')\n")
        self.assertIn("startup_search_shadowing:json", self.inspect("pytest_console")["errors"])

    def test_customization_sources_packages_native_and_sourceless_origins_are_rejected(self):
        for name in ("sitecustomize.py", "usercustomize.pyc", "sitecustomize.cpython-312-x86_64-linux-gnu.so"):
            path = self.site / name
            path.write_bytes(b"explicit unreviewed startup input, never executed")
            self.assertIn("startup_customization_present:" + name, self.inspect()["errors"])
            path.unlink()
        (self.site / "sitecustomize").mkdir()
        self.assertIn("startup_customization_present:sitecustomize", self.inspect()["errors"])

    def test_user_and_system_site_domains_require_their_own_contract(self):
        (self.venv / "pyvenv.cfg").write_text("include-system-site-packages = true\n")
        self.assertIn("startup_system_or_user_site_domain_unreviewed", self.inspect()["errors"])
        (self.venv / "pyvenv.cfg").write_text("include-system-site-packages = false\ninclude-system-site-packages = false\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.inspect()

    def test_console_must_be_the_exact_reviewed_wrapper_not_a_substring_match(self):
        script = self.venv / "bin/pytest"
        script.write_bytes(script.read_bytes() + b"\n# unreviewed wrapper bytes\n")
        self.assertIn("startup_console_entrypoint_unreviewed", self.inspect("pytest_console")["errors"])

    def test_wrong_console_interpreter_is_not_replaced_with_selected_python(self):
        path = self.venv / "bin/python3"
        path.unlink()
        path.write_bytes(b"different selected executable, never run")
        self.assertIn("startup_console_interpreter_mismatch", self.inspect("pytest_console")["errors"])

    def test_symlink_fifo_oversize_and_excessive_startup_inputs_fail_before_effects(self):
        target = self.root / "foreign"
        target.write_bytes(b"contents")
        linked = self.site / "foreign.pth"
        linked.symlink_to(target)
        with self.assertRaises(OSError):
            self.inspect()
        linked.unlink()
        os.mkfifo(linked)
        with self.assertRaises(ValueError):
            self.inspect()
        linked.unlink()
        linked.write_bytes(b"oversize")
        with mock.patch.object(guard, "STARTUP_READ_LIMIT", 1), self.assertRaises(ValueError):
            self.inspect()
        with mock.patch.object(guard, "STARTUP_ENTRY_LIMIT", 0), self.assertRaises(ValueError):
            self.inspect()
        self.assertFalse((self.project / "effect").exists())

    def test_more_findings_than_the_reply_budget_fail_instead_of_omitting_inputs(self):
        for index in range(17):
            (self.site / f"unknown-{index}.pth").write_bytes(b"import unreviewed\n")
        with self.assertRaisesRegex(ValueError, "bounded diagnostic reply"):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
