//! Native single-file association for the separate supplied-byte ELF projection.
//! Not exhaustive tree verification, a loader, an immutable generation or exec FD.
use super::{
    Chain, ElfLimits, ElfLoadInputs, IdentityError, Result, Stamp, TreeEntry, TreeKind,
    TreeManifest, check, components, named_stat, open, require, stat,
};
use sha2::{Digest, Sha256};
use std::ffi::OsString;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const ELF_FILE_POLICY_ID: &str = "linux-live-declared-elf-file-v1";

/// Endpoint observations only. No FD or reusable execution permission escapes.
/// The manifest digest describes expected content, not an exhaustive live check.
#[derive(Debug)]
pub struct ElfFileObservation {
    root: PathBuf,
    root_binding: (u64, u64),
    file_binding: (u64, u64),
    metadata: ElfLoadInputs,
}
impl ElfFileObservation {
    pub fn policy_id(&self) -> &'static str {
        ELF_FILE_POLICY_ID
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn root_device_inode(&self) -> (u64, u64) {
        self.root_binding
    }
    pub fn file_device_inode(&self) -> (u64, u64) {
        self.file_binding
    }
    pub fn metadata(&self) -> &ElfLoadInputs {
        &self.metadata
    }
    /// First supplied-buffer hash plus a separate post-parse native file hash.
    /// Separate from any exhaustive tree walk and the metadata-only byte count.
    pub fn bytes_hashed(&self) -> u64 {
        self.metadata.image_bytes() * 2
    }
}

