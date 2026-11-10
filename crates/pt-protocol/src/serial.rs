use crate::{
    Accounting, ArtifactReady, AttemptKey, BridgeMessage, BridgePayload, ChannelIdentity,
    CollectionError, CollectionFinished, CollectionReport, CollectionStatus, Disposition,
    InvocationProfile, MAX_EVENTS, MAX_STREAM_BYTES, NotRunReason, Outcome, Phase, PhaseCounts,
    PhaseReport, ProtocolError, SessionError, SessionErrorCategory, SessionTerminal,
    SessionTermination, StreamEnd,
};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestMode {
    Run,
    CollectOnly,
}

/// Coordinator-owned request facts, never assertions supplied by a bridge.
/// This serial revision permits no retry, extension, scheduling or reattachment.
#[derive(Debug, Clone)]
pub struct SerialContract {
    pub invocation_profile: InvocationProfile,
    pub mode: RequestMode,
    pub max_items: usize,
    pub max_collection_reports: usize,
    pub max_nodeid_bytes: usize,
    pub declared_artifact_ids: Vec<String>,
}

impl SerialContract {
    fn validate(&self) -> Result<(), ProtocolError> {
        if !(1..=100_000).contains(&self.max_items)
            || !(1..=100_000).contains(&self.max_collection_reports)
            || !(1..=16 * 1024 * 1024).contains(&self.max_nodeid_bytes)
            || self.declared_artifact_ids.len() > 1024
            || self
                .declared_artifact_ids
                .iter()
                .collect::<HashSet<_>>()
                .len()
                != self.declared_artifact_ids.len()
            || self.declared_artifact_ids.iter().any(|id| {
                id.is_empty()
                    || id.len() > 128
                    || !id.as_bytes()[0].is_ascii_alphanumeric()
                    || !id
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
            })
        {
            Err(ProtocolError::new(
                "invalid explicit serial accounting contract/bounds",
            ))
        } else {
            Ok(())
        }
    }
}

#[derive(Debug, Clone)]
pub struct BridgeSnapshot {
    pub stream_consistent_so_far: bool,
    pub handshake_seen: bool,
    pub collection: Option<CollectionFinished>,
    pub nodeids: Vec<String>,
    pub selected: Vec<u64>,
    pub deselected: Vec<u64>,
    pub accounting: Accounting,
    pub phase_counts: PhaseCounts,
    pub incomplete_ordinals: Vec<u64>,
    pub session_error_count: u64,
    pub terminal: Option<SessionTerminal>,
    pub artifact_ready_claims: Vec<ArtifactReady>,
    pub collection_reports: Vec<CollectionReport>,
    pub collection_errors: Vec<CollectionError>,
    pub attempts: Vec<AttemptObservation>,
    pub not_run: Vec<crate::ItemNotRun>,
    pub session_errors: Vec<SessionError>,
}

#[derive(Debug, Clone)]
pub struct AttemptObservation {
    pub ordinal: u64,
    pub phases: Vec<PhaseReport>,
    pub disposition: Option<Disposition>,
    pub reason: Option<String>,
}

/// Necessary ledger consistency only. Snapshots contain no current/full-success,
/// environment-verified or artifact-committed assertion. Known death/timeout can
/// retain a partial snapshot without calling normal-exit validation or replaying.
pub struct SerialLedger {
    source: Option<Arc<()>>,
    identity: ChannelIdentity,
    contract: SerialContract,
    failed: bool,
    events: u64,
    wire_bytes: u64,
    handshake: bool,
    collecting: bool,
    inventory_closed: bool,
    collection: Option<CollectionFinished>,
    items: Vec<String>,
    nodeid_bytes: usize,
    reports: HashMap<u64, CollectionReport>,
    report_order: Vec<u64>,
    collection_errors: HashMap<u64, CollectionError>,
    error_order: Vec<u64>,
    selected: Vec<u64>,
    selected_set: HashSet<u64>,
    next_selected: usize,
    deselected: Vec<u64>,
    partition: HashSet<u64>,
    chunks: [u64; 2],
    attempts: HashMap<u64, AttemptObservation>,
    active: Option<u64>,
    not_run: HashMap<u64, NotRunReason>,
    execution_stopped: bool,
    phase_counts: PhaseCounts,
    session_error_count: u64,
    internal_errors: u64,
    usage_errors: u64,
    session_errors: Vec<SessionError>,
    terminal: Option<SessionTerminal>,
    ready: HashMap<String, ArtifactReady>,
}

