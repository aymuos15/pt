# WP02 corpus and reproducible environment progress

Date: **2026-11-10**. Base: `4db6b6e`. Status: **partial development evidence;
WP02 acceptance, M0 and release qualification remain open**.

## Concrete serial-core baseline

The new [serial-core mechanism corpus](../bench/corpus/serial_core/README.md)
contains ten test-owned cases and its own exact CPython 3.12.12 / pytest 8.4.2
environment lock. Its explicit allocation is **training only, before optimization**;
it is not a substitute for representative or untouched confirmatory/holdout sets.
The original [nine draft probes](../bench/corpus/manifest.toml) and
[twelve-repository shortlist](../bench/corpus/candidates.toml) are unchanged.

The cases retain within-session state, parametrization, import/fixture effects,
setup/teardown failure, strict XPASS, skip/xfail, duplicate custom items, collection
failure, no-tests exit five, doctest/unittest integration and an application-work
negative control. A fresh case file copy and fresh `python -m pytest` process are
used for each invocation, without a collection-only preflight. Expected nonzero
outcomes remain intentional failures, not successful timing samples.

The materializer validates the complete fixture inventory, freezes the original
manifest/project/lock/source bytes, creates **two new isolated locked venvs** using
offline uv cache artifacts and copies rather than shared installed-file hard links.
It checks exact runtime/package/plugin declarations, compares all `site-packages`
files including unlisted ones before/after execution, and compares the two
installations except explicitly retained environment-specific RECORD entries.
No dependency/interpreter download, implicit lock update, automatic test replay,
system environment mutation or cache clearing occurs. See the corpus README for
the exact explicit environment policy, limits and operational caveats.

## Development observations so far

### External candidate follow-up

All nine remaining exact shortlisted source revisions now have a read-only
[configuration/profile assessment](../bench/corpus/assessments/source-profile-20261110.md),
including 22 original-file hashes. Direct FastAPI/NumPy pytest-9 requirements,
HTTPX's exact 8.4.1 tooling pin, Django's native entrypoint and pytest's self-hosting
identity are preserved rather than silently changed. Requests/SQLAlchemy/Trio
still need their actually declared plugin/service/build/scope qualification.

The subsequent [Flask assessment](../bench/corpus/assessments/flask-49943b5.md)
keeps original declarations intact and uses an explicit separate hashed 8.4.2
runtime/build lock, **not** Flask's pytest-9.1.1 upstream lock. Two separate local
builds produced identical wheel bytes. Both clean runtime environments ran
**494 passing JUnit occurrences**, with **716 comparable installed files** and
unchanged before/after site-packages inventories. A new, fully offline complete
assessment reproduced both builds and both 494-pass sessions. No candidate was
allocated or promoted to qualified. All eight qualification fields stayed null.
The explicit reproducible tool has **11 passing synthetic adverse controls**;
these are not native or semantic qualification. This extends real-repository
feasibility without substituting XML for the required phase/effect oracle.

The complete locked harness regression for this Flask/source-profile batch
passed: **735 tests ran, 734 passed and the one existing native-peak capability
test was skipped** (`Ran 735 tests in 858.730s`, `OK (skipped=1)`). No dependency,
support-matrix or product-runtime pin was changed. The native-peak skip remains
an unresolved qualification, not a fabricated memory metric.
The **68 separate contract/audit tests passed** (`8.033s`). Static read-back
checked all nine source profiles / 22 original file hashes, 24 local links,
Python grammar/JSON and five unchanged dependency/support pin files. All twelve
original eligibility/allocation declarations remain unassessed/unassigned.

### Serial-core baseline

- The initial ten direct fresh pytest invocations matched their declared JUnit
  occurrence order, adverse markers, sentinel sequences and exits **0, 1, 2, 5**.
  Evidence: `/tmp/opencode/pt-serial-core-initial-_pl9p69n`.
- An initial pre-install profile read rejected an incompatible retained-byte
  limit before work; the limit was corrected to the existing safe reader cap.
  The first native setup attempt then exposed a missing lazy raw-capture import
  after restoring `sys.path`. The observer cleaned its owned setup process and
  the API did not return a confirmed materialization. The import was made explicit;
  no complete-looking files were used to recover that failed return.
- A **new development invocation in a new directory** then completed both clean
  environments and all **20 planned cases**. **495 comparable installed files**
  matched, full per-environment `site-packages` inventories were unchanged, and
  all six qualification fields remained null. This was an explicit check of the
  corrected implementation, not a runtime retry/fallback of started corpus work.
  Evidence: `/tmp/opencode/pt-serial-core-materialize-dptvq6o5`.

This is reproducibility evidence for the narrow declared mechanism profile, not
the actual phase-level semantic oracle or PT support. JUnit and sentinels cannot
close WP03. Artifact provenance, complete interpreter/stdlib/environment identity,
atomic snapshots, hostile paths, external services and native resource budgets
remain unqualified. Reusing the same locked artifacts is not an independent build.

The expanded **16 targeted materialization tests passed** (`Ran 16 tests in
11.241s`, `OK`): one real two-environment offline installation/execution check and
fifteen source, inventory, declaration, XML, uncertainty and publication controls.
They preserve duplicate occurrences, reject an unrelated collection-error body,
refuse unsafe/unlisted/changed sources and environment mutations, retain twenty
planned rows after early failure, and never recover a lost return from JUnit.
Synthetic controls explicitly label their observations and do not supply native
installation or PT qualification. **68 contract/audit tests passed** (`Ran 68
tests in 8.428s`, `OK`).

The complete locked harness regression also passed: **724 tests ran, 723 passed
and one existing native-peak capability test was skipped** (`Ran 724 tests in
860.575s`, `OK (skipped=1)`). The skip does not qualify native charged-memory
peak accounting. Rust and bridge packaging were not rerun for this corpus-only
batch; product sources, the harness dependency lock and support pins are unchanged.
Static reproduction checked the current ten-case/fifteen-file frozen-input
inventory, Python 3.12 syntax and **103 local links** in this batch. The harness
lock, support matrix, Rust toolchain and Cargo lock match the prior commit exactly.

## Remaining acceptance work

- Preserve every external candidate's installability/profile conflict, exclusions,
  skips and deselections. The attrs pytest-version conflict and Click's 31,000
  default-deselected stress tests remain disclosed; no candidate is silently
  swapped for an easy passing workload or promoted to qualified.
- Establish reviewed representative eligibility, pinned artifacts/builds and
  interpreter provenance, complete clean materialization and per-scenario reset/
  bytecode/cache/service contracts for the actually claimed scope.
- Freeze training/confirmatory/holdout partitions before optimization tuning;
  this test-owned training set is not untouched confirmation evidence.
- Extend [WP03's bounded actual-reference oracle](wp03-status.md) and independent
  broken-runner controls to reviewed qualified corpus/environment profiles; finite
  training traces and effects alone do not qualify broader corpus outcomes.
- Complete WP01 acceptance, WP04/backend/protocol integration, real pytest parity,
  ecosystem and release gates under the original dependency roadmap. No runner
  speedup, `pt run` availability, full-corpus score or independent review is claimed.

The [prerequisite register](wp01-status.md) remains authoritative about open gates.
