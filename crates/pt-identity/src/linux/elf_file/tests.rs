use super::super::TreeLimits;
use super::*;
use std::fs::{self, FileTimes};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};
use std::time::Duration;

fn limits() -> ElfLimits {
    ElfLimits {
        program_headers: 16,
        dynamic_entries: 16,
        needed: 16,
        string_table_bytes: 1024,
        projected_string_bytes: 1024,
    }
}
fn image() -> Vec<u8> {
    let mut raw = vec![0; 131103];
    raw[..8].copy_from_slice(b"\x7fELF\x02\x01\x01\0");
    for (offset, value) in [(16, 2u16), (18, 62), (52, 64), (54, 56), (56, 1)] {
        raw[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
    }
    for (offset, value) in [(20, 1u32), (64, 1), (68, 4)] {
        raw[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    for (offset, value) in [
        (24, 0x400100u64),
        (32, 64),
        (80, 0x400000),
        (88, 0x400000),
        (96, raw.len() as u64),
        (104, raw.len() as u64),
        (112, 1),
    ] {
        raw[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    raw
}
fn directory(path: &Path) {
    fs::create_dir(path).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
}
struct Fixture {
    temp: tempfile::TempDir,
    root: PathBuf,
    raw: Vec<u8>,
    entries: Vec<TreeEntry>,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::Builder::new()
            .prefix("pt-live-elf-file-")
            .tempdir_in("/tmp/opencode")
            .unwrap();
        let root = temp.path().join("tree");
        directory(&root);
        directory(&root.join("d"));
        let raw = image();
        fs::write(root.join("d/image"), &raw).unwrap();
        fs::set_permissions(root.join("d/image"), fs::Permissions::from_mode(0o600)).unwrap();
        let info = fs::metadata(root.join("d/image")).unwrap();
        let entries = vec![
            TreeEntry {
                path: "d".into(),
                mode: 0o700,
                kind: TreeKind::Directory,
            },
            TreeEntry {
                path: "d/image".into(),
                mode: 0o600,
                kind: TreeKind::File {
                    bytes: raw.len() as u64,
                    mtime_ns: info.mtime() as i128 * 1_000_000_000 + info.mtime_nsec() as i128,
                    sha256: Sha256::digest(&raw).into(),
                },
            },
        ];
        Self {
            temp,
            root,
            raw,
            entries,
        }
    }
    fn path(&self) -> PathBuf {
        self.root.join("d/image")
    }
    fn manifest(&self) -> TreeManifest {
        TreeManifest::new(
            0o700,
            self.entries.clone(),
            TreeLimits {
                entries: 100,
                per_file_bytes: 1024 * 1024,
                total_bytes: 4 * 1024 * 1024,
                path_bytes: 64 * 1024,
                deadline: Instant::now() + Duration::from_secs(20),
            },
        )
        .unwrap()
    }
    fn inspect(&self) -> Result<ElfFileObservation> {
        self.manifest()
            .inspect_live_declared_elf(&self.root, Path::new("d/image"), limits())
    }
}

#[test]
fn native_file_association_retains_root_leaf_and_exact_metadata_with_separate_two_hash_work() {
    let f = Fixture::new();
    let manifest = f.manifest();
    let value = manifest
        .inspect_live_declared_elf(&f.root, Path::new("d/image"), limits())
        .unwrap();
    assert_eq!(value.policy_id(), ELF_FILE_POLICY_ID);
    assert_eq!(value.root(), f.root);
    let root = fs::metadata(&f.root).unwrap();
    let file = fs::metadata(f.path()).unwrap();
    assert_eq!(value.root_device_inode(), (root.dev(), root.ino()));
    assert_eq!(value.file_device_inode(), (file.dev(), file.ino()));
    assert_eq!(value.metadata().manifest_sha256(), manifest.sha256());
    assert_eq!(value.metadata().path(), Path::new("d/image"));
    assert_eq!(
        value.metadata().image_sha256(),
        super::super::hex(&Sha256::digest(&f.raw))
    );
    assert_eq!(value.metadata().bytes_hashed(), f.raw.len() as u64);
    assert_eq!(value.bytes_hashed(), f.raw.len() as u64 * 2);
    assert_eq!(fs::read(f.path()).unwrap(), f.raw);
}

#[test]
fn live_elf_raw_path_bytes_are_not_replaced_or_normalized() {
    let mut f = Fixture::new();
    let name = PathBuf::from(OsString::from_vec(b"d/\xce\xbb-\xff".to_vec()));
    fs::rename(f.path(), f.root.join(&name)).unwrap();
    f.entries[1].path = name.clone();
    let value = f
        .manifest()
        .inspect_live_declared_elf(&f.root, &name, limits())
        .unwrap();
    assert_eq!(
        value.metadata().path().as_os_str().as_bytes(),
        b"d/\xce\xbb-\xff"
    );
}

#[test]
fn nonregular_symlink_fifo_directory_and_hardlinked_leaves_fail_before_file_read() {
    for mode in ["symlink", "fifo", "directory", "hardlink"] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let retained = f.temp.path().join("original");
        if mode == "hardlink" {
            fs::hard_link(f.path(), &retained).unwrap();
        } else {
            fs::rename(f.path(), &retained).unwrap();
            match mode {
                "symlink" => symlink(&retained, f.path()).unwrap(),
                "fifo" => nix::unistd::mkfifo(&f.path(), nix::sys::stat::Mode::S_IRUSR).unwrap(),
                _ => directory(&f.path()),
            }
        }
        let mut opened = 0;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::Opened) {
                    opened += 1;
                }
                Ok(())
            })
            .unwrap_err();
        assert_eq!(
            error.code(),
            "tree_regular_file_or_single_link_required",
            "{mode}: {error}"
        );
        assert_eq!(error.relative_path(), Some(Path::new("d/image")));
        assert_eq!(opened, 0);
        assert_eq!(fs::read(&retained).unwrap(), f.raw);
    }
}

