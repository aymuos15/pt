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

## Owned request/failure-result integration (base 7e0e735)

[`pt-coordinator`](../crates/pt-coordinator/README.md) now captures an exact
bounded invocation, requested scope, distinct coordinator producer and owned
report declarations before a single native session. Only that live owned
session's readiness claims can be committed through that request's private
store. No unrelated caller-supplied process/snapshot/hash or saved artifact can
be substituted. The process, immutable request, store states and failure result
stay together, including unavailable final records. Pure report-declaration
validation opens no path and runs no interpreter.

Qualified work remains **unsupported before launch**, not silently downgraded to
a diagnostic. A separately explicit development observer can exercise the
integration without certifying support. It does not change argv/environment,
select/bootstrap Python, suppress plugins, add collection or replay effects.
It produces only nonzero revision-1 failure records: there is no positive
environment/current immutable-generation authority or `backend_completed` /
current-full-success constructor. A requested full-scope label alone also
cannot establish effective full work. An explicitly supplied matching-root
endpoint tree remains uncertain/live-tree, not an immutable snapshot.

Request/rejection, report declaration/publication/failure, actual worker return,
cleanup and optional live-tree records use existing protocol **0 / revision 1**
shapes. They are a bounded **coordinator-origin diagnostic subset**, not a
complete environment-resolved merged stream. No fake interpreter/installed hash
or environment-resolution event fills an unknown gate. No schema is weakened.

A real contract representation limit is explicit: revision 1 requires numeric
accounting fields and cannot encode a lost reader's unknown counters. In that
case the final record is **unavailable**, not a fabricated empty execution. Its
owned native observation remains accessible. Record/summary limits and wrong-
request generation association likewise preserve the observation rather than
reconstructing completion. JUnit context errors remain separately available;
diagnostic partial content never satisfies required completeness. Optional
publication errors, pending/missing readiness and uncertain publication remain
distinct native states.

Development failures are preserved. The first compile used a nonexistent
`Accounting::default`; an explicit known-not-started constructor corrected that
prelaunch path, not unknown postlaunch accounting. The first executing control
run was **10 passed / two failed**: synthetic output files inherited a
group-writable umask and the native artifact guard correctly rejected them.
A retained negative reproduction at
`/tmp/opencode/pt-coordinator-report-failure-control-de0out9c` contains actual
Cargo exit **101** and `artifact_file_type_owner_link_or_bound` publication
failure. The fixture now explicitly creates **its own new declared files** as
0600 before its synthetic producer truncates/writes them. No production guard,
user output, dependency or existing file permission was relaxed/repaired.

The final **locked offline release workspace passed 180 tests**, no skips;
strict clippy and rustfmt passed. The new **14 coordinator methods plus four
real-pytest methods / ten requests** cover both entrypoints, fresh shared state /
fixture/import effects, intentional failure, fail-fast, collect-only/no-tests,
interruption/SIGKILL, unsupported outer finalization and an actual JUnit file
without readiness. Raw codes/effects remain; that last report stays pending,
not adopted through an independent oracle hash. Existing session/JUnit controls
and the explicitly configured two-private-prefix reproduction passed again.

Evidence at `/tmp/opencode/pt-coordinator-final-verification-rca437le` retains
**44 coordinator cases**: **34 actual process reports** (**32 launched PIDs /
two not-launched**), **eight constructor rejections**, one qualified prelaunch
rejection and one pure validation-only control. One wrong-root finalization
is retained as **record unavailable**, with its actual zero process status, not
invented counts. The **34 schema/projection probes** cover 33 available live /
not-launched records plus the qualified rejection; they are not 34 qualified
test runs. The independent offline checker imports no PT code, resolves only
the local schemas and checks raw exit/signal/stop/cleanup projection separately.
It does not authenticate producers, complete merged trace causality or real-work
truth. Every checked coordinator CLI code is nonzero, environment verification
false and current-full-success false.

All **49 prior Cargo package identities/checksums** remain; only local
**pt-coordinator 0.0.0** is added, with no registry change. Frozen native/test /
schema sources stayed fixed. Existing bridge, Python dependency, support,
toolchain, protocol/result schema and candidate files are unchanged. No unchanged
large Python harness campaign is relabelled as new coordinator qualification.
Complete launch/environment/generation, positive finalization, rich artifacts,
abandonment/durable reporting and independent release gates remain open.
Static precommit read-back checked **81 local links**, seven unchanged pin /
candidate/schema files, unchanged bridge modules, Python test syntax and all
still-matching frozen native/test/schema sources.

