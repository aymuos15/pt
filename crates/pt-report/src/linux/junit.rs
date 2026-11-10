//! Pinned pytest 8.4.2 xunit2/no-extra-data report-completeness projection.
//! It is not execution proof, generic JUnit equivalence or a full-result gate.

use super::{ArtifactError, Result, check_deadline, require};
use pt_protocol::{
    Accounting, BridgeSnapshot, CollectionStatus, Disposition, NotRunReason, Outcome, Phase,
    PhaseCounts, SessionTermination,
};
use quick_xml::events::{BytesStart, Event};
use quick_xml::{Reader, XmlVersion};
use std::collections::{HashMap, HashSet};
use std::time::Instant;

const DECLARATION: &str = "<?xml version=\"1.0\" encoding=\"utf-8\"?>";
pub const JUNIT_POLICY_ID: &str = "pytest-8.4.2-xunit2-no-extra-data-v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct JunitLimits {
    pub bytes: u64,
    pub testcases: usize,
    pub events: usize,
}

/// Only the explicitly named pinned formatter surface: xunit2, no custom
/// attributes/properties/captured-output report nodes. Unknown data is rejected,
/// never stripped to make a report match. Actual pytest options are not changed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JunitPolicy {
    suite_name: String,
    prefix: Option<String>,
    limits: JunitLimits,
}
impl JunitPolicy {
    pub fn policy_id(&self) -> &'static str {
        JUNIT_POLICY_ID
    }
    pub fn xunit2(suite_name: String, prefix: Option<String>, limits: JunitLimits) -> Result<Self> {
        require(
            (1..=128 * 1024 * 1024).contains(&limits.bytes)
                && (1..=100_000).contains(&limits.testcases)
                && (1..=1_000_000).contains(&limits.events),
            "junit_limits_invalid",
        )?;
        require(
            suite_name.chars().count() <= 65536
                && suite_name.chars().all(xml_character)
                && prefix.as_ref().is_none_or(|value| {
                    value.chars().count() <= 65536 && value.chars().all(xml_character)
                }),
            "junit_policy_text_bound",
        )?;
        Ok(Self {
            suite_name,
            prefix,
            limits,
        })
    }
    pub fn limits(&self) -> JunitLimits {
        self.limits
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Adverse {
    tag: &'static str,
    message: String,
    skip_type: Option<&'static str>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
struct Case {
    classname: String,
    name: String,
    adverse: Vec<Adverse>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct Stats {
    passed: u64,
    failures: u64,
    errors: u64,
    skipped: u64,
    double_failures: u64,
}
impl Stats {
    fn tests(&self) -> u64 {
        self.passed + self.failures + self.errors + self.skipped - self.double_failures
    }
}

/// Coordinator projection built from an already validated live bridge ledger,
/// never inferred by reading the JUnit being checked. This constructor does not
/// authenticate a caller-fabricated snapshot or supply missing process/EOF proof.
#[derive(Clone, Debug)]
pub struct JunitExpectation {
    policy: JunitPolicy,
    cases: Vec<Case>,
    stats: Stats,
    metadata_bytes: usize,
}
impl JunitExpectation {
    pub fn from_snapshot(
        policy: JunitPolicy,
        snapshot: &BridgeSnapshot,
        deadline: Instant,
    ) -> Result<Self> {
        check_deadline(deadline)?;
        context(snapshot, deadline)?;
        require(
            snapshot.stream_consistent_so_far
                && snapshot
                    .terminal
                    .as_ref()
                    .is_some_and(|value| value.reporting_complete)
                && snapshot
                    .collection
                    .as_ref()
                    .is_some_and(|value| value.status != CollectionStatus::Interrupted)
                && snapshot.incomplete_ordinals.is_empty()
                && snapshot.session_errors.is_empty(),
            "junit_runtime_context_incomplete_or_unsupported",
        )?;
        require(
            snapshot.nodeids.len() <= 100_000
                && snapshot.attempts.len() <= 100_000
                && snapshot.collection_reports.len() <= 100_000,
            "junit_runtime_context_bound",
        )?;
        let mut value = Self {
            policy,
            cases: Vec::new(),
            stats: Stats::default(),
            metadata_bytes: 0,
        };
        let mut collector_ids = HashSet::new();
        for report in &snapshot.collection_reports {
            check_deadline(deadline)?;
            if report.outcome == Outcome::Passed {
                continue;
            }
            require(
                collector_ids.insert(&report.nodeid),
                "junit_repeated_adverse_collector_unsupported",
            )?;
            let (tag, message) = if report.outcome == Outcome::Failed {
                value.stats.errors += 1;
                ("error", "collection failure")
            } else {
                value.stats.skipped += 1;
                ("skipped", "collection skipped")
            };
            let mut case = value.case(&report.nodeid);
            case.adverse.push(Adverse {
                tag,
                message: message.into(),
                skip_type: None,
            });
            value.push(case)?;
        }
        let mut ordinals = HashSet::new();
        for attempt in &snapshot.attempts {
            check_deadline(deadline)?;
            require(
                attempt.disposition == Some(Disposition::Completed)
                    && ordinals.insert(attempt.ordinal),
                "junit_attempt_not_completed_or_selected",
            )?;
            let nodeid = snapshot
                .nodeids
                .get(attempt.ordinal as usize)
                .ok_or_else(|| ArtifactError::new("junit_unknown_ordinal"))?;
            require(
                !collector_ids.contains(nodeid),
                "junit_collector_attempt_identity_collision_unsupported",
            )?;
            let expected = if attempt
                .phases
                .first()
                .is_some_and(|phase| phase.outcome == Outcome::Passed)
            {
                vec![Phase::Setup, Phase::Call, Phase::Teardown]
            } else {
                vec![Phase::Setup, Phase::Teardown]
            };
            require(
                attempt
                    .phases
                    .iter()
                    .map(|value| value.phase)
                    .collect::<Vec<_>>()
                    == expected,
                "junit_applicable_phase_context_mismatch",
            )?;
            let mut case = value.case(nodeid);
            let mut call_failed = false;
            for phase in &attempt.phases {
                require(
                    phase.ordinal == attempt.ordinal && phase.attempt == 0,
                    "junit_phase_identity_or_retry_unsupported",
                )?;
                match phase.outcome {
                    Outcome::Passed if phase.phase == Phase::Call => value.stats.passed += 1,
                    Outcome::Passed => {}
                    Outcome::Failed => {
                        if phase.phase == Phase::Teardown && call_failed {
                            value.push(case)?;
                            case = value.case(nodeid);
                            value.stats.double_failures += 1;
                        }
                        if phase.phase == Phase::Call {
                            call_failed = true;
                            if phase.was_xfail.is_some() {
                                value.stats.skipped += 1;
                                case.adverse.push(Adverse {
                                    tag: "skipped",
                                    message: "xfail-marked test passes unexpectedly".into(),
                                    skip_type: None,
                                });
                            } else {
                                value.stats.failures += 1;
                                case.adverse.push(Adverse {
                                    tag: "failure",
                                    message: xml_escape(reason(&phase.reason)?),
                                    skip_type: None,
                                });
                            }
                        } else {
                            value.stats.errors += 1;
                            let stage = if phase.phase == Phase::Setup {
                                "setup"
                            } else {
                                "teardown"
                            };
                            case.adverse.push(Adverse {
                                tag: "error",
                                message: xml_escape(&format!(
                                    "failed on {stage} with \"{}\"",
                                    reason(&phase.reason)?
                                )),
                                skip_type: None,
                            });
                        }
                    }
                    Outcome::Skipped => {
                        value.stats.skipped += 1;
                        if let Some(reason) = &phase.was_xfail {
                            case.adverse.push(Adverse {
                                tag: "skipped",
                                message: xml_escape(
                                    reason.strip_prefix("reason: ").unwrap_or(reason),
                                ),
                                skip_type: Some("pytest.xfail"),
                            });
                        } else {
                            let reason = reason(&phase.reason)?;
                            case.adverse.push(Adverse {
                                tag: "skipped",
                                message: xml_escape(
                                    reason.strip_prefix("Skipped: ").unwrap_or(reason),
                                ),
                                skip_type: Some("pytest.skip"),
                            });
                        }
                    }
                }
            }
            value.push(case)?;
        }
        require(
            value.cases.len() <= value.policy.limits.testcases,
            "junit_expected_case_bound",
        )?;
        check_deadline(deadline)?;
        Ok(value)
    }

    fn push(&mut self, case: Case) -> Result<()> {
        require(
            self.cases.len() < self.policy.limits.testcases,
            "junit_expected_case_bound",
        )?;
        for text in [&case.classname, &case.name] {
            require(
                text.chars().count() <= 65536 && text.chars().all(xml_character),
                "junit_expected_text_bound_or_character",
            )?;
        }
        for adverse in &case.adverse {
            require(
                adverse.message.chars().count() <= 65536,
                "junit_expected_text_bound_or_character",
            )?;
        }
        self.metadata_bytes += case.classname.len()
            + case.name.len()
            + case
                .adverse
                .iter()
                .map(|value| value.message.len())
                .sum::<usize>();
        require(
            self.metadata_bytes as u64 <= self.policy.limits.bytes.min(64 * 1024 * 1024),
            "junit_expected_metadata_byte_bound",
        )?;
        self.cases.push(case);
        Ok(())
    }

    pub fn policy(&self) -> &JunitPolicy {
        &self.policy
    }
    pub fn expected_testcases(&self) -> usize {
        self.cases.len()
    }

    fn case(&self, nodeid: &str) -> Case {
        // This is the versioned pytest 8.4.2 JUnit address mapping, not generic
        // path erasure. Bracket contents/duplicates/order are preserved exactly.
        let (path, parameters) = nodeid
            .split_once('[')
            .map_or((nodeid, None), |(path, params)| (path, Some(params)));
        let mut names = path.split("::").map(str::to_owned).collect::<Vec<_>>();
        names[0] = names[0].replace('/', ".");
        if names[0].ends_with(".py") {
            let length = names[0].len() - 3;
            names[0].truncate(length);
        }
        if let Some(parameters) = parameters {
            let last = names.last_mut().expect("split always has a part");
            last.push('[');
            last.push_str(parameters);
        }
        let name = xml_escape(&names.pop().expect("split always has a part"));
        if let Some(prefix) = &self.policy.prefix
            && !prefix.is_empty()
        {
            names.insert(0, prefix.clone());
        }
        Case {
            classname: names.join("."),
            name,
            adverse: Vec::new(),
        }
    }

    pub(crate) fn validate(&self, raw: &[u8], deadline: Instant) -> Result<()> {
        check_deadline(deadline)?;
        require(
            raw.len() as u64 <= self.policy.limits.bytes,
            "junit_byte_bound",
        )?;
        let text = std::str::from_utf8(raw).map_err(|e| ArtifactError::io("junit_not_utf8", e))?;
        // This adapter names the pinned formatter, not arbitrary JUnit/XML
        // dialects. A closed literal declaration also rejects duplicate/unknown
        // declaration fields and leading data/BOMs instead of ignoring them.
        require(
            text.starts_with(DECLARATION),
            "junit_declaration_unsupported",
        )?;
        require(
            text.chars().all(xml_character),
            "junit_invalid_xml_character",
        )?;
        let mut reader = Reader::from_str(text);
        reader.config_mut().expand_empty_elements = true;
        reader.config_mut().check_comments = true;
        let mut stack = Vec::<String>::new();
        let mut outcome_text = false;
        let (
            mut declaration,
            mut root_closed,
            mut suite_seen,
            mut case_index,
            mut adverse_index,
            mut events,
        ) = (false, false, false, 0, 0, 0);
        loop {
            check_deadline(deadline)?;
            events += 1;
            require(events <= self.policy.limits.events, "junit_event_bound")?;
            let event = reader
                .read_event()
                .map_err(|e| ArtifactError::io("junit_xml_malformed", e))?;
            match event {
                Event::Decl(value) => {
                    require(
                        !declaration && stack.is_empty() && !root_closed,
                        "junit_declaration_order",
                    )?;
                    require(
                        value.as_ref() == "xml version=\"1.0\" encoding=\"utf-8\"",
                        "junit_declaration_unsupported",
                    )?;
                    declaration = true;
                }
                Event::Start(element) => {
                    self.start(
                        &element,
                        &stack,
                        case_index,
                        adverse_index,
                        root_closed,
                        suite_seen,
                        declaration,
                    )?;
                    if element.name().as_ref() == "testsuite" {
                        suite_seen = true;
                    }
                    if element.name().as_ref() == "testcase" {
                        adverse_index = 0;
                    }
                    if matches!(element.name().as_ref(), "failure" | "error" | "skipped") {
                        outcome_text = false;
                    }
                    stack.push(element.name().as_ref().to_owned());
                    require(stack.len() <= 4, "junit_depth_bound")?;
                }
                Event::End(element) => {
                    require(
                        stack.pop().as_deref() == Some(element.name().as_ref()),
                        "junit_unbalanced_end",
                    )?;
                    match element.name().as_ref() {
                        "testcase" => {
                            require(
                                adverse_index == self.cases[case_index].adverse.len(),
                                "junit_missing_outcome",
                            )?;
                            case_index += 1;
                        }
                        "failure" | "error" | "skipped" => {
                            let expected = &self.cases[case_index].adverse[adverse_index];
                            require(
                                outcome_text || expected.skip_type == Some("pytest.xfail"),
                                "junit_diagnostic_body_missing",
                            )?;
                            adverse_index += 1;
                        }
                        "testsuite" => {
                            require(case_index == self.cases.len(), "junit_missing_testcases")?
                        }
                        "testsuites" => root_closed = true,
                        _ => return Err(ArtifactError::new("junit_unknown_end")),
                    }
                }
                Event::Text(value) => {
                    let content = value.as_ref();
                    require(!content.contains("]]>"), "junit_invalid_text_delimiter")?;
                    let adverse = stack.last().is_some_and(|value| {
                        matches!(value.as_str(), "failure" | "error" | "skipped")
                    });
                    require(
                        adverse || content.chars().all(xml_space),
                        "junit_unexpected_text",
                    )?;
                    outcome_text |= adverse && !content.is_empty();
                }
                Event::GeneralRef(value) => {
                    require(
                        stack.last().is_some_and(|value| {
                            matches!(value.as_str(), "failure" | "error" | "skipped")
                        }),
                        "junit_unexpected_entity",
                    )?;
                    require(value.len() <= 512 * 1024, "junit_reference_bound")?;
                    let decoded = quick_xml::escape::unescape(&format!("&{};", value.as_ref()))
                        .map_err(|e| ArtifactError::io("junit_entity_unsupported", e))?
                        .into_owned();
                    require(
                        decoded.chars().all(xml_character),
                        "junit_invalid_reference_character",
                    )?;
                    outcome_text |= !decoded.is_empty();
                }
                Event::Eof => {
                    require(
                        declaration
                            && root_closed
                            && suite_seen
                            && stack.is_empty()
                            && case_index == self.cases.len(),
                        "junit_truncated_or_missing_boundaries",
                    )?;
                    break;
                }
                _ => {
                    return Err(ArtifactError::new(
                        "junit_dtd_comment_cdata_or_extension_unsupported",
                    ));
                }
            }
        }
        check_deadline(deadline)
    }

    #[allow(clippy::too_many_arguments)]
    fn start(
        &self,
        element: &BytesStart<'_>,
        stack: &[String],
        case_index: usize,
        adverse_index: usize,
        root_closed: bool,
        suite_seen: bool,
        declaration: bool,
    ) -> Result<()> {
        let attrs = attributes(element)?;
        match (stack.len(), element.name().as_ref()) {
            (0, "testsuites") => {
                require(declaration && !root_closed, "junit_root_order")?;
                fields(&attrs, &["name"])?;
                require(attrs["name"] == "pytest tests", "junit_root_name")?;
            }
            (1, "testsuite") if stack[0] == "testsuites" => {
                require(!suite_seen, "junit_multiple_suites_unsupported")?;
                fields(
                    &attrs,
                    &[
                        "name",
                        "errors",
                        "failures",
                        "skipped",
                        "tests",
                        "time",
                        "timestamp",
                        "hostname",
                    ],
                )?;
                require(
                    attrs["name"] == self.policy.suite_name,
                    "junit_suite_name_mismatch",
                )?;
                for (name, expected) in [
                    ("errors", self.stats.errors),
                    ("failures", self.stats.failures),
                    ("skipped", self.stats.skipped),
                    ("tests", self.stats.tests()),
                ] {
                    require(
                        number(&attrs[name])? == expected,
                        "junit_suite_count_mismatch",
                    )?;
                }
                duration(&attrs["time"])?;
                timestamp(&attrs["timestamp"])?;
            }
            (2, "testcase") if stack[1] == "testsuite" => {
                let expected = self
                    .cases
                    .get(case_index)
                    .ok_or_else(|| ArtifactError::new("junit_extra_testcase"))?;
                fields(&attrs, &["classname", "name", "time"])?;
                require(
                    attrs["classname"] == expected.classname && attrs["name"] == expected.name,
                    "junit_occurrence_identity_or_order_mismatch",
                )?;
                duration(&attrs["time"])?;
            }
            (3, tag @ ("failure" | "error" | "skipped")) if stack[2] == "testcase" => {
                let expected = self
                    .cases
                    .get(case_index)
                    .and_then(|value| value.adverse.get(adverse_index))
                    .ok_or_else(|| ArtifactError::new("junit_extra_outcome"))?;
                if expected.skip_type.is_some() {
                    fields(&attrs, &["message", "type"])?;
                } else {
                    fields(&attrs, &["message"])?;
                }
                require(
                    tag == expected.tag && attrs["message"] == expected.message,
                    "junit_outcome_or_reason_mismatch",
                )?;
                if let Some(expected) = expected.skip_type {
                    require(attrs["type"] == expected, "junit_skip_kind_mismatch")?;
                }
            }
            _ => {
                return Err(ArtifactError::new(
                    "junit_unknown_structure_or_report_extension",
                ));
            }
        }
        Ok(())
    }
}

fn reason(value: &Option<String>) -> Result<&str> {
    value
        .as_deref()
        .ok_or_else(|| ArtifactError::new("junit_failure_reason_context_missing"))
}
fn xml_space(value: char) -> bool {
    matches!(value, ' ' | '\t' | '\r' | '\n')
}

fn timestamp(value: &str) -> Result<()> {
    // The pinned formatter uses aware datetime.isoformat(), not an arbitrary
    // schema timestamp. Values are not compared across runs or treated as clocks.
    let bytes = value.as_bytes();
    require(
        matches!(bytes.len(), 25 | 32) && bytes.is_ascii(),
        "junit_timestamp_format_unsupported",
    )?;
    let offset = bytes.len() - 6;
    require(
        bytes[4] == b'-'
            && bytes[7] == b'-'
            && bytes[10] == b'T'
            && bytes[13] == b':'
            && bytes[16] == b':'
            && matches!(bytes[offset], b'+' | b'-')
            && bytes[offset + 3] == b':'
            && (offset == 19
                || (bytes[19] == b'.' && bytes[20..26].iter().all(u8::is_ascii_digit))),
        "junit_timestamp_format_unsupported",
    )?;
    let part = |start, end| -> Result<u32> {
        require(
            bytes[start..end].iter().all(u8::is_ascii_digit),
            "junit_timestamp_format_unsupported",
        )?;
        value[start..end]
            .parse::<u32>()
            .map_err(|e| ArtifactError::io("junit_timestamp_format_unsupported", e))
    };
    let year = part(0, 4)?;
    let month = part(5, 7)?;
    let day = part(8, 10)?;
    let maximum = match month {
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        _ => 0,
    };
    require(
        year > 0
            && day > 0
            && day <= maximum
            && part(11, 13)? < 24
            && part(14, 16)? < 60
            && part(17, 19)? < 60
            && part(offset + 1, offset + 3)? < 24
            && part(offset + 4, offset + 6)? < 60,
        "junit_timestamp_format_unsupported",
    )
}

fn context(snapshot: &BridgeSnapshot, deadline: Instant) -> Result<()> {
    require(
        snapshot.handshake_seen
            && snapshot.stream_consistent_so_far
            && snapshot.session_error_count == 0
            && snapshot.session_errors.is_empty()
            && snapshot.incomplete_ordinals.is_empty(),
        "junit_runtime_context_incomplete_or_unsupported",
    )?;
    require(
        [
            snapshot.nodeids.len(),
            snapshot.selected.len(),
            snapshot.deselected.len(),
            snapshot.attempts.len(),
            snapshot.not_run.len(),
            snapshot.collection_reports.len(),
        ]
        .iter()
        .all(|value| *value <= 100_000)
            && snapshot.collection_errors.len() <= 1024,
        "junit_runtime_context_bound",
    )?;
    let collection = snapshot
        .collection
        .as_ref()
        .ok_or_else(|| ArtifactError::new("junit_collection_context_missing"))?;
    let terminal = snapshot
        .terminal
        .as_ref()
        .ok_or_else(|| ArtifactError::new("junit_terminal_context_missing"))?;
    require(
        terminal.reporting_complete
            && terminal.incomplete_ordinals.is_empty()
            && terminal.termination == SessionTermination::BackendExited
            && matches!(terminal.backend_exit_code, Some(0 | 1 | 2 | 5))
            && collection.status != CollectionStatus::Interrupted,
        "junit_runtime_context_incomplete_or_unsupported",
    )?;
    let mut partition = HashSet::new();
    for ordinal in snapshot.selected.iter().chain(&snapshot.deselected) {
        check_deadline(deadline)?;
        require(
            (*ordinal as u128) < snapshot.nodeids.len() as u128 && partition.insert(*ordinal),
            "junit_inventory_partition_mismatch",
        )?;
    }
    require(
        partition.len() == snapshot.nodeids.len()
            && collection.inventory_complete == (collection.status == CollectionStatus::Complete),
        "junit_inventory_partition_mismatch",
    )?;
    require(
        snapshot
            .attempts
            .iter()
            .map(|value| value.ordinal)
            .chain(snapshot.not_run.iter().map(|value| value.ordinal))
            .eq(snapshot.selected.iter().copied())
            && snapshot
                .not_run
                .iter()
                .all(|value| value.reason != NotRunReason::Interrupted),
        "junit_unaccounted_or_interrupted_selected_work",
    )?;
    let expected = Accounting {
        collected_count: snapshot.nodeids.len() as u64,
        selected_count: snapshot.selected.len() as u64,
        deselected_count: snapshot.deselected.len() as u64,
        executed_count: snapshot.attempts.len() as u64,
        completed_count: snapshot.attempts.len() as u64,
        not_run_count: snapshot.not_run.len() as u64,
        attempts_started: snapshot.attempts.len() as u64,
        attempts_completed: snapshot.attempts.len() as u64,
    };
    require(
        snapshot.accounting == expected
            && terminal.accounting == expected
            && collection.collected_count == expected.collected_count
            && collection.selected_count == expected.selected_count
            && collection.deselected_count == expected.deselected_count,
        "junit_context_accounting_mismatch",
    )?;
    let mut phases = PhaseCounts::default();
    let mut text_bytes = 0usize;
    let mut add_text = |text: &str| -> Result<()> {
        require(text.chars().count() <= 65536, "junit_context_text_bound")?;
        text_bytes += text.len();
        require(
            text_bytes <= 64 * 1024 * 1024,
            "junit_context_text_byte_bound",
        )
    };
    let mut nodeid_bytes = 0usize;
    for nodeid in &snapshot.nodeids {
        check_deadline(deadline)?;
        add_text(nodeid)?;
        nodeid_bytes += nodeid.len();
        require(
            !nodeid.is_empty() && nodeid_bytes <= 16 * 1024 * 1024,
            "junit_context_nodeid_bound",
        )?;
    }
    for attempt in &snapshot.attempts {
        check_deadline(deadline)?;
        require(attempt.phases.len() <= 3, "junit_context_phase_bound")?;
        for phase in &attempt.phases {
            for text in [&phase.reason, &phase.was_xfail].into_iter().flatten() {
                add_text(text)?;
            }
            let counts = match phase.phase {
                Phase::Setup => &mut phases.setup,
                Phase::Call => &mut phases.call,
                Phase::Teardown => &mut phases.teardown,
            };
            match phase.outcome {
                Outcome::Passed => counts.passed += 1,
                Outcome::Failed => counts.failed += 1,
                Outcome::Skipped => counts.skipped += 1,
            }
        }
    }
    require(
        snapshot.phase_counts == phases && terminal.phase_counts == phases,
        "junit_context_phase_counts_mismatch",
    )?;
    let mut ids = HashSet::new();
    let mut failed = HashMap::new();
    for report in &snapshot.collection_reports {
        check_deadline(deadline)?;
        add_text(&report.nodeid)?;
        if let Some(reason) = &report.reason {
            add_text(reason)?;
        }
        require(
            ids.insert(report.report_id),
            "junit_context_collector_identity_mismatch",
        )?;
        if report.outcome == Outcome::Failed {
            failed.insert(report.report_id, report.nodeid.as_str());
        }
    }
    for error in &snapshot.collection_errors {
        add_text(&error.reason)?;
        require(
            failed.remove(&error.report_id) == Some(error.nodeid.as_str()),
            "junit_context_collection_error_mismatch",
        )?;
    }
    require(
        failed.is_empty()
            && (snapshot.collection_errors.is_empty()
                || collection.status == CollectionStatus::Failed),
        "junit_context_collection_error_mismatch",
    )?;
    let failures = phases.setup.failed
        + phases.call.failed
        + phases.teardown.failed
        + snapshot.collection_errors.len() as u64;
    require(
        match terminal.backend_exit_code {
            Some(0) => {
                failures == 0
                    && !snapshot.selected.is_empty()
                    && snapshot
                        .not_run
                        .iter()
                        .all(|value| value.reason == NotRunReason::CollectOnly)
            }
            Some(1) => {
                failures > 0
                    && snapshot.not_run.iter().all(|value| {
                        matches!(
                            value.reason,
                            NotRunReason::FailFast
                                | NotRunReason::CollectionFailed
                                | NotRunReason::CollectOnly
                        )
                    })
            }
            Some(2) => collection.status == CollectionStatus::Failed,
            Some(5) => {
                snapshot.selected.is_empty()
                    && collection.status == CollectionStatus::Complete
                    && failures == 0
            }
            _ => false,
        },
        "junit_context_backend_exit_mismatch",
    )?;
    check_deadline(deadline)
}
fn xml_character(value: char) -> bool {
    matches!(value, '\t' | '\n' | '\r')
        || (' '..='\u{d7ff}').contains(&value)
        || ('\u{e000}'..='\u{fffd}').contains(&value)
        || value >= '\u{10000}'
}
fn xml_escape(value: &str) -> String {
    value
        .chars()
        .map(|value| {
            if xml_character(value) && value != '\u{7f}' {
                value.to_string()
            } else if (value as u32) <= 255 {
                format!("#x{:02X}", value as u32)
            } else {
                format!("#x{:04X}", value as u32)
            }
        })
        .collect()
}
fn number(value: &str) -> Result<u64> {
    let parsed = value
        .parse::<u64>()
        .map_err(|e| ArtifactError::io("junit_count_invalid", e))?;
    require(parsed.to_string() == value, "junit_count_not_canonical")?;
    Ok(parsed)
}
fn duration(value: &str) -> Result<()> {
    let (whole, fraction) = value
        .split_once('.')
        .ok_or_else(|| ArtifactError::new("junit_duration_format_unsupported"))?;
    number(whole)?;
    require(
        fraction.len() == 3 && fraction.bytes().all(|byte| byte.is_ascii_digit()),
        "junit_duration_format_unsupported",
    )?;
    let value = value
        .parse::<f64>()
        .map_err(|e| ArtifactError::io("junit_duration_invalid", e))?;
    require(value.is_finite() && value >= 0.0, "junit_duration_invalid")
}
fn fields(attrs: &HashMap<String, String>, keys: &[&str]) -> Result<()> {
    require(
        attrs.len() == keys.len() && keys.iter().all(|key| attrs.contains_key(*key)),
        "junit_closed_attributes_mismatch",
    )
}
fn attributes(element: &BytesStart<'_>) -> Result<HashMap<String, String>> {
    attribute_separators(element)?;
    let mut result = HashMap::new();
    for attribute in element.attributes() {
        let attribute = attribute
            .map_err(|e| ArtifactError::io("junit_attribute_malformed_or_duplicate", e))?;
        require(
            result.len() < 16
                && attribute.key.as_ref().len() <= 32
                && attribute.value.len() <= 512 * 1024,
            "junit_attribute_bound",
        )?;
        require(
            !attribute.value.contains('<'),
            "junit_unescaped_attribute_markup",
        )?;
        require(
            !attribute.value.contains(['\t', '\r', '\n']),
            "junit_attribute_whitespace_format_unsupported",
        )?;
        let value = attribute
            .normalized_value(XmlVersion::Explicit1_0)
            .map_err(|e| ArtifactError::io("junit_attribute_decode", e))?
            .into_owned();
        require(
            value.chars().count() <= 65536 && value.chars().all(xml_character),
            "junit_attribute_text_bound",
        )?;
        result.insert(attribute.key.as_ref().to_owned(), value);
    }
    Ok(result)
}

fn attribute_separators(element: &BytesStart<'_>) -> Result<()> {
    // quick-xml is deliberately a permissive pull reader: it accepts adjacent
    // quoted attributes without XML's mandatory whitespace separator. Closed
    // typed fields alone do not catch that malformed document. Validate this
    // lexical boundary too; values/entities still go through the pinned parser.
    let raw = element.as_ref().as_bytes();
    let mut position = element.name().as_ref().len();
    let mut count = 0;
    while position < raw.len() {
        require(
            matches!(raw[position], b' ' | b'\t' | b'\r' | b'\n'),
            "junit_attribute_separator_missing",
        )?;
        while position < raw.len() && matches!(raw[position], b' ' | b'\t' | b'\r' | b'\n') {
            position += 1;
        }
        if position == raw.len() {
            break;
        }
        count += 1;
        require(count <= 16, "junit_attribute_bound")?;
        let start = position;
        while position < raw.len() && !matches!(raw[position], b'=' | b' ' | b'\t' | b'\r' | b'\n')
        {
            position += 1;
            require(position - start <= 32, "junit_attribute_bound")?;
        }
        require(position > start, "junit_attribute_syntax")?;
        while position < raw.len() && matches!(raw[position], b' ' | b'\t' | b'\r' | b'\n') {
            position += 1;
        }
        require(raw.get(position) == Some(&b'='), "junit_attribute_syntax")?;
        position += 1;
        while position < raw.len() && matches!(raw[position], b' ' | b'\t' | b'\r' | b'\n') {
            position += 1;
        }
        let quote = *raw
            .get(position)
            .ok_or_else(|| ArtifactError::new("junit_attribute_syntax"))?;
        require(matches!(quote, b'\'' | b'"'), "junit_attribute_syntax")?;
        position += 1;
        let length = raw[position..]
            .iter()
            .take(512 * 1024 + 1)
            .position(|byte| *byte == quote)
            .ok_or_else(|| ArtifactError::new("junit_attribute_bound_or_quote"))?;
        position += length + 1;
    }
    Ok(())
}

#[cfg(test)]
pub(super) mod tests;
