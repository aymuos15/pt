use nix::fcntl::{AtFlags, OFlag, RenameFlags, openat, renameat2};
use nix::sys::stat::{FileStat, Mode, fstat, fstatat, mkdirat};
use nix::unistd::geteuid;
use pt_process::{Cleanup, LeaderStatus, ProcessReport, Termination};
use pt_protocol::ArtifactReady;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant};

mod junit;
pub use junit::{JUNIT_POLICY_ID, JunitExpectation, JunitLimits, JunitPolicy};

const MAX_FILE_BYTES: u64 = 128 * 1024 * 1024;
const MAX_TOTAL_BYTES: u64 = 512 * 1024 * 1024;
const MAX_FILES: usize = 1024;
const MAX_COMPONENTS: usize = 24;

#[derive(Debug)]
pub struct ArtifactError {
    code: &'static str,
    detail: Option<String>,
}

impl ArtifactError {
    pub fn code(&self) -> &'static str {
        self.code
    }
    fn new(code: &'static str) -> Self {
        Self { code, detail: None }
    }
    fn io(code: &'static str, error: impl fmt::Display) -> Self {
        Self {
            code,
            detail: Some(error.to_string()),
        }
    }
}
impl fmt::Display for ArtifactError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.code)?;
        if let Some(detail) = &self.detail {
            write!(f, ": {detail}")?;
        }
        Ok(())
    }
}
impl Error for ArtifactError {}
type Result<T> = std::result::Result<T, ArtifactError>;

