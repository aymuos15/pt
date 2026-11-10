use super::*;
#[path = "../../../pt-protocol/tests/common/mod.rs"]
mod common;
use common::{Trace, contract, event, identity};
use pt_process::ProcessScope;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

struct Case {
    _temp: Option<tempfile::TempDir>,
    path: PathBuf,
}
impl Case {
    fn new(id: &str) -> Self {
        if let Some(parent) = std::env::var_os("PT_SESSION_CASE_ROOT") {
            let path = PathBuf::from(parent).join(id);
            fs::create_dir(&path).unwrap();
            Self { _temp: None, path }
        } else {
            let temp = tempfile::Builder::new()
                .prefix("pt-session-controls-")
                .tempdir_in("/tmp/opencode")
                .unwrap();
            let path = temp.path().to_path_buf();
            Self {
                _temp: Some(temp),
                path,
            }
        }
    }
    fn request(&self, mode: &str, rows: Vec<Value>) -> SerialRequest {
        let input = self.path.join("requested-synthetic-trace.json");
        fs::write(&input, serde_json::to_vec(&rows).unwrap()).unwrap();
        let mut process = process(&self.path);
        process.args = vec![
            "-I".into(),
            "-S".into(),
            "-B".into(),
            root()
                .join("crates/pt-session/tests/session_producer.py")
                .into_os_string(),
            mode.into(),
            input.into_os_string(),
        ];
        SerialRequest {
            process,
            identity: identity(),
            contract: contract(),
            stream_budget: StreamBudget {
                bytes: 1024 * 1024,
                events: 1024,
            },
            drain_allowance: Duration::from_millis(200),
        }
    }
    fn save(&self, observed: &SessionObservation) {
        fs::write(
            self.path.join("actual-process.json"),
            serde_json::to_vec_pretty(observed.process()).unwrap(),
        )
        .unwrap();
        fs::write(
            self.path.join("actual-observation.txt"),
            format!(
                "outcome={:?}\nchannel={:?}\nsnapshot={:#?}\nelapsed_ns={}\nqualified=false\n",
                observed.outcome(),
                observed.channel(),
                observed.snapshot(),
                observed.elapsed_ns()
            ),
        )
        .unwrap();
    }
}
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
fn process(cwd: &Path) -> ProcessRequest {
    ProcessRequest {
        executable: python(),
        args: vec![],
        cwd: cwd.into(),
        timeout: Duration::from_secs(4),
        cleanup_timeout: Duration::from_secs(1),
    }
}
fn passing() -> Trace {
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_one"], &[0], "complete");
    trace.attempt(0, "passed", "passed", "passed");
    trace.terminal(0, "backend_exited");
    trace
}
fn rows(trace: &Trace) -> Vec<Value> {
    trace
        .raw()
        .iter()
        .map(|raw| serde_json::from_slice(raw).unwrap())
        .collect()
}
fn partial() -> Trace {
    let mut trace = passing();
    trace.rows.truncate(
        trace
            .rows
            .iter()
            .position(|(kind, value)| kind == "phase_report" && value["phase"] == "call")
            .unwrap(),
    );
    trace
}
fn observe(case: &Case, request: SerialRequest) -> SessionObservation {
    let result = observe_serial(request, &AtomicI32::new(0)).unwrap();
    case.save(&result);
    assert_eq!(result.process().cleanup, Cleanup::Complete);
    result
}

#[test]
fn actual_owned_synthetic_success_and_failure_returns_have_necessary_accounting_only() {
    for code in [0, 1] {
        let case = Case::new(&format!("accounted-{code}"));
        let mut trace = passing();
        if code == 1 {
            trace = Trace::new();
            trace.collection(&["x.py::test_one"], &[0], "complete");
            trace.attempt(0, "passed", "failed", "passed");
            trace.terminal(1, "backend_exited");
        }
        let observed = observe(
            &case,
            case.request(
                if code == 0 { "complete" } else { "exit_one" },
                rows(&trace),
            ),
        );
        assert_eq!(
            observed.outcome(),
            &SessionOutcome::NormalExitAccounted {
                backend_exit_code: code
            }
        );
        assert!(observed.normal_snapshot().is_some());
        assert_eq!(observed.process().exit_code(), code);
        assert!(observed.channel().clean_eof);
        assert!(observed.channel().issue.is_none());
        assert_eq!(observed.snapshot().unwrap().accounting.completed_count, 1);
        assert!(observed.elapsed_ns() >= observed.process().elapsed_ns);
        assert_eq!(
            fs::read_to_string(case.path.join("started-once")).unwrap(),
            "one execution effect\n"
        );
    }
}

