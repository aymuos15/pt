# Declared-tree identity observations

**Development-only Linux component**, not a complete environment verifier,
index, cache, supported launcher or immutable-generation certifier. It does not
import/execute Python, install dependencies, infer expected bytes from the tree
being checked, repair inputs or authorize `pt run`.

## Contract and native checks

`TreeManifest::new(root_mode, entries, limits)` takes trusted caller-owned expected
entries, strictly sorted by **raw Unix relative-path bytes**. Parent directories
must be explicit. Duplicate paths, aliases/traversal, unsupported entry types,
oversized/invalid fields and nonpositive/unbounded limits fail; nothing is silently
sorted, normalized, omitted or repaired to make an input pass.

`verify(absolute_root)` opens and pins every directory component from `/` using
native no-follow operations. It checks the root mode and **exhaustively**
enumerates the domain: extra entries, including caches, are failures. Regular
files require exact mode, length, nanosecond mtime, SHA-256 and single-link
identity. Directories and symlinks require their exact declared mode/type.
Symlink checks compare raw link text and **never open/certify referents**. An
external, absolute, dangling or dynamically resolved referent is not thereby
part of a verified environment; callers must close that separate input domain.

Both walks enumerate the complete tree and independently hash every regular
file. The second also checks first-walk metadata/bindings. Open/named identity,
device/inode, uid/gid, link count, mode, size, mtime/ctime and directory mutation
stamps are checked at relevant boundaries. **Stat/ctime agreement is never a
substitute for the second byte read.** The complete second count/type/byte/path
totals must match, too. `IdentityError` retains a code and, where available, the
exact raw relative path. Failures return no successful observation.

All reads are bounded, with a 64 KiB file buffer and one caller-supplied absolute
monotonic deadline shared by construction and verification. Per-entry/chunk and
return checks cannot reset that window. Ordinary filesystem reads can update
kernel-managed access times; the library never writes file content, changes
permissions/mtime, deletes caches or modifies source trees. It is not a sandbox
against a hostile kernel, arbitrary virtual/FUSE filesystem or concurrent device
substitution, and a userspace deadline cannot interrupt an uninterruptible kernel
I/O call.

`TreeObservation` has private fields and read-only accessors for the root binding,
manifest digest and observed counts. `file_bytes()` counts unique regular-file
content; `bytes_hashed()` counts **both complete reads**, twice that value on
success. Neither count is a speed measurement or application execution proof.
There is no saved-proof recovery or automatic retry.

## Versioned canonical identity

Policy **`linux-declared-tree-content-v1`** uses SHA-256 over:

1. Literal `b"pt-tree-manifest-v1\0"`, root mode (u32), entry count (u64).
2. For each strictly byte-sorted entry: length-delimited raw relative path,
   mode (u32), then a one-byte kind: directory **0**, symlink **1**, file **2**.
