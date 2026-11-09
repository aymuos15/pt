#![cfg(target_os = "linux")]

use pt_process::{Cleanup, LeaderStatus, ProcessRequest, Termination, supervise};
use std::ffi::OsString;
use std::fs;
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicI32, AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

static NEXT: AtomicU64 = AtomicU64::new(0);

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let base = std::env::var_os("PT_TEST_TMPDIR").unwrap_or_else(|| "/tmp/opencode".into());
        let path = PathBuf::from(base).join(format!(
            "pt-rust-process-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        // Only the exclusively created, test-owned directory is removed.
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn request(root: &Path, code: &str) -> ProcessRequest {
    ProcessRequest {
        executable: std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| "python3".into()),
        args: vec!["-c".into(), code.into()],
        cwd: root.to_owned(),
        timeout: Duration::from_secs(5),
        cleanup_timeout: Duration::from_secs(1),
    }
}

fn run(request: &ProcessRequest) -> pt_process::ProcessReport {
    supervise(request, &AtomicI32::new(0)).unwrap()
}

fn wait_for_file(path: &Path) {
    let deadline = Instant::now() + Duration::from_secs(4);
    while !path.exists() {
        assert!(
            Instant::now() < deadline,
            "child never became ready: {path:?}"
        );
        thread::sleep(Duration::from_millis(5));
    }
}

fn assert_no_live_pid(pid: u32) {
    if let Ok(text) = fs::read_to_string(format!("/proc/{pid}/stat")) {
        let fields: Vec<_> = text
            .rsplit_once(')')
            .unwrap()
            .1
            .split_whitespace()
            .collect();
        assert!(
            matches!(fields[0], "Z" | "X" | "x"),
            "process {pid} remains live: {text}"
        );
    }
}

#[test]
fn repeated_invocations_use_fresh_pids_and_python_state() {
    let root = TestDir::new();
    fs::write(root.0.join("stateful.py"), "value = 0\n").unwrap();
    let invocation = request(
        &root.0,
        "import stateful; assert stateful.value == 0; stateful.value += 1",
    );
    let first = run(&invocation);
    let second = run(&invocation);
    assert_eq!(first.exit_code(), 0);
    assert_eq!(second.exit_code(), 0);
    assert_ne!(first.pid, second.pid);
    assert_eq!(first.cleanup, Cleanup::Complete);
    assert_eq!(second.cleanup, Cleanup::Complete);
    // The owned direct children have been reaped, not merely signaled.
    assert!(!Path::new(&format!("/proc/{}", first.pid.unwrap())).exists());
    assert!(!Path::new(&format!("/proc/{}", second.pid.unwrap())).exists());
}

#[test]
fn cwd_and_empty_unicode_non_utf8_arguments_are_preserved() {
    let root = TestDir::new();
    let mut invocation = request(
        &root.0,
        "import os,sys; open('args','wb').write(b'|'.join(os.fsencode(a) for a in sys.argv[1:]))",
    );
    invocation.args.extend([
        OsString::from(""),
        OsString::from("two words"),
        OsString::from("λ"),
        OsString::from("--plugin-flag=literal;not a shell"),
        OsString::from_vec(vec![b'x', 0xff]),
    ]);
    let result = run(&invocation);
    assert_eq!(result.exit_code(), 0);
    assert_eq!(
        fs::read(root.0.join("args")).unwrap(),
        b"|two words|\xce\xbb|--plugin-flag=literal;not a shell|x\xff"
    );
}

#[test]
fn inherited_environment_is_not_replaced() {
    let root = TestDir::new();
    let mut invocation = request(
        &root.0,
        "import os,sys; assert os.environ['PATH'] == sys.argv[1]",
    );
    invocation.args.push(std::env::var_os("PATH").unwrap());
    assert_eq!(run(&invocation).exit_code(), 0);
}

#[test]
fn nonzero_and_signal_exits_remain_distinct() {
    let root = TestDir::new();
    let failed = run(&request(&root.0, "raise SystemExit(7)"));
    assert_eq!(failed.termination, Termination::ProcessExited);
    assert_eq!(failed.leader_status, Some(LeaderStatus::Exited { code: 7 }));
    assert_eq!(failed.exit_code(), 7);
    let killed = run(&request(
        &root.0,
        "import os,signal; os.kill(os.getpid(),signal.SIGKILL)",
    ));
    assert_eq!(killed.termination, Termination::BackendTerminated);
    assert_eq!(
        killed.leader_status,
        Some(LeaderStatus::Signaled {
            signal: 9,
            core_dumped: false
        })
    );
    assert_eq!(killed.exit_code(), 137);
}

#[test]
fn failed_launch_is_retained_and_not_replayed() {
    let root = TestDir::new();
    let mut invocation = request(&root.0, "pass");
    invocation.executable = root.0.join("does-not-exist").into_os_string();
    let result = run(&invocation);
    assert!(matches!(
        result.termination,
        Termination::LaunchError { .. }
    ));
    assert_eq!(result.cleanup, Cleanup::NotLaunched);
    assert_eq!(result.pid, None);
    assert_eq!(result.exit_code(), 3);
}

#[test]
fn invalid_request_and_prelaunch_cancellation_do_not_start_project_work() {
    let root = TestDir::new();
    let mut invocation = request(&root.0, "open('must-not-run','w').close()");
    invocation.timeout = Duration::ZERO;
    assert!(supervise(&invocation, &AtomicI32::new(0)).is_err());
    invocation.timeout = Duration::from_secs(5);
    let result = supervise(&invocation, &AtomicI32::new(2)).unwrap();
    assert_eq!(result.termination, Termination::Interrupted { signal: 2 });
    assert_eq!(result.cleanup, Cleanup::NotLaunched);
    assert_eq!(result.pid, None);
    assert_eq!(result.exit_code(), 2);
    assert!(!root.0.join("must-not-run").exists());
    invocation.args.push(OsString::from_vec(vec![b'x', 0]));
    assert!(supervise(&invocation, &AtomicI32::new(0)).is_err());
}

#[test]
fn terminal_stdin_is_rejected_before_launch() {
    if std::env::var_os("PT_TEST_STDIN_FIXTURE").is_some() {
        let root = TestDir::new();
        let invocation = request(&root.0, "open('must-not-run','w').close()");
        let error = supervise(&invocation, &AtomicI32::new(0)).unwrap_err();
        assert!(error.0.contains("interactive stdin"));
        assert!(!root.0.join("must-not-run").exists());
        return;
    }
    // Run this exact validation fixture under a real PTY input descriptor,
    // without changing the parent test process's stdin or signal handling.
    let result = std::process::Command::new(
        std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| "python3".into()),
    )
    .args(["-c", r#"
import os,pty,subprocess,sys
master,slave=pty.openpty()
try:
    result=subprocess.run([sys.argv[1],'--exact','terminal_stdin_is_rejected_before_launch','--nocapture'],
                          stdin=slave,capture_output=True,timeout=10)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)
finally:
    os.close(master)
    os.close(slave)
"#])
    .arg(std::env::current_exe().unwrap())
    .env("PT_TEST_STDIN_FIXTURE", "1")
    .output().unwrap();
    assert!(result.status.success(), "{:?}", result);
}

const TREE: &str = r#"
import os, sys, subprocess, time
from pathlib import Path
child_code = "import os,time; from pathlib import Path; Path('descendant.tmp').write_text(str(os.getpid())); Path('descendant.tmp').replace('descendant'); time.sleep(30)"
subprocess.Popen([sys.executable, '-c', child_code])
while not Path('descendant').exists():
    time.sleep(.005)
if sys.argv[1] == 'exit':
    raise SystemExit(0)
while True:
    time.sleep(1)
"#;

#[test]
fn ordinary_descendant_is_stopped_even_after_successful_leader_exit() {
    let root = TestDir::new();
    let mut invocation = request(&root.0, TREE);
    invocation.args.push("exit".into());
    let result = run(&invocation);
    assert_eq!(result.termination, Termination::ProcessExited);
    assert_eq!(result.exit_code(), 0, "{result:?}");
    assert_eq!(result.cleanup, Cleanup::Complete);
    let pid = fs::read_to_string(root.0.join("descendant"))
        .unwrap()
        .parse()
        .unwrap();
    assert_no_live_pid(pid);
}

#[test]
fn hard_timeout_stops_ordinary_process_group_and_reaps_leader() {
    let root = TestDir::new();
    let mut invocation = request(&root.0, TREE);
    invocation.args.push("hang".into());
    invocation.timeout = Duration::from_millis(750);
    let result = run(&invocation);
    assert_eq!(result.termination, Termination::Timeout);
    assert_eq!(result.exit_code(), 3);
    assert_eq!(result.cleanup, Cleanup::Complete, "{result:?}");
    assert!(result.cleanup_signals.contains(&9));
    assert!(result.elapsed_ns < 3_000_000_000);
    let pid = fs::read_to_string(root.0.join("descendant"))
        .unwrap()
        .parse()
        .unwrap();
    assert_no_live_pid(pid);
    assert!(!Path::new(&format!("/proc/{}", result.pid.unwrap())).exists());
}

#[test]
fn cancellation_remains_interrupted_if_child_handles_term_and_exits_zero() {
    let root = TestDir::new();
    let invocation = request(
        &root.0,
        r#"
import signal,sys,time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
Path('ready').touch()
time.sleep(30)
"#,
    );
    let cancelled = Arc::new(AtomicI32::new(0));
    let flag = cancelled.clone();
    let ready = root.0.join("ready");
    let canceller = thread::spawn(move || {
        wait_for_file(&ready);
        flag.store(15, Ordering::SeqCst);
    });
    let result = supervise(&invocation, &cancelled).unwrap();
    canceller.join().unwrap();
    assert_eq!(result.termination, Termination::Interrupted { signal: 15 });
    assert_eq!(result.leader_status, Some(LeaderStatus::Exited { code: 0 }));
    assert_eq!(result.cleanup, Cleanup::Complete);
    assert_eq!(result.exit_code(), 2);
}

#[test]
fn cancellation_escalates_for_term_ignoring_child() {
    let root = TestDir::new();
    let invocation = request(
        &root.0,
        r#"
import signal,time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path('ready').touch()
time.sleep(30)
"#,
    );
    let cancelled = Arc::new(AtomicI32::new(0));
    let flag = cancelled.clone();
    let ready = root.0.join("ready");
    let canceller = thread::spawn(move || {
        wait_for_file(&ready);
        flag.store(2, Ordering::SeqCst);
    });
    let result = supervise(&invocation, &cancelled).unwrap();
    canceller.join().unwrap();
    assert_eq!(result.termination, Termination::Interrupted { signal: 2 });
    assert_eq!(result.cleanup, Cleanup::Complete);
    assert!(result.cleanup_signals.ends_with(&[15, 9]));
    assert_eq!(result.exit_code(), 2);
}
