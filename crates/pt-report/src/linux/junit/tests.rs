//! Independent literal report controls. Synthetic snapshots are explicitly test
//! data, not native completion receipts or qualification evidence.
use super::*;
use pt_protocol::{
    AttemptObservation, CollectionFinished, CollectionReport, PhaseReport, SessionTerminal,
};
use serde_json::json;
use std::time::Duration;

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
fn limits() -> JunitLimits {
    JunitLimits {
        bytes: 1024 * 1024,
        testcases: 256,
        events: 10000,
    }
}
fn policy() -> JunitPolicy {
    JunitPolicy::xunit2("pytest".into(), None, limits()).unwrap()
}

pub(in crate::linux) fn passing_snapshot() -> BridgeSnapshot {
    snapshot(
        &["test_x.py::test_first"],
        &[["passed", "passed", "passed"]],
    )
}

fn snapshot(nodeids: &[&str], outcomes: &[[&str; 3]]) -> BridgeSnapshot {
    assert_eq!(nodeids.len(), outcomes.len());
    let mut phases = PhaseCounts::default();
    let mut attempts = Vec::new();
    for (ordinal, values) in outcomes.iter().enumerate() {
        let mut reports = Vec::new();
        for (index, when) in ["setup", "call", "teardown"].into_iter().enumerate() {
            if index == 1 && values[0] != "passed" {
                continue;
            }
            let outcome = values[index];
            let cell = match index {
                0 => &mut phases.setup,
                1 => &mut phases.call,
                _ => &mut phases.teardown,
            };
            match outcome {
                "passed" => cell.passed += 1,
                "failed" => cell.failed += 1,
                "skipped" => cell.skipped += 1,
                _ => panic!("bad test input"),
            }
            reports.push(serde_json::from_value::<PhaseReport>(json!({"ordinal":ordinal,"attempt":0,"phase":when,"outcome":outcome,
                "reason":if outcome=="failed" {Some("PT_FAILURE")}else if outcome=="skipped" {Some("Skipped: PT_SKIP")}else{None},
                "was_xfail":null,"strict_xpass":false,"duration_ns":1,"artifact_ids":[]})).unwrap());
        }
        attempts.push(AttemptObservation {
            ordinal: ordinal as u64,
            phases: reports,
            disposition: Some(Disposition::Completed),
            reason: None,
        });
    }
    let accounting = Accounting {
        collected_count: nodeids.len() as u64,
        selected_count: nodeids.len() as u64,
        deselected_count: 0,
        executed_count: nodeids.len() as u64,
        completed_count: nodeids.len() as u64,
        not_run_count: 0,
        attempts_started: nodeids.len() as u64,
        attempts_completed: nodeids.len() as u64,
    };
    let code = if phases.setup.failed + phases.call.failed + phases.teardown.failed > 0 {
        1
    } else if nodeids.is_empty() {
        5
    } else {
        0
    };
    BridgeSnapshot {
        stream_consistent_so_far: true,
        handshake_seen: true,
        collection: Some(CollectionFinished {
            status: CollectionStatus::Complete,
            inventory_complete: true,
            collected_count: nodeids.len() as u64,
            selected_count: nodeids.len() as u64,
            deselected_count: 0,
        }),
        nodeids: nodeids.iter().map(|value| (*value).into()).collect(),
        selected: (0..nodeids.len() as u64).collect(),
        deselected: vec![],
        accounting: accounting.clone(),
        phase_counts: phases.clone(),
        incomplete_ordinals: vec![],
        session_error_count: 0,
        terminal: Some(SessionTerminal {
            termination: SessionTermination::BackendExited,
            backend_exit_code: Some(code),
            reporting_complete: true,
            accounting,
            phase_counts: phases,
            incomplete_ordinals: vec![],
        }),
        artifact_ready_claims: vec![],
        collection_reports: vec![],
        collection_errors: vec![],
        attempts,
        not_run: vec![],
        session_errors: vec![],
    }
}

fn expected(snapshot: &BridgeSnapshot) -> JunitExpectation {
    JunitExpectation::from_snapshot(policy(), snapshot, deadline()).unwrap()
}
fn report(tests: u64, failures: u64, errors: u64, skipped: u64, rows: &str) -> String {
    format!(
        "{DECLARATION}<testsuites name=\"pytest tests\"><testsuite name=\"pytest\" errors=\"{errors}\" failures=\"{failures}\" skipped=\"{skipped}\" tests=\"{tests}\" time=\"0.001\" timestamp=\"2026-11-10T12:34:56.123456+00:00\" hostname=\"test-host\">{rows}</testsuite></testsuites>"
    )
}
pub(in crate::linux) fn passing_xml() -> String {
    report(
        1,
        0,
        0,
        0,
        "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\" />",
    )
}
fn rejects(expectation: &JunitExpectation, raw: impl AsRef<[u8]>) {
    let raw = raw.as_ref();
    assert!(
        expectation.validate(raw, deadline()).is_err(),
        "unexpected acceptance: {}",
        String::from_utf8_lossy(raw)
    );
}

