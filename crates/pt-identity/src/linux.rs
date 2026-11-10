use nix::dir::Dir;
use nix::fcntl::{AtFlags, OFlag, openat, readlinkat};
use nix::sys::stat::{FileStat, Mode, fstat, fstatat};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant};

pub const TREE_POLICY_ID: &str = "linux-declared-tree-content-v1";
mod links;
pub use links::{ClosedLinkObservation, LinkLimits, RELATIVE_LINK_POLICY_ID};
mod elf;
pub use elf::{
    ELF_INPUT_POLICY_ID, ElfDynamicEntry, ElfLimits, ElfLoadInputs, ElfProgramHeader,
    ElfStringInput, ElfStringKind,
};
#[derive(Debug)]
pub struct IdentityError {
    code: &'static str,
    detail: Option<String>,
    path: Option<PathBuf>,
}
impl IdentityError {
    pub fn code(&self) -> &'static str {
        self.code
    }
    pub fn relative_path(&self) -> Option<&Path> {
        self.path.as_deref()
    }
    fn for_path(mut self, path: &Path) -> Self {
        if self.path.is_none() {
            self.path = Some(path.into());
        }
        self
    }
    fn new(code: &'static str) -> Self {
        Self {
            code,
            detail: None,
            path: None,
        }
    }
    fn io(code: &'static str, error: impl fmt::Display) -> Self {
        Self {
            code,
            detail: Some(error.to_string()),
            path: None,
        }
    }
}
impl fmt::Display for IdentityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.code)?;
        if let Some(path) = &self.path {
            write!(f, " at {path:?}")?;
        }
        if let Some(detail) = &self.detail {
            write!(f, ": {detail}")?;
        }
        Ok(())
    }
}
impl Error for IdentityError {}
type Result<T> = std::result::Result<T, IdentityError>;
fn require(value: bool, code: &'static str) -> Result<()> {
    if value {
        Ok(())
    } else {
        Err(IdentityError::new(code))
    }
}
fn check(deadline: Instant) -> Result<()> {
    require(Instant::now() < deadline, "tree_absolute_deadline_expired")
}

#[derive(Clone, Copy, Debug)]
pub struct TreeLimits {
    pub entries: usize,
    pub per_file_bytes: u64,
    pub total_bytes: u64,
    pub path_bytes: usize,
    pub deadline: Instant,
}
impl TreeLimits {
    fn validate(self) -> Result<()> {
        require(
            (1..=100_000).contains(&self.entries)
                && (1..=128 * 1024 * 1024).contains(&self.per_file_bytes)
                && (1..=4 * 1024 * 1024 * 1024).contains(&self.total_bytes)
                && self.per_file_bytes <= self.total_bytes
                && (1..=16 * 1024 * 1024).contains(&self.path_bytes),
            "tree_limits_invalid",
        )?;
        require(
            self.deadline
                .checked_duration_since(Instant::now())
                .is_some_and(|value| !value.is_zero() && value <= Duration::from_secs(3600)),
            "tree_deadline_invalid",
        )
    }
}

#[derive(Clone, Debug)]
pub enum TreeKind {
    Directory,
    /// Link text only; never following a link or claiming its referent is in the
    /// verified input domain. External/dynamic referents need separate identity.
    Symlink {
        target: Vec<u8>,
    },
    File {
        bytes: u64,
        mtime_ns: i128,
        sha256: [u8; 32],
    },
}
#[derive(Clone, Debug)]
pub struct TreeEntry {
    pub path: PathBuf,
    pub mode: u32,
    pub kind: TreeKind,
}

