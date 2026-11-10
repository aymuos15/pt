use crate::{MAX_EVENTS, ProtocolError, precheck};
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::value::RawValue;
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChannelIdentity {
    pub request_id: String,
    pub run_id: String,
    pub generation_id: String,
    pub session_id: String,
    pub producer_id: String,
}

fn id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

impl ChannelIdentity {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        if [
            &self.request_id,
            &self.run_id,
            &self.generation_id,
            &self.session_id,
            &self.producer_id,
        ]
        .iter()
        .all(|value| id(value))
        {
            Ok(())
        } else {
            Err(ProtocolError::new("invalid channel-bound opaque identity"))
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InvocationProfile {
    PytestModule,
    PytestConsole,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Setup,
    Call,
    Teardown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Passed,
    Failed,
    Skipped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CollectionStatus {
    Complete,
    Failed,
    Interrupted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Completed,
    Retry,
    Interrupted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NotRunReason {
    FailFast,
    CollectionFailed,
    CollectOnly,
    Interrupted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WarningWhen {
    Configure,
    Collect,
    Setup,
    Call,
    Teardown,
    Finalize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionErrorCategory {
    Internal,
    Usage,
    Infrastructure,
    Unsupported,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionTermination {
    BackendExited,
    InfrastructureFailed,
    Interrupted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputStream {
    Stdout,
    Stderr,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Handshake {
    pub python_version: String,
    pub pytest_version: String,
    pub bridge_version: String,
    pub invocation_profile: InvocationProfile,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CollectionReport {
    pub report_id: u64,
    pub nodeid: String,
    pub outcome: Outcome,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CollectionError {
    pub report_id: u64,
    pub nodeid: String,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Item {
    pub ordinal: u64,
    pub nodeid: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub chunk: u64,
    pub ordinals: Vec<u64>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Deselection {
    pub chunk: u64,
    pub ordinals: Vec<u64>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CollectionFinished {
    pub status: CollectionStatus,
    pub inventory_complete: bool,
    pub collected_count: u64,
    pub selected_count: u64,
    pub deselected_count: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttemptKey {
    pub ordinal: u64,
    pub attempt: u8,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PhaseReport {
    pub ordinal: u64,
    pub attempt: u8,
    pub phase: Phase,
    pub outcome: Outcome,
    pub reason: Option<String>,
    pub was_xfail: Option<String>,
    pub strict_xpass: bool,
    pub duration_ns: Option<u64>,
    pub artifact_ids: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttemptFinished {
    pub ordinal: u64,
    pub attempt: u8,
    pub disposition: Disposition,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ItemNotRun {
    pub ordinal: u64,
    pub reason: NotRunReason,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Warning {
    pub ordinal: Option<u64>,
    pub category: String,
    pub message: String,
    pub filename: Option<String>,
    pub line: Option<u64>,
    pub when: WarningWhen,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OutputReference {
    pub artifact_id: String,
    pub stream: OutputStream,
    pub ordinal: Option<u64>,
    pub attempt: Option<u8>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactReady {
    pub artifact_id: String,
    pub sha256: String,
    pub bytes: u64,
    pub complete: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionError {
    pub category: SessionErrorCategory,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtensionEvent {
    pub extension_id: String,
    pub extension_version: u64,
    pub artifact_id: String,
    pub ordinal: Option<u64>,
    pub attempt: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Accounting {
    pub collected_count: u64,
    pub selected_count: u64,
    pub deselected_count: u64,
    pub executed_count: u64,
    pub completed_count: u64,
    pub not_run_count: u64,
    pub attempts_started: u64,
    pub attempts_completed: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PhaseCount {
    pub passed: u64,
    pub failed: u64,
    pub skipped: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PhaseCounts {
    pub setup: PhaseCount,
    pub call: PhaseCount,
    pub teardown: PhaseCount,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionTerminal {
    pub termination: SessionTermination,
    pub backend_exit_code: Option<u8>,
    pub reporting_complete: bool,
    pub accounting: Accounting,
    pub phase_counts: PhaseCounts,
    pub incomplete_ordinals: Vec<u64>,
}

#[derive(Debug, Clone)]
pub enum BridgePayload {
    SessionStarted(Handshake),
    CollectionStarted,
    CollectionReport(CollectionReport),
    CollectionError(CollectionError),
    ItemCollected(Item),
    ItemsSelected(Selection),
    ItemsDeselected(Deselection),
    CollectionFinished(CollectionFinished),
    ItemStarted(AttemptKey),
    PhaseReport(PhaseReport),
    AttemptFinished(AttemptFinished),
    ItemNotRun(ItemNotRun),
    Warning(Warning),
    OutputReference(OutputReference),
    ArtifactReady(ArtifactReady),
    SessionError(SessionError),
    ExtensionEvent(ExtensionEvent),
    SessionTerminated(SessionTerminal),
}

#[derive(Debug)]
pub struct BridgeMessage {
    pub(crate) source: Option<std::sync::Arc<()>>,
    identity: ChannelIdentity,
    sequence: u64,
    payload: BridgePayload,
    raw: Vec<u8>,
}

impl BridgeMessage {
    pub fn identity(&self) -> &ChannelIdentity {
        &self.identity
    }
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    pub fn payload(&self) -> &BridgePayload {
        &self.payload
    }
    /// Original bounded bytes for explicitly requested raw retention. No
    /// reserialization/normalization or automatic artifact publication occurs.
    pub fn raw_json(&self) -> &[u8] {
        &self.raw
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    protocol_version: u64,
    contract_revision: u64,
    request_id: String,
    run_id: String,
    generation_id: String,
    session_id: String,
    producer_id: String,
    producer_role: String,
    sequence: u64,
    kind: String,
    payload: Box<RawValue>,
}

fn payload<T: DeserializeOwned>(raw: &str, keys: &[&str]) -> Result<T, ProtocolError> {
    // Explicit required-key checking matters: serde Option fields otherwise
    // accept absence as null. Direct typed decoding still rejects duplicate keys.
    let shape: HashMap<String, Box<RawValue>> = serde_json::from_str(raw)
        .map_err(|error| ProtocolError::new(format!("control payload shape: {error}")))?;
    if shape.len() != keys.len() || keys.iter().any(|name| !shape.contains_key(*name)) {
        return Err(ProtocolError::new(
            "unsupported closed payload fields (including missing nullable fields)",
        ));
    }
    serde_json::from_str(raw)
        .map_err(|error| ProtocolError::new(format!("typed control payload: {error}")))
}

fn text(value: &str) -> Result<(), ProtocolError> {
    if value.chars().count() <= 65_536 {
        Ok(())
    } else {
        Err(ProtocolError::new("control text bound exceeded"))
    }
}

fn reason(value: &Option<String>) -> Result<(), ProtocolError> {
    value.as_deref().map_or(Ok(()), text)
}

fn identifier(value: &str) -> Result<(), ProtocolError> {
    if id(value) {
        Ok(())
    } else {
        Err(ProtocolError::new("invalid payload identifier"))
    }
}

fn attempt(value: u8) -> Result<(), ProtocolError> {
    if value < 32 {
        Ok(())
    } else {
        Err(ProtocolError::new("attempt exceeds revision-1 bound"))
    }
}

fn ordinals(values: &[u64], maximum: usize) -> Result<(), ProtocolError> {
    if values.len() <= maximum && values.iter().collect::<HashSet<_>>().len() == values.len() {
        Ok(())
    } else {
        Err(ProtocolError::new("duplicate or excessive ordinal list"))
    }
}

pub fn decode_bridge(
    raw: &[u8],
    expected: &ChannelIdentity,
) -> Result<BridgeMessage, ProtocolError> {
    let original = raw;
    expected.validate()?;
    precheck(raw)?;
    let frame: Envelope = serde_json::from_slice(raw)
        .map_err(|error| ProtocolError::new(format!("closed bridge envelope: {error}")))?;
    let identity = ChannelIdentity {
        request_id: frame.request_id,
        run_id: frame.run_id,
        generation_id: frame.generation_id,
        session_id: frame.session_id,
        producer_id: frame.producer_id,
    };
    if &identity != expected
        || frame.protocol_version != 0
        || frame.contract_revision != 1
        || frame.producer_role != "bridge"
        || frame.sequence >= MAX_EVENTS
    {
        return Err(ProtocolError::new(
            "unsupported envelope version/role/channel identity/sequence",
        ));
    }
    let raw = frame.payload.get();
    let decoded = match frame.kind.as_str() {
        "session_started" => {
            let value: Handshake = payload(
                raw,
                &[
                    "python_version",
                    "pytest_version",
                    "bridge_version",
                    "invocation_profile",
                ],
            )?;
            if value.python_version != "3.12.12"
                || value.pytest_version != "8.4.2"
                || value.bridge_version != "0.0.0"
            {
                return Err(ProtocolError::new(
                    "unsupported bridge/backend handshake versions",
                ));
            }
            BridgePayload::SessionStarted(value)
        }
        "collection_started" => {
            let _: HashMap<String, Box<RawValue>> = payload(raw, &[])?;
            BridgePayload::CollectionStarted
        }
        "collection_report" => {
            let value: CollectionReport =
                payload(raw, &["report_id", "nodeid", "outcome", "reason"])?;
            text(&value.nodeid)?;
            reason(&value.reason)?;
            BridgePayload::CollectionReport(value)
        }
        "collection_error" => {
            let value: CollectionError = payload(raw, &["report_id", "nodeid", "reason"])?;
            text(&value.nodeid)?;
            text(&value.reason)?;
            BridgePayload::CollectionError(value)
        }
        "item_collected" => {
            let value: Item = payload(raw, &["ordinal", "nodeid"])?;
            text(&value.nodeid)?;
            if value.nodeid.is_empty() {
                return Err(ProtocolError::new("empty item node ID"));
            }
            BridgePayload::ItemCollected(value)
        }
        "items_selected" => {
            let value: Selection = payload(raw, &["chunk", "ordinals"])?;
            ordinals(&value.ordinals, 4096)?;
            BridgePayload::ItemsSelected(value)
        }
        "items_deselected" => {
            let value: Deselection = payload(raw, &["chunk", "ordinals", "reason"])?;
            ordinals(&value.ordinals, 4096)?;
            reason(&value.reason)?;
            BridgePayload::ItemsDeselected(value)
        }
        "collection_finished" => {
            let value: CollectionFinished = payload(
                raw,
                &[
                    "status",
                    "inventory_complete",
                    "collected_count",
                    "selected_count",
                    "deselected_count",
                ],
            )?;
            if value.inventory_complete != (value.status == CollectionStatus::Complete) {
                return Err(ProtocolError::new(
                    "collection status/inventory-complete contradiction",
                ));
            }
            BridgePayload::CollectionFinished(value)
        }
        "item_started" => {
            let value: AttemptKey = payload(raw, &["ordinal", "attempt"])?;
            attempt(value.attempt)?;
            BridgePayload::ItemStarted(value)
        }
        "phase_report" => {
            let value: PhaseReport = payload(
                raw,
                &[
                    "ordinal",
                    "attempt",
                    "phase",
                    "outcome",
                    "reason",
                    "was_xfail",
                    "strict_xpass",
                    "duration_ns",
                    "artifact_ids",
                ],
            )?;
            attempt(value.attempt)?;
            reason(&value.reason)?;
            reason(&value.was_xfail)?;
            if value.strict_xpass
                && (value.phase != Phase::Call || value.outcome != Outcome::Failed)
            {
                return Err(ProtocolError::new(
                    "strict XPASS requires a failed call phase",
                ));
            }
            if value.artifact_ids.len() > 1024
                || value.artifact_ids.iter().collect::<HashSet<_>>().len()
                    != value.artifact_ids.len()
            {
                return Err(ProtocolError::new("duplicate or excessive phase artifacts"));
            }
            for value in &value.artifact_ids {
                identifier(value)?;
            }
            BridgePayload::PhaseReport(value)
        }
        "attempt_finished" => {
            let value: AttemptFinished =
                payload(raw, &["ordinal", "attempt", "disposition", "reason"])?;
            attempt(value.attempt)?;
            reason(&value.reason)?;
            BridgePayload::AttemptFinished(value)
        }
        "item_not_run" => BridgePayload::ItemNotRun(payload(raw, &["ordinal", "reason"])?),
        "warning" => {
            let value: Warning = payload(
                raw,
                &["ordinal", "category", "message", "filename", "line", "when"],
            )?;
            text(&value.category)?;
            text(&value.message)?;
            reason(&value.filename)?;
            if value.line == Some(0) {
                return Err(ProtocolError::new("warning line is one-based or null"));
            }
            BridgePayload::Warning(value)
        }
        "output_reference" => {
            let value: OutputReference =
                payload(raw, &["artifact_id", "stream", "ordinal", "attempt"])?;
            identifier(&value.artifact_id)?;
            if value.ordinal.is_some() != value.attempt.is_some() {
                return Err(ProtocolError::new("output attempt identity is incomplete"));
            }
            if let Some(value) = value.attempt {
                attempt(value)?;
            }
            BridgePayload::OutputReference(value)
        }
        "artifact_ready" => {
            let value: ArtifactReady =
                payload(raw, &["artifact_id", "sha256", "bytes", "complete"])?;
            identifier(&value.artifact_id)?;
            if value.sha256.len() != 64
                || !value
                    .sha256
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(ProtocolError::new("invalid artifact SHA-256"));
            }
            BridgePayload::ArtifactReady(value)
        }
        "session_error" => {
            let value: SessionError = payload(raw, &["category", "code", "message"])?;
            identifier(&value.code)?;
            text(&value.message)?;
            BridgePayload::SessionError(value)
        }
        "extension_event" => {
            let value: ExtensionEvent = payload(
                raw,
                &[
                    "extension_id",
                    "extension_version",
                    "artifact_id",
                    "ordinal",
                    "attempt",
                ],
            )?;
            identifier(&value.extension_id)?;
            identifier(&value.artifact_id)?;
            if value.extension_version == 0 {
                return Err(ProtocolError::new("extension version is positive"));
            }
            if let Some(value) = value.attempt {
                attempt(value)?;
            }
            BridgePayload::ExtensionEvent(value)
        }
        "session_terminated" => {
            let value: SessionTerminal = payload(
                raw,
                &[
                    "termination",
                    "backend_exit_code",
                    "reporting_complete",
                    "accounting",
                    "phase_counts",
                    "incomplete_ordinals",
                ],
            )?;
            ordinals(&value.incomplete_ordinals, 100_000)?;
            if value.termination == SessionTermination::BackendExited
                && value.backend_exit_code.is_none()
            {
                return Err(ProtocolError::new(
                    "normal bridge terminal requires backend exit",
                ));
            }
            BridgePayload::SessionTerminated(value)
        }
        _ => {
            return Err(ProtocolError::new(
                "unknown or coordinator-owned kind on bridge channel",
            ));
        }
    };
    Ok(BridgeMessage {
        source: None,
        identity,
        sequence: frame.sequence,
        payload: decoded,
        raw: original.to_vec(),
    })
}