#[test]
fn literal_pass_and_actual_empty_formatter_boundaries_are_valid() {
    let expectation = expected(&passing_snapshot());
    expectation
        .validate(passing_xml().as_bytes(), deadline())
        .unwrap();
    let empty = expected(&snapshot(&[], &[]));
    let explicit = report(0, 0, 0, 0, "");
    empty.validate(explicit.as_bytes(), deadline()).unwrap();
    let compact = explicit.replace("></testsuite>", " />");
    empty.validate(compact.as_bytes(), deadline()).unwrap();
    rejects(&expectation, &compact);
    rejects(&empty, passing_xml());
}

#[test]
fn missing_adverse_outcome_is_rejected_for_both_empty_and_explicit_testcase_syntax() {
    let expectation = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["passed", "failed", "passed"]],
    ));
    let valid = report(
        1,
        1,
        0,
        0,
        "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><failure message=\"PT_FAILURE\">trace</failure></testcase>",
    );
    expectation.validate(valid.as_bytes(), deadline()).unwrap();
    rejects(
        &expectation,
        report(
            1,
            1,
            0,
            0,
            "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\" />",
        ),
    );
    rejects(
        &expectation,
        valid.replace("<failure message=\"PT_FAILURE\">trace</failure>", ""),
    );
    rejects(&expectation, valid.replace("trace</failure>", "</failure>"));
    rejects(
        &expectation,
        valid.replace(
            "<failure message=\"PT_FAILURE\">trace</failure>",
            "<failure message=\"PT_FAILURE\" />",
        ),
    );
}

#[test]
fn identities_multiplicity_order_and_extra_outcomes_cannot_be_replaced_by_equal_totals() {
    let expectation = expected(&snapshot(
        &[
            "test_x.py::test_first",
            "test_x.py::test_first",
            "test_y.py::test_last",
        ],
        &[["passed"; 3]; 3],
    ));
    let one = "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\" />";
    let last = "<testcase classname=\"test_y\" name=\"test_last\" time=\"0.000\" />";
    let valid = report(3, 0, 0, 0, &format!("{one}{one}{last}"));
    expectation.validate(valid.as_bytes(), deadline()).unwrap();
    for rows in [
        format!("{one}{last}"),
        format!("{one}{one}{one}{last}"),
        format!("{last}{one}{one}"),
        format!("{one}{last}{last}"),
    ] {
        rejects(&expectation, report(3, 0, 0, 0, &rows));
    }
    rejects(&expectation, valid.replace("test_x\"", "different\""));
    rejects(
        &expected(&passing_snapshot()),
        passing_xml().replace(" />", " ><skipped message=\"extra\" /></testcase>"),
    );
}

#[test]
fn exact_suite_counters_include_pass_plus_teardown_error_and_split_call_teardown_failure() {
    let pass_error = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["passed", "passed", "failed"]],
    ));
    let row = "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><error message=\"failed on teardown with &quot;PT_FAILURE&quot;\">trace</error></testcase>";
    pass_error
        .validate(report(2, 0, 1, 0, row).as_bytes(), deadline())
        .unwrap();
    rejects(&pass_error, report(1, 0, 1, 0, row));
    let double = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["passed", "failed", "failed"]],
    ));
    let failure = "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><failure message=\"PT_FAILURE\">trace</failure></testcase>";
    double
        .validate(
            report(1, 1, 1, 0, &format!("{failure}{row}")).as_bytes(),
            deadline(),
        )
        .unwrap();
    assert_eq!(double.expected_testcases(), 2);
    rejects(&double, report(2, 1, 1, 0, &format!("{failure}{row}")));
    rejects(&double, report(1, 1, 1, 0, row));
    let valid = passing_xml();
    for (before, after) in [
        ("tests=\"1\"", "tests=\"2\""),
        ("errors=\"0\"", "errors=\"1\""),
        ("failures=\"0\"", "failures=\"1\""),
        ("skipped=\"0\"", "skipped=\"1\""),
    ] {
        rejects(&expected(&passing_snapshot()), valid.replace(before, after));
    }
}

