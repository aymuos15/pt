#![cfg(all(target_os = "linux", target_env = "gnu", target_arch = "x86_64"))]

use pt_process::{Cleanup, ProcessRequest, supervise};
use pt_protocol::ArtifactReady;
use pt_report::{ArtifactDeclaration, ArtifactStore, RetentionBudget, WritersStopped};
use std::fs::{self, OpenOptions};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::PathBuf;
use std::sync::atomic::AtomicI32;
use std::time::{Duration, Instant};

#[test]
fn actual_pytest_junit_is_rehashed_against_independent_python_but_unknown_completeness_stays_blocked()
 {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let python = std::env::var_os("PT_OBSERVER_TEST_PYTHON")
        .or_else(|| std::env::var_os("PT_TEST_PYTHON"))
        .unwrap_or_else(|| root.join("bench/harness/.venv/bin/python").into_os_string());
    let temp = tempfile::Builder::new()
        .prefix("pt-actual-junit-artifact-")
        .tempdir_in("/tmp/opencode")
        .unwrap();
    let work = temp.path().join("work");
    let output = temp.path().join("output");
    fs::create_dir(&work).unwrap();
    fs::create_dir(&output).unwrap();
    for path in [&work, &output] {
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    // Explicit test-owned destination reservation, not a chmod/repair of a
    // user-produced report or a silent change to forwarded report arguments.
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(work.join("requested-junit.xml"))
        .unwrap();
    fs::write(work.join("test_actual_report.py"),"from pathlib import Path\nimport pytest\n@pytest.fixture(autouse=True)\ndef released():\n    yield\n    Path('released').write_text('actually finalized')\ndef test_failure():\n    assert False, 'PT_ACTUAL_JUNIT_FAILURE'\n").unwrap();
    let mut store = ArtifactStore::create(
        &work,
        &output,
        "private",
        vec![ArtifactDeclaration {
            artifact_id: "junit".into(),
            source: "requested-junit.xml".into(),
            required: true,
            expected_content: None,
        }],
        RetentionBudget {
            files: 1,
            bytes: 1024 * 1024,
            per_file_bytes: 1024 * 1024,
            deadline: Instant::now() + Duration::from_secs(45),
        },
    )
    .unwrap();
    assert!(!store.required_artifacts_checkable());
    let request = ProcessRequest {
        executable: python.clone(),
        args: vec![
            "-B".into(),
            "-m".into(),
            "pytest".into(),
            "-q".into(),
            "--junitxml=requested-junit.xml".into(),
            "test_actual_report.py".into(),
        ],
        cwd: work.clone(),
        timeout: Duration::from_secs(20),
        cleanup_timeout: Duration::from_secs(1),
    };
    let process = supervise(&request, &AtomicI32::new(0)).unwrap();
    assert_eq!(process.exit_code(), 1);
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert_eq!(
        fs::read_to_string(work.join("released")).unwrap(),
        "actually finalized"
    );
    let stopped = WritersStopped::after_cleanup(&process).unwrap();
    let probe = r#"import hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
raw=Path('requested-junit.xml').read_bytes()
tree=ET.fromstring(raw)
items=list(tree.iter('testcase'))
assert len(items)==1 and items[0].get('name')=='test_failure'
assert len(list(items[0].iter('failure')))==1 and b'PT_ACTUAL_JUNIT_FAILURE' in raw
with Path('independent-content.json').open('x') as output:
    json.dump({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},output)
"#;
    let probe_request = ProcessRequest {
        executable: python,
        args: vec![
            "-I".into(),
            "-S".into(),
            "-B".into(),
            "-c".into(),
            probe.into(),
        ],
        cwd: work.clone(),
        timeout: Duration::from_secs(5),
        cleanup_timeout: Duration::from_secs(1),
    };
    let observed = supervise(&probe_request, &AtomicI32::new(0)).unwrap();
    assert_eq!(observed.exit_code(), 0);
    assert_eq!(observed.cleanup, Cleanup::Complete);
    let expected: serde_json::Value =
        serde_json::from_slice(&fs::read(work.join("independent-content.json")).unwrap()).unwrap();
    let claim = ArtifactReady {
        artifact_id: "junit".into(),
        sha256: expected["sha256"].as_str().unwrap().into(),
        bytes: expected["bytes"].as_u64().unwrap(),
        complete: true,
    };
    let artifact = store.commit(&claim, &stopped).unwrap();
    assert_eq!(artifact.sha256(), claim.sha256);
    assert_eq!(artifact.bytes(), claim.bytes);
    assert_eq!(
        fs::read(work.join("requested-junit.xml")).unwrap(),
        fs::read(output.join("private/artifact-junit")).unwrap()
    );
    // This independent test parser is not a production format/completeness
    // adapter. Ready claims/content hashes cannot quietly close that gate.
    assert!(artifact.ready_complete_claim());
    assert!(!artifact.complete());
    assert!(!store.required_artifacts_satisfied());
    assert_eq!(process.exit_code(), 1); // Verified failure reporting is not passing work.
}
