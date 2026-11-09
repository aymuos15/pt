"""Inspect a historical resource observation, not current processes or test work."""

import argparse
import json
from pathlib import Path
import sys

from finalization import MAX_RECEIPT_BYTES, read_json
from resource_run import inspect_resource_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        record, _ = read_json(args.record, limit=MAX_RECEIPT_BYTES)
        report = inspect_resource_record(record)
    except (OSError, ValueError) as exc:
        print(f"inspect-resources: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