#[test]
fn clean_channel_eof_never_returns_before_actual_process_exit_or_finalizer_effects() {
    let case = Case::new("eof-before-process");
    let start = Instant::now();
    let observed = observe(&case, case.request("close_wait", rows(&passing())));
    assert_eq!(
        observed.outcome(),
        &SessionOutcome::NormalExitAccounted {
            backend_exit_code: 0
        }
    );
    assert!(start.elapsed() >= Duration::from_millis(200));
    assert_eq!(
        fs::read_to_string(case.path.join("late-finalizer")).unwrap(),
        "after channel EOF, before process return"
    );
}

#[test]
fn missing_terminal_despite_complete_looking_artifacts_or_completed_counts_is_never_a_pass() {
    for completed in [false, true] {
        let case = Case::new(if completed {
            "missing-terminal-completed"
        } else {
            "missing-terminal-partial"
        });
        let mut trace = passing();
        if completed {
            trace.rows.pop();
        } else {
            trace.rows.truncate(1);
        }
        let observed = observe(&case, case.request("early_zero", rows(&trace)));
        assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
        assert!(observed.normal_snapshot().is_none());
        assert_eq!(
            observed.channel().issue.as_ref().unwrap().kind,
            ChannelIssueKind::MissingTerminal
        );
        assert!(case.path.join("complete-looking.xml").exists());
        assert!(observed.snapshot().unwrap().terminal.is_none());
        assert_eq!(
            observed.snapshot().unwrap().accounting.completed_count,
            u64::from(completed)
        );
    }
}

#[test]
fn missing_terminal_and_closed_channel_stops_live_work_and_its_ordinary_descendant() {
    let case = Case::new("missing-terminal-live-descendant");
    let observed = observe(&case, case.request("clean_wait", rows(&Trace::new())));
    assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
    assert!(matches!(
        observed.process().termination,
        Termination::InfrastructureError { .. }
    ));
    assert!(observed.elapsed_ns() < 2_000_000_000);
    assert!(!observed.process().cleanup_signals.is_empty());
    let pid = fs::read_to_string(case.path.join("descendant.pid")).unwrap();
    if let Ok(raw) = fs::read_to_string(format!("/proc/{}/stat", pid.trim())) {
        assert!(matches!(
            raw.rsplit_once(')').unwrap().1.split_whitespace().next(),
            Some("Z" | "X" | "x")
        ));
    }
}

#[test]
fn malformed_or_budgeted_frames_and_ledger_faults_stop_live_execution_without_replay() {
    for mode in ["oversize", "bad_json", "sequence", "ledger", "flood"] {
        let case = Case::new(&format!("fault-{mode}"));
        let mut trace = Trace::new();
        if mode == "sequence" {
            let mut values = rows(&trace);
            values
                .push(serde_json::from_slice(&event(99, "collection_started", json!({}))).unwrap());
            let observed = observe(&case, case.request("wait_no_reader", values));
            assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
            continue;
        }
        if mode == "ledger" {
            trace.push("item_started", json!({"ordinal":0,"attempt":0}));
        }
        let mut request = case.request(
            if mode == "ledger" {
                "wait_no_reader"
            } else {
                mode
            },
            rows(&trace),
        );
        if mode == "flood" {
            request.stream_budget.events = 1;
        }
        let observed = observe(&case, request);
        assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
        assert!(observed.normal_snapshot().is_none());
        assert!(observed.elapsed_ns() < 2_000_000_000);
        assert_eq!(observed.snapshot().unwrap().accounting.executed_count, 0);
        if mode == "ledger" {
            assert_eq!(observed.channel().confirmed_frames, Some(2));
            assert_eq!(
                observed.channel().issue.as_ref().unwrap().kind,
                ChannelIssueKind::Ledger
            );
        }
    }
}

#[test]
fn timeout_and_actual_sigkill_keep_partial_phase_prefix_without_inventing_independent_protocol_errors()
 {
    for mode in ["timeout_partial", "signal_partial", "truncated_exit"] {
        let case = Case::new(mode);
        let mut request = case.request(mode, rows(&partial()));
        if mode == "timeout_partial" {
            request.process.timeout = Duration::from_millis(250);
        }
        let observed = observe(&case, request);
        assert!(observed.normal_snapshot().is_none());
        let snapshot = observed.snapshot().unwrap();
        assert_eq!(snapshot.accounting.executed_count, 1);
        assert_eq!(snapshot.accounting.completed_count, 0);
        assert_eq!(snapshot.incomplete_ordinals, vec![0]);
        assert!(snapshot.terminal.is_none());
        assert_eq!(
            observed.channel().issue.as_ref().unwrap().kind,
            ChannelIssueKind::Framing(ProtocolErrorKind::Truncated)
        );
        if mode == "timeout_partial" {
            assert_eq!(observed.outcome(), &SessionOutcome::Timeout);
            assert_eq!(observed.process().termination, Termination::Timeout);
        } else {
            assert_eq!(observed.outcome(), &SessionOutcome::BackendTerminated);
        }
    }
}