## Explicit real-JUnit producer readiness (base 809b2f0)

The bridge now has opt-in **bootstrap schema 2** for one explicitly declared
required JUnit artifact, alongside unchanged closed schema 1. This is **not** a
wire-version change: protocol **0 / contract revision 1** still uses its existing
`artifact_ready` shape; the independent reference trace's v2 is unrelated.
Configuration is bounded in actual UTF-8 bytes, including Unicode/whitespace.

Only the actual enabled pinned pytest JUnit formatter's matching destination is
eligible. No plugin is enabled/disabled, no requested path/options/properties /
capture data is rewritten, and no report is auto-discovered. Native no-follow
root/parent/leaf operations, exact modes/ownership/link count/length/bindings,
bounded hashing and the observer's one absolute deadline produce a **readiness
assertion only** after underlying finalizers. The coordinator independently
copies/hashes/checks live-context JUnit completeness and actual process cleanup;
matching ready/hash claims cannot certify XML/semantic/generation/environment
truth. Optional/arbitrary/coverage output observation is not inferred supported.

The new controls preserve partial interrupted JUnit, unsupported properties,
root/leaf substitution, missing/unsafe output and explicit finalizer removal.
A removal is a read failure with pending required output and preserved actual
pytest return/effects, not an automatic file repair, report adoption or replay.
Qualified launch and current-full success remain unavailable. The installed
wheel smoke now selects both schema 1 and opt-in schema 2 for both entrypoints
in new disposable environments; ordinary pytest before/after still must not
autoload PT. Its optional explicit base/output settings retain new test-owned
setup rather than mutating an existing environment.

Development failures remain explicit: the first eight-method file-control run
had **seven passing methods and one error** (four negative subcases). Those
subcases correctly raised the existing `ObserverError` RuntimeError, but the
test only expected ValueError. The expected exception class was corrected;
no product rejection was relaxed. The corrected eight-method focused run and
seven native coordinator methods / **17 real pytest requests** passed before
the additional FD-closure/formatter-binding controls and full verification.
Final locked native, Python/oracle/contracts and rebuilt-wheel checks are
recorded only after their actual returns.

The initial unprotected bundle's **locked offline release workspace passed 183 tests**, no
skips; strict clippy, rustfmt and the release CLI build passed. Python regression
passed **66 integration checks / 76 plain-reference-bridge requests**, **63
independent oracle checks** and **68 contract checks**, all without skips.
Evidence: `/tmp/opencode/pt-declared-junit-final-verification-9z9f9j35`, with fixed
source hashes, the predeclared command plan and distinct actual command return /
stdout/stderr records. These are development correctness/setup checks, not a
timing/resource campaign or current-generation qualification.

The coordinator subset retains **41 process reports**, including **17 real
pytest requests**. **Seven** explicitly select bootstrap schema 2: four commit
the independently checked JUnit projection (ordinary module, console failure,
collect-only and no-tests), one interrupted report commits **partial** content,
one properties extension is **failed**, and one intentionally removed report
stays **pending** with its read error. **Six independent stdlib XML/hash probes**
agree with observed readiness bytes. Every coordinator record remains nonzero /
environment-unverified / not-current-full-success. Producer assertions do not
upgrade that gate just because required artifact projection completeness passed.

The offline wheel rebuild and retained disposable installed-wheel smoke passed
schema 1 and schema 2 on **both** entrypoints. Plain pytest still did not load PT;
pytest11 entries stayed unchanged, and unknown startup hooks stayed present and
rejected rather than imported/suppressed/repaired. The new wheel is
`/tmp/opencode/pt-declared-junit-final-verification-9z9f9j35/wheel/pt_bridge-0.0.0-py3-none-any.whl`,
SHA-256 `f0612542649a80f365129f6c5704274ac39c111579ae7ac631b24c153d5768f1`.
It is an unauthenticated development build, **not a release**; the earlier wheel
and failed development records are not overwritten. The smoke explicitly uses
the retained private interpreter for its new environments. Existing user/managed
environments are not upgraded or repaired.

All **50 Cargo package identities/checksums** remain identical, with no registry,
lock, Python dependency, protocol/result schema, support/toolchain or external
candidate-allocation change. The source changes are the bridge readiness
component/hooks, independent controls and explicit packaging reproduction options.
The unchanged large independent timing harness was not rerun or relabelled as
qualification. Environment/startup closure, current immutable declared inputs,
complete positive finalization, coverage/rich exceptions and independent release
gates remain open; `pt run` remains unavailable.