#[test]
fn setup_and_teardown_adverse_nodes_skip_types_and_exact_reasons_remain_distinct() {
    let expectation = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["failed", "passed", "failed"]],
    ));
    let row = "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><error message=\"failed on setup with &quot;PT_FAILURE&quot;\">setup trace</error><error message=\"failed on teardown with &quot;PT_FAILURE&quot;\">teardown trace</error></testcase>";
    expectation
        .validate(report(2, 0, 2, 0, row).as_bytes(), deadline())
        .unwrap();
    rejects(
        &expectation,
        report(
            2,
            0,
            2,
            0,
            &row.replace("failed on setup", "failed on call"),
        ),
    );
    let skip = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["skipped", "passed", "passed"]],
    ));
    let row = "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><skipped type=\"pytest.skip\" message=\"PT_SKIP\">x.py:1: PT_SKIP</skipped></testcase>";
    skip.validate(report(1, 0, 0, 1, row).as_bytes(), deadline())
        .unwrap();
    for (before, after) in [
        ("PT_SKIP\"", "wrong\""),
        ("pytest.skip", "pytest.xfail"),
        ("skipped type", "failure type"),
    ] {
        rejects(&skip, report(1, 0, 0, 1, &row.replace(before, after)));
    }
    let mut xfail = snapshot(
        &["test_x.py::test_first"],
        &[["passed", "skipped", "passed"]],
    );
    xfail.attempts[0].phases[1].was_xfail = Some("reason: PT_XFAIL".into());
    expected(&xfail).validate(report(1,0,0,1,"<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><skipped type=\"pytest.xfail\" message=\"PT_XFAIL\" /></testcase>").as_bytes(),deadline()).unwrap();
}

#[test]
fn literal_address_mapping_preserves_unicode_brackets_extension_and_custom_prefix() {
    let snapshot = snapshot(
        &[
            "dir/λ.py::C::test[x/y::z]",
            "cases.ptcase::duplicate",
            "documentation.py::documentation",
        ],
        &[["passed"; 3]; 3],
    );
    let policy =
        JunitPolicy::xunit2("suite & λ".into(), Some("prefix.p".into()), limits()).unwrap();
    let expected = JunitExpectation::from_snapshot(policy, &snapshot, deadline()).unwrap();
    let rows = "<testcase classname=\"prefix.p.dir.λ.C\" name=\"test[x/y::z]\" time=\"0.000\" /><testcase classname=\"prefix.p.cases.ptcase\" name=\"duplicate\" time=\"0.000\" /><testcase classname=\"prefix.p.documentation\" name=\"documentation\" time=\"0.000\" />";
    let valid = report(3, 0, 0, 0, rows).replace("name=\"pytest\"", "name=\"suite &amp; λ\"");
    expected.validate(valid.as_bytes(), deadline()).unwrap();
    rejects(&expected, valid.replace("[x/y::z]", "[x.y.z]"));
}

#[test]
fn numeric_entities_and_pinned_visual_escape_are_not_broad_text_normalization() {
    let mut data = snapshot(&["test_x.py::test_λ"], &[["passed", "failed", "passed"]]);
    data.attempts[0].phases[1].reason = Some("λ < & \" '\n\t\r\u{7f}\u{1}".into());
    let expectation = expected(&data);
    let valid = report(
        1,
        1,
        0,
        0,
        "<testcase classname=\"test_x\" name=\"test_&#955;\" time=\"0.000\"><failure message=\"λ &lt; &amp; &quot; &apos;&#10;&#9;&#13;#x7F#x01\">diagnostic &amp; &#x1F40D;</failure></testcase>",
    );
    expectation.validate(valid.as_bytes(), deadline()).unwrap();
    rejects(&expectation, valid.replace("#x01", ""));
    rejects(&expectation, valid.replace("&#10;", " "));
}

#[test]
fn malformed_utf8_xml_entities_and_illegal_reference_characters_never_become_complete() {
    let expectation = expected(&snapshot(
        &["test_x.py::test_first"],
        &[["passed", "failed", "passed"]],
    ));
    let valid = report(
        1,
        1,
        0,
        0,
        "<testcase classname=\"test_x\" name=\"test_first\" time=\"0.000\"><failure message=\"PT_FAILURE\">trace</failure></testcase>",
    );
    for bad in [
        "&unknown;",
        "&amp",
        "&;",
        "&#0;",
        "&#1;",
        "&#xFFFF;",
        "&#xD800;",
        "&#x110000;",
        "&#-1;",
        "&#x;",
        "a]]>b",
        "\u{1}",
        "</error>",
    ] {
        rejects(&expectation, valid.replace("trace", bad));
    }
    for bad in ["x&no;", "x<y", "&#0;", "&#1;", "&#xD800;", "&#x110000;"] {
        rejects(
            &expectation,
            valid.replace("PT_FAILURE\"", &format!("{bad}\"")),
        );
    }
    rejects(&expectation, b"\xff\xfe");
    for end in [0, 1, 5, valid.len() / 2, valid.len() - 1] {
        rejects(&expectation, &valid.as_bytes()[..end]);
    }
    rejects(&expectation, valid.replace("</failure>", "</error>"));
}

