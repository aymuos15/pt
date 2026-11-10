use super::*;
#[path = "../../../pt-protocol/tests/common/mod.rs"]
mod common;
use common::{Trace, contract, identity};
use pt_process::{ProcessRequest, supervise};
use pt_protocol::StreamBudget;
use pt_report::ExpectedContent;
use std::fs;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;

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
fn private(path: &Path) {
    fs::create_dir(path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
struct Case {
    _temp: Option<tempfile::TempDir>,
    path: PathBuf,
    work: PathBuf,
    retained: PathBuf,
}
impl Case {
    fn new(id: &str) -> Self {
        let (temp, path) = if let Some(parent) = std::env::var_os("PT_COORDINATOR_CASE_ROOT") {
            let path = PathBuf::from(parent).join(id);
            private(&path);
            (None, path)
        } else {
            let temp = tempfile::Builder::new()
                .prefix("pt-coordinator-controls-")
                .tempdir_in("/tmp/opencode")
                .unwrap();
            let path = temp.path().to_path_buf();
            (Some(temp), path)
        };
        let work = path.join("work");
        private(&work);
        let retained = path.join("retained");
        private(&retained);
        Self {
            _temp: temp,
            path,
            work,
            retained,
        }
    }
    fn serial(&self, mode: &str, trace: &Trace) -> SerialRequest {
        let values = trace
            .raw()
            .iter()
            .map(|raw| serde_json::from_slice::<Value>(raw).unwrap())
            .collect::<Vec<_>>();
        let input = self.path.join("synthetic-trace.json");
        fs::write(&input, serde_json::to_vec_pretty(&values).unwrap()).unwrap();
        let mut contract = contract();
        contract.declared_artifact_ids = vec![];
        SerialRequest {
            process: ProcessRequest {
                executable: python(),
                args: vec![
                    "-I".into(),
                    "-S".into(),
                    "-B".into(),
                    root()
                        .join("crates/pt-session/tests/session_producer.py")
                        .into_os_string(),
                    mode.into(),
                    input.into_os_string(),
                ],
                cwd: self.work.clone(),
                timeout: Duration::from_secs(4),
                cleanup_timeout: Duration::from_secs(1),
            },
            identity: identity(),
            contract,
            stream_budget: StreamBudget {
                bytes: 1024 * 1024,
                events: 1024,
            },
            drain_allowance: Duration::from_millis(200),
        }
    }
    fn request(
        &self,
        mode: &str,
        trace: &Trace,
        scope: RequestedScope,
        declarations: Vec<ArtifactDeclaration>,
    ) -> RunRequest {
        // Explicitly prepare only new test-owned declared output files. The
        // producer's truncating write preserves 0600 instead of inheriting the
        // caller's group-writable umask. Product guards are not relaxed.
        for declaration in &declarations {
            fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(self.work.join(&declaration.source))
                .unwrap();
        }
        let mut serial = self.serial(mode, trace);
        serial.contract.declared_artifact_ids = declarations
            .iter()
            .map(|value| value.artifact_id.clone())
            .collect();
        RunRequest::new(serial, scope, "coordinator-1".into(), declarations).unwrap()
    }
    fn retention(&self) -> RetentionTarget {
        RetentionTarget {
            parent: self.retained.clone(),
            private_name: "private".into(),
            budget: RetentionBudget {
                files: 16,
                bytes: 1024 * 1024,
                per_file_bytes: 512 * 1024,
                deadline: Instant::now() + Duration::from_secs(15),
            },
        }
    }
    fn observe(&self, request: RunRequest) -> ObservedRun {
        request
            .observe_development(self.retention(), &AtomicI32::new(0))
            .unwrap()
    }
    fn check(&self, run: &FinishedRun) {
        self.save(run);
        let record = run.record().unwrap();
        assert!(record.cli_exit_code() > 0);
        assert_eq!(record.as_json()["current_full_success"], false);
        assert_eq!(record.as_json()["environment_verified"], false);
        self.shape(
            record,
            run.coordinator_records(),
            Some(run.session().process()),
        );
    }
    fn save(&self, run: &FinishedRun) {
        fs::write(
            self.path.join("actual-process.json"),
            serde_json::to_vec_pretty(run.session().process()).unwrap(),
        )
        .unwrap();
        fs::write(
            self.path.join("actual-observation.txt"),
            format!(
                "outcome={:?}\nchannel={:?}\nsnapshot={:#?}\nqualified=false\n",
                run.session().outcome(),
                run.session().channel(),
                run.session().snapshot()
            ),
        )
        .unwrap();
        fs::write(self.path.join("artifact-diagnostics.json"),serde_json::to_vec_pretty(&run.artifact_diagnostics().iter().map(|value|json!({"artifact_id":value.artifact_id(),"code":value.code(),"detail":value.detail()})).collect::<Vec<_>>()).unwrap()).unwrap();
        if let Err(error) = run.record() {
            fs::write(
                self.path.join("final-record-unavailable.json"),
                serde_json::to_vec_pretty(
                    &json!({"code":error.code(),"error":error.to_string(),"qualified":false}),
                )
                .unwrap(),
            )
            .unwrap();
        }
    }
    fn shape(
        &self,
        record: &FinalRecord,
        records: &[Value],
        process: Option<&pt_process::ProcessReport>,
    ) {
        let source = self.path.join("native-records.json");
        let output = self.path.join("independent-shape.json");
        fs::write(&source,serde_json::to_vec_pretty(&json!({"coordinator_records":records,"final_result":record.as_json(),"native_process":process,"qualified":false})).unwrap()).unwrap();
        let process = supervise(
            &ProcessRequest {
                executable: python(),
                args: vec![
                    "-I".into(),
                    "-B".into(),
                    root()
                        .join("crates/pt-coordinator/tests/check_records.py")
                        .into_os_string(),
                    root().join("docs/protocol-v0.schema.json").into_os_string(),
                    root()
                        .join("docs/final-result-v0.schema.json")
                        .into_os_string(),
                    source.into_os_string(),
                    output.clone().into_os_string(),
                ],
                cwd: self.work.clone(),
                timeout: Duration::from_secs(5),
                cleanup_timeout: Duration::from_secs(1),
            },
            &AtomicI32::new(0),
        )
        .unwrap();
        fs::write(
            self.path.join("schema-process.json"),
            serde_json::to_vec_pretty(&process).unwrap(),
        )
        .unwrap();
        assert_eq!(process.exit_code(), 0);
        assert_eq!(process.cleanup, Cleanup::Complete);
        assert!(output.is_file());
    }
}
fn passing() -> Trace {
    let mut trace = Trace::new();
    trace.collection(&["x.py::test_one"], &[0], "complete");
    trace.attempt(0, "passed", "passed", "passed");
    trace.terminal(0, "backend_exited");
    trace
}
const REPORT: &[u8] = b"<testsuite tests=\"1\"><testcase name=\"looks_complete\"/></testsuite>";
fn declaration(required: bool) -> ArtifactDeclaration {
    ArtifactDeclaration {
        artifact_id: "report-1".into(),
        source: "complete-looking.xml".into(),
        required,
        expected_content: Some(ExpectedContent {
            bytes: REPORT.len() as u64,
            sha256: Sha256::digest(REPORT)
                .iter()
                .map(|value| format!("{value:02x}"))
                .collect(),
        }),
        junit_policy: None,
    }
}
fn ready(trace: &mut Trace, hash: &str, complete: bool) {
    let terminal = trace.rows.pop().unwrap();
    trace.push(
        "artifact_ready",
        json!({"artifact_id":"report-1","sha256":hash,"bytes":REPORT.len(),"complete":complete}),
    );
    trace.rows.push(terminal);
}

#[test]
fn qualified_request_is_rejected_before_any_child_store_or_interpreter_probe() {
    let case = Case::new("qualified-prelaunch-rejection");
    let request = case.request("complete", &passing(), RequestedScope::Full, vec![]);
    let rejected = request.reject_qualified().unwrap();
    let value = rejected.record().as_json();
    assert_eq!(value["outcome"], "unsupported_profile");
    assert_eq!(value["cli_exit_code"], 4);
    assert_eq!(value["accounting"]["executed_count"], 0);
    assert!(!case.work.join("started-once").exists());
    assert!(!case.retained.join("private").exists());
    case.shape(rejected.record(), rejected.coordinator_records(), None);
}

#[test]
fn accounted_zero_nonzero_and_full_request_labels_cannot_bypass_environment_or_generation_gates() {
    for (name, scope, failed) in [
        ("normal-zero", RequestedScope::Explicit, false),
        ("normal-one", RequestedScope::Explicit, true),
        ("normal-full-label", RequestedScope::Full, false),
    ] {
        let case = Case::new(name);
        let mut trace = passing();
        if failed {
            trace = Trace::new();
            trace.collection(&["x.py::test_one"], &[0], "complete");
            trace.attempt(0, "passed", "failed", "passed");
            trace.terminal(1, "backend_exited");
        }
        let run = case
            .observe(case.request(
                if failed { "exit_one" } else { "complete" },
                &trace,
                scope,
                vec![],
            ))
            .finish();
        case.check(&run);
        let result = run.record().unwrap().as_json();
        assert_eq!(result["outcome"], "infrastructure_error");
        assert_eq!(result["backend_exit_code"], u8::from(failed));
        assert_eq!(result["accounting_verified"], true);
        assert_eq!(result["work_complete"], scope == RequestedScope::Explicit);
        assert_eq!(result["generation"]["assurance"], "unverified");
        assert_eq!(
            fs::read_to_string(case.work.join("started-once")).unwrap(),
            "one execution effect\n"
        );
    }
}

#[test]
fn only_live_ready_claims_can_publish_the_owned_request_report_and_still_never_certify_execution() {
    let case = Case::new("bound-required-report");
    let declaration = declaration(true);
    let mut trace = passing();
    ready(
        &mut trace,
        &declaration.expected_content.as_ref().unwrap().sha256,
        true,
    );
    let run = case
        .observe(case.request(
            "complete",
            &trace,
            RequestedScope::Explicit,
            vec![declaration],
        ))
        .finish();
    case.check(&run);
    let result = run.record().unwrap().as_json();
    assert_eq!(result["artifacts_verified"], true);
    assert_eq!(result["artifacts"][0]["complete"], true);
    assert_eq!(result["outcome"], "infrastructure_error");
    assert_eq!(
        fs::read(case.retained.join("private/artifact-report-1")).unwrap(),
        REPORT
    );
}

#[test]
fn complete_looking_source_without_live_readiness_stays_pending_and_is_not_recovered() {
    let case = Case::new("report-no-ready");
    let run = case
        .observe(case.request(
            "complete",
            &passing(),
            RequestedScope::Explicit,
            vec![declaration(true)],
        ))
        .finish();
    case.check(&run);
    let result = run.record().unwrap().as_json();
    assert_eq!(result["artifacts_verified"], false);
    assert_eq!(result["artifacts"][0]["status"], "pending");
    assert_eq!(result["artifacts"][0]["sha256"], Value::Null);
    assert_eq!(
        fs::read(case.work.join("complete-looking.xml")).unwrap(),
        REPORT
    );
    assert!(!case.retained.join("private/artifact-report-1").exists());
}

#[test]
fn bad_hash_partial_unknown_required_and_optional_failures_keep_exact_distinct_states() {
    for mode in ["bad-hash", "partial", "unknown", "optional-bad-hash"] {
        let case = Case::new(&format!("artifact-{mode}"));
        let mut declaration = declaration(mode != "optional-bad-hash");
        let mut trace = passing();
        let digest = declaration
            .expected_content
            .as_ref()
            .unwrap()
            .sha256
            .clone();
        ready(
            &mut trace,
            if mode.contains("bad-hash") {
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            } else {
                &digest
            },
            mode != "partial",
        );
        if mode == "unknown" {
            declaration.expected_content = None;
        }
        let run = case
            .observe(case.request(
                "complete",
                &trace,
                RequestedScope::Explicit,
                vec![declaration],
            ))
            .finish();
        case.check(&run);
        let result = run.record().unwrap().as_json();
        assert_eq!(result["artifacts_verified"], mode == "optional-bad-hash");
        if mode.contains("bad-hash") {
            assert_eq!(result["artifacts"][0]["status"], "failed");
            assert!(matches!(
                run.artifact_state("report-1"),
                Some(ArtifactState::Failed {
                    publication_may_exist: false,
                    ..
                })
            ));
        } else {
            assert_eq!(result["artifacts"][0]["status"], "committed");
            assert_eq!(result["artifacts"][0]["complete"], false);
            assert_eq!(
                fs::read(case.retained.join("private/artifact-report-1")).unwrap(),
                REPORT
            );
        }
    }
}

#[test]
fn destination_race_and_missing_normal_terminal_cannot_be_relabelled_from_saved_artifacts() {
    let case = Case::new("destination-race");
    let declaration = declaration(true);
    let mut trace = passing();
    ready(
        &mut trace,
        &declaration.expected_content.as_ref().unwrap().sha256,
        true,
    );
    let observed = case.observe(case.request(
        "complete",
        &trace,
        RequestedScope::Explicit,
        vec![declaration],
    ));
    fs::write(
        case.retained.join("private/artifact-report-1"),
        b"foreign bytes remain",
    )
    .unwrap();
    let run = observed.finish();
    case.check(&run);
    assert_eq!(
        run.record().unwrap().as_json()["artifacts"][0]["status"],
        "failed"
    );
    assert_eq!(
        fs::read(case.retained.join("private/artifact-report-1")).unwrap(),
        b"foreign bytes remain"
    );
    let case = Case::new("no-normal-terminal");
    let mut trace = passing();
    trace.rows.pop();
    let run = case
        .observe(case.request("early_zero", &trace, RequestedScope::Explicit, vec![]))
        .finish();
    case.check(&run);
    assert_eq!(
        run.record().unwrap().as_json()["accounting_verified"],
        false
    );
    assert_eq!(
        run.record().unwrap().as_json()["accounting"]["completed_count"],
        1
    );
    assert_eq!(
        run.record().unwrap().as_json()["outcome"],
        "infrastructure_error"
    );
}

#[test]
fn known_timeout_signal_and_undocumented_exit_preserve_raw_causes_without_inventing_transport_corruption()
 {
    for mode in ["timeout_partial", "signal_partial", "truncated_exit"] {
        let case = Case::new(mode);
        let mut trace = passing();
        trace.rows.truncate(8);
        let mut serial = case.serial(mode, &trace);
        if mode == "timeout_partial" {
            serial.process.timeout = Duration::from_millis(250);
        }
        let request = RunRequest::new(
            serial,
            RequestedScope::Explicit,
            "coordinator-1".into(),
            vec![],
        )
        .unwrap();
        let run = case.observe(request).finish();
        case.check(&run);
        let result = run.record().unwrap().as_json();
        assert_eq!(result["accounting_verified"], false);
        assert_eq!(result["current_full_success"], false);
        assert_eq!(result["infrastructure_status"], "ok");
        if mode == "timeout_partial" {
            assert_eq!(result["outcome"], "timeout");
            assert_eq!(result["stop_cause"], "timeout");
        } else {
            assert_eq!(result["outcome"], "backend_terminated");
        }
        if mode == "signal_partial" {
            assert_eq!(result["backend_signal"], 9);
            assert_eq!(result["cli_exit_code"], 137);
        }
        if mode == "truncated_exit" {
            assert_eq!(result["backend_exit_code"], 17);
            assert_eq!(result["cli_exit_code"], 3);
        }
    }
}

#[test]
fn launch_failure_and_prelaunch_cancellation_have_actual_not_started_accounting() {
    for cancel in [false, true] {
        let case = Case::new(if cancel {
            "prelaunch-cancel"
        } else {
            "launch-failure"
        });
        let mut serial = case.serial("complete", &passing());
        if !cancel {
            serial.process.executable = "/absent/pt-coordinator-test".into();
        }
        let request = RunRequest::new(
            serial,
            RequestedScope::Explicit,
            "coordinator-1".into(),
            vec![],
        )
        .unwrap();
        let run = request
            .observe_development(
                case.retention(),
                &AtomicI32::new(if cancel { 2 } else { 0 }),
            )
            .unwrap()
            .finish();
        case.check(&run);
        let result = run.record().unwrap().as_json();
        assert_eq!(
            result["outcome"],
            if cancel {
                "interrupted"
            } else {
                "launch_error"
            }
        );
        assert_eq!(result["accounting"]["executed_count"], 0);
        assert_eq!(result["cleanup"]["status"], "not_started");
        assert!(!case.work.join("started-once").exists());
    }
}

#[test]
fn live_tree_identity_stays_uncertain_and_wrong_request_tree_cannot_be_adopted() {
    for same in [true, false] {
        let case = Case::new(if same {
            "live-tree-uncertain"
        } else {
            "wrong-tree"
        });
        let observed =
            case.observe(case.request("complete", &passing(), RequestedScope::Explicit, vec![]));
        let source = if same {
            case.work.clone()
        } else {
            let path = case.path.join("other-root");
            private(&path);
            path
        };
        // The purpose is request association and assurance demotion, not deriving
        // independent expected environment bytes from an observed test tree.
        let entries = if same {
            let mut values = Vec::new();
            for name in ["complete-looking.xml", "started-once"] {
                let raw = fs::read(source.join(name)).unwrap();
                let info = fs::metadata(source.join(name)).unwrap();
                use std::os::unix::fs::MetadataExt;
                values.push(pt_identity::TreeEntry {
                    path: name.into(),
                    mode: info.mode() & 0o7777,
                    kind: pt_identity::TreeKind::File {
                        bytes: raw.len() as u64,
                        mtime_ns: info.mtime() as i128 * 1_000_000_000 + info.mtime_nsec() as i128,
                        sha256: Sha256::digest(&raw).into(),
                    },
                });
            }
            values
        } else {
            vec![]
        };
        let manifest = pt_identity::TreeManifest::new(
            0o700,
            entries,
            pt_identity::TreeLimits {
                entries: 100,
                per_file_bytes: 1024 * 1024,
                total_bytes: 4 * 1024 * 1024,
                path_bytes: 65536,
                deadline: Instant::now() + Duration::from_secs(10),
            },
        )
        .unwrap();
        let tree = manifest.verify(&source).unwrap();
        let run = observed.finish_with_live_tree(tree);
        if same {
            case.check(&run);
            assert_eq!(
                run.record().unwrap().as_json()["outcome"],
                "generation_invalid"
            );
            assert_eq!(
                run.record().unwrap().as_json()["generation"]["status"],
                "uncertain"
            );
            assert_eq!(
                run.record().unwrap().as_json()["generation"]["declared_inputs_complete"],
                false
            );
        } else {
            case.save(&run);
            assert_eq!(
                run.record().unwrap_err().code(),
                "final_tree_request_mismatch"
            );
            assert_eq!(run.session().process().exit_code(), 0);
        }
    }
}

#[test]
fn command_identity_preserves_raw_boundaries_without_exporting_or_claiming_environment_identity() {
    let case = Case::new("command-raw-identity");
    let mut serial = case.serial("args", &passing());
    use std::os::unix::ffi::OsStringExt;
    serial.process.args.extend([
        "".into(),
        "λ a/b".into(),
        std::ffi::OsString::from_vec(vec![b'x', 0xff]),
    ]);
    let request = RunRequest::new(
        serial,
        RequestedScope::Explicit,
        "coordinator-1".into(),
        vec![],
    )
    .unwrap();
    let digest = request.command_sha256().to_owned();
    let mut other = case.serial("args", &passing());
    other.process.args.extend([
        "λ a/b".into(),
        std::ffi::OsString::from_vec(vec![b'x', 0xff]),
    ]);
    assert_ne!(
        digest,
        RunRequest::new(
            other,
            RequestedScope::Explicit,
            "coordinator-1".into(),
            vec![]
        )
        .unwrap()
        .command_sha256()
    );
    let run = case.observe(request).finish();
    case.check(&run);
    assert_eq!(run.command_sha256(), digest);
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(case.work.join("arguments.json")).unwrap())
            .unwrap(),
        json!(["", "cebb20612f62", "78ff"])
    );
    assert!(
        !run.record()
            .unwrap()
            .as_json()
            .as_object()
            .unwrap()
            .contains_key("environment")
    );
}

