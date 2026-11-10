mod common;

use common::*;
use pt_protocol::{
    BridgePayload, MAX_DEPTH, MAX_EVENTS, MAX_FRAME_BYTES, MAX_NODES, decode_bridge,
};
use serde_json::{Value, json};
use std::collections::HashSet;

#[test]
fn all_eighteen_bridge_shapes_decode_and_preserve_original_json_bytes() {
    let rows = fixtures();
    assert_eq!(rows.len(), 18);
    assert_eq!(
        rows.iter()
            .map(|value| value["kind"].as_str().unwrap())
            .collect::<HashSet<_>>()
            .len(),
        18
    );
    for value in rows {
        let raw = serde_json::to_vec_pretty(&envelope(
            0,
            value["kind"].as_str().unwrap(),
            value["payload"].clone(),
        ))
        .unwrap();
        let message = decode_bridge(&raw, &identity()).unwrap();
        assert_eq!(message.raw_json(), raw);
        assert_eq!(message.identity(), &identity());
        assert_eq!(message.sequence(), 0);
    }
    let warning = decode_bridge(
        &event(0, "warning", fixtures()[12]["payload"].clone()),
        &identity(),
    )
    .unwrap();
    assert!(
        matches!(warning.payload(), BridgePayload::Warning(value) if value.message.ends_with("λ 🐍"))
    );
}

#[test]
fn every_required_field_including_nullable_fields_is_required_and_all_shapes_are_closed() {
    for fixture in fixtures() {
        let original = envelope(
            0,
            fixture["kind"].as_str().unwrap(),
            fixture["payload"].clone(),
        );
        for key in original.as_object().unwrap().keys() {
            let mut value = original.clone();
            value.as_object_mut().unwrap().remove(key);
            assert!(
                decode_bridge(&serde_json::to_vec(&value).unwrap(), &identity()).is_err(),
                "missing envelope {key}"
            );
        }
        for key in original["payload"].as_object().unwrap().keys() {
            let mut value = original.clone();
            value["payload"].as_object_mut().unwrap().remove(key);
            assert!(
                decode_bridge(&serde_json::to_vec(&value).unwrap(), &identity()).is_err(),
                "{} missing {key}",
                fixture["kind"]
            );
        }
        for target in ["envelope", "payload"] {
            let mut value = original.clone();
            let object = if target == "envelope" {
                value.as_object_mut().unwrap()
            } else {
                value["payload"].as_object_mut().unwrap()
            };
            object.insert("unknown".into(), Value::Null);
            assert!(decode_bridge(&serde_json::to_vec(&value).unwrap(), &identity()).is_err());
        }
    }
}

#[test]
fn duplicate_keys_are_rejected_in_envelopes_payloads_and_nested_terminal_counts() {
    let valid = String::from_utf8(event(0, "warning", fixtures()[12]["payload"].clone())).unwrap();
    for (before, after) in [
        ("\"sequence\":0", "\"sequence\":0,\"sequence\":0"),
        ("\"ordinal\":null", "\"ordinal\":null,\"ordinal\":null"),
        ("\"message\":", "\"message\":\"first\",\"message\":"),
        (
            "\"category\":",
            "\"categ\\u006fry\":\"shadow\",\"category\":",
        ),
    ] {
        assert!(valid.contains(before));
        assert!(decode_bridge(valid.replace(before, after).as_bytes(), &identity()).is_err());
    }
    let terminal = String::from_utf8(event(
        0,
        "session_terminated",
        fixtures()[17]["payload"].clone(),
    ))
    .unwrap();
    for before in ["\"passed\":0", "\"selected_count\":2", "\"setup\":"] {
        let extra = if before.ends_with(':') {
            "\"setup\":{},\"setup\":".into()
        } else {
            format!("{before},{before}")
        };
        assert!(terminal.contains(before));
        assert!(
            decode_bridge(terminal.replacen(before, &extra, 1).as_bytes(), &identity()).is_err()
        );
    }
}

#[test]
fn versions_roles_identities_and_coordinator_kinds_cannot_be_spoofed() {
    let base = envelope(0, "collection_started", json!({}));
    for (key, replacement) in [
        ("protocol_version", json!(1)),
        ("contract_revision", json!(2)),
        ("producer_role", json!("coordinator")),
        ("request_id", json!("other")),
        ("run_id", json!("other")),
        ("generation_id", json!("other")),
        ("session_id", json!("other")),
        ("producer_id", json!("other")),
        ("sequence", json!(MAX_EVENTS)),
        ("kind", json!("unknown")),
        ("kind", json!("artifact_committed")),
    ] {
        let mut value = base.clone();
        value[key] = replacement;
        assert!(
            decode_bridge(&serde_json::to_vec(&value).unwrap(), &identity()).is_err(),
            "{key}"
        );
    }
    for value in ["", "_bad", "has space", "a/b", "λ", &"x".repeat(129)] {
        let mut bad = identity();
        bad.producer_id = value.into();
        assert!(bad.validate().is_err());
        assert!(decode_bridge(&serde_json::to_vec(&base).unwrap(), &bad).is_err());
    }
    for name in [
        "python_version",
        "pytest_version",
        "bridge_version",
        "invocation_profile",
    ] {
        let mut payload = handshake();
        payload[name] = json!("unreviewed-version-or-entrypoint");
        assert!(decode_bridge(&event(0, "session_started", payload), &identity()).is_err());
    }
}

