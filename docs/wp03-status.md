# WP03 reference oracle progress and remaining qualification

Date: **2026-11-10**. Base: `3f71695`. Status: **bounded development oracle;
WP03 acceptance, M0/M1 and PT backend qualification remain open**.

## Implemented

[`tests/conformance`](../tests/conformance/README.md) now contains an explicitly
loaded real-pytest observer, closed canonical JSONL schema, independent bounded
reader/comparator, repeated-reference stability check, required-file/absence
oracle, coverage-data set comparator and independent deliberately incorrect
pytest plugin. The product bridge is still separate and unchanged.

The observer preserves exact duplicate occurrence identities, final selection /
deselection, collector reports, separate setup/call/teardown, xfail/strict XPASS,
warnings, captured sections and terminal accounting in one fresh pytest session.
Request options, fail-fast's not-run suffix and interrupted phase prefixes remain
visible. Only the exact observer transport option and explicitly recorded test
control args are excluded from request comparison. Raw diagnostics are retained;
the finite failure contract compares stable crash/skip/string messages, not full
traceback equivalence or arbitrary custom report objects.

Independent controls exercise skipped bodies/setup/teardown, duplicate dropping,
strict-XPASS relaxation, hidden collection errors, warning suppression, extra
preflight imports, stale same-size/same-mtime timestamp bytecode, corrupted traces,
request/exit contradictions, unknown producer shapes, missing artifacts and
unreleased leases. Phase equality alone is deliberately insufficient: externally
declared effect sentinels detect equal-count skipped bodies and stale loaded code.
A nondeterministic application sentinel produces `baseline_uncertain`, not a
candidate correctness or performance win.

The coverage fixture executes actual parent and subprocess work and merges real
coverage databases. Omitted subprocess measurement/merge, branch mode or child
contexts are rejected even when pytest phases and application effects match.
Source hashes, explicit root mappings, effective tracer observations, file/line/
arc/context sets and missing-required policies are checked independently of a
rounded percentage. This does not qualify a production coverage integration.

The explicit retained-evidence command freezes the corpus/conformance/outer
observer sources, executes that copy, retains raw projects/traces/process output/
coverage/forgeries and records every planned test and subtest outcome. Failed,
skipped, not-run, incomplete and lost-return states remain visible. No dependency
installation, plugin suppression, existing result overwrite or automatic retry
occurs. Source end checks are not immutable-generation proof; all seven artifact/
environment/backend/generation/coverage/release qualifications remain null.

## Development verification so far

- Initial corrected observer smoke: **20 fresh pytest requests, ten matching
  instrumented reference comparisons**, including all adverse exits **0, 1, 2,
  5** and exact duplicate occurrences. Historical prototype evidence:
  `/tmp/opencode/pt-reference-oracle-check-qvqd3qpl`. The subsequently hardened
  unreleased trace shape is intentionally stricter; old prototype traces are not
  retroactively promoted into current-format evidence.
- The first reference reader smoke rejected normal collection failure because
  pytest's ordinary `Interrupted` had been incorrectly called an observer error.
  Evidence: `/tmp/opencode/pt-reference-oracle-initial-bh9ir008`. The observer now
  records backend interruption separately; no failed return was recovered.
- The initial **18 actual-reference/adverse tests passed** (`11.943s`). After
  request/partial-work and coverage/artifact checks, **37 tests passed** (`19.168s`).
  Those historical runs precede the final bounded source-retention checks; final
  verification is recorded below rather than extrapolated from those results.
- A first expanded **48-test** run had **47 passes and one test-fixture error**
  (`29.190s`): the corrupt-database restoration statements had been accidentally
  placed in the next test, where `output`/`raw` were undefined. Those statements
  were moved back into their original control; both the corrupt-data and
  equally-incomplete-coverage expectations remain enforced. This was not a
  candidate exclusion or a weakened expectation.

## Final verification of this development batch