#[test]
fn invalid_domain_identity_arguments_and_budgets_fail_before_store_or_effects() {
    for mode in [
        "domain",
        "identity",
        "nul",
        "relative",
        "arguments",
        "budget",
        "lifetime",
    ] {
        let case = Case::new(&format!("invalid-{mode}"));
        let mut serial = case.serial("complete", &passing());
        let mut coordinator = "coordinator-1".to_owned();
        match mode {
            "domain" => serial.contract.declared_artifact_ids = vec!["other".into()],
            "identity" => coordinator = "bridge-1".into(),
            "nul" => serial.process.args.push(std::ffi::OsString::from("a\0b")),
            "relative" => serial.process.cwd = ".".into(),
            "arguments" => serial.process.args.push("x".repeat(65537).into()),
            "budget" => serial.stream_budget.events = 0,
            _ => serial.process.timeout = Duration::from_secs(3600),
        }
        let error = match RunRequest::new(serial, RequestedScope::Explicit, coordinator, vec![]) {
            Err(error) => error,
            Ok(_) => panic!("invalid {mode} request accepted"),
        };
        fs::write(case.path.join("setup-rejection.json"),serde_json::to_vec_pretty(&json!({"code":error.code(),"error":error.to_string(),"work_started":false,"qualified":false})).unwrap()).unwrap();
        assert!(!case.work.join("started-once").exists());
        assert!(!case.retained.join("private").exists());
    }
    let case = Case::new("invalid-report-path");
    let mut serial = case.serial("complete", &passing());
    serial.contract.declared_artifact_ids = vec!["report-1".into()];
    let mut report = declaration(true);
    report.source = "../foreign".into();
    let error = match RunRequest::new(
        serial,
        RequestedScope::Explicit,
        "coordinator-1".into(),
        vec![report],
    ) {
        Err(error) => error,
        Ok(_) => panic!("invalid report path accepted"),
    };
    assert_eq!(error.code(), "request_report_declaration_invalid");
    fs::write(case.path.join("setup-rejection.json"),serde_json::to_vec_pretty(&json!({"code":error.code(),"error":error.to_string(),"work_started":false,"qualified":false})).unwrap()).unwrap();
    assert!(!case.retained.join("private").exists());
    assert!(!case.work.join("started-once").exists());
}

