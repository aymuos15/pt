#![cfg(all(target_os = "linux", target_env = "gnu", target_arch = "x86_64"))]
//! Real native framing/ledger + stdlib XML/hash controls. The direct env wrapper
//! and frozen fixture copies are explicit correctness-only test setup, not the
//! shipping coordinator, supported launcher or a product-timing arm.
use pt_process::{
    Cleanup, ProcessReport, ProcessRequest, control_channel_pair, supervise, supervise_with_control,
};
use pt_protocol::{
    BridgeSnapshot, ChannelIdentity, FrameReader, InvocationProfile, RequestMode, SerialContract,
    SerialLedger, StreamBudget,
};
use pt_report::{
    ArtifactDeclaration, ArtifactState, ArtifactStore, JunitExpectation, JunitLimits, JunitPolicy,
    RetentionBudget, WritersStopped,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
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
fn limits() -> JunitLimits {
    JunitLimits {
        bytes: 4 * 1024 * 1024,
        testcases: 256,
        events: 25000,
    }
}
fn policy() -> JunitPolicy {
    JunitPolicy::xunit2("pytest".into(), None, limits()).unwrap()
}
fn private_dir(path: &Path) {
    fs::create_dir(path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|value| format!("{value:02x}")).collect()
}

struct CaseRoot {
    _temporary: Option<tempfile::TempDir>,
    path: PathBuf,
}
impl CaseRoot {
    fn new(id: &str) -> Self {
        if let Some(parent) = std::env::var_os("PT_JUNIT_CASE_ROOT") {
            let path = PathBuf::from(parent).join(id);
            private_dir(&path);
            Self {
                _temporary: None,
                path,
            }
        } else {
            let temporary = tempfile::Builder::new()
                .prefix("pt-junit-native-")
                .tempdir_in("/tmp/opencode")
                .unwrap();
            let path = temporary.path().to_path_buf();
            Self {
                _temporary: Some(temporary),
                path,
            }
        }
    }
}

struct Observation {
    _root: CaseRoot,
    work: PathBuf,
    retained: PathBuf,
    process: ProcessReport,
    snapshot: BridgeSnapshot,
    oracle: Value,
    store: ArtifactStore,
    deadline: Instant,
}

#[allow(clippy::too_many_arguments)] // All subject/request fields remain explicit in these test arms.
fn invoke(
    id: &str,
    case: &str,
    args: &[&str],
    extra: &[(&str, &str)],
    mode: RequestMode,
    profile: InvocationProfile,
    policy: JunitPolicy,
    code: u8,
) -> Observation {
    let owned = CaseRoot::new(id);
    let work = owned.path.join("work");
    let retained = owned.path.join("retained");
    private_dir(&work);
    private_dir(&retained);
    let corpus = root().join("bench/corpus/serial_core");
    let declaration: Value =
        serde_json::from_slice(&fs::read(corpus.join("corpus.json")).unwrap()).unwrap();
    let prefix = format!("fixtures/{case}/");
    let mut frozen = Vec::new();
    for file in declaration["files"].as_array().unwrap() {
        let source = file["path"].as_str().unwrap();
        if let Some(name) = source.strip_prefix(&prefix) {
            let raw = fs::read(corpus.join(source)).unwrap();
            assert_eq!(hex(&Sha256::digest(&raw)), file["sha256"].as_str().unwrap());
            fs::write(work.join(name), &raw).unwrap();
            frozen.push((name.to_owned(), raw));
        }
    }
    assert!(!frozen.is_empty());
    fs::copy(corpus.join("pyproject.toml"), work.join("pyproject.toml")).unwrap();
    for (name, source) in extra {
        fs::write(work.join(name), source).unwrap();
    }
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(work.join("requested.xml"))
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(45);
    let store = ArtifactStore::create(
        &work,
        &retained,
        "private",
        vec![ArtifactDeclaration {
            artifact_id: "junit".into(),
            source: "requested.xml".into(),
            required: true,
            expected_content: None,
            junit_policy: Some(policy),
        }],
        RetentionBudget {
            files: 1,
            bytes: 4 * 1024 * 1024,
            per_file_bytes: 4 * 1024 * 1024,
            deadline,
        },
    )
    .unwrap();
    assert!(store.required_artifacts_checkable());
    let identity = ChannelIdentity {
        request_id: id.into(),
        run_id: "junit-run".into(),
        generation_id: "junit-test-generation".into(),
        session_id: "junit-session".into(),
        producer_id: "junit-observer".into(),
    };
    let (parent, control) = control_channel_pair().unwrap();
    let reader_identity = identity.clone();
    let reader = thread::spawn(move || {
        let mut reader = FrameReader::new(
            parent,
            reader_identity.clone(),
            StreamBudget {
                bytes: 8 * 1024 * 1024,
                events: 25000,
            },
        )
        .unwrap();
        let mut ledger = SerialLedger::new(
            reader_identity,
            SerialContract {
                invocation_profile: profile,
                mode,
                max_items: 256,
                max_collection_reports: 1024,
                max_nodeid_bytes: 1024 * 1024,
                declared_artifact_ids: vec!["junit".into()],
            },
        )
        .unwrap();
        let mut wire = Vec::new();
        while let Some(message) = reader.receive(deadline).unwrap() {
            wire.extend_from_slice(&(message.raw_json().len() as u32).to_be_bytes());
            wire.extend_from_slice(message.raw_json());
            ledger.apply(&message).unwrap();
        }
        (ledger, reader.end_evidence().unwrap(), wire)
    });
    let configuration = json!({"schema_version":1,"fd":3,"identity":{"request_id":identity.request_id,"run_id":identity.run_id,"generation_id":identity.generation_id,"session_id":identity.session_id,"producer_id":identity.producer_id},
        "invocation_profile":if profile==InvocationProfile::PytestModule {"pytest_module"}else{"pytest_console"},"mode":if mode==RequestMode::CollectOnly {"collect_only"}else{"run"},
        "max_items":256,"max_collection_reports":1024,"max_nodeid_bytes":1024*1024,"byte_budget":8*1024*1024,"event_budget":25000,"timeout_seconds":30});
    let mut argv = vec![
        format!("PT_BRIDGE_CONTROL={configuration}").into(),
        format!("PT_CORE_EVENTS={}", work.join("events.txt").display()).into(),
        format!(
            "PYTHONPATH={}:{}",
            work.display(),
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
    argv.extend([
        "-q".into(),
        "-p".into(),
        "pt_bridge.pytest_observer".into(),
        "--junitxml=requested.xml".into(),
    ]);
    argv.extend(args.iter().map(std::ffi::OsString::from));
    fs::write(owned.path.join("invocation.json"),serde_json::to_vec_pretty(&json!({"argv":argv.iter().map(|value|value.to_string_lossy().into_owned()).collect::<Vec<_>>(),"qualified":false})).unwrap()).unwrap();
    let request = ProcessRequest {
        executable: "/usr/bin/env".into(),
        args: argv,
        cwd: work.clone(),
        timeout: Duration::from_secs(30),
        cleanup_timeout: Duration::from_secs(1),
    };
    let process = supervise_with_control(&request, &AtomicI32::new(0), control).unwrap();
    fs::write(
        owned.path.join("pytest.process.json"),
        serde_json::to_vec_pretty(&process).unwrap(),
    )
    .unwrap();
    let (ledger, end, wire) = reader.join().unwrap();
    fs::write(owned.path.join("observer.wire"), wire).unwrap();
    assert_eq!(process.exit_code(), code, "{id}: {process:?}");
    assert_eq!(process.cleanup, Cleanup::Complete);
    let snapshot = ledger.validate_normal_exit(&end, code).unwrap();
    for (name, raw) in frozen {
        assert_eq!(fs::read(work.join(name)).unwrap(), raw);
    }
    let oracle_path = owned.path.join("independent-junit.json");
    let oracle_request = ProcessRequest {
        executable: python().into_os_string(),
        args: vec![
            "-I".into(),
            "-S".into(),
            "-B".into(),
            root()
                .join("crates/pt-report/tests/junit_reference.py")
                .into_os_string(),
            work.join("requested.xml").into_os_string(),
            oracle_path.clone().into_os_string(),
        ],
        cwd: work.clone(),
        timeout: Duration::from_secs(5),
        cleanup_timeout: Duration::from_secs(1),
    };
    let oracle_process = supervise(&oracle_request, &AtomicI32::new(0)).unwrap();
    fs::write(
        owned.path.join("oracle.process.json"),
        serde_json::to_vec_pretty(&oracle_process).unwrap(),
    )
    .unwrap();
    assert_eq!(oracle_process.exit_code(), 0);
    assert_eq!(oracle_process.cleanup, Cleanup::Complete);
    let oracle = serde_json::from_slice(&fs::read(oracle_path).unwrap()).unwrap();
    Observation {
        _root: owned,
        work,
        retained,
        process,
        snapshot,
        oracle,
        store,
        deadline,
    }
}

fn claim(oracle: &Value) -> pt_protocol::ArtifactReady {
    pt_protocol::ArtifactReady {
        artifact_id: "junit".into(),
        sha256: oracle["sha256"].as_str().unwrap().into(),
        bytes: oracle["bytes"].as_u64().unwrap(),
        complete: true,
    }
}
fn complete(mut observed: Observation, policy: JunitPolicy) -> Observation {
    let expectation =
        JunitExpectation::from_snapshot(policy, &observed.snapshot, observed.deadline).unwrap();
    assert_eq!(
        expectation.expected_testcases(),
        observed.oracle["rows"].as_array().unwrap().len()
    );
    let artifact = observed
        .store
        .commit_with_junit(
            &claim(&observed.oracle),
            &WritersStopped::after_cleanup(&observed.process).unwrap(),
            &expectation,
        )
        .unwrap();
    assert!(artifact.complete());
    assert!(observed.store.required_artifacts_satisfied());
    assert_eq!(
        artifact.sha256(),
        observed.oracle["sha256"].as_str().unwrap()
    );
    assert_eq!(
        fs::read(observed.work.join("requested.xml")).unwrap(),
        fs::read(observed.retained.join("private/artifact-junit")).unwrap()
    );
    observed
}

#[test]
fn all_ten_core_fixtures_have_actual_ledger_derived_complete_junit_including_duplicate_occurrences()
{
    let corpus = root().join("bench/corpus/serial_core");
    let declaration: Value =
        serde_json::from_slice(&fs::read(corpus.join("corpus.json")).unwrap()).unwrap();
    for case in declaration["cases"].as_array().unwrap() {
        let id = case["id"].as_str().unwrap();
        let args = case["argv"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap())
            .collect::<Vec<_>>();
        let observed = complete(
            invoke(
                &format!("core-{id}"),
                id,
                &args,
                &[],
                RequestMode::Run,
                InvocationProfile::PytestModule,
                policy(),
                case["expected_exit_code"].as_u64().unwrap() as u8,
            ),
            policy(),
        );
        let rows = observed.oracle["rows"].as_array().unwrap();
        let expected = case["junit"].as_array().unwrap();
        assert_eq!(rows.len(), expected.len());
        for (row, expected) in rows.iter().zip(expected) {
            assert_eq!(row["name"], expected["name"]);
            let adverse = row["adverse"].as_array().unwrap();
            if expected["kind"] == "passed" {
                assert!(adverse.is_empty());
            } else {
                assert_eq!(adverse.len(), 1);
                assert_eq!(adverse[0]["kind"], expected["kind"]);
            }
        }
        if !case["expected_events"].is_null() {
            let actual = fs::read_to_string(observed.work.join("events.txt")).unwrap();
            assert_eq!(
                actual.lines().collect::<Vec<_>>(),
                case["expected_events"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|value| value.as_str().unwrap())
                    .collect::<Vec<_>>()
            );
        }
    }
}

#[test]
fn collect_only_fail_fast_selection_collection_skip_and_continue_errors_keep_actual_scope() {
    for (id, case, args, mode, code) in [
        (
            "mode-collect",
            "basic",
            vec!["--collect-only", "."],
            RequestMode::CollectOnly,
            0,
        ),
        (
            "mode-failfast",
            "phases",
            vec!["-x", "."],
            RequestMode::Run,
            1,
        ),
        (
            "mode-selected",
            "basic",
            vec!["-k", "first", "."],
            RequestMode::Run,
            0,
        ),
        (
            "mode-deselected",
            "basic",
            vec!["-k", "not_present", "."],
            RequestMode::Run,
            5,
        ),
    ] {
        complete(
            invoke(
                id,
                case,
                &args,
                &[],
                mode,
                InvocationProfile::PytestModule,
                policy(),
                code,
            ),
            policy(),
        );
    }
    let skip = "import pytest\npytest.skip('PT_COLLECT_SKIP',allow_module_level=True)\n";
    let observed = complete(
        invoke(
            "collection-skip",
            "basic",
            &["test_skip.py"],
            &[("test_skip.py", skip)],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            policy(),
            5,
        ),
        policy(),
    );
    assert_eq!(observed.oracle["suite"]["skipped"], "1");
    complete(
        invoke(
            "continue-collection-errors",
            "collection_error",
            &["--continue-on-collection-errors", "."],
            &[("test_also.py", "def test_also():\n    pass\n")],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            policy(),
            1,
        ),
        policy(),
    );
}

#[test]
fn actual_passing_call_error_and_double_failure_counters_are_not_inferred_from_row_count() {
    let source = "import pytest\n@pytest.fixture\ndef errors():\n    yield\n    raise RuntimeError('PT_TEARDOWN')\ndef test_pass_error(errors):\n    pass\ndef test_double(errors):\n    assert False,'PT_CALL'\n";
    let observed = complete(
        invoke(
            "double-failure-counters",
            "basic",
            &["test_double.py"],
            &[("test_double.py", source)],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            policy(),
            1,
        ),
        policy(),
    );
    assert_eq!(observed.snapshot.accounting.completed_count, 2);
    assert_eq!(observed.oracle["rows"].as_array().unwrap().len(), 3);
    assert_eq!(observed.oracle["suite"]["tests"], "3");
    assert_eq!(observed.oracle["suite"]["failures"], "1");
    assert_eq!(observed.oracle["suite"]["errors"], "2");
}

#[test]
fn explicit_prefix_suite_unicode_entities_and_console_entrypoint_match_the_pinned_mapping() {
    let custom =
        JunitPolicy::xunit2("suite & λ".into(), Some("prefix.p".into()), limits()).unwrap();
    let source = r#"import pytest
@pytest.mark.parametrize('value',[0],ids=['λ/a::b'])
def test_unicode(value):
    assert False,'PT_REASON < & " \n \t \x01'
"#;
    let observed = complete(
        invoke(
            "console-prefix-suite",
            "basic",
            &[
                "--junit-prefix",
                "prefix.p",
                "-o",
                "junit_suite_name=suite & λ",
                "-o",
                "disable_test_id_escaping_and_forfeit_all_rights_to_community_support=True",
                "test_unicode.py",
            ],
            &[("test_unicode.py", source)],
            RequestMode::Run,
            InvocationProfile::PytestConsole,
            custom.clone(),
            1,
        ),
        custom,
    );
    assert_eq!(observed.oracle["suite"]["name"], "suite & λ");
    assert_eq!(
        observed.oracle["rows"][0]["classname"],
        "prefix.p.test_unicode"
    );
    assert_eq!(observed.oracle["rows"][0]["name"], "test_unicode[λ/a::b]");
}

#[test]
fn real_property_capture_and_legacy_extensions_are_rejected_without_changing_pytest() {
    for (id, args, source) in [
        (
            "unsupported-properties",
            vec!["test_extra.py"],
            "def test_extra(record_property):\n    record_property('PT_PROPERTY','retained')\n",
        ),
        (
            "unsupported-capture",
            vec!["-o", "junit_logging=all", "test_extra.py"],
            "def test_extra():\n    print('PT_CAPTURE')\n",
        ),
        (
            "unsupported-legacy",
            vec!["-o", "junit_family=xunit1", "test_extra.py"],
            "def test_extra():\n    pass\n",
        ),
        (
            "unsupported-suite-properties",
            vec!["test_extra.py"],
            "def test_extra(record_testsuite_property):\n    record_testsuite_property('PT_SUITE','retained')\n",
        ),
    ] {
        let mut observed = invoke(
            id,
            "basic",
            &args,
            &[("test_extra.py", source)],
            RequestMode::Run,
            InvocationProfile::PytestModule,
            policy(),
            0,
        );
        let expectation =
            JunitExpectation::from_snapshot(policy(), &observed.snapshot, observed.deadline)
                .unwrap();
        assert!(
            observed
                .store
                .commit_with_junit(
                    &claim(&observed.oracle),
                    &WritersStopped::after_cleanup(&observed.process).unwrap(),
                    &expectation
                )
                .is_err()
        );
        assert!(!observed.store.required_artifacts_satisfied());
        assert!(matches!(
            observed.store.state("junit"),
            Some(ArtifactState::Failed {
                publication_may_exist: false,
                ..
            })
        ));
        assert!(!observed.retained.join("private/artifact-junit").exists());
        assert_eq!(observed.process.exit_code(), 0);
    }
}

#[test]
fn real_interrupt_unnamed_junit_remains_unknown_and_cannot_supply_completeness_context() {
    let mut observed = invoke(
        "interrupted-unnamed",
        "basic",
        &["test_interrupt.py"],
        &[(
            "test_interrupt.py",
            "def test_interrupt():\n    raise KeyboardInterrupt('PT_JUNIT_INTERRUPT')\n",
        )],
        RequestMode::Run,
        InvocationProfile::PytestModule,
        policy(),
        2,
    );
    assert_eq!(observed.oracle["rows"][0]["name"], Value::Null);
    assert_eq!(observed.oracle["suite"]["tests"], "0");
    assert!(
        JunitExpectation::from_snapshot(policy(), &observed.snapshot, observed.deadline).is_err()
    );
    let retained = observed
        .store
        .commit(
            &claim(&observed.oracle),
            &WritersStopped::after_cleanup(&observed.process).unwrap(),
        )
        .unwrap();
    assert!(!retained.complete());
    assert!(!observed.store.required_artifacts_satisfied());
    assert_eq!(observed.process.exit_code(), 2);
}
