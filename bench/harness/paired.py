"""Run exploratory paired commands; this is not a confirmatory campaign."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from pt_bench import measure, write_record
from schedule import paired_schedule
from metadata import collect_metadata


class RunAbortedError(RuntimeError):
    """Further arms must not run after cleanup becomes visibly uncertain."""


def _command(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
        raise ValueError("each command must be a nonempty array of strings")
    if not value[0]:
        raise ValueError("command executable cannot be empty")
    return value.copy()


def _cleanup_uncertain(result: dict[str, Any] | None) -> bool:
    return (result is not None and result.get("status") in ("exited_unqualified", "timeout")
            and (result.get("process_reaped") is not True
                 or result.get("output_complete") is not True))


def _successful(result: dict[str, Any]) -> bool:
    return (result.get("status") == "exited_unqualified" and result.get("returncode") == 0
            and result.get("output_complete") is True and result.get("process_reaped") is True)


def run_pairs(output: Path, cwd: Path, baseline: list[str], candidate: list[str],
              blocks: int, seed: int, timeout: float, *,
              baseline_prepare: list[str] | None = None,
              candidate_prepare: list[str] | None = None,
              baseline_probe: list[str] | None = None,
              candidate_probe: list[str] | None = None,
              capture_raw: bool = False, raw_limit_bytes: int = 10 * 1024 * 1024) -> None:
    """Run both arms in each ordered block and publish unqualified observations.

    The output directory must not already exist. Optional preparation is timed
    separately and is not proof of reset, state equivalence, or qualification.
    """
    baseline = _command(baseline)
    candidate = _command(candidate)
    preparations = {
        "baseline": _command(baseline_prepare) if baseline_prepare is not None else None,
        "candidate": _command(candidate_prepare) if candidate_prepare is not None else None,
    }
    probes = {
        "baseline": _command(baseline_probe) if baseline_probe is not None else None,
        "candidate": _command(candidate_probe) if candidate_probe is not None else None,
    }
    schedule = paired_schedule(blocks, seed)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if type(capture_raw) is not bool:
        raise ValueError("capture_raw must be a boolean")
    if capture_raw and (os.name != "posix" or not hasattr(os, "O_NOFOLLOW")):
        raise ValueError("raw output capture requires safe POSIX blob lookup")
    if type(raw_limit_bytes) is not int or raw_limit_bytes < 0:
        raise ValueError("raw output limit must be a nonnegative integer")
    cwd = cwd.resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("cwd must be a directory")
    output.mkdir()  # Exclusive: never write into an existing campaign directory.
    bundle = output / "blobs" if capture_raw else None
    if bundle is not None:
        bundle.mkdir()
    plan = {
        "schema_version": 1, "mode": "exploratory_unqualified", "seed": seed,
        "cwd": str(cwd), "timeout_seconds": timeout, "schedule": schedule,
        "baseline_argv": baseline, "candidate_argv": candidate,
        "preparation_argv": preparations,
        "state_probe_argv": probes,
        "host_metadata": collect_metadata(),
        "limitations": ["state not verified", "no work validation", "no confirmatory eligibility"],
    }
    if capture_raw:
        plan["raw_capture"] = {"enabled": True, "limit_per_stream_bytes": raw_limit_bytes,
                               "bundle_directory": "blobs"}
    write_record(str(output / "schedule.json"), plan)

    def measure_stage(command):
        return measure(command, str(cwd), timeout, raw_bundle=bundle, raw_limit_bytes=raw_limit_bytes)

    commands = {"baseline": baseline, "candidate": candidate}
    for block in schedule:
        for position, arm in enumerate(block["order"], 1):
            preparation = None
            probe = None
            try:
                if preparations[arm] is not None:
                    preparation = measure_stage(preparations[arm])
                    write_record(str(output / f"preparation-{block['block']:06d}-{arm}.json"), {
                        "schema_version": 1, "mode": "exploratory_unqualified",
                        "block": block["block"], "position": position, "arm": arm,
                        "result": preparation,
                    })
                preparation_ok = preparation is None or _successful(preparation)
                if preparation_ok and probes[arm] is not None:
                    probe = measure_stage(probes[arm])
                    write_record(str(output / f"probe-{block['block']:06d}-{arm}.json"), {
                        "schema_version": 1, "mode": "exploratory_unqualified",
                        "block": block["block"], "position": position, "arm": arm,
                        "result": probe,
                    })
                if not preparation_ok:
                    result = {"status": "not_run_preparation_failed"}
                elif probe is not None and not _successful(probe):
                    result = {"status": "not_run_probe_failed"}
                else:
                    result = measure_stage(commands[arm])
            except (OSError, ValueError) as exc:
                # Preserve the interruption and stop rather than silently resume
                # after an unexpected harness failure.
                write_record(str(output / f"block-{block['block']:06d}-{arm}.json"), {
                    "schema_version": 1, "mode": "exploratory_unqualified",
                    "block": block["block"], "position": position, "arm": arm,
                    "result": {"status": "harness_error", "error": str(exc)},
                })
                raise
            write_record(str(output / f"block-{block['block']:06d}-{arm}.json"), {
                "schema_version": 1, "mode": "exploratory_unqualified",
                "block": block["block"], "position": position, "arm": arm,
                "preparation": "not_requested" if preparation is None else "recorded",
                "state_probe": ("not_requested" if probes[arm] is None else
                                "recorded" if probe is not None else "skipped_preparation_failed"),
                "result": result,
            })
            if any(_cleanup_uncertain(item) for item in (preparation, probe, result)):
                raise RunAbortedError(
                    f"block {block['block']} {arm}: cleanup uncertain; remaining arms not run"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--baseline-json", required=True, help="command argv as a JSON array")
    parser.add_argument("--candidate-json", required=True, help="command argv as a JSON array")
    parser.add_argument("--baseline-prepare-json", help="optional preparation argv as JSON")
    parser.add_argument("--candidate-prepare-json", help="optional preparation argv as JSON")
    parser.add_argument("--baseline-probe-json", help="optional state-probe argv as JSON")
    parser.add_argument("--candidate-probe-json", help="optional state-probe argv as JSON")
    parser.add_argument("--capture-raw", action="store_true", help="retain bounded raw output; may contain secrets")
    parser.add_argument("--raw-limit-bytes", type=int, default=10 * 1024 * 1024,
                        help="maximum captured prefix per stream (default: 10 MiB)")
    parser.add_argument("--blocks", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    args = parser.parse_args()
    try:
        run_pairs(args.output, args.cwd, json.loads(args.baseline_json),
                  json.loads(args.candidate_json), args.blocks, args.seed, args.timeout,
                  baseline_prepare=(_command(json.loads(args.baseline_prepare_json))
                                    if args.baseline_prepare_json is not None else None),
                  candidate_prepare=(_command(json.loads(args.candidate_prepare_json))
                                     if args.candidate_prepare_json is not None else None),
                  baseline_probe=(_command(json.loads(args.baseline_probe_json))
                                  if args.baseline_probe_json is not None else None),
                  candidate_probe=(_command(json.loads(args.candidate_probe_json))
                                   if args.candidate_probe_json is not None else None),
                  capture_raw=args.capture_raw, raw_limit_bytes=args.raw_limit_bytes)
    except (ValueError, OSError, RunAbortedError) as exc:
        parser.exit(2, f"paired: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
