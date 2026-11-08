"""Strict exploratory point summary; not an equal-work benchmark result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from analysis import guarded_exploratory_ratio
from inspect_run import InspectionError, inspect_run


def summarize_run(directory: Path) -> dict[str, Any]:
    """Inspect once and summarize all arms, or block without discarding any pair."""
    observations: list[dict[str, Any]] = []
    inspection = inspect_run(directory, _observations=observations)
    blockers = []
    samples = []
    if inspection["recorded_interval_order"] != "nonoverlapping":
        blockers.append({"block": None, "arm": None, "reasons": ["recorded_interval_order_incomplete"]})
    for observation in observations:
        result, guard = observation["result"], observation["guard"]
        reasons = []
        if result.get("status") != "exited_unqualified":
            reasons.append("measurement_not_completed")
        if guard is None:
            reasons.append("guard_not_requested")
        elif not guard["matched_expected_observations"]:
            reasons.append("guard_mismatch")
        if type(result.get("elapsed_ns")) is not int or result["elapsed_ns"] <= 0:
            reasons.append("missing_positive_elapsed_time")
        capture = result.get("raw_capture")
        if capture is not None and any(capture[stream]["truncated"] for stream in ("stdout", "stderr")):
            reasons.append("raw_capture_truncated")
        if reasons:
            blockers.append({"block": observation["block"], "arm": observation["arm"],
                             "reasons": reasons})
        else:
            samples.append({"block": observation["block"], "arm": observation["arm"],
                            "status": "guard_matched_unqualified", "elapsed_ns": result["elapsed_ns"]})
    summary: dict[str, Any] = {
        "mode": "exploratory_unqualified", "confirmatory_eligible": False,
        "blocks": inspection["blocks"], "arm_status_counts": inspection["arm_status_counts"],
        "observation_guard_counts": inspection["observation_guard_counts"],
        "recorded_interval_order": inspection["recorded_interval_order"],
        "blockers": blockers,
        "limitations": ["sentinel matches do not prove equal work", "records are not authenticated",
                        "source and environment are not qualified", "no uncertainty interval or release claim"],
    }
    if blockers:
        summary["status"] = "blocked"
        summary["ratio"] = None
    else:
        summary["status"] = "exploratory_point_estimate"
        summary["ratio_direction"] = "baseline_over_candidate"
        summary["ratio"] = guarded_exploratory_ratio(samples)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = summarize_run(args.directory)
    except (InspectionError, ValueError, OSError) as exc:
        print(f"summarize-run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "exploratory_point_estimate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