#[test]
fn expected_mode_size_mtime_and_same_stat_content_are_not_repaired_or_inferred() {
    for mode in [
        "root-mode",
        "parent-mode",
        "file-mode",
        "size",
        "mtime",
        "content",
    ] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let times =
            FileTimes::new().set_modified(fs::metadata(f.path()).unwrap().modified().unwrap());
        match mode {
            "root-mode" => fs::set_permissions(&f.root, fs::Permissions::from_mode(0o750)).unwrap(),
            "parent-mode" => {
                fs::set_permissions(f.root.join("d"), fs::Permissions::from_mode(0o750)).unwrap()
            }
            "file-mode" => {
                fs::set_permissions(f.path(), fs::Permissions::from_mode(0o640)).unwrap()
            }
            "size" => fs::write(f.path(), b"different byte length").unwrap(),
            "mtime" => File::open(f.path())
                .unwrap()
                .set_times(FileTimes::new().set_modified(std::time::UNIX_EPOCH))
                .unwrap(),
            _ => {
                let mut raw = f.raw.clone();
                raw[131102] = 1;
                fs::write(f.path(), raw).unwrap();
                File::open(f.path()).unwrap().set_times(times).unwrap();
            }
        }
        let error = manifest
            .inspect_live_declared_elf(&f.root, Path::new("d/image"), limits())
            .unwrap_err();
        assert_eq!(
            error.code(),
            match mode {
                "root-mode" => "tree_root_mode_mismatch",
                "parent-mode" => "elf_file_parent_type_or_mode_mismatch",
                "content" => "elf_declared_image_digest_mismatch",
                _ => "elf_file_declared_metadata_mismatch",
            },
            "{mode}"
        );
        if mode == "content" {
            assert_eq!(fs::read(f.path()).unwrap()[131102], 1);
        }
        if mode == "size" {
            assert_eq!(fs::read(f.path()).unwrap(), b"different byte length");
        }
    }
}

