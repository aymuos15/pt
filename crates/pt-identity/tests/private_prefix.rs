#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
//! Optional explicitly selected archive-manifest reproduction, never inferring
//! expected bytes from the installed tree being checked or modifying that tree.
use pt_identity::{LinkLimits, TreeEntry, TreeKind, TreeLimits, TreeManifest};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[test]
#[ignore = "requires explicitly supplied retained private archive manifest and both prepared prefixes"]
fn both_complete_private_prefixes_match_the_archive_derived_declared_tree() {
    let source = PathBuf::from(
        std::env::var_os("PT_IDENTITY_PREFIX_MANIFEST")
            .expect("explicit archive-derived manifest required"),
    );
    let expected = std::env::var("PT_IDENTITY_PREFIX_MANIFEST_SHA256")
        .expect("explicit prior manifest digest required");
    assert!(fs::metadata(&source).unwrap().len() <= 4 * 1024 * 1024);
    let raw = fs::read(&source).unwrap();
    let actual = Sha256::digest(&raw)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    assert_eq!(actual, expected);
    let document: Value = serde_json::from_slice(&raw).unwrap();
    let entries = document["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| {
            let kind = match value["kind"].as_str().unwrap() {
                "directory" => TreeKind::Directory,
                "symlink" => TreeKind::Symlink {
                    target: value["target"].as_str().unwrap().as_bytes().to_vec(),
                },
                "file" => {
                    let text = value["sha256"].as_str().unwrap();
                    assert_eq!(text.len(), 64);
                    let mut digest = [0; 32];
                    for (index, byte) in digest.iter_mut().enumerate() {
                        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16).unwrap();
                    }
                    TreeKind::File {
                        bytes: value["bytes"].as_u64().unwrap(),
                        mtime_ns: value["mtime_ns"].as_i64().unwrap() as i128,
                        sha256: digest,
                    }
                }
                _ => panic!("unsupported archive entry"),
            };
            TreeEntry {
                path: value["path"].as_str().unwrap().into(),
                mode: value["mode"].as_u64().unwrap() as u32,
                kind,
            }
        })
        .collect::<Vec<_>>();
    let manifest = TreeManifest::new(
        0o700,
        entries,
        TreeLimits {
            entries: 10000,
            per_file_bytes: 128 * 1024 * 1024,
            total_bytes: 2 * 1024 * 1024 * 1024,
            path_bytes: 4 * 1024 * 1024,
            deadline: Instant::now() + Duration::from_secs(120),
        },
    )
    .unwrap();
    let mut reports = Vec::new();
    for variable in ["PT_IDENTITY_PREFIX_ONE", "PT_IDENTITY_PREFIX_TWO"] {
        let root = PathBuf::from(
            std::env::var_os(variable).expect("both explicit private prefixes required"),
        );
        let closed = manifest
            .verify_with_closed_links(
                &root,
                LinkLimits {
                    steps: 100000,
                    dereferences: 40,
                    pending_components: 4096,
                },
            )
            .unwrap();
        let observed = closed.tree();
        assert_eq!(observed.entries(), 4971);
        assert_eq!(observed.files(), 3722);
        assert_eq!(observed.symlinks(), 1048);
        assert_eq!(observed.directories(), 201);
        assert_eq!(observed.bytes_hashed(), observed.file_bytes() * 2);
        assert_eq!(closed.links(), 1048);
        assert_eq!(closed.resolution_steps(), 1648);
        reports.push(json!({"root":root,"entries":observed.entries(),"files":observed.files(),"symlinks":observed.symlinks(),"directories":observed.directories(),"file_bytes":observed.file_bytes(),"bytes_hashed":observed.bytes_hashed(),"manifest_sha256":observed.manifest_sha256(),"declared_relative_links":{"policy_id":closed.policy_id(),"links":closed.links(),"component_steps":closed.resolution_steps(),"maximum_dereferences":closed.maximum_dereferences(),"resolution_sha256":closed.resolution_sha256()},"qualified":false}));
    }
    if let Some(path) = std::env::var_os("PT_IDENTITY_PROOF_OUTPUT") {
        use std::io::Write;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .unwrap();
        file.write_all(&serde_json::to_vec_pretty(&json!({"mode":"read_only_endpoint_tree_identity","source_manifest_sha256":expected,"reports":reports,"qualified":false})).unwrap()).unwrap();
    }
}
