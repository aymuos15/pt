#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod common;

use common::*;
use pt_process::{Cleanup, ProcessRequest, control_channel_pair, supervise_with_control};
use pt_protocol::{
    BridgeSnapshot, FrameReader, SerialContract, SerialLedger, StreamBudget, StreamEnd,
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
fn python() -> PathBuf {
    std::env::var_os("PT_OBSERVER_TEST_PYTHON")
        .or_else(|| std::env::var_os("PT_TEST_PYTHON"))
        .map(PathBuf::from)
        .unwrap_or_else(|| root().join("bench/harness/.venv/bin/python"))
}

struct Observed {
    process: pt_process::ProcessReport,
    ledger: SerialLedger,
    end: Option<StreamEnd>,
    rows: Vec<Value>,
    fault: Option<String>,
}

fn invoke(
    work: &Path,
    args: &[&str],
    mode: pt_protocol::RequestMode,
    max_items: usize,
) -> Observed {
    let (parent, control) = control_channel_pair().unwrap();
    let contract = SerialContract {
        mode,
        max_items,
        ..contract()
    };
    let reader = thread::spawn(move || {
        let mut reader = FrameReader::new(
            parent,
            identity(),
            StreamBudget {
                bytes: 8 * 1024 * 1024,
                events: 25000,
            },
        )
        .unwrap();
        let mut ledger = SerialLedger::new(identity(), contract).unwrap();
        let mut rows = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(30);
        let fault = loop {
            match reader.receive(deadline) {
                Ok(Some(message)) => {
                    rows.push(serde_json::from_slice(message.raw_json()).unwrap());
                    if let Err(error) = ledger.apply(&message) {
                        break Some(error.to_string());
                    }
                }
                Ok(None) => break None,
                Err(error) => break Some(error.to_string()),
            }
        };
        (ledger, reader.end_evidence(), rows, fault)
    });
    let id = identity();
    let configuration = json!({"schema_version":1,"fd":3,"identity":{"request_id":id.request_id,"run_id":id.run_id,
        "generation_id":id.generation_id,"session_id":id.session_id,"producer_id":id.producer_id},
        "invocation_profile":"pytest_module","mode":if mode==pt_protocol::RequestMode::Run {"run"}else{"collect_only"},
        "max_items":max_items,"max_collection_reports":1024,"max_nodeid_bytes":1024*1024,
        "byte_budget":8*1024*1024,"event_budget":25000,"timeout_seconds":25});
    // This env executable is a test-only direct exec wrapper, not a shell,
    // product launcher or timing arm. No dependency is installed or suppressed.
    let mut argv = vec![
        format!("PT_BRIDGE_CONTROL={configuration}").into(),
        format!(
            "PYTHONPATH={}",
            root().join("python/pt_bridge/src").display()
        )
        .into(),
        "PYTHONDONTWRITEBYTECODE=1".into(),
        python().into_os_string(),
        "-m".into(),
        "pytest".into(),
        "-q".into(),
        "-p".into(),
        "pt_bridge.pytest_observer".into(),
    ];
    argv.extend(args.iter().map(std::ffi::OsString::from));
    let request = ProcessRequest {
        executable: "/usr/bin/env".into(),
        args: argv,
        cwd: work.into(),
        timeout: Duration::from_secs(25),
        cleanup_timeout: Duration::from_secs(1),
    };
    let process = supervise_with_control(&request, &AtomicI32::new(0), control).unwrap();
    let (ledger, end, rows, fault) = reader.join().unwrap();
    Observed {
        process,
        ledger,
        end,
        rows,
        fault,
    }
}

fn checked(observed: &Observed, code: u8) -> BridgeSnapshot {
    assert_eq!(observed.process.exit_code(), code, "{:?}", observed.process);
    assert_eq!(observed.process.cleanup, Cleanup::Complete);
    assert!(observed.fault.is_none(), "{:?}", observed.fault);
    observed
        .ledger
        .validate_normal_exit(observed.end.as_ref().expect("actual clean EOF"), code)
        .unwrap()
}

#[test]
fn actual_same_session_pytest_preserves_one_import_shared_fixture_globals_and_failures_over_native_ipc()
 {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(
        tmp.path().join("test_actual.py"),
        r#"
from pathlib import Path
import pytest
def effect(value):
    with Path('effects').open('a') as output: output.write(value+'\n')
effect('import')
state=0
@pytest.fixture(scope='module',autouse=True)
def shared():
    effect('setup')
    yield
    effect('teardown')
def test_first():
    global state
    state+=1
    assert state==1
    effect('first')
def test_second():
    assert state==1
    effect('second')
    assert False, 'PT_NATIVE_ASSERTION'
"#,
    )
    .unwrap();
    let observed = invoke(
        tmp.path(),
        &["test_actual.py"],
        pt_protocol::RequestMode::Run,
        256,
    );
    let snapshot = checked(&observed, 1);
    assert_eq!(snapshot.accounting.completed_count, 2);
    assert_eq!(snapshot.phase_counts.call.failed, 1);
    assert_eq!(
        fs::read_to_string(tmp.path().join("effects")).unwrap(),
        "import\nsetup\nfirst\nsecond\nteardown\n"
    );
    assert!(
        snapshot.attempts[1].phases[1]
            .reason
            .as_deref()
            .unwrap()
            .contains("PT_NATIVE_ASSERTION")
    );
}

#[test]
fn native_ledger_follows_final_backend_selection_order_without_a_second_collection() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-order-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(
        tmp.path().join("conftest.py"),
        "def pytest_collection_modifyitems(items):\n    items.reverse()\n",
    )
    .unwrap();
    fs::write(tmp.path().join("test_order.py"),"from pathlib import Path\ndef test_first():\n    assert Path('second-was-first').exists()\ndef test_second():\n    Path('second-was-first').touch()\n").unwrap();
    let snapshot = checked(
        &invoke(
            tmp.path(),
            &["test_order.py"],
            pt_protocol::RequestMode::Run,
            256,
        ),
        0,
    );
    assert_eq!(snapshot.selected, vec![1, 0]);
    assert_eq!(snapshot.accounting.completed_count, 2);
}

