# WP01 timing evidence and open prerequisites

Status: **partial independent-harness regression evidence; WP01 remains open**.
Date: **2026-11-09**. Timing-fixture evidence was committed in `3871aee` (base
`373907e`); the [publication-inclusive follow-up](wp01-lifecycle.md) builds on it.
No PT backend, semantic qualification, coverage support, speedup or
confirmatory campaign is established. `pt run` remains unavailable.

## Observed timing stages

`bench/harness/tests/test_timing_boundaries.py` now supplements the existing four
startup/shutdown/leader-exit/inherited-pipe checks. Its controlled fixture runs
one real pytest session in a fresh process, without a preflight collection.
External plugin autoload is disabled only for this isolated fixture. No product
plugin policy, production bridge or default runner behavior changed.

For each of six stages, the child records entry and waits for the parent to
release a gate. After observing entry, the parent requires the measured command
to remain pending for **0.15 seconds**. It then releases the stage and checks that
the timer's start/end enclose that parent-observed interval. The hold has a
120 ms lower-bound guard, not a measured speed comparison. All readings used for
the interval comparison come from the **same parent/harness process monotonic
clock**; no child clock, pytest duration or startup overhead is the authority.

| Stage | Real fixture operation after the gate | Completion evidence checked separately |
|---|---|---|
| Collection | Pytest's normal collection hook chain | One exact collected occurrence, followed by setup/call/teardown in the same session |
| Teardown | Yield-fixture finalization | Ordered `fixture-finalized` sentinel and passed teardown report |
| Reporting | Test-owned `pytest_sessionfinish` JSON writer | Exact occurrence and three phase/outcome records, backend exit zero |
| Coverage merge | Coverage.py combines two actual data shards and saves the merged database | Both input shards exist before release, are consumed, and a merged data file exists |
| Coverage report | Coverage.py generates JSON from the merged data | Exact path and executed-line union `[1, 2, 4, 5]`, no missing lines |
| Required cleanup | Cooperative release of a test-owned file lease | Lease absent and explicit release artifact after final reports |

The second coverage shard comes from a distinct diagnostic function, not a
replayed test or a second pytest session. Coverage.py **7.17.2** is now locked as
a development-only dependency on Python >=3.11. Python 3.10 retains the generic
harness minimum, but these coverage-backed fixture checks explicitly skip there;
only CPython 3.12.12 on the selected Linux development host was exercised. No
pytest-cov plugin, branch/context/subprocess behavior or effective-core
qualification is claimed.

Two additional held-stage subcases exercise the real optional `RawCapture.publish`
and spool-context cleanup, with verified blob bytes/digests and closed spools.
These require the existing Linux native no-replace publication support. The
delay wrappers do not replace the actual publication/cleanup operations.

## Negative controls and evidence limits

- All six stages also run with the wait deliberately omitted. Even though the
  process exits zero and the final artifacts match, a completed command before
  release must fail the same held-stage check. These controls wait for command
  completion before checking the omitted wait; they do not depend on a noisy
  upper bound for subprocess startup.
- For every positive stage, a record mutation moves the endpoint back to the
  observed stage entry and recomputes `elapsed_ns`. Interval enclosure rejects
  it despite intact final artifacts. These are explicitly synthetic record
  mutations, not tests of a real PT candidate's reporting.
- A cooperative fixture deliberately leaves its required lease unreleased.
  Zero exit, drained output, reaped leader, included wait and complete reports
  still fail the independent fixture-evidence check.
- These checks belong to the test fixture. `measure()` itself still reports
  `exited_unqualified`; it has no general semantic, artifact, generation or
  resource validator. This is not WP03's broken-runner oracle or WP15 coverage
  qualification, and it does not establish process containment.

## Command interval and publication-inclusive follow-up

`pt_bench.measure()` resolves/validates arguments and cwd **before** starting the
clock. It starts immediately before `Popen` and stops after process/pipe handling
and any optional raw-capture publication/context cleanup. In the tested fixture,
the command itself awaits final reports, coverage and cooperative resource
release, which is why those stages are included.

At `3871aee`, `pt_bench.main()` wrote the sample only after `measure()` returned,
and no larger endpoint existed. That exclusion remains true for the unchanged
inner `result.elapsed_ns`. The follow-up adds `measure_and_publish()` and a
separate post-commit receipt whose `lifecycle.elapsed_ns` includes sample
publication, temporary cleanup, read-back and declared required-finalization
validation. The regression now verifies both intervals: the command interval
excludes the held publication stage, and the lifecycle interval encloses it.
The immutable sample is not rewritten to invent its own post-commit timestamp.
See [the exact new boundary, validation and limitations](wp01-lifecycle.md).

