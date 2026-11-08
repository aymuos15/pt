"""Read-only digest checks for a local manifest artifact bundle, not qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from manifest import ManifestError, load_structural_manifest


ARM_FIELDS = ("binary_sha256", "environment_lock_sha256", "interpreter_sha256",
              "reset_script_sha256", "state_probe_sha256")
OTHER_FIELDS = {
    "scenario": ("expected_inventory_sha256", "expected_outcome_artifact_sha256",
                 "reset_policy_document_sha256"),
    "machine": ("profile_sha256",),
    "experiment": ("exclusion_policy_sha256", "pilot_report_sha256"),
    "analysis": ("analysis_code_sha256",),
}


def _digest_status(directory_fd: int, expected: str) -> str:
    """Hash a regular bundle file without following the final symlink on POSIX."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(expected, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            return "not_regular"
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                 item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after):
            return "changed_during_read"
        return "matched" if digest.hexdigest() == expected else "mismatch"
    except OSError:
        return "unreadable"
    finally:
        os.close(fd)


def check_artifacts(data: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Check explicitly named SHA-256 fields against files named by their digest.

    The input must already have passed manifest schema validation. This does not
    establish provenance, semantic content, source revision, or immutable state.
    """
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise ManifestError("safe artifact bundle lookup is unsupported on this platform")
    fields = {arm: ARM_FIELDS for arm in ("candidate", "baseline")}
    fields.update(OTHER_FIELDS)
    if data["scenario"]["coverage"] != "none":
        fields["scenario"] += ("coverage_config_sha256",)
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise ManifestError(f"cannot open artifact directory: {exc}") from exc
    try:
        statuses = {}
        checks = []
        for section, names in fields.items():
            for name in names:
                expected = data[section][name]
                if expected is None:
                    status = "unresolved"
                else:
                    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
                        raise ManifestError(f"invalid artifact digest in {section}.{name}")
                    if expected not in statuses:
                        statuses[expected] = _digest_status(directory_fd, expected)
                    status = statuses[expected]
                checks.append({"field": f"{section}.{name}", "status": status})
    finally:
        os.close(directory_fd)
    return {
        "listed_artifact_checks": checks,
        "all_listed_digests_resolved_and_matching": all(item["status"] == "matched" for item in checks),
        "confirmatory_eligible": False,
        "limitations": ["source revisions and artifact provenance not verified",
                        "artifact semantics and reset equivalence not checked",
                        "no immutable snapshot or complete campaign validation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("bundle", type=Path, help="directory of regular files named by SHA-256")
    args = parser.parse_args()
    try:
        data, _ = load_structural_manifest(args.manifest)
        result = check_artifacts(data, args.bundle)
    except (ManifestError, OSError) as exc:
        print(f"artifact-check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["all_listed_digests_resolved_and_matching"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
