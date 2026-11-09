"""Test-owned declared session state, not a daemon, PT backend or semantic oracle."""

import os
from pathlib import Path
import sys
import time


def main():
    root, role, name, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    with (root / "events").open("a") as output:
        output.write(f"{name}:begin:{os.getpid()}\n")
    if role == "preparation":
        (root / "lease").touch()
        (root / "state").write_text("0")
    if mode == "wait":
        (root / f"{name}.entered").touch()
        deadline = time.monotonic() + 15
        while not (root / f"{name}.release").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("parent did not release replay fixture")
            time.sleep(0.005)
    if mode == "hang":
        time.sleep(5)
    if role == "interaction":
        if not (root / "lease").exists():
            raise RuntimeError("interaction did not observe preparation state")
        (root / "state").write_text(str(int((root / "state").read_text()) + 1))
    if role == "shutdown" and mode != "unreleased":
        (root / "lease").unlink(missing_ok=True)
    (root / f"report-{name}").write_bytes(b"ready\n")
    with (root / "events").open("a") as output:
        output.write(f"{name}:end:{os.getpid()}\n")
    print("ready")
    return 7 if mode == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
