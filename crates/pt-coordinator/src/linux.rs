use pt_identity::TreeObservation;
use pt_process::{Cleanup, LeaderStatus, ProcessRequest, Termination};
use pt_protocol::{
    Accounting, BridgeSnapshot, ChannelIdentity, CollectionStatus, InvocationProfile, MAX_EVENTS,
    MAX_STREAM_BYTES, PhaseCounts, RequestMode, SerialContract, SerialLedger, SessionErrorCategory,
};
use pt_report::{
    ArtifactDeclaration, ArtifactState, ArtifactStore, JunitExpectation, RetentionBudget,
    WritersStopped,
};
use pt_session::{SerialRequest, SessionObservation, SessionOutcome, observe_serial};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::error::Error;
use std::fmt;
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicI32;
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct CoordinatorError {
    code: &'static str,
    detail: String,
}
impl CoordinatorError {
    pub fn code(&self) -> &'static str {
        self.code
    }
    fn new(code: &'static str, detail: impl fmt::Display) -> Self {
        Self {
            code,
            detail: detail.to_string(),
        }
    }
}
impl fmt::Display for CoordinatorError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.detail)
    }
}
impl Error for CoordinatorError {}
type Result<T> = std::result::Result<T, CoordinatorError>;
fn require(value: bool, code: &'static str) -> Result<()> {
    if value {
        Ok(())
    } else {
        Err(CoordinatorError::new(
            code,
            "explicit request contract not satisfied",
        ))
    }
}
fn id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

/// Requested scope only, never proof of effective full-scope semantics. PT-chosen
/// affected execution is not available through this conservative component.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequestedScope {
    Full,
    Explicit,
}
impl RequestedScope {
    fn text(self) -> &'static str {
        match self {
            Self::Full => "full",
            Self::Explicit => "explicit",
        }
    }
}

struct Facts {
    process: ProcessRequest,
    identity: ChannelIdentity,
    contract: SerialContract,
    scope: RequestedScope,
    coordinator_id: String,
    declarations: Vec<ArtifactDeclaration>,
    command_sha256: String,
}
/// An exact bounded invocation and its owned declarations. Acceptance is not
/// authorization: use `reject_qualified` for the unavailable qualified path.
/// The separately named development observer never promises supported execution.
pub struct RunRequest {
    serial: SerialRequest,
    facts: Facts,
}
impl RunRequest {
    pub fn new(
        serial: SerialRequest,
        scope: RequestedScope,
        coordinator_id: String,
        declarations: Vec<ArtifactDeclaration>,
    ) -> Result<Self> {
        serial
            .process
            .validate()
            .map_err(|error| CoordinatorError::new("request_process_invalid", error))?;
        SerialLedger::new(serial.identity.clone(), serial.contract.clone())
            .map_err(|error| CoordinatorError::new("request_serial_invalid", error))?;
        require(
            id(&coordinator_id) && coordinator_id != serial.identity.producer_id,
            "request_coordinator_identity_invalid",
        )?;
        require(
            serial.process.executable.as_bytes().len() <= 4096
                && serial.process.cwd.is_absolute()
                && serial.process.cwd.as_os_str().as_bytes().len() <= 4096
                && serial.process.args.len() <= 16_384,
            "request_argument_bound_or_relative_cwd",
        )?;
        let mut bytes = 0usize;
        for argument in &serial.process.args {
            bytes += argument.as_bytes().len();
            require(
                argument.as_bytes().len() <= 65_536 && bytes <= 1024 * 1024,
                "request_argument_byte_bound",
            )?;
        }
        require(
            serial.stream_budget.bytes > 0
                && serial.stream_budget.bytes <= MAX_STREAM_BYTES
                && serial.stream_budget.events > 0
                && serial.stream_budget.events <= MAX_EVENTS,
            "request_stream_budget_invalid",
        )?;
        require(
            !serial.drain_allowance.is_zero()
                && serial.drain_allowance <= Duration::from_secs(30)
                && serial
                    .process
                    .timeout
                    .checked_add(serial.process.cleanup_timeout)
                    .and_then(|value| value.checked_add(serial.drain_allowance))
                    .is_some_and(|value| value <= Duration::from_secs(3600)),
            "request_lifetime_invalid",
        )?;
        let declared: HashSet<_> = declarations
            .iter()
            .map(|value| value.artifact_id.as_str())
            .collect();
        for declaration in &declarations {
            declaration.validate().map_err(|error| {
                CoordinatorError::new("request_report_declaration_invalid", error)
            })?;
        }
        require(
            declarations.len() <= 1024
                && declared.len() == declarations.len()
                && declared
                    == serial
                        .contract
                        .declared_artifact_ids
                        .iter()
                        .map(String::as_str)
                        .collect(),
            "request_artifact_domain_mismatch",
        )?;
        let facts = Facts {
            process: serial.process.clone(),
            identity: serial.identity.clone(),
            contract: serial.contract.clone(),
            scope,
            coordinator_id,
            declarations,
            command_sha256: command_digest(&serial.process),
        };
        Ok(Self { serial, facts })
    }
    /// Versioned identity of only executable/cwd/raw argv, not a complete request,
    /// environment, declared artifacts or generation digest. Raw secrets are not
    /// exported; an unkeyed command digest is not secret-safe provenance either.
    pub fn command_sha256(&self) -> &str {
        &self.facts.command_sha256
    }
    pub fn process(&self) -> &ProcessRequest {
        &self.facts.process
    }

