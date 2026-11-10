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
