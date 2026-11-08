"""Run exploratory paired commands; this is not a confirmatory campaign."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from pt_bench import measure, write_record
from schedule import paired_schedule


def _command(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
        raise ValueError("each command must be a nonempty array of strings")
    if not value[0]:
        raise ValueError("command executable cannot be empty")
    return value.copy()


def run_pairs(output: Path, cwd: Path, baseline: list[str], candidate: list[str],
              blocks: int, seed: int, timeout: float, *,
              baseline_prepare: list[str] | None = None,
              candidate_prepare: list[str] | None = None) -> None:
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
    schedule = paired_schedule(blocks, seed)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    cwd = cwd.resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("cwd must be a directory")
    output.mkdir()  # Exclusive: never write into an existing campaign directory.
    write_record(str(output / "schedule.json"), {
        "schema_version": 1, "mode": "exploratory_unqualified", "seed": seed,
        "cwd": str(cwd), "timeout_seconds": timeout, "schedule": schedule,
        "baseline_argv": baseline, "candidate_argv": candidate,
        "preparation_argv": preparations,
        "limitations": ["state not verified", "no work validation", "no confirmatory eligibility"],
    })
    commands = {"baseline": baseline, "candidate": candidate}
    for block in schedule:
        for position, arm in enumerate(block["order"], 1):
            preparation = None
            try:
                if preparations[arm] is not None:
                    preparation = measure(preparations[arm], str(cwd), timeout)
                    write_record(str(output / f"preparation-{block['block']:06d}-{arm}.json"), {
                        "schema_version": 1, "mode": "exploratory_unqualified",
                        "block": block["block"], "position": position, "arm": arm,
                        "result": preparation,
                    })
                preparation_ok = preparation is None or (
                    preparation["status"] == "exited_unqualified"
                    and preparation["returncode"] == 0
                    and preparation["output_complete"]
                    and preparation["process_reaped"]
                )
                result = (measure(commands[arm], str(cwd), timeout) if preparation_ok
                          else {"status": "not_run_preparation_failed"})
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
                "result": result,
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--baseline-json", required=True, help="command argv as a JSON array")
    parser.add_argument("--candidate-json", required=True, help="command argv as a JSON array")
    parser.add_argument("--baseline-prepare-json", help="optional preparation argv as JSON")
    parser.add_argument("--candidate-prepare-json", help="optional preparation argv as JSON")
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
                                     if args.candidate_prepare_json is not None else None))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"paired: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
