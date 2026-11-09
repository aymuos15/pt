"""Trusted harness-only replay driver; exec'd with -I after fresh cgroup enrollment.

All imports, replay work and receipt publication here are inside the resource
boundary. Subject processes inherit their original environment, not driver flags
or sys.path. No harness code is imported into the actual measured test workers.
"""

import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    # -I excludes cwd/PYTHONPATH. Only this explicit trusted harness path is added.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from replay_resources import driver_main
    try:
        return driver_main(args.root, args.request_sha256)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"replay-resource-driver: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
