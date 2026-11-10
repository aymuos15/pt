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
    fn link(&self, name: impl AsRef<Path>, target: &[u8]) -> TreeEntry {
        symlink(OsString::from_vec(target.to_vec()), self.root.join(&name)).unwrap();
        TreeEntry {
            path: name.as_ref().into(),
            mode: 0o777,
            kind: TreeKind::Symlink {
                target: target.to_vec(),
            },
        }
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

fn link_limits() -> LinkLimits {
    LinkLimits {
        steps: 1000,
        dereferences: 40,
        pending_components: 100,
    }
}
fn declared_directory(path: &str) -> TreeEntry {
    TreeEntry {
        path: path.into(),
        mode: 0o700,
        kind: TreeKind::Directory,
    }
}
fn sorted_fixture_manifest(f: &Fixture, mut entries: Vec<TreeEntry>) -> TreeManifest {
    // Sorting is explicit preparation of these test-owned expected fixtures.
    // Production construction still rejects unsorted caller manifests unchanged.
    entries.sort_by(|left, right| {
        left.path
            .as_os_str()
            .as_bytes()
            .cmp(right.path.as_os_str().as_bytes())
    });
    f.manifest(entries)
}

#[test]
fn closed_relative_links_bind_raw_names_root_aliases_and_independent_kernel_resolution_hash() {
    let f = Fixture::new();
    directory(&f.root.join("d"));
    let mut entries = vec![
        declared_directory("d"),
        f.file("d/a", b"abc"),
        f.link("d/self", b"."),
        f.link("dir_alias", b"d/self"),
        f.link("root_alias", b"d/.."),
        f.link("λ", b"d//./a"),
    ];
    entries.push(f.link(PathBuf::from(OsString::from_vec(vec![b'l', 0xff])), b"d/a"));
    let manifest = sorted_fixture_manifest(&f, entries);
    let closed = manifest
        .verify_with_closed_links(&f.root, link_limits())
        .unwrap();
    assert_eq!(closed.links(), 5);
    assert_eq!(closed.maximum_dereferences(), 2);
    assert_eq!(closed.tree().bytes_hashed(), 6);
    assert_eq!(closed.tree().manifest_sha256(), manifest.sha256());
    assert_eq!(closed.policy_id(), RELATIVE_LINK_POLICY_ID);
    let names = manifest
        .entries
        .values()
        .filter(|entry| matches!(entry.kind, TreeKind::Symlink { .. }))
        .map(|entry| hex(entry.path.as_os_str().as_bytes()))
        .collect::<Vec<_>>();
    let input = f.temp.path().join("declared-links.json");
    fs::write(
        &input,
        serde_json::to_vec(&serde_json::json!({"tree_sha256":manifest.sha256(),"links_hex":names}))
            .unwrap(),
    )
    .unwrap();
    // Independent stdlib/OS path resolution on only these fixed closed positive
    // fixtures; no product resolver, project code or negative external path is
    // imported/opened by this control. Root maps to an explicit empty byte path.
    let source = r#"import hashlib,json,os,stat,sys
root=os.fsencode(sys.argv[1])
with open(sys.argv[2]) as stream: data=json.load(stream)
h=hashlib.sha256(b'pt-declared-link-resolution-v1\0')
def field(raw): h.update(len(raw).to_bytes(8,'big')+raw)
field(data['tree_sha256'].encode('ascii'));h.update(len(data['links_hex']).to_bytes(8,'big'))
for name in sorted(bytes.fromhex(value) for value in data['links_hex']):
    resolved=os.path.realpath(root+b'/'+name,strict=True)
    assert os.path.commonpath([root,resolved])==root
    relative=os.path.relpath(resolved,root)
    if relative==b'.': relative=b''
    info=os.stat(resolved)
    assert stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
    field(name);field(relative);h.update(b'\0' if stat.S_ISDIR(info.st_mode) else b'\2')
with open(sys.argv[3],'x') as output: output.write(h.hexdigest())
"#;
    let output = f.temp.path().join("independent-link-resolution.sha256");
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    use pt_process::{Cleanup, ProcessRequest, supervise};
    use std::sync::atomic::AtomicI32;
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
                f.root.clone().into_os_string(),
                input.into_os_string(),
                output.clone().into_os_string(),
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
        closed.resolution_sha256(),
        fs::read_to_string(output).unwrap()
    );
}