3. Directory: no additional fields. Symlink: length-delimited raw target text.
   File: byte length (u64), signed mtime in nanoseconds (i128, two's complement),
   followed by the 32 raw SHA-256 bytes.

All integer fields are big-endian. Length prefixes are u64 byte lengths, not
Unicode character counts. There is no JSON/Unicode/path normalization. Absolute
root location, device/inode, ownership and observation limits/deadline are not
part of this relocatable expected-content digest; live root/entry bindings are
checked separately. Hashes identify declared content, **not producer honesty or
artifact provenance**. A lockfile, wheel RECORD, or caller assertion alone does
not establish independently trustworthy expected installed files.

Maximum bounds are **100,000 entries**, **128 MiB/file**, **4 GiB unique regular
content per walk**, **16 MiB aggregate paths**, **4,096 bytes/path or link target**,
**24 path components**, and a positive initial deadline **at most one hour**.
The second read is not hidden free work: successful hashing reads up to 8 GiB
across both walks under the same deadline. Relative and absolute root paths are
each validated; unusual depth/mode/permission/identity fails rather than gaining
an implicit exemption.

## Opt-in declared relative-link target closure

Ordinary `verify` remains **link-text-only**. The separate
`verify_with_closed_links(root, LinkLimits)` first resolves every expected link
through the **declared manifest graph only**, then performs the same two native
byte walks under the manifest's original deadline. It returns no observation
unless both the graph and the exact live tree checks succeed. No link referent
outside that declared graph is opened, adopted as expected truth or repaired.

Policy **`linux-declared-relative-link-closure-v1`** requires relative targets
whose component-by-component resolution ends at a declared regular file,
directory or the declared root. Absolute targets (even apparently inside the
root), root escapes, dangling targets, non-directory traversal, cycles/over-bound
chains and unknown targets are unsupported. `symlink/..` is expanded before the
parent traversal; `file/..` and a trailing slash on a file fail. Repeated slashes
and `.` are traversed with their native relative semantics, **not removed from
the original hashed link text**. Raw non-UTF-8/Unicode names remain distinct.

All graph limits are explicit and positive: at most **1,000,000 consumed component
steps across all links**, **40 dereferences per link resolution including the
initial link**, and **4,096 queued components**. Lower limits are allowed, never
inferred or silently expanded. No progress resets the original tree deadline.
This adds real verification work; counts are not speed measurements.

`ClosedLinkObservation` owns the matching read-only `TreeObservation`, closed-link
count, component-step count, maximum observed dereferences and a resolution digest.
It is not deserializable authority. `into_tree` explicitly discards the additional
graph observation and cannot mint an environment/generation success token.

The separate resolution SHA-256 hashes literal
`b"pt-declared-link-resolution-v1\0"`, a u64-length-delimited **64-byte ASCII
canonical tree digest**, the symlink count (u64), and, in strict raw source-path
order, each length-delimited source path, length-delimited resolved relative path
(empty for the root), then one-byte final kind (**0 directory / 2 file**). All
integers/lengths are big-endian. This binds the graph projection to the unchanged
**`linux-declared-tree-content-v1`** identity; the original canonical tree format
and link text are not weakened or normalized. Absolute root location and chosen
graph bounds are not part of this relocatable projection digest.

The claim is **declared target-graph closure plus endpoint tree identity**, not
proof of the paths a later Python process will actually load. Concurrent changes,
host dynamic loaders/libraries, absolute program inputs, `.pth`/plugin effects,
filesystem/mount behavior and complete immutable/runtime input domains retain
their separate gates. This does not certify installed distributions or a full
environment, follow unknown host targets, authorize launch or enable an optimizer.

## Explicit assurance exclusions

Two serial walks are **endpoint observations, not an atomic snapshot**. A change
and revert between reads, or a change after the final relevant read, can escape
endpoint detection. No lock/freeze/mount isolation or continuous monitoring is
provided. Successful tree identity does **not** imply immutable/current source
generation, complete external inputs, environment closure or later launch safety.

In particular, the interpreter's prefix does not include every host dynamic
loader/system library, environment variable, `.pth`/editable effect, user site,
plugin, project input or native/runtime resource. Those inputs, ordinary startup
semantics, the private-FD handoff and release authentication remain separate
gates. No authoritative cache/optimization or full-success API is enabled.

## Reproduction

```sh
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" \
  cargo test --locked --offline --release -p pt-identity --lib </dev/null
cargo clippy --locked --offline --workspace --all-targets -- -D warnings
cargo fmt --all --check
```

Controls cover raw non-UTF-8/Unicode paths, same-size/same-mtime edits, missing /
extra entries, mode/mtime changes, traversal/links/FIFOs/hardlinks, between-pass
edits, replacement/root races, finite bounds/deadlines, canonical hash agreement
with independent isolated stdlib Python, and the pinned nix failure-FD cleanup.
The metadata-neutralized byte control is explicitly synthetic, not identity or
generation qualification.

The ignored `private_prefix` integration test requires explicit
`PT_IDENTITY_PREFIX_MANIFEST`, `PT_IDENTITY_PREFIX_MANIFEST_SHA256`,
`PT_IDENTITY_PREFIX_ONE` and `PT_IDENTITY_PREFIX_TWO`. It verifies both already
prepared complete private prefixes against the retained **archive-derived**
manifest; it never adopts the observed prefix as its own expected truth. Select
it with `cargo test --locked --offline --release -p pt-identity --test private_prefix
-- --ignored`. `PT_IDENTITY_PROOF_OUTPUT` optionally writes a **new exclusive**
test evidence file; existing evidence is never overwritten or upgraded.

Production dependencies are the already pinned **nix 0.30.1** (`fs`/`dir`) and
**sha2 0.11.1**; no registry version is added. Pinned nix consumes its directory
FD before `fdopendir` and fails to close it on error despite its doc comment.
The adapter closes only its consumed duplicate on failure, and a real ENOTDIR
control verifies that the independently owned parent remains open. This narrow
workaround must be re-audited rather than assumed valid after a dependency change.
