"""Experimental paired estimator, not a campaign validation or publication tool."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


def _paired_log_ratios(samples: Sequence[Mapping[str, Any]], *,
                       required_status: str = "valid_expected_outcome") -> list[float]:
    """Validate and return log ratios in stable block-identifier order."""
    if not samples:
        raise ValueError("at least one complete block is required")
    blocks: dict[str, dict[str, int]] = {}
    for sample in samples:
        block, arm, status, duration = (sample.get(key) for key in
                                        ("block", "arm", "status", "elapsed_ns"))
        if not isinstance(block, str) or not block:
            raise ValueError("block must be a nonempty string")
        if arm not in ("baseline", "candidate"):
            raise ValueError("unrecognized arm")
        if status != required_status:
            raise ValueError("unqualified or invalid sample")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValueError("elapsed_ns must be a positive integer")
        block_samples = blocks.setdefault(block, {})
        if arm in block_samples:
            raise ValueError("duplicate arm within block")
        block_samples[arm] = duration

    ratios = []
    for block in sorted(blocks):
        arms = blocks[block]
        if set(arms) != {"baseline", "candidate"}:
            raise ValueError("incomplete block")
        ratios.append(math.log(arms["baseline"]) - math.log(arms["candidate"]))
    return ratios


def paired_geometric_ratio(samples: Sequence[Mapping[str, Any]]) -> float:
    """Calculate exp(mean(log(baseline / candidate))) over complete blocks.

    Samples must already be independently qualified by the caller. This checks
    record shape and completeness, not their provenance or correctness. It never
    silently drops invalid, duplicate, or incomplete observations.
    """
    ratios = _paired_log_ratios(samples)
    return math.exp(math.fsum(ratios) / len(ratios))


def guarded_exploratory_ratio(samples: Sequence[Mapping[str, Any]]) -> float:
    """Point estimate over guard-matched records, not equal-work qualification."""
    ratios = _paired_log_ratios(samples, required_status="guard_matched_unqualified")
    return math.exp(math.fsum(ratios) / len(ratios))


def bootstrap_paired_ratio(samples: Sequence[Mapping[str, Any]], *, seed: int,
                           resamples: int, confidence: float = 0.95) -> dict[str, Any]:
    """Return exploratory percentile intervals resampling complete paired blocks.

    The caller must establish qualification and independence; this calculation
    cannot detect correlated blocks or justify an inferential claim. It uses
    linear interpolation between sorted bootstrap replicates for quantiles.
    """
    return _bootstrap_ratio(samples, seed=seed, resamples=resamples, confidence=confidence,
                            required_status="valid_expected_outcome")


def guarded_exploratory_bootstrap(samples: Sequence[Mapping[str, Any]], *, seed: int,
                                  resamples: int, confidence: float = 0.95) -> dict[str, Any]:
    """Bootstrap guard-matched observations without calling them qualified."""
    return _bootstrap_ratio(samples, seed=seed, resamples=resamples, confidence=confidence,
                            required_status="guard_matched_unqualified")


def _bootstrap_ratio(samples: Sequence[Mapping[str, Any]], *, seed: int, resamples: int,
                     confidence: float, required_status: str) -> dict[str, Any]:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 2:
        raise ValueError("resamples must be an integer of at least two")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number strictly between zero and one")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be a number strictly between zero and one")
    logs = _paired_log_ratios(samples, required_status=required_status)
    if len(logs) < 2:
        raise ValueError("at least two paired blocks are required")

    rng = random.Random(seed)
    estimates = sorted(
        math.exp(math.fsum(rng.choice(logs) for _ in logs) / len(logs))
        for _ in range(resamples)
    )

    def quantile(probability: float) -> float:
        position = probability * (len(estimates) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        return estimates[lower] + (estimates[upper] - estimates[lower]) * (position - lower)

    tail = (1 - confidence) / 2
    return {
        "mode": "exploratory_unqualified", "ratio_direction": "baseline_over_candidate",
        "point_estimate": math.exp(math.fsum(logs) / len(logs)),
        "interval_method": "percentile_whole_paired_blocks_linear_quantile",
        "confidence_level": confidence, "interval_lower": quantile(tail),
        "interval_upper": quantile(1 - tail), "blocks": len(logs),
        "bootstrap_resamples": resamples, "bootstrap_seed": seed,
    }