#[test]
fn closed_structures_and_attributes_reject_extensions_duplicate_keys_and_extra_roots() {
    let expectation = expected(&passing_snapshot());
    let valid = passing_xml();
    for extension in [
        "<properties><property name=\"x\" value=\"y\" /></properties>",
        "<system-out>output</system-out>",
        "<system-err />",
        "<unknown />",
        "<!-- note -->",
        "<![CDATA[text]]>",
        "<?other data?>",
    ] {
        rejects(
            &expectation,
            valid.replace(
                " /></testsuite>",
                &format!(" >{extension}</testcase></testsuite>"),
            ),
        );
    }
    for (before, after) in [
        (
            "classname=\"test_x\"",
            "classname=\"test_x\" classname=\"test_x\"",
        ),
        ("time=\"0.000\"", "time=\"0.000\" file=\"x.py\""),
        ("name=\"test_first\"", ""),
        ("<testsuites name", "<testsuites xmlns=\"unexpected\" name"),
    ] {
        rejects(&expectation, valid.replace(before, after));
    }
    rejects(
        &expectation,
        valid.replace("</testsuites>", "<testsuite /></testsuites>"),
    );
    rejects(&expectation, format!("{valid}{valid}"));
    rejects(
        &expectation,
        format!("<!DOCTYPE testsuites [<!ENTITY xx SYSTEM 'file:///never-read'>]>{valid}"),
    );
}

#[test]
fn declarations_counters_durations_and_timestamp_formats_are_explicit_not_repaired() {
    let expectation = expected(&passing_snapshot());
    let valid = passing_xml();
    for (before, after) in [
        ("version=\"1.0\"", "version=\"1.1\""),
        ("encoding=\"utf-8\"", "encoding=\"utf-8\" unknown=\"x\""),
        ("version=\"1.0\"", "version=\"1.0\" version=\"1.0\""),
        ("tests=\"1\"", "tests=\"01\""),
        ("tests=\"1\"", "tests=\"+1\""),
        ("tests=\"1\"", "tests=\"1e0\""),
        ("tests=\"1\"", "tests=\"18446744073709551616\""),
        ("0.001", "NaN"),
        ("0.001", "inf"),
        ("0.001", "-0.001"),
        ("0.001", "1e0"),
        ("0.001", "0.1"),
        ("2026-11-10", "2026-02-30"),
        ("+00:00", "Z"),
    ] {
        rejects(&expectation, valid.replace(before, after));
    }
    rejects(&expectation, valid.replace(DECLARATION, ""));
    rejects(&expectation, format!(" {valid}"));
    rejects(
        &expectation,
        valid.replace("</testsuite>", "\u{a0}</testsuite>"),
    );
}

#[test]
fn bounds_and_absolute_deadlines_fail_without_silent_trimming_or_late_acceptance() {
    let snapshot = passing_snapshot();
    let raw = passing_xml();
    for limits in [
        JunitLimits {
            bytes: 0,
            ..limits()
        },
        JunitLimits {
            bytes: 128 * 1024 * 1024 + 1,
            ..limits()
        },
        JunitLimits {
            testcases: 0,
            ..limits()
        },
        JunitLimits {
            testcases: 100001,
            ..limits()
        },
        JunitLimits {
            events: 0,
            ..limits()
        },
        JunitLimits {
            events: 1000001,
            ..limits()
        },
    ] {
        assert!(JunitPolicy::xunit2("pytest".into(), None, limits).is_err());
    }
    let small = JunitPolicy::xunit2(
        "pytest".into(),
        None,
        JunitLimits {
            bytes: raw.len() as u64 - 1,
            ..limits()
        },
    )
    .unwrap();
    rejects(
        &JunitExpectation::from_snapshot(small, &snapshot, deadline()).unwrap(),
        &raw,
    );
    let small = JunitPolicy::xunit2(
        "pytest".into(),
        None,
        JunitLimits {
            events: 5,
            ..limits()
        },
    )
    .unwrap();
    rejects(
        &JunitExpectation::from_snapshot(small, &snapshot, deadline()).unwrap(),
        &raw,
    );
    let two = snapshot_with_two();
    let small = JunitPolicy::xunit2(
        "pytest".into(),
        None,
        JunitLimits {
            testcases: 1,
            ..limits()
        },
    )
    .unwrap();
    assert!(JunitExpectation::from_snapshot(small, &two, deadline()).is_err());
    let expected = expected(&snapshot);
    assert!(expected.validate(raw.as_bytes(), Instant::now()).is_err());
    assert!(JunitExpectation::from_snapshot(policy(), &snapshot, Instant::now()).is_err());
    rejects(&expected, raw.replace("test-host", &"x".repeat(65537)));
    rejects(
        &expected,
        raw.replace("test-host", &"x".repeat(512 * 1024 + 1)),
    );
}
fn snapshot_with_two() -> BridgeSnapshot {
    snapshot(&["x.py::one", "x.py::two"], &[["passed"; 3]; 2])
}

