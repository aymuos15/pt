//! Linux process groups; no application imports, shell, output buffer, or replay.

use crate::{Cleanup, LeaderStatus, ProcessReport, ProcessScope, Termination};
use nix::errno::Errno;
use nix::sys::signal::{Signal, killpg};
use nix::sys::wait::{Id, WaitPidFlag, WaitStatus, waitid};
use nix::unistd::Pid;
use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::fs;
use std::io::{self, IsTerminal, Read};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicI32, Ordering};
use std::thread;
use std::time::{Duration, Instant};

const TICK: Duration = Duration::from_millis(10);

#[derive(Debug, Clone)]
pub struct ProcessRequest {
    pub executable: OsString,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    /// Execution deadline, followed by a separately bounded cleanup period.
    pub timeout: Duration,
    pub cleanup_timeout: Duration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestError(pub String);

impl fmt::Display for RequestError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(&self.0)
    }
}

impl Error for RequestError {}

impl ProcessRequest {
    fn validate(&self) -> Result<(), RequestError> {
        let bad_argument = self.executable.is_empty()
            || self.executable.as_bytes().contains(&0)
            || self.args.iter().any(|arg| arg.as_bytes().contains(&0));
        if bad_argument || self.cwd.as_os_str().as_bytes().contains(&0) {
            return Err(RequestError(
                "empty executable or NUL in OS argument".into(),
            ));
        }
        if !self.cwd.is_dir() {
            return Err(RequestError("cwd must be an existing directory".into()));
        }
        if io::stdin().is_terminal() {
            return Err(RequestError(
                "interactive stdin is unsupported until terminal job control is qualified; supply non-terminal input explicitly".into(),
            ));
        }
        let now = Instant::now();
        if self.timeout.is_zero()
            || now.checked_add(self.timeout).is_none()
            || self.cleanup_timeout.is_zero()
            || self.cleanup_timeout > Duration::from_secs(30)
        {
            return Err(RequestError(
                "timeout must be positive and representable; cleanup must be in (0, 30s]".into(),
            ));
        }
        // The cleanup contract requires a usable procfs, not just kill(0).
        group_members(std::process::id()).map_err(|error| {
            RequestError(format!("Linux procfs verification unavailable: {error}"))
        })?;
        Ok(())
    }
}

/// The direct child stays unreaped until group signaling is finished. Keeping
/// its PID allocated prevents a recycled process/group receiving our signals.
struct OwnedChild {
    child: Child,
    pgid: Pid,
    ownership: bool,
}

impl OwnedChild {
    fn observe(&mut self) -> Result<Option<LeaderStatus>, Errno> {
        let status = waitid(
            Id::Pid(self.pgid),
            WaitPidFlag::WEXITED | WaitPidFlag::WNOHANG | WaitPidFlag::WNOWAIT,
        );
        match status {
            Ok(WaitStatus::Exited(_, code)) => Ok(Some(LeaderStatus::Exited { code })),
            Ok(WaitStatus::Signaled(_, signal, core_dumped)) => Ok(Some(LeaderStatus::Signaled {
                signal: signal as i32,
                core_dumped,
            })),
            Ok(WaitStatus::StillAlive) | Err(Errno::EINTR) => Ok(None),
            Ok(_) => Err(Errno::EINVAL),
            Err(error) => {
                // A foreign SIGCHLD handler/reaper may have released the PID.
                // Do not signal a potentially reused identity in that case.
                if error == Errno::ECHILD {
                    self.ownership = false;
                }
                Err(error)
            }
        }
    }

    fn signal(&self, signal: Signal) -> Result<(), Errno> {
        if !self.ownership {
            return Err(Errno::ECHILD);
        }
        match killpg(self.pgid, signal) {
            Ok(()) | Err(Errno::ESRCH) => Ok(()),
            Err(error) => Err(error),
        }
    }

    fn reap(&mut self) -> io::Result<bool> {
        match self.child.try_wait()? {
            Some(_) => {
                self.ownership = false;
                Ok(true)
            }
            None => Ok(false),
        }
    }
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if self.ownership {
            // Emergency best effort only. Normal paths return explicit cleanup
            // evidence; neither Drop nor any other path waits without a bound.
            if self.observe().is_ok() && self.ownership {
                let _ = self.signal(Signal::SIGKILL);
                let _ = self.reap();
            }
        }
    }
}

