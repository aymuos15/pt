# WP01 paired publication-inclusive observations

Status: **implemented exploratory integration; WP01 remains open**. Date:
**2026-11-09**. Base: `02c72c6`. This extends the
[standalone endpoint](wp01-lifecycle.md), not PT's runtime. There is no PT backend,
semantic oracle, qualified profile, confirmatory campaign or release claim;
`pt run` remains unavailable. No dependency/toolchain pins changed.

## Endpoint and integration

`paired.py` now defaults to `--timing-endpoint lifecycle`. Its version-2 plan
names `invocation_through_sample_publication_and_declared_finalization_v1`.
Each requested preparation, probe and measured arm calls the same independent
outer harness API. Its interval includes contract/context validation, process
launch/exit and pipe handling, optional raw capture, guard checks, declared-file
archival, sample serialization/fsync/no-overwrite publication/staging cleanup,
read-back, final required checks and the last sample recheck. The inner command
interval remains unchanged, separately recorded and enclosed by the outer one.

Preparation and probes still have **separate** intervals; they are not folded
into the measured arm or advertised as free preparation in a session replay.
The summary's ratios, absolute latencies and whole-paired-block bootstrap use
the **measured arm's lifecycle elapsed time**, never its shorter command time.
Endpoint IDs propagate into summaries/bootstrap inputs. Mixing endpoints, or
mixing labelled and unlabelled inputs, is rejected rather than silently falling
back to whichever gives a favorable result.

The immutable sample cannot contain its own post-publication timestamp. A
separate receipt binds that sample's exact name/bytes/SHA-256 and contains the
outer clock/status plus the stage context and evidence. Receipt persistence and
read-back are **observer bookkeeping outside that declared endpoint**. They must
finish before another stage starts. Initial schedule publication is also outside
stage timing and must verify before any command starts. These boundaries do not
claim full CLI startup, campaign publication, watch/replay/amortized latency,
whole-boundary resource accounting or a hard filesystem-finalization deadline.
The timed validation/archival is correctness instrumentation, not an unmodified
shipping-product benchmark or a measured engine speedup.

## Required finalization and retained evidence

The standalone `{expected_exit_code, artifacts, absent}` contract is used by:

- `--baseline-finalization-json` / `--candidate-finalization-json` for measurement;
- `--baseline-prepare-finalization-json` / candidate equivalent for preparation;
- `--baseline-probe-finalization-json` / candidate equivalent for probes.

Preparation/probes require exit zero. A measurement guard's declared exit is
bound into its finalization contract; contradictory expectations, an unrequested
stage's requirements, unknown options and ambiguous/non-finite object JSON fail
before execution. Deliberately expected nonzero measurement exits remain possible;
they do not become ordinary passes or PT qualification.

Later stages/reset procedures may overwrite the same report path. Therefore
paired runs archive **observed declared report bytes** under their SHA-256 in
the private run's `blobs/` directory, inside the timed boundary. Safe regular-file
lookup and unchanged device/inode/size/mtime/ctime fingerprints are required
across copying and publication. This uses the existing Linux native no-replace
blob publisher, with no weakened ctime/digest check or retry-until-green behavior.
Bounded digest/size mismatches are retained under their **actual** digest as
failed evidence. Unreadable, unsafe or oversized files are failed observations,
not invented complete artifacts. Archive references must stay inside the declared
path/byte budget before any blob read; record and retention limits remain explicit.

Declaring an artifact is an opt-in to retain those bytes even when stdout/stderr
capture is off. Reports/hashes/paths/arguments can disclose sensitive data; review
the private bundle before sharing. Arbitrary project files are not collected.

Inspection uses retained bytes plus typed **historical** process, stat and
absence observations. It does not reread a later-mutated worktree and pretend it
is an earlier arm. Original stat identities remain in the trace; retained blobs
are checked by their current safe type, size and digest, not by equating their
inodes with source files. Absence observations cannot be authenticated/recreated
from a file that no longer exists. This is not a current-state, atomic snapshot,
generation, lease/service-release, descendant-containment or coverage-semantics
claim. The standalone inspector's ordinary live-state checks remain distinct.

## Version-2 layout and failure accounting

```text
schedule.json                         # fixed order, commands/contracts/guards
blobs/<sha256>                        # required report bytes; optional raw prefixes
preparation-000001-baseline.json       # sample when requested/executed
receipt-preparation-000001-baseline.json
probe-000001-baseline.json             # sample when requested/executed
receipt-probe-000001-baseline.json
block-000001-baseline.json             # measurement sample or explicit skipped record
receipt-block-000001-baseline.json     # only for an invoked measurement
...                                   # same deterministic names per arm/block
abort.json                            # optional stop point/cause/diagnostic receipt
```

Stage context binds the block, scheduled position, arm and stage. Inspection
checks those identities, exact sample/receipt binding, contracts/guards, process
observations, retained bytes and non-overlapping ordered lifecycle intervals.
Unknown/missing files, missing required receipts/blobs, inconsistent clocks,
changed contracts and endpoint relabelling are rejected. Guard/JSON comparisons
preserve types (`True` is not an integer assertion). The legacy
`sample.schema.json` is still the **version-1 command record schema**, not a
claim to describe the complete version-2 or WP01 raw-evidence format.