fn require(condition: bool, code: &str) -> Result<(), ProtocolError> {
    if condition {
        Ok(())
    } else {
        Err(ProtocolError::new(code))
    }
}

impl SerialLedger {
    pub fn new(identity: ChannelIdentity, contract: SerialContract) -> Result<Self, ProtocolError> {
        identity.validate()?;
        contract.validate()?;
        Ok(Self {
            source: None,
            identity,
            contract,
            failed: false,
            events: 0,
            wire_bytes: 0,
            handshake: false,
            collecting: false,
            inventory_closed: false,
            collection: None,
            items: Vec::new(),
            nodeid_bytes: 0,
            reports: HashMap::new(),
            report_order: Vec::new(),
            collection_errors: HashMap::new(),
            error_order: Vec::new(),
            selected: Vec::new(),
            selected_set: HashSet::new(),
            next_selected: 0,
            deselected: Vec::new(),
            partition: HashSet::new(),
            chunks: [0, 0],
            attempts: HashMap::new(),
            active: None,
            not_run: HashMap::new(),
            execution_stopped: false,
            phase_counts: PhaseCounts::default(),
            session_error_count: 0,
            internal_errors: 0,
            usage_errors: 0,
            session_errors: Vec::new(),
            terminal: None,
            ready: HashMap::new(),
        })
    }

    pub fn apply(&mut self, message: &BridgeMessage) -> Result<(), ProtocolError> {
        if self.failed {
            return Err(ProtocolError::new("failed bridge ledger cannot be resumed"));
        }
        let result = self.apply_inner(message);
        if result.is_err() {
            self.failed = true;
        }
        result
    }

    fn apply_inner(&mut self, message: &BridgeMessage) -> Result<(), ProtocolError> {
        if self.events == 0 {
            self.source = message.source.clone();
        } else {
            require(
                match (&self.source, &message.source) {
                    (Some(left), Some(right)) => Arc::ptr_eq(left, right),
                    (None, None) => true,
                    _ => false,
                },
                "mixed framed/unframed or distinct private streams",
            )?;
        }
        require(
            message.identity() == &self.identity && message.sequence() == self.events,
            "ledger channel identity/sequence mismatch",
        )?;
        require(self.terminal.is_none(), "event after bridge terminal")?;
        let bytes = message.raw_json().len() as u64 + 4;
        require(
            self.events < MAX_EVENTS && bytes <= MAX_STREAM_BYTES - self.wire_bytes,
            "aggregate ledger event/byte bound",
        )?;
        require(
            self.handshake || matches!(message.payload(), BridgePayload::SessionStarted(_)),
            "bridge handshake must be first",
        )?;
        self.dispatch(message.payload())?;
        self.events += 1;
        self.wire_bytes += bytes;
        Ok(())
    }

    fn partition(&mut self, chunk: u64, values: &[u64], side: usize) -> Result<(), ProtocolError> {
        require(chunk == self.chunks[side], "selection chunk gap/duplicate")?;
        require(
            values.iter().all(|ordinal| {
                (*ordinal as u128) < self.items.len() as u128 && !self.partition.contains(ordinal)
            }),
            "unknown/duplicate selection occurrence",
        )?;
        self.inventory_closed = true;
        self.chunks[side] += 1;
        self.partition.extend(values.iter().copied());
        if side == 0 {
            self.selected.extend_from_slice(values);
            self.selected_set.extend(values.iter().copied());
        } else {
            self.deselected.extend_from_slice(values);
        }
        Ok(())
    }

    fn counts(&self) -> Accounting {
        let completed = self
            .attempts
            .values()
            .filter(|value| value.disposition == Some(Disposition::Completed))
            .count() as u64;
        Accounting {
            collected_count: self.items.len() as u64,
            selected_count: self.selected.len() as u64,
            deselected_count: self.deselected.len() as u64,
            executed_count: self.attempts.len() as u64,
            completed_count: completed,
            not_run_count: self.not_run.len() as u64,
            attempts_started: self.attempts.len() as u64,
            attempts_completed: completed,
        }
    }