### Required post-setup identity failure and corrected setup control

The nine commands in the retained readiness bundle above returned zero, but
the **subsequent required prefix-stability check failed**: native Cargo exit
**101**, independently confirmed by the read-only Python verifier. Original
`prefix-1` now has **5,069 entries: 98 extra entries and three changed encoding
bytecode files**; `prefix-2` still matches all 4,971 archive-manifest entries.
Evidence is retained in that bundle's `prefix-after-setup.*` files. Thus its
passing component checks are **not a complete environment/stable-input pass**.
No cache was deleted, changed file repaired, extra ignored or expected manifest
rebuilt from the mutated installation. Earlier matching endpoint observations
remain historical, not current proof.

An explicitly new negative-control prefix at
`/tmp/opencode/pt-isolated-probe-prefix-control-ncmm4r2y` reproduced the mechanism:
`python -I` with `PYTHONDONTWRITEBYTECODE=1` reported
`dont_write_bytecode: false`, returned zero and generated 21 extra entries /
three changed bytecode files during a small stdlib probe. Isolated mode ignores
that environment setting. Existing packaging metadata commands include such
isolated probes; setup-tool interpreter discovery can do so too. This control
does not claim a unique writer/stage for all 98 observed extras. Its changed
prefix and original changed `prefix-1` remain intact as failed evidence.

The explicit test-only `readonly_interpreter_setup.py` wrapper now creates a new
user/private mount namespace and read-only bind views of **only named temporary
interpreter inputs**, then executes the requested validation/setup command.
Distinct original namespace descriptors and private propagation are checked;
there is no parent mount/permission/input repair and no automatic retry. The
new `verify_declared_junit.py` driver refuses writable interpreter inputs,
creates a fresh native subject environment, freezes the command/source plan and
checks both prefixes again after all setup. It does not reuse the changed
prefix as expected truth.

A focused read-only control at
`/tmp/opencode/pt-readonly-probe-setup-control-bxvtw4p7` ran the same isolated
probe with bytecode writing still enabled: the child observed a read-only base,
both the untouched original `prefix-2` and a new archive-derived prefix remained
exact matches, and the parent's read-only flags stayed false. A separate native
process-only namespace capability observation is at
`/tmp/opencode/pt-snapshot-capability-diagnostic-9nfm6cuf`; it is not a snapshot.

This is an explicitly different **test-setup policy**, including a mapped UID
view inside the temporary namespace, not a shipping launcher or equivalent
performance arm. Writable host aliases, namespace capabilities, external inputs,
complete environment and current immutable-generation assurance remain outside
the claim. Corrected full reproduction follows its new actual return, never
overwrites the failed bundle or upgrades these controls into qualification.

### Artifact boundary exposed by the protected-input run

The first corrected full setup at
`/tmp/opencode/pt-declared-junit-readonly-verification-lv_haw8u` returned **1**:
new-environment setup commands 1–2 returned zero, but native command 3 returned
Cargo **101**, with **35 passing / one failing pt-report method**. Nine later
planned commands (clippy, formatting, Python suites, build/wheel/install and the
native post-setup check) were **not run**. Both interpreter inputs still matched
their expected 4,971 entries in the independent after-failure inventory; no
changed input or later passing component return erases this native failure.

The failing four-arm test's old assertion recorded no arm/error. Additional
diagnostics passed a focused run and a full 36-method report-library run at
`/tmp/opencode/pt-artifact-boundary-diagnostic-dlbdtizi` and
`/tmp/opencode/pt-artifact-parallel-diagnostic-noifx9r0`. Thus the exact original
arm cannot be retrospectively proven from those reruns. The assertions are not
relaxed; future failures retain mode, error, state and target-presence diagnostics.
Inspection found an actual independent gap: pending bytes were hashed **before**
XML validation, followed only by stat/binding checks before rename. Same-stat
changes could reach publication and fail only during the later published read.

Two deterministic controls at
`/tmp/opencode/pt-artifact-boundary-red-controls-0ogi9eay` returned Cargo **101**:
**22 passed / two failed**. One explicitly masks the pending metadata guard and
shows it accepts different same-length bytes; this is synthetic isolation, not
a claim that this host's ctime was restored. The other shows that a different
same-length buffer can reach successful XML validation before metadata detects
the substitution. This identifies byte-domain/ordering gaps without claiming a
unique explanation for the earlier undiagnosed arm.