#[test]
fn actual_collect_only_fail_fast_and_empty_requests_keep_their_distinct_native_accounting() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-modes-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(tmp.path().join("test_modes.py"),"from pathlib import Path\ndef test_failure():\n    Path('first-ran').touch()\n    assert False, 'PT_FAILFAST'\ndef test_not_run():\n    Path('second-ran').touch()\n").unwrap();
    let collect = checked(
        &invoke(
            tmp.path(),
            &["--collect-only", "test_modes.py"],
            pt_protocol::RequestMode::CollectOnly,
            256,
        ),
        0,
    );
    assert_eq!(collect.accounting.not_run_count, 2);
    assert_eq!(collect.accounting.executed_count, 0);
    assert!(!tmp.path().join("first-ran").exists());
    let fail = checked(
        &invoke(
            tmp.path(),
            &["-x", "test_modes.py"],
            pt_protocol::RequestMode::Run,
            256,
        ),
        1,
    );
    assert_eq!(fail.accounting.not_run_count, 1);
    assert!(!tmp.path().join("second-ran").exists());
    let empty = checked(
        &invoke(
            tmp.path(),
            &["-k", "does_not_exist", "test_modes.py"],
            pt_protocol::RequestMode::Run,
            256,
        ),
        5,
    );
    assert_eq!(empty.accounting.selected_count, 0);
    assert_eq!(empty.accounting.deselected_count, 2);
}

#[test]
fn an_actual_outer_unconfigure_wrapper_still_runs_but_cannot_supply_reporting_complete() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-finalizer-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(tmp.path().join("conftest.py"),"import pytest\nfrom pathlib import Path\n@pytest.hookimpl(wrapper=True,tryfirst=True)\ndef pytest_unconfigure(config):\n    value=yield\n    Path('outer-cleanup').touch()\n    return value\n").unwrap();
    fs::write(
        tmp.path().join("test_pass.py"),
        "def test_pass():\n    pass\n",
    )
    .unwrap();
    let observed = invoke(
        tmp.path(),
        &["test_pass.py"],
        pt_protocol::RequestMode::Run,
        256,
    );
    assert_eq!(observed.process.exit_code(), 0);
    assert_eq!(observed.process.cleanup, Cleanup::Complete);
    assert!(tmp.path().join("outer-cleanup").exists());
    assert!(observed.fault.is_none());
    assert!(
        observed
            .rows
            .iter()
            .any(|row| row["kind"] == "session_error"
                && row["payload"]["code"] == "unconfigure_wrapper_order_unsupported")
    );
    assert!(
        observed
            .ledger
            .validate_normal_exit(&observed.end.unwrap(), 0)
            .is_err()
    );
    assert!(
        !observed
            .ledger
            .snapshot()
            .terminal
            .unwrap()
            .reporting_complete
    );
}

#[test]
fn actual_keyboard_interrupt_retains_an_incomplete_attempt_instead_of_a_pass() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-interrupt-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(tmp.path().join("test_interrupt.py"),"from pathlib import Path\ndef test_interrupt():\n    with Path('started-once').open('x') as output: output.write('effect before interruption')\n    raise KeyboardInterrupt('PT_NATIVE_INTERRUPT')\n").unwrap();
    let observed = invoke(
        tmp.path(),
        &["test_interrupt.py"],
        pt_protocol::RequestMode::Run,
        256,
    );
    let snapshot = checked(&observed, 2);
    assert_eq!(snapshot.accounting.executed_count, 1);
    assert_eq!(snapshot.accounting.completed_count, 0);
    assert_eq!(snapshot.incomplete_ordinals, vec![0]);
    assert!(
        snapshot.attempts[0]
            .phases
            .iter()
            .all(|phase| phase.phase == pt_protocol::Phase::Setup)
    );
    assert_eq!(
        fs::read_to_string(tmp.path().join("started-once")).unwrap(),
        "effect before interruption"
    );
}

#[test]
fn actual_worker_death_after_effects_keeps_raw_signal_and_partial_observation_without_replay() {
    let tmp = tempfile::Builder::new()
        .prefix("pt-native-pytest-death-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    fs::write(tmp.path().join("test_death.py"),"import os,signal\nfrom pathlib import Path\ndef test_death():\n    with Path('started-once').open('x') as output: output.write('effect before death')\n    os.kill(os.getpid(),signal.SIGKILL)\n").unwrap();
    let observed = invoke(
        tmp.path(),
        &["test_death.py"],
        pt_protocol::RequestMode::Run,
        256,
    );
    assert_eq!(
        observed.process.termination,
        pt_process::Termination::BackendTerminated
    );
    assert_eq!(
        observed.process.leader_status,
        Some(pt_process::LeaderStatus::Signaled {
            signal: 9,
            core_dumped: false
        })
    );
    assert_eq!(observed.process.cleanup, Cleanup::Complete);
    assert!(observed.fault.is_none());
    let snapshot = observed.ledger.snapshot();
    assert!(snapshot.terminal.is_none());
    assert_eq!(snapshot.incomplete_ordinals, vec![0]);
    assert!(
        observed
            .ledger
            .validate_normal_exit(&observed.end.unwrap(), 0)
            .is_err()
    );
    assert_eq!(
        fs::read_to_string(tmp.path().join("started-once")).unwrap(),
        "effect before death"
    );
}
