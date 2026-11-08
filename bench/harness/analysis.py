"""Experimental paired estimator, not a campaign validation or publication tool."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def paired_geometric_ratio(samples: Sequence[Mapping[str, Any]]) -> float:
    """Calculate exp(mean(log(baseline / candidate))) over complete blocks.

    Samples must already be independently qualified by the caller. This checks
    record shape and completeness, not their provenance or correctness. It never
    silently drops invalid, duplicate, or incomplete observations.
    """
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
        if status != "valid_expected_outcome":
            raise ValueError("unqualified or invalid sample")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValueError("elapsed_ns must be a positive integer")
        block_samples = blocks.setdefault(block, {})
        if arm in block_samples:
            raise ValueError("duplicate arm within block")
        block_samples[arm] = duration

    ratios = []
    for arms in blocks.values():
        if set(arms) != {"baseline", "candidate"}:
            raise ValueError("incomplete block")
        ratios.append(math.log(arms["baseline"]) - math.log(arms["candidate"]))
    return math.exp(math.fsum(ratios) / len(ratios))
