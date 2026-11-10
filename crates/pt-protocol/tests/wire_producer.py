"""Actual Python wire interoperability; synthetic payloads, not a pytest backend."""

import json
import os
from pathlib import Path
import sys
import time


bridge_source, rows_path, mode = sys.argv[1:]
sys.path.insert(0, bridge_source)
from pt_bridge._wire import ControlStream

identity = {"request_id": "request-1", "run_id": "run-1", "generation_id": "generation-1",
            "session_id": "session-1", "producer_id": "bridge-1"}
with ControlStream.take_fd(3, identity, byte_budget=1024*1024, event_budget=1024) as channel:
    assert not os.get_inheritable(3)
    assert "pytest" not in sys.modules
    rows = json.loads(Path(rows_path).read_bytes())
    for index, row in enumerate(rows):
        channel.send(row["kind"], row["payload"], deadline=time.monotonic()+5)
        if mode in ("abort", "truncated", "timeout"):
            with Path("performed-before-lost-completion").open("x") as output:
                output.write("PT_SYNTHETIC_COMPONENT_EFFECT\n")
            if mode != "abort":
                channel.stream.sendall(b'\x00\x00\x00\x64{"partial":')
            if mode == "timeout":
                time.sleep(30)
            os._exit(17)
    if mode == "expected_failure":
        raise SystemExit(1)
