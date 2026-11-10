//! Non-executing necessary load-input projection of declared ELF image bytes.
//! Not an ELF loader, general validity checker, native dependency resolver,
//! trust/provenance check, runtime/environment closure or launch authorization.
use super::{IdentityError, Result, TreeKind, TreeManifest, check, components, hex, require};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const ELF_INPUT_POLICY_ID: &str = "elf64le-x86_64-declared-load-inputs-v1";
const PT_LOAD: u32 = 1;
const PT_DYNAMIC: u32 = 2;
const PT_INTERP: u32 = 3;

#[derive(Debug, Clone, Copy)]
pub struct ElfLimits {
    pub program_headers: usize,
    pub dynamic_entries: usize,
    pub needed: usize,
    pub string_table_bytes: usize,
    pub projected_string_bytes: usize,
}
impl ElfLimits {
    pub(super) fn validate(self) -> Result<()> {
        require(
            (1..=128).contains(&self.program_headers)
                && (1..=4096).contains(&self.dynamic_entries)
                && (1..=256).contains(&self.needed)
                && (1..=1024 * 1024).contains(&self.string_table_bytes)
                && (1..=64 * 1024).contains(&self.projected_string_bytes),
            "elf_limits_invalid",
        )
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ElfProgramHeader {
    kind: u32,
    flags: u32,
    offset: u64,
    virtual_address: u64,
    physical_address: u64,
    file_bytes: u64,
    memory_bytes: u64,
    alignment: u64,
}
impl ElfProgramHeader {
    pub fn kind(&self) -> u32 {
        self.kind
    }
    pub fn flags(&self) -> u32 {
        self.flags
    }
    pub fn offset(&self) -> u64 {
        self.offset
    }
    pub fn virtual_address(&self) -> u64 {
        self.virtual_address
    }
    pub fn physical_address(&self) -> u64 {
        self.physical_address
    }
    pub fn file_bytes(&self) -> u64 {
        self.file_bytes
    }
    pub fn memory_bytes(&self) -> u64 {
        self.memory_bytes
    }
    pub fn alignment(&self) -> u64 {
        self.alignment
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ElfDynamicEntry {
    tag: u64,
    value: u64,
}
impl ElfDynamicEntry {
    /// Exact little-endian tag bits, including unknown/signed tag encodings.
    pub fn tag_bits(&self) -> u64 {
        self.tag
    }
    pub fn value(&self) -> u64 {
        self.value
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ElfStringKind {
    Needed,
    Soname,
    Rpath,
    Runpath,
    Config,
    DepAudit,
    Audit,
    Auxiliary,
    Filter,
}
impl ElfStringKind {
    fn from_tag(tag: u64) -> Option<Self> {
        Some(match tag {
            1 => Self::Needed,
            14 => Self::Soname,
            15 => Self::Rpath,
            29 => Self::Runpath,
            0x6ffffefa => Self::Config,
            0x6ffffefb => Self::DepAudit,
            0x6ffffefc => Self::Audit,
            0x7ffffffd => Self::Auxiliary,
            0x7fffffff => Self::Filter,
            _ => return None,
        })
    }
}
#[derive(Debug)]
pub struct ElfStringInput {
    kind: ElfStringKind,
    bytes: Vec<u8>,
}
impl ElfStringInput {
    pub fn kind(&self) -> ElfStringKind {
        self.kind
    }
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

/// Only metadata about caller-supplied bytes matching one declared regular file.
/// The caller still needs independent live file/tree/path/process association.
/// There is no success/closure flag or deserializable evidence-token constructor.
#[derive(Debug)]
pub struct ElfLoadInputs {
    path: PathBuf,
    manifest_sha256: String,
    image_sha256: String,
    image_bytes: u64,
    object_type: u16,
    os_abi: u8,
    entry_point: u64,
    interpreter: Option<Vec<u8>>,
    headers: Vec<ElfProgramHeader>,
    dynamic: Vec<ElfDynamicEntry>,
    used_dynamic: usize,
    strings: Vec<ElfStringInput>,
}
impl ElfLoadInputs {
    pub fn policy_id(&self) -> &'static str {
        ELF_INPUT_POLICY_ID
    }
    pub fn path(&self) -> &Path {
        &self.path
    }
    pub fn manifest_sha256(&self) -> &str {
        &self.manifest_sha256
    }
    pub fn image_sha256(&self) -> &str {
        &self.image_sha256
    }
    pub fn image_bytes(&self) -> u64 {
        self.image_bytes
    }
    /// Exactly one complete input-byte hash, separate from native tree walks.
    pub fn bytes_hashed(&self) -> u64 {
        self.image_bytes
    }
    pub fn object_type(&self) -> u16 {
        self.object_type
    }
    pub fn os_abi(&self) -> u8 {
        self.os_abi
    }
    pub fn entry_point(&self) -> u64 {
        self.entry_point
    }
    pub fn interpreter(&self) -> Option<&[u8]> {
        self.interpreter.as_deref()
    }
    pub fn program_headers(&self) -> &[ElfProgramHeader] {
        &self.headers
    }
    /// All declared slots, including the terminator and explicitly zero padding.
    pub fn dynamic_entries(&self) -> &[ElfDynamicEntry] {
        &self.dynamic
    }
    pub fn used_dynamic_entries(&self) -> usize {
        self.used_dynamic
    }
    pub fn string_inputs(&self) -> &[ElfStringInput] {
        &self.strings
    }
    pub fn needed(&self) -> impl Iterator<Item = &[u8]> {
        self.strings
            .iter()
            .filter(|value| value.kind == ElfStringKind::Needed)
            .map(|value| value.bytes.as_slice())
    }
}

impl TreeManifest {
    /// Inspect supplied bytes only: no filesystem traversal, target execution,
    /// `ldd`, interpreter import, library search or dependency installation.
    /// The original manifest deadline and independent expected file hash apply.
    pub fn inspect_declared_elf(
        &self,
        path: &Path,
        image: &[u8],
        limits: ElfLimits,
    ) -> Result<ElfLoadInputs> {
        let result = (|| {
            limits.validate()?;
            check(self.limits.deadline)?;
            components(path, false)?;
            let entry = self
                .entries
                .get(path.as_os_str().as_bytes())
                .ok_or_else(|| IdentityError::new("elf_image_not_declared_regular_file"))?;
            let TreeKind::File { bytes, sha256, .. } = &entry.kind else {
                return Err(IdentityError::new("elf_image_not_declared_regular_file"));
            };
            require(
                image.len() as u64 == *bytes,
                "elf_declared_image_size_mismatch",
            )?;
            let mut digest = Sha256::new();
            for chunk in image.chunks(65536) {
                check(self.limits.deadline)?;
                digest.update(chunk);
            }
            require(
                digest.finalize().as_slice() == sha256,
                "elf_declared_image_digest_mismatch",
            )?;
            let mut value = parse(image, limits, self.limits.deadline)?;
            value.path = path.into();
            value.manifest_sha256 = self.digest.clone();
            value.image_sha256 = hex(sha256);
            check(self.limits.deadline)?;
            Ok(value)
        })();
        result.map_err(|error| error.for_path(path))
    }
}

fn parse(image: &[u8], limits: ElfLimits, deadline: Instant) -> Result<ElfLoadInputs> {
    require(image.len() >= 64, "elf_header_truncated")?;
    require(
        &image[..7] == b"\x7fELF\x02\x01\x01"
            && matches!(image[7], 0 | 3)
            && image[8..16].iter().all(|byte| *byte == 0),
        "elf_ident_or_abi_unsupported",
    )?;
    let object_type = u16le(image, 16)?;
    require(
        matches!(object_type, 2 | 3)
            && u16le(image, 18)? == 62
            && u32le(image, 20)? == 1
            && u32le(image, 48)? == 0
            && u16le(image, 52)? == 64
            && u16le(image, 54)? == 56,
        "elf_header_profile_unsupported",
    )?;
    let count = u16le(image, 56)? as usize;
    require(
        count > 0 && count <= limits.program_headers,
        "elf_program_header_bound",
    )?;
    let offset = u64le(image, 32)?;
    require(offset >= 64, "elf_program_header_offset_invalid")?;
    let raw_headers = span(image, offset, (count * 56) as u64)?;
    let mut headers = Vec::new();
    let mut interpreter = None;
    let mut dynamic_header = None;
    let mut text_bytes = 0;
    for raw in raw_headers.as_chunks::<56>().0 {
        check(deadline)?;
        let header = ElfProgramHeader {
            kind: u32le(raw, 0)?,
            flags: u32le(raw, 4)?,
            offset: u64le(raw, 8)?,
            virtual_address: u64le(raw, 16)?,
            physical_address: u64le(raw, 24)?,
            file_bytes: u64le(raw, 32)?,
            memory_bytes: u64le(raw, 40)?,
            alignment: u64le(raw, 48)?,
        };
        span(image, header.offset, header.file_bytes)?;
        require(
            header
                .virtual_address
                .checked_add(header.memory_bytes)
                .is_some()
                && header
                    .virtual_address
                    .checked_add(header.file_bytes)
                    .is_some(),
            "elf_virtual_range_overflow",
        )?;
        if header.kind == PT_LOAD {
            require(
                header.file_bytes <= header.memory_bytes
                    && (header.alignment <= 1
                        || header.alignment.is_power_of_two()
                            && header.offset % header.alignment
                                == header.virtual_address % header.alignment),
                "elf_load_segment_layout_unsupported",
            )?;
        }
        if header.kind == PT_INTERP {
            require(interpreter.is_none(), "elf_duplicate_interpreter")?;
            require(
                (2..=4097).contains(&header.file_bytes),
                "elf_interpreter_byte_bound",
            )?;
            let raw = span(image, header.offset, header.file_bytes)?;
            let value = cstring(raw, 0)?;
            require(
                value.len() + 1 == raw.len() && value.starts_with(b"/"),
                "elf_interpreter_path_unsupported",
            )?;
            add_text(&mut text_bytes, value.len(), limits.projected_string_bytes)?;
            interpreter = Some(value.to_vec());
        }
        if header.kind == PT_DYNAMIC {
            require(dynamic_header.is_none(), "elf_duplicate_dynamic_segment")?;
            require(
                header.file_bytes >= 16
                    && header.file_bytes.is_multiple_of(16)
                    && header.file_bytes / 16 <= limits.dynamic_entries as u64,
                "elf_dynamic_entry_bound_or_layout",
            )?;
            dynamic_header = Some(header);
        }
        headers.push(header);
    }
    let mut dynamic = Vec::new();
    let mut used_dynamic = 0;
    let mut strtab = None;
    let mut strsz = None;
    if let Some(header) = dynamic_header {
        let mapped = mapped_bytes(
            image,
            &headers,
            header.virtual_address,
            header.file_bytes,
            deadline,
        )?;
        require(
            mapped == span(image, header.offset, header.file_bytes)?,
            "elf_dynamic_file_mapping_mismatch",
        )?;
        let mut ended = false;
        for raw in mapped.as_chunks::<16>().0 {
            check(deadline)?;
            let value = ElfDynamicEntry {
                tag: u64le(raw, 0)?,
                value: u64le(raw, 8)?,
            };
            if ended {
                require(
                    value.tag == 0 && value.value == 0,
                    "elf_nonzero_dynamic_padding",
                )?;
            } else if value.tag == 0 {
                require(value.value == 0, "elf_nonzero_dynamic_terminator")?;
                ended = true;
                used_dynamic = dynamic.len() + 1;
            } else if value.tag == 5 {
                require(
                    strtab.replace(value.value).is_none(),
                    "elf_duplicate_string_table_address",
                )?;
            } else if value.tag == 10 {
                require(
                    strsz.replace(value.value).is_none(),
                    "elf_duplicate_string_table_size",
                )?;
            }
            dynamic.push(value);
        }
        require(ended, "elf_dynamic_terminator_missing")?;
    }
    require(
        strtab.is_some() == strsz.is_some(),
        "elf_string_table_pair_missing",
    )?;
    let table = match (strtab, strsz) {
        (Some(address), Some(bytes)) => {
            require(
                bytes > 0 && bytes <= limits.string_table_bytes as u64,
                "elf_string_table_byte_bound",
            )?;
            mapped_bytes(image, &headers, address, bytes, deadline)?
        }
        _ => Vec::new(),
    };
    let mut strings = Vec::new();
    let mut singleton = HashSet::new();
    let mut needed = 0;
    for entry in dynamic.iter().take(used_dynamic) {
        check(deadline)?;
        if let Some(kind) = ElfStringKind::from_tag(entry.tag) {
            require(strtab.is_some(), "elf_string_input_without_table")?;
            if kind == ElfStringKind::Needed {
                needed += 1;
                require(needed <= limits.needed, "elf_needed_entry_bound")?;
            } else {
                require(singleton.insert(kind), "elf_duplicate_projected_string_tag")?;
            }
            let bytes = cstring(&table, entry.value)?;
            require(
                kind != ElfStringKind::Needed || !bytes.is_empty(),
                "elf_empty_needed_name",
            )?;
            add_text(&mut text_bytes, bytes.len(), limits.projected_string_bytes)?;
            strings.push(ElfStringInput {
                kind,
                bytes: bytes.to_vec(),
            });
        }
    }
    check(deadline)?;
    Ok(ElfLoadInputs {
        path: PathBuf::new(),
        manifest_sha256: String::new(),
        image_sha256: String::new(),
        image_bytes: image.len() as u64,
        object_type,
        os_abi: image[7],
        entry_point: u64le(image, 24)?,
        interpreter,
        headers,
        dynamic,
        used_dynamic,
        strings,
    })
}

fn add_text(total: &mut usize, bytes: usize, bound: usize) -> Result<()> {
    require(bytes <= bound - *total, "elf_projected_string_byte_bound")?;
    *total += bytes;
    Ok(())
}
fn cstring(table: &[u8], offset: u64) -> Result<&[u8]> {
    let start =
        usize::try_from(offset).map_err(|_| IdentityError::new("elf_string_offset_invalid"))?;
    let raw = table
        .get(start..)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| IdentityError::new("elf_string_offset_invalid"))?;
    let end = raw
        .iter()
        .take(4097)
        .position(|byte| *byte == 0)
        .ok_or_else(|| IdentityError::new("elf_string_unterminated_or_bound"))?;
    Ok(&raw[..end])
}
fn span(raw: &[u8], offset: u64, bytes: u64) -> Result<&[u8]> {
    let end = offset
        .checked_add(bytes)
        .ok_or_else(|| IdentityError::new("elf_file_range_invalid"))?;
    let start =
        usize::try_from(offset).map_err(|_| IdentityError::new("elf_file_range_invalid"))?;
    let end = usize::try_from(end).map_err(|_| IdentityError::new("elf_file_range_invalid"))?;
    raw.get(start..end)
        .ok_or_else(|| IdentityError::new("elf_file_range_invalid"))
}
fn u16le(raw: &[u8], offset: u64) -> Result<u16> {
    Ok(u16::from_le_bytes(
        span(raw, offset, 2)?
            .try_into()
            .expect("exact integer width"),
    ))
}
fn u32le(raw: &[u8], offset: u64) -> Result<u32> {
    Ok(u32::from_le_bytes(
        span(raw, offset, 4)?
            .try_into()
            .expect("exact integer width"),
    ))
}
fn u64le(raw: &[u8], offset: u64) -> Result<u64> {
    Ok(u64::from_le_bytes(
        span(raw, offset, 8)?
            .try_into()
            .expect("exact integer width"),
    ))
}

/// File-backed virtual ranges can cross adjacent LOAD headers (the pinned Python
/// image actually does). Recheck every segment boundary and reject holes/BSS or
/// ambiguous overlapping file offsets, rather than guessing one segment.
fn mapped_bytes(
    image: &[u8],
    headers: &[ElfProgramHeader],
    address: u64,
    bytes: u64,
    deadline: Instant,
) -> Result<Vec<u8>> {
    let end = address
        .checked_add(bytes)
        .ok_or_else(|| IdentityError::new("elf_virtual_range_overflow"))?;
    let mut current = address;
    let mut output = Vec::new();
    while current < end {
        check(deadline)?;
        let mut offset = None;
        let mut boundary = end;
        for segment in headers
            .iter()
            .filter(|header| header.kind == PT_LOAD && header.file_bytes > 0)
        {
            let segment_end = segment.virtual_address + segment.file_bytes; // Checked during header parsing.
            if segment.virtual_address <= current && current < segment_end {
                let candidate = segment.offset + (current - segment.virtual_address);
                require(
                    offset.is_none_or(|value| value == candidate),
                    "elf_virtual_mapping_ambiguous",
                )?;
                offset = Some(candidate);
                boundary = boundary.min(segment_end);
            } else if segment.virtual_address > current {
                boundary = boundary.min(segment.virtual_address);
            }
        }
        let offset =
            offset.ok_or_else(|| IdentityError::new("elf_virtual_range_not_file_backed"))?;
        require(boundary > current, "elf_virtual_mapping_no_progress")?;
        output.extend_from_slice(span(image, offset, boundary - current)?);
        current = boundary;
    }
    check(deadline)?;
    Ok(output)
}

#[cfg(test)]
mod tests;
