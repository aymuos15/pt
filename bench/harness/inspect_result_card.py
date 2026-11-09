"""Reconstruct an exploratory result card from its retained paired-run evidence."""

import argparse
import json
from pathlib import Path
import sys

from finalization import read_json
from result_card import MAX_CARD_BYTES, inspect_result_card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", type=Path)
    parser.add_argument("--run", type=Path, required=True, help="retained evidence bundle; no subject commands execute")
    args = parser.parse_args()
    try:
        card, _ = read_json(args.card, limit=MAX_CARD_BYTES)
        result = inspect_result_card(card, args.run)
    except (OSError, ValueError) as exc:
        print(f"inspect-result-card: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
