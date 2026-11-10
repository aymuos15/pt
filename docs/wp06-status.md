# WP06 identity prerequisite progress

Status: **partial read-only native identity foundation**, not WP06 acceptance,
a content index, complete environment identity, immutable snapshot or launch
authorization. `pt run` remains unavailable. This prerequisite does not enable
WP07/WP08 optimizations ahead of their own gates.

## Declared-tree identity (base 9739ab4)

[`pt-identity`](../crates/pt-identity/README.md) checks a trusted, versioned,
strictly byte-sorted manifest against an exhaustive native no-follow tree.
Root/parent/leaf bindings, modes, regular-file length/mtime/SHA-256 and exact
symlink text are explicit. Undeclared caches/extra entries and unsupported types
fail; files are not repaired, permission-changed, ignored or deleted. Symlinks
identify **text only**; their referents and host/runtime inputs remain outside
this observation unless independently verified elsewhere.

Every regular file is hashed in **both** bounded walks. Metadata-only rechecking
is insufficient: the first draft's `edit-earlier` control changed three file
bytes between passes, restored length/mode/mtime and returned an incorrect tree
match. The focused run was **11 passed / one failed**. No timestamp sleep or test
relaxation was used to erase that counterexample. The implementation now rehashes
all bytes on the second pass, and a separate synthetic metadata-neutralization
control requires an exact byte-mismatch failure regardless of ctime granularity.
Second-walk completeness/totals are checked as well. This still does not prove
continuous immutability or exclude edit-and-revert outside relevant reads.

Other development corrections remain explicit: the initial draft missed nix's
`dir` feature and had an unused test import, so compilation/strict clippy stopped
before those new tests executed. The features/import were corrected without a
dependency-version change. Inspection found pinned nix 0.30.1's FD-consuming
`fdopendir` failure branch did not close its descriptor despite its documentation.
The native wrapper closes its duplicate on failure; a real repeated ENOTDIR
control checks that cleanup and the still-open parent.

Initial corrected controls passed **14 identity unit tests**, and strict clippy
passed before the final mixed-type canonical-hash control was added. Final locked
release, explicitly configured private-prefix reproduction and independent
archive/manifest/hash evidence follow their actual returns, not estimates.

The retained final **locked offline release workspace passed 162 tests**, no
skips: the prior 147 plus **14 identity methods and one explicitly selected
private-prefix reproduction**. Clippy `-D warnings` and rustfmt passed. Evidence
at `/tmp/opencode/pt-identity-final-verification-5jeu3ttv` includes frozen unchanged
workspace native/Python test sources, actual command returns/stdout/stderr and
separate native/independent prefix proofs. Both already prepared prefixes match
**4,971 entries each: 3,722 files, 1,048 symlinks and 201 directories**. Each has
**95,599,575 unique regular bytes**, independently hashed **twice** natively
(191,199,150 bytes read per successful verification).

The independent Python archive planner re-derived the complete expected manifest
from the still-matching archive, then its read-only inventory verifier again
reported no missing, extra or changed entries in either prefix. Separate Python
canonical hashing agreed with native manifest digest
`aef7ea220c93ad437c655d74c617c0b7a7a1cfc0a51c47e6a960d7185a39f499`.
Retained JSON manifest SHA-256 is
`53d7e48554c08a0f6ee912d085cfa37a8256f7a0bb6c7d29d9dc48ac408e279e`;
archive SHA-256 is
`1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c`.
These identify different byte domains, not interchangeable evidence or signed
build provenance. The test imported no subject/project code to perform native
identity verification.

All **48 prior Cargo package identities/checksums** survive; only local
**pt-identity 0.0.0** is added. Existing nix 0.30.1 gains `dir` alongside `fs`,
with no registry version substitution. Python/bridge/schema/toolchain/support
pins and all external candidate allocations are unchanged. The native suite
reran existing real pytest/JUnit/session controls, not the unchanged large
independent Python harness or qualification campaign.
Static precommit checks verified **78 local links**, seven unchanged pin /
candidate/schema files, unchanged bridge modules and all still-matching frozen
native/test source hashes. No generated raw evidence or local environment is
added to the repository.

## Opt-in declared relative-link closure follow-up (base f2bb2de)

The ordinary tree API still identifies **link text only**. Its separate opt-in
`verify_with_closed_links` checks every expected relative target through the
declared manifest graph, then requires the same two exhaustive native byte walks.
It never opens/adopts an unknown host referent or treats link text as proof of
runtime environment closure. The original canonical tree identity stays
**`linux-declared-tree-content-v1`**; a separate
**`linux-declared-relative-link-closure-v1`** digest binds ordered resolved target
paths/kinds to that tree digest. Root-relative output preserves raw bytes, exact
source link text and the distinction between root, directory and regular file.

