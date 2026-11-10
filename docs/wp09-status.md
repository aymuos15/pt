# WP09 core protocol/reporting progress

Status: **partial development foundation; WP09/M1 acceptance remain open**.
This does not implement a complete coordinator result, secure store, qualified
launcher, backend, generation assurance or successful `pt run`.

## Existing component evidence

- [Native bounded bridge reader and serial ledger](../crates/pt-protocol/README.md):
  18 bridge payloads, actual EOF provenance, typed same-session necessary accounting
  and no full-success API. Base `d17fc99` passed 79 locked release Rust methods and
  2,372 independent schema/wire-shape adversaries. These are not all coordinator
  event/catalog/final-result requirements.
- [Explicit real-pytest observer](wp05-status.md): base `78ef9f9` has actual native /
  plain/reference/bridge tests, with 85 Rust checks and the corrected 56-check /
  76-request integration run. Rich artifact/report/coverage semantics remain
  explicitly separate, not inferred from matching phase counts or JUnit.

## Verified artifact component checks (base 78ef9f9)

The new [`pt-report`](../crates/pt-report/README.md) component pins native directory
and file identities, rejects unsafe traversal/links/types/ownership, independently
copies/hashes/rereads declared bytes, and publishes privately without replacement
only after actual writer reaping/cleanup evidence. Bounds and one absolute
lifetime deadline fail visibly. No source repair, arbitrary overwrite/delete,
started-work replay or stale-root recovery exists.

Crucially, readiness/hash agreement alone cannot establish required completeness.
At that foundation revision, an independent coordinator exact-byte contract was
the only completeness policy; unknown variable reports could be retained but stayed
**ineligible for required-complete status**. Generic JUnit/coverage/exception
format and semantic adapters, actual coordinator request/process association,
complete environments and immutable generations remain open. This component
cannot certify any full test result.

The selected digest dependency is explicitly pinned `sha2 0.11.1` with default
features disabled and its lock/checksums retained. The existing nix 0.30.1 gains
filesystem/user features, not a version substitution. Final dependency identity
and native verification records follow actual returns, not estimates.

Development failures are retained: the first fixture pass created directories /
files using the inherited group-writable umask, so the product correctly rejected
12 purported positive controls at the private-parent guard (four other controls
passed). The fixture now explicitly creates **its own new** private entries; the
guard was not relaxed and no user output/cache was repaired. A subsequent helper
compile failed because its private `fs` wrapper omitted `hard_link`; that import
was corrected before those new controls could execute. These are setup corrections,
not eliminated benchmark samples or automatic project-test retries.

The final retained locked release workspace run passed **104 tests**, no skips:
the prior 85 plus **18 artifact controls and one real pytest/JUnit/hash case**.
Clippy `-D warnings` and rustfmt passed. Sources stayed fixed; actual command
returns and full stdout/stderr are retained at
`/tmp/opencode/pt-artifact-final-verification-mvv4nrep`. The real JUnit scenario
retains the actual pytest assertion-failure exit **1**, fixture cleanup and exact
published bytes; independent stdlib XML/hash inspection does not silently become
a production generic-completeness adapter. Unknown required completeness stays
blocked despite a true ready claim.

All **38 prior Cargo package identities/checksums** remain unchanged. The new
local crate adds exactly seven registry identities: sha2 **0.11.1**, digest
**0.11.3**, block-buffer **0.12.1**, crypto-common **0.2.2**, cpufeatures **0.3.1**,
hybrid-array **0.4.15** and typenum **1.20.1**. Every cached `.crate` archive's
independently rehashed SHA-256 matched its lock checksum. sha2's is
`47d7069beb7d6ac7b9acd1039986e73443f24234f41074da099d6f994ac9ad19`.
This is pinned artifact identity, not signed-build authentication or an
independent supply-chain/security audit. Python/package/support/toolchain pins
and bridge source bytes are unchanged by this batch.

The unchanged Python bridge retains its latest **56 integration checks / 76
observer requests**, **63 oracle checks** and **68 contract checks** from WP05.
The unchanged independent harness retains **762 tests: 761 passed / one native
peak capability skip**. Those large suites were not needlessly relabelled/rerun
as artifact-native or resource qualification. Complete format adapters,
coordinator integration, environments/generations and release gates below remain
open; no successful `pt run` is enabled by the component.
Static read-back checked **74 local links**, five unchanged Python/support /
toolchain/candidate pin files and all unchanged bridge source modules.

## Pinned JUnit completeness adapter (base fdf6241)