The native publisher now rehashes the owned pending FD **after validation and all
pre-rename hooks**, under the original deadline and byte ceiling, before rename.
It checks both open/named bindings around that read and revalidates ancestors /
deadline before publication. The actual XML buffer is independently hashed to
the readiness digest **before parsing**, too. Copy/XML/published readbacks now
check the original deadline after each read. These are endpoint observations,
not a content freeze or waiver of the mandatory independent post-rename check.

The focused corrected run at
`/tmp/opencode/pt-artifact-boundary-fixed-controls-d0fkxhyq` passed **39 report
methods**, strict workspace clippy and rustfmt. The three added methods cover
metadata-neutralized byte verification, validation-buffer binding and pending
read fault/expiry/substitution/growth. Prepublication failures stay terminal with
`publication_may_exist: false`; return loss after rename retains **true**, without
recovery, repair, retry or deletion of foreign data. Full acceptance still follows
the new protected-input run's actual returns and post-setup checks.

### Corrected protected-input final verification

The new exclusive run at
`/tmp/opencode/pt-declared-junit-protected-final-rzazf7qr/run` returned zero for
**all 12 planned commands, with zero not-run commands**. The locked offline
release workspace passed **186 tests**, no skips, including all **39 pt-report
methods**. Strict clippy, rustfmt, the CLI release build, **66 integration checks /
76 observer requests**, **63 oracle checks**, **68 contract checks**, the offline
wheel build and disposable installed-wheel smoke all passed. An additional
explicit native two-prefix test passed **after** the setup/test/wheel stages.

Native before/after and independent after-setup/after-outer inventories agree on
both protected interpreter inputs: **4,971 entries each**, no extra, missing or
changed entries, with the same archive-derived canonical digest
`aef7ea220c93ad437c655d74c617c0b7a7a1cfc0a51c47e6a960d7185a39f499`.
Each successful native verification hashes **191,199,150 bytes**, twice the
95,599,575 unique regular-file bytes. The independent read-back rechecked the
original archive/manifest hashes, re-derived the expected archive entries and
canonical digest, and checked both native proof files. Parent read-only flags
remained false; the private setup view did not change parent mount policy.
Original changed `prefix-1` and the negative isolated-probe prefix remain intact.

The corrected coordinator denominator is **51 retained cases / 41 process
reports**, including **39 launched PIDs / two not-launched reports**, **17 real
pytest requests**, **41 independent schema/raw-process projection probes** and
**six independent XML/hash probes**. The seven opt-in readiness outcomes remain
four complete projection commits, one partial interrupt commit, one properties
failure and one missing-output pending state. All coordinator results stay
nonzero, environment-unverified and not-current-full-success.

The wheel reproduces SHA-256
`f0612542649a80f365129f6c5704274ac39c111579ae7ac631b24c153d5768f1`.
Both schemas/entrypoints pass the installed smoke, without ordinary pytest
autoload changes. Independent precommit read-back checked **186 frozen source /
pin/schema files**, **50 identical Cargo package identities/checksums**, **eight
unchanged lock/pin/candidate/schema files**, Python 3.12 grammar and **43 local
links**. The corrected driver now records every not-run stage explicitly and
freezes independent oracle/corpus/harness sources and pins too; frozen copies
are audit evidence, not an immutable execution snapshot.

This accepts the **development readiness/setup/artifact fix only**. It does not
overwrite earlier failures or qualify complete environment/startup closure,
immutable/current declared-input generations, a positive final result, coverage /
rich exception completeness, native memory peaks, independent release review or
authenticated release provenance. No accelerator, release or successful `pt run`
is enabled.

## Config cleanup finalization follow-up (base 683c23d)

The pinned pytest Config runs `add_cleanup` callbacks **after** the unconfigure
hook. Three retained real-pytest controls at
`/tmp/opencode/pt-config-cleanup-red-controls-nz04d6w6` exposed premature producer
readiness/terminal emission: a callback appended report bytes after hashing,
another removed the report, and another raised an unobserved cleanup exception.
Cargo returned **101: zero passed / three failed**. The native artifact/process
checks still prevented qualification; this was a producer-ordering gap, not
permission to adopt a missing or changed report or a claim of false full success.

The new private CPython **3.12.12 / pytest 8.4.2** Config cleanup adapter places
only its newly registered non-suppressing observer exit callback below the
existing ExitStack entries. No pytest/user callback is removed, inspected,
executed early or reordered relative to another original callback. The same
queue retains ordinary LIFO behavior and callbacks registered during cleanup.
Readiness/terminal emission now waits for that queue to drain. Unsuppressed
exceptions retain their original propagation and become incomplete reporting /
partial readiness with a generic infrastructure diagnostic; no arbitrary
exception `str`/`repr` is requested for metadata.

