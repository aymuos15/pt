# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals, semantically validate campaign
manifests, reset state, retain raw output by default, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
Known-delay regression tests cover process startup, shutdown, pipe drainage,
controlled real-pytest collection/teardown, test-owned reporting, real coverage.py
combine/save/JSON reporting, cooperative resource release, and opt-in raw-capture
publication/spool cleanup. These are instrumented harness fixtures, not PT
conformance or coverage qualification. They do not validate every product or
campaign timing boundary. See [WP01 evidence and open gates](../../docs/wp01-status.md).
On Linux, a separate timer test exercises timeout termination of an ordinary
owned child process group. It does not establish PT process supervision or
containment of hostile or detached descendants.
On POSIX, output is hashed and counted in bounded-memory chunks; it is not
retained. Timeout cleanup kills the process group and bounds pipe drainage.
Detached descendants may escape cleanup, and incomplete drainage is reported
as `output_complete: false`; the timer is not a sandbox. On non-POSIX systems
legacy `measure()` still uses in-memory pipes and process-tree cleanup is not
covered; the new standalone publication-inclusive endpoint requires safe POSIX lookup.
Unexpected harness errors and interruptions trigger bounded, best-effort child
termination; cleanup is not guaranteed if OS process control fails.

`schedule.py` independently generates reproducible balanced AB/BA block orders;
it does not establish independent observations. `paired.py` can run those
orders sequentially and preserve individual unqualified observations. It does
not verify state or work. Optional per-arm `--baseline-prepare-json` and
`--candidate-prepare-json` commands run before each arm, with separate timing
and records; failed preparation prevents that arm from running. Preparation is
not measured in the arm's elapsed time and is not proof of a valid reset. A zero
exit from the paired driver means only that records were written, not that
either command succeeded or was equivalent.
Optional `--baseline-cwd` and `--candidate-cwd` choose separate working
directories for each arm's preparation, probe, and measurement; otherwise both
use `--cwd`. Separate paths do not prove isolated or equivalent input states.
Optional `--baseline-probe-json` and `--candidate-probe-json` commands run after
successful preparation and before the corresponding measurement. Their output
hashes and statuses are recorded separately; nonzero exits or timeouts skip the
arm. A zero probe exit does not itself verify or certify equivalent state.
Optional `--baseline-probe-guard-json` and `--candidate-probe-guard-json` also
compare probe stdout to an explicit expected byte count and SHA-256; a mismatch
skips the arm even if the probe exited zero. Guarded probes must expect exit zero.
This is an observation check, not proof of equivalent starting state.
`state_probe.py --root <directory> --file <relative-path> [...]` hashes explicit
regular files, rejecting symlinks in listed paths and the root's final component.
It emits deterministic JSON suitable for a probe guard, but does not inspect
undeclared inputs, reject symlinks in ancestors of the supplied root, or provide
an atomic snapshot. File names and even hashes may disclose sensitive information.
`../resets/restore_declared_files.py` is a separately documented, opt-in reset
prototype for disposable worktrees; it can be supplied as a preparation command.
If a preparation or measurement reports incomplete output drainage or an
unreaped direct process, the runner preserves the arm record and aborts before
starting later arms. Reaped direct processes and drained pipes still do not prove
that detached descendants have exited.
`inspect_run.py <run-directory>` checks planned block order, record presence,
arm identities, arm-record schema, output metadata shape, and preparation/result
consistency. It cannot authenticate
records, verify unobserved work or state, or qualify a benchmark; it rejects
partial runs and unexpected files rather than silently excluding them.
When all stage intervals are available, inspection rejects recorded overlap or
out-of-order stages; legacy records with missing intervals are labelled
`incomplete` for that check. Recorded non-overlap cannot prove actual resource
isolation or rule out detached descendants.
`guards.py` compares a timer result to an expected exit and stdout sentinel;
even a match cannot prove equal work, correct generation, or artifact validity.
The paired driver accepts `--baseline-guard-json` and `--candidate-guard-json`
with explicit `expected_exit_code`, `expected_stdout_bytes`, and
`expected_stdout_sha256` fields. It retains matching and mismatching outcomes;
inspection recomputes guard verdicts rather than trusting recorded booleans.
`summarize_run.py <run-directory>` can calculate an exploratory paired point
estimate only when every arm completed and matched a requested guard; any
missing guard, mismatch, or failed measurement blocks the estimate instead of
dropping pairs. Missing interval ordering or explicitly truncated raw captures
also block the estimate. A matching sentinel still does not establish equal work, and
the summary is neither authenticated nor confirmatory.
The summary includes absolute mean arm latencies and can optionally run a
whole-block percentile bootstrap using `--bootstrap-resamples N --bootstrap-seed
S`. These values remain exploratory: input independence, equal work, sample
adequacy, and release criteria are not established by the calculation.
`sample.schema.json` describes the current exploratory arm-record structure; it
is not the complete WP01 raw-evidence format and does not establish validity.
`junit_inventory.py` compares ordered JUnit classname/name/outcome attributes,
preserving duplicates. JUnit is not authoritative pytest collection or phase
evidence; the comparison omits tracebacks and must not be used as an oracle.
`coverage_lines.py` compares exact paths and executed/missing/excluded line sets
from no-context, non-branch coverage.py JSON reports. It does not verify coverage
core, configuration, subprocess behavior, source identity, or PT conformance.
The schedule records basic host and harness-Python metadata, including the
harness executable's path and digest. It does not record environment variables,
inspect arm interpreters, or establish machine limits. Paths and command arguments
may contain sensitive information; review records before sharing.
New timer records include start/end monotonic nanoseconds and their clock domain;
only differences within the recorded harness process are meaningful. Older v1
records without these optional fields remain readable.
`elapsed_ns` starts immediately before process launch, after argument/cwd checks,
and ends after leader/pipe handling and any opt-in raw-capture finalization.
The standalone sample JSON and paired arm/schedule records are published **after**
their **command** intervals. The standalone CLI now also emits a post-commit
JSON receipt on stdout, with a separate `lifecycle.elapsed_ns` covering API-entry
validation, the command, sample publication/temp cleanup/read-back and declared
finalization checks. The receipt is bound to the sample's exact digest/size; the
sample alone does not claim this larger interval completed. Receipt serialization
and stdout transport are observer bookkeeping outside that declared endpoint.
See [the endpoint contract and failure controls](../../docs/wp01-lifecycle.md).
The paired driver/inspector/summary explicitly label their existing endpoint
`process_launch_through_exit_pipes_and_optional_raw_finalization_v1`; they do not
use the new lifecycle receipt or include arm/schedule publication in latency.
Inspection rejects attempts to relabel those records as lifecycle measurements.
Neither endpoint establishes a complete generation-valid result, watch/replay
lifecycle, resource containment or confirmatory eligibility.
`analysis.py` implements a paired geometric point estimator and exploratory
whole-block percentile bootstrap for caller-qualified samples. It rejects invalid
or incomplete blocks but cannot verify qualification, independence, statistical
adequacy, or publication gates; calculated intervals are not release evidence.
`manifest.py` checks YAML syntax and the supplied JSON Schema. Even a structurally
valid frozen manifest is always reported ineligible for confirmation: artifact,
reset, eligibility, independence, and other semantic checks are not implemented.
For drafts it also lists paths that fail frozen-schema requirements; this is a
structural preview, not verification of the referenced files or hashes.
`artifact_check.py <manifest> <bundle>` separately checks the manifest's listed
artifact digests against regular files named by SHA-256 in a supplied local
bundle (safe POSIX lookup only). It rejects symlink targets and reports unresolved
or mismatched fields. It cannot verify revisions, provenance, semantic content,
reset equivalence, or a stable snapshot; even all matches remain unqualified.
`blob_store.py` provides bounded, content-addressed, no-overwrite publication.
Blob files are now published with Linux `renameat2(RENAME_NOREPLACE)`, requiring
a libc wrapper and kernel/filesystem support. The synchronized staging file is
moved atomically, so a newly visible inode has no staging alias for its creator
to unlink during a duplicate reader's verification. Unsupported native operations
fail visibly; there is no hard-link, overwrite-rename or check-then-rename
fallback. Existing-blob verification still rejects any device/inode/size/mtime/
ctime change or wrong digest; it does not retry away evidence of mutation.
Content-addressed names and blob record fields are unchanged. This remains a
caller-owned-directory prototype, not a hostile-directory/parent-path security
boundary or a power-loss-durable store.
The standalone timer can optionally retain bounded stdout/stderr prefixes with
`--raw-output-bundle <existing-directory> --raw-limit-bytes <per-stream-limit>`
on Linux with that native publication support. Truncation is explicit and full
observed-stream hashes remain separate;
spooling and blob publication are inside the timer, so this is instrumented
timing, not an unmodified product benchmark. The paired driver can opt in with
`--capture-raw --raw-limit-bytes <per-stream-limit>` and stores blobs in its run
directory for each preparation, probe, and measured arm. Inspection verifies
referenced blob sizes and hashes but cannot authenticate the records or files.
Blob publication does not authenticate content or guarantee
power-loss durability. A blob-publication failure aborts the sample instead of
publishing a successful record; previously published blobs may remain. Raw output
can contain secrets; enable it deliberately.

