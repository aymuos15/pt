"""Private bounded framing primitives, not pytest hooks or a semantic validator.

Only bridge-origin envelopes use this channel. Payload catalog/state/terminal,
artifact, environment and generation checks are separate required gates. An EOF
or decoded message is never a test-success verdict. Socket ownership is explicit;
the eventual launcher must qualify all interpreter startup before project imports.
"""

import json
import math
import os
import re
import socket
import stat
import struct
import time


MAX_FRAME_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 1000000
MAX_DEPTH = 32
MAX_NODES = 65536
IDENTITY_FIELDS = {"request_id", "run_id", "generation_id", "session_id", "producer_id"}
ENVELOPE_FIELDS = IDENTITY_FIELDS | {"protocol_version", "contract_revision", "producer_role", "sequence", "kind", "payload"}
BRIDGE_KINDS = {
    "session_started", "collection_started", "collection_report", "collection_error", "item_collected", "items_selected",
    "items_deselected", "collection_finished", "item_started", "phase_report", "attempt_finished", "item_not_run", "warning",
    "output_reference", "extension_event", "artifact_ready", "session_error", "session_terminated",
}


class WireError(ValueError):
    pass


def _identity(value):
    if type(value) is not dict or set(value) != IDENTITY_FIELDS:
        raise WireError("control identity requires the exact coordinator-owned ID fields")
    for name in IDENTITY_FIELDS:
        if type(value[name]) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value[name]) is None:
            raise WireError("invalid opaque control identity")
    return dict(value)


def _plain(value, depth=0, count=None):
    if count is None:
        count = [0, 0]
    count[0] += 1
    if count[0] > MAX_NODES or depth > MAX_DEPTH:
        raise WireError("control JSON node/depth bound exceeded")

    def add(size):
        count[1] += size
        if count[1] > MAX_FRAME_BYTES:
            raise WireError("control JSON aggregate encoded byte bound exceeded before serialization")

    if type(value) is dict:
        add(2 + len(value) + max(len(value) - 1, 0))
        for name, item in value.items():
            if type(name) is not str:
                raise WireError("control JSON object keys must be strings")
            _plain(name, depth + 1, count)
            _plain(item, depth + 1, count)
    elif type(value) is list:
        add(2 + max(len(value) - 1, 0))
        for item in value:
            _plain(item, depth + 1, count)
    elif type(value) is str:
        if len(value) > MAX_FRAME_BYTES:
            raise WireError("control string exceeds the frame bound")
        try:
            encoded = value.encode("utf-8", errors="strict")
            if len(encoded) > MAX_FRAME_BYTES:
                raise WireError("control string exceeds its UTF-8 byte bound")
            escapes = sum(1 if character in '"\\\b\f\n\r\t' else 5 if ord(character) < 32 else 0 for character in value)
            add(2 + len(encoded) + escapes)
        except UnicodeError as exc:
            raise WireError("unsupported surrogate in control string") from exc
    elif type(value) is int:
        if not -(1 << 63) <= value < (1 << 64):
            raise WireError("control integer is outside signed/unsigned 64-bit range")
        add(len(str(value)))
    elif type(value) is bool:
        add(4 if value else 5)
    elif value is None:
        add(4)
    elif type(value) not in (bool, type(None)):
        raise WireError("control JSON permits only ordinary strings, integers, booleans, null, lists and objects")


def _envelope(event, identity):
    _plain(event)
    if (type(event) is not dict or set(event) != ENVELOPE_FIELDS
            or type(event["protocol_version"]) is not int or event["protocol_version"] != 0
            or type(event["contract_revision"]) is not int or event["contract_revision"] != 1
            or event["producer_role"] != "bridge" or type(event["kind"]) is not str or event["kind"] not in BRIDGE_KINDS
            or type(event["sequence"]) is not int or not 0 <= event["sequence"] < MAX_EVENTS or type(event["payload"]) is not dict):
        raise WireError("unsupported closed bridge envelope/version/role/kind")
    if {name: event[name] for name in IDENTITY_FIELDS} != identity:
        raise WireError("control message does not match the channel-bound identity")
    return event


def _pairs(rows):
    value = {}
    for name, item in rows:
        if name in value:
            raise WireError("duplicate control JSON object key")
        value[name] = item
    return value


def _no_float(value):
    raise WireError("non-integer/nonfinite control JSON number")


def _scan_json(text):
    """Bound containers/tokens before the generic JSON decoder allocates them."""
    stack, quoted, escaped, atom, nodes = [], False, False, False, 0
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted, atom = True, False
            nodes += 1
        elif character in "[{":
            stack.append(character)
            if len(stack) > MAX_DEPTH:
                raise WireError("control JSON nesting bound exceeded before decoding")
            nodes += 1
            atom = False
        elif character in "]}":
            expected = "[" if character == "]" else "{"
            if not stack or stack.pop() != expected:
                raise WireError("unbalanced control JSON containers")
            atom = False
        elif character in ",:" or character.isspace():
            atom = False
        elif not atom:
            atom = True
            nodes += 1
        if nodes > MAX_NODES:
            raise WireError("control JSON token bound exceeded before decoding")
    if stack or quoted:
        raise WireError("truncated control JSON containers/string")


