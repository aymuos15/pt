"""Reproducible exploratory paired-block ordering, independent of PT runtime."""

from __future__ import annotations

import random
from typing import Any


def paired_schedule(blocks: int, seed: int) -> list[dict[str, Any]]:
    """Return randomized, balanced AB/BA blocks; odd counts differ by one.

    This chooses order only. It does not establish independent samples, prepare
    arm state, execute commands, or validate a campaign.
    """
    if isinstance(blocks, bool) or not isinstance(blocks, int) or blocks < 1:
        raise ValueError("blocks must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    rng = random.Random(seed)
    orders = [("baseline", "candidate"), ("candidate", "baseline")] * (blocks // 2)
    if blocks % 2:
        orders.append(rng.choice([("baseline", "candidate"), ("candidate", "baseline")]))
    rng.shuffle(orders)
    return [
        {"block": index, "order": list(order)}
        for index, order in enumerate(orders, start=1)
    ]
