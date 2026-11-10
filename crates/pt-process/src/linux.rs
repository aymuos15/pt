//! Linux process groups; no application imports, shell, output buffer, or replay.

use crate::{Cleanup, LeaderStatus, ProcessReport, ProcessScope, Termination};
use command_fds::{CommandFdExt, FdMapping};
use nix::errno::Errno;
use nix::sys::signal::{Signal, killpg};
use nix::sys::wait::{Id, WaitPidFlag, WaitStatus, waitid};
use nix::unistd::Pid;
use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::fs;
use std::io::{self, IsTerminal, Read};
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::thread;
use std::time::{Duration, Instant};

const TICK: Duration = Duration::from_millis(10);

/// Reserved child-only descriptor, never an output/control multiplex on stdio.
pub const CONTROL_FD: i32 = 3;

/// Single-launch capability. Construction creates no named/listening endpoint;
/// consuming it prevents accidental reuse across fresh execution sessions.
#[derive(Debug)]
pub struct ChildControl {
    socket: UnixStream,
}

/// Create connected, close-on-exec endpoints without changing parent FD flags.
/// The caller owns reading, bounds, validation and the terminal protocol gate.
/// A process-only report cannot certify that the stream is valid or complete.
pub fn control_channel_pair() -> io::Result<(UnixStream, ChildControl)> {
    let (parent, child) = UnixStream::pair()?;
    if parent.as_raw_fd() < 3 || child.as_raw_fd() < 3 {
        return Err(io::Error::other(
            "private control handoff requires existing standard-stream descriptors",
        ));
    }
    Ok((parent, ChildControl { socket: child }))
}

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
    /// Metadata/process-capability checks only; does not launch an interpreter,
    /// import project code, collect tests or authorize a qualified pytest run.
    pub fn validate(&self) -> Result<(), RequestError> {
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
    supervise_inner(request, cancelled, None, None)
}

/// Launch with exactly one explicitly supplied connected control capability at
/// CONTROL_FD. The child must mark it non-inheritable before project imports and
/// close it after final control output. No environment or argv injection occurs.
///
/// The caller must drain/validate the stream concurrently under its own bounds;
/// this function supervises the same process boundary, not a pytest protocol.
pub fn supervise_with_control(
    request: &ProcessRequest,
    cancelled: &AtomicI32,
    control: ChildControl,
) -> Result<ProcessReport, RequestError> {
    supervise_inner(request, cancelled, Some(control), None)
}

/// As above, with a separate trusted observer-failure stop flag. This is not a
/// user signal. A live leader is killed/reaped on a detected control failure;
/// a leader already observed dead retains its raw cause for caller classification.
pub fn supervise_with_control_checked(
    request: &ProcessRequest,
    cancelled: &AtomicI32,
    control: ChildControl,
    observer_failed: &AtomicBool,
) -> Result<ProcessReport, RequestError> {
    supervise_inner(request, cancelled, Some(control), Some(observer_failed))
}

fn supervise_inner(
    request: &ProcessRequest,
    cancelled: &AtomicI32,
    control: Option<ChildControl>,
    observer_failed: Option<&AtomicBool>,
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
    if observer_failed.is_some_and(|flag| flag.load(Ordering::SeqCst)) {
        report.termination = Termination::InfrastructureError {
            detail: "private control observer failed before launch".into(),
        };
        finish(&mut report, start);
        return Ok(report);
    }
    let mut command = Command::new(&request.executable);
    command
        .args(&request.args)
        .current_dir(&request.cwd)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .process_group(0);
    if let Some(control) = control
        && let Err(error) = command.fd_mappings(vec![FdMapping {
            parent_fd: control.socket.into(),
            child_fd: CONTROL_FD,
        }])
    {
        report.termination = Termination::InfrastructureError {
            detail: format!("private control descriptor mapping: {error}"),
        };
        finish(&mut report, start);
        return Ok(report);
    }
    let child = command.spawn();
    // command-fds owns the parent's copy until Command is dropped. Close it
    // immediately after spawn (also on failure), not after the supervise loop,
    // so the receiving endpoint can observe the child's real EOF.
    drop(command);
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
    let mut observer_failure_seen = None;

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
        if observer_failed.is_some_and(|flag| flag.load(Ordering::SeqCst)) {
            // Descriptor closure during do_exit can precede waitable status.
            // Give it one bounded supervisor tick, observing the leader again,
            // before declaring that a channel fault stopped a still-live child.
            let first = observer_failure_seen.get_or_insert_with(Instant::now);
            if first.elapsed() >= TICK {
                report.termination = Termination::InfrastructureError {
                    detail: "private control observer failed while execution was live".into(),
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