def _decode(raw, identity):
    try:
        text = raw.decode("utf-8", errors="strict")
        _scan_json(text)
        event = json.loads(text, object_pairs_hook=_pairs, parse_float=_no_float, parse_constant=_no_float)
        return _envelope(event, identity)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WireError("malformed or unsupported bounded control JSON") from exc


def _timeout(stream, deadline):
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise WireError("control I/O requires a finite absolute local-monotonic deadline")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("private control deadline expired")
    stream.settimeout(remaining)


class ControlStream:
    """Own one connected Unix socket; each direction has bounded sequence/accounting.

    byte_budget includes framing headers and is intentionally no larger than the
    protocol's aggregate payload ceiling. Neither decoded payloads nor EOF assert
    catalog validity, completion, producer honesty or current test success.
    Counters describe complete confirmed frames, not bytes/effects lost during
    an interrupted send/read; a failed stream is never resumed or replayed.
    """

    def __init__(self, stream, identity, *, byte_budget, event_budget):
        self.identity = _identity(identity)
        if (type(byte_budget) is not int or not 1 <= byte_budget <= MAX_STREAM_BYTES
                or type(event_budget) is not int or not 1 <= event_budget <= MAX_EVENTS):
            raise WireError("control budgets must be explicit positive bounded integers")
        if type(stream) is not socket.socket or stream.family != socket.AF_UNIX or stream.type != socket.SOCK_STREAM:
            raise WireError("private control requires an owned Unix stream socket")
        stream.getpeername()  # A listening/unconnected socket is not the capability.
        stream.set_inheritable(False)
        self.stream = stream
        self.byte_budget, self.event_budget = byte_budget, event_budget
        self.sent = self.received = self.sent_bytes = self.received_bytes = 0
        self.failed = self.ended = self.closed = False

    @classmethod
    def take_fd(cls, fd, identity, *, byte_budget, event_budget):
        """Consume a caller-owned declared descriptor, never stdin/stdout/stderr.

        This closes a valid socket on construction failure. A non-socket is not
        adopted or altered. Single-threaded bootstrap/early startup qualification
        remains the launcher's responsibility; this is not a hostile-FD boundary.
        """
        if type(fd) is not int or fd < 3 or not stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise WireError("declared private control descriptor is not a non-stdio socket")
        os.set_inheritable(fd, False)
        stream = socket.socket(fileno=fd)
        try:
            return cls(stream, identity, byte_budget=byte_budget, event_budget=event_budget)
        except BaseException:
            stream.close()
            raise

    def _active(self):
        if self.failed or self.closed:
            raise WireError("private control stream is failed or closed; no recovery/replay")

    def send(self, kind, payload, *, deadline):
        self._active()
        try:
            event = {**self.identity, "protocol_version": 0, "contract_revision": 1, "producer_role": "bridge",
                     "sequence": self.sent, "kind": kind, "payload": payload}
            _envelope(event, self.identity)
            raw = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if not 1 <= len(raw) <= MAX_FRAME_BYTES:
                raise WireError("control frame exceeds its nonzero 1 MiB bound")
            _scan_json(raw.decode("utf-8"))
            size = len(raw) + 4
            if self.sent >= self.event_budget or self.sent_bytes + size > self.byte_budget:
                raise WireError("private control event/byte budget exceeded")
            _timeout(self.stream, deadline)
            self.stream.sendall(struct.pack("!I", len(raw)) + raw)
            self.sent += 1
            self.sent_bytes += size
        except BaseException:
            self.failed = True
            raise

    def _read_exact(self, size, deadline, *, allow_eof=False):
        raw, position = bytearray(size), 0
        while position < size:
            _timeout(self.stream, deadline)
            count = self.stream.recv_into(memoryview(raw)[position:])
            if count == 0:
                if position == 0 and allow_eof:
                    return None
                raise WireError("truncated private control frame")
            position += count
        return bytes(raw)

    def receive(self, *, deadline):
        self._active()
        if self.ended:
            raise WireError("private control EOF already observed; no reattachment")
        try:
            prefix = self._read_exact(4, deadline, allow_eof=True)
            if prefix is None:
                self.ended = True
                return None  # EOF is not a terminal semantic verdict.
            size = struct.unpack("!I", prefix)[0]
            if not 1 <= size <= MAX_FRAME_BYTES:
                raise WireError("unsupported zero/oversize private control frame")
            if self.received >= self.event_budget or self.received_bytes + 4 + size > self.byte_budget:
                raise WireError("private control event/byte budget exceeded before payload allocation")
            event = _decode(self._read_exact(size, deadline), self.identity)
            if event["sequence"] != self.received:
                raise WireError("lost, duplicate or reordered private control sequence")
            self.received += 1
            self.received_bytes += 4 + size
            return event
        except BaseException:
            self.failed = True
            raise

    def close(self):
        self.closed = True
        self.stream.close()

    def __enter__(self):
        self._active()
        return self

    def __exit__(self, *exception):
        self.close()
