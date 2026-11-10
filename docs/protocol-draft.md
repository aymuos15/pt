# Bridge protocol v0 — serial contract revision 1

Status: **specified and synthetically tested for WP00; no complete production
bridge/session transport, validator, or conformance claim**. This is a breaking completion of an
unreleased five-event draft, not a stable public wire format. Engineering
self-review is not independent qualification. The
[baseline decision](baseline-contract-v1.md) and implementation specification
remain authoritative about execution, safety, and later-package gates.

The subsequent [WP04 private-channel foundation](wp04-status.md) supplies a
native inherited-socket handoff and separately tested Python framing/envelope
component. The later [Rust channel/accounting foundation](../crates/pt-protocol/README.md)
decodes the 18 bridge payloads and checks bounded fresh-serial ledger consistency.
Neither supplies the actual pytest observer, required artifact/environment/generation
verification, coordinator-owned final result or supported-launcher early-startup
assurance. Decoded/consistent streams cannot become full test success.

## Transport and envelope

Use a private inherited Unix socket pair, separate from test stdout/stderr, not
a named listener. The connected descriptor is a capability; mark it
non-inheritable before project imports. This does not isolate hostile code in
the same process or user account. Producer-role fields are not authentication.

A frame is a nonzero 32-bit unsigned big-endian length followed by at most
**1 MiB** of UTF-8 JSON. Reject truncation, invalid UTF-8/JSON, duplicate object
keys, non-integer numbers, unknown fields, and unsupported versions/revisions.
Never unpickle messages or resolve a supplied name into executable code. A
production reader must enforce the byte bound before allocating the payload.
These requirements are now exercised separately by the Rust reader and Python
component; they are **not features or native qualification of the decoded test-only
contract checker**. Rust's wire budget conservatively includes framing headers.

Every envelope has `protocol_version: 0`, `contract_revision: 1`, `request_id`,
`run_id`, `generation_id`, `session_id`, `producer_id`, `producer_role`,
`sequence`, `kind`, and typed `payload`. The schema defines IDs as 1–128 ASCII
letters/digits/`._:-`, starting with a letter/digit; they are opaque owned IDs,
not filenames. Exact node IDs are separate bounded strings and may be Unicode,
contain path separators, and repeat. Do not reconstruct parameter objects or
call project `repr` methods for metadata.

The revision-1 handshake names exactly CPython **3.12.12**, pytest **8.4.2**,
bridge **0.0.0**, and the request's `pytest_console` or `pytest_module` invocation
profile. Unknown tuples/revisions fail; there is no downgrade, entrypoint
substitution, dependency installation, hidden collection, or replay. This tuple
is a development target, not an implemented or qualified bridge version pair.

The explicit observer's warning `when` is an **observed delivery boundary**, not
proof of the warning's originating test phase. Pytest's deferred runtest warnings
are delivered during protocol finalization (`finalize`); assigning them a setup /
call/teardown origin would invent precision. Original filters and actual
warnings-as-errors remain authoritative. The independent reference keeps pytest's
raw hook `when` separately; this mapping does not erase its original observations.

## Catalog: 32 typed kinds

[Event schema](protocol-v0.schema.json) (`urn:pt:protocol:v0`):

| Producer | Kinds | Meaning |
|---|---|---|
| Coordinator | `request_accepted`, `request_rejected`, `environment_resolved` | Record receipt of a normalized request, prelaunch rejection, and asserted environment identity. Acceptance is not permission to execute an unsupported request. |
| Bridge | `session_started`, `collection_started`, `collection_report`, `collection_error`, `item_collected`, `items_selected`, `items_deselected`, `collection_finished` | One live session, raw collector reports, occurrence inventory, final selection and collection barrier. |
| Coordinator | `capability_decision` | Deny/unknown decisions with scope, issuer, evidence and invalidation fields; this serial revision cannot grant optimizations. |
| Bridge | `item_started`, `phase_report`, `attempt_finished`, `item_not_run` | Per-occurrence attempt lifecycle and separately reported setup/call/teardown; explicit reasons for selected work not run. |
| Bridge | `warning`, `output_reference`, `extension_event`, `artifact_ready`, `session_error`, `session_terminated` | Diagnostics, bounded artifact references, proposed extensions, readiness assertions, session errors and terminal accounting. |
| Coordinator | `artifact_declared`, `artifact_committed`, `artifact_failed` | Owned artifact requirements and final publication or failure. |
| Coordinator | `infrastructure_error`, `cancellation_requested`, `deadline_exceeded`, `resource_event`, `worker_exited`, `cleanup_finished`, `generation_checked` | Failure/control observations, raw process status, cleanup and generation assurance. |