    fn incomplete(&self) -> Vec<u64> {
        self.selected
            .iter()
            .copied()
            .filter(|ordinal| {
                !self.not_run.contains_key(ordinal)
                    && self
                        .attempts
                        .get(ordinal)
                        .is_none_or(|value| value.disposition != Some(Disposition::Completed))
            })
            .collect()
    }

    pub fn snapshot(&self) -> BridgeSnapshot {
        let mut ready = self.ready.values().cloned().collect::<Vec<_>>();
        ready.sort_by(|left, right| left.artifact_id.cmp(&right.artifact_id));
        let reports = self
            .report_order
            .iter()
            .map(|id| self.reports[id].clone())
            .collect();
        let errors = self
            .error_order
            .iter()
            .map(|id| self.collection_errors[id].clone())
            .collect();
        BridgeSnapshot {
            stream_consistent_so_far: !self.failed,
            handshake_seen: self.handshake,
            collection: self.collection.clone(),
            nodeids: self.items.clone(),
            selected: self.selected.clone(),
            deselected: self.deselected.clone(),
            accounting: self.counts(),
            phase_counts: self.phase_counts.clone(),
            incomplete_ordinals: self.incomplete(),
            session_error_count: self.session_error_count,
            terminal: self.terminal.clone(),
            artifact_ready_claims: ready,
            collection_reports: reports,
            collection_errors: errors,
            attempts: self
                .selected
                .iter()
                .filter_map(|ordinal| self.attempts.get(ordinal).cloned())
                .collect(),
            not_run: self
                .selected
                .iter()
                .filter_map(|ordinal| {
                    self.not_run.get(ordinal).map(|reason| crate::ItemNotRun {
                        ordinal: *ordinal,
                        reason: *reason,
                    })
                })
                .collect(),
            session_errors: self.session_errors.clone(),
        }
    }

    /// Presence only, not validity, normal process return or full completion.
    pub fn terminal_observed(&self) -> bool {
        self.terminal.is_some()
    }