The new, source-frozen retained-evidence invocation passed **all 48 tests**
(`Ran 48 tests in 29.783s`, `OK`), with **no skips**. Evidence:
`/tmp/opencode/pt-oracle-evidence-suarh6_o/run`. The independent read-back found:

- **80 frozen source/control/lock files**, all matching their recorded hashes.
- **99 retained real-pytest process observations**, **89 instrumented reference
  traces** and **19 distinct deliberately forged trace files**. These are test
  operations, not independent benchmark samples.
- **21 matching and nine mismatching retained trace comparisons**. Expected
  mismatches are the independent negative controls, not removed failing cases.
  Baseline instability remains a separate uncertainty report.
- All **seven qualification fields stayed null**, confirmatory eligibility false;
  no phase or coverage comparison became product/generation qualification.

The separate **68 contract/audit tests passed** (`8.762s`). The corpus batch's
last full harness result remains **724 tests, 723 passed / one native-peak skip**
(`860.575s`); no existing harness or product runtime module changed in this oracle
batch. Static checks validated the canonical schema, Python 3.12 grammar, **90
local links** and unchanged harness/support/Rust/Cargo/bridge dependency pins.
Rust and bridge packaging were not rerun for this test-only batch.

## Explicit repository reference profile

The follow-up adds **trace version 2**, with an explicit bounded reference profile.
The default `serial-core-v1` remains capped at **256 occurrences**; the separately
requested `serial-repository-v1` permits **1024**, retaining the existing byte /
event/depth ceilings. A 257-item real fixture fails visibly under the default
rather than silently truncating, and executes all 257 / 771 phases under the
explicit repository profile. Versions are never mixed. The committed v1 schema
is unchanged; comparison against the actual prior retained evidence preserved
**88 accepted / one rejected** historical trace dispositions and every normalized
field. This is engineering evidence for these finite ceilings, not broader
semantic/profile/release qualification.

The [Flask reference tool](../bench/corpus/assessments/check_flask_phases_49943b5.py)
uses the two already prepared isolated environments and performs no installation.
Its four predeclared fresh pytest invocations each retain **494 selected and
completed occurrences / 1482 ordered setup-call-teardown reports**, exit zero.
Both within-environment repeated-reference comparisons matched exactly, including
captured sections and warning messages. Every owned work copy is archived by
rename and the same literal cwd recreated, avoiding path erasure or deletion of
earlier evidence. No body-effect or PT-backend qualification is inferred.
The initial development evidence is at
`/tmp/opencode/pt-flask-phase-reference-yk0x1bkf`; verification of the reusable
tool and expanded source-frozen controls is recorded with the final checks.

The two new actual-reference controls plus the prior checks passed **50 tests**
(`28.878s`), and the separate **five synthetic Flask plan controls passed**
(`0.061s`). They preserve four planned outcomes, same-cwd/no-delete resets,
pre-execution installed-state mismatch, lost-return uncertainty and unstable
baseline classification. Synthetic observations stay explicitly labelled and
cannot resolve the six remaining support/effect/environment/generation/backend/
release qualifications of the real-repository reference tool.

Final source-frozen verification of this follow-up passed **all 55 tests** with
no skips (`Ran 55 tests in 29.504s`, `OK`), retaining **88 frozen source/lock
files** at `/tmp/opencode/pt-oracle-v2-evidence-j3hyfqdn/run`. All seven outer
qualification fields remain null. The reusable Flask tool separately completed
its actual four-request, 494-occurrence / 1482-phase-per-request check with both
reference comparisons matching at `/tmp/opencode/pt-flask-phase-tool-uf8bxbcd/run`;
all six tool qualifications remain null.

**68 contract/audit tests passed** (`8.188s`). Static checks covered six edited
Python files, both schema versions, unchanged original v1 schema and **17 local
links**. The unchanged harness's last full result remains **735 tests, 734 passed
/ one native-peak skip** (`858.730s`). Rust, bridge packaging and shipping timing
were not rerun or claimed by this test-only oracle-profile follow-up.

