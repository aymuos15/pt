use super::*;
use crate::{TreeEntry, TreeLimits};
use std::time::Duration;

const BASE: u64 = 0x400000;
const DYNAMIC: usize = 0x200;
const STRTAB: usize = 0x300;
const INTERP: usize = 0x180;
const LOADER: &[u8] = b"/lib64/ld-linux-x86-64.so.2\0";
const STRINGS: &[u8] = b"\0libx.so\0$ORIGIN/../lib\0";

fn limits() -> ElfLimits {
    ElfLimits {
        program_headers: 16,
        dynamic_entries: 64,
        needed: 16,
        string_table_bytes: 4096,
        projected_string_bytes: 512,
    }
}
fn p16(raw: &mut [u8], offset: usize, value: u16) {
    raw[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}
fn p32(raw: &mut [u8], offset: usize, value: u32) {
    raw[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}
fn p64(raw: &mut [u8], offset: usize, value: u64) {
    raw[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}
fn load(offset: u64, address: u64, bytes: u64) -> ElfProgramHeader {
    ElfProgramHeader {
        kind: PT_LOAD,
        flags: 5,
        offset,
        virtual_address: address,
        physical_address: address,
        file_bytes: bytes,
        memory_bytes: bytes,
        alignment: 1,
    }
}
fn program(raw: &mut [u8], index: usize, header: ElfProgramHeader) {
    let offset = 64 + index * 56;
    p32(raw, offset, header.kind);
    p32(raw, offset + 4, header.flags);
    p64(raw, offset + 8, header.offset);
    p64(raw, offset + 16, header.virtual_address);
    p64(raw, offset + 24, header.physical_address);
    p64(raw, offset + 32, header.file_bytes);
    p64(raw, offset + 40, header.memory_bytes);
    p64(raw, offset + 48, header.alignment);
}
fn dynamics(raw: &mut [u8], values: &[(u64, u64)], header_index: usize) {
    for (index, (tag, value)) in values.iter().enumerate() {
        p64(raw, DYNAMIC + index * 16, *tag);
        p64(raw, DYNAMIC + index * 16 + 8, *value);
    }
    program(
        raw,
        header_index,
        ElfProgramHeader {
            kind: PT_DYNAMIC,
            flags: 6,
            alignment: 8,
            ..load(
                DYNAMIC as u64,
                BASE + DYNAMIC as u64,
                (values.len() * 16) as u64,
            )
        },
    );
}
fn image() -> Vec<u8> {
    let mut raw = vec![0; 2048];
    raw[..8].copy_from_slice(b"\x7fELF\x02\x01\x01\x00");
    p16(&mut raw, 16, 2);
    p16(&mut raw, 18, 62);
    p32(&mut raw, 20, 1);
    p64(&mut raw, 24, BASE + 0x100);
    p64(&mut raw, 32, 64);
    p16(&mut raw, 52, 64);
    p16(&mut raw, 54, 56);
    p16(&mut raw, 56, 3);
    program(&mut raw, 0, load(0, BASE, 2048));
    program(
        &mut raw,
        1,
        ElfProgramHeader {
            kind: PT_INTERP,
            flags: 4,
            ..load(INTERP as u64, BASE + INTERP as u64, LOADER.len() as u64)
        },
    );
    raw[INTERP..INTERP + LOADER.len()].copy_from_slice(LOADER);
    raw[STRTAB..STRTAB + STRINGS.len()].copy_from_slice(STRINGS);
    dynamics(
        &mut raw,
        &[
            (5, BASE + STRTAB as u64),
            (10, STRINGS.len() as u64),
            (1, 1),
            (15, 9),
            (0, 0),
            (0, 0),
        ],
        2,
    );
    raw
}
fn manifest(raw: &[u8]) -> TreeManifest {
    TreeManifest::new(
        0o700,
        vec![TreeEntry {
            path: "image".into(),
            mode: 0o600,
            kind: TreeKind::File {
                bytes: raw.len() as u64,
                mtime_ns: 0,
                sha256: Sha256::digest(raw).into(),
            },
        }],
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
fn inspect(raw: &[u8]) -> Result<ElfLoadInputs> {
    manifest(raw).inspect_declared_elf(Path::new("image"), raw, limits())
}

#[test]
fn literal_projection_preserves_context_headers_order_and_unresolved_origin_without_execution() {
    let raw = image();
    let manifest = manifest(&raw);
    let value = manifest
        .inspect_declared_elf(Path::new("image"), &raw, limits())
        .unwrap();
    assert_eq!(value.policy_id(), ELF_INPUT_POLICY_ID);
    assert_eq!(value.path(), Path::new("image"));
    assert_eq!(value.manifest_sha256(), manifest.sha256());
    assert_eq!(value.image_sha256(), hex(&Sha256::digest(&raw)));
    assert_eq!(value.image_bytes(), 2048);
    assert_eq!(value.bytes_hashed(), 2048);
    assert_eq!(value.object_type(), 2);
    assert_eq!(value.os_abi(), 0);
    assert_eq!(value.entry_point(), BASE + 0x100);
    assert_eq!(value.interpreter(), Some(&LOADER[..LOADER.len() - 1]));
    assert_eq!(
        value
            .program_headers()
            .iter()
            .map(|header| header.kind())
            .collect::<Vec<_>>(),
        [PT_LOAD, PT_INTERP, PT_DYNAMIC]
    );
    let load = &value.program_headers()[0];
    assert_eq!(
        (
            load.offset(),
            load.virtual_address(),
            load.physical_address(),
            load.file_bytes(),
            load.memory_bytes(),
            load.alignment(),
            load.flags()
        ),
        (0, BASE, BASE, 2048, 2048, 1, 5)
    );
    assert_eq!(value.dynamic_entries().len(), 6);
    assert_eq!(value.used_dynamic_entries(), 5);
    assert_eq!(value.dynamic_entries()[0].tag_bits(), 5);
    assert_eq!(value.dynamic_entries()[0].value(), BASE + STRTAB as u64);
    assert_eq!(
        value.needed().collect::<Vec<_>>(),
        vec![b"libx.so".as_slice()]
    );
    assert_eq!(value.string_inputs()[1].kind(), ElfStringKind::Rpath);
    assert_eq!(value.string_inputs()[1].bytes(), b"$ORIGIN/../lib");
}

#[test]
fn adjacent_load_headers_can_split_a_string_or_table_without_guessing_one_segment() {
    let mut raw = image();
    let split = (STRTAB + 8) as u64;
    p16(&mut raw, 56, 4);
    program(&mut raw, 0, load(0, BASE, split));
    program(&mut raw, 1, load(split, BASE + split, 2048 - split));
    program(
        &mut raw,
        2,
        ElfProgramHeader {
            kind: PT_INTERP,
            flags: 4,
            ..load(INTERP as u64, BASE + INTERP as u64, LOADER.len() as u64)
        },
    );
    dynamics(
        &mut raw,
        &[
            (5, BASE + STRTAB as u64),
            (10, STRINGS.len() as u64),
            (1, 1),
            (15, 9),
            (0, 0),
            (0, 0),
        ],
        3,
    );
    let value = inspect(&raw).unwrap();
    assert_eq!(value.needed().collect::<Vec<_>>(), [b"libx.so".as_slice()]);
    assert_eq!(value.string_inputs()[1].bytes(), b"$ORIGIN/../lib");
    let mut gap = raw.clone();
    p64(&mut gap, 64 + 56 + 16, BASE + split + 1);
    assert_eq!(
        inspect(&gap).unwrap_err().code(),
        "elf_virtual_range_not_file_backed"
    );
    let mut overlap = image();
    p16(&mut overlap, 56, 4);
    program(&mut overlap, 3, load(0x400, BASE + STRTAB as u64, 32));
    assert_eq!(
        inspect(&overlap).unwrap_err().code(),
        "elf_virtual_mapping_ambiguous"
    );
    program(
        &mut overlap,
        3,
        load(STRTAB as u64, BASE + STRTAB as u64, 32),
    );
    assert_eq!(
        inspect(&overlap).unwrap().needed().collect::<Vec<_>>(),
        [b"libx.so".as_slice()]
    );
}

#[test]
fn image_hash_size_canonical_path_and_declared_regular_kind_precede_metadata_acceptance() {
    let original = image();
    let manifest = manifest(&original);
    let mut changed = original.clone();
    changed[2047] = 1;
    assert_eq!(
        manifest
            .inspect_declared_elf(Path::new("image"), &changed, limits())
            .unwrap_err()
            .code(),
        "elf_declared_image_digest_mismatch"
    );
    assert_eq!(
        manifest
            .inspect_declared_elf(Path::new("image"), &original[..2047], limits())
            .unwrap_err()
            .code(),
        "elf_declared_image_size_mismatch"
    );
    assert_eq!(
        manifest
            .inspect_declared_elf(Path::new("absent"), &original, limits())
            .unwrap_err()
            .code(),
        "elf_image_not_declared_regular_file"
    );
    assert!(
        manifest
            .inspect_declared_elf(Path::new("./image"), &original, limits())
            .is_err()
    );
    let manifest = TreeManifest::new(
        0o700,
        vec![TreeEntry {
            path: "image".into(),
            mode: 0o777,
            kind: TreeKind::Symlink {
                target: b".".to_vec(),
            },
        }],
        manifest.limits,
    )
    .unwrap();
    assert_eq!(
        manifest
            .inspect_declared_elf(Path::new("image"), &original, limits())
            .unwrap_err()
            .code(),
        "elf_image_not_declared_regular_file"
    );
}

#[test]
fn unknown_class_endianness_machine_abi_and_header_layout_are_not_converted_or_repaired() {
    for mode in [
        "magic",
        "class",
        "endian",
        "ident-version",
        "osabi",
        "abi-version",
        "padding",
        "type",
        "machine",
        "version",
        "flags",
        "header-size",
        "entry-size",
    ] {
        let mut raw = image();
        match mode {
            "magic" => raw[0] = 0,
            "class" => raw[4] = 1,
            "endian" => raw[5] = 2,
            "ident-version" => raw[6] = 2,
            "osabi" => raw[7] = 255,
            "abi-version" => raw[8] = 1,
            "padding" => raw[9] = 1,
            "type" => p16(&mut raw, 16, 1),
            "machine" => p16(&mut raw, 18, 183),
            "version" => p32(&mut raw, 20, 2),
            "flags" => p32(&mut raw, 48, 1),
            "header-size" => p16(&mut raw, 52, 63),
            _ => p16(&mut raw, 54, 55),
        }
        let expected = raw.clone();
        let error = inspect(&raw).unwrap_err();
        assert!(error.code().starts_with("elf_"), "{mode}: {error}");
        assert_eq!(error.relative_path(), Some(Path::new("image")));
        assert_eq!(raw, expected);
    }
    let mut shared = image();
    shared[7] = 3;
    p16(&mut shared, 16, 3);
    let value = inspect(&shared).unwrap();
    assert_eq!(value.os_abi(), 3);
    assert_eq!(value.object_type(), 3);
}

#[test]
fn header_ranges_overflows_duplicate_segments_and_bad_load_layouts_fail_without_execution() {
    for mode in [
        "phoff",
        "phnum-zero",
        "phnum-extended",
        "file-range",
        "virtual-overflow",
        "memory-short",
        "alignment",
        "congruence",
        "duplicate-interp",
        "duplicate-dynamic",
        "dynamic-layout",
        "dynamic-map",
    ] {
        let mut raw = image();
        match mode {
            "phoff" => p64(&mut raw, 32, u64::MAX),
            "phnum-zero" => p16(&mut raw, 56, 0),
            "phnum-extended" => p16(&mut raw, 56, u16::MAX),
            "file-range" => p64(&mut raw, 64 + 32, u64::MAX),
            "virtual-overflow" => p64(&mut raw, 64 + 16, u64::MAX),
            "memory-short" => p64(&mut raw, 64 + 40, 1024),
            "alignment" => p64(&mut raw, 64 + 48, 3),
            "congruence" => {
                p64(&mut raw, 64 + 48, 4096);
                p64(&mut raw, 64 + 16, BASE + 1);
            }
            "duplicate-interp" => {
                p16(&mut raw, 56, 4);
                program(
                    &mut raw,
                    3,
                    ElfProgramHeader {
                        kind: PT_INTERP,
                        ..load(INTERP as u64, BASE + INTERP as u64, LOADER.len() as u64)
                    },
                );
            }
            "duplicate-dynamic" => {
                p16(&mut raw, 56, 4);
                program(
                    &mut raw,
                    3,
                    ElfProgramHeader {
                        kind: PT_DYNAMIC,
                        ..load(DYNAMIC as u64, BASE + DYNAMIC as u64, 96)
                    },
                );
            }
            "dynamic-layout" => p64(&mut raw, 64 + 2 * 56 + 32, 95),
            _ => p64(&mut raw, 64 + 2 * 56 + 16, BASE + DYNAMIC as u64 + 16),
        }
        let error = inspect(&raw).unwrap_err();
        assert!(error.code().starts_with("elf_"), "{mode}: {error}");
    }
}

#[test]
fn interpreter_must_be_one_bounded_exact_nul_terminated_absolute_byte_string() {
    for mode in [
        "empty",
        "unterminated",
        "embedded-null",
        "relative",
        "oversize",
    ] {
        let mut raw = image();
        match mode {
            "empty" => p64(&mut raw, 64 + 56 + 32, 1),
            "unterminated" => raw[INTERP + LOADER.len() - 1] = b'x',
            "embedded-null" => raw[INTERP + 2] = 0,
            "relative" => raw[INTERP] = b'x',
            _ => p64(&mut raw, 64 + 56 + 32, 4098),
        }
        assert!(inspect(&raw).is_err(), "{mode}");
    }
    let mut raw = image();
    raw[INTERP + 2] = 0xff;
    assert_eq!(inspect(&raw).unwrap().interpreter().unwrap()[2], 0xff);
}

#[test]
fn dynamic_termination_pairs_singletons_and_nonzero_trailing_slots_are_not_ignored() {
    for mode in [
        "no-null",
        "null-value",
        "padding",
        "strtab-duplicate",
        "strsz-duplicate",
        "strtab-missing",
        "strsz-missing",
        "both-missing",
        "rpath-duplicate",
        "empty-needed",
        "string-offset",
        "unterminated",
        "table-zero",
    ] {
        let mut raw = image();
        match mode {
            "no-null" => {
                p64(&mut raw, DYNAMIC + 4 * 16, 0x1234);
                p64(&mut raw, DYNAMIC + 5 * 16, 0x1234);
            }
            "null-value" => p64(&mut raw, DYNAMIC + 4 * 16 + 8, 1),
            "padding" => p64(&mut raw, DYNAMIC + 5 * 16, 1),
            "strtab-duplicate" => p64(&mut raw, DYNAMIC + 3 * 16, 5),
            "strsz-duplicate" => p64(&mut raw, DYNAMIC + 3 * 16, 10),
            "strtab-missing" => p64(&mut raw, DYNAMIC, 0x1234),
            "strsz-missing" => p64(&mut raw, DYNAMIC + 16, 0x1234),
            "both-missing" => {
                p64(&mut raw, DYNAMIC, 0x1234);
                p64(&mut raw, DYNAMIC + 16, 0x5678);
            }
            "rpath-duplicate" => {
                p64(&mut raw, DYNAMIC + 2 * 16, 15);
                p64(&mut raw, DYNAMIC + 2 * 16 + 8, 9);
            }
            "empty-needed" => p64(&mut raw, DYNAMIC + 2 * 16 + 8, 0),
            "string-offset" => p64(&mut raw, DYNAMIC + 2 * 16 + 8, u64::MAX),
            "unterminated" => p64(&mut raw, DYNAMIC + 16 + 8, (STRINGS.len() - 1) as u64),
            _ => p64(&mut raw, DYNAMIC + 16 + 8, 0),
        }
        assert!(inspect(&raw).is_err(), "{mode}");
    }
}

#[test]
fn raw_unknown_tags_duplicate_needed_names_and_empty_search_strings_remain_ordered() {
    let mut raw = image();
    dynamics(
        &mut raw,
        &[
            (5, BASE + STRTAB as u64),
            (10, STRINGS.len() as u64),
            (1, 1),
            (0xf123456789abcdef, u64::MAX),
            (1, 1),
            (15, 9),
            (29, 0),
            (0, 0),
            (0, 0),
        ],
        2,
    );
    let value = inspect(&raw).unwrap();
    assert_eq!(value.dynamic_entries().len(), 9);
    assert_eq!(value.used_dynamic_entries(), 8);
    assert_eq!(value.dynamic_entries()[3].tag_bits(), 0xf123456789abcdef);
    assert_eq!(value.dynamic_entries()[3].value(), u64::MAX);
    assert_eq!(
        value.needed().collect::<Vec<_>>(),
        [b"libx.so".as_slice(), b"libx.so".as_slice()]
    );
    assert_eq!(
        value
            .string_inputs()
            .iter()
            .map(|value| value.kind())
            .collect::<Vec<_>>(),
        [
            ElfStringKind::Needed,
            ElfStringKind::Needed,
            ElfStringKind::Rpath,
            ElfStringKind::Runpath
        ]
    );
    assert_eq!(value.string_inputs()[3].bytes(), b"");
    raw[STRTAB + 1] = 0xff;
    assert_eq!(inspect(&raw).unwrap().needed().next().unwrap()[0], 0xff);
}

#[test]
fn audit_config_filter_and_auxiliary_names_are_visible_not_silently_dropped() {
    let mut raw = image();
    let tags = [
        1, 14, 15, 29, 0x6ffffefa, 0x6ffffefb, 0x6ffffefc, 0x7ffffffd, 0x7fffffff,
    ];
    let mut values = vec![(5, BASE + STRTAB as u64), (10, STRINGS.len() as u64)];
    values.extend(tags.into_iter().map(|tag| (tag, 1)));
    values.push((0, 0));
    values.push((0, 0));
    dynamics(&mut raw, &values, 2);
    let value = inspect(&raw).unwrap();
    assert_eq!(value.string_inputs().len(), 9);
    assert_eq!(
        value
            .string_inputs()
            .iter()
            .map(|value| value.kind())
            .collect::<Vec<_>>(),
        [
            ElfStringKind::Needed,
            ElfStringKind::Soname,
            ElfStringKind::Rpath,
            ElfStringKind::Runpath,
            ElfStringKind::Config,
            ElfStringKind::DepAudit,
            ElfStringKind::Audit,
            ElfStringKind::Auxiliary,
            ElfStringKind::Filter
        ]
    );
}

#[test]
fn positive_explicit_metadata_bounds_and_the_original_tree_deadline_cannot_be_reset() {
    let raw = image();
    let declared = manifest(&raw);
    let selected = limits();
    for chosen in [
        ElfLimits {
            program_headers: 0,
            ..selected
        },
        ElfLimits {
            program_headers: 129,
            ..selected
        },
        ElfLimits {
            dynamic_entries: 0,
            ..selected
        },
        ElfLimits {
            dynamic_entries: 4097,
            ..selected
        },
        ElfLimits {
            needed: 0,
            ..selected
        },
        ElfLimits {
            needed: 257,
            ..selected
        },
        ElfLimits {
            string_table_bytes: 0,
            ..selected
        },
        ElfLimits {
            string_table_bytes: 1024 * 1024 + 1,
            ..selected
        },
        ElfLimits {
            projected_string_bytes: 0,
            ..selected
        },
        ElfLimits {
            projected_string_bytes: 64 * 1024 + 1,
            ..selected
        },
    ] {
        assert_eq!(
            declared
                .inspect_declared_elf(Path::new("image"), &raw, chosen)
                .unwrap_err()
                .code(),
            "elf_limits_invalid"
        );
    }
    for chosen in [
        ElfLimits {
            program_headers: 2,
            ..selected
        },
        ElfLimits {
            dynamic_entries: 5,
            ..selected
        },
        ElfLimits {
            string_table_bytes: STRINGS.len() - 1,
            ..selected
        },
        ElfLimits {
            projected_string_bytes: 1,
            ..selected
        },
    ] {
        assert!(
            declared
                .inspect_declared_elf(Path::new("image"), &raw, chosen)
                .is_err()
        );
    }
    let exact = LOADER.len() - 1 + b"libx.so".len() + b"$ORIGIN/../lib".len();
    assert!(
        declared
            .inspect_declared_elf(
                Path::new("image"),
                &raw,
                ElfLimits {
                    projected_string_bytes: exact,
                    ..selected
                }
            )
            .is_ok()
    );
    assert_eq!(
        declared
            .inspect_declared_elf(
                Path::new("image"),
                &raw,
                ElfLimits {
                    projected_string_bytes: exact - 1,
                    ..selected
                }
            )
            .unwrap_err()
            .code(),
        "elf_projected_string_byte_bound"
    );
    let mut duplicate = raw.clone();
    dynamics(
        &mut duplicate,
        &[
            (5, BASE + STRTAB as u64),
            (10, STRINGS.len() as u64),
            (1, 1),
            (1, 1),
            (0, 0),
            (0, 0),
        ],
        2,
    );
    assert_eq!(
        manifest(&duplicate)
            .inspect_declared_elf(
                Path::new("image"),
                &duplicate,
                ElfLimits {
                    needed: 1,
                    ..selected
                }
            )
            .unwrap_err()
            .code(),
        "elf_needed_entry_bound"
    );
    let mut expired = declared;
    expired.limits.deadline = Instant::now();
    assert_eq!(
        expired
            .inspect_declared_elf(Path::new("image"), &raw, selected)
            .unwrap_err()
            .code(),
        "tree_absolute_deadline_expired"
    );
}

#[test]
fn absent_dynamic_and_interpreter_are_distinct_metadata_not_proof_of_no_runtime_loading() {
    let mut raw = image();
    p16(&mut raw, 56, 1);
    let value = inspect(&raw).unwrap();
    assert!(value.interpreter().is_none());
    assert!(value.dynamic_entries().is_empty());
    assert!(value.string_inputs().is_empty());
    assert_eq!(value.needed().count(), 0);
    assert_eq!(value.used_dynamic_entries(), 0);
}

#[test]
fn truncated_and_hostile_offset_controls_never_panic_or_modify_input_bytes() {
    let base = image();
    let mut count = 0;
    for length in 0..64 {
        assert!(inspect(&base[..length]).is_err());
        count += 1;
    }
    for offset in [
        32,
        64 + 8,
        64 + 16,
        64 + 32,
        64 + 40,
        64 + 56 + 8,
        64 + 2 * 56 + 8,
        64 + 2 * 56 + 16,
        DYNAMIC + 8,
        DYNAMIC + 16 + 8,
        DYNAMIC + 2 * 16 + 8,
    ] {
        for value in [0, 1, u32::MAX as u64, u64::MAX] {
            let mut raw = base.clone();
            p64(&mut raw, offset, value);
            let expected = raw.clone();
            assert!(std::panic::catch_unwind(|| inspect(&raw)).is_ok());
            assert_eq!(raw, expected);
            count += 1;
        }
    }
    assert_eq!(count, 108);
}
