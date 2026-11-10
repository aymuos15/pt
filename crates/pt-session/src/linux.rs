use pt_process::{
    Cleanup, LeaderStatus, ProcessReport, ProcessRequest, Termination, control_channel_pair,
    supervise_with_control_checked,
};
use pt_protocol::{
    BridgeSnapshot, ChannelIdentity, FrameReader, ProtocolError, ProtocolErrorKind, SerialContract,
    SerialLedger, StreamBudget, StreamEnd,
};
use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct SessionSetupError(String);
impl fmt::Display for SessionSetupError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl Error for SessionSetupError {}

/// Explicit component request, not a normalized RunRequest or launch approval.
/// The executable/argv must already contain the caller's chosen bootstrap and
/// entrypoint; this layer passes them exactly without interpreting pytest flags.
pub struct SerialRequest {
    pub process: ProcessRequest,
    pub identity: ChannelIdentity,
    pub contract: SerialContract,
    pub stream_budget: StreamBudget,
    /// One finite allowance for draining already-written frames after the
    /// execution/cleanup window. It never resets per event (maximum 30 seconds).
    pub drain_allowance: Duration,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChannelIssueKind {
    Framing(ProtocolErrorKind),
    Ledger,
    MissingTerminal,
    NormalExitMismatch,
    ObserverPanicked,
}
#[derive(Debug, Clone)]
pub struct ChannelIssue {
    pub kind: ChannelIssueKind,
    pub detail: String,
}
impl ChannelIssue {
    fn protocol(error: ProtocolError, ledger: bool) -> Self {
        Self {
            kind: if ledger {
                ChannelIssueKind::Ledger
            } else {
                ChannelIssueKind::Framing(error.kind())
            },
            detail: error.to_string(),
        }
    }
    fn independent(&self) -> bool {
        matches!(
            self.kind,
            ChannelIssueKind::Ledger
                | ChannelIssueKind::ObserverPanicked
                | ChannelIssueKind::NormalExitMismatch
                | ChannelIssueKind::Framing(
                    ProtocolErrorKind::InvalidData
                        | ProtocolErrorKind::Limit
                        | ProtocolErrorKind::Closed
                )
        )
    }
}

#[derive(Debug, Clone)]
pub struct ChannelObservation {
    pub clean_eof: bool,
    /// Unknown after a lost reader return/panic, never an invented zero.
    pub confirmed_frames: Option<u64>,
    pub confirmed_wire_bytes: Option<u64>,
    pub issue: Option<ChannelIssue>,
}

/// Necessary lifecycle classification only; deliberately not `backend_completed`
/// from the final-result contract, nor an exit code/full/current-success claim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionOutcome {
    NormalExitAccounted { backend_exit_code: u8 },
    LaunchFailed,
    BackendTerminated,
    Timeout,
    Interrupted { signal: i32 },
    InfrastructureFailed,
}

/// Constructible only by this owned live launch/reader flow. Partial observations
/// remain accessible, but cannot be upgraded/retried by loading saved files.
pub struct SessionObservation {
    identity: ChannelIdentity,
    process: ProcessReport,
    snapshot: Option<BridgeSnapshot>,
    channel: ChannelObservation,
    outcome: SessionOutcome,
    elapsed_ns: u128,
}
impl SessionObservation {
    pub fn identity(&self) -> &ChannelIdentity {
        &self.identity
    }
    pub fn process(&self) -> &ProcessReport {
        &self.process
    }
    pub fn snapshot(&self) -> Option<&BridgeSnapshot> {
        self.snapshot.as_ref()
    }
    pub fn channel(&self) -> &ChannelObservation {
        &self.channel
    }
    pub fn outcome(&self) -> &SessionOutcome {
        &self.outcome
    }
    /// Present only after same-reader EOF and the actual documented normal
    /// process return/cleanup were reconciled. Does not waive any other gate.
    pub fn normal_snapshot(&self) -> Option<&BridgeSnapshot> {
        if matches!(self.outcome, SessionOutcome::NormalExitAccounted { .. }) {
            self.snapshot.as_ref()
        } else {
            None
        }
    }
    /// Local diagnostic duration including the reader join and required process
    /// cleanup, not the independent harness's authoritative product stopwatch.
    pub fn elapsed_ns(&self) -> u128 {
        self.elapsed_ns
    }
}

