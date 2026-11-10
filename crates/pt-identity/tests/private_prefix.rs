#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
//! Optional explicitly selected archive-manifest reproduction, never inferring
//! expected bytes from the installed tree being checked or modifying that tree.
use pt_identity::{
    ElfLimits, ElfStringKind, LinkLimits, TreeEntry, TreeKind, TreeLimits, TreeManifest,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::ffi::OsStr;
use std::fs;
use std::io::{Read, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

fn elf_reference_path(root: &Path, prefix: &OsStr, index: usize, suffix: &str) -> PathBuf {
    let mut name = prefix.to_os_string();
    name.push(format!("-elf-reference-{index}{suffix}"));
    root.join(name)
}

#[test]
fn reference_output_names_preserve_non_utf8_bytes_without_replacement_collisions() {
    use std::os::unix::ffi::OsStrExt;
    let raw = elf_reference_path(
        Path::new("/evidence"),
        OsStr::from_bytes(b"proof-\xff"),
        1,
        ".json",
    );
    let unicode = elf_reference_path(Path::new("/evidence"), OsStr::new("proof-�"), 1, ".json");
    assert_eq!(
        raw.as_os_str().as_bytes(),
        b"/evidence/proof-\xff-elf-reference-1.json"
    );
    assert_ne!(raw, unicode);
}

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
    let deadline = Instant::now() + Duration::from_secs(120);
    let manifest = TreeManifest::new(
        0o700,
        entries,
        TreeLimits {
            entries: 10000,
            per_file_bytes: 128 * 1024 * 1024,
            total_bytes: 2 * 1024 * 1024 * 1024,
            path_bytes: 4 * 1024 * 1024,
            deadline,
        },
    )
    .unwrap();
    let evidence = std::env::var_os("PT_IDENTITY_PROOF_OUTPUT").map(PathBuf::from);
    let temporary = if evidence.is_none() {
        Some(
            tempfile::Builder::new()
                .prefix("pt-native-elf-reference-")
                .tempdir_in("/tmp/opencode")
                .unwrap(),
        )
    } else {
        None
    };
    let evidence_root = evidence
        .as_ref()
        .map(|path| path.parent().expect("proof output has a parent"))
        .unwrap_or_else(|| temporary.as_ref().unwrap().path());
    let prefix = evidence
        .as_ref()
        .map(|path| path.file_stem().unwrap().to_os_string())
        .unwrap_or_else(|| "prefix".into());
    let mut reports = Vec::new();
    for (index, variable) in ["PT_IDENTITY_PREFIX_ONE", "PT_IDENTITY_PREFIX_TWO"]
        .into_iter()
        .enumerate()
    {
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
        let mut file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(nix::libc::O_NOFOLLOW | nix::libc::O_NONBLOCK | nix::libc::O_CLOEXEC)
            .open(root.join("bin/python3.12"))
            .unwrap();
        let before = file.metadata().unwrap();
        assert!(before.is_file() && before.nlink() == 1 && before.len() <= 128 * 1024 * 1024);
        let mut image = Vec::new();
        let mut chunk = [0; 65536];
        loop {
            assert!(Instant::now() < deadline);
            let size = file.read(&mut chunk).unwrap();
            assert!(Instant::now() < deadline);
            if size == 0 {
                break;
            }
            assert!(image.len() + size <= 128 * 1024 * 1024);
            image.extend_from_slice(&chunk[..size]);
        }
        let stamp = |value: fs::Metadata| {
            (
                value.dev(),
                value.ino(),
                value.mode(),
                value.nlink(),
                value.len(),
                value.mtime(),
                value.mtime_nsec(),
                value.ctime(),
                value.ctime_nsec(),
            )
        };
        assert_eq!(stamp(file.metadata().unwrap()), stamp(before));
        assert_eq!(
            stamp(fs::symlink_metadata(root.join("bin/python3.12")).unwrap()),
            stamp(file.metadata().unwrap())
        );
        let elf = manifest
            .inspect_declared_elf(
                std::path::Path::new("bin/python3.12"),
                &image,
                ElfLimits {
                    program_headers: 128,
                    dynamic_entries: 4096,
                    needed: 256,
                    string_table_bytes: 1024 * 1024,
                    projected_string_bytes: 64 * 1024,
                },
            )
            .unwrap();
        assert_eq!(
            elf.interpreter(),
            Some(b"/lib64/ld-linux-x86-64.so.2".as_slice())
        );
        assert_eq!(
            elf.needed().collect::<Vec<_>>(),
            [
                b"libpthread.so.0".as_slice(),
                b"libdl.so.2".as_slice(),
                b"libutil.so.1".as_slice(),
                b"librt.so.1".as_slice(),
                b"libm.so.6".as_slice(),
                b"libc.so.6".as_slice()
            ]
        );
        assert_eq!(
            elf.string_inputs()
                .iter()
                .find(|value| value.kind() == ElfStringKind::Rpath)
                .unwrap()
                .bytes(),
            b"$ORIGIN/../lib"
        );
        let oracle_path = elf_reference_path(evidence_root, &prefix, index, ".json");
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let process = pt_process::supervise(
            &pt_process::ProcessRequest {
                executable: std::env::var_os("PT_TEST_PYTHON").unwrap_or_else(|| {
                    workspace
                        .join("bench/harness/.venv/bin/python")
                        .into_os_string()
                }),
                args: vec![
                    "-I".into(),
                    "-S".into(),
                    "-B".into(),
                    workspace
                        .join("crates/pt-identity/tests/elf_reference.py")
                        .into_os_string(),
                    root.join("bin/python3.12").into_os_string(),
                    elf.image_sha256().into(),
                    oracle_path.clone().into_os_string(),
                ],
                cwd: evidence_root.into(),
                timeout: Duration::from_secs(10),
                cleanup_timeout: Duration::from_secs(1),
            },
            &std::sync::atomic::AtomicI32::new(0),
        )
        .unwrap();
        let mut process_output = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(elf_reference_path(
                evidence_root,
                &prefix,
                index,
                ".process.json",
            ))
            .unwrap();
        process_output
            .write_all(&serde_json::to_vec_pretty(&process).unwrap())
            .unwrap();
        assert_eq!(process.exit_code(), 0);
        assert_eq!(process.cleanup, pt_process::Cleanup::Complete);
        let oracle: Value = serde_json::from_slice(&fs::read(&oracle_path).unwrap()).unwrap();
        let headers = elf
            .program_headers()
            .iter()
            .map(|value| {
                json!([
                    value.kind(),
                    value.flags(),
                    value.offset(),
                    value.virtual_address(),
                    value.physical_address(),
                    value.file_bytes(),
                    value.memory_bytes(),
                    value.alignment()
                ])
            })
            .collect::<Vec<_>>();
        let dynamic = elf
            .dynamic_entries()
            .iter()
            .map(|value| json!([value.tag_bits(), value.value()]))
            .collect::<Vec<_>>();
        let needed = elf
            .needed()
            .map(|value| std::str::from_utf8(value).unwrap())
            .collect::<Vec<_>>();
        let strings = elf
            .string_inputs()
            .iter()
            .map(|value| json!({"kind":format!("{:?}",value.kind()),"bytes":value.bytes()}))
            .collect::<Vec<_>>();
        assert_eq!(oracle["program_headers"], json!(headers));
        assert_eq!(oracle["dynamic_entries"], json!(dynamic));
        assert_eq!(oracle["needed"], json!(needed));
        assert_eq!(oracle["used_dynamic_entries"], elf.used_dynamic_entries());
        assert_eq!(
            oracle["interpreter"],
            std::str::from_utf8(elf.interpreter().unwrap()).unwrap()
        );
        assert_eq!(oracle["image_sha256"], elf.image_sha256());
        assert_eq!(oracle["image_bytes"], elf.image_bytes());
        assert_eq!(oracle["object_type"], elf.object_type());
        assert_eq!(oracle["os_abi"], elf.os_abi());
        assert_eq!(oracle["entry_point"], elf.entry_point());
        assert_eq!(oracle["search"], json!([["RPATH", "$ORIGIN/../lib"]]));
        reports.push(json!({"root":root,"entries":observed.entries(),"files":observed.files(),"symlinks":observed.symlinks(),"directories":observed.directories(),"file_bytes":observed.file_bytes(),"bytes_hashed":observed.bytes_hashed(),"manifest_sha256":observed.manifest_sha256(),"declared_relative_links":{"policy_id":closed.policy_id(),"links":closed.links(),"component_steps":closed.resolution_steps(),"maximum_dereferences":closed.maximum_dereferences(),"resolution_sha256":closed.resolution_sha256()},
            "declared_elf_load_inputs":{"policy_id":elf.policy_id(),"path":elf.path(),"image_sha256":elf.image_sha256(),"image_bytes":elf.image_bytes(),"bytes_hashed":elf.bytes_hashed(),"object_type":elf.object_type(),"os_abi":elf.os_abi(),"entry_point":elf.entry_point(),"interpreter":std::str::from_utf8(elf.interpreter().unwrap()).unwrap(),"needed":needed,"string_inputs":strings,"program_headers":headers,"dynamic_entries":dynamic,"used_dynamic_entries":elf.used_dynamic_entries(),"target_executed":false,"dependency_resolution_verified":false,"environment_verified":false},"qualified":false}));
    }
    if let Some(path) = evidence {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .unwrap();
        file.write_all(&serde_json::to_vec_pretty(&json!({"mode":"read_only_endpoint_tree_identity","source_manifest_sha256":expected,"reports":reports,"qualified":false})).unwrap()).unwrap();
    }
}
