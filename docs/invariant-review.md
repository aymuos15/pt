# Correctness invariants: preliminary review

Status: **draft, unreviewed, not implementation evidence**. This traceability
map identifies the evidence needed to review C01–C12 in section 2.2 of the
specification. No PT backend exists, so every product invariant remains untested.

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

The draft corpus currently has small probes for C02/C06-related behaviors, but
they have only been run against pytest. The timer and paired driver are
exploratory and do not establish C08, C11, or C12 for PT or qualify a benchmark
campaign. Full adverse inventories, plugin cases, source-integrity cases and
fault injection in section 14.3 remain to be designed and executed.