struct ReadResult {
    ledger: SerialLedger,
    end: Option<StreamEnd>,
    channel: ChannelObservation,
}
struct ReaderGuard {
    failed: Arc<AtomicBool>,
    armed: bool,
}
impl Drop for ReaderGuard {
    fn drop(&mut self) {
        if self.armed {
            self.failed.store(true, Ordering::SeqCst);
        }
    }
}

fn read(
    mut reader: FrameReader,
    mut ledger: SerialLedger,
    deadline: Instant,
    failed: &AtomicBool,
) -> ReadResult {
    let issue = loop {
        match reader.receive(deadline) {
            Ok(Some(message)) => {
                if let Err(error) = ledger.apply(&message) {
                    break Some(ChannelIssue::protocol(error, true));
                }
            }
            Ok(None) => {
                break if ledger.terminal_observed() {
                    None
                } else {
                    Some(ChannelIssue{kind:ChannelIssueKind::MissingTerminal,detail:"actual clean EOF lacks a bridge terminal; observed work was not replayed".into()})
                };
            }
            Err(error) => break Some(ChannelIssue::protocol(error, false)),
        }
    };
    if issue.is_some() {
        failed.store(true, Ordering::SeqCst);
    }
    let end = reader.end_evidence();
    let channel = ChannelObservation {
        clean_eof: end.is_some(),
        confirmed_frames: Some(reader.confirmed_frames()),
        confirmed_wire_bytes: Some(reader.confirmed_wire_bytes()),
        issue,
    };
    ReadResult {
        ledger,
        end,
        channel,
    }
}

/// Observe exactly one explicitly requested process with its own new private
/// capability, concurrent bounded reader and serial ledger. Protocol faults stop
/// live owned work; all started outcomes/cleanup are retained and never replayed.
pub fn observe_serial(
    request: SerialRequest,
    cancelled: &AtomicI32,
) -> Result<SessionObservation, SessionSetupError> {
    observe_with(request, cancelled, read)
}

