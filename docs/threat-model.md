# Threat model — conservative baseline review

Status: **WP00 engineering self-review completed, 2026-11-09; controls are
requirements, not security qualification**. The review disposition and remaining
gates are in [wp00-review.md](wp00-review.md). The authoritative requirements are
specification §§3–7, 9–11, 14.3, WP09/WP16 and the
[baseline contract](baseline-contract-v1.md). No production bridge or secure
store exists yet. Process-only diagnostic evidence is in
[wp04-status.md](wp04-status.md), not evidence that all controls below work.

## Authority, assets and adversaries

PT runs with the invoking user's ordinary authority. **It is not a sandbox**,
privilege boundary, firewall or transactional rollback mechanism. The operator
must trust the selected interpreter, tests, plugins, build tools and dependencies
to execute as that user. They may access credentials, use the network, modify
files, start external services or deliberately escape an ordinary process group.
Mitigating that requires separately supplied/qualified isolation; PT does not
claim it or silently add it. No elevated privileges, system tuning, service
installation or remote/public control endpoint is required by this baseline.

Protect result/scope/generation integrity, owned process identities, private IPC,
PT-owned paths and metadata, required artifact finalization, local credentials,
and bounded coordinator resources against accidental/malformed input, corruption,
concurrent edits, crashes and unrelated local processes. Project-origin strings,
paths, messages, cache records and claims remain untrusted *data*, even when
the project's execution is operator-authorized.

Different-user local processes must not gain access through PT-created listeners,
world-readable state or writable publication paths. Hostile same-user processes,
root/kernel compromise, a malicious chosen interpreter or forged observations
inside the authorized worker are **not contained**. IDs/hashes and schema-valid
events cannot prove producer honesty or actual test execution. Independent WP03
sentinels/oracles qualify supported non-hostile semantics; they are not security
attestation against hostile same-user code.

## Reviewed controls and explicit implementation gates

Each T-row resolves the previous draft's baseline decision. None is a claim of
an implemented mitigation. If its prerequisite cannot be met, reject the
required feature before work where possible; after effects, preserve the failure
and work prefix, clean up the owned boundary, and never silently replay or
publish success. Optional functionality stays disabled rather than weakening a
required control. Later platform/feature expansion needs a new reviewed contract.