fn stat_group(text: &[u8]) -> io::Result<(u32, bool)> {
    // comm can contain spaces, newlines, and ')'; the final ')' ends it.
    let end = text
        .iter()
        .rposition(|byte| *byte == b')')
        .ok_or_else(|| io::Error::other("invalid procfs process record"))?;
    let fields: Vec<_> = text[end + 1..]
        .split(|byte| byte.is_ascii_whitespace())
        .filter(|field| !field.is_empty())
        .collect();
    if fields.len() < 3 {
        return Err(io::Error::other("short procfs process record"));
    }
    let group = std::str::from_utf8(fields[2])
        .map_err(|_| io::Error::other("invalid procfs process group bytes"))?
        .parse()
        .map_err(|_| io::Error::other("invalid procfs process group"))?;
    Ok((group, !matches!(fields[0], b"Z" | b"X" | b"x")))
}

fn group_members(pgid: u32) -> io::Result<Vec<u32>> {
    let mut members = Vec::new();
    for entry in fs::read_dir("/proc")? {
        let entry = entry?;
        let Some(pid) = entry
            .file_name()
            .to_str()
            .and_then(|name| name.parse::<u32>().ok())
        else {
            continue;
        };
        let file = match fs::File::open(entry.path().join("stat")) {
            Ok(file) => file,
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.raw_os_error() == Some(Errno::ESRCH as i32) =>
            {
                continue;
            }
            Err(error) => return Err(error),
        };
        let mut text = Vec::new();
        match file.take(16 * 1024).read_to_end(&mut text) {
            Ok(_) => {}
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.raw_os_error() == Some(Errno::ESRCH as i32) =>
            {
                continue;
            }
            Err(error) => return Err(error),
        }
        let (group, live) = stat_group(&text)?;
        if group == pgid && live {
            members.push(pid);
        }
    }
    members.sort_unstable();
    Ok(members)
}

fn finish(report: &mut ProcessReport, start: Instant) {
    report.elapsed_ns = start.elapsed().as_nanos();
}

fn send(child: &OwnedChild, signal: Signal, report: &mut ProcessReport, errors: &mut Vec<String>) {
    match child.signal(signal) {
        Ok(()) => report.cleanup_signals.push(signal as i32),
        Err(error) => errors.push(format!("group signal {signal}: {error}")),
    }
}

