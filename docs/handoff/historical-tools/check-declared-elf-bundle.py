"""Independent read-back of one returned development bundle; no target execution."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tomllib
import zipfile


root, outer = map(Path, sys.argv[1:3])
live = len(sys.argv) == 4 and sys.argv[3] == "--live"
out = outer / "run"
base = Path("/tmp/opencode/pt-private-interpreter-bounded-dmjw5w0t/run")
prefixes = [base / "prefix-2", Path("/tmp/opencode/pt-isolated-probe-prefix-control-ncmm4r2y/new-clean-prefix")]
pins = ("Cargo.lock", "bench/harness/uv.lock", "python/pt_bridge/pyproject.toml", "support-matrix.toml", "rust-toolchain.toml", "bench/corpus/candidates.toml", "docs/protocol-v0.schema.json", "docs/final-result-v0.schema.json")
report = {"status": "independent_readback_started", "qualified": False,
          "runtime_environment_verified": False, "immutable_generation_verified": False}


def field(h, raw):
    h.update(len(raw).to_bytes(8, "big") + raw)


def packages(text):
    return {(row["name"], row["version"], row.get("source"), row.get("checksum")) for row in tomllib.loads(text)["package"]}


def elf_projection(raw):
    assert raw[:9] == b"\x7fELF\x02\x01\x01\0\0"
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    size, count = struct.unpack_from("<HH", raw, 54)
    assert size == 56 and count == 13
    headers = [list(struct.unpack_from("<IIQQQQQQ", raw, phoff + index * size)) for index in range(count)]
    interp, = [row for row in headers if row[0] == 3]
    interpreter = raw[interp[2]:interp[2] + interp[5]]
    assert interpreter.endswith(b"\0") and b"\0" not in interpreter[:-1]
    dyn, = [row for row in headers if row[0] == 2]
    dynamic = [list(struct.unpack_from("<QQ", raw, dyn[2] + index)) for index in range(0, dyn[5], 16)]
    used = next(index + 1 for index, (tag, _) in enumerate(dynamic) if tag == 0)
    assert len(dynamic) == 35 and used == 30
    assert all(tag == value == 0 for tag, value in dynamic[used - 1:])
    address, = [value for tag, value in dynamic[:used] if tag == 5]
    table_size, = [value for tag, value in dynamic[:used] if tag == 10]
    assert table_size == 43370
    # Independently partition the complete virtual interval by all intersecting
    # file-backed LOAD endpoints. Each partition must have one file offset.
    loads = [row for row in headers if row[0] == 1 and row[5]]
    stops = sorted({address, address + table_size} | {
        point for row in loads for point in (row[3], row[3] + row[5])
        if address < point < address + table_size})
    table = bytearray()
    participating = set()
    for start, end in zip(stops, stops[1:]):
        candidates = [(index, row[2] + start - row[3]) for index, row in enumerate(loads)
                      if row[3] <= start and end <= row[3] + row[5]]
        assert candidates and len({offset for _, offset in candidates}) == 1
        participating.update(index for index, _ in candidates)
        offset = candidates[0][1]
        table.extend(raw[offset:offset + end - start])
    assert len(table) == table_size and len(participating) == 2
    strings = []
    kinds = {1: "Needed", 14: "Soname", 15: "Rpath", 29: "Runpath", 0x6ffffefa: "Config",
             0x6ffffefb: "DepAudit", 0x6ffffefc: "Audit", 0x7ffffffd: "Auxiliary", 0x7fffffff: "Filter"}
    for tag, value in dynamic[:used]:
        if tag in kinds:
            end = table.index(0, value)
            strings.append({"kind": kinds[tag], "bytes": list(table[value:end])})
    needed = [bytes(row["bytes"]).decode("ascii") for row in strings if row["kind"] == "Needed"]
    search = [["RPATH" if row["kind"] == "Rpath" else "RUNPATH", bytes(row["bytes"]).decode("ascii")]
              for row in strings if row["kind"] in ("Rpath", "Runpath")]
    assert needed == ["libpthread.so.0", "libdl.so.2", "libutil.so.1", "librt.so.1", "libm.so.6", "libc.so.6"]
    assert search == [["RPATH", "$ORIGIN/../lib"]]
    return {"program_headers": headers, "dynamic_entries": dynamic, "used_dynamic_entries": used,
            "interpreter": interpreter[:-1].decode("ascii"), "needed": needed, "string_inputs": strings,
            "search": search, "image_sha256": hashlib.sha256(raw).hexdigest(), "image_bytes": len(raw),
            "object_type": struct.unpack_from("<H", raw, 16)[0], "os_abi": raw[7],
            "entry_point": struct.unpack_from("<Q", raw, 24)[0]}


try:
    returned = json.loads((outer / "returned.json").read_bytes())
    assert returned["returncode"] == 0 and returned["status"] == "returned_unqualified"
    result = json.loads((out / "result.json").read_bytes())
    assert result["status"] == "passed_development_readonly_setup_checks"
    assert len(result["records"]) == 12 and not result["not_run"]
    assert all(row["returncode"] == 0 for row in result["records"])
    for name, digest in result["sources"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
        assert (out / "frozen" / name).read_bytes() == (root / name).read_bytes(), name
        if name.endswith(".py"):
            ast.parse((root / name).read_bytes(), filename=name, feature_version=(3, 12))
    manifest = (base / "prefix-manifest.json").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == "53d7e48554c08a0f6ee912d085cfa37a8256f7a0bb6c7d29d9dc48ac408e279e"
    assert hashlib.sha256((base / "interpreter.tar.gz").read_bytes()).hexdigest() == "1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c"
    spec = importlib.util.spec_from_file_location("independent_elf_bundle_archive", root / "bench/corpus/interpreter/materialize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module.plan_archive(base / "interpreter.tar.gz")
    assert expected == json.loads(manifest)["entries"]
    h = hashlib.sha256(b"pt-tree-manifest-v1\0")
    h.update((0o700).to_bytes(4, "big") + len(expected).to_bytes(8, "big"))
    for row in expected:
        field(h, row["path"].encode())
        h.update(row["mode"].to_bytes(4, "big"))
        if row["kind"] == "directory":
            h.update(b"\0")
        elif row["kind"] == "symlink":
            h.update(b"\1")
            field(h, row["target"].encode())
        else:
            h.update(b"\2" + row["bytes"].to_bytes(8, "big") + row["mtime_ns"].to_bytes(16, "big", signed=True) + bytes.fromhex(row["sha256"]))
    tree_digest = h.hexdigest()
    assert tree_digest == "aef7ea220c93ad437c655d74c617c0b7a7a1cfc0a51c47e6a960d7185a39f499"
    links = [row for row in expected if row["kind"] == "symlink"]
    assert len(links) == 1048
    native = [(name, json.loads((out / name).read_bytes())) for name in ("native-prefix-proof.json", "native-prefix-after-setup.json")]
    observations = []
    references = 0
    for index, prefix in enumerate(prefixes):
        assert module.verify_prefix(prefix, expected)["status"] == "matched_exact_prefix"
        h = hashlib.sha256(b"pt-declared-link-resolution-v1\0")
        field(h, tree_digest.encode("ascii"))
        h.update(len(links).to_bytes(8, "big"))
        resolved_rows = []
        raw_root = os.fsencode(prefix)
        for row in links:
            name = row["path"].encode()
            resolved = os.path.realpath(raw_root + b"/" + name, strict=True)
            assert os.path.commonpath([raw_root, resolved]) == raw_root
            relative = os.path.relpath(resolved, raw_root)
            if relative == b".":
                relative = b""
            info = os.stat(resolved)
            assert stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            directory = stat.S_ISDIR(info.st_mode)
            field(h, name)
            field(h, relative)
            h.update(b"\0" if directory else b"\2")
            resolved_rows.append({"path": row["path"], "resolved": os.fsdecode(relative), "kind": "directory" if directory else "file"})
        link_digest = h.hexdigest()
        assert link_digest == "7f38ee25958f4fc2ee5aeb9320227a947a3be244c34dbccc392a81c90fdf713d"
        raw = (prefix / "bin/python3.12").read_bytes()
        projected = elf_projection(raw)
        assert projected["image_sha256"] == "3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66"
        assert next(row for row in expected if row["path"] == "bin/python3.12")["sha256"] == projected["image_sha256"]
        for name, document in native:
            row = next(value for value in document["reports"] if value["root"] == str(prefix))
            assert row["manifest_sha256"] == tree_digest and row["entries"] == 4971
            assert row["bytes_hashed"] == 191199150 and row["file_bytes"] == 95599575
            assert row["declared_relative_links"]["resolution_sha256"] == link_digest
            assert row["declared_relative_links"]["component_steps"] == 1648
            if live:
                association = row["declared_elf_file"]
                assert association["policy_id"] == "linux-live-declared-elf-file-v1"
                assert association["bytes_hashed"] == len(raw) * 2
                root_info, file_info = prefix.stat(), (prefix / "bin/python3.12").stat(follow_symlinks=False)
                assert association["root_device_inode"] == [root_info.st_dev, root_info.st_ino]
                assert association["file_device_inode"] == [file_info.st_dev, file_info.st_ino]
                assert not association["exhaustive_tree_verified_by_file_inspection"]
                assert not association["execution_authorized"]
            elf = row["declared_elf_load_inputs"]
            assert elf["policy_id"] == "elf64le-x86_64-declared-load-inputs-v1"
            assert elf["path"] == "bin/python3.12" and elf["bytes_hashed"] == len(raw)
            for key, value in projected.items():
                if key != "search":
                    assert elf[key] == value, (name, key)
            reference = out / (Path(name).stem + f"-elf-reference-{index}.json")
            oracle = json.loads(reference.read_bytes())
            for key, value in projected.items():
                if key != "string_inputs":
                    assert oracle[key] == value, (reference.name, key)
            assert oracle["readelf_returncode"] == 0 and oracle["readelf_locale"] == "C"
            assert oracle["readelf_sha256"] == "8a18acb78aa5ede10f30f815a4aeb58eaa2a85d9b887efff68292c66311fa48c"
            assert not oracle["target_executed"] and not elf["dependency_resolution_verified"]
            text = reference.with_suffix(".readelf.stdout").read_text()
            assert re.findall(r"\(NEEDED\)[^\n]*Shared library: \[([^\]]*)\]", text) == projected["needed"]
            assert re.findall(r"Requesting program interpreter: ([^\]]+)\]", text) == [projected["interpreter"]]
            assert re.findall(r"\((RPATH|RUNPATH)\)[^\n]*Library (?:rpath|runpath): \[([^\]]*)\]", text) == [tuple(value) for value in projected["search"]]
            process = json.loads(reference.with_suffix(".process.json").read_bytes())
            assert process["leader_status"] == {"kind": "exited", "code": 0} and process["cleanup"]["kind"] == "complete"
            references += 1
        after = module.verify_prefix(prefix, expected)
        assert after["status"] == "matched_exact_prefix"
        with (outer / f"independent-links-and-elf-{index}.json").open("x") as stream:
            json.dump({"root": str(prefix), "links": resolved_rows, "resolution_sha256": link_digest,
                       "declared_elf": projected, "qualified": False}, stream, sort_keys=True, indent=2)
            stream.write("\n")
        observations.append({"root": str(prefix), **after, "resolved_links": len(links), "resolution_sha256": link_digest,
                             "additional_elf_image_bytes_hashed": len(raw) * (2 if live else 1), "elf_image_sha256": projected["image_sha256"]})
    for name in pins:
        assert (root / name).read_bytes() == subprocess.check_output(["git", "show", "HEAD:" + name], cwd=root), name
    assert packages((root / "Cargo.lock").read_text()) == packages(subprocess.check_output(["git", "show", "HEAD:Cargo.lock"], cwd=root, text=True))
    assert len(packages((root / "Cargo.lock").read_text())) == 50
    workspace_passes = sum(int(re.search(r"([0-9]+) passed", value).group(1)) for value in result["records"][2]["test_summaries"])
    assert workspace_passes == (225 if live else 209)
    wheel = out / "wheel/pt_bridge-0.0.0-py3-none-any.whl"
    wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert wheel_sha == "4e973ca41e0a9f1614ebd0615f3d302fd4513a19e5a02acd1f68e4450ec286c1"
    with zipfile.ZipFile(wheel) as archive:
        for path in (root / "python/pt_bridge/src/pt_bridge").glob("*.py"):
            assert archive.read("pt_bridge/" + path.name) == path.read_bytes()
    links_checked = 0
    for name in ("README.md", "docs/development.md", "docs/wp06-status.md", "docs/wp09-status.md", "crates/pt-identity/README.md"):
        source = root / name
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", source.read_text()):
            target = target.split("#", 1)[0]
            if target and "://" not in target:
                assert (source.parent / target).exists(), (name, target)
                links_checked += 1
    report.update(status="passed_independent_elf_development_readback", workspace_release_passes=workspace_passes,
                  planned_commands=12, not_run_commands=0, frozen_source_files=len(result["sources"]),
                  cargo_package_identities_unchanged=50, unchanged_pin_files=len(pins), local_links=links_checked,
                  canonical_tree_manifest_sha256=tree_digest, independent_prefixes_after_outer=observations,
                  elf_reference_processes=references, parent_readonly_flags=[bool(os.statvfs(path).f_flag & os.ST_RDONLY) for path in prefixes],
                  wheel_sha256=wheel_sha)
except Exception as error:
    report.update(status="failed_independent_elf_development_readback", error=type(error).__name__ + ": " + str(error))
with (outer / "independent-after-outer.json").open("x") as stream:
    json.dump(report, stream, sort_keys=True, indent=2)
    stream.write("\n")
print(json.dumps({"root": str(outer), **report}, sort_keys=True))
raise SystemExit(int(report["status"] != "passed_independent_elf_development_readback"))
