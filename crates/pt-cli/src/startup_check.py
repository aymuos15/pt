"""Bounded static startup rejection checks, embedded in the isolated doctor probe.

Never imported by ordinary Python/pytest. This checks necessary prelaunch inputs,
not their immutability, complete installed-file provenance, native initialization,
or permission to claim safe startup. It executes no inspected hook or project.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys


STARTUP_READ_LIMIT = 1024 * 1024
STARTUP_ENTRY_LIMIT = 64
VIRTUALENV_SHIM = {
    "_virtualenv.pth": "69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d",
    "_virtualenv.py": "cfb3db86aaa53bb62b5ff764970bec2d71c9228590a0ebec57f6ec926cc0bf1a",
}
STARTUP_ENV_INPUTS = ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PYTHONPLATLIBDIR", "PYTHONPYCACHEPREFIX",
                      "PYTHONINSPECT", "PYTHONWARNINGS", "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH")
PYTEST_CONSOLE_BODY = b'''# -*- coding: utf-8 -*-
import sys
from pytest import console_main
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(console_main())
'''


def _startup_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > STARTUP_READ_LIMIT:
            raise ValueError("startup input is not a bounded regular file")
        raw = stream.read(STARTUP_READ_LIMIT + 1)
        after = os.fstat(stream.fileno())
        named = os.stat(path, follow_symlinks=False)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_mtime_ns, value.st_ctime_ns)
        if len(raw) > STARTUP_READ_LIMIT or identity(before) != identity(after) or identity(before) != identity(named):
            raise ValueError("startup input changed during inspection")
    return raw


def _startup_entries(path):
    with os.scandir(path) as entries:
        result = []
        for entry in entries:
            if len(result) >= STARTUP_ENTRY_LIMIT:
                raise ValueError("startup directory exceeds entry bound")
            result.append(entry)
    return sorted(result, key=lambda entry: entry.name)


def inspect_startup(root, library, profile, cwd):
    result = {"mode": "bounded_static_startup_inputs_only", "profile": profile, "qualified": False,
              "errors": [], "files": [], "relevant_environment_names_present": [],
              "assurance": {"immutable_inputs": None, "complete_environment": None, "native_initialization": None,
                            "private_handoff": None, "semantic_backend": None},
              "limitations": ["no inspected .pth/customization/project code is imported or suppressed",
                              "matching static inputs are necessary checks, not a launch authorization or atomic snapshot",
                              "only the exact development uv shim is reviewed; other startup hooks remain unsupported",
                              "cache files are never deleted, ignored via runtime flags or inferred equivalent from source hashes"]}

    def error(code):
        if code not in result["errors"]:
            if len(result["errors"]) >= 16:
                raise ValueError("startup findings exceed the bounded diagnostic reply")
            result["errors"].append(code)

    def capture(path):
        if len(result["files"]) >= 16:
            raise ValueError("startup file inventory exceeds the bounded diagnostic reply")
        raw = _startup_file(path)
        result["files"].append({"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        return raw

    if profile not in ("pytest_module", "pytest_console"):
        raise ValueError("unsupported static startup invocation profile")
    for name in STARTUP_ENV_INPUTS:
        if os.environ.get(name):
            result["relevant_environment_names_present"].append(name)
            error("startup_environment_input_unreviewed:" + name)
    configuration = capture(root / "pyvenv.cfg").decode("utf-8", errors="strict")
    options = {}
    for line in configuration.splitlines():
        if "=" not in line:
            continue
        name, value = (value.strip() for value in line.split("=", 1))
        if name in options:
            raise ValueError("duplicate virtual-environment startup key")
        options[name] = value
    if options.get("include-system-site-packages", "").lower() != "false":
        error("startup_system_or_user_site_domain_unreviewed")
    if library.is_symlink() or not library.is_dir():
        raise ValueError("startup site directory must be an ordinary declared directory")
    entries = _startup_entries(library)
    names = {entry.name for entry in entries}
    for entry in entries:
        # Importable modules/packages can have native or sourceless forms too.
        if entry.name.split(".", 1)[0] in ("sitecustomize", "usercustomize"):
            error("startup_customization_present:" + entry.name)
        if entry.name.endswith(".pth"):
            raw = capture(Path(entry.path))
            if entry.name != "_virtualenv.pth" or hashlib.sha256(raw).hexdigest() != VIRTUALENV_SHIM["_virtualenv.pth"]:
                error("startup_pth_unreviewed:" + entry.name)
    if "_virtualenv.pth" in names:
        if "_virtualenv.py" not in names:
            error("startup_virtualenv_shim_missing")
        else:
            raw = capture(library / "_virtualenv.py")
            if hashlib.sha256(raw).hexdigest() != VIRTUALENV_SHIM["_virtualenv.py"]:
                error("startup_virtualenv_shim_changed")
        # A timestamp/source match alone cannot establish loaded bytecode.
        for name in names:
            if name.split(".", 1)[0] == "_virtualenv" and name not in VIRTUALENV_SHIM:
                error("startup_virtualenv_alternative_origin:" + name)
        if "__pycache__" in names:
            cache = library / "__pycache__"
            if cache.is_symlink() or not cache.is_dir():
                raise ValueError("startup shim cache directory is not an ordinary directory")
            if any(entry.name.startswith("_virtualenv.") for entry in _startup_entries(cache)):
                error("startup_virtualenv_bytecode_unreviewed")
    # The module invocation searches the cwd before installed pytest/bridge
    # dependencies. Console startup instead searches its script directory.
    search = cwd if profile == "pytest_module" else root / "bin"
    protected = set(sys.stdlib_module_names) | {"pytest", "_pytest", "pt_bridge", "pluggy", "packaging", "pygments", "iniconfig"}
    for entry in _startup_entries(search):
        stem = entry.name.split(".", 1)[0]
        importable = entry.is_dir(follow_symlinks=False) or entry.is_symlink() or entry.name.endswith((".py", ".pyc", ".so"))
        if importable and stem in protected:
            error("startup_search_shadowing:" + stem)
    if profile == "pytest_console":
        # Check the actual script at the selected environment, never substitute
        # python -m pytest. Only the ordinary installed pytest console form is
        # currently recognized; alternate wrappers are explicit unsupported data.
        raw = capture(root / "bin/pytest")
        first, separator, body = raw.partition(b"\n")
        expected = [b"#!" + os.fsencode(root / "bin" / name) for name in ("python", "python3", "python3.12")]
        if first not in expected or not separator or body != PYTEST_CONSOLE_BODY:
            error("startup_console_entrypoint_unreviewed")
        elif Path(os.fsdecode(first[2:])).resolve(strict=True) != Path(sys.executable).resolve(strict=True):
            error("startup_console_interpreter_mismatch")
    result["status"] = "static_startup_inputs_checked_unqualified" if not result["errors"] else "startup_inputs_unsupported"
    if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > 12 * 1024:
        raise ValueError("startup findings exceed the bounded diagnostic reply")
    return result
