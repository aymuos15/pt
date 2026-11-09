#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use nix::sys::signal::{Signal, kill};
use nix::unistd::Pid;
use serde_json::Value;
use std::fs;
use std::io::Write;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

static NEXT: AtomicU64 = AtomicU64::new(0);

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let base = std::env::var_os("PT_TEST_TMPDIR").unwrap_or_else(|| "/tmp/opencode".into());
        let path = PathBuf::from(base).join(format!(
            "pt-rust-cli-{}-{}-{}",
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

    fn command(&self, code: &str) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_pt"));
        command
            .current_dir(&self.0)
            .args(["exec", "--timeout-seconds", "3", "--report"])
            .arg(self.0.join("result.json"))
            .arg("--")
            .arg(std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| "python3".into()))
            .arg("-c")
            .arg(code);
        command
    }

    fn report(&self) -> Value {
        serde_json::from_slice(&fs::read(self.0.join("result.json")).unwrap()).unwrap()
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn exact_arguments_environment_and_binary_output_are_forwarded() {
    let root = TestDir::new();
    let output = root
        .command(
            r#"
import os,sys
assert sys.argv[1:] == ['', '--a=two words; not a shell', '\u03bb', os.fsdecode(b'bad-\xff')]
assert os.environ['PT_EXEC_SENTINEL'] == 'inherited'
os.write(1,b'out\x00\xff')
os.write(2,b'err\x00\xfe')
"#,
        )
        .args(["", "--a=two words; not a shell", "λ"])
        .arg(std::ffi::OsString::from_vec(b"bad-\xff".to_vec()))
        .env("PT_EXEC_SENTINEL", "inherited")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(0), "{:?}", output.stderr);
    assert_eq!(output.stdout, b"out\x00\xff");
    assert_eq!(output.stderr, b"err\x00\xfe");
    let report = root.report();
    assert_eq!(report["scope"], "process_only");
    assert_eq!(report["cleanup"]["kind"], "complete");
    assert_eq!(report["leader_status"]["code"], 0);
    assert!(report.get("conformance").is_none());
    assert!(report.get("generation_valid").is_none());
    assert_eq!(
        fs::metadata(root.0.join("result.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

#[test]
fn stdin_and_large_stdout_stderr_are_not_hidden_in_a_pt_buffer() {
    let root = TestDir::new();
    let mut child = root
        .command(
            r#"
import sys,os
assert sys.stdin.buffer.read() == b'input\x00bytes'
for _ in range(64): os.write(1,b'x'*8192)
for _ in range(32): os.write(2,b'y'*8192)
"#,
        )
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"input\x00bytes")
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stdout, vec![b'x'; 64 * 8192]);
    assert_eq!(output.stderr, vec![b'y'; 32 * 8192]);
}

#[test]
fn nonzero_child_exit_is_preserved_in_cli_and_report() {
    let root = TestDir::new();
    let output = root.command("raise SystemExit(7)").output().unwrap();
    assert_eq!(output.status.code(), Some(7));
    assert_eq!(root.report()["leader_status"]["code"], 7);
    assert_eq!(root.report()["termination"]["kind"], "process_exited");
}

#[test]
fn existing_report_or_another_writers_lock_prevents_execution() {
    for name in ["result.json", ".pt-report-result.json.lock"] {
        let root = TestDir::new();
        let original = root.0.join(name);
        fs::write(&original, b"existing user evidence").unwrap();
        let output = root
            .command("open('must-not-run','w').close()")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(4));
        assert!(!root.0.join("must-not-run").exists());
        assert_eq!(fs::read(original).unwrap(), b"existing user evidence");
    }
}

#[test]
fn publication_race_does_not_overwrite_or_replay_work() {
    let root = TestDir::new();
    let output = root.command("from pathlib import Path; Path('attempts').write_text('once'); Path('result.json').write_text('other writer')")
        .output().unwrap();
    assert_eq!(output.status.code(), Some(3));
    assert!(String::from_utf8_lossy(&output.stderr).contains("report publication failed"));
    assert_eq!(
        fs::read_to_string(root.0.join("result.json")).unwrap(),
        "other writer"
    );
    assert_eq!(fs::read_to_string(root.0.join("attempts")).unwrap(), "once");
    assert!(!root.0.join(".pt-report-result.json.lock").exists());
}

#[test]
fn replaced_staging_file_is_not_published_or_removed() {
    let root = TestDir::new();
    let output = root.command("from pathlib import Path; p=Path('.pt-report-result.json.lock'); p.unlink(); p.write_text('replacement')")
        .output().unwrap();
    assert_eq!(output.status.code(), Some(3));
    assert!(!root.0.join("result.json").exists());
    assert_eq!(
        fs::read_to_string(root.0.join(".pt-report-result.json.lock")).unwrap(),
        "replacement"
    );
}

#[test]
fn timeout_is_nonzero_and_includes_process_cleanup() {
    let root = TestDir::new();
    let mut command = Command::new(env!("CARGO_BIN_EXE_pt"));
    let output = command
        .args(["exec", "--timeout-seconds", "0.3", "--report"])
        .arg(root.0.join("result.json"))
        .arg("--")
        .arg(std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| "python3".into()))
        .args([
            "-c",
            "import os,time; os.write(1,b'before'); time.sleep(20)",
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(3));
    assert_eq!(output.stdout, b"before");
    let report = root.report();
    assert_eq!(report["termination"]["kind"], "timeout");
    assert_eq!(report["cleanup"]["kind"], "complete");
    assert!(!Path::new(&format!("/proc/{}", report["pid"].as_u64().unwrap())).exists());
}

#[test]
fn actual_cli_sigint_and_sigterm_cancel_and_reap_the_execution() {
    for signal in [Signal::SIGINT, Signal::SIGTERM] {
        let root = TestDir::new();
        let ready = root.0.join("ready");
        let mut child = root
            .command("import time; from pathlib import Path; Path('ready').touch(); time.sleep(20)")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(4);
        while !ready.exists() && child.try_wait().unwrap().is_none() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        assert!(ready.exists(), "execution never became ready");
        kill(Pid::from_raw(child.id() as i32), signal).unwrap();
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            if Instant::now() >= deadline {
                child.kill().unwrap();
                let _ = child.wait();
                panic!("CLI did not stop within the cancellation deadline");
            }
            thread::sleep(Duration::from_millis(5));
        };
        assert_eq!(status.code(), Some(2));
        let report = root.report();
        assert_eq!(report["termination"]["kind"], "interrupted");
        assert_eq!(report["termination"]["signal"], signal as i32);
        assert_eq!(report["cleanup"]["kind"], "complete");
        assert!(!Path::new(&format!("/proc/{}", report["pid"].as_u64().unwrap())).exists());
    }
}

#[test]
fn unimplemented_run_and_ambiguous_forwarding_fail_closed() {
    for args in [vec!["run"], vec!["exec", "python3", "-c", "pass"]] {
        let result = Command::new(env!("CARGO_BIN_EXE_pt"))
            .args(args)
            .output()
            .unwrap();
        assert_eq!(result.status.code(), Some(4));
        assert!(String::from_utf8_lossy(&result.stderr).contains("configuration_error"));
    }
    let result = Command::new(env!("CARGO_BIN_EXE_pt"))
        .arg("--help")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&result.stdout).contains("not a qualified pytest runner"));
}
