# Serial ecosystem mechanism references

This is **test-owned training material**, not representative repositories,
untouched confirmation, a PT backend, production plugin support or timing data.
No optimization is enabled or tuned here. The twelve external candidates remain
unassessed/unassigned, with their declared conflicts preserved.

The separate lock selects Linux x86-64, GIL-enabled CPython **3.12.12**, pytest
**8.4.2**, pytest-asyncio **1.4.1.post1** and Hypothesis **6.170.15**. These exact
plugin releases declare compatibility with the selected interpreter/pytest ranges;
that is not itself qualification. Runtime transitive pins are iniconfig 2.3.1,
packaging 26.3, pluggy 1.7.0, Pygments 2.21.0, sortedcontainers 2.4.0 and
typing-extensions 4.16.0. The general harness and product dependencies are unchanged.

## Actual mechanism coverage

[`profile.json`](profile.json) declares the expected work before execution:

| Case | Requested occurrences / applicable phases | Expected behavior |
|---|---|---|
| Async | 3 / 8 | Awaited test/fixture bodies, same-loop async release, an assertion after await and an async setup error with no call phase; exit 1 remains intentional. |
| Property | 2 / 6 | Real Hypothesis generates the full two-boolean and four-boolean-pair domains. Six body examples are **not six pytest occurrences**. |
| SQLite | 2 / 6 | Import-time database write, exactly one collection import, function-owned connection/lease, committed writes, reset and close/release before the next fixture. |

Hypothesis uses explicit `database=None`, `derandomize=True`, finite example limits
and no deadline. This bounded setup tests that actual generation runs, not general
shrinking, arbitrary strategies or example-database semantics. Finite-domain
coverage is checked independently; **raw example/effect order is still compared
exactly**, never sorted to force a match. Its remaining storage is directed to
the test-owned work copy and retained. SQLite is a local test-owned fixture, not
a general external-service/database reset adapter.

The independent deliberately broken plugin omits a passing awaited body, all
generated bodies of one property, or database finalization. Each control compares
two explicitly selected **one-occurrence** requests, with zero exit and three
matching phase reports. External effects must still detect each omission; the
independent required-absence check additionally rejects the leftover database
lease. Matching reports are deliberately insufficient evidence of completed work.

## Reproduction

First explicitly prepare the two [archive-pinned private interpreter prefixes](../interpreter/README.md).
Then use a **new** output directory outside the repository:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -B bench/corpus/serial_ecosystem/check_references.py --prepared /absolute/path/to/prepared --output /absolute/new/output --execute
```

The default is **fully offline**. If the exact locked wheels are not cached,
setup fails and retains its outcome. A separate explicit `--prepare-artifacts`
permits wheel downloads only during the first new environment's locked setup;
the second remains offline. `--no-build` forbids registry sdist builds, and
`UV_LINK_MODE=copy` avoids shared installed cache inodes. No caller environment
is upgraded, no lock is rewritten, and plugin autoload is **not disabled**.
Actual package versions and both pytest11 entries must match the declared profile.

There are **24 predeclared fresh real-pytest requests**:

- In each of two clean venvs, three cases run once without the reference observer
  and twice with it: **18 requests**. Exit/JUnit/effects must match the declaration
  and uninstrumented observation. The six within-environment reference-pair
  comparisons retain uncertainty instead of assuming a disagreeing baseline valid.
- Three omission controls each have a reference and deliberately broken request:
  **six requests**. They are explicit correctness controls, not automatic retries,
  fallback execution or a PT candidate performance comparison.

The same literal work cwd is recreated from frozen inputs before each request;
every earlier work/output copy is retained by rename, not deleted. Interpreter
bases, installed files and source/observer bytes are checked before/after the
applicable execution. Across venvs only the retained path-specific RECORD entries
are excluded; within-environment mutation checks exclude none. The output retains
all source/lock hashes, frozen oracle code, command/raw observations, traces,
JUnit, exact effects, databases, leases, package inventories and planned outcomes.

The existing independent bounded observer owns process timing/cleanup as setup
diagnostics, not a shipping latency authority. The explicit minimal environment
has private HOME/TMPDIR, C.UTF-8, disabled bytecode **writes**, fixed hash seed and
the observer source path. This is a correctness experiment, not a change to PT's
caller-environment policy. No pytest preflight collection, implicit installation,
plugin suppression, result overwrite or started-work replay occurs.

Failed, unsupported, not-run and lost-return rows remain distinct. A complete
trace/JUnit cannot recover a lost process API return. Known async failure is not
a passing test or an excluded sample. Full-prefix/site/source observations are
not immutable snapshots, complete host-library identity or test sandboxing.
All eight qualification fields remain null and confirmatory eligibility false.

See [WP02](../../../docs/wp02-status.md) and [WP03](../../../docs/wp03-status.md)
for retained verification evidence and open gates. Generated environments/raw
results do not belong in the repository.
