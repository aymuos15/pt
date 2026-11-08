# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals, semantically validate campaign
manifests, reset state, retain raw output by default, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
Known-delay regression tests cover process startup, shutdown, and pipe drainage;
they do not validate every product or campaign timing boundary.
On POSIX, output is hashed and counted in bounded-memory chunks; it is not
retained. Timeout cleanup kills the process group and bounds pipe drainage.
Detached descendants may escape cleanup, and incomplete drainage is reported
as `output_complete: false`; the timer is not a sandbox. On non-POSIX systems
capture still uses in-memory pipes and process-tree cleanup is not covered.
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
`sample.schema.json` describes the current exploratory arm-record structure; it
is not the complete WP01 raw-evidence format and does not establish validity.
The schedule records basic host and harness-Python metadata, including the
harness executable's path and digest. It does not record environment variables,
inspect arm interpreters, or establish machine limits. Paths and command arguments
may contain sensitive information; review records before sharing.
New timer records include start/end monotonic nanoseconds and their clock domain;
only differences within the recorded harness process are meaningful. Older v1
records without these optional fields remain readable.
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
The standalone timer can optionally retain bounded stdout/stderr prefixes with
`--raw-output-bundle <existing-directory> --raw-limit-bytes <per-stream-limit>`
on POSIX. Truncation is explicit and full observed-stream hashes remain separate;
spooling and blob publication are inside the timer, so this is instrumented
timing, not an unmodified product benchmark. The paired driver can opt in with
`--capture-raw --raw-limit-bytes <per-stream-limit>` and stores blobs in its run
directory for each preparation, probe, and measured arm. Inspection verifies
referenced blob sizes and hashes but cannot authenticate the records or files.
Blob publication does not authenticate content or guarantee
power-loss durability. A blob-publication failure aborts the sample instead of
publishing a successful record; previously published blobs may remain. Raw output
can contain secrets; enable it deliberately.

Install the pinned prototype dependencies and run tests from the repository root
with `uv` (the environment is local to `bench/harness`):

```sh
uv sync --locked --project bench/harness --python 3.12.12
uv run --locked --project bench/harness --python 3.12.12 python -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/manifest.py bench/benchmark-campaign.template.yaml
```

Example exploratory observation (write output outside the repository):

```sh
python3 bench/harness/pt_bench.py --cwd . --timeout 5 --output /tmp/pt-sample.json -- python3 -c 'print("hello")'
```

An `exited_unqualified` observation means only that the process exited; even a
zero exit is not evidence that expected work happened. By default, output hashes
and sizes are recorded instead of content.
Records are published via a same-filesystem hard link after serialization and
file synchronization, without overwriting existing paths. A crash can leave a
hidden temporary file, and directory entries are not synced for power-loss
durability. Filesystems without hard-link support reject publication.
