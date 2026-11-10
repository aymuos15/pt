"""Offline, explicit two-prefix interpreter preparation; never repair a managed Python."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TREE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 16384
MAX_PATH_DEPTH = 24
QUALIFICATION = ("signed_build_provenance", "complete_environment", "startup_handoff", "semantic_oracle", "pt_backend", "generation", "release")


def _pairs(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError("duplicate interpreter artifact key")
        value[key] = item
    return value


def load_pin():
    raw = (HERE / "artifact.json").read_bytes()
    if len(raw) > 16384:
        raise ValueError("interpreter artifact declaration exceeds its bound")
    pin = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    if (type(pin) is not dict or set(pin) != {"schema_version", "profile", "status", "target", "source", "archive", "executable"}
            or type(pin["schema_version"]) is not int or pin["schema_version"] != 1
            or pin["profile"] != "pbs-20260211-cpython-3.12.12-linux-x86_64-gnu-stripped-v1"
            or pin["status"] != "pinned_development_artifact_not_qualified"
            or pin["target"] != {"implementation": "cpython", "version": [3, 12, 12], "platform": "linux", "machine": "x86_64", "gil_disabled": False}):
        raise ValueError("unsupported interpreter artifact declaration")
    for key, fields in (("archive", {"name", "bytes", "sha256"}), ("executable", {"path", "bytes", "sha256"})):
        item = pin[key]
        if (type(item) is not dict or set(item) != fields or type(item["bytes"]) is not int or not 1 <= item["bytes"] <= MAX_ARCHIVE_BYTES
                or type(item["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("invalid interpreter byte descriptor")
    if (pin["executable"]["path"] != "bin/python3.12" or type(pin["archive"]["name"]) is not str
            or "/" in pin["archive"]["name"] or type(pin["source"]) is not dict
            or pin["source"].get("signed_build_attestation") is not None):
        raise ValueError("unsupported interpreter executable/provenance declaration")
    return pin, raw


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("interpreter input must be a regular no-follow file")
        yield stream, before
        if (_identity(before) != _identity(os.fstat(stream.fileno()))
                or _identity(before) != _identity(os.stat(path, follow_symlinks=False))):
            raise ValueError("interpreter input changed during read")


def _bytes(stream, maximum, *, output=None):
    digest, size = hashlib.sha256(), 0
    while chunk := stream.read(min(1024 * 1024, maximum - size + 1)):
        size += len(chunk)
        if size > maximum:
            raise ValueError("interpreter file exceeded its byte bound")
        digest.update(chunk)
        if output is not None:
            output.write(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def copy_archive(source, destination, descriptor):
    with _regular(source) as (stream, info):
        if info.st_size != descriptor["bytes"] or info.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("interpreter archive size differs from its pin")
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            observed = _bytes(stream, descriptor["bytes"], output=output)
        if observed != {key: descriptor[key] for key in ("bytes", "sha256")}:
            raise ValueError("interpreter archive SHA-256 differs from its pin")
    return observed


def _path(name):
    if (type(name) is not str or not name or len(name) > 1024 or "\\" in name or "\0" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise ValueError("unsupported interpreter archive path")
    name.encode("utf-8", errors="strict")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or len(path.parts) > MAX_PATH_DEPTH or name == ".":
        raise ValueError("interpreter archive requires canonical bounded relative paths")
    return path


def _link_target(name, target):
    if (type(target) is not str or not target or len(target) > 1024 or target.startswith("/") or "\\" in target
            or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        raise ValueError("unsupported interpreter link target")
    target.encode("utf-8", errors="strict")
    parts = list(PurePosixPath(name).parent.parts)
    for part in target.split("/"):
        if part in ("", "."):
            raise ValueError("noncanonical interpreter link target")
        if part == "..":
            if not parts:
                raise ValueError("interpreter link escapes the private prefix")
            parts.pop()
        else:
            parts.append(part)
    return str(_path("/".join(parts)))


@contextmanager
def _tar(archive):
    # Bound the complete inflated stream, including padding/PAX/header bodies,
    # before tarfile can allocate those bodies. Regular-file totals alone do not
    # bound compressed metadata. Never seek through an unvalidated output tree.
    with _regular(archive) as (source, info):
        if info.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("interpreter archive exceeds compressed byte bound")
        with gzip.GzipFile(fileobj=source) as expanded:
            class Limited:
                size = 0

                def read(self, size):
                    raw = expanded.read(min(size, MAX_EXPANDED_ARCHIVE_BYTES - self.size + 1))
                    self.size += len(raw)
                    if self.size > MAX_EXPANDED_ARCHIVE_BYTES:
                        raise ValueError("interpreter archive exceeds complete inflated byte bound")
                    return raw

            limited = Limited()
            with tarfile.open(fileobj=limited, mode="r|") as tar:
                yield tar
            # Read through gzip trailers too, detecting truncation/CRC errors and
            # expansion beyond bounds even after tar's normal end-of-archive.
            while limited.read(1024 * 1024):
                pass


def plan_archive(archive):
    """Validate the entire bounded namespace before creating any prefix entries."""
    entries, count, total = {}, 0, 0
    with _tar(archive) as tar:
        for member in tar:
            count += 1
            if count > MAX_ENTRIES:
                raise ValueError("interpreter archive exceeds member bound")
            path = _path(member.name.removesuffix("/") if member.isdir() else member.name)
            if path.parts[0] != "python" or len(path.parts) < 2:
                raise ValueError("interpreter archive root must be python/<relative-entry>")
            name = PurePosixPath(*path.parts[1:]).as_posix()
            if name in entries:
                raise ValueError("duplicate interpreter archive entry")
            if (type(member.mtime) is not int or not 0 <= member.mtime < (1 << 32) or member.mode & ~0o777
                    or (not member.issym() and member.mode & 0o002) or member.sparse is not None):
                raise ValueError("unsupported interpreter permissions, timestamp or sparse member")
            row = {"path": name, "mode": member.mode}
            if member.isfile():
                if not 0 <= member.size <= MAX_FILE_BYTES:
                    raise ValueError("interpreter archive file exceeds its bound")
                total += member.size
                if total > MAX_TREE_BYTES:
                    raise ValueError("interpreter archive exceeds aggregate byte bound")
                with tar.extractfile(member) as stream:
                    observed = _bytes(stream, member.size)
                if observed["bytes"] != member.size:
                    raise ValueError("truncated interpreter archive member")
                row.update(kind="file", mtime_ns=member.mtime * 1000000000, **observed)
            elif member.issym():
                # Symlink mode is not chmod'ed; Linux reports 0777. Targets are
                # resolved below and only in-prefix regular-file aliases qualify.
                row.update(kind="symlink", mode=0o777, target=member.linkname)
                _link_target(name, member.linkname)
            elif member.isdir():
                row.update(kind="directory")
            else:
                raise ValueError("hardlinks/devices/FIFOs/unknown interpreter members are unsupported")
            entries[name] = row
    # The official archive contains implicit directories, not directory headers.
    # Derive them; do not count those parents as installed extras.
    for name in list(entries):
        for parent in PurePosixPath(name).parents:
            if str(parent) == ".":
                continue
            key = str(parent)
            if key in entries and entries[key]["kind"] != "directory":
                raise ValueError("interpreter archive places entries beneath a non-directory")
            entries.setdefault(key, {"path": key, "kind": "directory", "mode": 0o755})
            if len(entries) > MAX_ENTRIES:
                raise ValueError("interpreter namespace including implicit parents exceeds its bound")
    for name, row in entries.items():
        if row["kind"] != "symlink":
            continue
        target, visited = name, set()
        while entries.get(target, {}).get("kind") == "symlink":
            if target in visited or len(visited) >= 40:
                raise ValueError("interpreter link cycle/depth exceeds supported resolution")
            visited.add(target)
            target = _link_target(target, entries[target]["target"])
        if entries.get(target, {}).get("kind") != "file":
            raise ValueError("interpreter link must resolve to a declared in-prefix regular file")
    return sorted(entries.values(), key=lambda row: row["path"])


def extract_prefix(archive, destination, manifest):
    """No tarfile extraction API, hardlinks, ownership changes, repair or overwrite."""
    destination.mkdir(mode=0o700)
    expected = {row["path"]: row for row in manifest}
    for row in sorted(manifest, key=lambda row: (len(PurePosixPath(row["path"]).parts), row["path"])):
        if row["kind"] == "directory":
            path = destination / row["path"]
            path.mkdir(mode=0o700)
            path.chmod(row["mode"])
    copied = set()
    with _tar(archive) as tar:
        for member in tar:
            name = str(PurePosixPath(*_path(member.name).parts[1:]))
            row = expected.get(name)
            if row is None or name in copied:
                raise ValueError("interpreter archive namespace changed after validation")
            copied.add(name)
            if row["kind"] != "file":
                continue
            if not member.isfile() or member.size != row["bytes"]:
                raise ValueError("interpreter archive member changed after validation")
            path = destination / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as output, tar.extractfile(member) as stream:
                if _bytes(stream, row["bytes"], output=output) != {key: row[key] for key in ("bytes", "sha256")}:
                    raise ValueError("interpreter member bytes changed after validation")
                os.fchmod(output.fileno(), row["mode"])
            os.utime(path, ns=(row["mtime_ns"], row["mtime_ns"]), follow_symlinks=False)
    for row in manifest:
        if row["kind"] == "symlink":
            os.symlink(row["target"], destination / row["path"])
    return verify_prefix(destination, manifest)


def prefix_inventory(prefix):
    """Observe files, exact link targets and all directories, including unlisted ones."""
    rows, total = [], 0
    if not stat.S_ISDIR(os.lstat(prefix).st_mode):
        raise ValueError("interpreter prefix must not be a symlink")

    def walk(directory, depth=0):
        nonlocal total
        if depth > MAX_PATH_DEPTH:
            raise ValueError("installed interpreter tree exceeds depth bound")
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                name = str(_path(path.relative_to(prefix).as_posix()))
                info = entry.stat(follow_symlinks=False)
                row = {"path": name, "mode": stat.S_IMODE(info.st_mode)}
                if stat.S_ISDIR(info.st_mode):
                    row["kind"] = "directory"
                    rows.append(row)
                    if len(rows) > MAX_ENTRIES:
                        raise ValueError("installed interpreter entry bound exceeded")
                    walk(path, depth + 1)
                    continue
                if stat.S_ISLNK(info.st_mode):
                    row.update(kind="symlink", target=os.readlink(path))
                elif stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
                        raise ValueError("installed interpreter file is linked or exceeds its bound")
                    total += info.st_size
                    if total > MAX_TREE_BYTES:
                        raise ValueError("installed interpreter aggregate byte bound exceeded")
                    with _regular(path) as (stream, before):
                        if _identity(info) != _identity(before):
                            raise ValueError("installed interpreter entry changed before read")
                        row.update(kind="file", mtime_ns=info.st_mtime_ns, **_bytes(stream, info.st_size))
                else:
                    raise ValueError("nonregular installed interpreter entry")
                rows.append(row)
                if len(rows) > MAX_ENTRIES:
                    raise ValueError("installed interpreter entry bound exceeded")

    walk(Path(prefix))
    return sorted(rows, key=lambda row: row["path"])


def verify_prefix(prefix, manifest):
    actual = prefix_inventory(prefix)
    expected, observed = ({row["path"]: row for row in value} for value in (manifest, actual))
    missing, extra = sorted(expected.keys() - observed.keys()), sorted(observed.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & observed.keys() if expected[name] != observed[name])
    return {"status": "matched_exact_prefix" if not (missing or extra or changed) else "prefix_mismatch",
            "missing": missing, "extra": extra, "changed": changed, "entries": len(actual)}


def _tools():
    spec = importlib.util.spec_from_file_location("interpreter_preparation_process_tools", HERE.parent / "serial_core/materialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(archive, output, *, execute=False):
    if execute is not True:
        raise ValueError("--execute is required to create and probe two new private interpreter prefixes")
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("interpreter preparation targets Linux x86-64 only")
    pin, raw_pin = load_pin()
    archive = Path(os.path.abspath(archive))
    output = Path(os.path.abspath(output))
    output = output.parent.resolve(strict=True) / output.name
    if output.is_relative_to(ROOT) or archive.is_relative_to(output):
        raise ValueError("interpreter output must be outside the repository and separate from its input")
    tools = _tools()
    output.mkdir(mode=0o700)
    captured = {"artifact.json": raw_pin, "materialize.py": Path(__file__).read_bytes(), "runtime_probe.py": (HERE / "runtime_probe.py").read_bytes()}
    tools._freeze(output / "frozen", captured)
    for name in ("home", "tmp", "work"):
        (output / name).mkdir(mode=0o700)
    rows = [{"prefix": index, "status": "not_run_prior_failure", "before": None, "observation": None, "runtime": None, "after": None} for index in (1, 2)]
    report = {"kind": "two_private_interpreter_prefixes", "status": "aborted", "profile": pin["profile"], "archive": None,
              "planned_prefixes": rows, "errors": [], "manifest_sha256": None, "confirmatory_eligible": False,
              "qualification": {key: None for key in QUALIFICATION},
              "limitations": ["HTTPS digest pin is identity evidence, not authenticated independent build provenance",
                              "exact regular bytes/modes/mtimes, symlink targets and implicit directories; no ownership/xattr equivalence claim",
                              "ordinary site startup probe uses explicit -B and minimal private HOME/TMPDIR as a setup diagnostic, not production policy",
                              "prefix reads/end checks are not atomic snapshots or hostile-concurrency protection",
                              "host loader/system libraries, installed project environments and pytest semantics remain separate gates"]}
    try:
        private_archive = output / "interpreter.tar.gz"
        report["archive"] = copy_archive(archive, private_archive, pin["archive"])
        manifest = plan_archive(private_archive)
        executable = next((row for row in manifest if row["path"] == pin["executable"]["path"]), None)
        if (executable is None or executable["kind"] != "file" or not executable["mode"] & 0o111
                or any(executable[key] != pin["executable"][key] for key in ("bytes", "sha256"))):
            raise ValueError("archive executable differs from its separate byte pin")
        tools._save(output / "prefix-manifest.json", {"profile": pin["profile"], "entries": manifest})
        report["manifest_sha256"] = hashlib.sha256((output / "prefix-manifest.json").read_bytes()).hexdigest()
        env = {"PATH": os.defpath, "HOME": str(output / "home"), "TMPDIR": str(output / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        for row in rows:
            prefix = output / f"prefix-{row['prefix']}"
            row["status"] = "preparation_failed"
            row["before"] = extract_prefix(private_archive, prefix, manifest)
            if row["before"]["status"] != "matched_exact_prefix":
                raise ValueError("new interpreter prefix differs from the archive manifest")
            row["status"] = "unknown_execution_return"
            observation, raw = tools._command(output, f"probe-{row['prefix']}",
                [str(prefix / pin["executable"]["path"]), "-B", str(output / "frozen/runtime_probe.py")], output / "work", env)
            row.update(status="returned_unqualified", observation=observation)
            if observation["returncode"] != 0:
                raise ValueError("private interpreter ordinary-startup probe failed; no repair/retry")
            runtime = tools.files.parse_json(raw["stdout"])
            row["runtime"] = runtime
            if (runtime.get("target") != pin["target"] or runtime.get("prefix") != str(prefix) or runtime.get("base_prefix") != str(prefix)
                    or runtime.get("executable") != str(prefix / pin["executable"]["path"]) or runtime.get("qualified") is not False
                    or runtime.get("flags") != {"no_site": 0, "isolated": 0, "ignore_environment": 0, "no_user_site": 0, "dont_write_bytecode": 1}
                    or runtime.get("site_loaded") is not True or runtime.get("user_site_exists") is not False
                    or runtime.get("soabi") != "cpython-312-x86_64-linux-gnu"):
                raise ValueError("ordinary-startup runtime does not match the explicit interpreter diagnostic profile")
            row["after"] = verify_prefix(prefix, manifest)
            if row["after"]["status"] != "matched_exact_prefix":
                raise ValueError("private interpreter prefix changed during startup diagnostic")
            row["status"] = "matched_prefix_and_startup_diagnostic_unqualified"
        compared = [{key: value for key, value in row["runtime"].items() if key not in ("prefix", "base_prefix", "executable")} for row in rows]
        if compared[0] != compared[1]:
            raise ValueError("private interpreter diagnostics differ outside exact prefix-root mapping")
        with _regular(private_archive) as (stream, _):
            if _bytes(stream, pin["archive"]["bytes"]) != report["archive"]:
                raise ValueError("private interpreter archive changed during preparation")
        if (load_pin() != (pin, raw_pin)
                or any((output / "frozen" / name).read_bytes() != raw or (HERE / name).read_bytes() != raw for name, raw in captured.items())
                or hashlib.sha256((output / "prefix-manifest.json").read_bytes()).hexdigest() != report["manifest_sha256"]):
            raise ValueError("original/frozen interpreter preparation inputs changed")
        report["status"] = "matched_two_private_prefixes_unqualified"
    except (OSError, EOFError, ValueError, RuntimeError, ImportError, KeyboardInterrupt, tarfile.TarError) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    tools._save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="already-downloaded exact artifact; this command never downloads")
    parser.add_argument("--output", type=Path, required=True, help="new directory outside the repository")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        report = prepare(args.archive, args.output, execute=args.execute)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"interpreter-materialize: {exc}\n")
    print(json.dumps({"status": report["status"], "prefixes": [{"prefix": row["prefix"], "status": row["status"]} for row in report["planned_prefixes"]],
                      "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "matched_two_private_prefixes_unqualified")


if __name__ == "__main__":
    raise SystemExit(main())
