# Correctness invariants: preliminary review

Status: **engineering self-review map, not qualification evidence**. This traceability
map identifies the evidence needed to review C01–C12 in section 2.2 of the
specification. No PT pytest backend exists. Partial process-only C03/C08 evidence
is recorded in `wp04-status.md`; synthetic ledger evidence does not qualify any
product semantic or generation invariant.

| ID | Boundary to qualify | Minimum adverse evidence still needed |
|---|---|---|
| C01 | Index is never authoritative collection. | Custom collectors and tests outside index heuristics still run; syntax errors reach pytest. |
| C02 | Default collection and execution share one pytest session. | Import/collection sentinels show one session, including collection errors, selection and `--collect-only`. |
| C03 | A process that executed tests is never reused for a later run. | Multiple invocations show distinct session PIDs and no leaked module globals or interpreter state. |
| C04 | Unknown capability disables optimization, not a plugin. | Unknown/dynamically loaded plugin remains enabled and relevant capability falls back with an explanation. |
| C05 | Started work is not automatically replayed. | A test with an external side effect followed by late incompatibility or crash has no invisible second attempt. |
| C06 | Collection, setup, call, teardown and infrastructure failures stay distinct. | Setup failure, teardown error following a passed call, strict XPASS, collection and bridge failures produce separately identifiable outcomes. |
| C07 | An older generation cannot make a newer one green. | Concurrent edits, late results, edit-and-revert, watcher overflow and uncertain integrity never publish a current success. |
| C08 | Hard timeout terminates the owned boundary. | A hanging worker and ordinary descendant are stopped, unfinished work is interrupted, and lost teardown is recorded. Detached hostile descendants are outside the sandbox claim. |
| C09 | Full success requires complete work and finalization. | Lost phase event, worker crash, artifact write failure, incomplete coverage merge and failed cleanup cannot yield full success. |
| C10 | Selection, reordering, fixture replication and resource reuse have independent permissions. | Denying one permission does not imply permission for another; conflicts or unknown evidence fall back or fail before effects. |
| C11 | Required validation, reporting, coverage and shutdown stay inside the relevant latency boundary. | Inject independently measured delays into each stage and verify the outer endpoint includes them. |
| C12 | A benchmark mismatch is a correctness failure. | A candidate that drops tests, changes outcomes, omits coverage or returns stale results is rejected even if faster. |

## Section 14.3 design review and evidence boundary

The following groups retain the entire adverse inventory as obligations, not
exclusions to manufacture agreement. The baseline contract, capability policy
and protocol define the disposition; every real profile/plugin case still needs
an independent oracle and a recorded pass/fail/unsupported/uncertain result.

| Adverse cases | Contract/disposition | Current evidence and required real checks |
|---|---|---|
| Autouse fixtures; scope/override/parametrization; dynamic lookup; yield/finalizer exceptions | C02/C06/C10: preserve the backend's lifetimes, multiplicities and effects; no fixture replication or reset shortcut. | Synthetic setup skip/failure and teardown-error phases only. WP03/WP05 must compare fixture sentinels and supported hooks; custom semantics need an adapter or explicit unsupported result. |
| Setup skip/failure; teardown error after passed call; strict XPASS | C06/C09: setup may omit call, not teardown; preserve xfail/xpass reason/strictness and phase failure. | Contract scenarios/mutations retain raw phase outcomes and reject missing phases or false zero. Real pytest behavior and observer effects remain unqualified. |
| Collection errors; duplicate node IDs; Unicode paths/IDs; doctest; unittest; custom collectors | C01/C02/C06/C09: authoritative same-session inventory, exact identities/order and collection errors; no static-index filtering or deduplication. | Synthetic partial/interrupted collection, duplicate Unicode occurrences, selection and lost-identity checks. Actual custom collection/doctest/unittest need WP03/WP05 traces/sentinels, not JUnit pass totals. |
| Hook wrappers/order; warnings-as-errors; fd stdout/stderr capture; async/property-based plugins; dynamically loaded plugins; session hook inspecting selected items | C02/C04/C06/C10: preserve plugin discovery/options and hook behavior; unknown capability denies optimization, never the plugin. | Typed warning/output references and deny/unknown decisions only. Real plugin/capture/warning behavior and bridge introspection need oracle tests/versioned support decisions. Extension shapes do not mean support. |
| Subprocesses; import-time database writes; module globals; repeated invocations | C02/C03/C05/C08: fresh sessions, one collection pass, no automatic replay, bounded owned-process termination; detached/hostile descendants remain outside containment. | WP04 process-only freshness/ordinary-descendant tests; synthetic attempt rules. WP03/WP05 must verify import/side-effect multiplicities, no hidden probe/replay, and actual teardown loss after death. |
| Same-size/same-mtime edits; edit-and-revert; deletion/rename; symlink retargeting; external data; environment/editable dependency changes; dependency upgrades; watcher overflow; stale same-second bytecode | C07/C09: content/input identity and declared assurance, unknown/superseded/uncertain integrity cannot become current green; live-tree is not snapshot proof. | Ledger rejects asserted stale/live/unverified generations, requires end-of-run observation and matches identities. It never touches sources or proves installed files. WP06/WP08/WP15 must verify actual loaded code and adverse edits; unknown external inputs cannot be silently omitted. |
| Corrupt caches; lost/duplicate/truncated events; invalid versions; worker death before acknowledgement; coordinator death | C05/C06/C09: fail closed, never infer execution from missing acknowledgement or reattach/replay executed state. | Schema/version and normalized loss/duplicate/terminal mutations; abandoned is schema-only. No framing, transactional cache, authenticated recovery or production transport tests yet (WP07/WP09/WP16). |
| Disk-full writes; broken pipes; orphaned descendants; OOM; interrupted coverage merge | C06/C08/C09/C11: preserve raw failure, require actual termination/reaping and required finalized artifacts within the endpoint. | Synthetic ready/commit mismatch, partial/failed required artifact, cleanup/terminal failure and timeout precedence. WP09/WP15/WP16 must fault-test actual bytes, merge, I/O and ownership; a checksum assertion is not verification. |

The exploratory corpus probes run against direct pytest and its harness timing
checks do not establish PT parity or a qualified campaign. Full adverse plugin,
source-integrity and fault-injection executions remain open. C11/C12 require
independent lifecycle timing and broken candidates, not this contract ledger.
