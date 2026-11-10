use super::*;
use pt_process::{ProcessRequest, supervise};
// Every positive fixture explicitly creates private test-owned entries, rather
// than depending on the caller's umask or relaxing the product's path guard.
mod fs {
    pub use std::fs::{Permissions, hard_link, metadata, read, rename, set_permissions};
    use std::os::unix::fs::PermissionsExt;
    pub fn create_dir(path: impl AsRef<std::path::Path>) -> std::io::Result<()> {
        std::fs::create_dir(&path)?;
        std::fs::set_permissions(path, Permissions::from_mode(0o700))
    }
    pub fn write(path: impl AsRef<std::path::Path>, raw: impl AsRef<[u8]>) -> std::io::Result<()> {
        std::fs::write(&path, raw)?;
        std::fs::set_permissions(path, Permissions::from_mode(0o600))
    }
}
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::sync::atomic::AtomicI32;
use std::time::Duration;

struct Fixture {
    temp: tempfile::TempDir,
    source: PathBuf,
    retention: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::Builder::new()
            .prefix("pt-artifact-controls-")
            .tempdir_in("/tmp/opencode")
            .unwrap();
        let source = temp.path().join("source");
        let retention = temp.path().join("retained");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&retention).unwrap();
        Self {
            temp,
            source,
            retention,
        }
    }
    fn declare(path: impl Into<PathBuf>, id: &str, required: bool) -> ArtifactDeclaration {
        ArtifactDeclaration {
            artifact_id: id.into(),
            source: path.into(),
            required,
            // Independent fixed content expectation selected before the writer
            // and not derived from the later bridge readiness assertion.
            expected_content: Some(ExpectedContent {
                bytes: 3,
                sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".into(),
            }),
        }
    }
    fn store(&self, declarations: Vec<ArtifactDeclaration>) -> ArtifactStore {
        ArtifactStore::create(
            &self.source,
            &self.retention,
            "private",
            declarations,
            budget(),
        )
        .unwrap()
    }
    fn writers(&self) -> WritersStopped {
        let report = supervise(
            &ProcessRequest {
                executable: "/bin/true".into(),
                args: vec![],
                cwd: self.temp.path().into(),
                timeout: Duration::from_secs(2),
                cleanup_timeout: Duration::from_secs(1),
            },
            &AtomicI32::new(0),
        )
        .unwrap();
        WritersStopped::after_cleanup(&report).unwrap()
    }
    fn claim(id: &str, raw: &[u8], complete: bool) -> ArtifactReady {
        ArtifactReady {
            artifact_id: id.into(),
            sha256: hex(&Sha256::digest(raw)),
            bytes: raw.len() as u64,
            complete,
        }
    }
    fn target(&self, id: &str) -> PathBuf {
        self.retention
            .join("private")
            .join(format!("artifact-{id}"))
    }
}
fn budget() -> RetentionBudget {
    RetentionBudget {
        files: 8,
        bytes: 1024 * 1024,
        per_file_bytes: 512 * 1024,
        deadline: std::time::Instant::now() + Duration::from_secs(30),
    }
}