#[test]
fn root_parent_and_undeclared_path_aliases_never_gain_implicit_follow_authority() {
    let f = Fixture::new();
    let manifest = f.manifest();
    let alias = f.temp.path().join("root-alias");
    symlink(&f.root, &alias).unwrap();
    assert_eq!(
        manifest
            .inspect_live_declared_elf(&alias, Path::new("d/image"), limits())
            .unwrap_err()
            .code(),
        "tree_no_follow_open"
    );
    for name in [
        "./d/image",
        "d//image",
        "d/../d/image",
        "/d/image",
        "d/absent",
        "",
    ] {
        assert!(
            manifest
                .inspect_live_declared_elf(
                    &f.temp.path().join("never-opened"),
                    Path::new(name),
                    limits()
                )
                .is_err(),
            "{name}"
        );
    }
    let retained = f.temp.path().join("original-d");
    fs::rename(f.root.join("d"), &retained).unwrap();
    symlink(&retained, f.root.join("d")).unwrap();
    assert_eq!(
        manifest
            .inspect_live_declared_elf(&f.root, Path::new("d/image"), limits())
            .unwrap_err()
            .code(),
        "elf_file_parent_type_or_mode_mismatch"
    );
    assert_eq!(fs::read(retained.join("image")).unwrap(), f.raw);
}

#[test]
fn growth_or_truncation_during_first_read_is_terminal_without_parsing_or_retry() {
    for grow in [false, true] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let mut opens = 0;
        let mut parsed = false;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::Opened) {
                    opens += 1;
                    if grow {
                        let mut file = fs::OpenOptions::new().append(true).open(f.path()).unwrap();
                        std::io::Write::write_all(&mut file, b"extra").unwrap();
                    } else {
                        fs::write(f.path(), b"truncated").unwrap();
                    }
                }
                if matches!(step, Step::AfterParse) {
                    parsed = true;
                }
                Ok(())
            })
            .unwrap_err();
        assert_eq!(
            error.code(),
            if grow {
                "elf_file_grew_during_read"
            } else {
                "elf_declared_image_size_mismatch"
            }
        );
        assert_eq!(opens, 1);
        assert!(!parsed);
    }
}

#[test]
fn after_parse_same_length_edit_and_leaf_replacement_never_publish_file_association() {
    for replace in [false, true] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let mut parsed = 0;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::AfterParse) {
                    parsed += 1;
                    if replace {
                        fs::rename(f.path(), f.temp.path().join("original-image")).unwrap();
                        fs::write(f.path(), &f.raw).unwrap();
                        fs::set_permissions(f.path(), fs::Permissions::from_mode(0o600)).unwrap();
                    } else {
                        let mut raw = f.raw.clone();
                        raw[131102] = 1;
                        fs::write(f.path(), raw).unwrap();
                    }
                }
                Ok(())
            })
            .unwrap_err();
        assert_eq!(error.code(), "elf_file_binding_changed");
        assert_eq!(parsed, 1);
        assert_eq!(fs::read(f.path()).unwrap()[131102], u8::from(!replace));
    }
}