    fn dispatch(&mut self, payload: &BridgePayload) -> Result<(), ProtocolError> {
        match payload {
            BridgePayload::SessionStarted(value) => {
                require(
                    !self.handshake && value.invocation_profile == self.contract.invocation_profile,
                    "duplicate/mismatched bridge handshake",
                )?;
                self.handshake = true;
            }
            BridgePayload::CollectionStarted => {
                require(
                    !self.collecting && self.collection.is_none(),
                    "duplicate collection session",
                )?;
                self.collecting = true;
            }
            BridgePayload::CollectionReport(value) => {
                self.collection_open()?;
                require(
                    self.reports.len() < self.contract.max_collection_reports
                        && !self.reports.contains_key(&value.report_id),
                    "duplicate/excessive collection report",
                )?;
                self.reports.insert(value.report_id, value.clone());
                self.report_order.push(value.report_id);
            }
            BridgePayload::CollectionError(value) => {
                self.collection_open()?;
                require(
                    self.reports.get(&value.report_id).is_some_and(|report| {
                        report.nodeid == value.nodeid && report.outcome == Outcome::Failed
                    }) && !self.collection_errors.contains_key(&value.report_id),
                    "unmatched/duplicate collection error",
                )?;
                require(
                    self.collection_errors.len() + self.session_errors.len() < 1024,
                    "excessive retained error summaries",
                )?;
                self.collection_errors
                    .insert(value.report_id, value.clone());
                self.error_order.push(value.report_id);
            }
            BridgePayload::ItemCollected(value) => {
                self.collection_open()?;
                require(
                    !self.inventory_closed && value.ordinal == self.items.len() as u64,
                    "inventory after selection or ordinal gap/duplicate",
                )?;
                require(
                    self.items.len() < self.contract.max_items
                        && value.nodeid.len() <= self.contract.max_nodeid_bytes - self.nodeid_bytes,
                    "item/node-ID aggregate bound exceeded",
                )?;
                self.nodeid_bytes += value.nodeid.len();
                self.items.push(value.nodeid.clone());
            }
            BridgePayload::ItemsSelected(value) => {
                self.collection_open()?;
                self.partition(value.chunk, &value.ordinals, 0)?;
            }
            BridgePayload::ItemsDeselected(value) => {
                self.collection_open()?;
                self.partition(value.chunk, &value.ordinals, 1)?;
            }
            BridgePayload::CollectionFinished(value) => {
                self.collection_open()?;
                let failed = self
                    .reports
                    .iter()
                    .filter(|(_, report)| report.outcome == Outcome::Failed)
                    .map(|(id, _)| *id)
                    .collect::<HashSet<_>>();
                require(
                    self.partition.len() == self.items.len()
                        && value.collected_count == self.items.len() as u64
                        && value.selected_count == self.selected.len() as u64
                        && value.deselected_count == self.deselected.len() as u64,
                    "incomplete selection partition/collection counts",
                )?;
                require(
                    failed == self.collection_errors.keys().copied().collect()
                        && (failed.is_empty() || value.status != CollectionStatus::Complete),
                    "hidden/unaccounted collection failure",
                )?;
                self.collection = Some(value.clone());
            }
            BridgePayload::ItemStarted(value) => self.start(*value)?,
            BridgePayload::PhaseReport(value) => {
                self.attempt_open(value.ordinal, value.attempt)?;
                require(
                    value
                        .artifact_ids
                        .iter()
                        .all(|id| self.contract.declared_artifact_ids.contains(id)),
                    "undeclared phase artifact",
                )?;
                let attempt = self
                    .attempts
                    .get_mut(&value.ordinal)
                    .expect("active attempt exists");
                let observed = attempt
                    .phases
                    .iter()
                    .map(|value| (value.phase, value.outcome))
                    .collect::<Vec<_>>();
                let expected = match observed.as_slice() {
                    [] => Phase::Setup,
                    [(Phase::Setup, Outcome::Passed)] => Phase::Call,
                    [(Phase::Setup, _)] | [(Phase::Setup, Outcome::Passed), (Phase::Call, _)] => {
                        Phase::Teardown
                    }
                    _ => return Err(ProtocolError::new("extra/duplicate phase after teardown")),
                };
                require(value.phase == expected, "missing/reordered phase")?;
                attempt.phases.push(value.clone());
                let counts = match value.phase {
                    Phase::Setup => &mut self.phase_counts.setup,
                    Phase::Call => &mut self.phase_counts.call,
                    Phase::Teardown => &mut self.phase_counts.teardown,
                };
                match value.outcome {
                    Outcome::Passed => counts.passed += 1,
                    Outcome::Failed => counts.failed += 1,
                    Outcome::Skipped => counts.skipped += 1,
                }
            }
            BridgePayload::AttemptFinished(value) => {
                self.attempt_open(value.ordinal, value.attempt)?;
                require(
                    value.disposition != Disposition::Retry,
                    "retry adapter is unsupported; no unrequested replay",
                )?;
                let attempt = self
                    .attempts
                    .get_mut(&value.ordinal)
                    .expect("active attempt exists");
                let phases = attempt
                    .phases
                    .iter()
                    .map(|value| value.phase)
                    .collect::<Vec<_>>();
                let expected = if attempt
                    .phases
                    .first()
                    .is_some_and(|value| value.outcome == Outcome::Passed)
                {
                    vec![Phase::Setup, Phase::Call, Phase::Teardown]
                } else {
                    vec![Phase::Setup, Phase::Teardown]
                };
                require(
                    value.disposition == Disposition::Interrupted || phases == expected,
                    "attempt completion lacks applicable phases",
                )?;
                attempt.disposition = Some(value.disposition);
                attempt.reason = value.reason.clone();
                self.active = None;
            }
            BridgePayload::ItemNotRun(value) => {
                require(
                    self.collection.is_some()
                        && self.active.is_none()
                        && self.selected_set.contains(&value.ordinal)
                        && !self.attempts.contains_key(&value.ordinal)
                        && !self.not_run.contains_key(&value.ordinal),
                    "invalid/duplicate/late not-run occurrence",
                )?;
                require(
                    (value.reason == NotRunReason::CollectOnly)
                        == (self.contract.mode == RequestMode::CollectOnly),
                    "not-run mode contradiction",
                )?;
                if value.reason == NotRunReason::CollectionFailed {
                    require(
                        self.collection
                            .as_ref()
                            .is_some_and(|value| value.status == CollectionStatus::Failed),
                        "not-run collection-failure context missing",
                    )?;
                }
                if value.reason == NotRunReason::FailFast {
                    require(
                        self.failed_phases() > 0,
                        "not-run fail-fast context missing",
                    )?;
                }
                self.execution_stopped = true;
                self.not_run.insert(value.ordinal, value.reason);
            }
            BridgePayload::Warning(value) => {
                require(
                    value
                        .ordinal
                        .is_none_or(|ordinal| (ordinal as u128) < self.items.len() as u128),
                    "warning names an unknown occurrence",
                )?;
            }
            BridgePayload::OutputReference(value) => {
                require(
                    self.contract
                        .declared_artifact_ids
                        .contains(&value.artifact_id),
                    "undeclared output artifact",
                )?;
                if let Some(ordinal) = value.ordinal {
                    require(
                        value.attempt == Some(0) && self.attempts.contains_key(&ordinal),
                        "output names unknown attempt",
                    )?;
                }
            }
            BridgePayload::ArtifactReady(value) => {
                require(
                    self.contract
                        .declared_artifact_ids
                        .contains(&value.artifact_id)
                        && !self.ready.contains_key(&value.artifact_id),
                    "undeclared/duplicate artifact-ready claim",
                )?;
                self.ready.insert(value.artifact_id.clone(), value.clone());
            }
            BridgePayload::SessionError(value) => {
                require(
                    self.collection_errors.len() + self.session_errors.len() < 1024,
                    "excessive retained error summaries",
                )?;
                self.session_errors.push(value.clone());
                self.session_error_count += 1;
                if value.category == SessionErrorCategory::Internal {
                    self.internal_errors += 1;
                }
                if value.category == SessionErrorCategory::Usage {
                    self.usage_errors += 1;
                }
            }
            BridgePayload::ExtensionEvent(_) => {
                return Err(ProtocolError::new("extension adapter is unsupported"));
            }
            BridgePayload::SessionTerminated(value) => {
                require(
                    self.active.is_none()
                        && value.accounting == self.counts()
                        && value.phase_counts == self.phase_counts
                        && value.incomplete_ordinals == self.incomplete(),
                    "terminal arithmetic/incomplete accounting mismatch",
                )?;
                self.terminal = Some(value.clone());
            }
        }
        Ok(())
    }