    /// No qualified launch implementation exists yet. Consumes the request and
    /// returns an actual prelaunch rejection; no child, store or interpreter probe.
    pub fn reject_qualified(self) -> Result<RejectedRun> {
        let mut events = Records::new(&self.facts);
        events.push("request_accepted", request_payload(&self.facts))?;
        let message = "qualified launch unavailable: complete environment/startup handoff, current immutable declared-input generation and supported-profile evidence remain open";
        events.push("request_rejected", json!({"outcome":"unsupported_profile","code":"qualified_prerequisites_unavailable","message":message}))?;
        let record = base_result(
            &self.facts,
            &not_started_accounting(),
            &PhaseCounts::default(),
        );
        let mut record = record;
        record["outcome"] = json!("unsupported_profile");
        record["cli_exit_code"] = json!(4);
        record["errors"] = json!([error_record(
            "coordinator",
            "unsupported",
            "qualified_prerequisites_unavailable",
            message
        )]);
        record["artifacts"] = json!(
            self.facts
                .declarations
                .iter()
                .map(pending_artifact)
                .collect::<Vec<_>>()
        );
        record["artifacts_verified"] =
            json!(self.facts.declarations.iter().all(|value| !value.required));
        record["terminal_sequences"]["coordinator"] = json!(events.last_sequence());
        let record = FinalRecord::new(record)?;
        Ok(RejectedRun {
            facts: self.facts,
            record,
            records: events.values,
        })
    }

    /// Explicitly requested development observation, not a fallback for rejected
    /// qualified work. Passes the supplied invocation through unchanged once.
    /// No bootstrap/environment injection, plugin suppression or replay occurs.
    pub fn observe_development(
        self,
        retention: RetentionTarget,
        cancelled: &AtomicI32,
    ) -> Result<ObservedRun> {
        let start = Instant::now();
        let mut records = Records::new(&self.facts);
        records.push("request_accepted", request_payload(&self.facts))?;
        for declaration in &self.facts.declarations {
            records.push("artifact_declared", json!({"artifact_id":declaration.artifact_id,"artifact_kind":"report","required":declaration.required}))?;
        }
        let deadline = retention.budget.deadline;
        let store = ArtifactStore::create(
            &self.facts.process.cwd,
            &retention.parent,
            &retention.private_name,
            self.facts.declarations.clone(),
            retention.budget,
        )
        .map_err(|error| CoordinatorError::new("request_artifact_setup_failed", error))?;
        let session = observe_serial(self.serial, cancelled)
            .map_err(|error| CoordinatorError::new("request_session_setup_failed", error))?;
        Ok(ObservedRun {
            facts: self.facts,
            session,
            store,
            records,
            deadline,
            start,
            artifact_diagnostics: Vec::new(),
        })
    }
}

