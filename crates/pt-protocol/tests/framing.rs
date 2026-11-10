#![cfg(target_os = "linux")]
mod common;

use common::*;
use pt_protocol::{FrameReader, MAX_EVENTS, MAX_FRAME_BYTES, MAX_STREAM_BYTES, StreamBudget};
use serde_json::json;
use std::io::Write;
use std::os::unix::net::{UnixListener, UnixStream};
use std::thread;
use std::time::{Duration, Instant};

fn budget() -> StreamBudget {
    StreamBudget {
        bytes: MAX_STREAM_BYTES,
        events: MAX_EVENTS,
    }
}
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(3)
}

#[test]
fn actual_socket_frames_and_clean_eof_preserve_exact_bytes_and_confirmed_counters() {
    let (parent, mut child) = UnixStream::pair().unwrap();
    parent.set_nonblocking(true).unwrap(); // Reader owns and normalizes blocking I/O.
    let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
    let raw = event(0, "warning", fixtures()[12]["payload"].clone());
    let wire = frame(&raw);
    let expected = raw.clone();
    let bytes = wire.len() as u64;
    let writer = thread::spawn(move || {
        child.write_all(&wire[..1]).unwrap();
        thread::sleep(Duration::from_millis(5));
        child.write_all(&wire[1..3]).unwrap();
        thread::sleep(Duration::from_millis(5));
        for part in wire[3..].chunks(7) {
            child.write_all(part).unwrap();
        }
    });
    assert!(reader.end_evidence().is_none());
    assert_eq!(
        reader.receive(deadline()).unwrap().unwrap().raw_json(),
        expected
    );
    assert_eq!(reader.confirmed_frames(), 1);
    assert_eq!(reader.confirmed_wire_bytes(), bytes);
    assert!(reader.end_evidence().is_none());
    assert!(reader.receive(deadline()).unwrap().is_none());
    assert!(reader.end_evidence().is_some());
    assert!(reader.receive(deadline()).is_err()); // Never redeliver an EOF/event.
    writer.join().unwrap();
}

#[test]
fn exact_event_and_wire_byte_budget_still_allows_proving_eof_but_not_another_payload() {
    let first = frame(&event(0, "collection_started", json!({})));
    for extra in [false, true] {
        let (parent, mut child) = UnixStream::pair().unwrap();
        let mut reader = FrameReader::new(
            parent,
            identity(),
            StreamBudget {
                bytes: first.len() as u64,
                events: 1,
            },
        )
        .unwrap();
        child.write_all(&first).unwrap();
        if extra {
            child
                .write_all(&(MAX_FRAME_BYTES as u32).to_be_bytes())
                .unwrap();
        }
        drop(child);
        assert!(reader.receive(deadline()).unwrap().is_some());
        let result = reader.receive(deadline());
        if extra {
            assert!(result.unwrap_err().to_string().contains("budget"));
            assert!(reader.end_evidence().is_none());
            assert!(reader.receive(deadline()).is_err());
        } else {
            assert!(result.unwrap().is_none());
        }
        assert_eq!(reader.confirmed_frames(), 1);
        assert_eq!(reader.confirmed_wire_bytes(), first.len() as u64);
    }
}

