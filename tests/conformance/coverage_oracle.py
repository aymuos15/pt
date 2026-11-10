"""Independent coverage-data set comparison for explicitly instrumented WP03 controls."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile

import coverage

from artifact_oracle import read_file, relative_path


VERSION = "7.17.2"
MAX_FILES = 256
MAX_ENTRIES = 250000


class CoverageError(ValueError):
    pass


def _strict_object(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise CoverageError("duplicate coverage runtime key")
        result[key] = value
    return result


def read_coverage(directory, *, data_name, runtime_name, source_root, sources, branch, contexts, effective_core):
    """Copy a bounded data file before reading it; map only the declared source root."""
    if coverage.__version__ != VERSION:
        raise CoverageError("coverage reader version differs from its pinned contract")
    if (type(sources) is not dict or not 1 <= len(sources) <= MAX_FILES or type(branch) is not bool
            or type(contexts) not in (tuple, list) or any(type(context) is not str for context in contexts)
            or len(set(contexts)) != len(contexts) or effective_core not in ("CTracer", "PyTracer", "SysMonitor")):
        raise CoverageError("invalid bounded source/coverage policy")
    root = Path(source_root).resolve(strict=True)
    source_hashes = {}
    for name, digest in sources.items():
        relative_path(name)
        raw = read_file(root, name)
        actual = hashlib.sha256(raw).hexdigest()
        if type(digest) is not str or actual != digest:
            raise CoverageError("coverage source differs from its declared bytes")
        source_hashes[name] = actual
    runtime_raw = read_file(directory, runtime_name)
    try:
        runtime = json.loads(runtime_raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CoverageError("invalid coverage runtime observation") from exc
    expected = {"version": VERSION, "branch": branch, "effective_core": effective_core}
    if type(runtime) is not dict or runtime != expected or type(runtime.get("branch")) is not bool:
        raise CoverageError("observed coverage version, branch policy or effective tracer differs")
    raw = read_file(directory, data_name)
    with tempfile.TemporaryDirectory(prefix="pt-coverage-oracle-") as temporary:
        snapshot = Path(temporary) / "data"
        snapshot.write_bytes(raw)
        data = coverage.CoverageData(basename=str(snapshot))
        try:
            data.read()
            measured = sorted(data.measured_files())
            actual_contexts = sorted(data.measured_contexts())
            if data.has_arcs() is not branch or len(measured) > MAX_FILES or len(actual_contexts) > MAX_FILES:
                raise CoverageError("coverage line/branch mode or file/context bound differs")
            files, entries = {}, 0
            for filename in measured:
                path = Path(filename)
                if not path.is_absolute() or not path.is_relative_to(root):
                    raise CoverageError("measured coverage path is outside the explicit source-root mapping")
                name = path.relative_to(root).as_posix()
                relative_path(name)
                if name not in sources or name in files or path != root / PurePosixPath(name):
                    raise CoverageError("undeclared, duplicate or noncanonical measured source path")
                lines = sorted(data.lines(filename) or [])
                arcs = sorted([list(arc) for arc in data.arcs(filename) or []]) if branch else None
                by_line = {str(line): sorted(values) for line, values in sorted(data.contexts_by_lineno(filename).items())}
                entries += len(lines) + (len(arcs) if arcs is not None else 0) + sum(len(values) for values in by_line.values())
                if entries > MAX_ENTRIES:
                    raise CoverageError("coverage set entries exceed the aggregate bound")
                if any(type(line) is not int or line <= 0 for line in lines):
                    raise CoverageError("invalid measured coverage line")
                files[name] = {"source_sha256": source_hashes[name], "lines": lines, "arcs": arcs, "contexts_by_line": by_line}
        except coverage.CoverageException as exc:
            raise CoverageError("unreadable coverage database") from exc
    return {"runtime": runtime, "files": files, "contexts": actual_contexts,
            "missing_required_files": sorted(set(sources) - set(files)),
            "missing_required_contexts": sorted(set(contexts) - set(actual_contexts)),
            "extra_contexts": sorted(set(actual_contexts) - set(contexts)),
            "data_sha256": hashlib.sha256(raw).hexdigest(), "runtime_sha256": hashlib.sha256(runtime_raw).hexdigest(),
            "confirmatory_eligible": False}


def compare_coverage(baseline, candidate):
    keys = ("runtime", "files", "contexts", "missing_required_files", "missing_required_contexts", "extra_contexts")
    differences = [key for key in keys if baseline[key] != candidate[key]]
    if any(value[key] for value in (baseline, candidate) for key in ("missing_required_files", "missing_required_contexts", "extra_contexts")):
        differences.append("required_coverage_policy")
    return {"status": "mismatch" if differences else "matched_declared_coverage_sets", "differences": differences,
            "baseline_data_sha256": baseline["data_sha256"], "candidate_data_sha256": candidate["data_sha256"],
            "limitations": ["finite instrumented coverage-data check, not pytest-cov/subprocess integration qualification",
                            "only the explicit source root is mapped; source bytes, file names, lines, arcs and contexts remain exact",
                            "effective tracer is a separate test-owned runtime observation, not an authenticated producer or generation proof"],
            "confirmatory_eligible": False}
