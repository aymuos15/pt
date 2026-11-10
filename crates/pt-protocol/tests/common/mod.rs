#![allow(dead_code)]

use pt_protocol::{ChannelIdentity, InvocationProfile, RequestMode, SerialContract};
use serde_json::{Value, json};

pub fn identity() -> ChannelIdentity {
    ChannelIdentity {
        request_id: "request-1".into(),
        run_id: "run-1".into(),
        generation_id: "generation-1".into(),
        session_id: "session-1".into(),
        producer_id: "bridge-1".into(),
    }
}

pub fn contract() -> SerialContract {
    SerialContract {
        invocation_profile: InvocationProfile::PytestModule,
        mode: RequestMode::Run,
        max_items: 256,
        max_collection_reports: 1024,
        max_nodeid_bytes: 1024 * 1024,
        declared_artifact_ids: vec!["stdout-1".into(), "exception-1".into()],
    }
}

pub fn fixtures() -> Vec<Value> {
    serde_json::from_str(include_str!("../fixtures/bridge-payloads.json")).unwrap()
}

pub fn envelope(sequence: u64, kind: &str, payload: Value) -> Value {
    let id = identity();
    json!({"protocol_version":0,"contract_revision":1,"request_id":id.request_id,"run_id":id.run_id,
        "generation_id":id.generation_id,"session_id":id.session_id,"producer_id":id.producer_id,
        "producer_role":"bridge","sequence":sequence,"kind":kind,"payload":payload})
}

pub fn event(sequence: u64, kind: &str, payload: Value) -> Vec<u8> {
    serde_json::to_vec(&envelope(sequence, kind, payload)).unwrap()
}

pub fn frame(raw: &[u8]) -> Vec<u8> {
    let mut wire = (raw.len() as u32).to_be_bytes().to_vec();
    wire.extend_from_slice(raw);
    wire
}

pub fn handshake() -> Value {
    fixtures()[0]["payload"].clone()
}

pub fn phase(ordinal: u64, phase: &str, outcome: &str) -> Value {
    json!({"ordinal":ordinal,"attempt":0,"phase":phase,"outcome":outcome,"reason":null,
        "was_xfail":null,"strict_xpass":false,"duration_ns":7,"artifact_ids":[]})
}

/// Deliberately independent test producer: terminal arithmetic is derived from
/// test-owned event descriptions, never from the product ledger snapshot.
#[derive(Clone)]
pub struct Trace {
    pub rows: Vec<(String, Value)>,
}

impl Trace {
    pub fn new() -> Self {
        Self {
            rows: vec![("session_started".into(), handshake())],
        }
    }
    pub fn push(&mut self, kind: &str, payload: Value) {
        self.rows.push((kind.into(), payload));
    }
    pub fn collection(&mut self, nodeids: &[&str], selected: &[u64], status: &str) {
        self.push("collection_started", json!({}));
        for (ordinal, nodeid) in nodeids.iter().enumerate() {
            self.push("item_collected", json!({"ordinal":ordinal,"nodeid":nodeid}));
        }
        self.push("items_selected", json!({"chunk":0,"ordinals":selected}));
        let deselected = (0..nodeids.len() as u64)
            .filter(|ordinal| !selected.contains(ordinal))
            .collect::<Vec<_>>();
        self.push(
            "items_deselected",
            json!({"chunk":0,"ordinals":deselected,"reason":null}),
        );
        self.push("collection_finished", json!({"status":status,"inventory_complete":status=="complete",
            "collected_count":nodeids.len(),"selected_count":selected.len(),"deselected_count":deselected.len()}));
    }
    pub fn attempt(&mut self, ordinal: u64, setup: &str, call: &str, teardown: &str) {
        self.push("item_started", json!({"ordinal":ordinal,"attempt":0}));
        self.push("phase_report", phase(ordinal, "setup", setup));
        if setup == "passed" {
            self.push("phase_report", phase(ordinal, "call", call));
        }
        self.push("phase_report", phase(ordinal, "teardown", teardown));
        self.push(
            "attempt_finished",
            json!({"ordinal":ordinal,"attempt":0,"disposition":"completed","reason":null}),
        );
    }
    pub fn terminal(&mut self, code: u8, termination: &str) {
        let mut selected = Vec::new();
        let (mut collected, mut deselected, mut started, mut completed, mut not_run) =
            (0, 0, 0, 0, 0);
        let mut finished = std::collections::HashSet::new();
        let mut explained = std::collections::HashSet::new();
        let mut phases = json!({"setup":{"passed":0,"failed":0,"skipped":0},"call":{"passed":0,"failed":0,"skipped":0},"teardown":{"passed":0,"failed":0,"skipped":0}});
        for (kind, value) in &self.rows {
            match kind.as_str() {
                "item_collected" => collected += 1,
                "items_selected" => selected.extend(
                    value["ordinals"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|value| value.as_u64().unwrap()),
                ),
                "items_deselected" => deselected += value["ordinals"].as_array().unwrap().len(),
                "item_started" => started += 1,
                "attempt_finished" if value["disposition"] == "completed" => {
                    completed += 1;
                    finished.insert(value["ordinal"].as_u64().unwrap());
                }
                "item_not_run" => {
                    not_run += 1;
                    explained.insert(value["ordinal"].as_u64().unwrap());
                }
                "phase_report" => {
                    let cell = &mut phases[value["phase"].as_str().unwrap()]
                        [value["outcome"].as_str().unwrap()];
                    *cell = json!(cell.as_u64().unwrap() + 1);
                }
                _ => {}
            }
        }
        let incomplete = selected
            .iter()
            .filter(|ordinal| !finished.contains(*ordinal) && !explained.contains(*ordinal))
            .copied()
            .collect::<Vec<_>>();
        self.push("session_terminated", json!({"termination":termination,"backend_exit_code":code,"reporting_complete":true,
            "accounting":{"collected_count":collected,"selected_count":selected.len(),"deselected_count":deselected,"executed_count":started,
                "completed_count":completed,"not_run_count":not_run,"attempts_started":started,"attempts_completed":completed},
            "phase_counts":phases,"incomplete_ordinals":incomplete}));
    }
    pub fn raw(&self) -> Vec<Vec<u8>> {
        self.rows
            .iter()
            .enumerate()
            .map(|(seq, (kind, payload))| event(seq as u64, kind, payload.clone()))
            .collect()
    }
}
