#![cfg(target_os = "linux")]

use pt_process::{
    CONTROL_FD, Cleanup, LeaderStatus, ProcessRequest, Termination, control_channel_pair,
    supervise, supervise_with_control, supervise_with_control_checked,
};
use std::ffi::OsString;
use std::fs;
use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, Ordering};
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
fn observer_failure_is_not_a_user_signal_and_prevents_or_stops_the_single_owned_launch() {
    let root = TestDir::new();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let report = supervise_with_control_checked(
        &request(
            &root.0,
            "from pathlib import Path;Path('must-not-start').touch()",
        ),
        &AtomicI32::new(0),
        control,
        &AtomicBool::new(true),
    )
    .unwrap();
    assert!(matches!(
        report.termination,
        Termination::InfrastructureError { .. }
    ));
    assert_eq!(report.cleanup, Cleanup::NotLaunched);
    assert!(report.pid.is_none());
    assert_eq!(reader.join().unwrap().unwrap(), b"");
    assert!(!root.0.join("must-not-start").exists());
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let failed = AtomicBool::new(false);
    let report = thread::scope(|scope| {
        let root = &root.0;
        let flag = &failed;
        scope.spawn(move || {
            wait_for_file(&root.join("started-once"));
            flag.store(true, Ordering::SeqCst);
        });
        supervise_with_control_checked(&request(root,"import os,time\nfrom pathlib import Path\nos.set_inheritable(3,False)\nwith Path('started-once').open('x') as output: output.write('one effect')\ntime.sleep(30)"),&AtomicI32::new(0),control,&failed).unwrap()
    });
    assert!(matches!(
        report.termination,
        Termination::InfrastructureError { .. }
    ));
    assert_eq!(report.cleanup, Cleanup::Complete);
    assert_eq!(report.exit_code(), 3);
    assert_no_live_pid(report.pid.unwrap());
    assert_eq!(reader.join().unwrap().unwrap(), b"");
    assert_eq!(
        fs::read_to_string(root.0.join("started-once")).unwrap(),
        "one effect"
    );
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

fn read_private_channel(stream: UnixStream) -> thread::JoinHandle<io::Result<Vec<u8>>> {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    thread::spawn(move || {
        let mut raw = Vec::new();
        stream.take(1024 * 1024 + 1).read_to_end(&mut raw)?;
        if raw.len() > 1024 * 1024 {
            return Err(io::Error::other(
                "native test control stream exceeded its bound",
            ));
        }
        Ok(raw)
    })
}

#[test]
fn explicit_control_handoff_preserves_binary_bytes_on_a_connected_private_socket() {
    let root = TestDir::new();
    assert_eq!(CONTROL_FD, 3);
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let invocation = request(
        &root.0,
        r#"
import os
assert os.get_inheritable(3)
os.set_inheritable(3,False)
import socket
stream=socket.socket(fileno=3)
assert stream.family == socket.AF_UNIX
assert stream.type == socket.SOCK_STREAM
assert not os.get_inheritable(3)
stream.sendall(b'private control\x00\xff\n')
stream.close()
"#,
    );
    let result = supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap();
    let raw = reader.join().unwrap().unwrap();
    assert_eq!(result.exit_code(), 0, "{result:?}");
    assert_eq!(result.cleanup, Cleanup::Complete);
    assert_eq!(raw, b"private control\x00\xff\n");
}

#[test]
fn parent_copy_is_closed_after_spawn_so_control_eof_can_precede_leader_exit() {
    let root = TestDir::new();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let invocation = request(
        &root.0,
        r#"
import os
os.set_inheritable(3,False)
import socket,time
from pathlib import Path
stream=socket.socket(fileno=3)
stream.sendall(b'finished control before process exit')
stream.close()
Path('control-closed').touch()
while not Path('allow-exit').exists():
    time.sleep(.005)
"#,
    );
    let worker = thread::spawn(move || {
        supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap()
    });
    let read_result = reader.join();
    let already_exited = worker.is_finished();
    // Release the child even when a broken handoff caused a read error. Assert
    // only after joining the supervised execution and its bounded cleanup.
    fs::write(root.0.join("allow-exit"), b"").unwrap();
    let result = worker.join().unwrap();
    assert_eq!(result.exit_code(), 0, "{result:?}");
    assert!(
        !already_exited,
        "control EOF was delayed until process completion"
    );
    assert_eq!(
        read_result.unwrap().unwrap(),
        b"finished control before process exit"
    );
    assert!(root.0.join("control-closed").exists());
}

#[test]
fn child_noninheritability_prevents_the_control_capability_reaching_a_normal_exec_descendant() {
    let root = TestDir::new();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let invocation = request(
        &root.0,
        r#"
import os
os.set_inheritable(3,False)
import errno,socket,subprocess,sys
stream=socket.socket(fileno=3)
code='import errno,os\ntry: os.fstat(3)\nexcept OSError as error: assert error.errno == errno.EBADF\nelse: raise RuntimeError("control leaked across exec")'
subprocess.run([sys.executable,'-c',code],close_fds=False,check=True,timeout=3)
stream.sendall(b'normal exec child did not inherit control')
stream.close()
"#,
    );
    let result = supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap();
    let raw = reader.join().unwrap().unwrap();
    assert_eq!(result.exit_code(), 0, "{result:?}");
    assert_eq!(raw, b"normal exec child did not inherit control");
}

#[test]
fn parent_socket_flags_do_not_leak_private_channels_into_an_unrelated_concurrent_launch() {
    let root = TestDir::new();
    let (parent, control) = control_channel_pair().unwrap();
    let parent_target = fs::read_link(format!("/proc/self/fd/{}", parent.as_raw_fd())).unwrap();
    let flags_before =
        fs::read_to_string(format!("/proc/self/fdinfo/{}", parent.as_raw_fd())).unwrap();
    let reader = read_private_channel(parent);
    let invocation = request(
        &root.0,
        r#"
import os
os.set_inheritable(3,False)
import socket,time
from pathlib import Path
stream=socket.socket(fileno=3)
Path('control-target').write_text(os.readlink('/proc/self/fd/3'))
Path('ready').touch()
while not Path('allow-exit').exists(): time.sleep(.005)
stream.sendall(b'private')
stream.close()
"#,
    );
    let worker = thread::spawn(move || {
        supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap()
    });
    wait_for_file(&root.0.join("ready"));
    let ordinary = run(&request(
        &root.0,
        r#"
import os
from pathlib import Path
targets=[]
for name in os.listdir('/proc/self/fd'):
    try: targets.append(os.readlink('/proc/self/fd/'+name))
    except FileNotFoundError: pass
Path('ordinary-targets').write_text('\n'.join(targets))
"#,
    ));
    fs::write(root.0.join("allow-exit"), b"").unwrap();
    let first = worker.join().unwrap();
    let raw = reader.join().unwrap().unwrap();
    assert_eq!(ordinary.exit_code(), 0, "{ordinary:?}");
    assert_eq!(first.exit_code(), 0, "{first:?}");
    assert_eq!(raw, b"private");
    let targets = fs::read_to_string(root.0.join("ordinary-targets")).unwrap();
    let child_target = fs::read_to_string(root.0.join("control-target")).unwrap();
    assert!(!targets.lines().any(|target| target == child_target));
    assert!(
        !targets
            .lines()
            .any(|target| Path::new(target) == parent_target)
    );
    let flags = flags_before
        .lines()
        .find_map(|line| line.strip_prefix("flags:\t"))
        .unwrap();
    assert_ne!(u32::from_str_radix(flags, 8).unwrap() & 0o2000000, 0);
}

#[test]
fn invalid_cancelled_and_failed_launches_close_the_unused_control_capability() {
    let root = TestDir::new();
    for mode in ["invalid", "cancelled", "missing"] {
        let (parent, control) = control_channel_pair().unwrap();
        let reader = read_private_channel(parent);
        let mut invocation = request(&root.0, "open('must-not-run','w').close()");
        let cancel = AtomicI32::new(if mode == "cancelled" { 2 } else { 0 });
        if mode == "invalid" {
            invocation.timeout = Duration::ZERO;
        } else if mode == "missing" {
            invocation.executable = root.0.join("does-not-exist").into_os_string();
        }
        let result = supervise_with_control(&invocation, &cancel, control);
        let raw = reader.join().unwrap().unwrap();
        assert!(raw.is_empty());
        if mode == "invalid" {
            assert!(result.is_err());
        } else {
            let report = result.unwrap();
            assert_eq!(report.pid, None);
            assert_eq!(report.cleanup, Cleanup::NotLaunched);
            assert_ne!(report.exit_code(), 0);
        }
        assert!(!root.0.join("must-not-run").exists());
    }
}

#[test]
fn timeout_with_an_open_control_socket_retains_partial_bytes_and_reaps_the_execution() {
    let root = TestDir::new();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let mut invocation = request(
        &root.0,
        r#"
import os
os.set_inheritable(3,False)
import socket,time
stream=socket.socket(fileno=3)
stream.sendall(b'partial control before timeout')
time.sleep(30)
"#,
    );
    invocation.timeout = Duration::from_millis(750);
    let report = supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap();
    let raw = reader.join().unwrap().unwrap();
    assert_eq!(report.termination, Termination::Timeout);
    assert_eq!(report.exit_code(), 3);
    assert_eq!(report.cleanup, Cleanup::Complete);
    assert_eq!(raw, b"partial control before timeout");
    assert!(!Path::new(&format!("/proc/{}", report.pid.unwrap())).exists());
}

#[test]
fn source_bridge_framing_component_uses_the_actual_supervised_private_capability() {
    let root = TestDir::new();
    fs::write(
        root.0.join("test_owned_sentinel.py"),
        "import os\nfrom pathlib import Path\nassert not os.get_inheritable(3)\nPath('project-import-observed-closed-inheritance').touch()\n",
    )
    .unwrap();
    let bridge_source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../python/pt_bridge/src")
        .canonicalize()
        .unwrap();
    let (parent, control) = control_channel_pair().unwrap();
    let reader = read_private_channel(parent);
    let mut invocation = request(
        &root.0,
        r#"
import sys,time
sys.path.insert(0,sys.argv[1])
from pt_bridge._wire import ControlStream
identity={'request_id':'request-1','run_id':'run-1','generation_id':'generation-1','session_id':'session-1','producer_id':'bridge-1'}
with ControlStream.take_fd(3,identity,byte_budget=4096,event_budget=1) as stream:
    import test_owned_sentinel
    assert 'pytest' not in sys.modules
    stream.send('warning',{'ordinal':None,'category':'builtins.UserWarning','message':'PT_NATIVE_CONTROL_WARNING','filename':'test_owned_sentinel.py','line':1,'when':'configure'},deadline=time.monotonic()+2)
"#,
    );
    invocation.args.push(bridge_source.into_os_string());
    let report = supervise_with_control(&invocation, &AtomicI32::new(0), control).unwrap();
    let raw = reader.join().unwrap().unwrap();
    assert_eq!(report.exit_code(), 0, "{report:?}");
    assert_eq!(report.cleanup, Cleanup::Complete);
    assert!(matches!(
        report.scope,
        pt_process::ProcessScope::ProcessOnly
    ));
    assert!(raw.len() > 4);
    let size = u32::from_be_bytes(raw[..4].try_into().unwrap()) as usize;
    assert_eq!(size + 4, raw.len());
    let event: serde_json::Value = serde_json::from_slice(&raw[4..]).unwrap();
    assert_eq!(event["protocol_version"], 0);
    assert_eq!(event["contract_revision"], 1);
    assert_eq!(event["producer_role"], "bridge");
    assert_eq!(event["sequence"], 0);
    assert_eq!(event["kind"], "warning");
    assert_eq!(event["request_id"], "request-1");
    assert_eq!(event["payload"]["message"], "PT_NATIVE_CONTROL_WARNING");
    assert!(
        root.0
            .join("project-import-observed-closed-inheritance")
            .exists()
    );
}
