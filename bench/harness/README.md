# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals, semantically validate campaign
manifests, reset state, retain raw output, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
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
The schedule records basic host and harness-Python metadata, including the
harness executable's path and digest. It does not record environment variables,
inspect arm interpreters, or establish machine limits. Paths and command arguments
may contain sensitive information; review records before sharing.
`analysis.py` implements a paired geometric point estimator and exploratory
whole-block percentile bootstrap for caller-qualified samples. It rejects invalid
or incomplete blocks but cannot verify qualification, independence, statistical
adequacy, or publication gates; calculated intervals are not release evidence.
`manifest.py` checks YAML syntax and the supplied JSON Schema. Even a structurally
valid frozen manifest is always reported ineligible for confirmation: artifact,
reset, eligibility, independence, and other semantic checks are not implemented.

Install the pinned prototype dependencies and run tests from the repository root
with `uv` (the environment is local to `bench/harness`):

```sh
uv sync --locked --project bench/harness
uv run --locked --project bench/harness python -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness python bench/harness/manifest.py bench/benchmark-campaign.template.yaml
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
