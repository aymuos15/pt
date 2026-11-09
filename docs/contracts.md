# Execution contracts — WP00 draft

Status: **proposed, unreviewed, not implemented or qualified**. The
[implementation specification](pt-implementation-spec.md) remains authoritative;
this document begins WP00 and does not close its acceptance criteria.

The later [baseline contract v1](baseline-contract-v1.md) resolves the initial
target, process/output boundary, exit precedence, and transport choices for
conservative WP04 engineering. It is explicitly self-reviewed, not qualification.
The historical proposals below are retained; where they leave those decisions
open, the later record takes precedence.

The later [protocol revision 1](protocol-draft.md) and
[final-result schema](final-result-v0.schema.json) define the typed completion
flags, collection/attempt accounting, artifacts, all terminal categories and
precedence, with synthetic consistency tests. These supersede the historical
unresolved mapping/transport statements below; they do not implement a backend
or verify actual work, environment or generation evidence.

## Serial reference

The initial product delegates execution to real pytest in a fresh Python process
for each run. Its reference is a fresh invocation of the same pinned interpreter,
pytest entrypoint, arguments, source, relevant environment, and plugin
configuration. The exact supported versions remain undecided. Console pytest
and `python -m pytest` are distinct invocation profiles, not interchangeable
aliases.

Pytest performs authoritative collection and execution within the same session.
No hidden preflight collection is allowed. PT must preserve the reference's
collection multiplicity and order, selection, fixture lifecycle, phase outcomes,
and exit behavior within the eventual supported profile. A static index is not
authoritative collection. The coordinator does not import project Python code.

## Scope and transformations

Full, affected, and parallel runs have distinct contracts. A successful affected
run describes only its selected scope; it does not certify the full suite.
Parallel behavior is compared to an explicitly pinned parallel reference, not
automatically to serial pytest. Selection, reordering, fixture replication, and
resource reuse each require separate permission. Unknown capabilities deny the
relevant optimization, not the plugin. Started work is never automatically
replayed as a fallback.

## Completion and outcomes

A full-run success requires complete accounting of requested work, a valid
current generation, successful required reporting and finalization, and reaping
the owned execution processes. Required coverage artifacts and lease cleanup are
part of completion when applicable. A late, superseded, uncertain, incomplete,
or infrastructure-failed result cannot mark the current full run successful.

Setup, call, teardown, collection, and infrastructure failures remain distinct.
For a completed pytest session, preserve its exit status. PT-originated usage
and infrastructure failures map to documented pytest-compatible categories with
additional typed causes; exact representation and signal behavior remain to be
specified and tested. Unsupported profiles must report unsupported or use an
explicitly requested passthrough, never silently claim conformance.

Default pytest output should remain available, with structured reporting
additive. Capture, TTY, color, warnings, and output destinations are part of the
invocation contract; exact supported behavior remains an open WP00 decision.

### Proposed terminal outcome mapping

This table is a draft to review and test, not implemented behavior. A pytest exit
code is preserved only after all PT completion checks relevant to the result
pass. In particular, a backend zero cannot override incomplete reporting, failed
cleanup, or uncertain/superseded generation integrity.

| Condition | Proposed terminal category | Proposed process exit |
|---|---|---|
| Completed pytest session with valid accounting and finalization | `backend_completed` with original backend code | Preserve pytest's code: 0 success, 1 tests failed, 2 interrupted, 3 internal error, 4 usage error, 5 no tests collected. |
| Invalid PT configuration or unsupported required profile before execution | `configuration_error` | 4 (usage error). |
| PT bridge/protocol failure, missing reports, failed required artifact commit, or failed required cleanup | `infrastructure_error` with typed cause | 3 (internal error), even if pytest returned 0. |
| Relevant source generation superseded or integrity uncertain | `generation_invalid` with assurance and cause | 3; never current full-run success. |
| PT-enforced timeout | `timeout` with phase, interrupted work, cleanup and teardown limitations | 3, unless a documented platform signal policy applies. |
| Explicit cancellation or user interruption | `interrupted` with origin and cleanup status | 2 when represented as an ordinary exit; platform signal termination remains distinct. |
| Child terminated by signal or an undocumented backend status | `backend_terminated` with raw status and signal when available | Platform-appropriate propagation is unresolved; must not become success. |

An affected run that completes successfully may return 0, but its typed result
must label the scope and cannot update full-suite success. A completed pytest
no-tests exit stays 5; missing accounting must not be mistaken for no tests.
Configuration failure and timeout mappings need compatibility review. If a
completed backend error and a PT infrastructure error both occur, preserve both
in the structured result; the user-facing exit follows the reviewed precedence
policy, not a silently discarded cause. Exact signal handling and precedence
remain open.

## Integrity and safety

Live-tree observation must not claim immutable-snapshot assurance. A hard
timeout terminates the owned execution boundary and records interrupted work and
lost teardown guarantees. This is process supervision, not a sandbox for hostile
tests. No cached pickle is executed and no raw credentials are exported in plans.

## Remaining WP00 work

Freeze and review the exact support matrix and invocation profiles; draft the
protocol, threat model, benchmark charter and ADR001–ADR006; specify every exit
path and output behavior; and review all C01–C12 invariants and the adverse cases
in section 14.3. No optimization or conformance claim is approved by this draft.