    fn collection_open(&self) -> Result<(), ProtocolError> {
        require(
            self.collecting && self.collection.is_none(),
            "event outside collection barrier",
        )
    }

    fn start(&mut self, key: AttemptKey) -> Result<(), ProtocolError> {
        require(
            self.collection.is_some()
                && self.contract.mode == RequestMode::Run
                && self.active.is_none()
                && key.attempt == 0
                && !self.attempts.contains_key(&key.ordinal)
                && !self.not_run.contains_key(&key.ordinal),
            "unrequested replay/overlapping attempt or execution before collection",
        )?;
        require(
            !self.execution_stopped,
            "execution after declared not-run stop",
        )?;
        while self
            .selected
            .get(self.next_selected)
            .is_some_and(|ordinal| {
                self.attempts.contains_key(ordinal) || self.not_run.contains_key(ordinal)
            })
        {
            self.next_selected += 1;
        }
        require(
            self.selected.get(self.next_selected) == Some(&key.ordinal),
            "unselected/reordered occurrence execution",
        )?;
        self.attempts.insert(
            key.ordinal,
            AttemptObservation {
                ordinal: key.ordinal,
                phases: Vec::new(),
                disposition: None,
                reason: None,
            },
        );
        self.active = Some(key.ordinal);
        Ok(())
    }

    fn attempt_open(&self, ordinal: u64, attempt: u8) -> Result<(), ProtocolError> {
        require(
            attempt == 0 && self.active == Some(ordinal),
            "report outside active serial attempt",
        )
    }

    fn failed_phases(&self) -> u64 {
        self.phase_counts.setup.failed
            + self.phase_counts.call.failed
            + self.phase_counts.teardown.failed
    }

