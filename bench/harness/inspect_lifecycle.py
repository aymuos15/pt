"""Inspect a post-publication receipt and its sample; never qualify test work."""

import argparse
import json
from pathlib import Path
import sys

from finalization import MAX_RECEIPT_BYTES, read_json
from pt_bench import inspect_lifecycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt, _ = read_json(args.receipt, limit=MAX_RECEIPT_BYTES)
        result = inspect_lifecycle(args.sample, receipt)
    except (OSError, ValueError) as exc:
        print(f"inspect-lifecycle: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["lifecycle_finalized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
