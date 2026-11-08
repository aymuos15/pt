# Exploratory harness prototype

This is an independent, standard-library-only command timer. It does **not**
qualify outcomes, compare work, capture resource totals, validate campaign
manifests, reset state, execute paired blocks, retain raw output, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
The current capture uses in-memory pipes and is unsuitable for output-heavy or
untrusted commands. Timeout cleanup uses a POSIX process group; escaped
descendants and non-POSIX process trees are not covered.

`schedule.py` independently generates reproducible balanced AB/BA block orders;
it does not run them or establish independent observations.

Run tests from the repository root:

```sh
python3 -m unittest discover -s bench/harness/tests -v
```

Example exploratory observation (write output outside the repository):

```sh
python3 bench/harness/pt_bench.py --cwd . --timeout 5 --output /tmp/pt-sample.json -- python3 -c 'print("hello")'
```

An `exited_unqualified` observation means only that the process exited; even a
zero exit is not evidence that expected work happened. Output hashes and sizes
are recorded instead of content, so this prototype does not preserve raw output.