    /// Only for an actually observed normal process exit after clean socket EOF.
    /// Signals/timeouts retain snapshot() and the process-owned cause instead.
    /// Ok(...) still cannot certify artifacts, environment, scope or generations.
    pub fn validate_normal_exit(
        &self,
        eof: &StreamEnd,
        code: u8,
    ) -> Result<BridgeSnapshot, ProtocolError> {
        require(
            !self.failed
                && self.handshake
                && self
                    .source
                    .as_ref()
                    .is_some_and(|source| Arc::ptr_eq(source, &eof.source))
                && eof.identity == self.identity
                && eof.events == self.events
                && eof.wire_bytes == self.wire_bytes,
            "missing/mixed/unconsumed clean channel EOF",
        )?;
        let terminal = self
            .terminal
            .as_ref()
            .ok_or_else(|| ProtocolError::new("normal exit lacks bridge terminal"))?;
        require(
            terminal.backend_exit_code == Some(code) && code <= 5 && terminal.reporting_complete,
            "terminal/process exit mismatch, undocumented exit or incomplete reporting",
        )?;
        require(
            !self.collecting || self.collection.is_some(),
            "normal exit leaves an open collection barrier",
        )?;
        require(
            self.session_errors
                .iter()
                .all(|value| match value.category {
                    SessionErrorCategory::Internal => code == 3,
                    SessionErrorCategory::Usage => code == 4,
                    SessionErrorCategory::Infrastructure => code == 3,
                    SessionErrorCategory::Unsupported => false,
                }),
            "backend errors contradict normal process exit",
        )?;
        require(
            match terminal.termination {
                SessionTermination::BackendExited => true,
                SessionTermination::Interrupted => code == 2,
                SessionTermination::InfrastructureFailed => code == 3,
            },
            "bridge termination contradicts normal process exit",
        )?;
        if !matches!(code, 2..=4) {
            require(
                self.collection.is_some(),
                "normal execution/collection inventory missing",
            )?;
        }
        match code {
            0 => {
                let collection = self.collection.as_ref().expect("collection required above");
                require(
                    collection.status == CollectionStatus::Complete
                        && !self.selected.is_empty()
                        && self.failed_phases() == 0
                        && self.collection_errors.is_empty()
                        && self.session_error_count == 0
                        && self.incomplete().is_empty()
                        && terminal.termination == SessionTermination::BackendExited,
                    "zero exit contradicts nonempty complete failure-free work",
                )?;
                if self.contract.mode == RequestMode::Run {
                    require(
                        self.not_run.is_empty(),
                        "zero run exit hides not-run selected work",
                    )?;
                } else {
                    require(
                        self.attempts.is_empty() && self.not_run.len() == self.selected.len(),
                        "collect-only zero exit hides work accounting",
                    )?;
                }
            }
            1 => {
                require(
                    self.collection
                        .as_ref()
                        .is_some_and(|value| value.status != CollectionStatus::Interrupted),
                    "failure exit has interrupted collection",
                )?;
                require(
                    self.failed_phases() > 0 || !self.collection_errors.is_empty(),
                    "test-failure exit lacks observed failure",
                )?;
                require(
                    self.incomplete().is_empty()
                        && self.not_run.values().all(|reason| {
                            matches!(
                                reason,
                                NotRunReason::FailFast
                                    | NotRunReason::CollectionFailed
                                    | NotRunReason::CollectOnly
                            )
                        }),
                    "failure exit hides unexplained incomplete work",
                )?;
            }
            2 => require(
                terminal.termination == SessionTermination::Interrupted
                    || !self.collection_errors.is_empty(),
                "interrupted exit lacks interruption context",
            )?,
            3 => require(
                self.internal_errors > 0
                    || terminal.termination == SessionTermination::InfrastructureFailed,
                "internal-error exit lacks backend error",
            )?,
            4 => require(
                self.usage_errors > 0,
                "usage-error exit lacks backend usage error",
            )?,
            5 => require(
                self.collection
                    .as_ref()
                    .is_some_and(|value| value.status == CollectionStatus::Complete)
                    && self.selected.is_empty()
                    && self.attempts.is_empty()
                    && self.collection_errors.is_empty()
                    && self.session_error_count == 0
                    && self.failed_phases() == 0,
                "no-tests exit contradicts selected/executed/failed work",
            )?,
            _ => unreachable!(),
        }
        Ok(self.snapshot())
    }
}
