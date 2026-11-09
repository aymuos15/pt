"""Explicit doctor probe: isolated, no site initialization or project imports.

Invoked as python -I -S -B -c <this source>. This is installation metadata
inspection, not proof of the ordinary runtime's import graph or conformance.
"""

import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import sysconfig


def inspect():
    expected = {"pytest": "8.4.2", "pt-bridge": "0.0.0"}
    result = {"mode": "isolated_installation_metadata_only", "qualified": False,
              "target": "linux-x86_64-cpython312-pytest842",
              "python": list(sys.version_info[:3]), "packages": {}, "errors": [],
              "limitations": ["site initialization and PYTHONPATH deliberately not evaluated",
                              "installed files and provenance not verified",
                              "no pytest semantic or source-generation qualification"]}
    if (sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 12)
            or platform.system() != "Linux" or platform.machine() != "x86_64"
            or sysconfig.get_config_var("Py_GIL_DISABLED")):
        result["errors"].append("unsupported_interpreter_profile")
    # With -S on CPython 3.12, sys.prefix can be the base prefix. Preserve the
    # invoked venv executable path rather than following its base-Python symlink.
    root = Path(sys.executable).absolute().parent.parent
    site = root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not (root / "pyvenv.cfg").is_file() or not site.is_dir():
        result["errors"].append("explicit_standard_virtual_environment_required")
    else:
        distributions = list(metadata.distributions(path=[str(site)]))
        for name, version in expected.items():
            matching = [item for item in distributions
                        if re.sub(r"[-_.]+", "-", item.metadata.get("Name", "")).lower() == name]
            if len(matching) != 1:
                result["errors"].append(f"{name}:missing_or_duplicate_distribution")
                continue
            observed = matching[0].version
            result["packages"][name] = observed
            if observed != version:
                result["errors"].append(f"{name}:unsupported_version")
            if name == "pt-bridge" and any(ep.group == "pytest11" for ep in matching[0].entry_points):
                result["errors"].append("bridge_must_not_autoload")
        result["pth_files_present"] = any(site.glob("*.pth"))
    result["status"] = ("installed_profile_present_unqualified" if not result["errors"]
                        else "unavailable_or_unsupported")
    return result


try:
    report = inspect()
except (OSError, ValueError, TypeError, KeyError):
    report = {"mode": "isolated_installation_metadata_only", "qualified": False,
              "status": "invalid_installation_metadata", "errors": ["cannot_inspect_metadata"]}
with os.fdopen(os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as output:
    json.dump(report, output, sort_keys=True)
raise SystemExit(0 if not report["errors"] else 4)