#[test]
fn invalid_budgets_and_named_sockets_are_rejected_not_silently_expanded() {
    for bound in [
        StreamBudget {
            bytes: 0,
            events: 1,
        },
        StreamBudget {
            bytes: 1,
            events: 0,
        },
        StreamBudget {
            bytes: MAX_STREAM_BYTES + 1,
            events: 1,
        },
        StreamBudget {
            bytes: 1,
            events: MAX_EVENTS + 1,
        },
    ] {
        let (parent, _child) = UnixStream::pair().unwrap();
        assert!(FrameReader::new(parent, identity(), bound).is_err());
    }
    let root = tempfile::Builder::new()
        .prefix("pt-protocol-socket-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    let listener = UnixListener::bind(root.path().join("named")).unwrap();
    let client = UnixStream::connect(root.path().join("named")).unwrap();
    let (server, _) = listener.accept().unwrap();
    assert!(FrameReader::new(client, identity(), budget()).is_err());
    assert!(FrameReader::new(server, identity(), budget()).is_err());
}

#[test]
fn zero_and_oversized_length_fail_before_waiting_for_payload_or_allocating_it() {
    for length in [0, MAX_FRAME_BYTES as u32 + 1, u32::MAX] {
        let (parent, mut child) = UnixStream::pair().unwrap();
        child.write_all(&length.to_be_bytes()).unwrap();
        let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
        let start = Instant::now();
        assert!(
            reader
                .receive(deadline())
                .unwrap_err()
                .to_string()
                .contains("frame")
        );
        assert!(start.elapsed() < Duration::from_secs(1)); // Peer deliberately stays open.
        assert_eq!(reader.confirmed_frames(), 0);
        assert_eq!(reader.confirmed_wire_bytes(), 0);
        assert!(reader.end_evidence().is_none());
    }
}

#[test]
fn every_truncated_header_or_payload_is_a_permanent_fault_not_clean_eof() {
    let wire = frame(&event(0, "collection_started", json!({})));
    for end in [1, 2, 3, 4, 5, wire.len() - 1] {
        let (parent, mut child) = UnixStream::pair().unwrap();
        child.write_all(&wire[..end]).unwrap();
        drop(child);
        let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
        assert!(
            reader
                .receive(deadline())
                .unwrap_err()
                .to_string()
                .contains("truncated")
        );
        assert!(reader.receive(deadline()).is_err());
        assert!(reader.end_evidence().is_none());
        assert_eq!(reader.confirmed_frames(), 0);
    }
}

#[test]
fn clean_empty_eof_is_evidence_of_no_messages_not_a_semantic_terminal() {
    let (parent, child) = UnixStream::pair().unwrap();
    drop(child);
    let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
    assert!(reader.receive(deadline()).unwrap().is_none());
    assert_eq!(reader.confirmed_frames(), 0);
    assert_eq!(reader.confirmed_wire_bytes(), 0);
    assert!(reader.end_evidence().is_some());
}

#[test]
fn lost_duplicate_or_reordered_sequences_fail_without_counting_or_redelivering_faulty_frames() {
    for sequence in [0, 2, 99] {
        let (parent, mut child) = UnixStream::pair().unwrap();
        let first = frame(&event(0, "collection_started", json!({})));
        child.write_all(&first).unwrap();
        child
            .write_all(&frame(&event(sequence, "collection_started", json!({}))))
            .unwrap();
        drop(child);
        let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
        assert!(reader.receive(deadline()).unwrap().is_some());
        assert!(
            reader
                .receive(deadline())
                .unwrap_err()
                .to_string()
                .contains("event")
        );
        assert_eq!(reader.confirmed_frames(), 1);
        assert_eq!(reader.confirmed_wire_bytes(), first.len() as u64);
        assert!(reader.end_evidence().is_none());
        assert!(reader.receive(deadline()).is_err());
    }
}

#[test]
fn bad_payload_or_identity_poison_the_stream_even_if_a_valid_frame_follows() {
    let mut spoof = envelope(0, "collection_started", json!({}));
    spoof["generation_id"] = json!("other");
    for invalid in [
        b"not-json".to_vec(),
        serde_json::to_vec(&spoof).unwrap(),
        event(0, "collection_started", json!({"extra":true})),
    ] {
        let (parent, mut child) = UnixStream::pair().unwrap();
        child.write_all(&frame(&invalid)).unwrap();
        child
            .write_all(&frame(&event(0, "collection_started", json!({}))))
            .unwrap();
        drop(child);
        let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
        assert!(reader.receive(deadline()).is_err());
        assert!(reader.receive(deadline()).is_err());
        assert_eq!(reader.confirmed_frames(), 0);
        assert!(reader.end_evidence().is_none());
    }
}

#[test]
fn expired_or_stalled_deadlines_are_permanent_and_fragment_arrival_cannot_reset_them() {
    let (parent, mut child) = UnixStream::pair().unwrap();
    let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
    child
        .write_all(&frame(&event(0, "collection_started", json!({}))))
        .unwrap();
    assert!(reader.receive(Instant::now()).is_err());
    assert!(reader.receive(deadline()).is_err());
    let (parent, _child) = UnixStream::pair().unwrap();
    let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
    let start = Instant::now();
    assert!(reader.receive(start + Duration::from_millis(30)).is_err());
    assert!(start.elapsed() < Duration::from_secs(1));

    let (parent, mut child) = UnixStream::pair().unwrap();
    let mut reader = FrameReader::new(parent, identity(), budget()).unwrap();
    let wire = frame(&event(0, "collection_started", json!({})));
    let writer = thread::spawn(move || {
        child.write_all(&wire[..2]).unwrap();
        thread::sleep(Duration::from_millis(80));
        child.write_all(&wire[2..4]).unwrap();
        thread::sleep(Duration::from_millis(200));
    });
    let start = Instant::now();
    assert!(reader.receive(start + Duration::from_millis(130)).is_err());
    assert!(start.elapsed() < Duration::from_millis(260));
    assert!(reader.receive(deadline()).is_err());
    assert!(reader.end_evidence().is_none());
    writer.join().unwrap();
}
