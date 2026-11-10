"""Private framing component checks, not a production pytest session/qualification."""

import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/pt_bridge/src"))
from pt_bridge import _wire as wire
sys.path.pop(0)

IDENTITY = {"request_id": "request-1", "run_id": "run-1", "generation_id": "generation-1", "session_id": "session-1", "producer_id": "bridge-1"}


@unittest.skipUnless(sys.platform == "linux", "private transport component targets Linux")
class BridgeTransportTests(unittest.TestCase):
    def setUp(self):
        parent, child = socket.socketpair()
        self.sender = wire.ControlStream(child, IDENTITY, byte_budget=2 * 1024 * 1024, event_budget=1000)
        self.receiver = wire.ControlStream(parent, IDENTITY, byte_budget=2 * 1024 * 1024, event_budget=1000)
        self.addCleanup(self.sender.close)
        self.addCleanup(self.receiver.close)

    def event(self, sequence=0, **changes):
        return {**IDENTITY, "protocol_version": 0, "contract_revision": 1, "producer_role": "bridge", "sequence": sequence,
                "kind": "warning", "payload": {"message": "a diagnostic, not completed test work"}, **changes}

    def raw_event(self, **changes):
        return json.dumps(self.event(**changes), ensure_ascii=False, separators=(",", ":")).encode()

    def feed(self, raw, *, prefix=None, fragment=False):
        data = (struct.pack("!I", len(raw)) if prefix is None else prefix) + raw
        errors = []

        def write():
            try:
                self.sender.stream.settimeout(2)
                if fragment:
                    for byte in data:
                        self.sender.stream.sendall(bytes([byte]))
                else:
                    self.sender.stream.sendall(data)
            except OSError as error:
                errors.append(error)

        worker = threading.Thread(target=write)
        worker.start()

        def finish():
            try:
                self.sender.stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive(), "fault writer must not survive its test")

        self.addCleanup(finish)
        return errors

    def read(self):
        return self.receiver.receive(deadline=time.monotonic() + 2)

    def test_exact_unicode_payload_and_zero_based_sequence_round_trip(self):
        payload = {"nodeid": "tests/test_é.py::test_value[🧪]", "values": [None, True, False, -1, (1 << 64) - 1]}
        self.sender.send("phase_report", payload, deadline=time.monotonic() + 2)
        first = self.read()
        self.assertEqual(first, self.event(kind="phase_report", payload=payload))
        self.sender.send("warning", {"message": "second"}, deadline=time.monotonic() + 2)
        self.assertEqual(self.read()["sequence"], 1)
        self.assertEqual(self.sender.sent_bytes, self.receiver.received_bytes)
        self.assertEqual((self.sender.sent, self.receiver.received), (2, 2))

    def test_socket_is_connected_unix_noninheritable_and_not_a_named_listener(self):
        self.assertEqual(self.sender.stream.family, socket.AF_UNIX)
        self.assertFalse(self.sender.stream.get_inheritable())
        self.assertFalse(self.receiver.stream.get_inheritable())
        self.assertEqual(self.sender.stream.getpeername(), "")

    def test_fragmented_header_and_payload_are_reassembled_without_stdio_parsing(self):
        event = self.event(payload={"message": "text contains } ] { [ and a literal \\\" quote"})
        raw = json.dumps(event, separators=(",", ":")).encode()
        self.feed(raw, fragment=True)
        self.assertEqual(self.read(), event)

    def test_eof_is_not_a_success_or_a_terminal_accounting_event(self):
        self.sender.close()
        self.assertIsNone(self.read())
        self.assertTrue(self.receiver.ended)
        self.assertEqual(self.receiver.received, 0)
        self.assertFalse(hasattr(self.receiver, "current_full_success"))
        with self.assertRaises(wire.WireError):
            self.read()

    def test_truncated_header_and_payload_are_failures_not_recoverable_eof(self):
        for data in (b"\x00\x00", struct.pack("!I", 10) + b"{}"):
            with self.subTest(data=data):
                parent, child = socket.socketpair()
                with wire.ControlStream(parent, IDENTITY, byte_budget=1024, event_budget=2) as receiver:
                    child.sendall(data)
                    child.close()
                    with self.assertRaisesRegex(wire.WireError, "truncated"):
                        receiver.receive(deadline=time.monotonic() + 2)
                    self.assertTrue(receiver.failed)

    def test_zero_or_oversize_length_is_rejected_before_waiting_for_payload(self):
        for size in (0, wire.MAX_FRAME_BYTES + 1, (1 << 32) - 1):
            parent, child = socket.socketpair()
            with child, wire.ControlStream(parent, IDENTITY, byte_budget=2 * 1024 * 1024, event_budget=2) as receiver:
                child.sendall(struct.pack("!I", size))
                with self.subTest(size=size), self.assertRaises(wire.WireError):
                    receiver.receive(deadline=time.monotonic() + 0.1)

    def test_closed_shape_version_role_kind_and_identity_cannot_be_spoofed(self):
        mutations = [{"protocol_version": 1}, {"protocol_version": True}, {"contract_revision": 2}, {"sequence": True},
                     {"producer_role": "coordinator"}, {"kind": "generation_checked"}, {"kind": "unknown"},
                     {"request_id": "different"}, {"run_id": "different"}, {"session_id": "different"},
                     {"generation_id": "different"}, {"producer_id": "different"}, {"extra": "unknown"}, {"payload": []}]
        for change in mutations:
            parent, child = socket.socketpair()
            with child, wire.ControlStream(parent, IDENTITY, byte_budget=4096, event_budget=2) as receiver:
                raw = self.raw_event(**change)
                child.sendall(struct.pack("!I", len(raw)) + raw)
                with self.subTest(change=change), self.assertRaises(wire.WireError):
                    receiver.receive(deadline=time.monotonic() + 2)
                self.assertTrue(receiver.failed)

    def test_duplicate_nested_keys_invalid_utf8_utf16_nan_floats_and_surrogates_fail(self):
        valid = self.raw_event()
        bad = [valid.replace(b'"message":', b'"message":"duplicate","message":'), valid.replace(b'"sequence":0', b'"sequence":0,"sequence":0'),
               valid.replace(b'"message":"a diagnostic, not completed test work"', b'"message":NaN'),
               valid.replace(b'"message":"a diagnostic, not completed test work"', b'"message":1.0'),
               valid.replace(b'"message":"a diagnostic, not completed test work"', b'"message":"\\ud800"'),
               b"\xff", valid.decode().encode("utf-16"), b"{} trailing", b"[]"]
        for raw in bad:
            parent, child = socket.socketpair()
            with child, wire.ControlStream(parent, IDENTITY, byte_budget=8192, event_budget=2) as receiver:
                child.sendall(struct.pack("!I", len(raw)) + raw)
                with self.subTest(raw=raw[:80]), self.assertRaises(wire.WireError):
                    receiver.receive(deadline=time.monotonic() + 2)

    def test_depth_and_token_bounds_are_checked_before_generic_json_decoding(self):
        for raw in (b"[" * 33 + b"0" + b"]" * 33, b"[" + b"0," * wire.MAX_NODES + b"0]"):
            with mock.patch.object(wire.json, "loads", side_effect=AssertionError("decoder must not run")):
                with self.assertRaises(wire.WireError):
                    wire._decode(raw, IDENTITY)

    def test_exact_encoded_byte_bound_includes_unicode_quotes_and_control_escapes(self):
        payload = {"message": 'a"\\\b\f\n\r\t\x01 café 🧪'}
        raw = self.raw_event(payload=payload)
        with mock.patch.object(wire, "MAX_FRAME_BYTES", len(raw)):
            self.sender.send("warning", payload, deadline=time.monotonic() + 2)
            self.assertEqual(self.read()["payload"], payload)

    def test_aggregate_payload_is_rejected_before_json_serializer_can_allocate_it(self):
        with mock.patch.object(wire.json, "dumps", side_effect=AssertionError("serializer must not run")):
            with self.assertRaises(wire.WireError):
                self.sender.send("warning", {"values": ["x" * 1024] * 2048}, deadline=time.monotonic() + 2)
        self.assertTrue(self.sender.failed)

    def test_arbitrary_objects_and_repr_are_never_used_for_control_metadata(self):
        calls = []

        class ProjectObject:
            def __repr__(self):
                calls.append("repr")
                raise AssertionError("must not inspect project representation")

        with self.assertRaises(wire.WireError):
            self.sender.send("warning", {"message": ProjectObject()}, deadline=time.monotonic() + 2)
        self.assertEqual(calls, [])
        self.assertTrue(self.sender.failed)

    def test_duplicate_gap_or_reordered_sequences_fail_without_redelivery_recovery(self):
        for next_sequence in (0, 2):
            parent, child = socket.socketpair()
            with child, wire.ControlStream(parent, IDENTITY, byte_budget=8192, event_budget=4) as receiver:
                for sequence in (0, next_sequence):
                    raw = self.raw_event(sequence=sequence)
                    child.sendall(struct.pack("!I", len(raw)) + raw)
                self.assertEqual(receiver.receive(deadline=time.monotonic() + 2)["sequence"], 0)
                with self.assertRaises(wire.WireError):
                    receiver.receive(deadline=time.monotonic() + 2)
                with self.assertRaises(wire.WireError):
                    receiver.receive(deadline=time.monotonic() + 2)

    def test_byte_and_event_budgets_fail_before_allocating_the_next_payload(self):
        for option in ("byte", "event"):
            parent, child = socket.socketpair()
            with child, wire.ControlStream(parent, IDENTITY, byte_budget=4096 if option == "event" else 20, event_budget=1) as receiver:
                if option == "event":
                    raw = self.raw_event()
                    child.sendall(struct.pack("!I", len(raw)) + raw)
                    receiver.receive(deadline=time.monotonic() + 2)
                child.sendall(struct.pack("!I", 1000))
                with self.assertRaisesRegex(wire.WireError, "budget"):
                    receiver.receive(deadline=time.monotonic() + 0.1)

    def test_invalid_budgets_and_opaque_identities_are_rejected(self):
        for budget in (True, 0, -1, math.inf, wire.MAX_STREAM_BYTES + 1):
            with self.assertRaises(wire.WireError):
                wire.ControlStream(self.sender.stream, IDENTITY, byte_budget=budget, event_budget=1)
        for identity in ({}, {**IDENTITY, "extra": "x"}, {**IDENTITY, "session_id": "../escape"}, {**IDENTITY, "producer_id": True}):
            with self.assertRaises(wire.WireError):
                wire.ControlStream(self.sender.stream, identity, byte_budget=1000, event_budget=1)

    def test_deadline_is_absolute_finite_and_a_partial_read_cannot_reset_it(self):
        self.sender.stream.sendall(b"\0\0\0")
        with self.assertRaises(TimeoutError):
            self.receiver.receive(deadline=time.monotonic() + 0.03)
        self.assertTrue(self.receiver.failed)
        for deadline in (True, math.inf, math.nan):
            with self.assertRaises(wire.WireError):
                self.sender.send("warning", {}, deadline=deadline)

    def test_closed_peer_or_backpressure_cannot_be_retried_as_a_new_complete_event(self):
        self.receiver.close()
        with self.assertRaises(OSError):
            self.sender.send("warning", {}, deadline=time.monotonic() + 2)
        self.assertTrue(self.sender.failed)
        self.assertEqual(self.sender.sent, 0)
        with self.assertRaises(wire.WireError):
            self.sender.send("warning", {}, deadline=time.monotonic() + 2)

    def test_stalled_reader_bounds_a_writer_and_partial_or_unknown_bytes_do_not_become_completion(self):
        self.sender.stream.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        with self.assertRaises(TimeoutError):
            self.sender.send("warning", {"message": "x" * 500000}, deadline=time.monotonic() + 0.1)
        self.assertTrue(self.sender.failed)
        self.assertEqual(self.sender.sent, 0)  # No confirmed complete send, not proof of zero bytes/effects.
        self.sender.close()
        try:
            observed = self.receiver.receive(deadline=time.monotonic() + 2)
        except wire.WireError:
            observed = None  # Truncated bytes remain a fault, never an event.
        self.assertIsNone(observed)
        self.assertEqual(self.receiver.received, 0)

    def test_adopting_an_explicit_owned_fd_sets_noninheritability_and_rejects_stdio_or_files(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        fd = child.detach()
        os.set_inheritable(fd, True)
        with wire.ControlStream.take_fd(fd, IDENTITY, byte_budget=4096, event_budget=1) as stream:
            self.assertFalse(os.get_inheritable(fd))
        with self.assertRaises(OSError):
            os.fstat(fd)
        for fd in (0, 1, 2, -1, True):
            with self.assertRaises(wire.WireError):
                wire.ControlStream.take_fd(fd, IDENTITY, byte_budget=4096, event_budget=1)
        with tempfile.TemporaryFile() as file:
            before = os.get_inheritable(file.fileno())
            with self.assertRaises(wire.WireError):
                wire.ControlStream.take_fd(file.fileno(), IDENTITY, byte_budget=4096, event_budget=1)
            self.assertEqual(os.get_inheritable(file.fileno()), before)
            file.write(b"file still owned by caller")

    def test_unconnected_or_wrong_socket_family_is_not_a_private_channel(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            with self.assertRaises(OSError):
                wire.ControlStream(stream, IDENTITY, byte_budget=4096, event_budget=1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
            with self.assertRaises(wire.WireError):
                wire.ControlStream(stream, IDENTITY, byte_budget=4096, event_budget=1)

    def test_plain_component_import_does_not_import_pytest_or_a_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pytest.py").write_text("raise RuntimeError('project pytest must not load')\n")
            result = subprocess.run([sys.executable, "-I", "-c",
                "import sys; sys.path.insert(0,sys.argv[1]); import pt_bridge._wire; assert 'pytest' not in sys.modules",
                str(ROOT / "python/pt_bridge/src")], cwd=root, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