Absolute targets (including apparently internal ones), escapes, dangling links,
non-directory traversal and cyclic/over-bound chains are explicitly unsupported.
Resolution follows component order: expanding `symlink/..` before parent traversal
and rejecting `file/..`/file trailing slashes instead of lexically simplifying
them. Limits are explicit and positive: at most **one million component steps**,
**40 dereferences including the initial link**, and **4,096 queued components**,
all under the original tree deadline. No normalization, repair, cache exception,
automatic retry or optimizer/launch permission is introduced.

An independent static archive-manifest diagnostic at
`/tmp/opencode/pt-declared-link-domain-diagnostic-b87wy1zb` found all **1,048
relative links** close inside the expected graph using **1,648 component steps**.
That diagnostic was **not a live tree or runtime/environment check**. The native
optional prefix reproduction now explicitly requires both the graph and the
existing exact tree checks, not a relaxed manifest or an inventory adopted from
the installation.

The focused release identity library passed **20 methods**, including six new
controls for raw names/root aliases and an independent isolated stdlib/OS resolver
digest, symlink-before-parent semantics, external FIFO/no-follow/dangling/cycles,
exact bounds/deadlines, unchanged native byte/link checks and digest/root binding.
Empty/no-link observations remain identity evidence, not nonempty pytest work.
Full native/prefix/independent verification follows its actual returns.

The exclusive final run at
`/tmp/opencode/pt-relative-link-closure-final-uk9ktq3n/run` passed **all 12 planned
commands, zero not-run**: **196 locked offline release Rust tests**, strict
clippy/rustfmt, **74 integration / 63 oracle / 68 contract checks**, CLI/wheel
builds, installed-wheel smoke and the additional native post-setup prefix check.
The ordinary 76 observer requests, 22 coordinator pytest requests and three
explicit direct-pytest cleanup references retain their own denominators; no
unrelated timing/resource campaign is inferred from these regressions.

Both native before/after checks still match **4,971 entries / 95,599,575 unique
regular bytes** per prefix, hashing **191,199,150 bytes** in each successful two-
walk verification. All **1,048 links** close under the new declared graph policy
in **1,648 component steps**. Independent Python/OS resolution checked every
positive referent in both actual prepared prefixes, without importing target
code, then reconstructed the ordered resolution digest:
`7f38ee25958f4fc2ee5aeb9320227a947a3be244c34dbccc392a81c90fdf713d`.
It agrees with both native proof files and both roots. Independent inventories
before/after resolution still show no missing, extra or changed entries; parent
mount flags remain unchanged. Existing tree digest
`aef7ea220c93ad437c655d74c617c0b7a7a1cfc0a51c47e6a960d7185a39f499`
and the original archive/manifest pins also match. This is not runtime path-use,
mount immutability or complete environment proof.

Independent read-back checked **189 frozen source/pin/schema files**, **50
unchanged Cargo package identities/checksums**, **eight unchanged lock/pin /
candidate/schema files**, Python grammar and **85 local links**. No new registry
dependency, protocol/result schema, toolchain/support pin or candidate allocation
is introduced. The unchanged bridge wheel reproduces
`4e973ca41e0a9f1614ebd0615f3d302fd4513a19e5a02acd1f68e4450ec286c1`.
The optional graph result cannot set coordinator environment/current-full-success
fields or enable qualified launch.
The final documentation-link addition was separately rechecked: **86 local
links** and all still-matching frozen sources.

A separate **non-executing target** ELF assessment at
`/tmp/opencode/pt-interpreter-elf-input-diagnostic-wqsrsyqf` rechecked the pinned
interpreter binary SHA-256
`3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66`
and used read-only `readelf` metadata. It declares interpreter
`/lib64/ld-linux-x86-64.so.2`, RPATH `$ORIGIN/../lib` and ordered shared-library
requirements `libpthread.so.0`, `libdl.so.2`, `libutil.so.1`, `librt.so.1`,
`libm.so.6`, `libc.so.6`. This diagnostic neither executes the selected image nor
resolves/authenticates those host inputs. It identifies the next native startup
input boundary; prefix graph closure does not close it by implication.

## Still required

- Complete interpreter/build/ABI, installed distributions/plugins, editable /
  `.pth`/namespace/native, environment-variable and host loader/library identity.
- Trustworthy external expected-file provenance and supported startup/private-FD
  handoff; identity bytes alone do not authorize loading them.
- Authoritative source/declared-input domain and immutable/current generation
  assurance. Endpoint hashes cannot rule out transient edits or close unknown
  external inputs.
- Candidate index/watcher behavior, overflow recovery, malformed syntax and
  dependency/config invalidation under a stated input contract. An index must
  never suppress real pytest collection or default full-scope work.
- Independent index/identity cost, memory and write-amplification measurement,
  integrated backend conformance, release review and authenticated artifacts.

No performance claim, semantic cache, support-matrix upgrade, corpus allocation
change or full work-package completion follows from these observations.