fn require(value: bool, code: &'static str) -> Result<()> {
    if value {
        Ok(())
    } else {
        Err(ArtifactError::new(code))
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn components(path: &Path, absolute: bool) -> Result<Vec<OsString>> {
    require(
        path.is_absolute() == absolute
            && path.as_os_str().as_bytes().len() <= 4096
            && !path.as_os_str().as_bytes().contains(&0),
        "artifact_path_unsupported",
    )?;
    let mut names = Vec::new();
    for component in path.components() {
        match component {
            Component::RootDir if absolute => {}
            Component::Normal(name) => names.push(name.to_owned()),
            _ => return Err(ArtifactError::new("artifact_path_not_canonical")),
        }
    }
    require(
        names.len() <= MAX_COMPONENTS && (absolute || !names.is_empty()),
        "artifact_path_depth_or_empty",
    )?;
    let canonical = names.iter().fold(
        if absolute {
            PathBuf::from("/")
        } else {
            PathBuf::new()
        },
        |mut path, name| {
            path.push(name);
            path
        },
    );
    require(
        canonical.as_os_str() == path.as_os_str(),
        "artifact_path_not_canonical",
    )?;
    Ok(names)
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct DirectoryStamp {
    dev: u64,
    ino: u64,
    mode: u32,
    uid: u32,
    gid: u32,
}
impl DirectoryStamp {
    fn from(info: &FileStat) -> Result<Self> {
        require(
            info.st_mode & nix::libc::S_IFMT == nix::libc::S_IFDIR,
            "artifact_not_directory",
        )?;
        Ok(Self {
            dev: info.st_dev,
            ino: info.st_ino,
            mode: info.st_mode,
            uid: info.st_uid,
            gid: info.st_gid,
        })
    }
}
struct Link {
    name: OsString,
    file: File,
    stamp: DirectoryStamp,
}
struct DirectoryChain {
    anchor: File,
    links: Vec<Link>,
}
impl DirectoryChain {
    fn open(path: &Path) -> Result<Self> {
        let names = components(path, true)?;
        let mut value = Self {
            anchor: File::open("/").map_err(|e| ArtifactError::io("artifact_root_open", e))?,
            links: Vec::new(),
        };
        for name in names {
            value.push(name)?;
        }
        value.validate()?;
        Ok(value)
    }
    fn tail(&self) -> &File {
        self.links.last().map_or(&self.anchor, |link| &link.file)
    }
    fn push(&mut self, name: OsString) -> Result<()> {
        let fd = openat(
            self.tail(),
            name.as_os_str(),
            OFlag::O_RDONLY | OFlag::O_DIRECTORY | OFlag::O_NOFOLLOW | OFlag::O_CLOEXEC,
            Mode::empty(),
        )
        .map_err(|e| ArtifactError::io("artifact_directory_open", e))?;
        let file = File::from(fd);
        let info = fstat(&file).map_err(|e| ArtifactError::io("artifact_directory_stat", e))?;
        self.links.push(Link {
            name,
            file,
            stamp: DirectoryStamp::from(&info)?,
        });
        Ok(())
    }
    fn duplicate(&self) -> Result<Self> {
        let mut links = Vec::new();
        for link in &self.links {
            links.push(Link {
                name: link.name.clone(),
                file: link
                    .file
                    .try_clone()
                    .map_err(|e| ArtifactError::io("artifact_directory_duplicate", e))?,
                stamp: link.stamp.clone(),
            });
        }
        Ok(Self {
            anchor: self
                .anchor
                .try_clone()
                .map_err(|e| ArtifactError::io("artifact_directory_duplicate", e))?,
            links,
        })
    }
    fn validate(&self) -> Result<()> {
        let mut parent = &self.anchor;
        for link in &self.links {
            let named = fstatat(parent, link.name.as_os_str(), AtFlags::AT_SYMLINK_NOFOLLOW)
                .map_err(|e| ArtifactError::io("artifact_directory_binding_changed", e))?;
            let opened =
                fstat(&link.file).map_err(|e| ArtifactError::io("artifact_directory_stat", e))?;
            require(
                DirectoryStamp::from(&named)? == link.stamp
                    && DirectoryStamp::from(&opened)? == link.stamp,
                "artifact_directory_binding_changed",
            )?;
            parent = &link.file;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct FileStamp {
    dev: u64,
    ino: u64,
    mode: u32,
    uid: u32,
    gid: u32,
    links: u64,
    bytes: i64,
    mtime: (i64, i64),
    ctime: (i64, i64),
}
impl FileStamp {
    fn from(info: &FileStat) -> Result<Self> {
        require(
            info.st_mode & nix::libc::S_IFMT == nix::libc::S_IFREG
                && info.st_nlink == 1
                && info.st_uid == geteuid().as_raw()
                && info.st_mode & 0o022 == 0
                && info.st_size >= 0
                && info.st_size as u64 <= MAX_FILE_BYTES,
            "artifact_file_type_owner_link_or_bound",
        )?;
        Ok(Self {
            dev: info.st_dev,
            ino: info.st_ino,
            mode: info.st_mode,
            uid: info.st_uid,
            gid: info.st_gid,
            links: info.st_nlink,
            bytes: info.st_size,
            mtime: (info.st_mtime, info.st_mtime_nsec),
            ctime: (info.st_ctime, info.st_ctime_nsec),
        })
    }
}
fn stamp(file: &File) -> Result<FileStamp> {
    FileStamp::from(&fstat(file).map_err(|e| ArtifactError::io("artifact_file_stat", e))?)
}
fn named_stamp(parent: &File, name: &Path) -> Result<FileStamp> {
    FileStamp::from(
        &fstatat(parent, name, AtFlags::AT_SYMLINK_NOFOLLOW)
            .map_err(|e| ArtifactError::io("artifact_file_binding_changed", e))?,
    )
}

/// Positive limits apply to Rust-retained copies, not arbitrary pytest writes.
#[derive(Clone, Copy, Debug)]
pub struct RetentionBudget {
    pub files: usize,
    pub bytes: u64,
    pub per_file_bytes: u64,
    /// One explicit local-monotonic deadline for this store's whole lifetime.
    pub deadline: Instant,
}
impl RetentionBudget {
    fn validate(self) -> Result<()> {
        require(
            self.deadline
                .checked_duration_since(Instant::now())
                .is_some_and(|remaining| {
                    !remaining.is_zero() && remaining <= Duration::from_secs(3600)
                }),
            "artifact_retention_deadline_invalid",
        )?;
        require(
            (1..=MAX_FILES).contains(&self.files)
                && (1..=MAX_TOTAL_BYTES).contains(&self.bytes)
                && (1..=MAX_FILE_BYTES).contains(&self.per_file_bytes)
                && self.per_file_bytes <= self.bytes,
            "artifact_retention_budget_invalid",
        )
    }
}

/// Source paths are explicitly coordinator-owned request data, never bridge paths.
#[derive(Clone, Debug)]
pub struct ArtifactDeclaration {
    pub artifact_id: String,
    pub source: PathBuf,
    pub required: bool,
    /// Optional coordinator-owned exact content contract, independent of ready
    /// claims. None permits content retention but cannot satisfy required output.
    pub expected_content: Option<ExpectedContent>,
    /// Explicit pinned formatter policy; this alone is not runtime evidence.
    pub junit_policy: Option<JunitPolicy>,
}

#[derive(Clone, Debug)]
pub struct ExpectedContent {
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Clone, Debug)]
pub struct VerifiedArtifact {
    artifact_id: String,
    sha256: String,
    bytes: u64,
    complete: bool,
    ready_complete_claim: bool,
}
impl VerifiedArtifact {
    pub fn artifact_id(&self) -> &str {
        &self.artifact_id
    }
    pub fn sha256(&self) -> &str {
        &self.sha256
    }
    pub fn bytes(&self) -> u64 {
        self.bytes
    }
    pub fn complete(&self) -> bool {
        self.complete
    }
    pub fn ready_complete_claim(&self) -> bool {
        self.ready_complete_claim
    }
}

#[derive(Clone, Debug)]
pub enum ArtifactState {
    Pending,
    Committed(VerifiedArtifact),
    Failed {
        code: &'static str,
        publication_may_exist: bool,
    },
}

/// Constructed only after checking the caller's actually returned native process
/// report. This is not authentication of arbitrary same-user code or of a report
/// the trusted caller fabricated; request/process association remains its job.
pub struct WritersStopped {
    pid: u32,
}
impl WritersStopped {
    pub fn after_cleanup(process: &ProcessReport) -> Result<Self> {
        require(
            process.cleanup == Cleanup::Complete
                && process.pid.is_some_and(|pid| pid > 0)
                && process.leader_status.is_some(),
            "artifact_writers_not_reaped_or_cleanup_uncertain",
        )?;
        require(
            matches!(
                process.termination,
                Termination::ProcessExited
                    | Termination::BackendTerminated
                    | Termination::Timeout
                    | Termination::Interrupted { .. }
            ),
            "artifact_process_end_not_observed",
        )?;
        require(
            match &process.leader_status {
                Some(LeaderStatus::Exited { code }) => {
                    (0..=255).contains(code)
                        && process.termination != Termination::BackendTerminated
                }
                Some(LeaderStatus::Signaled { signal, .. }) => {
                    (1..=64).contains(signal) && process.termination != Termination::ProcessExited
                }
                None => false,
            },
            "artifact_process_status_contradiction",
        )?;
        Ok(Self {
            pid: process.pid.expect("positive observed PID required"),
        })
    }
    pub fn pid(&self) -> u32 {
        self.pid
    }
}

#[derive(Clone, Copy)]
enum Step {
    BeforeCopy,
    AfterCopy,
    BeforeValidation,
    AfterValidation,
    BeforeRename,
    AfterRename,
}

/// Private no-overwrite artifact retention only. Required-artifact satisfaction
/// never implies full work, complete environment, cleanup or current generation.
pub struct ArtifactStore {
    sources: DirectoryChain,
    retained: DirectoryChain,
    declarations: Vec<ArtifactDeclaration>,
    states: HashMap<String, ArtifactState>,
    budget: RetentionBudget,
    reserved_bytes: u64,
}
impl ArtifactStore {
    pub fn create(
        source_root: &Path,
        retention_parent: &Path,
        private_name: &str,
        declarations: Vec<ArtifactDeclaration>,
        budget: RetentionBudget,
    ) -> Result<Self> {
        budget.validate()?;
        require(
            identifier(private_name) && declarations.len() <= budget.files,
            "artifact_declaration_bound",
        )?;
        let mut states = HashMap::new();
        for value in &declarations {
            require(
                identifier(&value.artifact_id) && !states.contains_key(&value.artifact_id),
                "artifact_declaration_id_invalid_or_duplicate",
            )?;
            components(&value.source, false)?;
            if let Some(expected) = &value.expected_content {
                require(
                    expected.bytes <= budget.per_file_bytes && sha256(&expected.sha256),
                    "artifact_expected_content_invalid",
                )?;
            }
            require(
                value.expected_content.is_none() || value.junit_policy.is_none(),
                "artifact_completeness_policy_conflict",
            )?;
            if let Some(policy) = &value.junit_policy {
                require(
                    policy.limits().bytes <= budget.per_file_bytes,
                    "artifact_junit_limit_exceeds_retention_contract",
                )?;
            }
            states.insert(value.artifact_id.clone(), ArtifactState::Pending);
        }
        let sources = DirectoryChain::open(source_root)?;
        let mut retained = DirectoryChain::open(retention_parent)?;
        let info =
            fstat(retained.tail()).map_err(|e| ArtifactError::io("artifact_parent_stat", e))?;
        require(
            info.st_uid == geteuid().as_raw() && info.st_mode & 0o022 == 0,
            "artifact_retention_parent_not_owned_or_writable_by_others",
        )?;
        check_deadline(budget.deadline)?;
        mkdirat(retained.tail(), private_name, Mode::S_IRWXU)
            .map_err(|e| ArtifactError::io("artifact_private_root_create", e))?;
        retained.push(private_name.into())?;
        let info =
            fstat(retained.tail()).map_err(|e| ArtifactError::io("artifact_root_stat", e))?;
        require(
            info.st_uid == geteuid().as_raw() && info.st_mode & 0o7777 == 0o700,
            "artifact_private_root_permissions",
        )?;
        retained.validate()?;
        check_deadline(budget.deadline)?;
        Ok(Self {
            sources,
            retained,
            declarations,
            states,
            budget,
            reserved_bytes: 0,
        })
    }

    pub fn state(&self, id: &str) -> Option<&ArtifactState> {
        self.states.get(id)
    }
    pub fn reserved_bytes(&self) -> u64 {
        self.reserved_bytes
    }
    pub fn required_artifacts_satisfied(&self) -> bool {
        self.declarations.iter().filter(|value|value.required).all(|value|matches!(self.states.get(&value.artifact_id),Some(ArtifactState::Committed(value)) if value.complete))
    }

    /// A declared exact-content or pinned JUnit policy is necessary before a
    /// qualified launch. JUnit still needs independently validated live context.
    pub fn required_artifacts_checkable(&self) -> bool {
        self.declarations
            .iter()
            .filter(|value| value.required)
            .all(|value| value.expected_content.is_some() || value.junit_policy.is_some())
    }

    pub fn commit(
        &mut self,
        claim: &ArtifactReady,
        writers: &WritersStopped,
    ) -> Result<VerifiedArtifact> {
        self.commit_with(claim, writers, &mut |_| Ok(()))
    }

    pub fn commit_with_junit(
        &mut self,
        claim: &ArtifactReady,
        writers: &WritersStopped,
        expectation: &JunitExpectation,
    ) -> Result<VerifiedArtifact> {
        self.commit_context(claim, writers, Some(expectation), &mut |_| Ok(()))
    }

    fn commit_with(
        &mut self,
        claim: &ArtifactReady,
        _writers: &WritersStopped,
        step: &mut impl FnMut(Step) -> Result<()>,
    ) -> Result<VerifiedArtifact> {
        self.commit_context(claim, _writers, None, step)
    }

    fn commit_context(
        &mut self,
        claim: &ArtifactReady,
        _writers: &WritersStopped,
        junit: Option<&JunitExpectation>,
        step: &mut impl FnMut(Step) -> Result<()>,
    ) -> Result<VerifiedArtifact> {
        let declaration = self
            .declarations
            .iter()
            .find(|value| value.artifact_id == claim.artifact_id)
            .cloned()
            .ok_or_else(|| ArtifactError::new("artifact_not_declared"))?;
        require(
            matches!(self.states[&claim.artifact_id], ArtifactState::Pending),
            "artifact_already_terminal_no_retry",
        )?;
        let mut published = false;
        let result = self.commit_inner(&declaration, claim, junit, step, &mut published);
        match &result {
            Ok(value) => {
                self.states.insert(
                    claim.artifact_id.clone(),
                    ArtifactState::Committed(value.clone()),
                );
            }
            Err(error) => {
                self.states.insert(
                    claim.artifact_id.clone(),
                    ArtifactState::Failed {
                        code: error.code(),
                        publication_may_exist: published,
                    },
                );
            }
        }
        result
    }

    fn commit_inner(
        &mut self,
        declaration: &ArtifactDeclaration,
        claim: &ArtifactReady,
        junit: Option<&JunitExpectation>,
        step: &mut impl FnMut(Step) -> Result<()>,
        published: &mut bool,
    ) -> Result<VerifiedArtifact> {
        check_deadline(self.budget.deadline)?;
        if let Some(expectation) = junit {
            require(
                declaration.junit_policy.as_ref() == Some(expectation.policy()),
                "artifact_junit_policy_or_context_mismatch",
            )?;
        }
        require(sha256(&claim.sha256), "artifact_sha256_invalid")?;
        require(
            claim.bytes <= self.budget.per_file_bytes
                && claim.bytes <= self.budget.bytes - self.reserved_bytes,
            "artifact_retention_budget_exceeded",
        )?;
        self.reserved_bytes += claim.bytes; // Failure reserves its partial-copy budget; never retry.
        if let Some(expected) = &declaration.expected_content {
            require(
                expected.bytes == claim.bytes && expected.sha256 == claim.sha256,
                "artifact_coordinator_expected_content_mismatch",
            )?;
        }
        self.sources.validate()?;
        self.retained.validate()?;
        let mut source = self.sources.duplicate()?;
        let mut names = components(&declaration.source, false)?;
        let leaf = PathBuf::from(names.pop().expect("nonempty declared path"));
        for name in names {
            source.push(name)?;
        }
        source.validate()?;
        let fd = openat(
            source.tail(),
            &leaf,
            OFlag::O_RDONLY | OFlag::O_NOFOLLOW | OFlag::O_NONBLOCK | OFlag::O_CLOEXEC,
            Mode::empty(),
        )
        .map_err(|e| ArtifactError::io("artifact_source_open", e))?;
        let mut input = File::from(fd);
        let before = stamp(&input)?;
        require(
            before.bytes as u64 == claim.bytes && named_stamp(source.tail(), &leaf)? == before,
            "artifact_source_claim_or_binding_mismatch",
        )?;
        let pending = PathBuf::from(format!(".pending-{}", claim.artifact_id));
        let target = PathBuf::from(format!("artifact-{}", claim.artifact_id));
        let fd = openat(
            self.retained.tail(),
            &pending,
            OFlag::O_RDWR | OFlag::O_CREAT | OFlag::O_EXCL | OFlag::O_NOFOLLOW | OFlag::O_CLOEXEC,
            Mode::S_IRUSR | Mode::S_IWUSR,
        )
        .map_err(|e| ArtifactError::io("artifact_copy_create", e))?;
        let mut output = File::from(fd);
        step(Step::BeforeCopy)?;
        check_deadline(self.budget.deadline)?;
        let mut digest = Sha256::new();
        let mut count = 0;
        let mut chunk = [0u8; 65536];
        loop {
            check_deadline(self.budget.deadline)?;
            let maximum = std::cmp::min(chunk.len() as u64, claim.bytes - count + 1) as usize;
            let size = input
                .read(&mut chunk[..maximum])
                .map_err(|e| ArtifactError::io("artifact_source_read", e))?;
            check_deadline(self.budget.deadline)?;
            if size == 0 {
                break;
            }
            count += size as u64;
            require(count <= claim.bytes, "artifact_source_grew_during_copy")?;
            digest.update(&chunk[..size]);
            output
                .write_all(&chunk[..size])
                .map_err(|e| ArtifactError::io("artifact_copy_write", e))?;
        }
        require(
            count == claim.bytes && hex(&digest.finalize()) == claim.sha256,
            "artifact_source_digest_or_size_mismatch",
        )?;
        step(Step::AfterCopy)?;
        check_deadline(self.budget.deadline)?;
        require(
            stamp(&input)? == before && named_stamp(source.tail(), &leaf)? == before,
            "artifact_source_changed_during_copy",
        )?;
        source.validate()?;
        output
            .sync_all()
            .map_err(|e| ArtifactError::io("artifact_copy_sync", e))?;
        let copied = stamp(&output)?;
        require(
            copied.bytes as u64 == claim.bytes
                && copied.mode & 0o7777 == 0o600
                && named_stamp(self.retained.tail(), &pending)? == copied,
            "artifact_copy_binding_or_permissions_changed",
        )?;
        output
            .seek(SeekFrom::Start(0))
            .map_err(|e| ArtifactError::io("artifact_copy_seek", e))?;
        let mut digest = Sha256::new();
        let mut verified = 0;
        loop {
            check_deadline(self.budget.deadline)?;
            let maximum = std::cmp::min(chunk.len() as u64, claim.bytes - verified + 1) as usize;
            let size = output
                .read(&mut chunk[..maximum])
                .map_err(|e| ArtifactError::io("artifact_copy_readback", e))?;
            if size == 0 {
                break;
            }
            verified += size as u64;
            require(
                verified <= claim.bytes,
                "artifact_copy_grew_during_readback",
            )?;
            digest.update(&chunk[..size]);
        }
        require(
            verified == claim.bytes
                && hex(&digest.finalize()) == claim.sha256
                && stamp(&output)? == copied,
            "artifact_copy_readback_mismatch",
        )?;
        if let Some(expectation) = junit {
            require(
                claim.bytes <= expectation.policy().limits().bytes,
                "junit_byte_bound",
            )?;
            output
                .seek(SeekFrom::Start(0))
                .map_err(|e| ArtifactError::io("junit_copy_seek", e))?;
            step(Step::BeforeValidation)?;
            check_deadline(self.budget.deadline)?;
            let mut raw = Vec::new();
            raw.try_reserve_exact(claim.bytes as usize)
                .map_err(|e| ArtifactError::io("junit_copy_allocation_bound", e))?;
            loop {
                check_deadline(self.budget.deadline)?;
                let maximum =
                    std::cmp::min(chunk.len() as u64, claim.bytes - raw.len() as u64 + 1) as usize;
                let size = output
                    .read(&mut chunk[..maximum])
                    .map_err(|e| ArtifactError::io("junit_copy_read", e))?;
                require(
                    raw.len() as u64 + size as u64 <= claim.bytes,
                    "junit_copy_length_changed",
                )?;
                if size == 0 {
                    break;
                }
                raw.extend_from_slice(&chunk[..size]);
            }
            require(raw.len() as u64 == claim.bytes, "junit_copy_length_changed")?;
            expectation.validate(&raw, self.budget.deadline)?;
            step(Step::AfterValidation)?;
            require(
                stamp(&output)? == copied,
                "junit_copy_changed_during_validation",
            )?;
        }
        step(Step::BeforeRename)?;
        check_deadline(self.budget.deadline)?;
        source.validate()?;
        self.retained.validate()?;
        require(
            named_stamp(self.retained.tail(), &pending)? == copied,
            "artifact_copy_binding_changed_before_publish",
        )?;
        renameat2(
            self.retained.tail(),
            &pending,
            self.retained.tail(),
            &target,
            RenameFlags::RENAME_NOREPLACE,
        )
        .map_err(|e| ArtifactError::io("artifact_publish_no_replace_failed", e))?;
        *published = true;
        step(Step::AfterRename)?;
        check_deadline(self.budget.deadline)?;
        self.retained
            .tail()
            .sync_all()
            .map_err(|e| ArtifactError::io("artifact_publish_directory_sync_uncertain", e))?;
        self.retained.validate()?;
        // Rename changes ctime, so verify the stable identity/content fields and
        // bind a new post-publication stat rather than assuming its old ctime.
        let final_stamp = named_stamp(self.retained.tail(), &target)?;
        require(
            final_stamp.dev == copied.dev
                && final_stamp.ino == copied.ino
                && final_stamp.bytes == copied.bytes
                && final_stamp.mode == copied.mode
                && final_stamp.uid == copied.uid,
            "artifact_published_identity_changed",
        )?;
        output
            .seek(SeekFrom::Start(0))
            .map_err(|e| ArtifactError::io("artifact_published_seek", e))?;
        let mut digest = Sha256::new();
        let mut verified = 0;
        loop {
            check_deadline(self.budget.deadline)?;
            let maximum = std::cmp::min(chunk.len() as u64, claim.bytes - verified + 1) as usize;
            let size = output
                .read(&mut chunk[..maximum])
                .map_err(|e| ArtifactError::io("artifact_published_readback", e))?;
            if size == 0 {
                break;
            }
            verified += size as u64;
            require(
                verified <= claim.bytes,
                "artifact_published_grew_during_readback",
            )?;
            digest.update(&chunk[..size]);
        }
        require(
            verified == claim.bytes
                && hex(&digest.finalize()) == claim.sha256
                && stamp(&output)? == final_stamp
                && named_stamp(self.retained.tail(), &target)? == final_stamp,
            "artifact_published_readback_mismatch",
        )?;
        self.retained.validate()?;
        check_deadline(self.budget.deadline)?;
        Ok(VerifiedArtifact {
            artifact_id: claim.artifact_id.clone(),
            sha256: claim.sha256.clone(),
            bytes: claim.bytes,
            complete: claim.complete && (declaration.expected_content.is_some() || junit.is_some()),
            ready_complete_claim: claim.complete,
        })
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn check_deadline(deadline: Instant) -> Result<()> {
    require(
        Instant::now() < deadline,
        "artifact_absolute_deadline_expired",
    )
}

#[cfg(test)]
mod tests;
