# Execution contracts — conservative baseline

Status: **accepted for baseline engineering by WP00 self-review, 2026-11-09**.
This is a definition, not an implemented runner or qualified support claim. The
[acceptance record](wp00-review.md) distinguishes this review from all later
gates. The [implementation specification](pt-implementation-spec.md), C01–C12,
and its dependency order remain authoritative. This replaces the earlier draft's
unresolved prose; the original decisions/history are retained in git and
[baseline contract v1](baseline-contract-v1.md).

## Target, reference and exclusions

The selected initial target is Linux x86-64, GIL-enabled CPython **3.12.12**,
pytest **8.4.2**, bridge package **0.0.0**, Rust **1.99.1**, and fresh serial real
pytest. Neither the tuple nor the bridge skeleton is qualified. Required native
process/procfs features must be checked; there is no blanket kernel, libc,
distribution, plugin or neighboring-version support claim.

`pytest_console` and `pytest_module` are distinct invocation profiles. Reference
and candidate match interpreter, entrypoint semantics, exact OS argv, cwd,
relevant environment, source, configuration, plugin discovery/options and output
policy. No shell, interpreter/entrypoint substitution, dependency mutation,
silent plugin suppression, or hidden preflight collection is allowed. The Rust
coordinator does not import project Python. A metadata-only `doctor` is not
runtime/environment verification or permission to assert test success.

Pytest collects and executes in the same fresh session, preserving occurrence
multiplicity, exact node IDs, final selected order, fixtures and phase outcomes.
No source index can exclude an ordinary full-run candidate. Persisted plans are
descriptions, never live collectors, fixtures, parameters, callables, heaps or
pickled sessions. A process that executed tests is destroyed, not reset/reused.

Parallel execution, affected selection, cache-authoritative reconstruction,
preload/project snapshots, service reuse, non-Linux profiles and interactive
stdin are unavailable in this baseline. Reject a required unavailable feature
before effects; a preferred optimization stays on the conservative route with
an explanation. There is **no implemented passthrough profile**. `pt exec` is an
explicit process diagnostic, not pytest passthrough or conformance certification.
An unsupported condition discovered after effects preserves those effects and
errors; it does not pretend no launch occurred or replay work under a fallback.

## Scope and permissions

`full` is bounded by the declared reference project/configuration and selection
policy, not a promise to find every possible Python test. Explicit user targets
or subset selectors are labelled `explicit`; PT-chosen subsets are `affected`.
Neither can update whole-suite success. Backend-native default deselection must
remain visible and match the declared reference; a nonzero deselection count
alone does not prove PT narrowed scope. Unknown effective selection policy
cannot justify a current full-suite claim. The real coordinator/oracle must
establish scope from the request and same-session backend, not trust a flag in
a synthetic fixture. Do not run a second collection just to establish it.
If a full request's scope cannot be reconciled, report incomplete accounting
(`infrastructure_error`) rather than grant the full flag; retain the observed
backend status and effects. Unknown optimization permission alone is not a
reason to disable a plugin or change its selection behavior.

The [capability policy](capability-policy.md) names separate permissions and
reference contracts for every transformation. This serial revision admits only
session-scoped `deny`/`unknown`, never `allow`. Unknown, conflicting, stale or
wrong-scope evidence disables the transformation, not a plugin. No fallback
replays started work. An explicitly configured backend retry plugin is a
separately qualified backend contract and must retain every original attempt;
synthetic retry examples do not qualify such a plugin.

## Output and process boundary

Preserve caller stdin/stdout/stderr descriptors, non-terminal input, cwd and
environment; no PT-added output capture buffer, pseudo-terminal or color/TTY
substitution. Pytest retains its own capture, warning, verbosity and traceback
policies. Binary bytes and OS argument boundaries are not reinterpreted.
Terminal stdin is rejected before work until foreground job control is
implemented and qualified. Output-only TTY inheritance does not imply interactive
terminal equivalence. Exact cross-stream byte interleaving, PIDs, timestamps and
resource use are not promised equal.

