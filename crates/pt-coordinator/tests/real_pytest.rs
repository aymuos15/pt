#![cfg(all(target_os = "linux", target_env = "gnu", target_arch = "x86_64"))]
//! Explicit unqualified development observations. This prepared env wrapper is
//! test setup, not an authorized production bootstrap or product-timing arm.
use pt_coordinator::{FinishedRun, RequestedScope, RetentionTarget, RunRequest};
use pt_process::{Cleanup, ProcessRequest, supervise};
use pt_protocol::{ChannelIdentity, InvocationProfile, RequestMode, SerialContract, StreamBudget};
use pt_report::{ArtifactDeclaration, JunitLimits, JunitPolicy, RetentionBudget};
use pt_session::SerialRequest;
use serde_json::{Value, json};
use std::fs::{self, OpenOptions};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicI32;
use std::time::{Duration, Instant};

const SOURCE: &str = r#"from pathlib import Path
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
def test_third():
    assert state==1
    effect('third')
"#;
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
fn validation_python() -> PathBuf {
    std::env::var_os("PT_TEST_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| root().join("bench/harness/.venv/bin/python"))
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
    fn new(id: &str, source: &str, conftest: Option<&str>) -> Self {
        let (temp, path) = if let Some(parent) = std::env::var_os("PT_COORDINATOR_CASE_ROOT") {
            let path = PathBuf::from(parent).join(id);
            private(&path);
            (None, path)
        } else {
            let temp = tempfile::Builder::new()
                .prefix("pt-coordinator-pytest-")
                .tempdir_in("/tmp/opencode")
                .unwrap();
            let path = temp.path().to_path_buf();
            (Some(temp), path)
        };
        let work = path.join("work");
        private(&work);
        let retained = path.join("retained");
        private(&retained);
        fs::write(work.join("test_actual.py"), source).unwrap();
        if let Some(conftest) = conftest {
            fs::write(work.join("conftest.py"), conftest).unwrap();
        }
        Self {
            _temp: temp,
            path,
            work,
            retained,
        }
    }
    fn request(
        &self,
        id: &str,
        args: &[&str],
        mode: RequestMode,
        profile: InvocationProfile,
        scope: RequestedScope,
        report: bool,
    ) -> RunRequest {
        self.request_report(
            id,
            args,
            mode,
            profile,
            scope,
            if report { Some(false) } else { None },
        )
    }
    fn request_report(
        &self,
        id: &str,
        args: &[&str],
        mode: RequestMode,
        profile: InvocationProfile,
        scope: RequestedScope,
        report: Option<bool>,
    ) -> RunRequest {
        let mut configuration = json!({"schema_version":1,"fd":3,"identity":{"request_id":id,"run_id":"coordinator-run","generation_id":"unqualified-generation","session_id":"coordinator-session","producer_id":"coordinator-bridge"},
            "invocation_profile":if profile==InvocationProfile::PytestModule {"pytest_module"}else{"pytest_console"},"mode":if mode==RequestMode::Run {"run"}else{"collect_only"},
            "max_items":256,"max_collection_reports":1024,"max_nodeid_bytes":1024*1024,"byte_budget":8*1024*1024,"event_budget":25000,"timeout_seconds":30});
        if report == Some(true) {
            configuration["schema_version"] = json!(2);
            configuration["junit_artifact"] = json!({"artifact_id":"junit","source":"requested.xml","max_bytes":1024*1024,"required":true});
        }
        let mut argv = vec![
            format!("PT_BRIDGE_CONTROL={configuration}").into(),
            format!(
                "PYTHONPATH={}",
                root().join("python/pt_bridge/src").display()
            )
            .into(),
            "PYTHONDONTWRITEBYTECODE=1".into(),
        ];
        if profile == InvocationProfile::PytestModule {
            argv.extend([
                python().into_os_string(),
                "-B".into(),
                "-m".into(),
                "pytest".into(),
            ]);
        } else {
            argv.push(python().parent().unwrap().join("pytest").into_os_string());
        }
        argv.extend(["-q".into(), "-p".into(), "pt_bridge.pytest_observer".into()]);
        argv.extend(args.iter().map(std::ffi::OsString::from));
        let mut declarations = vec![];
        if report.is_some() {
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(self.work.join("requested.xml"))
                .unwrap();
            argv.push("--junitxml=requested.xml".into());
            declarations.push(ArtifactDeclaration {
                artifact_id: "junit".into(),
                source: "requested.xml".into(),
                required: true,
                expected_content: None,
                junit_policy: Some(
                    JunitPolicy::xunit2(
                        "pytest".into(),
                        None,
                        JunitLimits {
                            bytes: 1024 * 1024,
                            testcases: 256,
                            events: 10000,
                        },
                    )
                    .unwrap(),
                ),
            });
        }
        fs::write(self.path.join("invocation.json"),serde_json::to_vec_pretty(&json!({"argv":argv.iter().map(|value:&std::ffi::OsString|value.to_string_lossy().into_owned()).collect::<Vec<_>>(),"qualified":false})).unwrap()).unwrap();
        RunRequest::new(
            SerialRequest {
                process: ProcessRequest {
                    executable: "/usr/bin/env".into(),
                    args: argv,
                    cwd: self.work.clone(),
                    timeout: Duration::from_secs(30),
                    cleanup_timeout: Duration::from_secs(1),
                },
                identity: ChannelIdentity {
                    request_id: id.into(),
                    run_id: "coordinator-run".into(),
                    generation_id: "unqualified-generation".into(),
                    session_id: "coordinator-session".into(),
                    producer_id: "coordinator-bridge".into(),
                },
                contract: SerialContract {
                    invocation_profile: profile,
                    mode,
                    max_items: 256,
                    max_collection_reports: 1024,
                    max_nodeid_bytes: 1024 * 1024,
                    declared_artifact_ids: if report.is_some() {
                        vec!["junit".into()]
                    } else {
                        vec![]
                    },
                },
                stream_budget: StreamBudget {
                    bytes: 8 * 1024 * 1024,
                    events: 25000,
                },
                drain_allowance: Duration::from_secs(1),
            },
            scope,
            "coordinator-owner".into(),
            declarations,
        )
        .unwrap()
    }
    fn invoke(&self, request: RunRequest) -> FinishedRun {
        let run = request
            .observe_development(
                RetentionTarget {
                    parent: self.retained.clone(),
                    private_name: "private".into(),
                    budget: RetentionBudget {
                        files: 8,
                        bytes: 2 * 1024 * 1024,
                        per_file_bytes: 1024 * 1024,
                        deadline: Instant::now() + Duration::from_secs(45),
                    },
                },
                &AtomicI32::new(0),
            )
            .unwrap()
            .finish();
        assert_eq!(run.session().process().cleanup, Cleanup::Complete);
        let record = run.record().unwrap();
        assert!(record.cli_exit_code() > 0);
        assert_eq!(record.as_json()["current_full_success"], false);
        assert_eq!(record.as_json()["environment_verified"], false);
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
        let source = self.path.join("native-records.json");
        let output = self.path.join("independent-shape.json");
        fs::write(&source,serde_json::to_vec_pretty(&json!({"coordinator_records":run.coordinator_records(),"final_result":record.as_json(),"native_process":run.session().process(),"qualified":false})).unwrap()).unwrap();
        let process = supervise(
            &ProcessRequest {
                executable: validation_python().into_os_string(),
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
                    output.into_os_string(),
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
        run
    }
    fn xml_probe(&self) -> Value {
        let output = self.path.join("independent-junit.json");
        let process = supervise(
            &ProcessRequest {
                executable: python().into_os_string(),
                args: vec![
                    "-I".into(),
                    "-S".into(),
                    "-B".into(),
                    root()
                        .join("crates/pt-report/tests/junit_reference.py")
                        .into_os_string(),
                    self.work.join("requested.xml").into_os_string(),
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
            self.path.join("xml-oracle-process.json"),
            serde_json::to_vec_pretty(&process).unwrap(),
        )
        .unwrap();
        assert_eq!(process.exit_code(), 0);
        assert_eq!(process.cleanup, Cleanup::Complete);
        serde_json::from_slice(&fs::read(output).unwrap()).unwrap()
    }
    fn check_junit_copy(&self, run: &FinishedRun, complete: bool) {
        let oracle = self.xml_probe();
        let result = run.record().unwrap().as_json();
        let claim = &run.session().snapshot().unwrap().artifact_ready_claims[0];
        assert_eq!(claim.artifact_id, "junit");
        assert_eq!(claim.sha256, oracle["sha256"].as_str().unwrap());
        assert_eq!(claim.bytes, oracle["bytes"].as_u64().unwrap());
        assert_eq!(result["artifacts"][0]["status"], "committed");
        assert_eq!(result["artifacts"][0]["sha256"], oracle["sha256"]);
        assert_eq!(result["artifacts"][0]["complete"], complete);
        assert_eq!(result["artifacts_verified"], complete);
        assert_eq!(
            fs::read(self.work.join("requested.xml")).unwrap(),
            fs::read(self.retained.join("private/artifact-junit")).unwrap()
        );
    }
}

#[test]
fn both_entrypoints_keep_one_fresh_authoritative_session_but_neither_can_claim_qualified_zero() {
    let mut pids = vec![];
    for (id, profile, scope) in [
        (
            "coordinator-pytest-module",
            InvocationProfile::PytestModule,
            RequestedScope::Full,
        ),
        (
            "coordinator-pytest-console",
            InvocationProfile::PytestConsole,
            RequestedScope::Explicit,
        ),
    ] {
        let case = Case::new(id, SOURCE, None);
        let run = case.invoke(case.request(
            id,
            &["test_actual.py"],
            RequestMode::Run,
            profile,
            scope,
            false,
        ));
        pids.push(run.session().process().pid.unwrap());
        let value = run.record().unwrap().as_json();
        assert_eq!(value["backend_exit_code"], 0);
        assert_eq!(value["accounting"]["completed_count"], 3);
        assert_eq!(value["accounting_verified"], true);
        assert_eq!(value["outcome"], "infrastructure_error");
        assert_eq!(value["work_complete"], scope == RequestedScope::Explicit);
        assert_eq!(
            fs::read_to_string(case.work.join("effects")).unwrap(),
            "import\nsetup\nfirst\nsecond\nthird\nteardown\n"
        );
        assert_eq!(
            fs::read_to_string(case.work.join("test_actual.py")).unwrap(),
            SOURCE
        );
    }
    assert_ne!(pids[0], pids[1]);
}

#[test]
fn real_failure_failfast_collect_only_and_empty_selection_preserve_raw_status_and_not_run_scope() {
    let failing = SOURCE.replace(
        "effect('second')",
        "effect('second')\n    assert False,'PT_COORDINATOR_FAILURE'",
    );
    for (id, args, mode, code, executed, not_run) in [
        (
            "coordinator-pytest-failure",
            vec!["test_actual.py"],
            RequestMode::Run,
            1,
            3,
            0,
        ),
        (
            "coordinator-pytest-failfast",
            vec!["-x", "test_actual.py"],
            RequestMode::Run,
            1,
            2,
            1,
        ),
        (
            "coordinator-pytest-collect",
            vec!["--collect-only", "test_actual.py"],
            RequestMode::CollectOnly,
            0,
            0,
            3,
        ),
        (
            "coordinator-pytest-no-tests",
            vec!["-k", "not_present", "test_actual.py"],
            RequestMode::Run,
            5,
            0,
            0,
        ),
    ] {
        let case = Case::new(id, &failing, None);
        let run = case.invoke(case.request(
            id,
            &args,
            mode,
            InvocationProfile::PytestModule,
            RequestedScope::Explicit,
            false,
        ));
        let value = run.record().unwrap().as_json();
        assert_eq!(value["backend_exit_code"], code);
        assert_eq!(value["accounting"]["executed_count"], executed);
        assert_eq!(value["accounting"]["not_run_count"], not_run);
        assert_eq!(value["current_full_success"], false);
        if executed == 0 {
            assert_eq!(
                fs::read_to_string(case.work.join("effects")).unwrap(),
                "import\n"
            );
        }
        assert_eq!(
            fs::read_to_string(case.work.join("test_actual.py")).unwrap(),
            failing
        );
    }
}

#[test]
fn real_interruption_kill_and_outer_finalizer_keep_partial_work_and_actual_cleanup_effects() {
    for (id, body) in [
        (
            "coordinator-pytest-interrupt",
            "raise KeyboardInterrupt('PT_COORDINATOR_INTERRUPT')",
        ),
        (
            "coordinator-pytest-kill",
            "os.kill(os.getpid(),signal.SIGKILL)",
        ),
    ] {
        let source = format!(
            "import os,signal\nfrom pathlib import Path\ndef test_actual():\n    with Path('started-once').open('x') as output: output.write('effect')\n    {body}\n"
        );
        let case = Case::new(id, &source, None);
        let run = case.invoke(case.request(
            id,
            &["test_actual.py"],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            RequestedScope::Explicit,
            false,
        ));
        let value = run.record().unwrap().as_json();
        assert_eq!(value["accounting"]["executed_count"], 1);
        assert_eq!(value["accounting"]["completed_count"], 0);
        assert_eq!(value["incomplete_ordinals"], json!([0]));
        assert_eq!(value["work_complete"], false);
        if id.ends_with("kill") {
            assert_eq!(value["outcome"], "backend_terminated");
            assert_eq!(value["backend_signal"], 9);
            assert_eq!(value["cli_exit_code"], 137);
        } else {
            assert_eq!(value["backend_exit_code"], 2);
        }
        assert_eq!(
            fs::read_to_string(case.work.join("started-once")).unwrap(),
            "effect"
        );
    }
    let id = "coordinator-pytest-outer-finalizer";
    let conftest = "import pytest,time\nfrom pathlib import Path\n@pytest.hookimpl(wrapper=True,tryfirst=True)\ndef pytest_unconfigure(config):\n    result=yield\n    time.sleep(0.1)\n    Path('outer-finished').write_text('cleanup retained')\n    return result\n";
    let case = Case::new(id, "def test_actual():\n    pass\n", Some(conftest));
    let run = case.invoke(case.request(
        id,
        &["test_actual.py"],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        RequestedScope::Explicit,
        false,
    ));
    assert_eq!(run.session().process().exit_code(), 0);
    assert_eq!(
        run.record().unwrap().as_json()["outcome"],
        "infrastructure_error"
    );
    assert_eq!(run.record().unwrap().as_json()["reporting_complete"], false);
    assert_eq!(
        fs::read_to_string(case.work.join("outer-finished")).unwrap(),
        "cleanup retained"
    );
}

#[test]
fn actual_junit_file_without_bridge_ready_is_not_adopted_as_required_complete() {
    let id = "coordinator-pytest-report-no-ready";
    let case = Case::new(id, SOURCE, None);
    let run = case.invoke(case.request(
        id,
        &["test_actual.py"],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        RequestedScope::Explicit,
        true,
    ));
    let value = run.record().unwrap().as_json();
    assert_eq!(value["backend_exit_code"], 0);
    assert_eq!(value["artifacts_verified"], false);
    assert_eq!(value["artifacts"][0]["status"], "pending");
    assert_eq!(value["artifacts"][0]["sha256"], Value::Null);
    assert!(fs::read(case.work.join("requested.xml")).unwrap().len() > 100);
    assert!(!case.retained.join("private/artifact-junit").exists());
}

#[test]
fn explicitly_requested_real_junit_readiness_flows_through_native_owned_publication_without_qualifying_the_run()
 {
    let failing = SOURCE.replace(
        "effect('second')",
        "effect('second')\n    assert False,'PT_DECLARED_JUNIT_FAILURE'",
    );
    for (id, source, args, mode, profile, code) in [
        (
            "declared-junit-module",
            SOURCE,
            vec!["test_actual.py"],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            0,
        ),
        (
            "declared-junit-console-failure",
            failing.as_str(),
            vec!["test_actual.py"],
            RequestMode::Run,
            InvocationProfile::PytestConsole,
            1,
        ),
        (
            "declared-junit-collect",
            SOURCE,
            vec!["--collect-only", "test_actual.py"],
            RequestMode::CollectOnly,
            InvocationProfile::PytestModule,
            0,
        ),
        (
            "declared-junit-no-tests",
            SOURCE,
            vec!["-k", "not_present", "test_actual.py"],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            5,
        ),
    ] {
        let case = Case::new(id, source, None);
        let run = case.invoke(case.request_report(
            id,
            &args,
            mode,
            profile,
            RequestedScope::Explicit,
            Some(true),
        ));
        assert_eq!(run.session().process().exit_code(), code);
        assert_eq!(
            run.session()
                .snapshot()
                .unwrap()
                .artifact_ready_claims
                .len(),
            1
        );
        case.check_junit_copy(&run, true);
        assert!(run.record().unwrap().cli_exit_code() > 0);
        assert_eq!(
            run.record().unwrap().as_json()["environment_verified"],
            false
        );
        assert_eq!(
            run.record().unwrap().as_json()["current_full_success"],
            false
        );
        assert_eq!(
            fs::read_to_string(case.work.join("test_actual.py")).unwrap(),
            source
        );
    }
}

#[test]
fn interrupted_and_unsupported_real_junit_do_not_inherit_completeness_from_ready_hash_agreement() {
    let id = "declared-junit-interrupted";
    let source = "from pathlib import Path\ndef test_actual():\n    with Path('started-once').open('x') as output: output.write('effect')\n    raise KeyboardInterrupt('PT_DECLARED_JUNIT_INTERRUPT')\n";
    let case = Case::new(id, source, None);
    let run = case.invoke(case.request_report(
        id,
        &["test_actual.py"],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        RequestedScope::Explicit,
        Some(true),
    ));
    assert_eq!(run.session().process().exit_code(), 2);
    assert!(!run.session().snapshot().unwrap().artifact_ready_claims[0].complete);
    case.check_junit_copy(&run, false);
    assert!(!run.artifact_diagnostics().is_empty());
    assert_eq!(
        fs::read_to_string(case.work.join("started-once")).unwrap(),
        "effect"
    );
    let id = "declared-junit-properties";
    let source =
        "def test_actual(record_property):\n    record_property('PT_PROPERTY','retained')\n";
    let case = Case::new(id, source, None);
    let run = case.invoke(case.request_report(
        id,
        &["test_actual.py"],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        RequestedScope::Explicit,
        Some(true),
    ));
    let oracle = case.xml_probe();
    assert_eq!(run.session().process().exit_code(), 0);
    assert!(run.session().snapshot().unwrap().artifact_ready_claims[0].complete);
    assert_eq!(
        run.session().snapshot().unwrap().artifact_ready_claims[0].sha256,
        oracle["sha256"].as_str().unwrap()
    );
    assert_eq!(
        run.record().unwrap().as_json()["artifacts"][0]["status"],
        "failed"
    );
    assert_eq!(run.record().unwrap().as_json()["artifacts_verified"], false);
    assert!(!case.retained.join("private/artifact-junit").exists());
}

#[test]
fn explicit_junit_read_failure_preserves_actual_pytest_zero_and_finalizer_effects_without_repair_or_replay()
 {
    let id = "declared-junit-removed-by-finalizer";
    let conftest = "from pathlib import Path\ndef pytest_unconfigure(config):\n    Path('requested.xml').unlink()\n    with Path('removal-once').open('x') as output: output.write('removed intentionally')\n";
    let case = Case::new(id, SOURCE, Some(conftest));
    let run = case.invoke(case.request_report(
        id,
        &["test_actual.py"],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        RequestedScope::Explicit,
        Some(true),
    ));
    let snapshot = run.session().snapshot().unwrap();
    assert_eq!(run.session().process().exit_code(), 0);
    assert!(snapshot.artifact_ready_claims.is_empty());
    assert!(
        snapshot
            .session_errors
            .iter()
            .any(|value| value.code == "junit_artifact_observation_failed")
    );
    assert!(!snapshot.terminal.as_ref().unwrap().reporting_complete);
    assert_eq!(
        run.record().unwrap().as_json()["artifacts"][0]["status"],
        "pending"
    );
    assert!(!case.work.join("requested.xml").exists());
    assert!(!case.retained.join("private/artifact-junit").exists());
    assert_eq!(
        fs::read_to_string(case.work.join("removal-once")).unwrap(),
        "removed intentionally"
    );
    assert_eq!(
        fs::read_to_string(case.work.join("effects")).unwrap(),
        "import\nsetup\nfirst\nsecond\nthird\nteardown\n"
    );
}