#[test]
fn actual_owned_bytes_are_independently_copied_hashed_and_published_with_private_permissions() {
    let f = Fixture::new();
    fs::create_dir(f.source.join("λ")).unwrap();
    fs::write(f.source.join("λ/report"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("λ/report", "report", true)]);
    assert!(!store.required_artifacts_satisfied());
    let mut claim = Fixture::claim("report", b"abc", true);
    // Independent fixed SHA-256 test vector, not just the same helper as production.
    claim.sha256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".into();
    let verified = store.commit(&claim, &f.writers()).unwrap();
    assert_eq!(verified.sha256(), claim.sha256);
    assert_eq!(verified.artifact_id(), "report");
    assert_eq!(verified.bytes(), 3);
    assert!(verified.complete());
    assert_eq!(fs::read(f.target("report")).unwrap(), b"abc");
    assert!(store.required_artifacts_satisfied());
    assert_eq!(
        fs::metadata(f.retention.join("private"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    assert_eq!(
        fs::metadata(f.target("report"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(store.reserved_bytes(), 3);
    assert!(!f.retention.join("private/.pending-report").exists());
}

#[test]
fn empty_binary_and_non_utf8_source_names_are_preserved_without_path_normalization() {
    for (index, raw) in [
        b"".as_slice(),
        b"\0\xff\x80\r\ncontrol-looking bytes".as_slice(),
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new();
        let name = OsString::from_vec(vec![b'r', 0xff, b'0' + index as u8]);
        fs::write(f.source.join(&name), raw).unwrap();
        let mut declaration = Fixture::declare(PathBuf::from(name), "raw", true);
        declaration.expected_content = None; // Unknown opaque content is retained, never required-complete.
        let mut store = f.store(vec![declaration]);
        store
            .commit(&Fixture::claim("raw", raw, true), &f.writers())
            .unwrap();
        assert_eq!(fs::read(f.target("raw")).unwrap(), *raw);
        assert!(!store.required_artifacts_satisfied());
    }
}

#[test]
fn noncanonical_traversal_absolute_duplicate_and_excessive_declarations_fail_before_creating_a_root()
 {
    let f = Fixture::new();
    for path in [
        "../outside",
        "/absolute",
        "a/../b",
        "a/./b",
        "a//b",
        "",
        ".",
    ] {
        assert!(
            ArtifactStore::create(
                &f.source,
                &f.retention,
                "private",
                vec![Fixture::declare(path, "a", true)],
                budget()
            )
            .is_err(),
            "{path}"
        );
    }
    for declarations in [
        vec![
            Fixture::declare("a", "same", true),
            Fixture::declare("b", "same", true),
        ],
        vec![Fixture::declare("a", "bad/path", true)],
        vec![Fixture::declare("a", "_bad", true)],
    ] {
        assert!(
            ArtifactStore::create(&f.source, &f.retention, "private", declarations, budget())
                .is_err()
        );
    }
    assert!(!f.retention.join("private").exists());
    assert!(ArtifactStore::create(&f.source, &f.retention, "bad/root", vec![], budget()).is_err());
}

#[test]
fn positive_finite_storage_file_and_byte_budgets_are_not_inferred_or_silently_expanded() {
    let f = Fixture::new();
    for selected in [
        RetentionBudget {
            files: 0,
            ..budget()
        },
        RetentionBudget {
            files: 1025,
            ..budget()
        },
        RetentionBudget {
            bytes: 0,
            ..budget()
        },
        RetentionBudget {
            bytes: MAX_TOTAL_BYTES + 1,
            ..budget()
        },
        RetentionBudget {
            per_file_bytes: 0,
            ..budget()
        },
        RetentionBudget {
            per_file_bytes: MAX_FILE_BYTES + 1,
            ..budget()
        },
        RetentionBudget {
            bytes: 1,
            ..budget()
        },
    ] {
        assert!(
            ArtifactStore::create(&f.source, &f.retention, "private", vec![], selected).is_err()
        );
    }
    assert!(
        ArtifactStore::create(
            &f.source,
            &f.retention,
            "private",
            vec![
                Fixture::declare("a", "a", true),
                Fixture::declare("b", "b", true)
            ],
            RetentionBudget {
                files: 1,
                ..budget()
            }
        )
        .is_err()
    );
    assert!(!f.retention.join("private").exists());
}

#[test]
fn existing_or_symlinked_retention_paths_are_not_adopted_modified_or_deleted() {
    let f = Fixture::new();
    fs::create_dir(f.retention.join("private")).unwrap();
    fs::write(f.retention.join("private/user-work"), b"keep").unwrap();
    assert!(ArtifactStore::create(&f.source, &f.retention, "private", vec![], budget()).is_err());
    assert_eq!(
        fs::read(f.retention.join("private/user-work")).unwrap(),
        b"keep"
    );
    let alias = f.temp.path().join("linked-parent");
    symlink(&f.retention, &alias).unwrap();
    assert!(ArtifactStore::create(&f.source, &alias, "new", vec![], budget()).is_err());
    let alias = f.temp.path().join("linked-source");
    symlink(&f.source, &alias).unwrap();
    assert!(ArtifactStore::create(&alias, &f.retention, "new", vec![], budget()).is_err());
    fs::set_permissions(&f.retention, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(ArtifactStore::create(&f.source, &f.retention, "new", vec![], budget()).is_err());
    assert!(!f.retention.join("new").exists());
}

#[test]
fn symlink_hardlink_fifo_directory_and_world_writable_source_files_are_rejected_without_following_or_waiting()
 {
    for mode in [
        "symlink",
        "hardlink",
        "fifo",
        "directory",
        "writable",
        "parent_symlink",
    ] {
        let f = Fixture::new();
        fs::write(f.source.join("original"), b"abc").unwrap();
        let path = match mode {
            "symlink" => {
                symlink(f.source.join("original"), f.source.join("input")).unwrap();
                "input"
            }
            "hardlink" => {
                fs::hard_link(f.source.join("original"), f.source.join("input")).unwrap();
                "input"
            }
            "fifo" => {
                nix::unistd::mkfifo(&f.source.join("input"), Mode::S_IRUSR | Mode::S_IWUSR)
                    .unwrap();
                "input"
            }
            "directory" => {
                fs::create_dir(f.source.join("input")).unwrap();
                "input"
            }
            "writable" => {
                fs::write(f.source.join("input"), b"abc").unwrap();
                fs::set_permissions(f.source.join("input"), fs::Permissions::from_mode(0o666))
                    .unwrap();
                "input"
            }
            _ => {
                fs::create_dir(f.source.join("real")).unwrap();
                fs::write(f.source.join("real/input"), b"abc").unwrap();
                symlink("real", f.source.join("alias")).unwrap();
                "alias/input"
            }
        };
        let mut store = f.store(vec![Fixture::declare(path, "a", true)]);
        assert!(
            store
                .commit(&Fixture::claim("a", b"abc", true), &f.writers())
                .is_err(),
            "{mode}"
        );
        assert!(!store.required_artifacts_satisfied());
        assert!(!f.target("a").exists());
        assert!(f.source.join(path).symlink_metadata().is_ok());
    }
}

#[test]
fn wrong_hash_size_and_oversize_claims_remain_failed_without_retry_or_source_repair() {
    for mode in ["hash", "size", "budget", "malformed"] {
        let f = Fixture::new();
        fs::write(f.source.join("input"), b"abc").unwrap();
        let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
        let mut claim = Fixture::claim("a", b"abc", true);
        match mode {
            "hash" => claim.sha256 = "a".repeat(64),
            "size" => claim.bytes = 2,
            "budget" => claim.bytes = MAX_FILE_BYTES + 1,
            _ => claim.sha256 = "A".repeat(64),
        }
        assert!(store.commit(&claim, &f.writers()).is_err());
        assert!(!store.required_artifacts_satisfied());
        assert!(matches!(
            store.state("a"),
            Some(ArtifactState::Failed { .. })
        ));
        assert_eq!(
            store
                .commit(&Fixture::claim("a", b"abc", true), &f.writers())
                .unwrap_err()
                .code(),
            "artifact_already_terminal_no_retry"
        );
        assert_eq!(fs::read(f.source.join("input")).unwrap(), b"abc");
        assert!(!f.target("a").exists());
    }
}

#[test]
fn aggregate_budget_reserves_failed_or_published_copies_and_never_captures_undeclared_outputs() {
    let f = Fixture::new();
    for name in ["one", "two"] {
        fs::write(f.source.join(name), b"abc").unwrap();
    }
    let mut store = ArtifactStore::create(
        &f.source,
        &f.retention,
        "private",
        vec![
            Fixture::declare("one", "one", true),
            Fixture::declare("two", "two", true),
        ],
        RetentionBudget {
            files: 2,
            bytes: 5,
            per_file_bytes: 5,
            deadline: std::time::Instant::now() + Duration::from_secs(30),
        },
    )
    .unwrap();
    assert_eq!(
        store
            .commit(&Fixture::claim("unknown", b"abc", true), &f.writers())
            .unwrap_err()
            .code(),
        "artifact_not_declared"
    );
    store
        .commit(&Fixture::claim("one", b"abc", true), &f.writers())
        .unwrap();
    assert_eq!(
        store
            .commit(&Fixture::claim("two", b"abc", true), &f.writers())
            .unwrap_err()
            .code(),
        "artifact_retention_budget_exceeded"
    );
    assert_eq!(store.reserved_bytes(), 3);
    assert!(!f.target("two").exists());
    assert!(!store.required_artifacts_satisfied());
}

#[test]
fn partial_and_optional_commits_keep_completeness_separate_from_verified_content() {
    let f = Fixture::new();
    fs::write(f.source.join("required"), b"abc").unwrap();
    fs::write(f.source.join("optional"), b"abc").unwrap();
    let mut store = f.store(vec![
        Fixture::declare("required", "required", true),
        Fixture::declare("optional", "optional", false),
    ]);
    store
        .commit(&Fixture::claim("required", b"abc", true), &f.writers())
        .unwrap();
    let optional = store
        .commit(&Fixture::claim("optional", b"abc", false), &f.writers())
        .unwrap();
    assert!(!optional.complete());
    assert!(store.required_artifacts_satisfied());
    let f = Fixture::new();
    fs::write(f.source.join("required"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("required", "required", true)]);
    let partial = store
        .commit(&Fixture::claim("required", b"abc", false), &f.writers())
        .unwrap();
    assert!(!partial.complete());
    assert!(!store.required_artifacts_satisfied());
    assert_eq!(fs::read(f.target("required")).unwrap(), b"abc");
}

#[test]
fn writers_must_be_observably_reaped_with_complete_cleanup_not_merely_zero_exit() {
    let f = Fixture::new();
    let report = supervise(
        &ProcessRequest {
            executable: "/bin/true".into(),
            args: vec![],
            cwd: f.temp.path().into(),
            timeout: Duration::from_secs(2),
            cleanup_timeout: Duration::from_secs(1),
        },
        &AtomicI32::new(0),
    )
    .unwrap();
    assert!(WritersStopped::after_cleanup(&report).unwrap().pid() > 0);
    for mode in 0..4 {
        let mut bad = report.clone();
        match mode {
            0 => {
                bad.cleanup = Cleanup::Uncertain {
                    detail: "synthetic uncertainty".into(),
                }
            }
            1 => bad.leader_status = None,
            2 => bad.pid = None,
            _ => {
                bad.termination = Termination::LaunchError {
                    detail: "not observed".into(),
                }
            }
        }
        assert!(WritersStopped::after_cleanup(&bad).is_err());
    }
}

#[test]
fn same_stat_source_mutation_or_leaf_replacement_after_open_cannot_publish() {
    for mode in ["same_stat", "replace"] {
        let f = Fixture::new();
        fs::write(f.source.join("input"), b"abc").unwrap();
        let before = fs::metadata(f.source.join("input")).unwrap();
        let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
        let result = store.commit_with(
            &Fixture::claim("a", b"abc", true),
            &f.writers(),
            &mut |step| {
                if matches!(step, Step::AfterCopy) {
                    if mode == "replace" {
                        fs::rename(f.source.join("input"), f.source.join("old-input")).unwrap();
                    }
                    fs::write(f.source.join("input"), b"xyz").unwrap();
                    File::open(f.source.join("input"))
                        .unwrap()
                        .set_times(
                            std::fs::FileTimes::new().set_modified(before.modified().unwrap()),
                        )
                        .unwrap();
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert!(!f.target("a").exists());
        assert_eq!(fs::read(f.source.join("input")).unwrap(), b"xyz");
        assert!(!store.required_artifacts_satisfied());
    }
}

#[test]
fn staging_substitution_or_destination_race_never_overwrites_or_deletes_foreign_bytes() {
    for mode in ["pending", "target"] {
        let f = Fixture::new();
        fs::write(f.source.join("input"), b"abc").unwrap();
        let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
        let result = store.commit_with(
            &Fixture::claim("a", b"abc", true),
            &f.writers(),
            &mut |step| {
                if matches!(step, Step::BeforeRename) {
                    let target = if mode == "pending" {
                        let path = f.retention.join("private/.pending-a");
                        fs::rename(&path, f.retention.join("private/original-pending")).unwrap();
                        path
                    } else {
                        f.target("a")
                    };
                    fs::write(target, b"foreign bytes must remain").unwrap();
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        let foreign = if mode == "pending" {
            f.retention.join("private/.pending-a")
        } else {
            f.target("a")
        };
        assert_eq!(fs::read(foreign).unwrap(), b"foreign bytes must remain");
        assert!(!store.required_artifacts_satisfied());
    }
}

#[test]
fn ancestor_substitution_is_detected_while_operations_remain_anchored_to_the_original_directory() {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
    let result = store.commit_with(
        &Fixture::claim("a", b"abc", true),
        &f.writers(),
        &mut |step| {
            if matches!(step, Step::AfterCopy) {
                fs::rename(
                    f.retention.join("private"),
                    f.retention.join("original-private"),
                )
                .unwrap();
                fs::create_dir(f.retention.join("private")).unwrap();
                fs::write(f.retention.join("private/foreign"), b"keep").unwrap();
            }
            Ok(())
        },
    );
    assert!(result.is_err());
    assert_eq!(
        fs::read(f.retention.join("private/foreign")).unwrap(),
        b"keep"
    );
    assert!(f.retention.join("original-private/.pending-a").exists());
    assert!(!f.target("a").exists());
}

#[test]
fn lost_publication_return_stays_failed_even_when_complete_looking_published_bytes_exist() {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
    let error = store
        .commit_with(
            &Fixture::claim("a", b"abc", true),
            &f.writers(),
            &mut |step| {
                if matches!(step, Step::AfterRename) {
                    Err(ArtifactError::new("synthetic_publication_return_loss"))
                } else {
                    Ok(())
                }
            },
        )
        .unwrap_err();
    assert_eq!(error.code(), "synthetic_publication_return_loss");
    assert_eq!(fs::read(f.target("a")).unwrap(), b"abc");
    assert!(matches!(
        store.state("a"),
        Some(ArtifactState::Failed {
            publication_may_exist: true,
            ..
        })
    ));
    assert!(!store.required_artifacts_satisfied());
    assert!(
        store
            .commit(&Fixture::claim("a", b"abc", true), &f.writers())
            .is_err()
    );
}

#[test]
fn post_rename_same_size_byte_edits_are_independently_rehashed_not_assumed_valid_from_inode_and_size()
 {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
    let error = store
        .commit_with(
            &Fixture::claim("a", b"abc", true),
            &f.writers(),
            &mut |step| {
                if matches!(step, Step::AfterRename) {
                    fs::write(f.target("a"), b"xyz").unwrap();
                }
                Ok(())
            },
        )
        .unwrap_err();
    assert_eq!(error.code(), "artifact_published_readback_mismatch");
    assert_eq!(fs::read(f.target("a")).unwrap(), b"xyz");
    assert!(!store.required_artifacts_satisfied());
}

#[test]
fn bounded_copy_io_failure_preserves_partial_state_and_never_tries_a_second_write_or_publish() {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
    let error = store
        .commit_with(
            &Fixture::claim("a", b"abc", true),
            &f.writers(),
            &mut |step| {
                if matches!(step, Step::BeforeCopy) {
                    Err(ArtifactError::io(
                        "synthetic_storage_full",
                        std::io::Error::from_raw_os_error(nix::libc::ENOSPC),
                    ))
                } else {
                    Ok(())
                }
            },
        )
        .unwrap_err();
    assert_eq!(error.code(), "synthetic_storage_full");
    assert_eq!(store.reserved_bytes(), 3);
    assert!(f.retention.join("private/.pending-a").exists());
    assert!(!f.target("a").exists());
    assert!(
        store
            .commit(&Fixture::claim("a", b"abc", true), &f.writers())
            .is_err()
    );
}

#[test]
fn bridge_readiness_alone_never_proves_required_completeness_or_waives_independent_expectations() {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    let mut declaration = Fixture::declare("input", "a", true);
    declaration.expected_content = None;
    let mut store = f.store(vec![declaration]);
    assert!(!store.required_artifacts_checkable());
    let retained = store
        .commit(&Fixture::claim("a", b"abc", true), &f.writers())
        .unwrap();
    assert!(retained.ready_complete_claim());
    assert!(!retained.complete());
    assert!(!store.required_artifacts_satisfied());
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"xyz").unwrap();
    let mut store = f.store(vec![Fixture::declare("input", "a", true)]);
    assert!(store.required_artifacts_checkable());
    assert_eq!(
        store
            .commit(&Fixture::claim("a", b"xyz", true), &f.writers())
            .unwrap_err()
            .code(),
        "artifact_coordinator_expected_content_mismatch"
    );
    assert!(!f.target("a").exists());
    assert!(!store.required_artifacts_satisfied());
}

#[test]
fn an_expired_deadline_or_stalled_copy_cannot_reset_the_store_window_or_publish_success() {
    let f = Fixture::new();
    fs::write(f.source.join("input"), b"abc").unwrap();
    assert!(
        ArtifactStore::create(
            &f.source,
            &f.retention,
            "private",
            vec![Fixture::declare("input", "a", true)],
            RetentionBudget {
                deadline: Instant::now(),
                ..budget()
            }
        )
        .is_err()
    );
    assert!(!f.retention.join("private").exists());
    for after_rename in [false, true] {
        let f = Fixture::new();
        fs::write(f.source.join("input"), b"abc").unwrap();
        let mut store = ArtifactStore::create(
            &f.source,
            &f.retention,
            "private",
            vec![Fixture::declare("input", "a", true)],
            RetentionBudget {
                deadline: Instant::now() + Duration::from_secs(1),
                ..budget()
            },
        )
        .unwrap();
        let error = store
            .commit_with(
                &Fixture::claim("a", b"abc", true),
                &f.writers(),
                &mut |step| {
                    if (!after_rename && matches!(step, Step::BeforeCopy))
                        || (after_rename && matches!(step, Step::AfterRename))
                    {
                        std::thread::sleep(Duration::from_millis(1100));
                    }
                    Ok(())
                },
            )
            .unwrap_err();
        assert_eq!(error.code(), "artifact_absolute_deadline_expired");
        assert!(!store.required_artifacts_satisfied());
        assert_eq!(f.target("a").exists(), after_rename);
        assert!(
            matches!(store.state("a"),Some(ArtifactState::Failed{publication_may_exist,..}) if *publication_may_exist==after_rename)
        );
        assert_eq!(
            store
                .commit(&Fixture::claim("a", b"abc", true), &f.writers())
                .unwrap_err()
                .code(),
            "artifact_already_terminal_no_retry"
        );
    }
}
