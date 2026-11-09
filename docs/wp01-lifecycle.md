# WP01 publication-inclusive observation endpoint

Status: **implemented for the standalone exploratory timer; not WP01 acceptance,
semantic qualification or a PT backend**. Date: **2026-11-09**. Base: `3871aee`.
This closes that timer's unmeasured sample-publication stage without redefining
old observations, inventing a self-referential timestamp or relaxing publication
safety. The original failures and timing evidence remain in
[the WP01 register](wp01-status.md). `pt run` remains unavailable.

## Two explicitly different intervals

| Interval | Start | End | Recorded where |
|---|---|---|---|
| Command observation, unchanged | Immediately before process launch, after command/cwd checks | Leader/pipe handling and any optional raw capture publication/context cleanup | Immutable sample's `result.elapsed_ns` and original start/end/clock fields |
| Publication-inclusive observation | Entry to `measure_and_publish()`, before invocation-specific contract/path validation | Sample serialization/fsync/no-overwrite publication/temp cleanup, read-back, post-publication declared checks and final sample recheck have returned | Post-commit stdout receipt's `lifecycle.elapsed_ns` and separate start/end/clock fields |

The new endpoint ID is
`invocation_through_sample_publication_and_declared_finalization_v1`. Both clocks
are the same harness process's monotonic clock, not a product/child timer. The
outer interval must enclose the inner interval; no estimated overhead is
subtracted. In-memory contract normalization and byte verification cost are
included. CLI interpreter startup, argument/JSON parsing and the receipt's own
serialization/stdout transport are **not** inside this API-level endpoint.
The outer interval charges its observer/verification work and is a
correctness-instrumented harness observation, not unmodified shipping-product
timing or an engine speedup. A comparison must name its endpoint and layer.

An immutable file cannot contain a timestamp sampled after its own publication.
The sample therefore records process observations and **pre-publication**
finalization evidence, but never claims the larger lifecycle completed. After
publication/validation, the independent harness emits a distinct receipt with
the sample's exact name, byte count and SHA-256 and the post-commit endpoint.
Receipt transport is observer bookkeeping, not another required subject artifact
silently claimed timed. It must be retained separately to use this endpoint.
A missing, truncated or invalid receipt leaves the sample **unconfirmed**;
failure to output the receipt is a nonzero CLI outcome.

## Required-finalization contract

`--finalization-json` takes exactly these three fields:

- `expected_exit_code`: integer, or `null` when no exit expectation is declared.
  A declared intentional nonzero exit can match; an unexpected zero cannot.
- `artifacts`: a list of `{path, bytes, sha256}` objects for expected final files.
  Paths are normalized, relative to the command cwd; sizes and lowercase SHA-256
  are exact caller-supplied expectations, not inferred from a pass count.
- `absent`: normalized relative paths that must no longer exist, such as a
  cooperative test-owned cleanup marker. This does not prove release of a
  database lease, service, detached descendant or undeclared resource.

An omitted contract explicitly defaults to `null`, `[]`, `[]`: it does not
silently establish exit expectations, test work or resource cleanup. As with the
old diagnostic timer, a zero CLI status without an exit expectation can describe
a fully recorded nonzero command exit. **`finalized_unqualified` is not a test
pass, current-generation green or qualified sample.**

All modes require a reaped direct process, fully drained output and a non-timeout
exit before claiming finalized observations. Timeout/launch failure, mismatches,
missing reports and unreleased markers remain failures even with a zero command
exit or a published sample. Opted-in raw capture also requires matching prefix
blob bytes/size, consistent truncation metadata and unchanged verification.

Declared evidence is checked both before and after sample publication. Device,
inode, size, mtime and ctime fingerprints must agree across those reads, as well
as the expected bytes/digest. The final sample is rechecked after required-file
validation to catch replacement/corruption during that step. Changes are not
retried until green. Publication remains the original synchronized same-filesystem
hard-link/no-overwrite operation; its staging-alias cleanup is inside the clock.
The separate blob store's native no-replace rename protocol is unchanged.

The checker requires safe POSIX descriptor-relative lookup, rejects symlinks
within declared paths and at the root's final component, and never treats an
I/O/permission failure as successful absence. FIFOs/directories are not artifact
files. Artifact reads stream in bounded chunks; per-file declarations are capped
at 128 MiB and aggregate declared artifacts at 512 MiB, with at most 1,000 artifact
and 1,000 absence entries. Samples are capped at 1 MiB and receipts at 4 MiB.
The receiver rejects duplicate/non-finite JSON and incomplete receipts.

This is still a **caller-owned-path observation**, not an authenticated artifact
store or atomic multi-file snapshot. Ancestors of a supplied root can be
symlinks. Later mutation, detached writers and undeclared inputs cannot be ruled
out. No power-loss durability, coverage core/branch/context/subprocess semantics,
test-work equivalence or generation qualification follows from matching files.
Unknown/nondeterministic artifact content needs a later explicit validator; it
is not silently reduced to existence or a rounded coverage percentage.

## Failures and consumers

