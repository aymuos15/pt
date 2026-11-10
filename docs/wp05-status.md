# WP05 conservative observer progress

Status: **partial development implementation; WP05/M1 acceptance remain open**.
There is an explicitly loaded real-pytest observer, not a complete runnable
coordinator backend, qualified ecosystem/support profile or full-result API.

## Implemented boundary

- `pt_bridge.pytest_observer` is loaded only by an explicit `-p`. Package import /
  installation still has no auto-plugin or pytest shadow. A closed, bounded
  coordinator configuration names an already-owned private socket, exact target,
  invocation/mode and finite lifetime/budgets. No dependencies are installed or
  changed during a run.
- Pytest owns normal configuration, one authoritative collection and the standard
  serial run loop in the **same fresh process**. Hooks observe collector reports,
  occurrence identities (including duplicate node IDs), final selection order,
  setup/call/teardown, reasons, xfail/strict-XPASS and warnings without requesting
  arbitrary parameter representations. No optimization, hidden selection,
  collection preflight, cache, preload, replay or scheduling is introduced.
- Missing applicable reports or unsupported retry/parallel/metadata/finalizer
  semantics are visible, not disabled plugins or invented passes. Actual outer
  finalizer hooks still execute but cannot supply a reporting-complete assertion.
  Collect-only, fail-fast, failed collection, no-tests and interruption remain
  distinct from successful complete test execution.
- The [native protocol foundation](../crates/pt-protocol/README.md) supplies
  independently checked typed framing/accounting, opaque actual EOF provenance
  and normal-process-return cross-checking. A snapshot/terminal remains evidence
  of necessary channel consistency, not work honesty or full-result certification.

See the [bridge configuration and limits](../python/pt_bridge/README.md). Warning
`when` denotes its **observed delivery boundary**: pytest delivers runtest warnings
after its capture context, so the bridge uses `finalize` rather than inventing an
originating test phase. Original filters and actual warnings-as-errors stay in
pytest. Captured output sections/rich exception artifacts are not silently claimed
as already integrated; ordinary pytest stdout/stderr remain available.

## Initial evidence (base d17fc99)

The first retained native-subject comparison passed **five real methods / 58
fresh pytest requests** (`55.162s`): ten serial-core cases, async/Hypothesis/SQLite,
both entrypoint profiles, selection, collect-only, fail-fast and no-tests. Each
normal group compared plain pytest, the independent reference observer and the
product observer on new copies at the same literal work path. Actual exits,
JUnit, exact external effects, inventory/order and phase/reason projections
matched. The explicit outer-finalizer control retained its cleanup and visible
unsupported classification. Evidence: `/tmp/opencode/pt-observer-real-controls-83gy7m5u`.

Four new native Rust methods passed against an explicitly selected offline core
environment, exercising **six** real pytest requests: same-session import/globals /
shared fixture effects and intentional failure, final backend reordering,
collect-only, fail-fast/no-tests and late-finalizer rejection. These feed actual
Python-produced frames through the Rust reader/ledger under native supervision;
they do not reconstruct a lost return from artifacts. Five metadata controls
also passed (`0.003s`), including closed bootstrap bounds and absence of extra
custom `str`/`repr`/attribute-hook evaluation for report metadata.

Expanded warnings/dynamic-plugin/invalid-bootstrap, installed-wheel and final
regression evidence is recorded after actual completion, not inferred from this
first run. All observations remain **unqualified**, not timing/speedup samples.

The expanded eight-method check passed **70 actual requests** (`65.130s`) at
`/tmp/opencode/pt-observer-expanded-controls-xwa7yd3s`, preserving normal warnings,
warnings-as-errors, dynamically imported plugins/session inventory hooks and
three bootstrap rejections before conftest import. Sources stayed unchanged.
The offline-built wheel's source bytes match every current bridge module; its
SHA-256 is `e7a26708d019f0bfc00e1f2edb1d85f2ed4038c8b4eba56341b01579713046bb`,
retained at `/tmp/opencode/pt-observer-wheel-q_qm687n`. A disposable installed-wheel
smoke passed both explicit entrypoints, one import and fixture cleanup, while
ordinary pytest/pytest11 entries stayed unchanged and unreviewed startup inputs
remained rejected. This is not an authenticated release build or launch approval.

