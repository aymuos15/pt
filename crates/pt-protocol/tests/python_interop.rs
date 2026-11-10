#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod common;

use common::*;
use pt_process::{
    Cleanup, LeaderStatus, ProcessRequest, Termination, control_channel_pair, supervise,
    supervise_with_control,
};
use pt_protocol::{
    BridgeMessage, BridgePayload, FrameReader, MAX_EVENTS, MAX_STREAM_BYTES, SerialLedger,
    StreamBudget, StreamEnd, decode_bridge,
};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicI32;
use std::thread;
use std::time::{Duration, Instant};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}
fn python() -> std::ffi::OsString {
    std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| {
        root()
            .join("bench/harness/.venv/bin/python")
            .into_os_string()
    })
}
fn request(cwd: &Path) -> ProcessRequest {
    ProcessRequest {
        executable: python(),
        args: vec![],
        cwd: cwd.into(),
        timeout: Duration::from_secs(30),
        cleanup_timeout: Duration::from_secs(1),
    }
}

#[test]
fn independent_pinned_python_schema_and_wire_shape_mutations_agree_with_the_typed_decoder() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-protocol-schema-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    let output = tmp.path().join("schema-controls.json");
    let mut invocation = request(tmp.path());
    invocation.args = vec![
        "-I".into(),
        "-B".into(),
        root()
            .join("crates/pt-protocol/tests/schema_control.py")
            .into_os_string(),
        root().join("docs/protocol-v0.schema.json").into_os_string(),
        root()
            .join("crates/pt-protocol/tests/fixtures/bridge-payloads.json")
            .into_os_string(),
        output.clone().into_os_string(),
    ];
    let observed = supervise(&invocation, &AtomicI32::new(0)).unwrap();
    assert_eq!(observed.exit_code(), 0, "{observed:?}");
    assert_eq!(observed.cleanup, Cleanup::Complete);
    assert!(fs::metadata(&output).unwrap().len() <= 8 * 1024 * 1024);
    let report: Value = serde_json::from_slice(&fs::read(output).unwrap()).unwrap();
    assert_eq!(report["qualified"], false);
    assert_eq!(report["bridge_shapes"], 18);
    let cases = report["cases"].as_array().unwrap();
    assert!(cases.len() > 2000);
    for case in cases {
        let result = decode_bridge(case["raw"].as_str().unwrap().as_bytes(), &identity());
        assert_eq!(
            result.is_ok(),
            case["schema_and_wire_shape_accepted"].as_bool().unwrap(),
            "{}: {result:?}; raw={}",
            case["label"],
            case["raw"]
        );
    }
}

struct ReadObservation {
    messages: Vec<BridgeMessage>,
    end: Option<StreamEnd>,
    fault: Option<String>,
}

fn wire(rows: Vec<Value>, mode: &str) -> (pt_process::ProcessReport, ReadObservation, bool) {
    let tmp = tempfile::Builder::new()
        .prefix("pt-protocol-python-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    let input = tmp.path().join("synthetic-payloads.json");
    fs::write(&input, serde_json::to_vec(&rows).unwrap()).unwrap();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = thread::spawn(move || {
        let mut reader = FrameReader::new(
            parent,
            identity(),
            StreamBudget {
                bytes: MAX_STREAM_BYTES,
                events: MAX_EVENTS,
            },
        )
        .unwrap();
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut messages = Vec::new();
        let fault = loop {
            match reader.receive(deadline) {
                Ok(Some(message)) => messages.push(message),
                Ok(None) => break None,
                Err(error) => break Some(error.to_string()),
            }
        };
        ReadObservation {
            messages,
            end: reader.end_evidence(),
            fault,
        }
    });
    let mut invocation = request(tmp.path());
    invocation.args = vec![
        "-I".into(),
        "-S".into(),
        "-B".into(),
        root()
            .join("crates/pt-protocol/tests/wire_producer.py")
            .into_os_string(),
        root().join("python/pt_bridge/src").into_os_string(),
        input.into_os_string(),
        mode.into(),
    ];
    if mode == "timeout" {
        invocation.timeout = Duration::from_millis(400);
    }
    let report = supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap();
    let observation = reader.join().unwrap();
    let effect = tmp.path().join("performed-before-lost-completion").exists();
    (report, observation, effect)
}

#[test]
fn actual_python_wire_component_emits_all_eighteen_typed_shapes_over_the_native_owned_capability() {
    let expected = fixtures();
    let (process, read, effect) = wire(expected.clone(), "catalog");
    assert_eq!(process.exit_code(), 0, "{process:?}");
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert!(!effect);
    assert!(read.fault.is_none(), "{:?}", read.fault);
    assert!(read.end.is_some());
    assert_eq!(read.messages.len(), 18);
    for (sequence, (message, row)) in read.messages.iter().zip(expected).enumerate() {
        let value: Value = serde_json::from_slice(message.raw_json()).unwrap();
        assert_eq!(message.sequence(), sequence as u64);
        assert_eq!(value["kind"], row["kind"]);
        assert_eq!(value["payload"], row["payload"]);
    }
    assert!(
        matches!(read.messages[12].payload(),BridgePayload::Warning(value) if value.message.ends_with("λ 🐍"))
    );
}

#[test]
fn native_return_and_python_synthetic_failed_phases_remain_a_failed_backend_observation() {
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_failure"], &[0], "complete");
    trace.attempt(0, "passed", "failed", "passed");
    trace.terminal(1, "backend_exited");
    let rows = trace
        .rows
        .iter()
        .map(|(kind, payload)| json!({"kind":kind,"payload":payload}))
        .collect();
    let (process, read, effect) = wire(rows, "expected_failure");
    assert_eq!(
        process.leader_status,
        Some(LeaderStatus::Exited { code: 1 })
    );
    assert_eq!(process.exit_code(), 1);
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert!(!effect);
    assert!(read.fault.is_none());
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    for message in read.messages {
        ledger.apply(&message).unwrap();
    }
    let end = read.end.unwrap();
    assert!(ledger.validate_normal_exit(&end, 0).is_err());
    assert_eq!(
        ledger
            .validate_normal_exit(&end, 1)
            .unwrap()
            .phase_counts
            .call
            .failed,
        1
    );
}

#[test]
fn actual_partial_effects_and_clean_or_truncated_eof_do_not_recover_a_lost_component_completion() {
    for mode in ["abort", "truncated", "timeout"] {
        let (process, read, effect) = wire(
            vec![json!({"kind":"session_started","payload":handshake()})],
            mode,
        );
        assert!(effect, "{mode}");
        assert_eq!(process.cleanup, Cleanup::Complete);
        assert_eq!(read.messages.len(), 1);
        if mode == "timeout" {
            assert_eq!(process.termination, Termination::Timeout);
            assert_ne!(process.exit_code(), 0);
        } else {
            assert_eq!(
                process.leader_status,
                Some(LeaderStatus::Exited { code: 17 })
            );
            assert_eq!(process.exit_code(), 17);
        }
        let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
        for message in read.messages {
            ledger.apply(&message).unwrap();
        }
        assert!(ledger.snapshot().terminal.is_none());
        if mode == "abort" {
            assert!(read.fault.is_none());
            assert!(ledger.validate_normal_exit(&read.end.unwrap(), 17).is_err());
        } else {
            assert!(read.fault.as_deref().unwrap().contains("truncated"));
            assert!(read.end.is_none());
        }
    }
}