fn observe_with(
    request: SerialRequest,
    cancelled: &AtomicI32,
    reader_job: impl FnOnce(FrameReader, SerialLedger, Instant, &AtomicBool) -> ReadResult
    + Send
    + 'static,
) -> Result<SessionObservation, SessionSetupError> {
    let start = Instant::now();
    request
        .process
        .validate()
        .map_err(|e| SessionSetupError(e.to_string()))?;
    if request.drain_allowance.is_zero() || request.drain_allowance > Duration::from_secs(30) {
        return Err(SessionSetupError(
            "explicit channel drain allowance must be in (0, 30s]".into(),
        ));
    }
    let deadline=request.process.timeout.checked_add(request.process.cleanup_timeout).and_then(|duration|duration.checked_add(request.drain_allowance)).filter(|duration|*duration<=Duration::from_secs(3600))
        .and_then(|duration|start.checked_add(duration)).ok_or_else(||SessionSetupError("explicit whole channel/process lifetime must be representable and at most one hour".into()))?;
    let ledger = SerialLedger::new(request.identity.clone(), request.contract)
        .map_err(|e| SessionSetupError(e.to_string()))?;
    let (parent, control) = control_channel_pair().map_err(|e| SessionSetupError(e.to_string()))?;
    let reader = FrameReader::new(parent, request.identity.clone(), request.stream_budget)
        .map_err(|e| SessionSetupError(e.to_string()))?;
    let failed = Arc::new(AtomicBool::new(false));
    let reader_failed = failed.clone();
    let reader = thread::Builder::new()
        .name("pt-serial-control".into())
        .spawn(move || {
            let mut guard = ReaderGuard {
                failed: reader_failed.clone(),
                armed: true,
            };
            let result = reader_job(reader, ledger, deadline, &reader_failed);
            guard.armed = false;
            result
        })
        .map_err(|e| {
            SessionSetupError(format!(
                "private observer thread unavailable before launch: {e}"
            ))
        })?;
    let process = supervise_with_control_checked(&request.process, cancelled, control, &failed);
    // Dropping the consumed control capability on any validation/launch error
    // permits real EOF. A reader panic also trips the separate stop flag by RAII.
    let observed = reader.join();
    let process = process.map_err(|e| SessionSetupError(e.to_string()))?;
    let (snapshot,mut channel)=match observed {
        Ok(observed)=>{
            let mut channel=observed.channel;
            if channel.issue.is_none() && matches!(process.termination,Termination::ProcessExited)
                && let Some(LeaderStatus::Exited{code})=process.leader_status
                && (0..=5).contains(&code)
            {
                let result=observed.end.as_ref().ok_or_else(||"missing actual EOF evidence".to_owned()).and_then(|end|observed.ledger.validate_normal_exit(end,code as u8).map_err(|e|e.to_string()));
                if let Err(detail)=result {channel.issue=Some(ChannelIssue{kind:ChannelIssueKind::NormalExitMismatch,detail});}
            }
            (Some(observed.ledger.snapshot()),channel)
        },
        Err(_)=>(None,ChannelObservation{clean_eof:false,confirmed_frames:None,confirmed_wire_bytes:None,issue:Some(ChannelIssue{kind:ChannelIssueKind::ObserverPanicked,detail:"private observer return lost to panic; no snapshot or counters reconstructed".into()})}),
    };
    if channel.issue.is_none() && Instant::now() >= deadline {
        channel.issue = Some(ChannelIssue {
            kind: ChannelIssueKind::Framing(ProtocolErrorKind::Deadline),
            detail:
                "absolute channel/process accounting deadline expired before the observation return"
                    .into(),
        });
    }
    let outcome = classify(&process, &channel);
    Ok(SessionObservation {
        identity: request.identity,
        process,
        snapshot,
        channel,
        outcome,
        elapsed_ns: start.elapsed().as_nanos(),
    })
}

fn classify(process: &ProcessReport, channel: &ChannelObservation) -> SessionOutcome {
    if matches!(process.cleanup, Cleanup::Uncertain { .. })
        || channel
            .issue
            .as_ref()
            .is_some_and(ChannelIssue::independent)
    {
        return SessionOutcome::InfrastructureFailed;
    }
    match (&process.termination, &process.leader_status) {
        (Termination::LaunchError { .. }, _) => SessionOutcome::LaunchFailed,
        (Termination::InfrastructureError { .. }, _) => SessionOutcome::InfrastructureFailed,
        (Termination::Timeout, _) => SessionOutcome::Timeout,
        (Termination::Interrupted { signal }, _) => SessionOutcome::Interrupted { signal: *signal },
        (Termination::BackendTerminated, Some(LeaderStatus::Signaled { .. })) => {
            SessionOutcome::BackendTerminated
        }
        (Termination::ProcessExited, Some(LeaderStatus::Exited { code }))
            if (6..=255).contains(code) =>
        {
            SessionOutcome::BackendTerminated
        }
        (Termination::ProcessExited, Some(LeaderStatus::Exited { code }))
            if (0..=5).contains(code)
                && process.cleanup == Cleanup::Complete
                && channel.issue.is_none()
                && channel.clean_eof =>
        {
            SessionOutcome::NormalExitAccounted {
                backend_exit_code: *code as u8,
            }
        }
        _ => SessionOutcome::InfrastructureFailed,
    }
}

#[cfg(test)]
mod tests;
