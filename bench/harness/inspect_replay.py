"""Inspect one complete or accounted-aborted managed replay, without executing it."""

import argparse
import json
from pathlib import Path
import sys

from finalization import MAX_RECEIPT_BYTES, read_json
from managed_replay import inspect_replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True, help="post-endpoint receipt captured outside the evidence directory")
    args = parser.parse_args()
    try:
        receipt, _ = read_json(args.receipt, limit=MAX_RECEIPT_BYTES)
        result = inspect_replay(args.directory, receipt)
    except (OSError, ValueError) as exc:
        print(f"inspect-replay: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