#[test]
fn cancellation_stays_interrupted_even_when_sigterm_is_handled_as_process_zero() {
    let case = Case::new("cancel-then-zero");
    let request = case.request("cancel_zero", rows(&partial()));
    let cancelled = AtomicI32::new(0);
    let observed = thread::scope(|scope| {
        let path = case.path.join("complete-looking.xml");
        let flag = &cancelled;
        scope.spawn(move || {
            let end = Instant::now() + Duration::from_secs(2);
            while !path.exists() && Instant::now() < end {
                thread::sleep(Duration::from_millis(5));
            }
            flag.store(15, Ordering::SeqCst);
        });
        observe_serial(request, &cancelled).unwrap()
    });
    case.save(&observed);
    assert_eq!(observed.process().cleanup, Cleanup::Complete);
    assert_eq!(
        observed.outcome(),
        &SessionOutcome::Interrupted { signal: 15 }
    );
    assert_eq!(
        observed.process().leader_status,
        Some(LeaderStatus::Exited { code: 0 })
    );
    assert!(observed.normal_snapshot().is_none());
}

#[test]
fn terminal_assertions_do_not_override_late_exit_mismatch_timeout_or_incomplete_reporting() {
    for mode in ["mismatch", "wait_no_reader", "incomplete-report"] {
        let case = Case::new(&format!("terminal-{mode}"));
        let mut trace = passing();
        if mode == "incomplete-report" {
            trace.rows.last_mut().unwrap().1["reporting_complete"] = json!(false);
        }
        let mut request = case.request(
            if mode == "incomplete-report" {
                "complete"
            } else {
                mode
            },
            rows(&trace),
        );
        if mode == "wait_no_reader" {
            request.process.timeout = Duration::from_millis(250);
        }
        let observed = observe(&case, request);
        assert!(observed.snapshot().unwrap().terminal.is_some());
        assert!(observed.normal_snapshot().is_none());
        if mode == "wait_no_reader" {
            assert_eq!(observed.outcome(), &SessionOutcome::Timeout);
        } else {
            assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
            assert_eq!(
                observed.channel().issue.as_ref().unwrap().kind,
                ChannelIssueKind::NormalExitMismatch
            );
        }
    }
}

#[test]
fn later_frames_after_terminal_and_non_pytest_exit_status_cannot_be_accounted_completion() {
    let case = Case::new("frame-after-terminal");
    let mut trace = passing();
    trace.push("warning", common::fixtures()[12]["payload"].clone());
    let observed = observe(&case, case.request("complete", rows(&trace)));
    assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
    assert!(observed.normal_snapshot().is_none());
    let case = Case::new("terminal-then-exit-17");
    let observed = observe(&case, case.request("exit_17", rows(&passing())));
    assert_eq!(observed.outcome(), &SessionOutcome::BackendTerminated);
    assert_eq!(
        observed.process().leader_status,
        Some(LeaderStatus::Exited { code: 17 })
    );
    assert!(observed.normal_snapshot().is_none());
}

#[test]
fn launch_and_prelaunch_cancellation_or_invalid_contract_never_start_or_reattach_work() {
    let case = Case::new("launch-failed");
    let mut request = case.request("complete", rows(&passing()));
    request.process.executable = "/definitely/absent/pt-session".into();
    let observed = observe_serial(request, &AtomicI32::new(0)).unwrap();
    case.save(&observed);
    assert_eq!(observed.outcome(), &SessionOutcome::LaunchFailed);
    assert_eq!(observed.process().cleanup, Cleanup::NotLaunched);
    assert!(!case.path.join("started-once").exists());
    let case = Case::new("prelaunch-cancelled");
    let observed = observe_serial(
        case.request("complete", rows(&passing())),
        &AtomicI32::new(2),
    )
    .unwrap();
    case.save(&observed);
    assert_eq!(
        observed.outcome(),
        &SessionOutcome::Interrupted { signal: 2 }
    );
    assert!(observed.process().pid.is_none());
    assert!(!case.path.join("started-once").exists());
    for mode in ["contract", "budget", "lifetime", "drain"] {
        let case = Case::new(&format!("invalid-{mode}"));
        let mut request = case.request("complete", rows(&passing()));
        match mode {
            "contract" => request.contract.max_items = 0,
            "budget" => request.stream_budget.bytes = 0,
            "lifetime" => request.process.timeout = Duration::from_secs(3600),
            _ => request.drain_allowance = Duration::ZERO,
        }
        let error = match observe_serial(request, &AtomicI32::new(0)) {
            Err(error) => error.to_string(),
            Ok(_) => panic!("invalid {mode} unexpectedly launched"),
        };
        fs::write(case.path.join("setup-rejection.json"),serde_json::to_vec_pretty(&json!({"status":"rejected_before_launch","error":error,"work_started":false,"qualified":false})).unwrap()).unwrap();
        assert!(!case.path.join("started-once").exists());
    }
}