pub struct RetentionTarget {
    pub parent: PathBuf,
    pub private_name: String,
    pub budget: RetentionBudget,
}
pub struct RejectedRun {
    facts: Facts,
    record: FinalRecord,
    records: Vec<Value>,
}
impl RejectedRun {
    pub fn record(&self) -> &FinalRecord {
        &self.record
    }
    pub fn coordinator_records(&self) -> &[Value] {
        &self.records
    }
    pub fn command_sha256(&self) -> &str {
        &self.facts.command_sha256
    }
}

pub struct ObservedRun {
    facts: Facts,
    session: SessionObservation,
    store: ArtifactStore,
    records: Records,
    deadline: Instant,
    start: Instant,
    artifact_diagnostics: Vec<ArtifactDiagnostic>,
}
#[derive(Debug)]
pub struct ArtifactDiagnostic {
    artifact_id: String,
    code: &'static str,
    detail: String,
}
impl ArtifactDiagnostic {
    pub fn artifact_id(&self) -> &str {
        &self.artifact_id
    }
    pub fn code(&self) -> &'static str {
        self.code
    }
    pub fn detail(&self) -> &str {
        &self.detail
    }
}
impl ObservedRun {
    pub fn session(&self) -> &SessionObservation {
        &self.session
    }
    pub fn command_sha256(&self) -> &str {
        &self.facts.command_sha256
    }
    pub fn finish(self) -> FinishedRun {
        self.finish_with_generation(None)
    }
    /// The tree must name this request's cwd. It remains uncertain/live-tree,
    /// never complete environment identity or immutable/current source proof.
    pub fn finish_with_live_tree(self, tree: TreeObservation) -> FinishedRun {
        self.finish_with_generation(Some(tree))
    }
    fn finish_with_generation(mut self, tree: Option<TreeObservation>) -> FinishedRun {
        let record = self.finalize(tree.as_ref());
        let elapsed_ns = self.start.elapsed().as_nanos();
        FinishedRun {
            facts: self.facts,
            session: self.session,
            store: self.store,
            records: self.records.values,
            record,
            elapsed_ns,
            artifact_diagnostics: self.artifact_diagnostics,
        }
    }
    fn finalize(&mut self, tree: Option<&TreeObservation>) -> Result<FinalRecord> {
        // A lost observer return is not an empty inventory. Revision 1's final
        // schema cannot represent unknown counters: retain the owned observation
        // and return unavailable rather than invent zeros or weaken the schema.
        let snapshot = required_snapshot(self.session.snapshot())?;
        require(
            tree.is_none_or(|value| value.root() == self.facts.process.cwd),
            "final_tree_request_mismatch",
        )?;
        let process = self.session.process();
        if let Some(status) = &process.leader_status {
            let (code, signal, core_dumped) = raw_status(Some(status));
            self.records.push("worker_exited", json!({"exit_code":code,"signal":signal,"core_dumped":core_dumped,"reaped":process.cleanup == Cleanup::Complete}))?;
        }
        let cleanup = cleanup_record(process);
        self.records.push("cleanup_finished", cleanup.clone())?;
        let mut errors = snapshot
            .session_errors
            .iter()
            .map(|value| {
                error_record(
                    "bridge",
                    match value.category {
                        SessionErrorCategory::Internal => "internal",
                        SessionErrorCategory::Usage => "usage",
                        SessionErrorCategory::Infrastructure => "infrastructure",
                        SessionErrorCategory::Unsupported => "unsupported",
                    },
                    &value.code,
                    &value.message,
                )
            })
            .collect::<Vec<_>>();
        let (raw_code, raw_signal, _) = raw_status(process.leader_status.as_ref());
        let mut infrastructure_failed =
            self.session.outcome() == &SessionOutcome::InfrastructureFailed;
        if Instant::now() >= self.deadline {
            infrastructure_failed = true;
            errors.push(error_record("coordinator", "infrastructure", "coordinator_finalization_deadline_expired", "the original finite request/artifact finalization window expired; it was not reset"));
        }
        if self.session.outcome() == &SessionOutcome::InfrastructureFailed {
            errors.push(error_record("coordinator", "infrastructure", "native_session_failed", "owned process/channel/cleanup checks failed; raw causes remain in the session observation"));
        }
        // Only the live owned reader's readiness claims are eligible. No caller
        // can substitute an oracle hash or an unrelated run's store/receipt.
        if let Ok(writers) = WritersStopped::after_cleanup(process) {
            for claim in &snapshot.artifact_ready_claims {
                let declaration = self
                    .facts
                    .declarations
                    .iter()
                    .find(|value| value.artifact_id == claim.artifact_id)
                    .ok_or_else(|| {
                        CoordinatorError::new("final_undeclared_ready_claim", &claim.artifact_id)
                    })?;
                let expectation = match &declaration.junit_policy {
                    Some(policy) => {
                        let result = self
                            .session
                            .normal_snapshot()
                            .ok_or_else(|| {
                                "no normal live session context; partial content retention only"
                                    .to_owned()
                            })
                            .and_then(|snapshot| {
                                JunitExpectation::from_snapshot(
                                    policy.clone(),
                                    snapshot,
                                    self.deadline,
                                )
                                .map_err(|error| error.to_string())
                            });
                        match result {
                            Ok(expectation) => Some(expectation),
                            Err(detail) => {
                                self.artifact_diagnostics.push(ArtifactDiagnostic {
                                    artifact_id: declaration.artifact_id.clone(),
                                    code: "junit_context_unavailable",
                                    detail,
                                });
                                None
                            }
                        }
                    }
                    None => None,
                };
                let result = match &expectation {
                    Some(expectation) => self.store.commit_with_junit(claim, &writers, expectation),
                    None => self.store.commit(claim, &writers),
                };
                match result {
                    Ok(artifact)=>self.records.push("artifact_committed", json!({"artifact_id":artifact.artifact_id(),"sha256":artifact.sha256(),"bytes":artifact.bytes(),"complete":artifact.complete(),"verified":true}))?,
                    Err(error)=>self.records.push("artifact_failed", json!({"artifact_id":claim.artifact_id,"code":error.code(),"message":error.to_string()}))?,
                }
            }
        }
        let mut artifacts = Vec::new();
        for declaration in &self.facts.declarations {
            let state = self
                .store
                .state(&declaration.artifact_id)
                .expect("store owns exact request declarations");
            let artifact = match state {
                ArtifactState::Pending => pending_artifact(declaration),
                ArtifactState::Committed(value) => {
                    json!({"artifact_id":value.artifact_id(),"required":declaration.required,"status":"committed","sha256":value.sha256(),"bytes":value.bytes(),"complete":value.complete(),"verified":true,"failure":null})
                }
                ArtifactState::Failed {
                    code,
                    publication_may_exist,
                } => {
                    if declaration.required {
                        infrastructure_failed = true;
                    }
                    json!({"artifact_id":declaration.artifact_id,"required":declaration.required,"status":"failed","sha256":null,"bytes":null,"complete":false,"verified":false,
                        "failure":{"code":code,"message":format!("native publication failed; publication_may_exist={publication_may_exist}; no file-based recovery or retry")}})
                }
            };
            artifacts.push(artifact);
        }
        let accounting_verified = snapshot.stream_consistent_so_far
            && snapshot.terminal.is_some()
            && self.session.channel().clean_eof
            && self.session.channel().issue.is_none();
        let inventory_complete = snapshot.collection.as_ref().is_some_and(|value| {
            value.status == CollectionStatus::Complete && value.inventory_complete
        });
        let work_complete = accounting_verified
            && inventory_complete
            && snapshot.incomplete_ordinals.is_empty()
            && (self.facts.contract.mode == RequestMode::CollectOnly
                || snapshot.accounting.not_run_count == 0)
            && self.facts.scope == RequestedScope::Explicit;
        let reporting_complete = snapshot
            .terminal
            .as_ref()
            .is_some_and(|value| value.reporting_complete);
        let artifacts_verified = self.store.required_artifacts_satisfied();
        let generation = match tree {
            Some(tree) => {
                json!({"status":"uncertain","assurance":"live_tree","identity_sha256":tree.manifest_sha256(),"declared_inputs_complete":false})
            }
            None => unverified_generation(),
        };
        if tree.is_some() {
            self.records
                .push("generation_checked", generation.clone())?;
        }
        let (stop, interruption_signal) = match process.termination {
            Termination::Timeout => ("timeout", None),
            Termination::Interrupted { signal } => ("interrupted", Some(signal)),
            _ => ("none", None),
        };
        let (outcome, cli_exit_code) = if self.session.outcome() == &SessionOutcome::LaunchFailed {
            ("launch_error", 3)
        } else if infrastructure_failed {
            ("infrastructure_error", 3)
        } else if tree.is_some() && process.pid.is_some() {
            ("generation_invalid", 3)
        } else {
            match self.session.outcome() {
                SessionOutcome::Timeout => ("timeout", 3),
                SessionOutcome::Interrupted { .. } => ("interrupted", 2),
                SessionOutcome::BackendTerminated => (
                    "backend_terminated",
                    raw_signal.map_or(3, |signal| 128 + signal),
                ),
                _ => {
                    infrastructure_failed = true;
                    errors.push(error_record("coordinator","infrastructure","completion_prerequisites_unverified",
                    "complete environment/startup, effective requested scope and current immutable generation are not certified by development observation"));
                    ("infrastructure_error", 3)
                }
            }
        };
        if !artifacts_verified
            && matches!(
                self.session.outcome(),
                SessionOutcome::NormalExitAccounted { .. }
            )
        {
            errors.push(error_record("coordinator","infrastructure","required_artifacts_incomplete","ready/hash agreement or complete-looking source files do not satisfy missing or unknown required artifact completeness"));
        }
        require(errors.len() <= 1024, "final_error_summary_bound")?;
        for error in &errors {
            require(
                error["message"]
                    .as_str()
                    .is_some_and(|value| value.chars().count() <= 65536),
                "final_error_text_bound",
            )?;
        }
        let mut result = base_result(&self.facts, &snapshot.accounting, &snapshot.phase_counts);
        result["outcome"] = json!(outcome);
        result["cli_exit_code"] = json!(cli_exit_code);
        result["backend_exit_code"] = json!(raw_code);
        result["backend_signal"] = json!(raw_signal);
        result["stop_cause"] = json!(stop);
        result["interruption_signal"] = json!(interruption_signal);
        result["collection_status"] =
            json!(
                match snapshot.collection.as_ref().map(|value| value.status) {
                    Some(CollectionStatus::Complete) => "complete",
                    Some(CollectionStatus::Failed) => "failed",
                    Some(CollectionStatus::Interrupted) => "interrupted",
                    None if process.pid.is_none() => "not_started",
                    None => "unknown",
                }
            );
        result["inventory_complete"] = json!(inventory_complete);
        result["incomplete_ordinals"] = json!(snapshot.incomplete_ordinals);
        result["collection_error_ids"] = json!(
            snapshot
                .collection_errors
                .iter()
                .map(|value| value.report_id)
                .collect::<Vec<_>>()
        );
        result["errors"] = json!(errors);
        result["artifacts"] = json!(artifacts);
        result["accounting_verified"] = json!(accounting_verified);
        result["work_complete"] = json!(work_complete);
        result["reporting_complete"] = json!(reporting_complete);
        result["artifacts_verified"] = json!(artifacts_verified);
        result["infrastructure_status"] =
            json!(if infrastructure_failed || outcome == "launch_error" {
                "failed"
            } else if process.pid.is_some() {
                "ok"
            } else {
                "not_started"
            });
        result["cleanup"] = cleanup;
        result["generation"] = generation;
        result["terminal_sequences"] = json!({"coordinator":self.records.last_sequence(),"bridge":self.session.channel().confirmed_frames.and_then(|value|value.checked_sub(1))});
        FinalRecord::new(result)
    }
}