Ordinary failed preparation/probes skip their arm and remain in the denominator;
known complete timeout/nonzero observations can be retained without pretending
they matched. Publication/archival failure, incomplete reaping/drainage or failed
declared artifact/absence checks abort **before** further stages/arms. No work is
automatically replayed, no existing record adopted/overwritten, and no reaped
process is signalled merely to retry artifact publication.

When observer storage permits, `abort.json` preserves the stop point and receipt
even if the receipt's normal publication failed. That diagnostic copy is not a
successful observer commit. Inspection reports `record_consistency: aborted`,
accounts for every planned arm, and labels later arms `not_run_run_aborted`.
`planned_arm_count` is always twice the planned block count; `observed_arm_count`
counts invoked measurements for which a receipt was recovered, not proved test
work. Failed lifecycle and guard counts remain visible alongside raw exit status.
Every recorded abort blocks **all** point/absolute/bootstrap estimates, including
an otherwise finalized subject receipt whose own persistence failed. Surviving
favorable pairs are never analyzed alone.

Unrecoverable abort/receipt storage failure, corrupt observer output or retained
unreferenced fragments can make the bundle invalid rather than a consistent
abort. It is retained for diagnosis, not cleaned/relabelled to enable an estimate.
Inspection exit zero means structural consistency only, including an accounted
abort; consumers must check its status or use the strict summary. Producer aborts
exit nonzero, and a blocked summary exits nonzero. Every report remains
`confirmatory_eligible: false` and cannot authenticate unobserved history.

## Legacy separation and remaining gates

`--timing-endpoint command` retains the old version-1 path and explicitly rejects
required-finalization options. Old plans without an endpoint remain readable as
command-only observations, not upgraded lifecycle samples. Legacy tests select
this mode explicitly; the new default is covered separately. Version-1 plans
cannot be relabelled as version-2, and the analyzer will not mix their intervals.

This closes the focused paired publication/receipt integration gap, not WP01's
acceptance gate. Complete semantic manifests/raw formats/result cards,
scenario/request/replay endpoints and amortization, whole-boundary CPU/memory,
broader broken-runner controls, overhead characterization and campaign governance
remain open. WP02/WP03, WP04 completion and all backend/qualification/release
dependencies remain in the [prerequisite register](wp01-status.md).

## Regression evidence and retained development failures

Reproduce from the repository root, using the unchanged lock:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_lifecycle.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The targeted suite has **20 tests**. Parent-observed 0.15-second holds verify
publication delay in preparation/probe/measurement and report archival, while
actual summaries are checked against receipt (not command) durations. A delayed
receipt write must remain excluded from its own clock yet prevent the next stage
from starting. Failure controls cover sample/receipt/schedule/archive publication,
omitted/corrupt metadata, matched-guard cleanup/report failures, bounded wrong
bytes, same-byte replacement during archival, missing receipts/blobs/abort markers,
type ambiguity, mixed endpoints, expected/unexpected exits and incomplete pairs.
Repeated report paths and later worktree changes must still permit only explicitly
historical inspection. These are functional harness checks, not conformance or
independent benchmark/coverage observations.

Retained failures: the first new **14-test** targeted run reported **five failure
entries and four error entries**. The fixtures assumed seed 3 chose the same
first arm for both one-block choice and two-block shuffle, and omitted a lazy
`raw_capture` test import after removing the harness import path. Controlled
failure fixtures now deliberately select baseline-first order with seed 3 for
one block and seed 0 for two; the production randomized schedule is unchanged.
The next 14-test run passed. This is fixture setup, not benchmark order tuning.

The first full **219-test** run had **217 passes and two failures**: one old
relabeling check expected its earlier diagnostic text, and the reset/probe test
expected a version-1 sample mode although it now exercised the new default.
Version-1 relabeling still fails explicitly, and reset/probe assertions now check
the version-2 sample plus unqualified receipt. Existing legacy schema/inspection
tests explicitly request command mode; no failure was excluded or converted into
support/benchmark evidence.

Final verification on the selected Linux x86-64, GIL-enabled CPython 3.12.12
development host, using the unchanged lock and ResourceWarning as an error:

- **225 full harness tests passed** (`Ran 225 tests in 48.488s`, `OK`).
- **68 separate contract/audit tests passed** (`Ran 68 tests in 8.650s`, `OK`).
- **20 paired lifecycle tests passed**, plus targeted regressions for the
  standalone lifecycle, file validation, legacy inspection and reset integration.
  Subcases are not independent benchmark observations.
- `git diff --check` and **69 edited-document local links** passed. All **13**
  changed/new Python files parse with Python 3.10 grammar; this is not Python
  3.10 runtime qualification. Lock/pyproject, support-matrix, Rust toolchain and
  bridge pins are unchanged.
- A direct default-CLI check with two planned blocks retained **4/4** measured
  receipts for released markers. An unreleased marker, despite command exit zero
  and a matching stdout guard, aborted after **1/4** measured receipts, counted
  the other **3** arms as not run, and returned a blocked summary with no ratio,
  absolute comparison or bootstrap. Both cases remained unqualified. The
  functional bundle is retained locally under
  `/tmp/opencode/pt-paired-lifecycle-evidence-bwb7py4c`, not committed as a benchmark.

Rust/bridge, corpus materializations, real PT conformance and performance
campaigns were not rerun or qualified. **No measured test-runner speedup exists**;
this batch improves evidence accounting, not execution speed or backend readiness.