/// Trusted coordinator-owned expected bytes/metadata, not a RECORD/lockfile
/// automatically promoted into installed truth. Parent directories are explicit.
pub struct TreeManifest {
    root_mode: u32,
    entries: BTreeMap<Vec<u8>, TreeEntry>,
    digest: String,
    limits: TreeLimits,
}
impl TreeManifest {
    pub fn new(root_mode: u32, entries: Vec<TreeEntry>, limits: TreeLimits) -> Result<Self> {
        limits.validate()?;
        require(
            root_mode <= 0o7777 && entries.len() <= limits.entries,
            "tree_manifest_bound_or_mode",
        )?;
        let mut index = BTreeMap::new();
        let mut previous = Vec::new();
        let mut paths = 0usize;
        let mut total = 0u64;
        let mut digest = Sha256::new();
        digest.update(b"pt-tree-manifest-v1\0");
        digest.update(root_mode.to_be_bytes());
        digest.update((entries.len() as u64).to_be_bytes());
        for entry in entries {
            check(limits.deadline)?;
            let names = components(&entry.path, false)?;
            let raw = entry.path.as_os_str().as_bytes().to_vec();
            require(
                raw > previous && entry.mode <= 0o7777,
                "tree_manifest_order_duplicate_or_mode",
            )?;
            previous = raw.clone();
            paths += raw.len();
            require(paths <= limits.path_bytes, "tree_manifest_path_byte_bound")?;
            if names.len() > 1 {
                let parent = entry.path.parent().expect("multi-component parent");
                require(
                    index
                        .get(parent.as_os_str().as_bytes())
                        .is_some_and(|value: &TreeEntry| matches!(value.kind, TreeKind::Directory)),
                    "tree_manifest_parent_not_declared_directory",
                )?;
            }
            field(&mut digest, &raw);
            digest.update(entry.mode.to_be_bytes());
            match &entry.kind {
                TreeKind::Directory => digest.update([0]),
                TreeKind::Symlink { target } => {
                    require(
                        !target.is_empty() && target.len() <= 4096 && !target.contains(&0),
                        "tree_manifest_link_target_bound",
                    )?;
                    digest.update([1]);
                    field(&mut digest, target);
                }
                TreeKind::File {
                    bytes,
                    mtime_ns,
                    sha256,
                } => {
                    require(
                        *bytes <= limits.per_file_bytes && *bytes <= limits.total_bytes - total,
                        "tree_manifest_file_byte_bound",
                    )?;
                    total += bytes;
                    digest.update([2]);
                    digest.update(bytes.to_be_bytes());
                    digest.update(mtime_ns.to_be_bytes());
                    digest.update(sha256);
                }
            }
            index.insert(raw, entry);
        }
        check(limits.deadline)?;
        Ok(Self {
            root_mode,
            entries: index,
            digest: hex(&digest.finalize()),
            limits,
        })
    }
    pub fn sha256(&self) -> &str {
        &self.digest
    }
    pub fn policy_id(&self) -> &'static str {
        TREE_POLICY_ID
    }
    pub fn entries(&self) -> usize {
        self.entries.len()
    }
    pub fn verify(&self, root: &Path) -> Result<TreeObservation> {
        self.verify_with(root, &mut |_, _| Ok(()))
    }
    fn verify_with(
        &self,
        root: &Path,
        step: &mut impl FnMut(Step, &Path) -> Result<()>,
    ) -> Result<TreeObservation> {
        check(self.limits.deadline)?;
        let chain = Chain::open(root)?;
        chain.validate()?;
        let info = stat(chain.tail())?;
        require(
            info.st_mode & 0o7777 == self.root_mode,
            "tree_root_mode_mismatch",
        )?;
        let root_stamp = Stamp::from(&info);
        let mut stamps = BTreeMap::new();
        let mut counts = Counts::default();
        self.walk(
            chain.tail(),
            Path::new(""),
            &mut stamps,
            &mut counts,
            false,
            step,
        )?;
        require(
            stamps.len() == self.entries.len(),
            "tree_expected_entries_missing",
        )?;
        step(Step::BetweenPasses, Path::new(""))?;
        // Re-enumerate and independently rehash every regular file. Stat/ctime
        // agreement cannot stand in for bytes, including on coarse timestamps.
        // Two serial walks remain observations, never atomic immutability.
        let mut rechecked = Counts::default();
        self.walk(
            chain.tail(),
            Path::new(""),
            &mut stamps,
            &mut rechecked,
            true,
            step,
        )?;
        require(rechecked == counts, "tree_entries_missing_between_passes")?;
        require(
            Stamp::from(&stat(chain.tail())?) == root_stamp,
            "tree_root_changed_during_verification",
        )?;
        chain.validate()?;
        check(self.limits.deadline)?;
        Ok(TreeObservation {
            root: root.into(),
            manifest_sha256: self.digest.clone(),
            root_device: info.st_dev,
            root_inode: info.st_ino,
            bytes_hashed: counts.bytes + rechecked.bytes,
            counts,
        })
    }
    fn walk(
        &self,
        parent: &File,
        path: &Path,
        stamps: &mut BTreeMap<Vec<u8>, Stamp>,
        counts: &mut Counts,
        recheck: bool,
        step: &mut impl FnMut(Step, &Path) -> Result<()>,
    ) -> Result<()> {
        check(self.limits.deadline)?;
        let before = Stamp::from(&stat(parent)?);
        require(
            before.mode & nix::libc::S_IFMT == nix::libc::S_IFDIR,
            "tree_not_directory",
        )?;
        let mut directory = directory_reader(parent)?;
        let mut names = Vec::new();
        for entry in directory.iter() {
            check(self.limits.deadline)?;
            let entry = entry.map_err(|e| IdentityError::io("tree_directory_enumerate", e))?;
            let name = entry.file_name().to_bytes();
            if matches!(name, b"." | b"..") {
                continue;
            }
            counts.entries += 1;
            require(
                counts.entries <= self.limits.entries,
                "tree_directory_entry_bound",
            )?;
            counts.path_bytes += path.as_os_str().as_bytes().len()
                + usize::from(!path.as_os_str().is_empty())
                + name.len();
            require(
                counts.path_bytes <= self.limits.path_bytes,
                "tree_actual_path_byte_bound",
            )?;
            names.push(name.to_vec());
        }
        names.sort();
        require(
            names.windows(2).all(|pair| pair[0] != pair[1]),
            "tree_duplicate_observed_directory_entry",
        )?;
        for raw in names {
            check(self.limits.deadline)?;
            let name = OsString::from_vec(raw);
            let relative = path.join(&name);
            let key = relative.as_os_str().as_bytes();
            let result = (|| -> Result<()> {
                let expected = self
                    .entries
                    .get(key)
                    .ok_or_else(|| IdentityError::new("tree_unexpected_entry"))?;
                let named = named_stat(parent, Path::new(&name))?;
                let initial = Stamp::from(&named);
                require(
                    named.st_mode & 0o7777 == expected.mode,
                    "tree_entry_mode_mismatch",
                )?;
                if recheck {
                    require(
                        stamps.get(key) == Some(&initial),
                        "tree_entry_changed_between_passes",
                    )?;
                }
                step(Step::BeforeEntry, &relative)?;
                match &expected.kind {
                    TreeKind::Directory => {
                        require(
                            initial.mode & nix::libc::S_IFMT == nix::libc::S_IFDIR,
                            "tree_entry_type_mismatch",
                        )?;
                        let child = open(parent, Path::new(&name), true)?;
                        require(
                            Stamp::from(&stat(&child)?) == initial,
                            "tree_directory_binding_changed",
                        )?;
                        self.walk(&child, &relative, stamps, counts, recheck, step)?;
                        counts.directories += 1;
                    }
                    TreeKind::Symlink { target } => {
                        require(
                            initial.mode & nix::libc::S_IFMT == nix::libc::S_IFLNK
                                && (0..=4096).contains(&initial.bytes),
                            "tree_entry_type_mismatch",
                        )?;
                        let actual = readlinkat(parent, Path::new(&name))
                            .map_err(|e| IdentityError::io("tree_link_read", e))?;
                        require(actual.as_bytes() == target, "tree_link_target_mismatch")?;
                        counts.symlinks += 1;
                    }
                    TreeKind::File {
                        bytes,
                        mtime_ns,
                        sha256,
                    } => {
                        require(
                            initial.mode & nix::libc::S_IFMT == nix::libc::S_IFREG
                                && initial.links == 1,
                            "tree_regular_file_or_single_link_required",
                        )?;
                        require(
                            initial.bytes >= 0
                                && initial.bytes as u64 == *bytes
                                && initial.mtime.0 as i128 * 1_000_000_000
                                    + initial.mtime.1 as i128
                                    == *mtime_ns,
                            "tree_file_metadata_mismatch",
                        )?;
                        require(
                            *bytes <= self.limits.per_file_bytes
                                && *bytes <= self.limits.total_bytes - counts.bytes,
                            "tree_actual_content_bound",
                        )?;
                        counts.bytes += bytes;
                        let mut file = open(parent, Path::new(&name), false)?;
                        require(
                            Stamp::from(&stat(&file)?) == initial,
                            "tree_file_binding_changed",
                        )?;
                        let mut digest = Sha256::new();
                        let mut count = 0u64;
                        let mut buffer = [0u8; 65536];
                        loop {
                            check(self.limits.deadline)?;
                            let maximum = buffer.len().min((*bytes - count + 1) as usize);
                            let size = file
                                .read(&mut buffer[..maximum])
                                .map_err(|e| IdentityError::io("tree_file_read", e))?;
                            check(self.limits.deadline)?;
                            if size == 0 {
                                break;
                            }
                            count += size as u64;
                            require(count <= *bytes, "tree_file_grew_during_hash")?;
                            digest.update(&buffer[..size]);
                        }
                        require(
                            count == *bytes && digest.finalize().as_slice() == sha256,
                            "tree_file_content_mismatch",
                        )?;
                        require(
                            Stamp::from(&stat(&file)?) == initial,
                            "tree_file_changed_during_hash",
                        )?;
                        counts.files += 1;
                    }
                }
                step(Step::AfterEntry, &relative)?;
                require(
                    Stamp::from(&named_stat(parent, Path::new(&name))?) == initial,
                    "tree_named_entry_changed",
                )?;
                if !recheck {
                    require(
                        stamps.insert(key.to_vec(), initial).is_none(),
                        "tree_observed_entry_duplicate",
                    )?;
                }
                Ok(())
            })();
            result.map_err(|error| error.for_path(&relative))?;
        }
        require(
            Stamp::from(&stat(parent)?) == before,
            "tree_directory_changed_during_verification",
        )?;
        check(self.limits.deadline)
    }
}