#[test]
fn relative_link_dotdot_expands_symlinks_before_parent_and_requires_real_directories() {
    let f = Fixture::new();
    directory(&f.root.join("d"));
    directory(&f.root.join("d/nested"));
    let manifest = sorted_fixture_manifest(
        &f,
        vec![
            f.link("alias", b"d/nested"),
            declared_directory("d"),
            f.file("d/file", b"abc"),
            declared_directory("d/nested"),
            f.link("edge", b"alias/../file"),
        ],
    );
    assert!(
        manifest
            .verify_with_closed_links(&f.root, link_limits())
            .is_ok()
    );
    assert_eq!(fs::read(f.root.join("edge")).unwrap(), b"abc");
    for target in [
        b"file/..".as_slice(),
        b"file/".as_slice(),
        b"file/.".as_slice(),
    ] {
        let f = Fixture::new();
        let manifest =
            sorted_fixture_manifest(&f, vec![f.file("file", b"abc"), f.link("link", target)]);
        assert!(manifest.verify(&f.root).is_ok());
        let error = manifest
            .verify_with_closed_links(&f.root, link_limits())
            .unwrap_err();
        assert_eq!(error.code(), "tree_link_non_directory_component");
        assert_eq!(error.relative_path(), Some(Path::new("link")));
    }
    let f = Fixture::new();
    directory(&f.root.join("d"));
    let manifest = sorted_fixture_manifest(
        &f,
        vec![
            declared_directory("d"),
            f.link("d/alias", b".."),
            f.file("d/outside", b"declared but not the resolved referent"),
            f.link("edge", b"d/alias/../outside"),
        ],
    );
    let error = manifest
        .verify_with_closed_links(&f.root, link_limits())
        .unwrap_err();
    assert_eq!(error.code(), "tree_link_exits_declared_root");
    assert_eq!(error.relative_path(), Some(Path::new("edge")));
}

#[test]
fn external_absolute_dangling_and_cyclic_links_remain_text_only_or_fail_closed_without_following() {
    for mode in [
        "external",
        "absolute-inside",
        "dangling",
        "self-cycle",
        "pair-cycle",
    ] {
        let f = Fixture::new();
        nix::unistd::mkfifo(
            &f.temp.path().join("outside"),
            Mode::S_IRUSR | Mode::S_IWUSR,
        )
        .unwrap();
        let file = f.file("inside", b"abc");
        let target = match mode {
            "external" => b"../outside".to_vec(),
            "absolute-inside" => f.root.join("inside").into_os_string().into_vec(),
            "dangling" => b"absent".to_vec(),
            "self-cycle" => b"link".to_vec(),
            _ => b"other".to_vec(),
        };
        let mut entries = vec![file, f.link("link", &target)];
        if mode == "pair-cycle" {
            entries.push(f.link("other", b"link"));
        }
        let manifest = sorted_fixture_manifest(&f, entries);
        assert!(
            manifest.verify(&f.root).is_ok(),
            "ordinary verification still identifies text only: {mode}"
        );
        let error = manifest
            .verify_with_closed_links(&f.root, link_limits())
            .unwrap_err();
        assert_eq!(
            error.code(),
            match mode {
                "external" => "tree_link_exits_declared_root",
                "absolute-inside" => "tree_link_absolute_target_unsupported",
                "dangling" => "tree_link_target_not_declared",
                _ => "tree_link_dereference_bound_or_cycle",
            },
            "{mode}"
        );
        assert_eq!(error.relative_path(), Some(Path::new("link")));
        assert!(std::os::unix::fs::FileTypeExt::is_fifo(
            &fs::symlink_metadata(f.temp.path().join("outside"))
                .unwrap()
                .file_type()
        ));
        assert_eq!(
            fs::read_link(f.root.join("link"))
                .unwrap()
                .as_os_str()
                .as_bytes(),
            target
        );
        assert_eq!(fs::read(f.root.join("inside")).unwrap(), b"abc");
    }
}

