"""Independent exploratory command timer; not a confirmatory benchmark harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from raw_capture import RawCapture


def _abort_process(process: subprocess.Popen) -> None:
    """Best-effort termination after an unexpected harness error or interrupt."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except OSError:
        # Preserve the original exception; process ownership is unverified.
        pass
    for pipe in (process.stdout, process.stderr):
        if pipe is not None and not pipe.closed:
            try:
                pipe.close()
            except OSError:
                pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        # Do not hang indefinitely or pretend that cleanup succeeded.
        pass


def _stream_posix(process: subprocess.Popen, timeout: float,
                  capture: RawCapture | None = None) -> dict[str, Any]:
    """Drain both pipes without retaining output, with bounded timeout cleanup."""
    deadline = time.monotonic() + timeout
    cleanup_deadline = None
    timed_out = False
    complete = True
    digests = {name: hashlib.sha256() for name in ("stdout", "stderr")}
    sizes = {name: 0 for name in digests}
    with selectors.DefaultSelector() as selector:
        for name in digests:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        try:
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if not timed_out and now >= deadline:
                    timed_out = True
                    cleanup_deadline = now + 1.0
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if timed_out and now >= cleanup_deadline:
                    complete = False
                    break
                limit = cleanup_deadline if timed_out else deadline
                if not selector.get_map():
                    try:
                        process.wait(timeout=max(0, limit - now))
                    except subprocess.TimeoutExpired:
                        pass
                    continue
                for key, _ in selector.select(timeout=max(0, limit - now)):
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    else:
                        digests[key.data].update(chunk)
                        sizes[key.data] += len(chunk)
                        if capture is not None:
                            capture.write(key.data, chunk)
        finally:
            for key in list(selector.get_map().values()):
                selector.unregister(key.fileobj)
                key.fileobj.close()
        # Even when descendant-held pipes outlive the deadline, reap the leader
        # if it has exited; a closed pipe is not itself proof of process exit.
        process.poll()
    return {
        "timed_out": timed_out, "output_complete": complete,
        "process_reaped": process.returncode is not None,
        "stdout_bytes": sizes["stdout"], "stderr_bytes": sizes["stderr"],
        "stdout_sha256": digests["stdout"].hexdigest(),
        "stderr_sha256": digests["stderr"].hexdigest(),
    }


def _timing(start: int) -> dict[str, Any]:
    end = time.monotonic_ns()
    return {"monotonic_start_ns": start, "monotonic_end_ns": end,
            "clock_domain": "harness_process_monotonic", "elapsed_ns": end - start}