#[derive(Debug, Default, PartialEq, Eq)]
struct Counts {
    entries: usize,
    files: usize,
    directories: usize,
    symlinks: usize,
    bytes: u64,
    path_bytes: usize,
}
/// An endpoint identity observation. It cannot assert an immutable/current
/// generation, a complete installed/host environment or later launch permission.
#[derive(Debug)]
pub struct TreeObservation {
    root: PathBuf,
    manifest_sha256: String,
    root_device: u64,
    root_inode: u64,
    bytes_hashed: u64,
    counts: Counts,
}
impl TreeObservation {
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn manifest_sha256(&self) -> &str {
        &self.manifest_sha256
    }
    pub fn root_device_inode(&self) -> (u64, u64) {
        (self.root_device, self.root_inode)
    }
    pub fn entries(&self) -> usize {
        self.counts.entries
    }
    pub fn files(&self) -> usize {
        self.counts.files
    }
    pub fn directories(&self) -> usize {
        self.counts.directories
    }
    pub fn symlinks(&self) -> usize {
        self.counts.symlinks
    }
    pub fn bytes_hashed(&self) -> u64 {
        self.bytes_hashed
    }
    /// Unique regular-file content bytes in the declared tree. Verification
    /// reads/hashes these twice; neither metric is a measured performance claim.
    pub fn file_bytes(&self) -> u64 {
        self.counts.bytes
    }
}
#[derive(Clone, Copy)]
enum Step {
    BeforeEntry,
    AfterEntry,
    BetweenPasses,
}
#[derive(Debug, Clone, PartialEq, Eq)]
struct Stamp {
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
impl Stamp {
    fn from(value: &FileStat) -> Self {
        Self {
            dev: value.st_dev,
            ino: value.st_ino,
            mode: value.st_mode,
            uid: value.st_uid,
            gid: value.st_gid,
            links: value.st_nlink,
            bytes: value.st_size,
            mtime: (value.st_mtime, value.st_mtime_nsec),
            ctime: (value.st_ctime, value.st_ctime_nsec),
        }
    }
}
fn stat(file: &File) -> Result<FileStat> {
    fstat(file).map_err(|e| IdentityError::io("tree_stat", e))
}
fn directory_reader(parent: &File) -> Result<Dir> {
    let fd = parent
        .try_clone()
        .map_err(|e| IdentityError::io("tree_directory_duplicate", e))?;
    // Pinned nix 0.30.1 consumes the FD before fdopendir and does not close it
    // on failure, despite its doc comment. POSIX leaves it open on failure.
    // Close only our consumed duplicate, never the independently owned parent.
    let raw_fd = fd.as_raw_fd();
    match Dir::from_fd(fd.into()) {
        Ok(directory) => Ok(directory),
        Err(error) => {
            let closed = nix::unistd::close(raw_fd);
            Err(IdentityError::io(
                "tree_directory_enumerate",
                format!("{error}; owned duplicate close: {closed:?}"),
            ))
        }
    }
}
fn named_stat(parent: &File, path: &Path) -> Result<FileStat> {
    fstatat(parent, path, AtFlags::AT_SYMLINK_NOFOLLOW)
        .map_err(|e| IdentityError::io("tree_named_stat", e))
}
fn open(parent: &File, path: &Path, directory: bool) -> Result<File> {
    let flags = OFlag::O_RDONLY
        | OFlag::O_NOFOLLOW
        | OFlag::O_CLOEXEC
        | if directory {
            OFlag::O_DIRECTORY
        } else {
            OFlag::O_NONBLOCK
        };
    openat(parent, path, flags, Mode::empty())
        .map(File::from)
        .map_err(|e| IdentityError::io("tree_no_follow_open", e))
}
fn components(path: &Path, absolute: bool) -> Result<Vec<OsString>> {
    require(
        path.is_absolute() == absolute
            && path.as_os_str().as_bytes().len() <= 4096
            && !path.as_os_str().as_bytes().contains(&0),
        "tree_path_invalid",
    )?;
    let mut names = Vec::new();
    for component in path.components() {
        match component {
            Component::RootDir if absolute => {}
            Component::Normal(name) => names.push(name.to_owned()),
            _ => return Err(IdentityError::new("tree_path_not_canonical")),
        }
    }
    require(
        names.len() <= 24 && (absolute || !names.is_empty()),
        "tree_path_depth_or_empty",
    )?;
    let rebuilt = names.iter().fold(
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
        rebuilt.as_os_str() == path.as_os_str(),
        "tree_path_not_canonical",
    )?;
    Ok(names)
}
struct Chain {
    anchor: File,
    links: Vec<(OsString, File, Stamp)>,
}
impl Chain {
    fn open(path: &Path) -> Result<Self> {
        let mut chain = Self {
            anchor: File::open("/").map_err(|e| IdentityError::io("tree_anchor_open", e))?,
            links: vec![],
        };
        for name in components(path, true)? {
            let file = open(chain.tail(), Path::new(&name), true)?;
            let stamp = Stamp::from(&stat(&file)?);
            chain.links.push((name, file, stamp));
        }
        Ok(chain)
    }
    fn tail(&self) -> &File {
        self.links.last().map_or(&self.anchor, |(_, file, _)| file)
    }
    fn validate(&self) -> Result<()> {
        let mut parent = &self.anchor;
        for (name, file, stamp) in &self.links {
            let named = Stamp::from(&named_stat(parent, Path::new(name))?);
            let opened = Stamp::from(&stat(file)?);
            // Unrelated entries in /tmp or other ancestors must not invalidate this
            // binding; domain directories get full mutation stamps in the walk.
            require(
                [&named, &opened].iter().all(|value| {
                    value.dev == stamp.dev
                        && value.ino == stamp.ino
                        && value.mode == stamp.mode
                        && value.uid == stamp.uid
                        && value.gid == stamp.gid
                }),
                "tree_ancestor_binding_changed",
            )?;
            parent = file;
        }
        Ok(())
    }
}
fn field(digest: &mut Sha256, raw: &[u8]) {
    digest.update((raw.len() as u64).to_be_bytes());
    digest.update(raw);
}
fn hex(raw: &[u8]) -> String {
    raw.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(test)]
mod tests;