The original concurrent-publication failure is retained in
[`docs/wp00-review.md`](../../docs/wp00-review.md). The link/unlink publication
protocol changed ctime when the creator removed its staging alias, even though
the blob's bytes matched. A deterministic regression pauses the creator after
publication and finishes it during a duplicate verification; it fails the old
protocol even on coarse ctime clocks by exposing its second link. Tests also
preserve rejection of ctime-only/other fingerprint changes with matching bytes,
corrupt/non-regular/symlink entries, fsync/native failures and unsupported
publication, and exercise multi-threaded and multi-process callers. This is
functional harness evidence, not completion of WP01 or PT qualification.

Targeted regression command (run from the repository root):

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_blob_store.py -v
```

Timing-boundary regression command:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_timing_boundaries.py -v
```

Publication/finalization regression commands:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_lifecycle.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_finalization.py -v
```

`--finalization-json` optionally declares `expected_exit_code` (an integer or
`null`), `artifacts` (relative paths with exact byte counts/SHA-256), and `absent`
(relative paths that must not exist). All three fields are required when supplying
the option. These checks run before and after publication, without retries or
repair. The final sample is also re-read after validation. Opt-in raw blob
references are checked against actual bytes, including the explicit prefix limit.
An omitted contract defaults to no expected exit or external-file/absence checks;
undeclared test work/resources are never implied verified. A lifecycle receipt
with `finalized_unqualified` is an observation, **not a test-pass result**.
Safe POSIX relative lookup is required for this new endpoint; unsupported systems
fail visibly. Legacy `measure()` itself is unchanged.

The parent holds each observed stage for 0.15 seconds, requires the command to
remain pending, then checks that its own monotonic hold interval is enclosed by
the timer. Exact stage order, fixture phases, reports, merged line sets and
resource-release evidence are checked separately. Six omitted-wait controls and
six prematurely ended record mutations must be rejected, as must an unreleased
resource despite zero exit and complete reports. These checks are local to the
fixture; `measure()` does not acquire a semantic or resource validator from them.
Coverage.py **7.17.2** is a locked, test-only development dependency on Python
>=3.11; the coverage-backed stage checks explicitly skip on Python 3.10. Only the
selected CPython 3.12.12 development profile was exercised. No pytest-cov plugin
or product dependency was added, and no effective coverage core, branch/context,
subprocess-coverage or ecosystem support claim follows.

Install the pinned prototype dependencies and run tests from the repository root
with `uv` (the environment is local to `bench/harness`):

```sh
uv sync --locked --project bench/harness --python 3.12.12
uv run --locked --project bench/harness --python 3.12.12 python -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/manifest.py bench/benchmark-campaign.template.yaml
```

Example exploratory observation and receipt check (write outside the repository):

```sh
directory="$(mktemp -d /tmp/opencode/pt-bench.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/pt_bench.py --cwd . --timeout 5 --output "$directory/sample.json" --finalization-json '{"expected_exit_code":0,"artifacts":[],"absent":[]}' -- bench/harness/.venv/bin/python -c 'print("hello")' > "$directory/receipt.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_lifecycle.py --sample "$directory/sample.json" --receipt "$directory/receipt.json"
```

An `exited_unqualified` observation means only that the process exited; even a
zero exit is not evidence that expected work happened. By default, output hashes
and sizes are recorded instead of content.
Records are published via a same-filesystem hard link after serialization and
file synchronization, without overwriting existing paths. A crash can leave a
hidden temporary file, and directory entries are not synced for power-loss
durability. Filesystems without hard-link support reject publication.
The CLI returns 1 for timeout/launch failure or unmatched declared checks, and 2
for preflight, measurement/publication or receipt-output errors. Failure receipts
and failed sample observations are retained when possible. A failure can leave
partial blobs, a staging file or a visible sample without a valid receipt; none
is a finalized lifecycle. Existing paths are never overwritten or automatically
adopted, and publication failure never replays command work.