#[test]
fn closed_link_bounds_include_initial_dereference_and_all_queued_component_work() {
    let f = Fixture::new();
    let manifest = sorted_fixture_manifest(
        &f,
        vec![f.file("a", b"abc"), f.link("b", b"a"), f.link("c", b"b")],
    );
    let exact = LinkLimits {
        steps: 3,
        dereferences: 2,
        pending_components: 1,
    };
    let observed = manifest.verify_with_closed_links(&f.root, exact).unwrap();
    assert_eq!(observed.resolution_steps(), 3);
    assert_eq!(observed.maximum_dereferences(), 2);
    for selected in [
        LinkLimits { steps: 2, ..exact },
        LinkLimits {
            dereferences: 1,
            ..exact
        },
    ] {
        let error = manifest
            .verify_with_closed_links(&f.root, selected)
            .unwrap_err();
        assert_eq!(
            error.code(),
            if selected.steps == 2 {
                "tree_link_component_step_bound"
            } else {
                "tree_link_dereference_bound_or_cycle"
            }
        );
        assert_eq!(error.relative_path(), Some(Path::new("c")));
    }
    for selected in [
        LinkLimits { steps: 0, ..exact },
        LinkLimits {
            steps: 1_000_001,
            ..exact
        },
        LinkLimits {
            dereferences: 0,
            ..exact
        },
        LinkLimits {
            dereferences: 41,
            ..exact
        },
        LinkLimits {
            pending_components: 0,
            ..exact
        },
        LinkLimits {
            pending_components: 4097,
            ..exact
        },
    ] {
        assert_eq!(
            manifest
                .verify_with_closed_links(&f.temp.path().join("absent"), selected)
                .unwrap_err()
                .code(),
            "tree_link_limits_invalid"
        );
    }
    let f = Fixture::new();
    directory(&f.root.join("d"));
    let manifest = sorted_fixture_manifest(
        &f,
        vec![
            declared_directory("d"),
            f.file("d/a", b"abc"),
            f.link("l", b"d/./a"),
        ],
    );
    assert_eq!(
        manifest
            .verify_with_closed_links(
                &f.root,
                LinkLimits {
                    pending_components: 2,
                    ..link_limits()
                }
            )
            .unwrap_err()
            .code(),
        "tree_link_pending_component_bound"
    );
    assert!(
        manifest
            .verify_with_closed_links(
                &f.root,
                LinkLimits {
                    pending_components: 3,
                    ..link_limits()
                }
            )
            .is_ok()
    );
}

#[test]
fn closed_link_graph_does_not_waive_actual_bytes_link_text_or_original_deadline() {
    for mode in ["file-bytes", "link-text", "deadline"] {
        let f = Fixture::new();
        let mut manifest =
            sorted_fixture_manifest(&f, vec![f.file("a", b"abc"), f.link("l", b"a")]);
        match mode {
            "file-bytes" => {
                f.file("a", b"xyz");
            }
            "link-text" => {
                fs::rename(f.root.join("l"), f.temp.path().join("old-link")).unwrap();
                symlink("./a", f.root.join("l")).unwrap();
            }
            _ => manifest.limits.deadline = Instant::now(),
        }
        let error = manifest
            .verify_with_closed_links(&f.root, link_limits())
            .unwrap_err();
        if mode == "deadline" {
            assert_eq!(error.code(), "tree_absolute_deadline_expired");
        }
        assert!(fs::symlink_metadata(f.root.join("l")).unwrap().is_symlink());
        assert_eq!(
            fs::read(f.root.join("a")).unwrap(),
            if mode == "file-bytes" { b"xyz" } else { b"abc" }
        );
    }
}

#[test]
fn link_resolution_digest_keeps_exact_text_and_content_binding_but_not_absolute_root_location() {
    let mut digests = Vec::new();
    for target in [b"a".as_slice(), b"a".as_slice(), b"./a".as_slice()] {
        let f = Fixture::new();
        let manifest = sorted_fixture_manifest(&f, vec![f.file("a", b"abc"), f.link("l", target)]);
        let observed = manifest
            .verify_with_closed_links(&f.root, link_limits())
            .unwrap();
        digests.push((
            manifest.sha256().to_owned(),
            observed.resolution_sha256().to_owned(),
        ));
    }
    assert_eq!(digests[0], digests[1]);
    assert_ne!(digests[0].0, digests[2].0);
    assert_ne!(digests[0].1, digests[2].1);
    let f = Fixture::new();
    let empty = f
        .manifest(vec![])
        .verify_with_closed_links(&f.root, link_limits())
        .unwrap();
    assert_eq!(empty.links(), 0);
    assert_eq!(empty.maximum_dereferences(), 0);
    assert_eq!(empty.resolution_steps(), 0);
    assert_eq!(empty.into_tree().entries(), 0); // Never nonempty execution/environment proof.
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
