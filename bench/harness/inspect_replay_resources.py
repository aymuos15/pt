"""Inspect one retained whole-session resource diagnostic; never rerun its subject."""

import argparse
import json
from pathlib import Path
import sys

from finalization import MAX_RECEIPT_BYTES, read_json
from replay_resources import inspect_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt, _ = read_json(args.receipt, limit=MAX_RECEIPT_BYTES)
        summary = inspect_observation(args.directory, receipt)
    except (OSError, ValueError) as exc:
        print(f"inspect-replay-resources: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
