#![cfg(all(target_os = "linux", target_env = "gnu", target_arch = "x86_64"))]
//! Actual session/process/EOF accounting plus required JUnit composition. This
//! explicitly prepared env wrapper is test setup, not a shipping launch policy.
use pt_process::{Cleanup, LeaderStatus, ProcessRequest, supervise};
use pt_protocol::{
    ArtifactReady, ChannelIdentity, InvocationProfile, RequestMode, SerialContract, StreamBudget,
};
use pt_report::{
    ArtifactDeclaration, ArtifactStore, JunitExpectation, JunitLimits, JunitPolicy,
    RetentionBudget, WritersStopped,
};
use pt_session::{SerialRequest, SessionObservation, SessionOutcome, observe_serial};
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
    assert False,'PT_JOINED_FAILURE'
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
fn private(path: &Path) {
    fs::create_dir(path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
struct Run {
    _temp: Option<tempfile::TempDir>,
    path: PathBuf,
    work: PathBuf,
    observed: SessionObservation,
    store: ArtifactStore,
    policy: JunitPolicy,
    deadline: Instant,
}

fn invoke(id: &str, source: &str, conftest: Option<&str>, args: &[&str], mode: RequestMode) -> Run {
    let (temp, path) = if let Some(parent) = std::env::var_os("PT_SESSION_CASE_ROOT") {
        let path = PathBuf::from(parent).join(id);
        private(&path);
        (None, path)
    } else {
        let temp = tempfile::Builder::new()
            .prefix("pt-session-pytest-")
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
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(work.join("junit.xml"))
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(45);
    let policy = JunitPolicy::xunit2(
        "pytest".into(),
        None,
        JunitLimits {
            bytes: 1024 * 1024,
            testcases: 256,
            events: 10000,
        },
    )
    .unwrap();
    let store = ArtifactStore::create(
        &work,
        &retained,
        "private",
        vec![ArtifactDeclaration {
            artifact_id: "junit".into(),
            source: "junit.xml".into(),
            required: true,
            expected_content: None,
            junit_policy: Some(policy.clone()),
        }],
        RetentionBudget {
            files: 1,
            bytes: 1024 * 1024,
            per_file_bytes: 1024 * 1024,
            deadline,
        },
    )
    .unwrap();
    let configuration = json!({"schema_version":1,"fd":3,"identity":{"request_id":id,"run_id":"joined-run","generation_id":"unqualified-generation","session_id":"joined-session","producer_id":"joined-bridge"},
        "invocation_profile":"pytest_module","mode":if mode==RequestMode::Run {"run"}else{"collect_only"},"max_items":256,"max_collection_reports":1024,"max_nodeid_bytes":1024*1024,"byte_budget":8*1024*1024,"event_budget":25000,"timeout_seconds":30});
    let mut argv = vec![
        format!("PT_BRIDGE_CONTROL={configuration}").into(),
        format!(
            "PYTHONPATH={}",
            root().join("python/pt_bridge/src").display()
        )
        .into(),
        "PYTHONDONTWRITEBYTECODE=1".into(),
        python().into_os_string(),
        "-B".into(),
        "-m".into(),
        "pytest".into(),
        "-q".into(),
        "-p".into(),
        "pt_bridge.pytest_observer".into(),
        "--junitxml=junit.xml".into(),
    ];
    argv.extend(args.iter().map(std::ffi::OsString::from));
    fs::write(path.join("invocation.json"),serde_json::to_vec_pretty(&json!({"argv":argv.iter().map(|value|value.to_string_lossy().into_owned()).collect::<Vec<_>>(),"qualified":false})).unwrap()).unwrap();
    let observed = observe_serial(
        SerialRequest {
            process: ProcessRequest {
                executable: "/usr/bin/env".into(),
                args: argv,
                cwd: work.clone(),
                timeout: Duration::from_secs(30),
                cleanup_timeout: Duration::from_secs(1),
            },
            identity: ChannelIdentity {
                request_id: id.into(),
                run_id: "joined-run".into(),
                generation_id: "unqualified-generation".into(),
                session_id: "joined-session".into(),
                producer_id: "joined-bridge".into(),
            },
            contract: SerialContract {
                invocation_profile: InvocationProfile::PytestModule,
                mode,
                max_items: 256,
                max_collection_reports: 1024,
                max_nodeid_bytes: 1024 * 1024,
                declared_artifact_ids: vec!["junit".into()],
            },
            stream_budget: StreamBudget {
                bytes: 8 * 1024 * 1024,
                events: 25000,
            },
            drain_allowance: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    fs::write(
        path.join("actual-process.json"),
        serde_json::to_vec_pretty(observed.process()).unwrap(),
    )
    .unwrap();
    fs::write(
        path.join("actual-observation.txt"),
        format!(
            "outcome={:?}\nchannel={:?}\nsnapshot={:#?}\nqualified=false\n",
            observed.outcome(),
            observed.channel(),
            observed.snapshot()
        ),
    )
    .unwrap();
    assert_eq!(observed.process().cleanup, Cleanup::Complete);
    assert_eq!(
        fs::read_to_string(work.join("test_actual.py")).unwrap(),
        source
    );
    Run {
        _temp: temp,
        path,
        work,
        observed,
        store,
        policy,
        deadline,
    }
}

fn publish(run: &mut Run) {
    let expectation = JunitExpectation::from_snapshot(
        run.policy.clone(),
        run.observed.normal_snapshot().unwrap(),
        run.deadline,
    )
    .unwrap();
    let output = run.path.join("independent-junit.json");
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
                run.work.join("junit.xml").into_os_string(),
                output.clone().into_os_string(),
            ],
            cwd: run.work.clone(),
            timeout: Duration::from_secs(5),
            cleanup_timeout: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    fs::write(
        run.path.join("oracle-process.json"),
        serde_json::to_vec_pretty(&process).unwrap(),
    )
    .unwrap();
    assert_eq!(process.exit_code(), 0);
    let oracle: Value = serde_json::from_slice(&fs::read(output).unwrap()).unwrap();
    let claim = ArtifactReady {
        artifact_id: "junit".into(),
        sha256: oracle["sha256"].as_str().unwrap().into(),
        bytes: oracle["bytes"].as_u64().unwrap(),
        complete: true,
    };
    let artifact = run
        .store
        .commit_with_junit(
            &claim,
            &WritersStopped::after_cleanup(run.observed.process()).unwrap(),
            &expectation,
        )
        .unwrap();
    assert!(artifact.complete());
    assert!(run.store.required_artifacts_satisfied());
    fs::write(run.path.join("junit-publication.json"),serde_json::to_vec_pretty(&json!({"sha256":artifact.sha256(),"bytes":artifact.bytes(),"projection_complete":artifact.complete(),"policy":run.policy.policy_id(),"qualified":false})).unwrap()).unwrap();
    assert_eq!(
        fs::read(run.work.join("junit.xml")).unwrap(),
        fs::read(run.path.join("retained/private/artifact-junit")).unwrap()
    );
}

#[test]
fn one_authoritative_pytest_session_has_fresh_globals_import_fixture_effects_and_bound_junit() {
    let mut pids = Vec::new();
    for index in 0..2 {
        let mut run = invoke(
            &format!("joined-fresh-{index}"),
            SOURCE,
            None,
            &["test_actual.py"],
            RequestMode::Run,
        );
        assert_eq!(
            run.observed.outcome(),
            &SessionOutcome::NormalExitAccounted {
                backend_exit_code: 1
            }
        );
        assert_eq!(
            run.observed
                .normal_snapshot()
                .unwrap()
                .accounting
                .completed_count,
            3
        );
        assert_eq!(
            fs::read_to_string(run.work.join("effects")).unwrap(),
            "import\nsetup\nfirst\nsecond\nthird\nteardown\n"
        );
        pids.push(run.observed.process().pid.unwrap());
        publish(&mut run);
        assert_eq!(run.observed.process().exit_code(), 1);
    }
    assert_ne!(pids[0], pids[1]);
}

#[test]
fn real_collect_only_fail_fast_and_no_tests_are_accounted_but_not_falsely_full_execution() {
    for (id, args, mode, code, completed, not_run) in [
        (
            "joined-collect",
            vec!["--collect-only", "test_actual.py"],
            RequestMode::CollectOnly,
            0,
            0,
            3,
        ),
        (
            "joined-failfast",
            vec!["-x", "test_actual.py"],
            RequestMode::Run,
            1,
            2,
            1,
        ),
        (
            "joined-no-tests",
            vec!["-k", "not_present", "test_actual.py"],
            RequestMode::Run,
            5,
            0,
            0,
        ),
    ] {
        let mut run = invoke(id, SOURCE, None, &args, mode);
        assert_eq!(
            run.observed.outcome(),
            &SessionOutcome::NormalExitAccounted {
                backend_exit_code: code
            }
        );
        let snapshot = run.observed.normal_snapshot().unwrap();
        assert_eq!(snapshot.accounting.completed_count, completed);
        assert_eq!(snapshot.accounting.not_run_count, not_run);
        if completed == 0 {
            assert_eq!(
                fs::read_to_string(run.work.join("effects")).unwrap(),
                "import\n"
            );
        }
        publish(&mut run);
        assert_eq!(run.observed.process().exit_code(), code);
    }
}

#[test]
fn actual_interruption_and_sigkill_preserve_raw_causes_partial_work_and_incomplete_reporting() {
    for (id, body) in [
        (
            "joined-keyboard",
            "raise KeyboardInterrupt('PT_JOINED_INTERRUPT')",
        ),
        ("joined-killed", "os.kill(os.getpid(),signal.SIGKILL)"),
    ] {
        let source = format!(
            "import os,signal\nfrom pathlib import Path\ndef test_actual():\n    with Path('started-once').open('x') as output: output.write('effect')\n    {body}\n"
        );
        let run = invoke(id, &source, None, &["test_actual.py"], RequestMode::Run);
        let snapshot = run.observed.snapshot().unwrap();
        assert_eq!(snapshot.accounting.executed_count, 1);
        assert_eq!(snapshot.accounting.completed_count, 0);
        assert_eq!(snapshot.incomplete_ordinals, vec![0]);
        assert!(!run.store.required_artifacts_satisfied());
        assert!(
            JunitExpectation::from_snapshot(run.policy.clone(), snapshot, run.deadline).is_err()
        );
        assert_eq!(
            fs::read_to_string(run.work.join("started-once")).unwrap(),
            "effect"
        );
        if id == "joined-keyboard" {
            assert_eq!(
                run.observed.outcome(),
                &SessionOutcome::NormalExitAccounted {
                    backend_exit_code: 2
                }
            );
        } else {
            assert_eq!(run.observed.outcome(), &SessionOutcome::BackendTerminated);
            assert_eq!(
                run.observed.process().leader_status,
                Some(LeaderStatus::Signaled {
                    signal: 9,
                    core_dumped: false
                })
            );
            assert!(snapshot.terminal.is_none());
        }
    }
}

#[test]
fn outer_unconfigure_is_not_killed_or_suppressed_just_to_obtain_reporting_complete() {
    let source = "def test_actual():\n    pass\n";
    let conftest = "import pytest,time\nfrom pathlib import Path\n@pytest.hookimpl(wrapper=True,tryfirst=True)\ndef pytest_unconfigure(config):\n    result=yield\n    time.sleep(0.1)\n    Path('outer-finished').write_text('cleanup retained')\n    return result\n";
    let run = invoke(
        "joined-outer-finalizer",
        source,
        Some(conftest),
        &["test_actual.py"],
        RequestMode::Run,
    );
    assert_eq!(run.observed.process().exit_code(), 0);
    assert_eq!(
        run.observed.outcome(),
        &SessionOutcome::InfrastructureFailed
    );
    assert!(run.observed.normal_snapshot().is_none());
    assert_eq!(
        fs::read_to_string(run.work.join("outer-finished")).unwrap(),
        "cleanup retained"
    );
    assert!(
        !run.observed
            .snapshot()
            .unwrap()
            .terminal
            .as_ref()
            .unwrap()
            .reporting_complete
    );
}
