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

`ArtifactDeclaration::validate` also exposes the pure ID/path/content-policy
checks before any root creation or process launch. It does not validate live
bytes, per-store budgets, writers, environment or generation.

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

The original completeness policy in this foundation is a coordinator-owned
`ExpectedContent { bytes, sha256 }` contract, selected independently of the later
ready claim/output. A mismatch fails; an exact match plus a complete ready claim
can satisfy **that exact byte contract only**. Never populate this expectation by
copying an untrusted ready assertion or reconstructing a lost execution return.

`expected_content: None, junit_policy: None` allows requested diagnostic content retention,
but **cannot satisfy required completeness**, even when a bridge says complete.
`required_artifacts_checkable()` exposes this before a qualified launch;
`required_artifacts_satisfied()` is an artifact-only prerequisite, never full-run
success. Coverage and rich exception/report semantics still need independent
production format/accounting/finalization adapters. The original actual-JUnit
test's independent parser/hash probe is **not** the production adapter described
below. Environment, source scope, immutable generation and semantic truth remain
separate gates. Hashes identify bytes, not producer honesty or build trust.

## Versioned JUnit projection completeness

`JunitPolicy::xunit2` explicitly declares **`pytest-8.4.2-xunit2-no-extra-data-v1`**.
The coordinator selects the exact suite name, optional classname prefix and
positive XML byte/case/event budgets **before execution**. The declaration cannot
combine this policy with `expected_content`. Nothing changes pytest options,
filters, plugins, output paths or properties to force a report into this policy.

After actually observing the process return, reaping required writers and
validating the live reader's EOF/serial ledger, the trusted caller constructs
`JunitExpectation::from_snapshot(policy, snapshot, absolute_deadline)`. It derives
expected ordered/multiplicity-preserving XML identities, applicable adverse
outcomes, exact message/skip kind and counters **from the ledger**, not from the
report being checked. Collector skip/failure rows, doctest/unittest/custom
addresses, strict XPASS, ordinary skips/xfail, collect-only, fail-fast and empty
suites stay distinguishable. A passing call plus a teardown error counts **two**
suite tests with one XML row; a call/teardown double failure produces two rows
but subtracts the double-failure count. Neither counters nor rows alone can stand
in for item accounting.

`commit_with_junit` validates the **pending owned copy before publication** and
requires the matching declaration/context. Missing/extra/reordered identities,
missing/extra outcomes, mismatched messages/counters, malformed UTF-8/XML/entities,
unsafe extensions and unknown structures/attributes fail permanently. Empty tags
follow the same start/end checks, including required adverse outcomes; a missing
failure cannot pass just because its testcase is self-closing. The XML 1.0 / UTF-8
declaration, three-decimal nonnegative durations and aware ISO timestamp form
are explicit pinned-format constraints. Timestamp/hostname/durations are bounded
and validated, **not treated as runtime proof or compared as deterministic data**.
XML predefined/numeric references and pytest's exact visual invalid-character
escaping are supported, not broad path/Unicode/reason normalization.

The adapter rejects properties, `system-out`/`system-err`, legacy attributes,
multiple suites, DTDs, comments, CDATA and processing-instruction extensions.
It also rejects incomplete/interrupted attempts, session errors, retries,
ambiguous repeated adverse collectors or collector/attempt node-ID collisions.
An interruption's unnamed testcase remains **unknown/incomplete**, never a pass.
Unsupported data stays in the source/pending report; it is not stripped, repaired
or replayed. A plain `commit` without the ledger-derived JUnit context still
cannot satisfy this policy's required completeness.

The completion claim is intentionally **the named projection only**: identity /
outcome/message/counter and structural closure, plus a nonempty diagnostic body
where the formatter requires one. The bridge does not retain enough data to
independently compare every traceback-body byte, capture section, user property,
execution side effect or coverage record. The adapter does not certify those
contracts, authenticate a caller-fabricated snapshot, bind a different request's
process to a store, recover a lost return or waive environment/current immutable-
generation checks. Such requirements remain blocked on their own adapters/gates.

## Limits and time

Explicit ceilings: **1,024 retained artifacts**, **128 MiB/file**, **512 MiB total
content**; callers choose lower positive values. Root/declaration setup is bounded
to 24 canonical path components / 4,096 path bytes. IDs are bounded ASCII and raw
Unix source-name bytes (including supported non-UTF-8 names) are preserved.
Copy/readback uses one 64 KiB buffer. JUnit validation additionally retains at
most its explicitly declared XML bytes (**128 MiB maximum**) and **64 MiB maximum
expected projection text**. A report permits at most 100,000 testcase rows, one
million XML events, depth four, 16 attributes/element, 32 bytes/attribute name,
512 KiB/raw attribute and 65,536 decoded characters/attribute. All are failure
limits, not truncation. Projection construction and bounded copy reads also use
the explicit absolute deadline. Failed attempts
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

Additional controls exercise actual fresh pytest/JUnit + native frames/ledger /
retention across all ten core fixtures, report modes, both entrypoints, Unicode /
entity data, collection errors/skips, double failures and unsupported extensions.
The independent stdlib reader hashes every actual report and preserves unknown
identities; independent literal XML mutations and synthetic omission controls
are test evidence, not ecosystem or resource qualification. Set
`PT_OBSERVER_TEST_PYTHON` to the already prepared minimal subject environment;
`PT_JUNIT_CASE_ROOT` optionally retains every native subject request, raw private
stream, actual process return, oracle projection and source/published bytes in
new exclusive case directories. No test helper installs dependencies or disables
plugin autoload.

The explicit hash dependency is **`sha2==0.11.1`**, default features disabled,
with transitive versions/checksums recorded in `Cargo.lock`; no custom crypto or
unreviewed ad-hoc digest algorithm is introduced. Existing nix 0.30.1 gains native
filesystem/user features. Dependency identity, cryptographic test vectors and
finite controls are not a supply-chain/security audit or release qualification.
The format parser is separately pinned **`quick-xml==0.42.0`**, default features
disabled, using the existing memchr identity. Its registry archive/lock identity
is checked separately; selecting it does not authorize XML extensions or entity
resolution outside the policy above.
See [WP09 evidence and remaining gates](../../docs/wp09-status.md).
