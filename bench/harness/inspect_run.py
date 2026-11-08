"""Check exploratory paired-run record consistency, not benchmark validity."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

import jsonschema

from artifact_check import _digest_status
from schedule import paired_schedule

MAX_RECORD_BYTES = 1024 * 1024
SAMPLE_SCHEMA_PATH = Path(__file__).resolve().parent / "sample.schema.json"


class InspectionError(ValueError):
    pass


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InspectionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise InspectionError(f"missing or non-regular record: {path.name}")
        with path.open("rb") as source:
            raw = source.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise InspectionError(f"oversized record: {path.name}")
        value = json.loads(raw, object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               InspectionError("non-finite JSON value")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InspectionError(f"{path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise InspectionError(f"{path.name}: expected JSON object")
    return value


def _envelope(record: dict[str, Any], block: int, position: int, arm: str) -> dict[str, Any]:
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("mode") != "exploratory_unqualified"
            or type(record.get("block")) is not int or record["block"] != block
            or type(record.get("position")) is not int or record["position"] != position
            or record.get("arm") != arm or not isinstance(record.get("result"), dict)):
        raise InspectionError(f"invalid record envelope for block {block} {arm}")
    return record["result"]


def _measurement(result: dict[str, Any], command: Any, cwd: Any) -> None:
    status = result.get("status")
    if status not in ("exited_unqualified", "timeout", "launch_error"):
        raise InspectionError(f"unexpected measurement status: {status}")
    if result.get("argv") != command or result.get("cwd") != cwd:
        raise InspectionError("measurement command or cwd differs from schedule")
    elapsed = result.get("elapsed_ns")
    if type(elapsed) is not int or elapsed < 0:
        raise InspectionError("invalid measurement elapsed_ns")
    clock_fields = ("monotonic_start_ns", "monotonic_end_ns", "clock_domain")
    if any(field in result for field in clock_fields):
        start, end, domain = (result.get(field) for field in clock_fields)
        if (type(start) is not int or type(end) is not int or end < start
                or domain != "harness_process_monotonic" or elapsed != end - start):
            raise InspectionError("inconsistent monotonic timing fields")
    if status == "launch_error":
        if not isinstance(result.get("error"), str):
            raise InspectionError("launch error is missing its cause")
        return
    if type(result.get("output_complete")) is not bool or type(result.get("process_reaped")) is not bool:
        raise InspectionError("measurement missing cleanup status")
    code = result.get("returncode")
    if code is not None and type(code) is not int:
        raise InspectionError("invalid return code")
    if result["process_reaped"] != (code is not None):
        raise InspectionError("process-reaped and return-code fields conflict")
    for stream in ("stdout", "stderr"):
        size = result.get(f"{stream}_bytes")
        digest = result.get(f"{stream}_sha256")
        if type(size) is not int or size < 0:
            raise InspectionError(f"invalid {stream} byte count")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InspectionError(f"invalid {stream} digest")
    if status == "exited_unqualified" and (code is None or not result["process_reaped"]
                                            or not result["output_complete"]):
        raise InspectionError("exited measurement has incomplete cleanup")


def inspect_run(directory: Path) -> dict[str, Any]:
    """Reject missing or inconsistent records; never qualify their contents."""
    schema = _read(SAMPLE_SCHEMA_PATH)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise InspectionError(f"invalid exploratory sample schema: {exc.message}") from exc
    validator = jsonschema.Draft202012Validator(schema)
    plan = _read(directory / "schedule.json")
    schedule, seed, cwd = plan.get("schedule"), plan.get("seed"), plan.get("cwd")
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("mode") != "exploratory_unqualified"
            or not isinstance(schedule, list) or not schedule or type(seed) is not int
            or not isinstance(cwd, str) or not cwd):
        raise InspectionError("invalid schedule envelope")
    if (any(not isinstance(block, dict) or type(block.get("block")) is not int
            for block in schedule) or schedule != paired_schedule(len(schedule), seed)):
        raise InspectionError("schedule order or block numbering is inconsistent")
    commands = {arm: plan.get(f"{arm}_argv") for arm in ("baseline", "candidate")}
    preparations = plan.get("preparation_argv")
    has_probe_configuration = "state_probe_argv" in plan
    probes = plan.get("state_probe_argv", {"baseline": None, "candidate": None})
    if not isinstance(preparations, dict) or set(preparations) != set(commands):
        raise InspectionError("invalid preparation configuration")
    if not isinstance(probes, dict) or set(probes) != set(commands):
        raise InspectionError("invalid state-probe configuration")
    for command in list(commands.values()) + list(preparations.values()) + list(probes.values()):
        if command is not None and (not isinstance(command, list) or not command
                                    or not all(isinstance(arg, str) for arg in command)
                                    or not command[0]):
            raise InspectionError("invalid command in schedule")
    if any(command is None for command in commands.values()):
        raise InspectionError("missing arm command")

    expected = {"schedule.json"}
    raw_plan = plan.get("raw_capture")
    bundle = None
    blob_sizes: dict[str, int] = {}
    if raw_plan is not None:
        if (not isinstance(raw_plan, dict)
                or set(raw_plan) != {"enabled", "limit_per_stream_bytes", "bundle_directory"}
                or raw_plan.get("enabled") is not True or raw_plan.get("bundle_directory") != "blobs"
                or type(raw_plan.get("limit_per_stream_bytes")) is not int
                or raw_plan["limit_per_stream_bytes"] < 0):
            raise InspectionError("invalid raw capture configuration")
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise InspectionError("safe blob inspection unsupported on this platform")
        bundle = directory / "blobs"
        if bundle.is_symlink() or not bundle.is_dir():
            raise InspectionError("missing or unsafe blob directory")
        expected.add("blobs")

    def check_raw(measurement: dict[str, Any]) -> None:
        capture = measurement.get("raw_capture")
        if bundle is None:
            if capture is not None:
                raise InspectionError("raw capture present without schedule configuration")
            return
        if measurement["status"] == "launch_error":
            if capture is not None:
                raise InspectionError("launch error cannot contain raw capture")
            return
        if (not isinstance(capture, dict)
                or set(capture) != {"capture_mode", "limit_per_stream_bytes", "stdout", "stderr"}
                or capture.get("capture_mode") != "bounded_prefix"
                or type(capture.get("limit_per_stream_bytes")) is not int
                or capture["limit_per_stream_bytes"] != raw_plan["limit_per_stream_bytes"]):
            raise InspectionError("invalid raw capture metadata")
        limit = raw_plan["limit_per_stream_bytes"]
        try:
            directory_fd = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise InspectionError("cannot safely open blob directory") from exc
        try:
            for stream in ("stdout", "stderr"):
                item = capture.get(stream)
                if (not isinstance(item, dict)
                        or set(item) != {"sha256", "stored_bytes", "publication", "truncated"}
                        or not isinstance(item.get("sha256"), str)
                        or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
                        or type(item.get("stored_bytes")) is not int
                        or type(item.get("truncated")) is not bool
                        or item.get("publication") not in ("created", "already_present")):
                    raise InspectionError(f"invalid {stream} raw blob metadata")
                size, total, digest = item["stored_bytes"], measurement[f"{stream}_bytes"], item["sha256"]
                if size != min(total, limit) or item["truncated"] != (size < total):
                    raise InspectionError(f"inconsistent {stream} raw capture length")
                if not item["truncated"] and digest != measurement[f"{stream}_sha256"]:
                    raise InspectionError(f"inconsistent {stream} raw capture digest")
                if digest in blob_sizes and blob_sizes[digest] != size:
                    raise InspectionError("same raw digest has inconsistent sizes")
                if digest not in blob_sizes:
                    try:
                        metadata = os.stat(digest, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError as exc:
                        raise InspectionError("missing raw blob") from exc
                    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size
                            or _digest_status(directory_fd, digest) != "matched"):
                        raise InspectionError("raw blob is invalid or does not match its digest")
                    blob_sizes[digest] = size
        finally:
            os.close(directory_fd)

    counts: Counter[str] = Counter()
    last_end = None
    all_intervals_present = True

    def check_interval(measurement: dict[str, Any]) -> None:
        nonlocal last_end, all_intervals_present
        if "monotonic_start_ns" not in measurement:
            # Older records are still readable, but no ordering assertion can
            # cross an interval whose boundaries were not recorded.
            all_intervals_present = False
            last_end = None
            return
        start = measurement["monotonic_start_ns"]
        if last_end is not None and start < last_end:
            raise InspectionError("recorded intervals overlap or are out of scheduled order")
        last_end = measurement["monotonic_end_ns"]

    for block in schedule:
        for position, arm in enumerate(block["order"], 1):
            number = block["block"]
            filename = f"block-{number:06d}-{arm}.json"
            expected.add(filename)
            record = _read(directory / filename)
            schema_error = next(validator.iter_errors(record), None)
            if schema_error is not None:
                raise InspectionError(f"{filename}: sample schema: {schema_error.message}")
            result = _envelope(record, number, position, arm)
            prep_command = preparations[arm]
            prep_ok = True
            if prep_command is not None:
                prep_name = f"preparation-{number:06d}-{arm}.json"
                expected.add(prep_name)
                prep_record = _read(directory / prep_name)
                prep_result = _envelope(prep_record, number, position, arm)
                _measurement(prep_result, prep_command, cwd)
                check_raw(prep_result)
                check_interval(prep_result)
                prep_ok = (prep_result["status"] == "exited_unqualified"
                           and prep_result["returncode"] == 0)
            if record.get("preparation") != ("recorded" if prep_command is not None else "not_requested"):
                raise InspectionError("preparation record reference mismatch")
            probe_command = probes[arm]
            probe_ok = True
            expected_probe_reference = "not_requested"
            if probe_command is not None and not prep_ok:
                expected_probe_reference = "skipped_preparation_failed"
            elif probe_command is not None:
                expected_probe_reference = "recorded"
                probe_name = f"probe-{number:06d}-{arm}.json"
                expected.add(probe_name)
                probe_record = _read(directory / probe_name)
                probe_result = _envelope(probe_record, number, position, arm)
                _measurement(probe_result, probe_command, cwd)
                check_raw(probe_result)
                check_interval(probe_result)
                probe_ok = probe_result["status"] == "exited_unqualified" and probe_result["returncode"] == 0
            if has_probe_configuration or "state_probe" in record:
                if record.get("state_probe") != expected_probe_reference:
                    raise InspectionError("state-probe record reference mismatch")
            if not prep_ok:
                if result.get("status") != "not_run_preparation_failed":
                    raise InspectionError("work ran after unsuccessful preparation")
            elif not probe_ok:
                if result.get("status") != "not_run_probe_failed":
                    raise InspectionError("work ran after unsuccessful state probe")
            else:
                _measurement(result, commands[arm], cwd)
                check_raw(result)
                check_interval(result)
            counts[result["status"]] += 1
    try:
        actual = {path.name for path in directory.iterdir()}
    except OSError as exc:
        raise InspectionError(str(exc)) from exc
    if actual != expected:
        raise InspectionError(f"unexpected or missing files: {sorted(actual ^ expected)}")
    if bundle is not None:
        try:
            actual_blobs = {path.name for path in bundle.iterdir()}
        except OSError as exc:
            raise InspectionError("cannot list blob directory") from exc
        if actual_blobs != set(blob_sizes):
            raise InspectionError("unexpected or missing blob files")
    return {"record_consistency": "complete", "mode": "exploratory_unqualified",
            "blocks": len(schedule), "arm_status_counts": dict(sorted(counts.items())),
            "recorded_interval_order": ("nonoverlapping" if all_intervals_present else "incomplete"),
            "confirmatory_eligible": False,
            "limitations": ["record authenticity not established", "work and reset not validated",
                            "machine and input identities not qualified"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_run(args.directory)
    except (InspectionError, ValueError) as exc:
        print(f"inspect-run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