def measure(argv: Sequence[str], cwd: str, timeout: float, *,
            raw_bundle: Path | None = None, raw_limit_bytes: int = 10 * 1024 * 1024) -> dict[str, Any]:
    """Time launch through leader/pipe completion and optional raw finalization.

    Argument/cwd checks precede the clock; sample-record publication follows it.
    This interval does not prove all descendants or required resources are gone,
    or that the command completed any expected test work or artifact contract.
    """
    if not argv or not all(isinstance(arg, str) for arg in argv) or not argv[0]:
        raise ValueError("command must have a nonempty executable and string arguments")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if raw_bundle is not None:
        if os.name != "posix":
            raise ValueError("raw output capture is supported only on POSIX")
        if type(raw_limit_bytes) is not int or raw_limit_bytes < 0:
            raise ValueError("raw output limit must be a nonnegative integer")
        raw_bundle = Path(raw_bundle)
        if not raw_bundle.is_dir():
            raise ValueError("raw output bundle must be an existing directory")
    cwd_path = Path(cwd).resolve(strict=True)
    if not cwd_path.is_dir():
        raise ValueError("cwd must be a directory")

    start = time.monotonic_ns()
    try:
        process = subprocess.Popen(
            list(argv), cwd=cwd_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return {
            "status": "launch_error", "error": str(exc), "argv": list(argv),
            "cwd": str(cwd_path), **_timing(start),
        }

    execution_reaped = False
    try:
        if os.name == "posix":
            if raw_bundle is None:
                output = _stream_posix(process, timeout)
                execution_reaped = output["process_reaped"]
            else:
                from raw_capture import RawCapture
                with RawCapture(raw_bundle, raw_limit_bytes) as capture:
                    output = _stream_posix(process, timeout, capture)
                    execution_reaped = output["process_reaped"]
                    output["raw_capture"] = capture.publish()
        else:
            # The original prototype path does not provide bounded memory or
            # process-tree cleanup on non-POSIX systems.
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
            output = {
                "timed_out": timed_out, "output_complete": True,
                "process_reaped": process.returncode is not None,
                "stdout_bytes": len(stdout), "stderr_bytes": len(stderr),
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            }
            execution_reaped = output["process_reaped"]
    except BaseException:
        if not execution_reaped:
            _abort_process(process)
        raise

    return {
        "status": "timeout" if output.pop("timed_out") else "exited_unqualified",
        "argv": list(argv), "cwd": str(cwd_path),
        **_timing(start),
        "returncode": process.returncode,
        **output,
    }


def write_record(path: str, record: dict[str, Any]) -> None:
    """Publish a complete record without replacing an existing destination.

    The temporary file is on the destination filesystem so a hard link can
    atomically publish it. A crash may leave a hidden temporary file, but never
    exposes it as the destination before serialization and file synchronization.
    Filesystems without hard-link support fail closed rather than overwriting.
    This does not promise persistence across a power loss (no directory fsync).
    """
    destination = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{destination.name}.",
            suffix=".tmp", dir=destination.parent, delete=False,
        ) as output:
            temp_path = Path(output.name)
            json.dump(record, output, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


COMMAND_ENDPOINT = "process_launch_through_exit_pipes_and_optional_raw_finalization_v1"
LIFECYCLE_ENDPOINT = "invocation_through_sample_publication_and_declared_finalization_v1"
LIFECYCLE_LIMITATIONS = [
    "post-commit receipt serialization and transport are outside the measured endpoint",
    "undeclared work, resources and artifacts are not verified",
    "no semantic, generation, descendant-containment or power-loss-durability qualification",
    "caller-owned paths; observations are not an authenticated atomic snapshot",
]


def _same_json(left: Any, right: Any) -> bool:
    """JSON types matter: Python's True == 1 must not validate raw evidence."""
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("non-JSON lifecycle evidence") from exc


def measure_and_publish(argv: Sequence[str], cwd: str, timeout: float, output: Path, *,
                        required_finalization: dict[str, Any] | None = None,
                        raw_bundle: Path | None = None,
                        raw_limit_bytes: int = 10 * 1024 * 1024,
                        context: dict[str, Any] | None = None,
                        guard_expectations: dict[str, Any] | None = None,
                        archive_bundle: Path | None = None) -> dict[str, Any]:
    """Return a post-commit receipt; its transport is outside the subject clock.

    The immutable sample deliberately contains no post-publication timestamp or
    claim of lifecycle success. A successful receipt requires read-back of the
    exact sample bytes and unchanged declared evidence across publication. The
    old result.elapsed_ns remains the narrower command observation interval.
    """
    start = time.monotonic_ns()
    from finalization import (
        MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, check, inspect_file, require_safe_lookup, requirements,
    )
    require_safe_lookup()
    contract = requirements(required_finalization)
    extended = context is not None or guard_expectations is not None or archive_bundle is not None
    if extended:
        from evidence import validate_context, validate_v2
        validate_context(context)
    if context is not None:
        context = json.loads(json.dumps(context, allow_nan=False))
    if guard_expectations is not None:
        from guards import validate_expectations
        guard_expectations = validate_expectations(guard_expectations)
    output = Path(os.path.abspath(output))
    root = Path(os.path.abspath(cwd))
    # Reject obvious invalid destinations before executing work; exclusive
    # publication is still authoritative if another caller races this check.
    for directory in (root, output.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(fd)
    if os.path.lexists(output):
        raise FileExistsError(f"sample destination already exists: {output}")
    if raw_bundle is not None:
        raw_bundle = Path(os.path.abspath(raw_bundle))
    if archive_bundle is not None:
        archive_bundle = Path(os.path.abspath(archive_bundle))
    errors = []
    result = None
    sample = None
    published_identity = None
    initial = None
    final = None
    archived = None
    guard = None
    try:
        result = measure(argv, str(root), timeout, raw_bundle=raw_bundle, raw_limit_bytes=raw_limit_bytes)
    except (OSError, ValueError) as exc:
        errors.append({"stage": "measurement", "error": str(exc)})
    if result is not None:
        initial = check(result, root, contract, raw_bundle)
        if guard_expectations is not None:
            from guards import check_observation
            guard = check_observation(result, **guard_expectations)
        if archive_bundle is not None:
            from finalization import archive
            archived = archive(root, initial, archive_bundle)
            if archived["errors"]:
                errors.append({"stage": "artifact_archive", "error": "required artifact archival failed"})
        record = {"schema_version": 2 if extended else 1, "mode": "exploratory", "result": result,
                  "required_finalization": {"requirements": contract, "observed": initial}}
        if extended:
            record.update(context=context, guard_expectations=guard_expectations,
                          observation_guard=guard, artifact_archive=archived)
        try:
            if extended:
                validate_v2("sample", record)
            expected = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
            if len(expected) > MAX_RECORD_BYTES:
                raise ValueError("sample exceeds lifecycle record byte limit")
            write_record(str(output), record)
            observed, _ = inspect_file(output.parent, output.name, limit=len(expected))
            digest = hashlib.sha256(expected).hexdigest()
            if observed["bytes"] != len(expected) or observed["sha256"] != digest:
                raise ValueError("published sample does not match serialized observation")
            sample = {"name": output.name, "bytes": observed["bytes"], "sha256": digest}
            published_identity = observed
        except (OSError, ValueError) as exc:
            errors.append({"stage": "sample_publication", "error": str(exc)})
        # Do not accept artifacts/absence checks that changed while a slow
        # sample writer ran, even if the process and pre-publication check passed.
        final = check(result, root, contract, raw_bundle)
        if initial != final:
            errors.append({"stage": "required_finalization", "error": "declared evidence changed across sample publication"})
        if sample is not None:
            try:
                last, _ = inspect_file(output.parent, output.name, limit=sample["bytes"])
                if last != published_identity:
                    raise ValueError("sample changed during post-publication finalization")
            except (OSError, ValueError) as exc:
                errors.append({"stage": "sample_publication", "error": str(exc)})
    finalized = (not errors and sample is not None and initial is not None
                 and initial["matched"] and final["matched"])
    receipt = {
        "schema_version": 2 if extended else 1, "mode": "exploratory_unqualified", "confirmatory_eligible": False,
        "lifecycle": {"endpoint": LIFECYCLE_ENDPOINT,
                      "status": "finalized_unqualified" if finalized else "finalization_failed",
                      **_timing(start)},
        "result": result, "sample": sample, "cwd": str(root),
        "raw_bundle": str(raw_bundle) if raw_bundle is not None else None,
        "required_finalization": {"requirements": contract, "before_publication": initial,
                                  "after_publication": final},
        "errors": errors,
        "limitations": LIFECYCLE_LIMITATIONS.copy(),
    }
    if extended:
        receipt.update(context=context, guard_expectations=guard_expectations,
                       observation_guard=guard, artifact_archive=archived)
        validate_v2("receipt", receipt)
    if len(json.dumps(receipt, sort_keys=True, allow_nan=False).encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("lifecycle receipt exceeds byte limit; sample alone is unconfirmed")
    return receipt


def inspect_lifecycle(output: Path, receipt: dict[str, Any], *, archived_bundle: Path | None = None) -> dict[str, Any]:
    """Check a receipt/sample pair without authenticating it or qualifying work."""
    from finalization import check, read_json, requirements

    fields = {"schema_version", "mode", "confirmatory_eligible", "lifecycle", "result", "sample",
              "cwd", "raw_bundle", "required_finalization", "errors", "limitations"}
    extended = isinstance(receipt, dict) and type(receipt.get("schema_version")) is int and receipt["schema_version"] == 2
    if extended:
        from evidence import validate_v2
        validate_v2("receipt", receipt)
        fields |= {"context", "guard_expectations", "observation_guard", "artifact_archive"}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] not in (1, 2)
            or receipt["mode"] != "exploratory_unqualified" or receipt["confirmatory_eligible"] is not False
            or receipt["limitations"] != LIFECYCLE_LIMITATIONS):
        raise ValueError("invalid lifecycle receipt envelope")
    lifecycle = receipt["lifecycle"]
    if (not isinstance(lifecycle, dict)
            or set(lifecycle) != {"endpoint", "status", "monotonic_start_ns", "monotonic_end_ns", "elapsed_ns", "clock_domain"}
            or lifecycle["endpoint"] != LIFECYCLE_ENDPOINT
            or lifecycle["status"] not in ("finalized_unqualified", "finalization_failed")):
        raise ValueError("invalid lifecycle endpoint or status")

    def interval(value):
        if (not isinstance(value, dict) or any(type(value.get(name)) is not int for name in
                                             ("monotonic_start_ns", "monotonic_end_ns", "elapsed_ns"))
                or value.get("clock_domain") != "harness_process_monotonic"
                or value["monotonic_end_ns"] < value["monotonic_start_ns"]
                or value["elapsed_ns"] != value["monotonic_end_ns"] - value["monotonic_start_ns"]):
            raise ValueError("inconsistent lifecycle/command interval")

    interval(lifecycle)
    errors = receipt["errors"]
    if (not isinstance(errors, list) or any(not isinstance(item, dict) or set(item) != {"stage", "error"}
            or item["stage"] not in ("measurement", "sample_publication", "required_finalization", "artifact_archive")
            or not isinstance(item["error"], str) or not item["error"] for item in errors)):
        raise ValueError("invalid lifecycle error evidence")
    evidence = receipt["required_finalization"]
    if not isinstance(evidence, dict) or set(evidence) != {"requirements", "before_publication", "after_publication"}:
        raise ValueError("invalid required-finalization evidence")
    contract = requirements(evidence["requirements"])
    if not _same_json(contract, evidence["requirements"]):
        raise ValueError("noncanonical required-finalization contract")
    result = receipt["result"]
    sample = receipt["sample"]
    if result is not None and not isinstance(result, dict):
        raise ValueError("invalid lifecycle command observation")
    if result is None and (sample is not None or evidence["before_publication"] is not None
                           or evidence["after_publication"] is not None
                           or not any(item["stage"] == "measurement" for item in errors)):
        raise ValueError("missing measurement failure evidence")
    if result is not None:
        if (result.get("status") not in ("exited_unqualified", "timeout", "launch_error")
                or any(item["stage"] == "measurement" for item in errors)):
            raise ValueError("invalid lifecycle measurement status or failure evidence")
        if sample is None and not any(item["stage"] == "sample_publication" for item in errors):
            raise ValueError("missing sample-publication failure evidence")
        interval(result)
        if (result["monotonic_start_ns"] < lifecycle["monotonic_start_ns"]
                or result["monotonic_end_ns"] > lifecycle["monotonic_end_ns"]):
            raise ValueError("command is outside lifecycle interval")
    if not isinstance(receipt["cwd"], str) or not Path(receipt["cwd"]).is_absolute():
        raise ValueError("invalid lifecycle cwd")
    raw = receipt["raw_bundle"]
    if raw is not None and (not isinstance(raw, str) or not Path(raw).is_absolute()):
        raise ValueError("invalid lifecycle raw bundle")
    if extended and result is not None:
        from finalization import validate_observed
        if result["cwd"] != receipt["cwd"]:
            raise ValueError("command cwd differs from lifecycle receipt")
        before, after = evidence["before_publication"], evidence["after_publication"]
        for observed in (before, after):
            validate_observed(result, contract, observed, capture_raw=raw is not None)
        if (not _same_json(before, after)) != any(item["stage"] == "required_finalization" for item in errors):
            raise ValueError("changed finalization observations conflict with error evidence")
    expected_record = {"schema_version": 2 if extended else 1, "mode": "exploratory", "result": result,
                       "required_finalization": {"requirements": contract, "observed": evidence["before_publication"]}}
    if extended:
        if receipt["context"] is not None and not isinstance(receipt["context"], dict):
            raise ValueError("invalid lifecycle context")
        archive_value = receipt["artifact_archive"]
        if archive_value is not None and (not isinstance(archive_value, dict)
                or set(archive_value) != {"bundle", "artifacts", "errors"}
                or not isinstance(archive_value["bundle"], str)
                or not Path(archive_value["bundle"]).is_absolute()):
            raise ValueError("invalid artifact-archive evidence")
        from guards import check_observation, validate_expectations
        expectation = receipt["guard_expectations"]
        guard = (check_observation(result, **validate_expectations(expectation))
                 if expectation is not None and result is not None else None)
        if not _same_json(guard, receipt["observation_guard"]):
            raise ValueError("observation guard differs from lifecycle result")
        if bool(archive_value and archive_value["errors"]) != any(item["stage"] == "artifact_archive" for item in errors):
            raise ValueError("artifact archival conflicts with error evidence")
        expected_record.update({key: receipt[key] for key in
                                ("context", "guard_expectations", "observation_guard", "artifact_archive")})
    if sample is not None:
        record, observed = read_json(output)
        if extended:
            validate_v2("sample", record)
        if (not isinstance(sample, dict) or set(sample) != {"name", "bytes", "sha256"}
                or type(sample["bytes"]) is not int or sample["name"] != output.name
                or sample["bytes"] != observed["bytes"] or sample["sha256"] != observed["sha256"]
                or not _same_json(record, expected_record)):
            raise ValueError("sample does not match lifecycle receipt")
    matched = False
    if result is not None:
        historical = None
        if extended and receipt["artifact_archive"] is not None:
            from finalization import archived_check
            archive_root = archived_bundle if archived_bundle is not None else Path(receipt["artifact_archive"]["bundle"])
            historical = archived_check(result, contract, evidence["before_publication"],
                                        receipt["artifact_archive"], archive_root, capture_raw=raw is not None)
            if not _same_json(historical, evidence["before_publication"]):
                raise ValueError("historical finalization evidence contradicts retained bytes or checks")
        if archived_bundle is not None:
            if historical is None:
                raise ValueError("historical inspection requires archived evidence")
            current = historical
        else:
            current = check(result, Path(receipt["cwd"]), contract, Path(raw) if raw is not None else None)
        matched = (current["matched"] and _same_json(current, evidence["after_publication"])
                   and _same_json(current, evidence["before_publication"]))
        if historical is not None:
            matched = matched and _same_json(historical, evidence["before_publication"])
    finalized = not errors and sample is not None and matched
    if extended and receipt["artifact_archive"] is not None:
        if receipt["artifact_archive"].get("errors"):
            finalized = False
    if (lifecycle["status"] == "finalized_unqualified") != finalized:
        raise ValueError("lifecycle status conflicts with publication or required-finalization evidence")
    return {"receipt_consistency": "checked_unqualified", "lifecycle_finalized": finalized,
            "endpoint": LIFECYCLE_ENDPOINT, "elapsed_ns": lifecycle["elapsed_ns"],
            "confirmatory_eligible": False,
            "limitations": ["records are not authenticated", "only declared finalization evidence checked",
                            "no test-work, generation or descendant-containment qualification"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--output", required=True, help="new JSON file; never overwritten")
    parser.add_argument("--raw-output-bundle", type=Path, help="optional existing blob directory; may contain secrets")
    parser.add_argument("--raw-limit-bytes", type=int, default=10 * 1024 * 1024,
                         help="maximum captured prefix per stream (default: 10 MiB)")
    parser.add_argument("--finalization-json", help="explicit expected exit, artifact digests and absent paths")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not argv:
        parser.error("a command is required after --")
    try:
        from finalization import parse_json
        receipt = measure_and_publish(
            argv, args.cwd, args.timeout, Path(args.output), raw_bundle=args.raw_output_bundle,
            raw_limit_bytes=args.raw_limit_bytes,
            required_finalization=parse_json(args.finalization_json) if args.finalization_json is not None else None,
        )
        # The endpoint includes sample publication, not transport of its own
        # post-commit measurement receipt. A missing receipt cannot certify it.
        print(json.dumps(receipt, sort_keys=True, allow_nan=False), flush=True)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"pt-bench: {exc}\n")
    if receipt["errors"]:
        return 2
    return 0 if receipt["lifecycle"]["status"] == "finalized_unqualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