/// Supervise exactly one invocation, with caller-owned cancellation state.
///
/// A nonzero cancellation signal prevents launch if observed before spawn.
/// The environment and all standard streams are inherited without rewriting.
/// There is no automatic retry, hidden Python probe, or pytest success claim.
pub fn supervise(
    request: &ProcessRequest,
    cancelled: &AtomicI32,
) -> Result<ProcessReport, RequestError> {
    request.validate()?;
    let start = Instant::now();
    let deadline = start + request.timeout;
    let mut report = ProcessReport {
        schema_version: 1,
        scope: ProcessScope::ProcessOnly,
        pid: None,
        termination: Termination::ProcessExited,
        leader_status: None,
        cleanup: Cleanup::NotLaunched,
        cleanup_signals: Vec::new(),
        elapsed_ns: 0,
    };
    let signal = cancelled.load(Ordering::SeqCst);
    if signal != 0 {
        report.termination = Termination::Interrupted { signal };
        finish(&mut report, start);
        return Ok(report);
    }
    let child = Command::new(&request.executable)
        .args(&request.args)
        .current_dir(&request.cwd)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .process_group(0)
        .spawn();
    let child = match child {
        Ok(child) => child,
        Err(error) => {
            report.termination = Termination::LaunchError {
                detail: error.to_string(),
            };
            finish(&mut report, start);
            return Ok(report);
        }
    };
    report.pid = Some(child.id());
    let mut child = OwnedChild {
        pgid: Pid::from_raw(child.id() as i32),
        child,
        ownership: true,
    };

    loop {
        let signal = cancelled.load(Ordering::SeqCst);
        if signal != 0 {
            report.termination = Termination::Interrupted { signal };
            break;
        }
        if Instant::now() >= deadline {
            report.termination = Termination::Timeout;
            break;
        }
        match child.observe() {
            Ok(Some(status)) => {
                report.termination = match status {
                    LeaderStatus::Exited { .. } => Termination::ProcessExited,
                    LeaderStatus::Signaled { .. } => Termination::BackendTerminated,
                };
                report.leader_status = Some(status);
                break;
            }
            Ok(None) => {}
            Err(error) => {
                report.termination = Termination::InfrastructureError {
                    detail: format!("observing leader: {error}"),
                };
                break;
            }
        }
        thread::sleep(TICK.min(deadline.saturating_duration_since(Instant::now())));
    }

    let cleanup_start = Instant::now();
    let cleanup_deadline = cleanup_start + request.cleanup_timeout;
    let escalate_at = cleanup_start + (request.cleanup_timeout / 2).min(Duration::from_millis(100));
    let mut errors = Vec::new();
    let mut killed = matches!(
        report.termination,
        Termination::Timeout | Termination::InfrastructureError { .. }
    );
    send(
        &child,
        if killed {
            Signal::SIGKILL
        } else {
            Signal::SIGTERM
        },
        &mut report,
        &mut errors,
    );
    loop {
        let signal = cancelled.load(Ordering::SeqCst);
        if signal != 0
            && matches!(
                report.termination,
                Termination::ProcessExited | Termination::BackendTerminated
            )
        {
            report.termination = Termination::Interrupted { signal };
        }
        if !child.ownership {
            errors.push("leader ownership lost; process group not safe to signal".into());
            break;
        }
        match child.observe() {
            Ok(Some(status)) => report.leader_status = Some(status),
            Ok(None) => {}
            Err(error) => {
                if errors.is_empty() {
                    errors.push(format!("observing leader during cleanup: {error}"));
                }
                if !child.ownership {
                    break;
                }
            }
        }
        let members = group_members(child.pgid.as_raw() as u32);
        match members {
            Ok(ref members) if members.is_empty() && report.leader_status.is_some() => {
                match child.reap() {
                    Ok(true) => {
                        report.cleanup = if errors.is_empty() {
                            Cleanup::Complete
                        } else {
                            Cleanup::Uncertain {
                                detail: errors.join("; "),
                            }
                        };
                        finish(&mut report, start);
                        return Ok(report);
                    }
                    Ok(false) => errors.push("terminal leader could not be reaped".into()),
                    Err(error) => errors.push(format!("reaping leader: {error}")),
                }
                break;
            }
            Err(ref error) if errors.is_empty() => {
                // Retain one diagnostic, not an unbounded list on every tick.
                errors.push(format!("verifying process group: {error}"));
            }
            _ => {}
        }
        let now = Instant::now();
        if now >= cleanup_deadline {
            if !killed {
                send(&child, Signal::SIGKILL, &mut report, &mut errors);
            }
            errors.push(format!(
                "cleanup deadline expired; live members: {members:?}"
            ));
            break;
        }
        if !killed && now >= escalate_at {
            send(&child, Signal::SIGKILL, &mut report, &mut errors);
            killed = true;
        }
        thread::sleep(TICK.min(cleanup_deadline.saturating_duration_since(now)));
    }
    report.cleanup = Cleanup::Uncertain {
        detail: errors.join("; "),
    };
    // Any emergency Drop cleanup happens before the elapsed endpoint.
    drop(child);
    finish(&mut report, start);
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn procfs_group_parser_handles_embedded_parentheses_and_spaces() {
        assert_eq!(
            stat_group(b"13 (a ) weird name) S 1 13 13").unwrap(),
            (13, true)
        );
        assert_eq!(stat_group(b"13 (worker) Z 1 13 13").unwrap(), (13, false));
        assert_eq!(
            stat_group(b"13 (non-utf8-\xff) S 1 13 13").unwrap(),
            (13, true)
        );
        assert!(stat_group(b"malformed").is_err());
        assert!(stat_group(b"13 (worker) S 1 invalid").is_err());
    }
}