#[test]
fn independent_readback_rejects_different_bytes_with_the_metadata_guard_explicitly_masked() {
    let f = Fixture::new();
    let manifest = f.manifest();
    assert!(f.inspect().is_ok());
    let parent = File::open(f.root.join("d")).unwrap();
    let mut file = File::open(f.path()).unwrap();
    let original = Stamp::from(&stat(&file).unwrap());
    let times = FileTimes::new().set_modified(file.metadata().unwrap().modified().unwrap());
    let mut changed = f.raw.clone();
    changed[131102] = 1;
    fs::write(f.path(), &changed).unwrap();
    file.set_times(times).unwrap();
    // Synthetic guard isolation: adjust only the expected live stamp, not the
    // independent original content hash. No claim of restoring host ctime.
    let masked = Stamp::from(&stat(&file).unwrap());
    assert_eq!(
        (
            masked.dev,
            masked.ino,
            masked.mode,
            masked.bytes,
            masked.mtime
        ),
        (
            original.dev,
            original.ino,
            original.mode,
            original.bytes,
            original.mtime
        )
    );
    let error = readback(
        &mut file,
        &parent,
        Path::new("image"),
        &masked,
        &f.entries[1],
        manifest.limits.deadline,
        &mut |_| Ok(()),
    )
    .unwrap_err();
    assert_eq!(error.code(), "elf_file_readback_mismatch");
    assert_eq!(fs::read(f.path()).unwrap(), changed);
}

#[test]
fn root_or_parent_substitution_after_readback_fails_even_with_original_fd_bytes_intact() {
    for replace_root in [false, true] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let original = f.temp.path().join("retained-original");
        let mut reached = false;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::BeforeReturn) {
                    reached = true;
                    let target = if replace_root {
                        f.root.clone()
                    } else {
                        f.root.join("d")
                    };
                    fs::rename(&target, &original).unwrap();
                    directory(&target);
                    if replace_root {
                        directory(&target.join("d"));
                    }
                    fs::write(f.path(), b"foreign replacement retained").unwrap();
                }
                Ok(())
            })
            .unwrap_err();
        assert!(reached);
        assert_eq!(
            error.code(),
            if replace_root {
                "tree_ancestor_binding_changed"
            } else {
                "elf_file_root_changed"
            }
        );
        assert_eq!(fs::read(f.path()).unwrap(), b"foreign replacement retained");
        assert_eq!(
            fs::read(original.join(if replace_root { "d/image" } else { "image" })).unwrap(),
            f.raw
        );
    }
}

#[test]
fn growth_truncation_or_unread_byte_edits_during_readback_cannot_return_an_observation() {
    for mode in ["grow", "truncate", "edit-unread"] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let mut injected = false;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::ReadbackChunk) && !injected {
                    injected = true;
                    match mode {
                        "grow" => {
                            let mut file =
                                fs::OpenOptions::new().append(true).open(f.path()).unwrap();
                            std::io::Write::write_all(&mut file, b"extra").unwrap();
                        }
                        "truncate" => fs::write(f.path(), b"short").unwrap(),
                        _ => {
                            let mut raw = f.raw.clone();
                            raw[131102] = 1;
                            fs::write(f.path(), raw).unwrap();
                        }
                    }
                }
                Ok(())
            })
            .unwrap_err();
        assert!(injected);
        assert_eq!(
            error.code(),
            if mode == "grow" {
                "elf_file_grew_during_readback"
            } else {
                "elf_file_readback_mismatch"
            }
        );
    }
}

#[test]
fn final_named_leaf_binding_is_rechecked_after_the_second_complete_hash() {
    let f = Fixture::new();
    let manifest = f.manifest();
    let mut reached = false;
    let error = manifest
        .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
            if matches!(step, Step::BeforeReturn) {
                reached = true;
                fs::rename(f.path(), f.temp.path().join("original-image")).unwrap();
                fs::write(f.path(), b"foreign bytes retained").unwrap();
            }
            Ok(())
        })
        .unwrap_err();
    assert!(reached);
    assert_eq!(error.code(), "elf_file_binding_changed");
    assert_eq!(fs::read(f.path()).unwrap(), b"foreign bytes retained");
}