Paired preparation/probes have their own recorded intervals; arm and schedule
record publication is also outside the corresponding measured intervals. These
costs are not implicitly free preparation or part of a complete amortized replay.
Leader reaping and pipe drainage do not prove that ordinary pipe-closing or
detached descendants exited, or that external resources were released. The
cooperative file-lease check does not implement a product resource manager.

## Historical verification and retained failures: 3871aee

Reproduce from the repository root:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_timing_boundaries.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The first lock attempt failed because unconditional coverage.py 7.17.2 requires
Python >=3.11 while the generic harness declares >=3.10. An explicit dependency
marker and visible test skip preserve that minimum rather than selecting an
unrecorded older coverage version or claiming Python 3.10 execution evidence.
The lock adds coverage only; existing dependency versions are unchanged.

The first targeted run reported **14 tests, `FAILED (failures=13)`**, including
six failing omitted-wait subcases. Pytest collected the imported function named
`tested` as an extra `test*` item. The exact inventory check caught this fixture
bug. Importing it as `workload` fixes the fixture without relaxing the expected
single occurrence. The next targeted run passed **all 14 tests**. That earlier
failure is retained here, not reclassified as a benchmark exclusion or erased.

Final verification on the selected development host, with ResourceWarning
treated as an error:

- **14 targeted timing tests passed**, including the four pre-existing checks
  and ten new test methods. Subcases are not independent benchmark samples.
- **179 full locked harness tests passed** (`Ran 179 tests in 36.953s`, `OK`).
- **68 separate contract/audit tests passed** (`Ran 68 tests in 8.532s`, `OK`).
- `git diff --check` and **51 edited-document local links** passed; all **16
  pre-existing lock package versions** are unchanged, with coverage the only
  added package. These are regression results, not conformance, overhead
  measurements, qualified materialization or a confirmatory campaign.

Rust and bridge packaging were not rerun: runtime behavior and bridge sources
are unchanged. Real PT conformance and performance campaigns remain unavailable
and were not claimed by this batch.

## Remaining prerequisite gates

| Package | Still required before acceptance |
|---|---|
| WP01 / G01 | The [standalone endpoint](wp01-lifecycle.md), [paired v2 integration](wp01-paired-lifecycle.md), [strict schemas](wp01-evidence-v2.md), [cgroup resources](wp01-resources.md) and [per-stage resource campaigns](wp01-paired-resources.md) cover bounded publication/receipt consistency. [Declaration checks](wp01-manifest-checks.md) and [original cards](wp01-result-cards.md) retain qualification gaps. [Managed replay](wp01-managed-replay.md), [paired sessions](wp01-paired-replay.md) and [replay cards](wp01-replay-result-cards.md) preserve all outcomes and 24 unresolved fields; latency resampling uses whole pairs only. Separate [whole-session resources](wp01-replay-resources.md) and [paired resource replay campaigns](wp01-paired-replay-resources.md) now include preparation, idle/background work and shutdown in fresh per-session groups, preserving unsupported/failed/not-run/unknown sessions and missing metrics through resource-only summaries. Actual inputs/state, independence and work remain unverified; missing native `memory.peak` gates peak qualification, not implementation. Still required: resource replay cards and scenario/request/edit integration; semantic/work/generation and non-file finalization validation, complete semantic manifest/qualification/evidence integration; native peak qualification, resource budgets and frozen campaigns; broader broken candidates, overhead characterization and campaign/identity/review governance. WP01 acceptance remains open. |
| WP02 / G02 | Authenticated artifact/environment/repository pins, actual corpus eligibility with failures/exclusions, two clean qualified materializations, fixed training/confirmatory/holdout partitions and per-scenario reset/state contracts. Prior local synthetic materialization and external-repository feasibility checks are not those decisions; no new materialization is claimed for this changed harness lock. |
| WP03 / G03 | Real-pytest occurrence/phase observer and canonical raw trace, narrow normalization, independent semantic comparator and broken-runner cases including skipped setup/teardown, strict XPASS, hidden collection failure, stale inputs and subprocess coverage. Synthetic ledgers, JUnit and limited line-set comparisons remain insufficient. |

WP04 completion is also still open. WP05 remains gated on WP03 and WP04; this
fixture is not an early production backend. M0, M1, coverage/ecosystem support,
generation/security hardening and qualification/release gates remain open under
the [specification's original dependencies](pt-implementation-spec.md).
