"""Optional bounded-prefix output capture for the exploratory timer."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
from typing import Any

from blob_store import publish


class RawCapture:
    """Spool bounded stream prefixes, then publish them as content-addressed blobs."""

    def __init__(self, bundle: Path, limit: int):
        if type(limit) is not int or limit < 0:
            raise ValueError("raw output limit must be a nonnegative integer")
        if not bundle.is_dir():
            raise ValueError("raw output bundle must be an existing directory")
        self.bundle = bundle
        self.limit = limit
        self.stack = ExitStack()
        self.files = {}
        self.sizes = {"stdout": 0, "stderr": 0}
        self.truncated = {"stdout": False, "stderr": False}

    def __enter__(self):
        try:
            for name in self.sizes:
                self.files[name] = self.stack.enter_context(tempfile.TemporaryFile(mode="w+b", dir=self.bundle))
        except BaseException:
            self.stack.close()
            raise
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def write(self, name: str, data: bytes) -> None:
        remaining = self.limit - self.sizes[name]
        prefix = data[:remaining]
        self.files[name].write(prefix)
        self.sizes[name] += len(prefix)
        if len(prefix) != len(data):
            self.truncated[name] = True

    def publish(self) -> dict[str, Any]:
        result = {"capture_mode": "bounded_prefix", "limit_per_stream_bytes": self.limit}
        for name, spool in self.files.items():
            spool.flush()
            spool.seek(0)
            blob = publish(spool, self.bundle, max_bytes=self.limit)
            result[name] = {**blob, "truncated": self.truncated[name]}
        return result
