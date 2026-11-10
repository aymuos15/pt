"""Explicit setup diagnostic under ordinary -B startup, not pytest qualification."""

import json
import os
from pathlib import Path
import platform
import site
import sqlite3
import ssl
import sys
import sysconfig


prefix = Path(sys.prefix).resolve(strict=True)
work = Path.cwd().resolve(strict=True)
probe = Path(__file__).resolve(strict=True)


def origin(filename):
    path = Path(filename).absolute()
    if path.is_relative_to(prefix):
        return {"domain": "prefix", "path": path.relative_to(prefix).as_posix()}
    if path == work:
        return {"domain": "private_work", "path": "."}
    if path == probe:
        return {"domain": "frozen_probe", "path": probe.name}
    if path == probe.parent:
        return {"domain": "frozen_probe_directory", "path": "."}
    raise RuntimeError("unexpected external Python import/search origin: " + str(path))


modules = []
for name, module in sorted(sys.modules.copy().items()):
    filename = getattr(module, "__file__", None)
    if filename is not None:
        modules.append({"name": name, "origin": origin(filename)})

print(json.dumps({
    "kind": "ordinary_startup_setup_diagnostic", "qualified": False,
    "target": {"implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
               "platform": sys.platform, "machine": platform.machine(),
               "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED"))},
    "prefix": str(prefix), "base_prefix": str(Path(sys.base_prefix).resolve(strict=True)),
    "executable": str(Path(sys.executable).resolve(strict=True)),
    "flags": {name: getattr(sys.flags, name) for name in ("no_site", "isolated", "ignore_environment", "no_user_site", "dont_write_bytecode")},
    "site_loaded": "site" in sys.modules, "user_site_enabled": site.ENABLE_USER_SITE,
    "user_site_exists": Path(site.getusersitepackages()).exists(),
    "soabi": sysconfig.get_config_var("SOABI"), "openssl": ssl.OPENSSL_VERSION, "sqlite": sqlite3.sqlite_version,
    "sysconfigdata_prefix": sysconfig.get_config_var("prefix"),
    "search_paths": [origin(path or os.getcwd()) for path in sys.path], "modules": modules,
}, sort_keys=True, allow_nan=False))
