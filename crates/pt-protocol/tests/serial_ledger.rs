#![cfg(target_os = "linux")]
mod common;

use common::*;
use pt_protocol::{
    BridgeMessage, BridgeSnapshot, CollectionStatus, Disposition, FrameReader, MAX_EVENTS,
    MAX_STREAM_BYTES, NotRunReason, Outcome, RequestMode, SerialContract, SerialLedger,
    StreamBudget, StreamEnd, decode_bridge,
};
use serde_json::{Value, json};
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::thread;
use std::time::{Duration, Instant};

fn messages(trace: &Trace) -> (Vec<BridgeMessage>, StreamEnd) {
    let (parent, mut child) = UnixStream::pair().unwrap();
    child
        .set_write_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    let wire = trace
        .raw()
        .iter()
        .flat_map(|raw| frame(raw))
        .collect::<Vec<_>>();
    let writer = thread::spawn(move || child.write_all(&wire).unwrap());
    let mut reader = FrameReader::new(
        parent,
        identity(),
        StreamBudget {
            bytes: MAX_STREAM_BYTES,
            events: MAX_EVENTS,
        },
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut rows = Vec::new();
    while let Some(message) = reader.receive(deadline).unwrap() {
        rows.push(message);
    }
    writer.join().unwrap();
    (rows, reader.end_evidence().unwrap())
}

fn ledger(trace: &Trace, contract: SerialContract) -> (SerialLedger, StreamEnd) {
    let (messages, end) = messages(trace);
    let mut ledger = SerialLedger::new(identity(), contract).unwrap();
    for message in messages {
        ledger.apply(&message).unwrap();
    }
    (ledger, end)
}

fn normal(trace: &Trace, code: u8, contract: SerialContract) -> Result<BridgeSnapshot, String> {
    let (ledger, end) = ledger(trace, contract);
    ledger
        .validate_normal_exit(&end, code)
        .map_err(|error| error.to_string())
}

fn poison(prefix: &Trace, kind: &str, payload: Value) -> BridgeSnapshot {
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    for raw in prefix.raw() {
        ledger
            .apply(&decode_bridge(&raw, &identity()).unwrap())
            .unwrap();
    }
    let bad = decode_bridge(&event(prefix.rows.len() as u64, kind, payload), &identity()).unwrap();
    assert!(
        ledger.apply(&bad).is_err(),
        "expected ledger rejection: {kind}"
    );
    let otherwise_valid = decode_bridge(
        &event(
            prefix.rows.len() as u64,
            "warning",
            fixtures()[12]["payload"].clone(),
        ),
        &identity(),
    )
    .unwrap();
    assert!(
        ledger.apply(&otherwise_valid).is_err(),
        "fault cannot be resumed with another event"
    );
    let snapshot = ledger.snapshot();
    assert!(!snapshot.stream_consistent_so_far);
    snapshot
}

fn passing() -> Trace {
    let mut trace = Trace::new();
    trace.collection(&["test_x.py::test_one"], &[0], "complete");
    trace.attempt(0, "passed", "passed", "passed");
    trace.terminal(0, "backend_exited");
    trace
}

#[test]
fn duplicate_unicode_nodeids_keep_occurrences_and_the_backends_final_selection_order() {
    let mut trace = Trace::new();
    trace.collection(
        &[
            "λ.py::test_dup[x/y]",
            "λ.py::test_dup[x/y]",
            "deselected.py::test_unused",
        ],
        &[1, 0],
        "complete",
    );
    trace.attempt(1, "passed", "passed", "passed");
    trace.attempt(0, "passed", "passed", "passed");
    trace.terminal(0, "backend_exited");
    let snapshot = normal(&trace, 0, contract()).unwrap();
    assert_eq!(snapshot.nodeids.len(), 3);
    assert_eq!(snapshot.nodeids[0], snapshot.nodeids[1]);
    assert_eq!(snapshot.selected, vec![1, 0]);
    assert_eq!(snapshot.deselected, vec![2]);
    assert_eq!(
        snapshot
            .attempts
            .iter()
            .map(|value| value.ordinal)
            .collect::<Vec<_>>(),
        vec![1, 0]
    );
    assert_eq!(snapshot.accounting.executed_count, 2);
    assert_eq!(snapshot.accounting.completed_count, 2);
}

#[test]
fn setup_skip_or_failure_omits_call_but_never_the_required_teardown() {
    for (setup, code) in [("skipped", 0), ("failed", 1)] {
        let mut trace = Trace::new();
        trace.collection(&["test_x.py::test_one"], &[0], "complete");
        trace.attempt(0, setup, "must-not-have-call", "passed");
        trace.terminal(code, "backend_exited");
        let snapshot = normal(&trace, code, contract()).unwrap();
        assert_eq!(snapshot.attempts[0].phases.len(), 2);
        assert_eq!(snapshot.phase_counts.call.passed, 0);
        assert_eq!(snapshot.phase_counts.teardown.passed, 1);
        assert_eq!(snapshot.accounting.completed_count, 1);
    }
}

#[test]
fn teardown_failure_and_strict_xpass_are_retained_as_failed_phases_not_item_passes() {
    let mut trace = Trace::new();
    trace.collection(
        &["test_x.py::test_teardown", "test_x.py::test_xpass"],
        &[0, 1],
        "complete",
    );
    trace.attempt(0, "passed", "passed", "failed");
    trace.attempt(1, "passed", "failed", "passed");
    let report = &mut trace
        .rows
        .iter_mut()
        .find(|(kind, payload)| {
            kind == "phase_report" && payload["ordinal"] == 1 && payload["phase"] == "call"
        })
        .unwrap()
        .1;
    report["strict_xpass"] = json!(true);
    report["reason"] = json!("[XPASS(strict)] PT_REASON");
    trace.terminal(1, "backend_exited");
    let snapshot = normal(&trace, 1, contract()).unwrap();
    assert_eq!(snapshot.phase_counts.call.failed, 1);
    assert_eq!(snapshot.phase_counts.teardown.failed, 1);
    assert!(snapshot.attempts[1].phases[1].strict_xpass);
    assert_eq!(
        snapshot.attempts[1].phases[1].reason.as_deref(),
        Some("[XPASS(strict)] PT_REASON")
    );
    assert!(normal(&trace, 0, contract()).is_err());
}

#[test]
fn xfail_and_non_strict_xpass_reasons_survive_without_becoming_failures() {
    let mut trace = Trace::new();
    trace.collection(
        &["x.py::test_xfail", "x.py::test_xpass"],
        &[0, 1],
        "complete",
    );
    trace.attempt(0, "passed", "skipped", "passed");
    trace.attempt(1, "passed", "passed", "passed");
    for (kind, value) in &mut trace.rows {
        if kind == "phase_report" && value["phase"] == "call" {
            value["was_xfail"] = json!("PT_EXPECTED");
        }
    }
    trace.terminal(0, "backend_exited");
    let snapshot = normal(&trace, 0, contract()).unwrap();
    assert_eq!(snapshot.phase_counts.call.skipped, 1);
    assert_eq!(snapshot.phase_counts.call.passed, 1);
    assert!(
        snapshot
            .attempts
            .iter()
            .all(|value| value.phases[1].was_xfail.as_deref() == Some("PT_EXPECTED"))
    );
}

#[test]
fn fail_fast_explains_unstarted_work_but_does_not_relabel_started_work_or_allow_more_execution() {
    let mut trace = Trace::new();
    trace.collection(
        &["x.py::test_fail", "x.py::test_pending", "x.py::test_later"],
        &[0, 1, 2],
        "complete",
    );
    trace.attempt(0, "passed", "failed", "passed");
    trace.push("item_not_run", json!({"ordinal":1,"reason":"fail_fast"}));
    poison(&trace, "item_started", json!({"ordinal":2,"attempt":0}));
    poison(
        &trace,
        "item_not_run",
        json!({"ordinal":0,"reason":"fail_fast"}),
    );
    trace.push("item_not_run", json!({"ordinal":2,"reason":"fail_fast"}));
    trace.terminal(1, "backend_exited");
    let snapshot = normal(&trace, 1, contract()).unwrap();
    assert_eq!(snapshot.accounting.not_run_count, 2);
    assert!(snapshot.incomplete_ordinals.is_empty());
    assert!(
        snapshot
            .not_run
            .iter()
            .all(|value| value.reason == NotRunReason::FailFast)
    );
    let mut no_failure = Trace::new();
    no_failure.collection(&["x.py::test_one"], &[0], "complete");
    poison(
        &no_failure,
        "item_not_run",
        json!({"ordinal":0,"reason":"fail_fast"}),
    );
}

#[test]
fn collect_only_is_a_separate_request_and_requires_explicit_unexecuted_occurrences() {
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_one", "x.py::test_two"], &[0, 1], "complete");
    for ordinal in [0, 1] {
        trace.push(
            "item_not_run",
            json!({"ordinal":ordinal,"reason":"collect_only"}),
        );
    }
    trace.terminal(0, "backend_exited");
    let mut selected = contract();
    selected.mode = RequestMode::CollectOnly;
    let snapshot = normal(&trace, 0, selected).unwrap();
    assert_eq!(snapshot.accounting.executed_count, 0);
    assert_eq!(snapshot.accounting.not_run_count, 2);
    let mut execution = SerialLedger::new(
        identity(),
        SerialContract {
            mode: RequestMode::CollectOnly,
            ..contract()
        },
    )
    .unwrap();
    let mut prefix = Trace::new();
    prefix.collection(&["x.py::test_one"], &[0], "complete");
    for raw in prefix.raw() {
        execution
            .apply(&decode_bridge(&raw, &identity()).unwrap())
            .unwrap();
    }
    assert!(
        execution
            .apply(
                &decode_bridge(
                    &event(
                        prefix.rows.len() as u64,
                        "item_started",
                        json!({"ordinal":0,"attempt":0})
                    ),
                    &identity()
                )
                .unwrap()
            )
            .is_err()
    );
    poison(
        &prefix,
        "item_not_run",
        json!({"ordinal":0,"reason":"collect_only"}),
    );
}

#[test]
fn zero_selected_items_preserve_exit_five_not_empty_success_even_when_everything_is_deselected() {
    for nodeids in [vec![], vec!["x.py::test_deselected"]] {
        let mut trace = Trace::new();
        trace.collection(&nodeids, &[], "complete");
        trace.terminal(5, "backend_exited");
        assert_eq!(
            normal(&trace, 5, contract())
                .unwrap()
                .accounting
                .selected_count,
            0
        );
        assert!(normal(&trace, 0, contract()).is_err());
        let terminal = &mut trace.rows.last_mut().unwrap().1;
        terminal["backend_exit_code"] = json!(0);
        assert!(normal(&trace, 0, contract()).is_err());
    }
}

#[test]
fn failed_collection_requires_exact_error_mapping_and_incomplete_inventory() {
    let mut trace = Trace::new();
    trace.push("collection_started", json!({}));
    trace.push(
        "collection_report",
        json!({"report_id":17,"nodeid":"bad.py","outcome":"failed","reason":"PT_ERROR"}),
    );
    let barrier = json!({"status":"failed","inventory_complete":false,"collected_count":0,"selected_count":0,"deselected_count":0});
    poison(&trace, "collection_finished", barrier.clone());
    poison(
        &trace,
        "collection_error",
        json!({"report_id":17,"nodeid":"different.py","reason":"PT_ERROR"}),
    );
    trace.push(
        "collection_error",
        json!({"report_id":17,"nodeid":"bad.py","reason":"PT_ERROR"}),
    );
    poison(
        &trace,
        "collection_error",
        json!({"report_id":17,"nodeid":"bad.py","reason":"PT_ERROR"}),
    );
    trace.push("collection_finished", barrier);
    trace.terminal(2, "backend_exited");
    let snapshot = normal(&trace, 2, contract()).unwrap();
    assert_eq!(
        snapshot.collection.unwrap().status,
        CollectionStatus::Failed
    );
    assert_eq!(snapshot.collection_errors[0].reason, "PT_ERROR");
    assert_eq!(snapshot.collection_reports[0].report_id, 17);
    assert!(normal(&trace, 5, contract()).is_err());
}

#[test]
fn continue_after_collection_errors_can_execute_observed_items_but_cannot_make_inventory_complete()
{
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_one"], &[0], "failed");
    // Insert failed collector evidence before the collection barrier.
    trace.rows.insert(
        2,
        (
            "collection_report".into(),
            json!({"report_id":0,"nodeid":"bad.py","outcome":"failed","reason":"PT_COLLECT"}),
        ),
    );
    trace.rows.insert(
        3,
        (
            "collection_error".into(),
            json!({"report_id":0,"nodeid":"bad.py","reason":"PT_COLLECT"}),
        ),
    );
    trace.attempt(0, "passed", "passed", "passed");
    trace.terminal(1, "backend_exited");
    let snapshot = normal(&trace, 1, contract()).unwrap();
    assert!(!snapshot.collection.unwrap().inventory_complete);
    assert_eq!(snapshot.accounting.completed_count, 1);
}

#[test]
fn interruption_keeps_partial_phases_and_not_run_reasons_and_never_certifies_zero_or_ordinary_failure()
 {
    let mut trace = Trace::new();
    trace.collection(
        &["x.py::test_partial", "x.py::test_pending"],
        &[0, 1],
        "complete",
    );
    trace.push("item_started", json!({"ordinal":0,"attempt":0}));
    trace.push("phase_report", phase(0, "setup", "passed"));
    trace.push("attempt_finished",json!({"ordinal":0,"attempt":0,"disposition":"interrupted","reason":"PT_INTERRUPTED_BEFORE_CALL"}));
    trace.push("item_not_run", json!({"ordinal":1,"reason":"interrupted"}));
    trace.terminal(2, "interrupted");
    let snapshot = normal(&trace, 2, contract()).unwrap();
    assert_eq!(snapshot.incomplete_ordinals, vec![0]);
    assert_eq!(
        snapshot.attempts[0].disposition,
        Some(Disposition::Interrupted)
    );
    assert_eq!(
        snapshot.attempts[0].reason.as_deref(),
        Some("PT_INTERRUPTED_BEFORE_CALL")
    );
    assert_eq!(snapshot.accounting.attempts_completed, 0);
    assert!(normal(&trace, 0, contract()).is_err());
    let terminal = &mut trace.rows.last_mut().unwrap().1;
    terminal["backend_exit_code"] = json!(1);
    terminal["termination"] = json!("backend_exited");
    assert!(normal(&trace, 1, contract()).is_err());
}

#[test]
fn missing_terminal_or_unexplained_missing_work_remains_incomplete_after_real_clean_eof() {
    let mut trace = passing();
    trace.rows.pop();
    let (ledger, end) = ledger(&trace, contract());
    assert!(ledger.validate_normal_exit(&end, 0).is_err());
    assert!(ledger.snapshot().terminal.is_none());
    assert_eq!(ledger.snapshot().accounting.completed_count, 1);
    let mut partial = Trace::new();
    partial.collection(
        &["x.py::test_fail", "x.py::test_missing"],
        &[0, 1],
        "complete",
    );
    partial.attempt(0, "passed", "failed", "passed");
    partial.terminal(1, "backend_exited");
    assert!(
        normal(&partial, 1, contract())
            .unwrap_err()
            .contains("incomplete")
    );
}

#[test]
fn terminal_arithmetic_phase_counts_and_incomplete_lists_must_match_independent_observations() {
    let trace = passing();
    let terminal = trace.rows.last().unwrap().1.clone();
    let mut prefix = trace.clone();
    prefix.rows.pop();
    for field in [
        "collected_count",
        "selected_count",
        "deselected_count",
        "executed_count",
        "completed_count",
        "not_run_count",
        "attempts_started",
        "attempts_completed",
    ] {
        let mut bad = terminal.clone();
        bad["accounting"][field] = json!(999);
        poison(&prefix, "session_terminated", bad);
    }
    for phase in ["setup", "call", "teardown"] {
        for outcome in ["passed", "failed", "skipped"] {
            let mut bad = terminal.clone();
            bad["phase_counts"][phase][outcome] = json!(999);
            poison(&prefix, "session_terminated", bad);
        }
    }
    let mut bad = terminal;
    bad["incomplete_ordinals"] = json!([0]);
    poison(&prefix, "session_terminated", bad);
    poison(&trace, "warning", fixtures()[12]["payload"].clone());
}

#[test]
fn collection_chunks_ordinals_partition_and_barriers_are_not_optional() {
    poison(
        &Trace::new(),
        "item_started",
        json!({"ordinal":0,"attempt":0}),
    );
    poison(
        &Trace::new(),
        "collection_report",
        json!({"report_id":0,"nodeid":"x","outcome":"passed","reason":null}),
    );
    let mut trace = Trace::new();
    trace.push("collection_started", json!({}));
    poison(&trace, "item_collected", json!({"ordinal":1,"nodeid":"x"}));
    trace.push("item_collected", json!({"ordinal":0,"nodeid":"x"}));
    poison(&trace, "items_selected", json!({"chunk":1,"ordinals":[0]}));
    poison(&trace, "items_selected", json!({"chunk":0,"ordinals":[1]}));
    poison(
        &trace,
        "collection_finished",
        json!({"status":"complete","inventory_complete":true,"collected_count":1,"selected_count":0,"deselected_count":0}),
    );
    trace.push("items_selected", json!({"chunk":0,"ordinals":[0]}));
    poison(
        &trace,
        "item_collected",
        json!({"ordinal":1,"nodeid":"late"}),
    );
    poison(
        &trace,
        "items_deselected",
        json!({"chunk":0,"ordinals":[0],"reason":null}),
    );
    poison(&trace, "items_selected", json!({"chunk":0,"ordinals":[]}));
}

#[test]
fn overlap_reordered_execution_retries_extensions_and_phase_omissions_are_permanent_faults() {
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_one", "x.py::test_two"], &[0, 1], "complete");
    poison(&trace, "item_started", json!({"ordinal":1,"attempt":0}));
    poison(&trace, "item_started", json!({"ordinal":0,"attempt":1}));
    poison(&trace, "extension_event", fixtures()[16]["payload"].clone());
    trace.push("item_started", json!({"ordinal":0,"attempt":0}));
    poison(&trace, "item_started", json!({"ordinal":1,"attempt":0}));
    poison(&trace, "phase_report", phase(0, "call", "passed"));
    poison(
        &trace,
        "attempt_finished",
        json!({"ordinal":0,"attempt":0,"disposition":"completed","reason":null}),
    );
    trace.push("phase_report", phase(0, "setup", "passed"));
    poison(&trace, "phase_report", phase(0, "teardown", "passed"));
    trace.push("phase_report", phase(0, "call", "failed"));
    trace.push("phase_report", phase(0, "teardown", "passed"));
    poison(&trace, "phase_report", phase(0, "teardown", "passed"));
    poison(
        &trace,
        "attempt_finished",
        json!({"ordinal":0,"attempt":0,"disposition":"retry","reason":"PT_NO_REPLAY"}),
    );
}

#[test]
fn artifact_readiness_remains_a_claim_not_file_verification_or_commit() {
    let mut trace = passing();
    let terminal = trace.rows.pop().unwrap();
    trace.push("artifact_ready", fixtures()[14]["payload"].clone());
    trace.rows.push(terminal);
    let snapshot = normal(&trace, 0, contract()).unwrap();
    assert_eq!(snapshot.artifact_ready_claims.len(), 1);
    assert!(!snapshot.artifact_ready_claims[0].complete);
    let mut prefix = Trace::new();
    poison(
        &prefix,
        "artifact_ready",
        json!({"artifact_id":"undeclared","sha256":"a".repeat(64),"bytes":0,"complete":true}),
    );
    prefix.push("artifact_ready", fixtures()[14]["payload"].clone());
    poison(&prefix, "artifact_ready", fixtures()[14]["payload"].clone());
    poison(
        &prefix,
        "output_reference",
        json!({"artifact_id":"stdout-1","stream":"stdout","ordinal":0,"attempt":0}),
    );
}

#[test]
fn internal_usage_infrastructure_and_unknown_backend_exits_cannot_be_coerced_to_normal_zero() {
    for (category, code, termination) in [
        ("internal", 3, "backend_exited"),
        ("usage", 4, "backend_exited"),
        ("infrastructure", 3, "infrastructure_failed"),
    ] {
        let mut trace = Trace::new();
        trace.push(
            "session_error",
            json!({"category":category,"code":"PT_ERROR","message":"PT_DETAIL"}),
        );
        trace.terminal(code, termination);
        let snapshot = normal(&trace, code, contract()).unwrap();
        assert_eq!(snapshot.session_errors[0].message, "PT_DETAIL");
        assert!(normal(&trace, 0, contract()).is_err());
    }
    for code in [0, 1, 2, 3, 4, 5, 7, 255] {
        let mut trace = Trace::new();
        trace.terminal(code, "backend_exited");
        assert!(normal(&trace, code, contract()).is_err());
    }
    let mut no_tests = Trace::new();
    no_tests.collection(&[], &[], "failed");
    no_tests.terminal(5, "backend_exited");
    assert!(normal(&no_tests, 5, contract()).is_err());
    let mut interrupted = passing();
    interrupted.rows.last_mut().unwrap().1["termination"] = json!("interrupted");
    assert!(normal(&interrupted, 0, contract()).is_err());
}

#[test]
fn incomplete_reporting_and_handshake_or_profile_mismatch_cannot_be_ignored() {
    let mut trace = passing();
    trace.rows.last_mut().unwrap().1["reporting_complete"] = json!(false);
    assert!(normal(&trace, 0, contract()).is_err());
    poison(&Trace::new(), "session_started", handshake());
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    assert!(
        ledger
            .apply(&decode_bridge(&event(0, "collection_started", json!({})), &identity()).unwrap())
            .is_err()
    );
    let mut payload = handshake();
    payload["invocation_profile"] = json!("pytest_console");
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    assert!(
        ledger
            .apply(&decode_bridge(&event(0, "session_started", payload), &identity()).unwrap())
            .is_err()
    );
}

#[test]
fn unframed_messages_or_another_identical_streams_eof_cannot_supply_completion_evidence() {
    let trace = passing();
    let (rows, end) = messages(&trace);
    let (_, unrelated) = messages(&trace);
    let mut from_wire = SerialLedger::new(identity(), contract()).unwrap();
    let mut from_decoded = SerialLedger::new(identity(), contract()).unwrap();
    for message in rows {
        from_wire.apply(&message).unwrap();
        from_decoded
            .apply(&decode_bridge(message.raw_json(), &identity()).unwrap())
            .unwrap();
    }
    assert!(from_wire.validate_normal_exit(&unrelated, 0).is_err());
    assert!(from_wire.validate_normal_exit(&end, 0).is_ok());
    assert!(from_decoded.validate_normal_exit(&end, 0).is_err());
    let (left, _) = messages(&trace);
    let (right, _) = messages(&trace);
    let mut mixed = SerialLedger::new(identity(), contract()).unwrap();
    mixed.apply(&left[0]).unwrap();
    assert!(mixed.apply(&right[1]).is_err());
    assert!(!mixed.snapshot().stream_consistent_so_far);
}

#[test]
fn missing_consumed_frames_identity_and_sequence_cannot_be_repaired_from_an_eof() {
    let trace = passing();
    let (rows, end) = messages(&trace);
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    ledger.apply(&rows[0]).unwrap();
    assert!(ledger.validate_normal_exit(&end, 0).is_err());
    assert!(ledger.apply(&rows[2]).is_err());
    assert!(ledger.apply(&rows[1]).is_err());
    let mut ledger = SerialLedger::new(identity(), contract()).unwrap();
    let mut foreign = identity();
    foreign.generation_id = "different".into();
    let mut raw = envelope(0, "session_started", handshake());
    raw["generation_id"] = json!("different");
    let message = decode_bridge(&serde_json::to_vec(&raw).unwrap(), &foreign).unwrap();
    assert!(ledger.apply(&message).is_err());
}

#[test]
fn collector_report_and_error_order_are_preserved_without_sorting_opaque_report_ids() {
    let mut trace = Trace::new();
    trace.push("collection_started", json!({}));
    for report_id in [19, 3, 7] {
        trace.push(
            "collection_report",
            json!({"report_id":report_id,"nodeid":"bad.py","outcome":"failed","reason":"PT_ERROR"}),
        );
        trace.push(
            "collection_error",
            json!({"report_id":report_id,"nodeid":"bad.py","reason":"PT_ERROR"}),
        );
    }
    trace.push("collection_finished",json!({"status":"failed","inventory_complete":false,"collected_count":0,"selected_count":0,"deselected_count":0}));
    trace.terminal(2, "backend_exited");
    let snapshot = normal(&trace, 2, contract()).unwrap();
    assert_eq!(
        snapshot
            .collection_reports
            .iter()
            .map(|value| value.report_id)
            .collect::<Vec<_>>(),
        vec![19, 3, 7]
    );
    assert_eq!(
        snapshot
            .collection_errors
            .iter()
            .map(|value| value.report_id)
            .collect::<Vec<_>>(),
        vec![19, 3, 7]
    );
}

#[test]
fn coordinator_item_report_nodeid_and_error_summary_limits_are_explicit_and_fail_closed() {
    let mut limited = SerialLedger::new(
        identity(),
        SerialContract {
            max_collection_reports: 1,
            ..contract()
        },
    )
    .unwrap();
    let mut prefix = Trace::new();
    prefix.push("collection_started", json!({}));
    prefix.push(
        "collection_report",
        json!({"report_id":0,"nodeid":"x","outcome":"passed","reason":null}),
    );
    for raw in prefix.raw() {
        limited
            .apply(&decode_bridge(&raw, &identity()).unwrap())
            .unwrap();
    }
    assert!(
        limited
            .apply(
                &decode_bridge(
                    &event(
                        prefix.rows.len() as u64,
                        "collection_report",
                        json!({"report_id":1,"nodeid":"y","outcome":"passed","reason":null})
                    ),
                    &identity()
                )
                .unwrap()
            )
            .is_err()
    );
    for selected in [
        SerialContract {
            max_items: 0,
            ..contract()
        },
        SerialContract {
            max_collection_reports: 100_001,
            ..contract()
        },
        SerialContract {
            max_nodeid_bytes: 16 * 1024 * 1024 + 1,
            ..contract()
        },
        SerialContract {
            declared_artifact_ids: vec!["a".into(), "a".into()],
            ..contract()
        },
    ] {
        assert!(SerialLedger::new(identity(), selected).is_err());
    }
    let mut trace = Trace::new();
    trace.push("collection_started", json!({}));
    trace.push("item_collected", json!({"ordinal":0,"nodeid":"λ"}));
    for selected in [
        SerialContract {
            max_items: 1,
            ..contract()
        },
        SerialContract {
            max_nodeid_bytes: 2,
            ..contract()
        },
    ] {
        let mut ledger = SerialLedger::new(identity(), selected).unwrap();
        for raw in trace.raw() {
            ledger
                .apply(&decode_bridge(&raw, &identity()).unwrap())
                .unwrap();
        }
        assert!(
            ledger
                .apply(
                    &decode_bridge(
                        &event(
                            trace.rows.len() as u64,
                            "item_collected",
                            json!({"ordinal":1,"nodeid":"x"})
                        ),
                        &identity()
                    )
                    .unwrap()
                )
                .is_err()
        );
        assert_eq!(ledger.snapshot().nodeids, vec!["λ"]);
    }
    let mut trace = Trace::new();
    for _ in 0..1024 {
        trace.push(
            "session_error",
            json!({"category":"internal","code":"PT_ERROR","message":"PT_RETAINED"}),
        );
    }
    let snapshot = poison(
        &trace,
        "session_error",
        json!({"category":"internal","code":"PT_ERROR","message":"too many"}),
    );
    assert_eq!(snapshot.session_errors.len(), 1024);
    assert_eq!(snapshot.session_error_count, 1024);
    assert!(
        snapshot
            .session_errors
            .iter()
            .all(|value| value.message == "PT_RETAINED")
    );
    assert!(snapshot.attempts.iter().all(|value| {
        value
            .phases
            .iter()
            .all(|phase| phase.outcome != Outcome::Failed)
    }));
}