#[test]
fn invalid_utf8_json_surrogates_nonintegers_and_trailing_data_fail_without_repair() {
    let valid = event(0, "warning", fixtures()[12]["payload"].clone());
    let text = String::from_utf8(valid.clone()).unwrap();
    let invalid = [
        vec![],
        vec![0xff],
        b"\xff\xfe{\0}\0".to_vec(),
        b"null".to_vec(),
        b"[]".to_vec(),
        [valid.clone(), b" {}".to_vec()].concat(),
        valid[..valid.len() - 1].to_vec(),
        text.replace("\"ordinal\":null", "\"ordinal\":NaN")
            .into_bytes(),
        text.replace("\"ordinal\":null", "\"ordinal\":1.5")
            .into_bytes(),
        text.replace("\"ordinal\":null", "\"ordinal\":1e0")
            .into_bytes(),
        text.replace("\"ordinal\":null", "\"ordinal\":true")
            .into_bytes(),
        text.replace("\"ordinal\":null", "\"ordinal\":-1")
            .into_bytes(),
        text.replace("\"message\":", "\"message\":\"\\ud800\",\"extra\":")
            .into_bytes(),
        text.replace("\"ordinal\":null", "\"ordinal\":18446744073709551616")
            .into_bytes(),
    ];
    for raw in invalid {
        assert!(decode_bridge(&raw, &identity()).is_err(), "{raw:?}");
    }
}

#[test]
fn preallocation_frame_depth_and_token_limits_fail_instead_of_truncating() {
    for raw in [
        vec![b' '; MAX_FRAME_BYTES + 1],
        format!(
            "{}0{}",
            "[".repeat(MAX_DEPTH + 1),
            "]".repeat(MAX_DEPTH + 1)
        )
        .into_bytes(),
        format!("[{}0]", "0,".repeat(MAX_NODES)).into_bytes(),
    ] {
        let error = decode_bridge(&raw, &identity()).unwrap_err().to_string();
        assert!(
            error.contains("bound") || error.contains("length"),
            "{error}"
        );
    }
    let mut raw = event(0, "collection_started", json!({}));
    raw.resize(MAX_FRAME_BYTES, b' ');
    assert_eq!(
        decode_bridge(&raw, &identity()).unwrap().raw_json().len(),
        MAX_FRAME_BYTES
    );
}

#[test]
fn unicode_text_limit_is_in_characters_but_encoded_wire_bound_is_independent() {
    let mut payload = fixtures()[12]["payload"].clone();
    payload["message"] = json!("🐍".repeat(65_536));
    assert!(decode_bridge(&event(0, "warning", payload.clone()), &identity()).is_ok());
    payload["message"] = json!("🐍".repeat(65_537));
    assert!(decode_bridge(&event(0, "warning", payload), &identity()).is_err());
}

#[test]
fn array_count_attempt_hash_and_crossfield_constraints_are_not_just_generic_json() {
    for (index, key, values) in [
        (4, "nodeid", vec![json!(""), json!("x".repeat(65_537))]),
        (
            5,
            "ordinals",
            vec![
                json!([0, 0]),
                json!([true]),
                json!((0..4097).collect::<Vec<_>>()),
            ],
        ),
        (8, "attempt", vec![json!(32), json!(-1), json!(256)]),
        (
            9,
            "artifact_ids",
            vec![
                json!(["a", "a"]),
                json!(["bad/path"]),
                json!((0..1025).map(|i| format!("a-{i}")).collect::<Vec<_>>()),
            ],
        ),
        (12, "line", vec![json!(0), json!(-1)]),
        (13, "attempt", vec![json!(0)]),
        (
            14,
            "sha256",
            vec![json!("A".repeat(64)), json!("a".repeat(63))],
        ),
        (16, "extension_version", vec![json!(0)]),
        (17, "incomplete_ordinals", vec![json!([0, 0])]),
    ] {
        for replacement in values {
            let fixture = &fixtures()[index];
            let mut payload = fixture["payload"].clone();
            payload[key] = replacement;
            assert!(
                decode_bridge(
                    &event(0, fixture["kind"].as_str().unwrap(), payload),
                    &identity()
                )
                .is_err(),
                "{} {key}",
                fixture["kind"]
            );
        }
    }
    for (index, key, replacement) in [
        (7, "inventory_complete", json!(false)),
        (9, "outcome", json!("passed")),
        (9, "phase", json!("setup")),
        (17, "termination", json!("bad")),
    ] {
        let fixture = &fixtures()[index];
        let mut payload = fixture["payload"].clone();
        payload[key] = replacement;
        assert!(
            decode_bridge(
                &event(0, fixture["kind"].as_str().unwrap(), payload),
                &identity()
            )
            .is_err()
        );
    }
    let mut terminal = fixtures()[17]["payload"].clone();
    terminal["termination"] = json!("backend_exited");
    terminal["backend_exit_code"] = Value::Null;
    assert!(decode_bridge(&event(0, "session_terminated", terminal), &identity()).is_err());
}