#[test]
fn injected_read_failures_are_terminal_and_preserve_the_actual_error_without_reopening() {
    for second in [false, true] {
        let f = Fixture::new();
        let manifest = f.manifest();
        let mut opened = 0;
        let mut failed = false;
        let error = manifest
            .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
                if matches!(step, Step::Opened) {
                    opened += 1;
                }
                if matches!(
                    (step, second),
                    (Step::FirstReadChunk, false) | (Step::ReadbackChunk, true)
                ) {
                    failed = true;
                    return Err(IdentityError::io(
                        "synthetic_live_elf_read_failure",
                        std::io::Error::from_raw_os_error(nix::libc::EIO),
                    ));
                }
                Ok(())
            })
            .unwrap_err();
        assert!(failed);
        assert_eq!(opened, 1);
        assert_eq!(error.code(), "synthetic_live_elf_read_failure");
        assert_eq!(fs::read(f.path()).unwrap(), f.raw);
    }
}

#[test]
fn invalid_limits_missing_declarations_and_expired_original_deadlines_fail_before_opening() {
    let f = Fixture::new();
    let mut manifest = f.manifest();
    let mut opened = false;
    for path in [Path::new("d/absent"), Path::new("d")] {
        assert_eq!(
            manifest
                .inspect_live_declared_elf(&f.root, path, limits())
                .unwrap_err()
                .code(),
            "elf_image_not_declared_regular_file"
        );
    }
    assert_eq!(
        manifest
            .inspect_live_declared_elf(
                &f.root,
                Path::new("d/image"),
                ElfLimits {
                    program_headers: 0,
                    ..limits()
                }
            )
            .unwrap_err()
            .code(),
        "elf_limits_invalid"
    );
    manifest.limits.deadline = Instant::now();
    let error = manifest
        .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |_| {
            opened = true;
            Ok(())
        })
        .unwrap_err();
    assert_eq!(error.code(), "tree_absolute_deadline_expired");
    assert!(!opened);
}

#[test]
fn parse_progress_never_resets_the_original_deadline_before_readback() {
    let f = Fixture::new();
    let mut manifest = f.manifest();
    let deadline = Instant::now() + Duration::from_secs(2);
    manifest.limits.deadline = deadline;
    let mut reached = false;
    let mut readback_reached = false;
    let error = manifest
        .inspect_live_elf_with(&f.root, Path::new("d/image"), limits(), &mut |step| {
            if matches!(step, Step::AfterParse) {
                reached = true;
                std::thread::sleep(
                    deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(10),
                );
            }
            if matches!(step, Step::ReadbackChunk) {
                readback_reached = true;
            }
            Ok(())
        })
        .unwrap_err();
    assert!(reached);
    assert!(!readback_reached);
    assert_eq!(error.code(), "tree_absolute_deadline_expired");
}

#[test]
fn single_file_observation_does_not_enumerate_or_certify_unrelated_manifest_entries() {
    let f = Fixture::new();
    let manifest = f.manifest();
    fs::write(
        f.root.join("extra-input"),
        b"not certified by a leaf observation",
    )
    .unwrap();
    let leaf = manifest
        .inspect_live_declared_elf(&f.root, Path::new("d/image"), limits())
        .unwrap();
    assert_eq!(leaf.metadata().manifest_sha256(), manifest.sha256());
    assert_eq!(
        manifest.verify(&f.root).unwrap_err().code(),
        "tree_unexpected_entry"
    );
    assert_eq!(
        fs::read(f.root.join("extra-input")).unwrap(),
        b"not certified by a leaf observation"
    );
}

#[test]
fn declared_matching_non_elf_bytes_do_not_gain_metadata_from_a_valid_file_binding() {
    let mut f = Fixture::new();
    fs::write(f.path(), b"not ELF").unwrap();
    let info = fs::metadata(f.path()).unwrap();
    f.entries[1].kind = TreeKind::File {
        bytes: 7,
        mtime_ns: info.mtime() as i128 * 1_000_000_000 + info.mtime_nsec() as i128,
        sha256: Sha256::digest(b"not ELF").into(),
    };
    assert_eq!(f.inspect().unwrap_err().code(), "elf_header_truncated");
}