| ID | Threat / boundary | Resolved baseline requirement | Implementation evidence still required |
|---|---|---|---|
| T01 | Unauthorized execution or authority expansion | Explicit operator-selected executable/profile; direct OS argv, no shell or project imports in the coordinator; no auto-installation, plugin suppression or executable cache deserialization. No privileged/public/remote control plane. | WP04/WP05 validate the actual interpreter/entrypoint/bridge pair before project work; invalid/missing profiles fail visibly. Metadata-only doctor is not executable provenance or runtime identity proof. |
| T02 | IPC spoofing, descriptor leakage or an unrelated producer | Private inherited connected Unix socket pair, no named listener. Bind the bridge producer/role and run IDs to that channel; accept **only bridge-origin kinds** from it. Coordinator-only events are locally generated, never accepted because a message says `producer_role: coordinator`. Close unused ends and set non-inheritable before project imports. | WP05/WP09/WP16 test role spoofing, wrong IDs/versions, descriptor lifecycle and ordinary descendant leakage. Close-on-exec does not prevent raw-fork inheritance; deadline/cleanup must bound a retained descriptor. The role field or a session ID is not an authentication secret. |
| T03 | Malformed frames, event floods or backpressure | Strict bounded decoder, exact versions, per-producer continuity and the protocol ceilings below. No pickle, arbitrary name resolution or parsing control messages from stdout. Refuse excessive nesting and fail closed on stalled delivery. | WP09/WP16 must enforce actual incoming bytes/queue/decoder bounds and terminate on malformed/truncated/duplicate/conflicting input or stalled channels. The decoded synthetic checker is not this implementation. |
| T04 | Path traversal, symlink/hardlink substitution and unsafe overwrite/delete | Coordinator maps opaque artifact IDs to a fresh private root; bridge paths never choose a destination. Create owned roots/files restrictively and pin directory/file identities. Constrain traversal with race-resistant native operations; reject unsafe links/types/ownership and publish without replacement. No broad cleanup or cache clearing through project-controlled paths. | WP07/WP09/WP16 fault-test ancestor/leaf replacement, symlinks, hardlinks, concurrent writers, crash leftovers, invalid path bytes and no-overwrite semantics. String-prefix checks or one-time canonicalization are insufficient. Existing `pt exec --report` is not a hardened store. |
| T05 | Ready-but-partial output, disk-full writes or interrupted coverage merge | Required reporting/coverage remains inside completion/timing. Independently verify the owned regular file, identity, bytes/hash and completeness after finalized writers are reaped and required group cleanup completes; only then commit. Keep partial/failed states and reasons, never infer completion from backend zero/readiness alone. | WP05/WP09/WP15/WP16 must verify actual artifacts, effective coverage core/sets/subprocesses and merge/report failure. Checksums/verified flags in a schema-valid message are not verification. Unsupported required output locations/plugins fail rather than being silently redirected/disabled. |
| T06 | Corrupt/stale cache or forged capability evidence | Persist versioned descriptions only; never live runtime state or pickle. No authoritative metadata/runtime/result reuse in the baseline. No bridge/project/config/cached record can grant an optimization. Unknown/conflicting/stale evidence denies it. | WP06/WP07 validate identities, scoped issuer trust, migrations, transactions, leases and corruption recovery before reuse/allow. A narrower assertion cannot override an unknown/deny session constraint. |
| T07 | Concurrent source/data/environment mutation or false current-generation green | Generation and declared input domain accompany every test result. Unknown, superseded or uncertain assurance prevents current full success; live-tree observation is not immutable-snapshot proof. Include relevant symlink targets, external data, editable/native dependencies, plugin/config and bytecode identities or report inability to verify. | WP02/WP03/WP06/WP08/WP15 must establish actual loaded inputs and test edit-and-revert, same-mtime/size edits, renames, external changes, stale bytecode and watcher overflow. A matching final hash alone is insufficient. |
| T08 | Credentials/trace disclosure and uncontrolled retention | No bulk environment export or raw credential values, secrets in an index, automatic raw-output indexing, telemetry or automatic artifact upload. Private local retention/export policy below; treat argv, node IDs, paths, warnings and test output as potentially sensitive too. | WP06/WP07/WP09/WP16 implement allowlisted/keyed identity, protected storage/retention and explicit export review. Automatic perfect redaction of arbitrary test output is not promised; raw retained evidence may contain secrets. |
| T09 | PID reuse, timeout escape, OOM or failed shutdown | Fresh owned process group; keep leader identity until final signaling, reap it, verify ordinary live group members, and bound cleanup. Record raw cause and lost teardown. No automatic reset/replay. No success when ownership or cleanup is uncertain. | WP04/WP09/WP16 must fault-test ordinary descendants, foreign reapers, restrictive procfs, signal/timeout and I/O failures. Detached hostile descendants, external services, uninterruptible waits and coordinator SIGKILL are not guaranteed contained; they require separate recovery/isolation evidence. |
| T10 | Modified installation, unsafe dependencies or misleading version pins | Separate selected versions from installed-file identity and artifact trust. Explicit installation/build steps only, no mutations during execution. No replacement pytest package or global auto-plugin. Unknown plugin capability never disables that plugin. | WP02/WP04/WP05/WP15/WP19 must authenticate/pin artifacts, verify clean materializations and actual plugin/import graphs, and qualify the version pair. Locks, METADATA, RECORD hashes and doctor output have distinct limitations, not interchangeable proofs. |
| T11 | Resource exhaustion, service contamination or hidden work | No persistent daemon/seed, semantic caches, managed leases or service reuse in the initial contract. Explicit positive PT-owned artifact budgets are a prerequisite to capture/storage; enforce protocol limits. PT quotas do not constrain arbitrary writes/CPU/memory by authorized project code. | WP01/WP09/WP16 must measure full-boundary CPU/memory and buffering; WP10/WP14 need capacity, isolation/reset and worker-death lease tests before resource features. Missing native accounting/quotas must not become an invented zero cost or containment claim. |
| T12 | Coordinator death, concurrent clients or abandoned state | Single-session ownership of channels/staging; immutable published terminal records. Unfinished recovered runs are `abandoned`, never reattached/replayed or promoted from provisional files. Do not remove another client's state or an output whose ownership is uncertain. | WP07/WP09/WP16 implement transactional recovery, active leases, exclusive ownership and bounded reclamation. A typed abandoned example is not an authenticated recovery implementation; no power-loss durability is claimed for today's diagnostic reports. |

