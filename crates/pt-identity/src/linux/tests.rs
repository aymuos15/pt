use super::*;
use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::time::SystemTime;

fn limits() -> TreeLimits {
    TreeLimits {
        entries: 100,
        per_file_bytes: 1024 * 1024,
        total_bytes: 4 * 1024 * 1024,
        path_bytes: 64 * 1024,
        deadline: Instant::now() + Duration::from_secs(20),
    }
}
fn directory(path: &Path) {
    fs::create_dir(path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
struct Fixture {
    temp: tempfile::TempDir,
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::Builder::new()
            .prefix("pt-tree-identity-")
            .tempdir_in("/tmp/opencode")
            .unwrap();
        let root = temp.path().join("tree");
        directory(&root);
        Self { temp, root }
    }
    fn file(&self, name: impl AsRef<Path>, raw: &[u8]) -> TreeEntry {
        let path = self.root.join(&name);
        fs::write(&path, raw).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        File::open(&path)
            .unwrap()
            .set_times(std::fs::FileTimes::new().set_modified(SystemTime::UNIX_EPOCH))
            .unwrap();
        TreeEntry {
            path: name.as_ref().into(),
            mode: 0o600,
            kind: TreeKind::File {
                bytes: raw.len() as u64,
                mtime_ns: 0,
                sha256: Sha256::digest(raw).into(),
            },
        }
    }
    fn manifest(&self, entries: Vec<TreeEntry>) -> TreeManifest {
        TreeManifest::new(0o700, entries, limits()).unwrap()
    }
}

#[test]
fn declared_regular_directory_symlink_and_binary_bytes_match_without_import_or_execution() {
    let f = Fixture::new();
    directory(&f.root.join("d"));
    let file = f.file("d/a", b"\0\xff binary\n");
    symlink("d/a", f.root.join("link")).unwrap();
    let manifest = f.manifest(vec![
        TreeEntry {
            path: "d".into(),
            mode: 0o700,
            kind: TreeKind::Directory,
        },
        file,
        TreeEntry {
            path: "link".into(),
            mode: 0o777,
            kind: TreeKind::Symlink {
                target: b"d/a".to_vec(),
            },
        },
    ]);
    let proof = manifest.verify(&f.root).unwrap();
    assert_eq!(proof.entries(), 3);
    assert_eq!(proof.files(), 1);
    assert_eq!(proof.directories(), 1);
    assert_eq!(proof.symlinks(), 1);
    assert_eq!(proof.file_bytes(), 10);
    assert_eq!(proof.bytes_hashed(), 20);
    assert_eq!(proof.root(), f.root);
    assert_eq!(proof.manifest_sha256(), manifest.sha256());
    assert!(proof.root_device_inode().1 > 0);
}

#[test]
fn empty_tree_is_identity_evidence_not_a_nonempty_test_or_environment_result() {
    let f = Fixture::new();
    let proof = f.manifest(vec![]).verify(&f.root).unwrap();
    assert_eq!(proof.entries(), 0);
    assert_eq!(proof.bytes_hashed(), 0);
}

#[test]
fn same_size_same_mtime_byte_edits_and_missing_or_extra_entries_fail_without_repairs() {
    for mode in ["content", "missing", "extra", "mode", "mtime"] {
        let f = Fixture::new();
        let entry = f.file("a", b"abc");
        let manifest = f.manifest(vec![entry]);
        match mode {
            "content" => {
                fs::write(f.root.join("a"), b"xyz").unwrap();
                File::open(f.root.join("a"))
                    .unwrap()
                    .set_times(std::fs::FileTimes::new().set_modified(SystemTime::UNIX_EPOCH))
                    .unwrap();
            }
            "missing" => fs::rename(f.root.join("a"), f.temp.path().join("old-a")).unwrap(),
            "extra" => {
                f.file("b", b"extra");
            }
            "mode" => {
                fs::set_permissions(f.root.join("a"), fs::Permissions::from_mode(0o400)).unwrap()
            }
            _ => File::open(f.root.join("a"))
                .unwrap()
                .set_times(
                    std::fs::FileTimes::new()
                        .set_modified(SystemTime::UNIX_EPOCH + Duration::from_secs(1)),
                )
                .unwrap(),
        }
        assert!(manifest.verify(&f.root).is_err(), "{mode}");
        if mode == "content" {
            assert_eq!(fs::read(f.root.join("a")).unwrap(), b"xyz");
        }
        if mode == "extra" {
            assert_eq!(fs::read(f.root.join("b")).unwrap(), b"extra");
        }
    }
}

#[test]
fn raw_non_utf8_case_and_unicode_paths_are_distinct_and_never_normalized() {
    let f = Fixture::new();
    let mut entries = vec![
        f.file("A", b"A"),
        f.file("a", b"a"),
        f.file(PathBuf::from(OsString::from_vec(vec![0xff])), b"raw"),
        f.file("λ", b"unicode"),
    ];
    entries.sort_by(|a, b| {
        a.path
            .as_os_str()
            .as_bytes()
            .cmp(b.path.as_os_str().as_bytes())
    });
    let manifest = f.manifest(entries);
    assert_eq!(manifest.verify(&f.root).unwrap().files(), 4);
}

#[test]
fn traversal_aliases_parent_omissions_duplicate_or_reordered_manifests_are_rejected() {
    let f = Fixture::new();
    let a = f.file("a", b"abc");
    for path in ["", ".", "../a", "/absolute", "a/./b", "a//b", "a/../b"] {
        let mut entry = a.clone();
        entry.path = path.into();
        assert!(
            TreeManifest::new(0o700, vec![entry], limits()).is_err(),
            "{path}"
        );
    }
    for entries in [
        vec![a.clone(), a.clone()],
        vec![TreeEntry {
            path: "b/a".into(),
            ..a.clone()
        }],
        vec![
            TreeEntry {
                path: "b".into(),
                ..a.clone()
            },
            a.clone(),
        ],
    ] {
        assert!(TreeManifest::new(0o700, entries, limits()).is_err());
    }
    let alias = f.temp.path().join("alias");
    symlink(&f.root, &alias).unwrap();
    assert!(f.manifest(vec![a]).verify(&alias).is_err());
}

#[test]
fn directory_symlink_fifo_and_hardlink_substitutions_are_not_followed_or_repaired() {
    for mode in ["symlink", "fifo", "directory", "hardlink"] {
        let f = Fixture::new();
        let entry = f.file("a", b"abc");
        let manifest = f.manifest(vec![entry]);
        fs::rename(f.root.join("a"), f.temp.path().join("original")).unwrap();
        match mode {
            "symlink" => symlink(f.temp.path().join("original"), f.root.join("a")).unwrap(),
            "fifo" => {
                nix::unistd::mkfifo(&f.root.join("a"), Mode::S_IRUSR | Mode::S_IWUSR).unwrap()
            }
            "directory" => directory(&f.root.join("a")),
            _ => fs::hard_link(f.temp.path().join("original"), f.root.join("a")).unwrap(),
        }
        assert!(manifest.verify(&f.root).is_err(), "{mode}");
        assert_eq!(fs::read(f.temp.path().join("original")).unwrap(), b"abc");
    }
}

#[test]
fn link_text_is_checked_but_external_fifo_referents_are_not_opened_or_certified() {
    let f = Fixture::new();
    nix::unistd::mkfifo(
        &f.temp.path().join("outside-fifo"),
        Mode::S_IRUSR | Mode::S_IWUSR,
    )
    .unwrap();
    symlink("../outside-fifo", f.root.join("a")).unwrap();
    let manifest = f.manifest(vec![TreeEntry {
        path: "a".into(),
        mode: 0o777,
        kind: TreeKind::Symlink {
            target: b"../outside-fifo".to_vec(),
        },
    }]);
    assert_eq!(manifest.verify(&f.root).unwrap().symlinks(), 1);
    fs::rename(f.root.join("a"), f.temp.path().join("old-link")).unwrap();
    symlink("../different", f.root.join("a")).unwrap();
    assert_eq!(
        manifest.verify(&f.root).unwrap_err().code(),
        "tree_link_target_mismatch"
    );
}

#[test]
fn additions_leaf_replacements_and_root_substitutions_during_checks_cannot_publish_identity() {
    for mode in ["add", "replace", "root", "edit-earlier"] {
        let f = Fixture::new();
        let a = f.file("a", b"abc");
        let b = f.file("b", b"def");
        let manifest = f.manifest(vec![a, b]);
        let mut changed = false;
        let result = manifest.verify_with(&f.root, &mut |step, path| {
            if !changed
                && ((mode == "edit-earlier" && matches!(step, Step::BetweenPasses))
                    || (mode != "edit-earlier"
                        && matches!(step, Step::AfterEntry)
                        && path == Path::new("a")))
            {
                changed = true;
                match mode {
                    "add" => {
                        f.file("c", b"extra");
                    }
                    "replace" => {
                        fs::rename(f.root.join("a"), f.temp.path().join("old-a")).unwrap();
                        f.file("a", b"abc");
                    }
                    "root" => {
                        fs::rename(&f.root, f.temp.path().join("old-tree")).unwrap();
                        directory(&f.root);
                    }
                    _ => {
                        f.file("a", b"xyz");
                    }
                }
            }
            Ok(())
        });
        assert!(result.is_err(), "{mode}");
        assert!(changed);
    }
}

#[test]
fn recheck_rehashes_bytes_even_when_its_metadata_guard_is_explicitly_neutralized() {
    // Synthetic guard masking isolates the byte check regardless of the actual
    // filesystem's ctime precision. This is not fabricated successful evidence.
    let f = Fixture::new();
    let manifest = f.manifest(vec![f.file("a", b"abc")]);
    let parent = File::open(&f.root).unwrap();
    let mut stamps = BTreeMap::new();
    manifest
        .walk(
            &parent,
            Path::new(""),
            &mut stamps,
            &mut Counts::default(),
            false,
            &mut |_, _| Ok(()),
        )
        .unwrap();
    f.file("a", b"xyz");
    stamps.insert(
        b"a".to_vec(),
        Stamp::from(&named_stat(&parent, Path::new("a")).unwrap()),
    );
    let error = manifest
        .walk(
            &parent,
            Path::new(""),
            &mut stamps,
            &mut Counts::default(),
            true,
            &mut |_, _| Ok(()),
        )
        .unwrap_err();
    assert_eq!(error.code(), "tree_file_content_mismatch");
    assert_eq!(error.relative_path(), Some(Path::new("a")));
    assert_eq!(fs::read(f.root.join("a")).unwrap(), b"xyz");
}

#[test]
fn directory_reader_failure_closes_only_its_consumed_duplicate() {
    // A regular FD causes a real fdopendir ENOTDIR, without exhausting global
    // descriptors, changing permissions or relying on concurrent FD counts.
    let f = Fixture::new();
    f.file("a", b"abc");
    let parent = File::open(f.root.join("a")).unwrap();
    let before = stat(&parent).unwrap();
    for _ in 0..64 {
        let error = match directory_reader(&parent) {
            Ok(_) => panic!("regular file unexpectedly became a directory reader"),
            Err(error) => error,
        };
        assert_eq!(error.code(), "tree_directory_enumerate");
        assert!(error.to_string().contains("ENOTDIR"));
        assert!(error.to_string().contains("owned duplicate close: Ok(())"));
        assert_eq!(stat(&parent).unwrap().st_ino, before.st_ino);
    }
    assert_eq!(fs::read(f.root.join("a")).unwrap(), b"abc");
}

#[test]
fn positive_entry_path_content_and_absolute_lifetime_bounds_are_not_inferred_or_extended() {
    let f = Fixture::new();
    let entry = f.file("a", b"abc");
    for selected in [
        TreeLimits {
            entries: 0,
            ..limits()
        },
        TreeLimits {
            entries: 100001,
            ..limits()
        },
        TreeLimits {
            per_file_bytes: 0,
            ..limits()
        },
        TreeLimits {
            per_file_bytes: 128 * 1024 * 1024 + 1,
            ..limits()
        },
        TreeLimits {
            total_bytes: 0,
            ..limits()
        },
        TreeLimits {
            total_bytes: 4 * 1024 * 1024 * 1024 + 1,
            ..limits()
        },
        TreeLimits {
            path_bytes: 0,
            ..limits()
        },
        TreeLimits {
            deadline: Instant::now(),
            ..limits()
        },
    ] {
        assert!(TreeManifest::new(0o700, vec![entry.clone()], selected).is_err());
    }
    assert!(
        TreeManifest::new(
            0o700,
            vec![entry.clone()],
            TreeLimits {
                per_file_bytes: 2,
                ..limits()
            }
        )
        .is_err()
    );
    let mut manifest = f.manifest(vec![entry]);
    manifest.limits.deadline = Instant::now() + Duration::from_millis(100);
    let error = manifest
        .verify_with(&f.root, &mut |step, _| {
            if matches!(step, Step::BetweenPasses) {
                std::thread::sleep(Duration::from_millis(150));
            }
            Ok(())
        })
        .unwrap_err();
    assert_eq!(error.code(), "tree_absolute_deadline_expired");
}

#[test]
fn canonical_identity_hash_agrees_with_independent_isolated_python_stdlib_fields() {
    use pt_process::{Cleanup, ProcessRequest, supervise};
    use std::sync::atomic::AtomicI32;
    let f = Fixture::new();
    let entry = f.file("a", b"abc");
    let manifest = f.manifest(vec![entry]);
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let python = std::env::var_os("PT_TEST_PYTHON")
        .unwrap_or_else(|| root.join("bench/harness/.venv/bin/python").into_os_string());
    let source = "import hashlib\nh=hashlib.sha256();h.update(b'pt-tree-manifest-v1\\0');h.update((0o700).to_bytes(4,'big'));h.update((1).to_bytes(8,'big'));h.update((1).to_bytes(8,'big')+b'a');h.update((0o600).to_bytes(4,'big'));h.update(b'\\2');h.update((3).to_bytes(8,'big'));h.update((0).to_bytes(16,'big',signed=True));h.update(bytes.fromhex('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'));\nwith open('independent.sha256','x') as f:f.write(h.hexdigest())\n";
    let process = supervise(
        &ProcessRequest {
            executable: python,
            args: vec![
                "-I".into(),
                "-S".into(),
                "-B".into(),
                "-c".into(),
                source.into(),
            ],
            cwd: f.temp.path().into(),
            timeout: Duration::from_secs(5),
            cleanup_timeout: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    assert_eq!(process.exit_code(), 0);
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert_eq!(
        manifest.sha256(),
        fs::read_to_string(f.temp.path().join("independent.sha256")).unwrap()
    );

    // A second independently literal serialization covers directories, raw
    // non-UTF-8 link text, signed mtimes, empty file content and length boundaries.
    let entries = vec![
        TreeEntry {
            path: "d".into(),
            mode: 0o755,
            kind: TreeKind::Directory,
        },
        TreeEntry {
            path: "d/λ".into(),
            mode: 0o400,
            kind: TreeKind::File {
                bytes: 0,
                mtime_ns: -1,
                sha256: Sha256::digest(b"").into(),
            },
        },
        TreeEntry {
            path: "l".into(),
            mode: 0o777,
            kind: TreeKind::Symlink {
                target: vec![b'.', b'.', b'/', 0xff],
            },
        },
    ];
    let manifest = f.manifest(entries);
    let source = r#"import hashlib
h=hashlib.sha256(b'pt-tree-manifest-v1\0')
h.update((0o700).to_bytes(4,'big')+(3).to_bytes(8,'big'))
def field(raw): h.update(len(raw).to_bytes(8,'big')+raw)
field(b'd');h.update((0o755).to_bytes(4,'big')+b'\0')
field('d/λ'.encode());h.update((0o400).to_bytes(4,'big')+b'\2')
h.update((0).to_bytes(8,'big')+(-1).to_bytes(16,'big',signed=True))
h.update(bytes.fromhex('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'))
field(b'l');h.update((0o777).to_bytes(4,'big')+b'\1');field(b'../\xff')
with open('independent-mixed.sha256','x') as f: f.write(h.hexdigest())
"#;
    let process = supervise(
        &ProcessRequest {
            executable: std::env::var_os("PT_TEST_PYTHON")
                .unwrap_or_else(|| root.join("bench/harness/.venv/bin/python").into_os_string()),
            args: vec![
                "-I".into(),
                "-S".into(),
                "-B".into(),
                "-c".into(),
                source.into(),
            ],
            cwd: f.temp.path().into(),
            timeout: Duration::from_secs(5),
            cleanup_timeout: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    assert_eq!(process.exit_code(), 0);
    assert_eq!(process.cleanup, Cleanup::Complete);
    assert_eq!(
        manifest.sha256(),
        fs::read_to_string(f.temp.path().join("independent-mixed.sha256")).unwrap()
    );
}

#[test]
fn changed_mode_and_timestamp_change_manifest_identity_even_with_identical_file_bytes() {
    let f = Fixture::new();
    let a = f.file("a", b"abc");
    let original = f.manifest(vec![a.clone()]);
    let mut b = a.clone();
    b.mode = 0o400;
    assert_ne!(original.sha256(), f.manifest(vec![b]).sha256());
    let mut b = a;
    if let TreeKind::File { mtime_ns, .. } = &mut b.kind {
        *mtime_ns = 1;
    }
    assert_ne!(original.sha256(), f.manifest(vec![b]).sha256());
}

#[test]
fn root_permissions_and_symlink_directory_components_are_not_ignored() {
    let f = Fixture::new();
    let manifest = f.manifest(vec![]);
    fs::set_permissions(&f.root, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(
        manifest.verify(&f.root).unwrap_err().code(),
        "tree_root_mode_mismatch"
    );
    directory(&f.root.join("real"));
    symlink("real", f.root.join("alias")).unwrap();
    let alias = f.root.join("alias");
    assert!(
        TreeManifest::new(0o700, vec![], limits())
            .unwrap()
            .verify(&alias)
            .is_err()
    );
}