pub struct FinishedRun {
    facts: Facts,
    session: SessionObservation,
    store: ArtifactStore,
    records: Vec<Value>,
    record: Result<FinalRecord>,
    elapsed_ns: u128,
    artifact_diagnostics: Vec<ArtifactDiagnostic>,
}
impl FinishedRun {
    pub fn record(&self) -> std::result::Result<&FinalRecord, &CoordinatorError> {
        self.record.as_ref()
    }
    pub fn session(&self) -> &SessionObservation {
        &self.session
    }
    pub fn artifact_state(&self, id: &str) -> Option<&ArtifactState> {
        self.store.state(id)
    }
    /// Coordinator-origin records only. No environment_resolved is invented.
    /// These are not a complete qualified merged event stream or bridge archive.
    pub fn coordinator_records(&self) -> &[Value] {
        &self.records
    }
    pub fn command_sha256(&self) -> &str {
        &self.facts.command_sha256
    }
    pub fn elapsed_ns(&self) -> u128 {
        self.elapsed_ns
    }
    pub fn artifact_diagnostics(&self) -> &[ArtifactDiagnostic] {
        &self.artifact_diagnostics
    }
}
/// Read-only revision-1 failure record, not a deserializable proof token. This
/// component has no positive environment/immutable-generation authority and so
/// cannot construct backend_completed or current_full_success/zero CLI results.
#[derive(Debug)]
pub struct FinalRecord {
    value: Value,
}
impl FinalRecord {
    fn new(value: Value) -> Result<Self> {
        require(
            value["current_full_success"] == false
                && value["environment_verified"] == false
                && value["outcome"] != "backend_completed"
                && value["cli_exit_code"]
                    .as_u64()
                    .is_some_and(|value| value > 0 && value <= 255),
            "final_unqualified_record_cannot_be_success",
        )?;
        let bytes = serde_json::to_vec(&value)
            .map_err(|error| CoordinatorError::new("final_serialization", error))?;
        require(bytes.len() <= 16 * 1024 * 1024, "final_record_byte_bound")?;
        Ok(Self { value })
    }
    pub fn as_json(&self) -> &Value {
        &self.value
    }
    pub fn cli_exit_code(&self) -> u8 {
        self.value["cli_exit_code"]
            .as_u64()
            .expect("checked bounded code") as u8
    }
}