#[test]
fn lost_accounting_and_record_budget_failure_remain_unavailable_instead_of_invented_zero_results() {
    assert_eq!(
        required_snapshot(None).unwrap_err().code(),
        "final_accounting_unknown"
    );
    let case = Case::new("record-bounds");
    let request = case.request("complete", &passing(), RequestedScope::Explicit, vec![]);
    let mut records = Records::new(&request.facts);
    fs::write(
        case.path.join("validation-only.json"),
        serde_json::to_vec_pretty(
            &json!({"mode":"synthetic_record_limits_only","work_started":false,"qualified":false}),
        )
        .unwrap(),
    )
    .unwrap();
    assert!(
        records
            .push(
                "infrastructure_error",
                json!({"code":"too_large","message":"x".repeat(1024*1024)})
            )
            .is_err()
    );
    assert!(records.values.is_empty());
    let mut value = base_result(
        &request.facts,
        &not_started_accounting(),
        &PhaseCounts::default(),
    );
    value["current_full_success"] = json!(true);
    assert!(FinalRecord::new(value).is_err());
}

#[test]
fn matching_junit_unknown_context_and_unsupported_xml_keep_separate_native_publication_outcomes() {
    let raw = b"<?xml version=\"1.0\" encoding=\"utf-8\"?><testsuites name=\"pytest tests\"><testsuite name=\"pytest\" errors=\"0\" failures=\"0\" skipped=\"0\" tests=\"1\" time=\"0.001\" timestamp=\"2026-11-10T12:34:56.123456+00:00\" hostname=\"test-host\"><testcase classname=\"x\" name=\"test_one\" time=\"0.000\" /></testsuite></testsuites>";
    for mode in ["matching", "unknown-context", "unsupported-xml"] {
        let case = Case::new(&format!("junit-{mode}"));
        let raw = if mode == "unsupported-xml" {
            String::from_utf8(raw.to_vec())
                .unwrap()
                .replace("classname=\"x\"", "classname=\"x\" file=\"x.py\"")
                .into_bytes()
        } else {
            raw.to_vec()
        };
        let declaration = ArtifactDeclaration {
            artifact_id: "junit".into(),
            source: "requested.xml".into(),
            required: true,
            expected_content: None,
            junit_policy: Some(
                pt_report::JunitPolicy::xunit2(
                    "pytest".into(),
                    None,
                    pt_report::JunitLimits {
                        bytes: 512 * 1024,
                        testcases: 256,
                        events: 10000,
                    },
                )
                .unwrap(),
            ),
        };
        let mut trace = passing();
        if mode == "unknown-context" {
            for report_id in [0, 1] {
                trace.rows.insert(2,("collection_report".into(),json!({"report_id":report_id,"nodeid":"skipped.py","outcome":"skipped","reason":"synthetic collector skip"})));
            }
        }
        let terminal = trace.rows.pop().unwrap();
        trace.push("artifact_ready",json!({"artifact_id":"junit","sha256":Sha256::digest(&raw).iter().map(|value|format!("{value:02x}")).collect::<String>(),"bytes":raw.len(),"complete":true}));
        trace.rows.push(terminal);
        let request = case.request(
            "complete",
            &trace,
            RequestedScope::Explicit,
            vec![declaration],
        );
        fs::write(case.work.join("requested.xml"), &raw).unwrap();
        let run = case.observe(request).finish();
        case.check(&run);
        let result = run.record().unwrap().as_json();
        assert_eq!(result["artifacts_verified"], mode == "matching");
        if mode == "unsupported-xml" {
            assert_eq!(result["artifacts"][0]["status"], "failed");
        } else {
            assert_eq!(result["artifacts"][0]["status"], "committed");
            assert_eq!(result["artifacts"][0]["complete"], mode == "matching");
            assert_eq!(
                fs::read(case.retained.join("private/artifact-junit")).unwrap(),
                raw
            );
        }
        if mode == "unknown-context" {
            assert_eq!(run.artifact_diagnostics().len(), 1);
            assert_eq!(run.artifact_diagnostics()[0].artifact_id(), "junit");
            assert_eq!(
                run.artifact_diagnostics()[0].code(),
                "junit_context_unavailable"
            );
            assert!(run.artifact_diagnostics()[0].detail().contains("junit_"));
        }
    }
}