#[test]
fn reader_panic_loses_its_snapshot_and_counters_and_cannot_recover_from_saved_files() {
    let case = Case::new("reader-panicked");
    let request = case.request("wait_no_reader", rows(&passing()));
    let observed = observe_with(request, &AtomicI32::new(0), |_, _, _, _| {
        panic!("explicit observer failure injection")
    })
    .unwrap();
    case.save(&observed);
    assert_eq!(observed.outcome(), &SessionOutcome::InfrastructureFailed);
    assert!(observed.snapshot().is_none());
    assert!(observed.normal_snapshot().is_none());
    assert_eq!(observed.channel().confirmed_frames, None);
    assert_eq!(observed.channel().confirmed_wire_bytes, None);
    assert_eq!(
        observed.channel().issue.as_ref().unwrap().kind,
        ChannelIssueKind::ObserverPanicked
    );
    assert!(matches!(
        observed.process().cleanup,
        Cleanup::Complete | Cleanup::NotLaunched
    ));
}

#[test]
fn ordinary_descendant_cleanup_and_raw_argument_environment_bytes_remain_owned_and_exact() {
    let case = Case::new("ordinary-descendant");
    let observed = observe(&case, case.request("descendant", rows(&passing())));
    assert!(observed.normal_snapshot().is_some());
    assert!(!observed.process().cleanup_signals.is_empty());
    let case = Case::new("exact-arguments");
    let mut request = case.request("args", rows(&passing()));
    use std::os::unix::ffi::OsStringExt;
    request.process.args.extend([
        "".into(),
        "λ a/b".into(),
        std::ffi::OsString::from_vec(vec![b'x', 0xff]),
    ]);
    let observed = observe(&case, request);
    assert!(observed.normal_snapshot().is_some());
    let argv: Value =
        serde_json::from_slice(&fs::read(case.path.join("arguments.json")).unwrap()).unwrap();
    assert_eq!(argv, json!(["", "cebb20612f62", "78ff"]));
    assert_eq!(
        fs::read_to_string(case.path.join("environment")).unwrap(),
        std::env::var("PT_SESSION_TEST_INHERITED").unwrap_or_else(|_| "absent".into())
    );
}

#[test]
fn explicit_known_stop_classification_keeps_incomplete_transport_secondary_but_real_corruption_primary()
 {
    let mut process = ProcessReport {
        schema_version: 1,
        scope: ProcessScope::ProcessOnly,
        pid: Some(1),
        termination: Termination::Timeout,
        leader_status: Some(LeaderStatus::Signaled {
            signal: 9,
            core_dumped: false,
        }),
        cleanup: Cleanup::Complete,
        cleanup_signals: vec![9],
        elapsed_ns: 1,
    };
    let mut channel = ChannelObservation {
        clean_eof: false,
        confirmed_frames: Some(1),
        confirmed_wire_bytes: Some(1),
        issue: Some(ChannelIssue {
            kind: ChannelIssueKind::Framing(ProtocolErrorKind::Truncated),
            detail: "partial bytes after actual timeout".into(),
        }),
    };
    assert_eq!(classify(&process, &channel), SessionOutcome::Timeout);
    channel.issue.as_mut().unwrap().kind =
        ChannelIssueKind::Framing(ProtocolErrorKind::InvalidData);
    assert_eq!(
        classify(&process, &channel),
        SessionOutcome::InfrastructureFailed
    );
    channel.issue = None;
    process.cleanup = Cleanup::Uncertain {
        detail: "synthetic cleanup uncertainty".into(),
    };
    assert_eq!(
        classify(&process, &channel),
        SessionOutcome::InfrastructureFailed
    );
}