## Remaining gates

### Async, property and database mechanism follow-up (base d8c5680)

The [separate locked ecosystem corpus](../bench/corpus/serial_ecosystem/README.md)
adds pytest-asyncio **1.4.1.post1**, Hypothesis **6.170.15** and local SQLite effects
under the unchanged CPython **3.12.12** / pytest **8.4.2** target. Three cases
declare seven occurrences and 20 applicable phases per complete group; the async
case retains both an awaited assertion failure and an async setup error, exit 1.
The property case actually executes six generated finite-domain bodies as **two
pytest occurrences**, with explicit deterministic/database/reset settings.
SQLite verifies one import-time database write and connection/lease cleanup.

The first native run completed all **24 planned requests**, preserving six known
nonzero async outcomes, six matching repeated-reference comparisons and three
omission mismatches. Passing awaited/generated bodies and database finalization
were deliberately omitted while **three phase reports and zero exit still
matched**. External effects detected each omission; the artifact oracle also
rejected the leftover database lease. Source/work histories and all requests
remain retained at `/tmp/opencode/pt-serial-ecosystem-1toa_w_e/run`.

Eight synthetic plan controls passed (`0.235s`), preserving all 24 units, lost
returns, declared nonzero outcomes, explicit-only wheel downloads, no plugin
suppression, baseline uncertainty and unlisted installed-file changes. They are
not native plugin qualification. The source-frozen oracle driver now also captures
the interpreter/ecosystem tools and locks so these controls run from recorded
inputs, without installing their subject plugins into the independent harness.
Final native offline and expanded oracle checks are recorded after completion.

The new **fully offline** complete invocation also matched all 24 requests at
`/tmp/opencode/pt-serial-ecosystem-offline-3sesehzm/run`, with **638 comparable
installed files** and both entire base prefixes unchanged. Independent read-back
found **18 instrumented traces, 34 completed occurrence observations and 98 phase
reports**, six matching reference pairs and three detected body/finalization
omissions. These include repeated observations and are not independent benchmark
samples. All six intentional async nonzero exits remain in the ledger; all eight
qualification fields remain null.

The expanded **source-frozen oracle suite passed all 63 tests** with no skips
(`28.876s`), retaining **102 source/lock files** at
`/tmp/opencode/pt-oracle-ecosystem-frozen-cnbdi85u/run`; all seven outer
qualification fields remain null. **68 contract/audit tests passed** (`8.358s`).
Static checks covered six Python sources, **23 local links** and **seven
unchanged Cargo/Python/support/toolchain/candidate files**. The unchanged harness
retains its last full **762-test result: 761 passed / one native-peak skip**.
Rust and bridge packaging were not rerun for this subject-corpus-only batch;
their separate startup-component verification remains recorded in WP04.

### Still required

- WP01 acceptance and WP02's representative eligibility, authenticated artifact /
  interpreter/environment identity, broader reset and untouched partitions remain
  open. The serial-core set is test-owned training, not a representative score.
- Complete the mandatory claimed ecosystem/adversarial matrix and reviewed oracle
  expectations, including supported async/property/database/retry/subtest adapters,
  external inputs and coverage-core/subprocess behavior. Unsupported objects or
  bounds are visible failures, not smaller passing inventories.
- Establish effect evidence for the actually claimed suites and compare observer
  effects beyond this finite corpus. Matching phase reports do not prove bodies,
  resources, loaded-code identity, full tracebacks or uninstrumented nondeterminism.
- Complete WP04's actual entrypoint/bridge/backend integration and version checks;
  WP05 remains gated on qualified WP03/WP04 prerequisites. Production framing,
  protocol ownership/fault handling, artifact/environment verification and strict
  current-generation assurance are not supplied by these test-only files.
- Preserve the original full-success and release contracts. No `pt run`, full
  semantic compatibility, native peak support, speedup, independent review or
  release qualification is claimed.