#[test]
fn postlaunch_cancellation_handled_as_zero_and_late_finalization_never_lose_their_failure_cause() {
    let case = Case::new("cancel-then-raw-zero");
    let mut trace = passing();
    trace.rows.truncate(8);
    let request = case.request("cancel_zero", &trace, RequestedScope::Explicit, vec![]);
    let cancelled = AtomicI32::new(0);
    let run = std::thread::scope(|scope| {
        let flag = &cancelled;
        let started = case.work.join("complete-looking.xml");
        scope.spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(2);
            while !started.exists() && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(5));
            }
            flag.store(15, std::sync::atomic::Ordering::SeqCst);
        });
        request
            .observe_development(case.retention(), &cancelled)
            .unwrap()
            .finish()
    });
    case.check(&run);
    let result = run.record().unwrap().as_json();
    assert_eq!(result["outcome"], "interrupted");
    assert_eq!(result["backend_exit_code"], 0);
    assert_eq!(result["cli_exit_code"], 2);
    assert_eq!(result["interruption_signal"], 15);
    let case = Case::new("late-finalization");
    let mut observed =
        case.observe(case.request("complete", &passing(), RequestedScope::Explicit, vec![]));
    observed.deadline = Instant::now();
    let run = observed.finish();
    case.check(&run);
    assert_eq!(
        run.record().unwrap().as_json()["outcome"],
        "infrastructure_error"
    );
    assert!(
        run.record().unwrap().as_json()["errors"]
            .as_array()
            .unwrap()
            .iter()
            .any(|value| value["code"] == "coordinator_finalization_deadline_expired")
    );
}