struct Records {
    identity: ChannelIdentity,
    producer_id: String,
    values: Vec<Value>,
    bytes: usize,
}
impl Records {
    fn new(facts: &Facts) -> Self {
        Self {
            identity: facts.identity.clone(),
            producer_id: facts.coordinator_id.clone(),
            values: vec![],
            bytes: 0,
        }
    }
    fn push(&mut self, kind: &str, payload: Value) -> Result<()> {
        let value = json!({"protocol_version":0,"contract_revision":1,"request_id":self.identity.request_id,"run_id":self.identity.run_id,
            "generation_id":self.identity.generation_id,"session_id":self.identity.session_id,"producer_id":self.producer_id,"producer_role":"coordinator",
            "sequence":self.values.len(),"kind":kind,"payload":payload});
        let bytes = serde_json::to_vec(&value)
            .map_err(|error| CoordinatorError::new("coordinator_record_serialization", error))?
            .len();
        require(
            bytes <= 1024 * 1024
                && self.values.len() < 4096
                && self.bytes + bytes + 4 <= 16 * 1024 * 1024,
            "coordinator_record_bound",
        )?;
        self.bytes += bytes + 4;
        self.values.push(value);
        Ok(())
    }
    fn last_sequence(&self) -> Option<u64> {
        self.values.len().checked_sub(1).map(|value| value as u64)
    }
}
fn command_digest(process: &ProcessRequest) -> String {
    let mut digest = Sha256::new();
    digest.update(b"pt-command-bytes-v1\0");
    for raw in [
        process.executable.as_bytes(),
        process.cwd.as_os_str().as_bytes(),
    ] {
        field(&mut digest, raw);
    }
    digest.update((process.args.len() as u64).to_be_bytes());
    for argument in &process.args {
        field(&mut digest, argument.as_bytes());
    }
    digest
        .finalize()
        .iter()
        .map(|value| format!("{value:02x}"))
        .collect()
}
fn field(digest: &mut Sha256, raw: &[u8]) {
    digest.update((raw.len() as u64).to_be_bytes());
    digest.update(raw);
}
fn required_snapshot(snapshot: Option<&BridgeSnapshot>) -> Result<&BridgeSnapshot> {
    snapshot.ok_or_else(|| {
        CoordinatorError::new(
            "final_accounting_unknown",
            "lost reader return cannot be reconstructed from artifacts",
        )
    })
}
fn not_started_accounting() -> Accounting {
    Accounting {
        collected_count: 0,
        selected_count: 0,
        deselected_count: 0,
        executed_count: 0,
        completed_count: 0,
        not_run_count: 0,
        attempts_started: 0,
        attempts_completed: 0,
    }
}
fn mode_text(mode: RequestMode) -> &'static str {
    match mode {
        RequestMode::Run => "run",
        RequestMode::CollectOnly => "collect_only",
    }
}
fn request_payload(facts: &Facts) -> Value {
    json!({"mode":mode_text(facts.contract.mode),"scope":facts.scope.text(),"invocation_profile":match facts.contract.invocation_profile {
        InvocationProfile::PytestModule=>"pytest_module",InvocationProfile::PytestConsole=>"pytest_console"},
        "required_artifact_ids":facts.declarations.iter().filter(|value|value.required).map(|value|&value.artifact_id).collect::<Vec<_>>(),"retry_policy":"disabled","retry_plugin":null,"max_attempts":1})
}
fn error_record(role: &str, category: &str, code: &str, message: &str) -> Value {
    json!({"producer_role":role,"category":category,"code":code,"message":message})
}
fn pending_artifact(value: &ArtifactDeclaration) -> Value {
    json!({"artifact_id":value.artifact_id,"required":value.required,"status":"pending","sha256":null,"bytes":null,"complete":false,"verified":false,"failure":null})
}
fn unverified_generation() -> Value {
    json!({"status":"unverified","assurance":"unverified","identity_sha256":null,"declared_inputs_complete":false})
}
fn raw_status(status: Option<&LeaderStatus>) -> (Option<i32>, Option<i32>, bool) {
    match status {
        Some(LeaderStatus::Exited { code }) => (Some(*code), None, false),
        Some(LeaderStatus::Signaled {
            signal,
            core_dumped,
        }) => (None, Some(*signal), *core_dumped),
        None => (None, None, false),
    }
}
fn cleanup_record(process: &pt_process::ProcessReport) -> Value {
    match &process.cleanup {
        Cleanup::Complete => {
            json!({"status":"complete","leader_reaped":true,"live_members":0,"reason":null})
        }
        Cleanup::NotLaunched => {
            json!({"status":"not_started","leader_reaped":false,"live_members":null,"reason":null})
        }
        Cleanup::Uncertain { detail } => {
            json!({"status":"uncertain","leader_reaped":false,"live_members":null,"reason":detail})
        }
    }
}
fn base_result(facts: &Facts, accounting: &Accounting, phases: &PhaseCounts) -> Value {
    json!({"protocol_version":0,"contract_revision":1,"request_id":facts.identity.request_id,"run_id":facts.identity.run_id,"generation_id":facts.identity.generation_id,"session_id":facts.identity.session_id,
        "mode":mode_text(facts.contract.mode),"scope":facts.scope.text(),"outcome":"infrastructure_error","cli_exit_code":3,"backend_exit_code":null,"backend_signal":null,"stop_cause":"none","interruption_signal":null,
        "collection_status":"not_started","inventory_complete":false,"accounting":{
            "collected_count":accounting.collected_count,"selected_count":accounting.selected_count,"deselected_count":accounting.deselected_count,"executed_count":accounting.executed_count,
            "completed_count":accounting.completed_count,"not_run_count":accounting.not_run_count,"attempts_started":accounting.attempts_started,"attempts_completed":accounting.attempts_completed},
        "phase_counts":{"setup":{"passed":phases.setup.passed,"failed":phases.setup.failed,"skipped":phases.setup.skipped},"call":{"passed":phases.call.passed,"failed":phases.call.failed,"skipped":phases.call.skipped},"teardown":{"passed":phases.teardown.passed,"failed":phases.teardown.failed,"skipped":phases.teardown.skipped}},
        "incomplete_ordinals":[],"collection_error_ids":[],"errors":[],"required_artifact_ids":facts.declarations.iter().filter(|value|value.required).map(|value|&value.artifact_id).collect::<Vec<_>>(),
        "artifacts":[],"capability_decisions":[],"accounting_verified":false,"work_complete":false,"reporting_complete":false,"artifacts_verified":false,"environment_verified":false,
        "infrastructure_status":"not_started","cleanup":{"status":"not_started","leader_reaped":false,"live_members":null,"reason":null},"generation":unverified_generation(),
        "terminal_sequences":{"coordinator":null,"bridge":null},"current_full_success":false})
}

#[cfg(test)]
mod tests;