#[test]
fn interrupted_unknown_missing_or_contradictory_context_cannot_supply_expectations() {
    let valid = passing_snapshot();
    for mode in 0..13 {
        let mut bad = valid.clone();
        match mode {
            0 => bad.terminal = None,
            1 => bad.handshake_seen = false,
            2 => bad.stream_consistent_so_far = false,
            3 => bad.terminal.as_mut().unwrap().reporting_complete = false,
            4 => bad.incomplete_ordinals = vec![0],
            5 => bad.attempts[0].disposition = Some(Disposition::Interrupted),
            6 => {
                bad.attempts[0].phases.pop();
            }
            7 => bad.accounting.completed_count = 0,
            8 => bad.selected = vec![0, 0],
            9 => bad.terminal.as_mut().unwrap().backend_exit_code = Some(2),
            10 => bad.session_error_count = 1,
            11 => bad.phase_counts.call.passed = 0,
            _ => bad.attempts[0].phases[0].ordinal = 1,
        }
        assert!(
            JunitExpectation::from_snapshot(policy(), &bad, deadline()).is_err(),
            "{mode}"
        );
    }
}

#[test]
fn adverse_collection_reports_use_exact_pinned_mapping_and_never_become_item_passes() {
    let mut data = snapshot(&[], &[]);
    data.collection_reports.push(CollectionReport {
        report_id: 0,
        nodeid: "bad.py".into(),
        outcome: Outcome::Skipped,
        reason: Some("PT_COLLECT_SKIP".into()),
    });
    let expectation = expected(&data);
    expectation.validate(report(1,0,0,1,"<testcase classname=\"\" name=\"bad\" time=\"0.000\"><skipped message=\"collection skipped\">PT_COLLECT_SKIP</skipped></testcase>").as_bytes(),deadline()).unwrap();
    data.collection_reports
        .push(data.collection_reports[0].clone());
    data.collection_reports[1].report_id = 1;
    assert!(JunitExpectation::from_snapshot(policy(), &data, deadline()).is_err());
}

#[test]
fn independent_python_stdlib_xml_adversaries_agree_with_the_closed_literal_projection() {
    use pt_process::{Cleanup, ProcessRequest, supervise};
    use std::path::PathBuf;
    use std::sync::atomic::AtomicI32;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let temp = tempfile::Builder::new()
        .prefix("pt-junit-xml-controls-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    let output = temp.path().join("xml-cases.json");
    let python = std::env::var_os("PT_TEST_PYTHON")
        .unwrap_or_else(|| root.join("bench/harness/.venv/bin/python").into_os_string());
    let process = supervise(
        &ProcessRequest {
            executable: python,
            args: vec![
                "-I".into(),
                "-S".into(),
                "-B".into(),
                root.join("crates/pt-report/tests/junit_xml_controls.py")
                    .into_os_string(),
                output.clone().into_os_string(),
            ],
            cwd: temp.path().into(),
            timeout: Duration::from_secs(10),
            cleanup_timeout: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    assert_eq!(process.exit_code(), 0);
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert!(std::fs::metadata(&output).unwrap().len() <= 8 * 1024 * 1024);
    let evidence: serde_json::Value =
        serde_json::from_slice(&std::fs::read(output).unwrap()).unwrap();
    let cases = evidence["cases"].as_array().unwrap();
    assert!(cases.len() > 2000);
    let expected = expected(&passing_snapshot());
    for case in cases {
        let result = expected.validate(case["raw"].as_str().unwrap().as_bytes(), deadline());
        assert_eq!(
            result.is_ok(),
            case["accepted"].as_bool().unwrap(),
            "{}: {result:?}; raw={}",
            case["label"],
            case["raw"]
        );
    }
}