## Concrete limits and ownership policy

Adopt the [protocol's](protocol-draft.md) 1 MiB frame, 64 MiB aggregate encoded
events, 1,000,000 events, 100,000 occurrences, 16 MiB aggregate node-ID data,
1,024 artifacts/error summaries, 4,096 ordinals/chunk and 32 attempts ceilings.
For the future serial reader, pending wire payloads are limited to **two frames
and 2 MiB combined**, with JSON nesting at most **32 levels**. These are
additional fail-closed reader requirements, not implemented synthetic-check
limits or a claim of a 2 MiB total resident-memory footprint. Decoded ledger,
allocator, output and other resources must also be bounded/measured. Do not
buffer all test stdout/stderr in memory. Channel/output stalls cannot bypass
the declared execution and finite cleanup deadlines.

PT-owned staging/storage requires an explicit positive byte/file budget before
use; no unbounded/default infinite artifact capture or background store is
authorized. Exceeding a required budget fails visibly, retaining the bounded
failure record, not a silently truncated complete artifact. Optional capture can
remain off. The budget applies to PT's storage, not arbitrary user/pytest output
paths; do not alter forwarded output arguments or imply a disk sandbox.

Private PT roots use mode 0700 and new metadata/artifact files mode 0600 (or
equivalent restrictive rights), exclusive creation and verified ownership. Pin
trusted directory handles and use no-follow/beneath-root operations or equivalent
race-resistant primitives. Do not follow a project-supplied symlink, accept an
unowned/hardlinked staging file, or modify shared-cache hardlinks in place.
Missing required native safety primitives/permissions make the feature
unavailable, not silently best-effort. Only delete individually proven PT-owned,
inactive temporary/cache entries; uncertain ownership preserves the entry and
reports failure. Artifact hashes verify content identity, never ownership/trust.

## Confidentiality, retention and authentication disposition

Only explicit required or operator-opted-in artifacts may be retained; no global
automatic raw-log/index retention in this baseline. Preserve failed samples and
partial states *within that declared private evidence policy*; do not discard
inconvenient results, upload them by default, or treat privacy redaction as an
undisclosed benchmark exclusion. Export requires explicit operator action and
review for sensitive contents. Redacted bundles identify the transformation and
cannot pretend to be byte-identical raw evidence. Crash leftovers remain private,
bounded and visibly incomplete until safely inspected/reclaimed.

Environment identities use an allowlisted description; explicitly approved public
settings can be recorded for reproducibility, never a bulk credential-bearing
environment dump. Any necessary secret fingerprint requires a locally protected
keyed digest, not an exported secret or an easily guessed plain digest. Key
lifecycle/loss and policy changes invalidate
dependent identity/cache evidence. WP06/WP07 must implement and test this before
such identity can be authoritative. No key value or bearer token belongs in
argv, exported metadata or logs.

The private connected descriptor is the initial IPC access capability; there is
no public endpoint that needs a reusable bearer token. Match coordinator-owned
session IDs but do not call those IDs authentication. A future named listener,
remote client, persistent daemon, new OS, broader input domain or trust model
requires a separate credential/token-lifecycle/path review and qualification.
This resolves the baseline choice without claiming cross-platform credentials,
same-user isolation or protection from malicious chosen code.

## Acceptance boundary

The previous open topics (attacker scope, IPC/token lifecycle, traversal/path
races, redaction/retention, resource bounds, supply chain and detached children)
now have explicit conservative dispositions above. The design review does not
waive any implementation gate. Section 14.3 cases map to these controls in
[the invariant review](invariant-review.md) and [WP00 acceptance](wp00-review.md).
False success, secret export, unsafe publication/deletion, unbounded buffering
or an escaped *owned non-hostile* worker remains a blocker for its claimed
profile; being listed as a threat is not acceptance of defective behavior.
