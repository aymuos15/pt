"""Exercise locked serial-core venvs against two independently verified private bases."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_preparation(directory, preparation, tools):
    """Saved status is only a precondition; re-read artifact/manifest/all prefix bytes."""
    pin, raw = preparation.load_pin()
    report, _ = tools.files.read_json(directory / "result.json")
    if report.get("status") != "matched_two_private_prefixes_unqualified" or report.get("profile") != pin["profile"]:
        raise ValueError("a completed private-prefix setup record is required; no recovery of a lost setup API return")
    archive = directory / "interpreter.tar.gz"
    with preparation._regular(archive) as (stream, info):
        observed = preparation._bytes(stream, pin["archive"]["bytes"])
    if observed != {key: pin["archive"][key] for key in ("bytes", "sha256")}:
        raise ValueError("private interpreter archive differs from the separately pinned artifact")
    manifest = preparation.plan_archive(archive)
    saved, _ = tools.files.read_json(directory / "prefix-manifest.json", limit=tools.files.MAX_RECEIPT_BYTES)
    if saved != {"profile": pin["profile"], "entries": manifest} or (directory / "frozen/artifact.json").read_bytes() != raw:
        raise ValueError("private interpreter manifest/declaration differs from independent archive inspection")
    before = [preparation.verify_prefix(directory / f"prefix-{index}", manifest) for index in (1, 2)]
    if any(row["status"] != "matched_exact_prefix" for row in before):
        raise ValueError("a private interpreter prefix changed since preparation; never repair it")
    return pin, manifest, before


def check(prepared, output, *, execute=False):
    if execute is not True:
        raise ValueError("--execute is required for two offline venv installations and twenty planned pytest requests")
    prepared = Path(prepared).resolve(strict=True)
    output = Path(os.path.abspath(output))
    output = output.parent.resolve(strict=True) / output.name
    if output.is_relative_to(ROOT) or output.is_relative_to(prepared) or prepared.is_relative_to(output):
        raise ValueError("serial-core evidence must be separate from repository/prepared interpreter inputs")
    preparation = _load("serial_core_private_interpreter_tools", HERE / "materialize.py")
    core = _load("serial_core_private_base_corpus", HERE.parent / "serial_core/materialize.py")
    pin, manifest, before = verify_preparation(prepared, preparation, core)
    output.mkdir(mode=0o700)
    captured = {"check_serial_core.py": Path(__file__).read_bytes(), "materialize.py": (HERE / "materialize.py").read_bytes(),
                "artifact.json": (HERE / "artifact.json").read_bytes(),
                "serial_core_materialize.py": (HERE.parent / "serial_core/materialize.py").read_bytes()}
    core._freeze(output / "frozen", captured)
    report = {"kind": "serial_core_on_pinned_private_bases", "status": "unknown_corpus_return", "before": before, "after": None,
              "corpus": None, "errors": [], "confirmatory_eligible": False,
              "qualification": {key: None for key in preparation.QUALIFICATION},
              "limitations": ["actual pytest baseline with declared sentinels/JUnit, not a production bridge/backend or phase oracle",
                              "independently rehashed complete base prefixes, not immutable execution or complete host library identity",
                              "preparation is explicit/offline and separate from product execution/timing; no managed interpreter edits"]}
    try:
        interpreters = [prepared / f"prefix-{index}" / pin["executable"]["path"] for index in (1, 2)]
        report["corpus"] = core.materialize(output / "corpus", execute=True, interpreters=interpreters)
        report["status"] = "incomplete_corpus_or_interpreter_check"
        # An actual returned failed corpus is retained, not overwritten by a
        # clean final prefix. Never reconstruct a missing return from its files.
        report["after"] = [preparation.verify_prefix(prepared / f"prefix-{index}", manifest) for index in (1, 2)]
        if any(row["status"] != "matched_exact_prefix" for row in report["after"]):
            raise ValueError("base interpreter changed during serial-core materialization/execution")
        if report["corpus"]["status"] != "reproduced_declared_mechanism_profile":
            raise ValueError("returned serial-core materialization was incomplete or failed")
        if any((output / "frozen" / name).read_bytes() != raw for name, raw in captured.items()):
            raise ValueError("private-base corpus preparation source changed")
        verify_preparation(prepared, preparation, core)
        report["status"] = "matched_core_on_two_pinned_private_bases_unqualified"
    except (OSError, EOFError, ValueError, RuntimeError, ImportError, KeyboardInterrupt, tarfile.TarError) as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
    core._save(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        report = check(args.prepared, args.output, execute=args.execute)
    except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
        parser.exit(2, f"private-base-serial-core: {exc}\n")
    print(json.dumps({"status": report["status"], "corpus_status": None if report["corpus"] is None else report["corpus"]["status"],
                      "errors": report["errors"], "confirmatory_eligible": False}, sort_keys=True))
    return int(report["status"] != "matched_core_on_two_pinned_private_bases_unqualified")


if __name__ == "__main__":
    raise SystemExit(main())