struct Domain {
    root: Chain,
    root_stamp: Stamp,
    parents: Vec<(OsString, File, Stamp)>,
}
impl Domain {
    fn tail(&self) -> &File {
        self.parents
            .last()
            .map_or(self.root.tail(), |(_, file, _)| file)
    }
    fn validate(&self) -> Result<()> {
        self.root.validate()?;
        require(
            Stamp::from(&stat(self.root.tail())?) == self.root_stamp,
            "elf_file_root_changed",
        )?;
        let mut parent = self.root.tail();
        for (name, file, initial) in &self.parents {
            require(
                Stamp::from(&stat(file)?) == *initial
                    && Stamp::from(&named_stat(parent, Path::new(name))?) == *initial,
                "elf_file_parent_binding_changed",
            )?;
            parent = file;
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum Step {
    Opened,
    FirstReadChunk,
    BeforeParse,
    AfterParse,
    ReadbackChunk,
    AfterReadback,
    BeforeReturn,
}

impl TreeManifest {
    /// Read only a declared regular ELF file and its declared parent directories.
    /// Every root/parent component is pinned through native no-follow operations.
    /// This does not enumerate siblings or certify any other manifest entry.
    pub fn inspect_live_declared_elf(
        &self,
        root: &Path,
        path: &Path,
        limits: ElfLimits,
    ) -> Result<ElfFileObservation> {
        self.inspect_live_elf_with(root, path, limits, &mut |_| Ok(()))
    }

    fn inspect_live_elf_with(
        &self,
        root: &Path,
        path: &Path,
        limits: ElfLimits,
        step: &mut impl FnMut(Step) -> Result<()>,
    ) -> Result<ElfFileObservation> {
        let result = (|| {
            limits.validate()?;
            check(self.limits.deadline)?;
            let names = components(path, false)?;
            let expected = self
                .entries
                .get(path.as_os_str().as_bytes())
                .ok_or_else(|| IdentityError::new("elf_image_not_declared_regular_file"))?;
            let TreeKind::File {
                bytes, mtime_ns, ..
            } = &expected.kind
            else {
                return Err(IdentityError::new("elf_image_not_declared_regular_file"));
            };
            let chain = Chain::open(root)?;
            chain.validate()?;
            let root_stamp = Stamp::from(&stat(chain.tail())?);
            require(
                root_stamp.mode & 0o7777 == self.root_mode,
                "tree_root_mode_mismatch",
            )?;
            let root_binding = (root_stamp.dev, root_stamp.ino);
            let mut domain = Domain {
                root: chain,
                root_stamp,
                parents: Vec::new(),
            };
            let mut relative = PathBuf::new();
            for name in &names[..names.len() - 1] {
                check(self.limits.deadline)?;
                relative.push(name);
                let directory = self
                    .entries
                    .get(relative.as_os_str().as_bytes())
                    .ok_or_else(|| {
                        IdentityError::new("tree_manifest_parent_not_declared_directory")
                    })?;
                require(
                    matches!(directory.kind, TreeKind::Directory),
                    "tree_manifest_parent_not_declared_directory",
                )?;
                let initial = Stamp::from(&named_stat(domain.tail(), Path::new(name))?);
                require(
                    initial.mode & nix::libc::S_IFMT == nix::libc::S_IFDIR
                        && initial.mode & 0o7777 == directory.mode,
                    "elf_file_parent_type_or_mode_mismatch",
                )?;
                let file = open(domain.tail(), Path::new(name), true)?;
                require(
                    Stamp::from(&stat(&file)?) == initial,
                    "elf_file_parent_binding_changed",
                )?;
                domain.parents.push((name.clone(), file, initial));
            }
            let name = Path::new(names.last().expect("canonical nonempty relative path"));
            let initial = Stamp::from(&named_stat(domain.tail(), name)?);
            require(
                initial.mode & nix::libc::S_IFMT == nix::libc::S_IFREG && initial.links == 1,
                "tree_regular_file_or_single_link_required",
            )?;
            require(
                initial.mode & 0o7777 == expected.mode
                    && initial.bytes >= 0
                    && initial.bytes as u64 == *bytes
                    && initial.mtime.0 as i128 * 1_000_000_000 + initial.mtime.1 as i128
                        == *mtime_ns,
                "elf_file_declared_metadata_mismatch",
            )?;
            let mut file = open(domain.tail(), name, false)?;
            binding(&file, domain.tail(), name, &initial)?;
            domain.validate()?;
            step(Step::Opened)?;
            check(self.limits.deadline)?;
            let mut image = Vec::new();
            image
                .try_reserve_exact(*bytes as usize)
                .map_err(|error| IdentityError::io("elf_file_allocation_bound", error))?;
            let mut chunk = [0; 65536];
            loop {
                check(self.limits.deadline)?;
                let maximum = chunk.len().min((*bytes - image.len() as u64 + 1) as usize);
                let size = file
                    .read(&mut chunk[..maximum])
                    .map_err(|error| IdentityError::io("elf_file_read", error))?;
                step(Step::FirstReadChunk)?;
                check(self.limits.deadline)?;
                if size == 0 {
                    break;
                }
                require(
                    image.len() as u64 + size as u64 <= *bytes,
                    "elf_file_grew_during_read",
                )?;
                image.extend_from_slice(&chunk[..size]);
            }
            require(
                image.len() as u64 == *bytes,
                "elf_declared_image_size_mismatch",
            )?;
            step(Step::BeforeParse)?;
            let metadata = self.inspect_declared_elf(path, &image, limits)?;
            drop(image);
            step(Step::AfterParse)?;
            readback(
                &mut file,
                domain.tail(),
                name,
                &initial,
                expected,
                self.limits.deadline,
                step,
            )?;
            step(Step::AfterReadback)?;
            domain.validate()?;
            step(Step::BeforeReturn)?;
            binding(&file, domain.tail(), name, &initial)?;
            domain.validate()?;
            check(self.limits.deadline)?;
            Ok(ElfFileObservation {
                root: root.into(),
                root_binding,
                file_binding: (initial.dev, initial.ino),
                metadata,
            })
        })();
        result.map_err(|error| error.for_path(path))
    }
}

fn binding(file: &File, parent: &File, name: &Path, initial: &Stamp) -> Result<()> {
    require(
        Stamp::from(&stat(file)?) == *initial
            && Stamp::from(&named_stat(parent, name)?) == *initial,
        "elf_file_binding_changed",
    )
}

// Stat agreement is not byte verification. This independent second read takes
// place after parsing and keeps both the original expected bytes and deadline.
fn readback(
    file: &mut File,
    parent: &File,
    name: &Path,
    initial: &Stamp,
    expected: &TreeEntry,
    deadline: Instant,
    step: &mut impl FnMut(Step) -> Result<()>,
) -> Result<()> {
    let TreeKind::File { bytes, sha256, .. } = &expected.kind else {
        return Err(IdentityError::new("elf_image_not_declared_regular_file"));
    };
    check(deadline)?;
    binding(file, parent, name, initial)?;
    file.seek(SeekFrom::Start(0))
        .map_err(|error| IdentityError::io("elf_file_readback_seek", error))?;
    let mut digest = Sha256::new();
    let mut count = 0;
    let mut chunk = [0; 65536];
    loop {
        check(deadline)?;
        let maximum = chunk.len().min((*bytes - count + 1) as usize);
        let size = file
            .read(&mut chunk[..maximum])
            .map_err(|error| IdentityError::io("elf_file_readback", error))?;
        step(Step::ReadbackChunk)?;
        check(deadline)?;
        if size == 0 {
            break;
        }
        count += size as u64;
        require(count <= *bytes, "elf_file_grew_during_readback")?;
        digest.update(&chunk[..size]);
    }
    require(
        count == *bytes && digest.finalize().as_slice() == sha256,
        "elf_file_readback_mismatch",
    )?;
    binding(file, parent, name, initial)?;
    check(deadline)
}

#[cfg(test)]
mod tests;