The next full check passed **85 locked release Rust tests**, including six native
real-pytest methods / eight requests and actual KeyboardInterrupt/SIGKILL-after-
effect controls. Its Python integration run then retained **53 passes / one
reader error**, rather than hiding it: the independent test reader assumed every
JUnit testcase had a `name`. Actual interrupted pytest produced
`<testcase time="0.000"/>` with suite `tests="0"`. That unnamed row must remain
**unknown**, not be reconstructed into an occurrence or inferred passed merely
because it lacks `<failure>`. Evidence and all 74 actually attempted observer
requests remain at `/tmp/opencode/pt-observer-final-verification-p2l68x2h`; the
remaining two interruption arms were not run in that invocation. The corrected
bounded reader now retains null identity/unknown outcome only for documented
interruption/internal-error exits and refuses such rows for ordinary completion.
Two independent parser controls cover this and ambiguous/entity/oversize inputs.

The separate **63 oracle checks passed** (`30.494s`) and **68 contract/audit checks
passed** (`8.722s`). Final corrected integration verification is recorded after
its new actual invocation, never substituted into the failed record above.

The new corrected integration invocation passed **all 56 checks** with no skips
(`73.584s`), including **ten real observer methods / all 76 planned requests**
and the two unnamed/unsafe-JUnit parser controls. Plain/reference/bridge projections
matched for the real interruption and explicit Unicode parameter-ID/FD-capture
cases too; no extra project parameter `repr` was requested. Evidence:
`/tmp/opencode/pt-observer-corrected-integration-0k86c68f`, with actual returns,
all source hashes unchanged, raw streams, work histories and unknown interruption
JUnit rows preserved. Clippy `-D warnings` and rustfmt passed after this correction.
The last complete independent harness remains **762 tests: 761 passed / one
existing native-peak skip**; it was not pointlessly rerun for these bridge-only
changes. Six existing Cargo/Python/support/toolchain/candidate files are unchanged;
the bridge metadata changed its description only, not its pinned dependencies.
Static read-back also checked **83 local links** and both original private base
prefixes after all subject setup: each still matched **all 4,971 manifest entries**
with no missing, extra or changed entries. This is an end observation, not atomic
runtime/environment or immutable-generation proof.

## Required before acceptance or enabling successful `pt run`

- Integrate the coordinator request/entrypoint/process boundary without unsafe
  early descriptor exposure or silent environment/argument/plugin changes.
  Static startup checks and late FD noninheritability cannot waive earlier hooks.
- Independently verify required output/coverage/exception artifact locations,
  bytes and no-overwrite commit **after writer reaping and required cleanup**.
  Additive artifact requirements cannot be inferred from a ready claim or JUnit.
  The subsequent [native retention foundation](wp09-status.md) now checks bytes /
  publication, but generic required format/accounting completeness is still open.
- Establish complete interpreter/installed/plugin/host identity and immutable
  generation assurance over the explicit requested input domain. End hashes and
  live-tree observations are not proof against transient edit-and-revert.
- Complete the mandatory supported serial differential/adverse matrix, fault /
  cleanup/output-backpressure checks and explicit support/exclusion report. The
  current test projection excludes rich capture sections, coverage/required
  reporting, arbitrary introspection and unsupported extension/retry adapters.
- Close WP01–WP03 acceptance and independent release gates with real evidence.
  Native `memory.peak`, representative repository qualification, independent
  review/reproduction and release provenance are not supplied by these hooks.

No current/full-success field or qualified release claim is available. `pt run`
continues to reject the unavailable operation rather than return a false green.