`inspect_lifecycle.py --sample <sample.json> --receipt <receipt.json>` verifies
the receipt/sample binding, interval arithmetic/enclosure, the recorded contract
and current declared finalization evidence. Consistent failed observations can
be inspected as failures; missing/corrupt or contradictory pairs are rejected.
It cannot authenticate timestamps, reconstruct unobserved history, establish
atomic state, or promote an observation to confirmatory status.

The CLI returns 0 only for finalized observations under the declared checks;
1 for timeout/launch failure or unmatched checks; 2 for preflight, measurement,
publication or receipt-output errors. Failure receipts and failed process/sample
observations are retained when possible. If an inner raw-finalization exception
prevents `measure()` returning, the failure receipt explicitly has no recovered
process result; partial blobs can remain. No process identity or success is
invented. Interruption after committing a sample can leave it without a receipt.
Existing destinations fail before launch where observable, and racing
destinations are never overwritten or adopted. Failures never replay work or
signal an already reaped process merely to retry publication.

The existing timeout is still a **command/process timeout**, not a hard deadline
for filesystem finalization. Hung filesystem calls, whole-boundary resource
accounting and campaign-level recovery remain open work, not hidden guarantees.

The paired driver still calls `measure()` and uses the command interval. Its
plans, inspections and summaries now explicitly name
`process_launch_through_exit_pipes_and_optional_raw_finalization_v1`; inspection
rejects relabelling these as publication-inclusive. Legacy plans without an
endpoint remain readable as command observations only. Arm/schedule publication,
receipt transport/persistence, preparation amortization, full request/watch/
replay endpoints and semantic/campaign validation have not been added to paired
latencies. A standalone receipt is not evidence those later gates are closed.

## Regression evidence and retained development failures

Reproduce from the repository root with the existing lock (no dependency changes):

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_lifecycle.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_finalization.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The targeted lifecycle suite currently passes **20 tests**; the file/contract
validator suite passes **6 tests**. Held-stage subcases put 0.15-second waits in
the actual writer, fsync, link, temporary cleanup, read-back and pre/post required
validation. Parent-observed windows must be enclosed by the outer clock but not
the earlier command endpoint; startup overhead is not the proof. Controls inject
serialization/fsync/link/cleanup failures, omitted/wrong/symlink publication,
same-byte replacement, missing reports, reappearing cleanup markers, corrupt raw
blobs, interruption and a broken receipt consumer. Actual controlled real-pytest
reporting and omitted cooperative cleanup also use the new validation path.
These are harness regressions, not PT conformance, independent performance
samples or coverage qualification.

Two failed development runs are retained: the first six-test validator run had
**five passes and one error**, because mocking `os.stat` also removed that callable
from the native `supports_dir_fd` capability set. The test now explicitly keeps
the mock in that set so the intended permission error is exercised; production
capability checks were not weakened. The next six-test run had **five passes and
one assertion failure**: its expectation incorrectly required an independently
missing ancestor path to fail absence validation. Permission denial is now tested
on a separate path; genuine missing-ancestor absence remains accepted. The next
six-test run passed. Neither failure was reclassified as a product mismatch,
benchmark exclusion or qualification result.

An additional post-review negative control exposed a real receipt-checker bug:
Python equality treats `True` and `1` as equal. The one new test initially had
**two failing subcases**, accepting an integer for a boolean verdict and a boolean
for the sample's integer schema version. Comparisons now preserve JSON types,
rather than using permissive Python object equality. Both controls are rejected
without erasing paths, ordering or numeric types. The following targeted run
passed all **20** lifecycle tests. The earlier **204-test full pass** predates
this added control and is retained as historical, not evidence it could detect
the bug.

Final verification on the selected Linux x86-64, GIL-enabled CPython 3.12.12
development host, with the existing lock and ResourceWarning treated as an error:

- **205 full harness tests passed** (`Ran 205 tests in 59.892s`, `OK`).
- **68 separate contract/audit tests passed** (`Ran 68 tests in 14.998s`, `OK`).
- Targeted checks passed: **20 lifecycle**, **6 file/contract validator**,
  **14 timing-boundary**, **14 original timer** and **5 raw-capture** tests.
  Earlier targeted runs are supplemented by the final full-suite run; subcases
  are not counted as independent benchmark samples.
- A direct CLI/sample/receipt inspection check retained the expected behavior:
  released marker -> CLI/checker **0/0**, unreleased marker -> **1/1**, although
  both commands exited zero and their sample digests verified. Both remained
  `confirmatory_eligible: false`. This is functional evidence, not a benchmark.
- `git diff --check` and **60 edited-document local links** passed. All **11**
  changed/new Python files parsed with Python 3.10 grammar; this is not Python
  3.10 runtime or neighboring-platform qualification. The unchanged lock,
  pyproject, toolchain, support-matrix and bridge pins were checked separately.

Rust/bridge, WP02 materializations, real semantic conformance and campaigns were
not rerun and are not qualified by this harness-only batch. No dependency or
toolchain pins changed. WP01–WP03, WP04 completion and all later production/
qualification/release dependencies remain open as recorded in the
[WP01 prerequisite register](wp01-status.md).
