"""Strict exploratory point summary; not an equal-work benchmark result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from analysis import guarded_exploratory_bootstrap, guarded_exploratory_ratio
from inspect_run import InspectionError, inspect_run
from pt_bench import LIFECYCLE_ENDPOINT


def summarize_run(directory: Path, *, bootstrap_resamples: int | None = None,
                  bootstrap_seed: int | None = None,
                  _observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Inspect once and summarize all arms, or block without discarding any pair."""
    if (bootstrap_resamples is None) != (bootstrap_seed is None):
        raise ValueError("bootstrap resamples and seed must be specified together")
    if bootstrap_resamples is not None:
        if (type(bootstrap_resamples) is not int or not 2 <= bootstrap_resamples <= 1_000_000
                or type(bootstrap_seed) is not int):
            raise ValueError("bootstrap requires an integer seed and 2 to 1000000 resamples")
    observations: list[dict[str, Any]] = []
    inspection = inspect_run(directory, _observations=observations)
    if _observations is not None:
        _observations.extend(observations)
    if inspection.get("kind") == "paired_managed_replay_campaign":
        from paired_replay import summarize
        return summarize(inspection, observations, bootstrap_resamples=bootstrap_resamples, bootstrap_seed=bootstrap_seed)
    if inspection.get("measurement_layer") == "resource_diagnostic":
        if bootstrap_resamples is not None:
            raise ValueError("bootstrap is unsupported for separate resource diagnostic campaigns")
        from paired_resources import summarize
        return summarize(inspection, observations)
    if bootstrap_resamples is not None and bootstrap_resamples * inspection["blocks"] > 10_000_000:
        raise ValueError("bootstrap exceeds the exploratory computation limit")
    blockers = []
    samples = []
    if inspection["record_consistency"] != "complete":
        blockers.append({"block": None, "arm": None, "reasons": ["run_aborted_or_incomplete"]})
    if inspection["recorded_interval_order"] != "nonoverlapping":
        blockers.append({"block": None, "arm": None, "reasons": ["recorded_interval_order_incomplete"]})
    if bootstrap_resamples is not None and inspection["blocks"] < 2:
        blockers.append({"block": None, "arm": None, "reasons": ["bootstrap_requires_two_blocks"]})
    for observation in observations:
        result, guard = observation["result"], observation["guard"]
        reasons = observation.get("failure_reasons", []).copy()
        timing = result
        if inspection["timing_endpoint"] == LIFECYCLE_ENDPOINT:
            timing = observation.get("timing") or {}
            if not observation.get("lifecycle_finalized"):
                reasons.append("lifecycle_not_finalized")
        if result.get("status") != "exited_unqualified":
            reasons.append("measurement_not_completed")
        if guard is None:
            reasons.append("guard_not_requested")
        elif not guard["matched_expected_observations"]:
            reasons.append("guard_mismatch")
        if type(timing.get("elapsed_ns")) is not int or timing["elapsed_ns"] <= 0:
            reasons.append("missing_positive_elapsed_time")
        capture = result.get("raw_capture")
        if capture is not None and any(capture[stream]["truncated"] for stream in ("stdout", "stderr")):
            reasons.append("raw_capture_truncated")
        if reasons:
            blockers.append({"block": observation["block"], "arm": observation["arm"],
                             "reasons": reasons})
        else:
            samples.append({"block": observation["block"], "arm": observation["arm"],
                            "status": "guard_matched_unqualified", "elapsed_ns": timing["elapsed_ns"],
                            "timing_endpoint": inspection["timing_endpoint"]})
    summary: dict[str, Any] = {
        "mode": "exploratory_unqualified", "confirmatory_eligible": False,
        "timing_endpoint": inspection["timing_endpoint"],
        "blocks": inspection["blocks"], "arm_status_counts": inspection["arm_status_counts"],
        "planned_arm_count": inspection.get("planned_arm_count", 2 * inspection["blocks"]),
        "observed_arm_count": inspection.get("observed_arm_count", 2 * inspection["blocks"]),
        "stage_lifecycle_status_counts": inspection.get("stage_lifecycle_status_counts", {}),
        "observation_guard_counts": inspection["observation_guard_counts"],
        "recorded_interval_order": inspection["recorded_interval_order"],
        "blockers": blockers,
        "limitations": ["sentinel matches do not prove equal work", "records are not authenticated",
                        "source and environment are not qualified", "independence not established",
                        "no release claim"],
    }
    if blockers:
        summary["status"] = "blocked"
        summary["ratio"] = None
        summary["absolute_latency_ns"] = None
        summary["bootstrap"] = None
    else:
        summary["status"] = "exploratory_point_estimate"
        summary["ratio_direction"] = "baseline_over_candidate"
        summary["ratio"] = guarded_exploratory_ratio(samples)
        baseline_total = sum(sample["elapsed_ns"] for sample in samples if sample["arm"] == "baseline")
        candidate_total = sum(sample["elapsed_ns"] for sample in samples if sample["arm"] == "candidate")
        blocks = inspection["blocks"]
        summary["absolute_latency_ns"] = {
            "baseline_mean": baseline_total / blocks,
            "candidate_mean": candidate_total / blocks,
            "mean_paired_baseline_minus_candidate": (baseline_total - candidate_total) / blocks,
        }
        summary["bootstrap"] = (guarded_exploratory_bootstrap(
            samples, seed=bootstrap_seed, resamples=bootstrap_resamples)
            if bootstrap_resamples is not None else None)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--bootstrap-resamples", type=int, help="optional exploratory resample count")
    parser.add_argument("--bootstrap-seed", type=int, help="required with --bootstrap-resamples")
    args = parser.parse_args()
    try:
        result = summarize_run(args.directory, bootstrap_resamples=args.bootstrap_resamples,
                               bootstrap_seed=args.bootstrap_seed)
    except (InspectionError, ValueError, OSError) as exc:
        print(f"summarize-run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("exploratory_point_estimate", "diagnostic_resource_observations") else 1


if __name__ == "__main__":
    raise SystemExit(main())