The new `pytest-8.4.2-xunit2-no-extra-data-v1` policy derives ordered XML
occurrences, outcome/message/skip kinds and the formatter's exact suite counters
from the **already validated live serial ledger**, not from report bytes.
`ArtifactStore::commit_with_junit` checks the owned pending copy before native
no-replace publication, preserving all earlier byte/hash/readback/cleanup/deadline
requirements. Unknown completeness, missing context and partial ready claims
still cannot become required-complete. These are component prerequisites, not
coordinator execution, full work, environment, immutable generation or release
qualification.

The adapter covers default xunit2/no-extra-data reports, exact requested suite /
prefix options, collector skips/errors, duplicate custom occurrences, doctest /
unittest, strict XPASS, applicable phase outcomes, fail-fast, collect-only and
empty suites. Counter arithmetic is intentionally **not occurrence/XML-row
counting**: pass-plus-teardown-error counts two suite tests in one XML row;
call-plus-teardown-failure emits two XML rows but subtracts its double-failure
count. Interrupted unnamed testcases and incomplete attempts stay unknown and
cannot supply an expectation. Unsupported properties, capture/legacy nodes and
format changes are rejected, never removed or suppressed in pytest.

The claim is the named structural/identity/outcome/message/counter projection
only. Nonempty required diagnostic bodies are checked, but complete traceback
byte equivalence, coverage and rich exception/capture semantics require separate
adapters. The trusted coordinator must bind snapshots, actual process returns,
writers and requests correctly; public snapshots/content cannot authenticate that
association or recover a missing return. The [component limits/API](../crates/pt-report/README.md)
make those exclusions explicit. `pt run` remains unavailable.

Initial focused controls passed **35 artifact/parser methods plus six native
JUnit methods / 23 fresh real pytest requests**, and the existing real JUnit
retention method. All ten declared core fixtures, both explicit entrypoints,
report modes/counters, collection skip/continue-errors, Unicode/entity data,
actual unknown interrupted JUnit and four unsupported reporting extensions were
exercised. Each native request used real framing/EOF/ledger/cleanup, a source
copy and an independent isolated stdlib XML/hash probe. Every intended pytest
failure exit stayed nonzero; an unsupported extension was a reporting failure,
not an excuse to change the user's passing pytest behavior.

Development failures/corrections are retained rather than promoted to passes:
the original unverified draft used quick-xml's old byte API against its pinned
0.42 string API, so its first `cargo check` stopped at compilation. A new test
source also had an incorrectly quoted Rust/Python literal, caught by rustfmt
before executing those new arms. Independent stdlib XML mutations then found a
real parser strictness gap: the pull reader accepted adjacent quoted attributes
without XML's required separator, e.g. `name="pytest"errors="0"`. Typed closed
attributes alone did not reject it. A bounded lexical separator guard now rejects
that malformed input; its independent adversary remains in the suite. An explicit
test-helper argument-count clippy diagnostic was corrected without changing any
runtime behavior. Final locked release and retained-mutation evidence follows
its actual return, not the earlier partial checks.

The final **locked, offline release workspace passed 128 tests**, no skips;
rustfmt and clippy `-D warnings` passed. This includes **36 artifact/parser
methods**, six real JUnit methods / **23 fresh pytest requests**, and the existing
real JUnit content-only check. All **23 independent stdlib XML/hash probes**
returned successfully; raw streams, actual process reports, original/published
report bytes and frozen source hashes are retained at
`/tmp/opencode/pt-junit-final-verification-xalhnzal`. Sources stayed unchanged.
The independent literal XML corpus and Rust adapter agreed on **2,153 controls:
54 accepted / 2,099 rejected**. These are synthetic parser controls, not 2,153
executed pytest sessions or independent ecosystem observations.

All **46 prior Cargo package identities/checksums** remain unchanged. The only
new registry identity is **quick-xml 0.42.0**, default features disabled, using
the existing memchr identity. Its independently rehashed cached archive matched
lock SHA-256 `41b1177fdf999d2321d3fb46ff47159d9c1fb9ad66a4879f8c50a0b504615e9b`.
The selected parser requires Rust 1.86, below the already selected 1.99.1 target;
this does not widen the tested platform/toolchain matrix. No Python dependency,
bridge source, support profile or candidate allocation changed. The unchanged
762-test harness and prior Python observer/oracle/contract evidence are not
unnecessarily rerun or relabelled as new JUnit/resource qualification.
Static read-back checked **72 local links**, five unchanged pin/candidate files,
all unchanged bridge modules, Python test-source syntax and the still-matching
frozen native source hashes before committing this batch.

## Required before acceptance

The owned session-lifecycle foundation below joins process/channel observation,
but does not remove the remaining requirements in this list.

- Wire the complete coordinator-owned request, environment, artifact, process /
  cleanup, generation and final-result catalog to actual independent evidence.
- Implement supported required report/coverage/exception completeness and request
  accounting adapters. Unknown required output cannot pass on a ready flag.
