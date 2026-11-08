# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals, semantically validate campaign
manifests, reset state, retain raw output, or implement
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
Optional `--baseline-probe-json` and `--candidate-probe-json` commands run after
successful preparation and before the corresponding measurement. Their output
hashes and statuses are recorded separately; nonzero exits or timeouts skip the
arm. A zero probe exit does not itself verify or certify equivalent state.
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
`blob_store.py` provides bounded, content-addressed, no-overwrite publication
for a caller-provided byte stream. It is not yet connected to timer output;
it does not authenticate content or guarantee power-loss durability.

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
zero exit is not evidence that expected work happened. Output hashes and sizes
are recorded instead of content, so this prototype does not preserve raw output.
Records are published via a same-filesystem hard link after serialization and
file synchronization, without overwriting existing paths. A crash can leave a
hidden temporary file, and directory entries are not synced for power-loss
durability. Filesystems without hard-link support reject publication.