Unknown/replaced/transferred internals cannot inherit completion. A missing
callback yields no terminal, not a recovered zero or file-based success. The
adapter remains an explicit **private-internals restriction**, not support for
arbitrary Config/ExitStack replacements, callback introspection, interpreter
`atexit`, native-library shutdown, detached workers or external cleanup. The
native actual return/EOF/required cleanup and independent artifact checks remain
mandatory, as do all environment/generation/release gates. Protocol **0 /
revision 1** and bootstrap schemas **1/2** are unchanged.

Eight focused ordering/exception/lost-boundary controls passed. The first native
follow-up at `/tmp/opencode/pt-config-cleanup-native-controls-6vjlbyfp` passed
**ten methods**, before adding direct references and missing-stack controls.
Three separate fresh direct-pytest references now check callback and nested
registration order, import/fixture/body effects and actual returns. They are
predeclared correctness controls, **not** automatic fallback/replay or an
equal-configuration product-timing claim.

The first expanded full attempt at
`/tmp/opencode/pt-config-cleanup-protected-final-todqh6ul` returned **1**, native
Cargo **101**: ten coordinator-pytest methods passed and one fault-control
assertion failed. It incorrectly demanded a raw zero after removing the terminal
boundary. The retained native report instead shows actual clean EOF with
`MissingTerminal`, an observer-originated infrastructure stop of the still-live
leader, raw **SIGKILL 9**, and complete cleanup. The required JUnit stayed pending
and the result stayed failed. The fixture now permits only the exact native
ordering alternatives—observed zero return or the missing-terminal stop with
raw zero/SIGKILL—while retaining strict missing-terminal, incomplete accounting,
pending output, no-adoption and no-retry assertions. No product failure guard or
publication assertion was relaxed. Nine later commands were **not run**; both
protected interpreter prefixes still matched after this failed attempt.

The new exclusive final run at
`/tmp/opencode/pt-config-cleanup-verified-final-lly6myda/run` passed **all 12
planned commands, zero not-run**: **190 locked offline release Rust tests**,
strict clippy/rustfmt, **74 integration checks / 76 observer requests**, **63
oracle checks**, **68 contract checks**, release CLI/wheel builds and the
installed-wheel smoke. All suites had no skips. Both exact 4,971-entry interpreter
inputs still matched in native and independent post-setup/after-outer checks;
parent mount flags remained unchanged. Earlier failures remain retained.

The final denominator is **56 coordinator cases / 46 actual process reports**
(**44 launched PIDs / two not-launched**), **22 coordinator pytest requests**,
**46 independent schema/raw-process projection probes**, **eight XML/hash probes**
and **three separate direct-pytest reference requests**. Direct/candidate cleanup
and body/fixture/import effects and raw codes match for append, remove and raise.
The appended report commits the complete named projection; removal stays pending;
the cleanup exception retains raw **1** with partial content. Missing/transferred
boundaries stay pending/incomplete: the retained final run observed raw **zero**
for replacement and native **SIGKILL 9** for transfer, not invented equal exits.
All coordinator result codes remain nonzero and every environment/current-full-
success field remains false.

The new unauthenticated development wheel SHA-256 is
`4e973ca41e0a9f1614ebd0615f3d302fd4513a19e5a02acd1f68e4450ec286c1`.
Its module bytes match the frozen source and both schema/entrypoint installed
checks pass without ordinary-pytest autoload changes. Independent precommit
read-back checked **188 frozen source/pin/schema files**, **50 unchanged Cargo
package identities/checksums**, **eight unchanged lock/pin/candidate/schema files**,
Python 3.12 grammar and **44 local links**. No protocol/dependency/support pin or
external candidate allocation changed. This closes the bounded Config cleanup
batch, not the complete runner, environment/startup/current-generation, coverage,
native resource or independent/authenticated release gates.

The subsequent [relative-link identity prerequisite](wp06-status.md) adds an
opt-in closed **declared** target graph plus the unchanged endpoint byte walks.
Its **196-test** protected-input regression and independent 1,048-link checks
remain separate from complete host/runtime environment and immutable-generation
assurance; no positive coordinator authority is added.

The following [non-executing ELF input projection](wp06-status.md) passed its
**209-test / 12-stage** protected-input development run and four independent
readelf/struct comparisons. It preserves the earlier strict-clippy failure and
not-run stage, keeps image hashing separate from tree-walk costs, and supplies
no loader-resolution, complete environment, generation or positive-result token.