- Preserve argument/entrypoint/plugin semantics and qualify the actual supported
  launcher's early initialization/private-descriptor boundary.
- Fault-test complete integrated execution, output/backpressure, publication loss,
  coordinator death/abandonment, ordinary descendants and required cleanup.
- Complete declared-input/current immutable-generation and installed/host identity
  assurance; end hashes/live-tree observation do not waive edit-and-revert risks.
- Qualify the finite claimed corpus/profile and independent resource, review,
  release-build/provenance and reproducibility gates. Native peak absence remains
  unknown/blocked, not an invented zero or synthetic qualification.

No production speedup, complete work-package acceptance or release claim follows
from these components.

## Owned session lifecycle integration (base 145c73c)

[`pt-session`](../crates/pt-session/README.md) now owns a concurrent bounded
reader/ledger and a single fresh native launch together. Framing/ledger faults
or unexplained EOF stop still-live owned execution via a **distinct observer-
failure flag**, then reap required group members. A terminal/EOF never returns
before the actual process/finalizer/cleanup result. Raw arguments/environment /
stdout/stderr are unchanged; this layer does not choose/bootstrap Python, collect
again, install/suppress plugins or replay started effects.

Protocol errors expose typed invalid-data/limit/truncation/deadline/I/O/closed
categories. Complete contradictory data is independent failure; incompleteness
on a known actual stop/death remains secondary. Counters/snapshots stay observed;
a lost observer return is **unknown/None**, not reconstructed completion. The
read-only observation exposes no full-success/final-result API.
`NormalExitAccounted` means necessary channel/accounting + actual normal process
return, **not** all work passed or current/full execution. No schema is weakened.

The process supervisor adds a checked-control entrypoint and metadata-only
validation access. Existing `pt exec`, ordinary supervision and CLI semantics
are unchanged. Observer stops are not fake user interruptions; raw later statuses
remain retained. One bounded tick lets descriptor closure during process exit
become waitable status before stopping a still-live leader for channel failure.

Initial checks passed **13 lifecycle methods** over native synthetic failures,
missing terminal after complete-looking XML/effects, live descendant cleanup,
EOF before finalizer/process exit, late mismatch/timeout, handled-SIGTERM zero,
actual SIGKILL/exit-17, budgets, exact empty/Unicode/non-UTF-8 arguments, inherited
environment, reader panic and prelaunch rejection/cancellation. Raw producer
broken-pipe diagnostics remain evidence, not erased failed attempts. Four more
real-pytest methods / **eight fresh requests** passed, composing live process /
EOF/ledger with JUnit publication for fresh shared-state fixtures, intentional
failure, collect-only, fail-fast and no-tests; actual interrupt/death stayed
partial. An unsupported outer finalizer still finished its cleanup and returned
actual zero, while reporting completeness remained rejected. Final locked release
and retained/dependency evidence follows its actual return.

The final **locked offline release workspace passed 147 tests**, no skips;
clippy `-D warnings` and rustfmt passed. The prior 128 remain, plus one explicit
process observer-stop control, one typed framing-category method and **17 session
methods** (13 lifecycle / four real-pytest composition). Evidence:
`/tmp/opencode/pt-session-final-verification-xikqfoxt`, with frozen unchanged
sources and full actual command returns/stdout/stderr.

The retained session plan has **37 cases**: **33 actual process reports** with
**30 launched leader PIDs / three not-launched reports**, plus **four explicit
prelaunch rejections**. The 33 include **eight real pytest requests** and synthetic
channel/process controls; these denominators are not silently interchangeable.
Five real requests completed the independently hashed required JUnit projection
publication, while fail-fast/no-tests/intentional failure semantics stayed
separate. The prior JUnit adapter's **23** actual requests also passed again in
the full regression. Reader-panic unknown counters and unstarted cases remain
visible; none is reconstructed as successful work from artifacts.

All **47 previous Cargo package identities/checksums** remain unchanged; only
local **pt-session 0.0.0** is added. There are **no new registry versions** in
this batch. Existing Python/bridge, support/toolchain/candidate and schema files
are unchanged. The first focused lifecycle build reported three unused test-
import warnings (all 13 methods passed); those imports were removed before final
strict checks. No runtime plugin policy changed to make a control pass.
Before commit, static read-back checked **81 local links**, seven unchanged pin /
candidate/schema files, unchanged bridge sources, Python test-source syntax and
all still-matching frozen native source hashes.

Supported launch, coordinator request/final-result catalog, complete environment /
immutable-generation assurance, generic coverage/exception completeness and
independent release prerequisites stay open. Successful `pt run` is not enabled.
The subsequent [WP06 tree-identity prerequisite](wp06-status.md) adds bounded
endpoint byte/mode/link-text observations, not those environment/generation gates.
