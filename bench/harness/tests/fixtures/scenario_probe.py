"""Test-owned file inputs, effects and cleanup; not a semantic oracle or PT backend."""

import json
import os
from pathlib import Path
import sys
import time


def main():
    role, name, mode = sys.argv[1:4]
    with Path("events").open("a") as events:
        events.write(f"{role}:{name}:{os.getpid()}\n")
    if mode == "hang":
        time.sleep(20)
    if role == "request":
        payload = json.loads(Path("request.json").read_text())
        assert payload["request_id"] == name
        assert payload["input_seed"] == 17
        for path, expected in payload["data"].items():
            assert (Path(path).read_text() if Path(path).exists() else None) == expected
        Path("lease").touch()
        if mode == "mutate":
            Path("source.txt").write_text("changed by subject\n")
    elif mode != "unreleased":
        Path("lease").unlink(missing_ok=True)
    Path("report-" + name).write_text("ready\n")
    print("ready")
    return 7 if mode == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
