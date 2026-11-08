# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals, semantically validate campaign
manifests, reset state, execute paired blocks, retain raw output, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
The current capture uses in-memory pipes and is unsuitable for output-heavy or
untrusted commands. Timeout cleanup uses a POSIX process group; escaped
descendants and non-POSIX process trees are not covered.

`schedule.py` independently generates reproducible balanced AB/BA block orders;
it does not run them or establish independent observations.
`analysis.py` implements only the paired geometric point estimator for
caller-qualified samples; it rejects invalid or incomplete blocks but cannot
verify qualification, independence, confidence intervals, or publication gates.
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