Control messages use the private channel, never stdout/stderr. PT diagnostics
are distinct from backend output. Structured reporting is additive and explicit;
do not silently redirect pytest's requested report/coverage paths to make
verification easier. If a required artifact location/plugin cannot satisfy the
declared verification contract, classify that feature as unavailable before
work where possible; late failure retains effects and cannot become green.

One invocation owns one fresh process group and its ordinary, non-detached
members, including residual members after leader exit. Timeout/cancellation
terminates that boundary with a separate bounded cleanup deadline. Keep leader
identity allocated through final signaling, then reap it. Unverifiable cleanup
is not success. Detached/hostile descendants, external services, uninterruptible
kernel waits and coordinator SIGKILL are not solved by a process group. Never
promise teardown after a hard kill. See the [threat model](threat-model.md).

## Completion and typed exits

The [protocol contract](protocol-draft.md) and
[final-result schema](final-result-v0.schema.json) define the 32 event kinds,
collection/selection partitions, attempt/phase arithmetic, artifact assertions
and flags. Their synthetic tests do not authenticate producers, verify real work,
read artifacts, validate an installed environment or establish an immutable
generation. A checksum/`verified: true` supplied by a project is not verification.

Current full success requires nonempty full execution, complete authoritative
work/phase accounting, reporting, independently verified required artifacts and
environment, required cleanup, and current immutable-snapshot assurance over the
declared input domain. Collect-only completes collection, not execution; no-tests
is not a full success; fail-fast and interrupted work remain explicit. Unknown
external inputs, stale/uncertain generation or live-tree-only observations cannot
satisfy this baseline's strict full-success assertion. These are product gates,
not a claim that snapshot/runtime identity verification already exists.

| Outcome | Condition | CLI exit |
|---|---|---|
| `backend_completed` | Pytest completed with all applicable accounting, identity and finalization gates | Original 0–5: success, test failure, backend interruption, internal error, usage error, no tests. |
| `configuration_error` | Invalid PT input, interpreter selection, cwd or required feature before work | 4 |
| `unsupported_profile` | Required platform/version/backend/feature unavailable before work | 4; no implicit passthrough |
| `launch_error` | Validated launch failed at the OS boundary | 3; no replay |
| `backend_terminated` | Raw child signal or undocumented backend exit | Linux `128 + signal`; undocumented code maps to 3; raw status retained |
| `timeout` | PT execution deadline | 3, even if the child later exits zero |
| `interrupted` | PT signal/explicit cancellation | 2, even after later zero; signal/origin retained |
| `infrastructure_error` | Required protocol/accounting/I/O/report/artifact/supervision/cleanup failure | 3; preserve secondary test failures |
| `generation_invalid` | Required source/input generation assurance not current or verifiable | 3; never current full success |
| `abandoned` | Recovery finds unfinished coordinator state | 3; no executing-session reattachment |

After launch the precedence is independent infrastructure/required-cleanup
failure, invalid generation, first observed PT timeout/cancellation, raw signal
or undocumented exit, then completed pytest status. Retain secondary causes and
the raw trace/status. Known death/stop can explain missing terminal reports
without inventing an independent error. An unexplained zero/EOF cannot. A Linux
signal mapping is an ordinary CLI exit, not a claim PT itself was OS-signaled.

Help/version success and `doctor` metadata success are control-operation results,
not test results. Diagnostic `process_exited` preserves an arbitrary child code
only after process cleanup; it is deliberately absent from the full-test-result
schema. Invalid unnormalizable CLI input need not invent run IDs or a test
inventory. The implementation must classify its own I/O/publication failures;
the present prototype is not claimed to cover every such adverse path yet.

## Review disposition and implementation gates

[C01–C12 and every section 14.3 adverse group](invariant-review.md) were reviewed
against these definitions; actual oracle, plugin, coverage, edit-race and fault
tests remain mandatory. [WP00's acceptance record](wp00-review.md) closes the
baseline definition review only. WP01–WP03, WP04 completion, WP05's real observer,
generation assurance, production protocol/security and release review are not
waived. No optimization, support profile or performance claim is enabled here.
