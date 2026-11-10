# Native artifact retention foundation

**Development-only Linux GNU component**, not a complete reporter, secure store,
coordinator backend, generic report-completeness adapter or full-result certifier.
`pt run` remains unavailable. The existing diagnostic `pt exec --report` is not
silently replaced by or qualified through this library.

## What is independently checked

`ArtifactStore::create` takes **coordinator-owned** absolute source/retention roots,
a new opaque private-root name, explicit declarations and a positive finite
retention budget. Source paths are canonical relative paths selected by the
coordinator, not names supplied by bridge messages. IDs never choose an arbitrary
destination. Every ancestor is opened/pinned through no-follow native directory
operations from `/`; one-time string-prefix/canonicalization checks are not the
boundary. Symlinked directory components, traversal, aliases such as `a/./b`,
existing private roots and an unowned/other-writable retention parent fail.

The new root is 0700; retained files are exclusively created as 0600. Each source
must be an owned bounded regular file with one link and no group/world write bit.
Leaf symlinks, hardlinks, FIFOs, devices, directories and other unsafe inputs are
rejected without following or waiting on them. These are deliberate finite
development restrictions, not support for every reporting plugin/filesystem.

`WritersStopped::after_cleanup` requires the caller's **actually returned** native
process report with a reaped leader/status and complete required group cleanup.
A bare zero, missing return or uncertain cleanup cannot provide this token.
Failed/interrupted/signalled executions can still retain their artifacts without
turning into successful test work. The trusted coordinator must associate the
process with the correct request/store; this token does not authenticate a
report fabricated by that same trusted caller or contain hostile escaped writers.

For each declared artifact, `commit`:

1. Checks the ready claim, budget and any **independent coordinator expectation**.
2. Opens the source beneath pinned directory handles with no-follow/nonblocking
   flags; checks owner/type/link count, exact byte count and named/open identity.
3. Copies at most the bounded declared bytes to an exclusive private pending file,
   hashing actual source bytes. Source identity/stat/ancestor bindings are checked
   again; same-stat byte edits are not accepted merely by stat equality.
4. Syncs and independently rereads/hashes the pending copy, checks exact private
   permissions/identity and atomically publishes with native **rename no-replace**.
   There is no fallback that streams into or overwrites a final name.
5. Syncs the directory, checks named/root bindings and independently rereads the
   published descriptor too. A same-size edit after rename cannot pass on inode
   and length alone. A late error/deadline remains failed/uncertain even when
   complete-looking published bytes exist.

Failures are immutable per artifact: no retry, automatic recovery, source repair
or deletion of a substituted/foreign entry. Private pending/published leftovers
are retained; opening a previous private root does not reattach or recover it.
The API records whether publication **may** already exist. A required artifact
failure cannot be upgraded by discovering a file afterward.

## Content identity is not completeness

`ArtifactReady.complete` stays a **producer claim**. A matching hash/size alone
does not establish that a variable report, coverage merge or test session finished.
`VerifiedArtifact.ready_complete_claim()` preserves that assertion separately.

The only production completeness policy in this foundation is a coordinator-owned
`ExpectedContent { bytes, sha256 }` contract, selected independently of the later
ready claim/output. A mismatch fails; an exact match plus a complete ready claim
can satisfy **that exact byte contract only**. Never populate this expectation by
copying an untrusted ready assertion or reconstructing a lost execution return.

`expected_content: None` allows explicitly requested diagnostic content retention,
but **cannot satisfy required completeness**, even when a bridge says complete.
`required_artifacts_checkable()` exposes this before a qualified launch;
`required_artifacts_satisfied()` is an artifact-only prerequisite, never full-run
success. Variable JUnit, coverage and rich exception/report semantics still need
independent production format/accounting/finalization adapters. The actual-JUnit
test's independent parser/hash probe is **not** silently promoted to such an
adapter. Environment, source scope, immutable generation and semantic truth remain
separate gates. Hashes identify bytes, not producer honesty or build trust.

## Limits and time

Explicit ceilings: **1,024 retained artifacts**, **128 MiB/file**, **512 MiB total
content**; callers choose lower positive values. Root/declaration setup is bounded
to 24 canonical path components / 4,096 path bytes. IDs are bounded ASCII and raw
Unix source-name bytes (including supported non-UTF-8 names) are preserved.
Copy/readback uses one 64 KiB buffer, not whole-file buffering. Failed attempts
reserve their content budget; file count bounds both pending and final retention.
Metadata/allocator/charged-memory cost is not falsely labelled zero or measured.

One explicit absolute local-monotonic deadline covers the store's entire lifetime
(at most one hour from creation), including required execution/cleanup if the
store is declared beforehand. Partial progress cannot reset it. Expiry prevents
successful publication/return; expiry after rename retains uncertain publication.
Native regular-file I/O and directory sync can still be blocked in uninterruptible
kernel/filesystem waits; this is **not** a hard disk-I/O sandbox or qualification
of remote/special filesystems. Unsupported native rename/sync/permissions fail,
not best-effort success.

Budgets govern **Rust-retained copies**, not arbitrary user/pytest writes or an
OS-wide disk quota. Nothing silently redirects forwarded reporting arguments,
changes a user report's permissions, suppresses plugins or installs dependencies.
The caller must supply the explicit output policy/privacy contract and keep PT
state separate from source-generation inputs. Hostile same-user/root processes,
mount/loader compromise, ACL/xattr equivalence and complete input immutability are
not contained or certified.

## Reproduction

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --release --workspace </dev/null
```

Tests include real no-replace/filesystem/ownership operations, independently fixed
SHA-256 data, path/link/special-file controls, source/staging/ancestor substitution,
same-size edits, quota/deadline faults, explicit simulated storage/return loss,
unknown completeness and no recovery from complete-looking files. A real fresh
pytest assertion failure produces the requested JUnit, finishes its fixture and
is reaped; an independent isolated stdlib probe checks XML/hash, then Rust retains
the exact bytes while **required generic completeness stays blocked**.

The explicit hash dependency is **`sha2==0.11.1`**, default features disabled,
with transitive versions/checksums recorded in `Cargo.lock`; no custom crypto or
unreviewed ad-hoc digest algorithm is introduced. Existing nix 0.30.1 gains native
filesystem/user features. Dependency identity, cryptographic test vectors and
finite controls are not a supply-chain/security audit or release qualification.
See [WP09 evidence and remaining gates](../../docs/wp09-status.md).