Resource states are typed for evolution, but the initial ledger permits only
`requested -> denied`; it cannot acquire a lease. Extension shapes reserve
versioned references, **not supported adapters**. The checker rejects extension
execution. Subtests/custom collector semantics still require their own tested
adapter/oracle contract; do not flatten them into aggregate passes.

## Ordering and normalized traces

There is one coordinator and at most one bridge producer per session. IDs and
roles remain stable. Sequence starts at zero and increments by one **per
producer**, not per globally merged stream. A transport may deduplicate an
identical redelivery using the full envelope identity and contents; conflicting
redelivery or a gap fails closed. The test ledger takes an already normalized
trace and rejects *all* redeliveries. Neither rule implies exactly-once effects.

The development Rust reader also rejects all redeliveries. Its opaque per-reader
binding ties actual framed messages to clean EOF; matching opaque IDs/counts alone,
a second identical stream or manually decoded events cannot forge this binding.
EOF still proves no backend exit, required cleanup or successful work by itself.

- Request receipt precedes environment resolution and bridge handshake. A
  prelaunch rejection prohibits a bridge or worker result. Invalid input that
  cannot be normalized can fail in the CLI without inventing a pytest session.
- One collection pass supplies consecutive occurrence ordinals starting at
  zero, preserving duplicate node IDs. Selection chunks start at zero separately
  for selected and deselected lists. All occurrences precede selection chunks;
  selection is exhaustive and disjoint at `collection_finished`. The selected
  list records the **backend's final order**, which can differ from original
  collection order due to ordinary pytest/plugin hooks. PT does not reorder it.
- Every failed collector report has exactly one matching `collection_error`.
  Failed/interrupted collection has an explicitly incomplete inventory; counts
  describe observed work, not an invented complete suite.
- Execution follows the collection barrier and selected order, with at most one
  active attempt. Setup passes before call; setup skip/failure omits call, not
  teardown. Completed/retry attempts require all applicable phases. Interrupted
  attempts retain their prefix and lost-teardown limitation. A normal test-failure
  exit cannot excuse an unexplained missing attempt or phase.
- PT never retries. Only an explicitly declared backend-plugin policy, plugin
  identity, and finite attempt bound allow a failed completed attempt to request
  the next consecutive attempt of that **same occurrence**. Preserve every
  phase/outcome, including the failed original. This is a synthetic contract,
  not qualification of any retry plugin or its raw reporting adapter.
- `item_not_run` cannot relabel started work. Collect-only is separate from test
  execution; fail-fast requires an observed failure; collection-failure reasons
  require failed collection. Interruption needs a corresponding stop/backend
  error. Explicit not-run work remains incomplete for a requested execution.
- Bridge terminal state is immutable. Coordinator process exit can be observed
  before the bridge's already-written terminal frame is drained. Preserve each
  producer's order and causal barriers; do not assume a cross-process clock or
  discard buffered bridge events just because the process exited. Durations are
  elapsed observations, not cross-process timestamps to subtract/add blindly.
- Required artifact commit follows readiness, writer reaping and verified group
  cleanup. Generation observation follows process exit and the cleanup decision.
  Neither is a hidden preflight check that can authorize later changed inputs.

## Completion arithmetic and terminal result

[Final-result schema](final-result-v0.schema.json)
(`urn:pt:final-result:v0`) is a separate coordinator-owned record, **not a bridge
event**. References to the event schema resolve offline; do not fetch arbitrary
schema URLs from a project. `pt exec` process-only reports do not match it.

At a completed collection barrier:

```text
collected_count = selected_count + deselected_count
selected_count = completed_count + not_run_count + len(incomplete_ordinals)
completed_count <= executed_count <= selected_count
attempts_completed <= attempts_started
```

`executed_count` counts distinct started occurrences, not calls or attempts.
`completed_count` counts occurrences whose **last** attempt completed all
applicable phases, even if a phase failed. `attempts_completed` counts completed
and retry dispositions, not interrupted prefixes. Phase counters include every
raw attempt, so an explicitly requested successful retry can coexist with a
historical failed phase. `incomplete_ordinals` lists unstarted/unfinished selected
occurrences not already explained by `item_not_run`, in selected order. Before
a collection barrier, completeness is unknown and the flags say so; absent data
is not interchangeable with zero.

The bridge terminal's counts, phase counts and incomplete list must match the
ledger. The final record repeats them plus raw exit/signal, collection error IDs,
session/PT errors, artifact states, capability decisions, stop cause, cleanup,
generation assurance and last observed sequence for each producer. Its boolean
flags have distinct meanings:

- `accounting_verified`: a terminal assertion reconciles with the observed ledger;
  it is not proof that an unobserved test was actually executed.
- `work_complete`: the requested collection/execution was fully accounted for,
  not that tests passed. Fail-fast or interrupted execution is not complete.
  Collect-only can complete its collection request without executing tests.
- `reporting_complete`: a bridge terminal asserts reporting finalized.
- `artifacts_verified`, `environment_verified`: necessary verification claims
  requiring **external evidence** in production, not checks this ledger performs.
- `current_full_success`: only full, nonempty execution with backend/CLI zero,
  current immutable-snapshot assurance over the declared input domain, all work,
  reporting, required artifacts, environment and cleanup gates, and no errors.
  Affected/explicit scope, no-tests and collect-only never certify a full suite.

Both schemas enforce necessary structure/conditions, not cross-field arithmetic,
required-ID membership, signal arithmetic, provenance, or truth. The test ledger
checks additional internal relationships. It cannot detect a producer that
consistently lies about execution; that needs independent sentinels and WP03.

## Artifacts, failures and bounds

An artifact ID maps to a coordinator-owned output location, never a bridge-supplied
path. Before commit, the coordinator must independently verify allowed location,
file identity/type, byte count/hash, completeness and finalized writer/cleanup
state, then publish without unsafe overwrite. Ready and committed IDs, hashes,
sizes and completeness must agree. This ledger compares those **assertions**;
it does not read any artifact. Pending/failed required artifacts prevent normal
completion. Optional failure remains visible, including code/message, without
silently becoming a required failure. A partial committed artifact retains its
digest and `complete: false`; it cannot satisfy a required artifact.

The baseline precedence applies: independent infrastructure/required cleanup or
artifact failure, invalid generation, first observed timeout/cancellation, raw
signal/undocumented backend status, then completed pytest status 0–5. Preserve
secondary causes in the raw trace and final fields. A known timeout, cancellation
or crash can explain missing terminal work/artifacts without inventing an
independent protocol failure. Unexplained EOF/zero without terminal accounting is
infrastructure failure, not no-tests or success. A later zero never reverses a
stop. Session internal/usage errors remain distinct and cannot accompany zero.
`abandoned` is typed for coordinator recovery outside the live-event ledger;
no recovery/reattachment implementation is claimed.

Initial **fail-closed ceilings**, not qualifications or performance targets:
1,000,000 events; 64 MiB aggregate encoded event data; 100,000 occurrences;
16 MiB aggregate UTF-8 node-ID data; 1,024 artifacts/error summaries; 4,096
ordinals per selection chunk; at most 32 attempts per occurrence. The schemas
add string/array/count bounds. The decoded test ledger uses a conservative
compact ASCII JSON size estimate; only a future reader can enforce actual
incoming byte, queue and decoding limits. Oversize work fails visibly without
rerunning it. Queue/backpressure stall is bounded by the execution/cleanup
deadlines; output must not be buffered indefinitely or used as a control channel.

The [threat-model review](threat-model.md) adds production-reader requirements
(at most two pending wire frames/2 MiB payloads and JSON depth 32), restrictive
artifact ownership, explicit storage budgets and channel-bound producer roles.
These are not features of the decoded test checker or a new qualification claim.

## Evidence and open implementation gates

[Synthetic contract tests](../tests/contracts/README.md) cover valid/failure
scenarios and mutations, separately from the harness's event-schema checks.
They always report `qualified: false`, with artifact/environment/generation
evidence checks false. They are neither a production validator nor the real
semantic oracle. No PT conformance or timing claim follows from their passing.

WP03 must independently establish actual work and adverse semantics. WP05 must
implement an observational same-session bridge and respect plugin/entrypoint
behavior. WP09/WP16 must implement/fault-test framing, authentication/ownership,
buffer bounds, path races, artifact verification and crash recovery. Strict
snapshot/live-tree assurance needs its own implementation/evidence; live-tree
observation is not immutable-snapshot proof. These gates remain open.
