# Serial-core development mechanism corpus

This is a **test-owned training corpus**, not a representative/holdout corpus,
semantic oracle, PT backend qualification or benchmark. The older probe inventory
and external shortlist remain unchanged and unassigned. No optimization has been
tuned on this profile; any later confirmatory work requires a separate frozen set.

The finite profile is Linux x86-64, GIL-enabled CPython **3.12.12**, pytest
**8.4.2**, serial `python -m pytest`, and no third-party pytest entry points. The
independent `pyproject.toml` / `uv.lock` freeze its development dependencies; the
general harness lock and support matrix are unchanged.

`corpus.json` binds every fixture file and both environment files by SHA-256.
It declares ten ordered cases, exact argv, expected exit, ordered JUnit occurrences
and import/fixture sentinels where present:

- Within-session globals and runtime parametrization.
- Setup error, teardown error, strict XPASS, skip and expected xfail.
- One import and one test call per requested fresh pytest invocation.
- Autouse/override/dynamic fixture lookup and exact finalizer ordering.
- An explicitly loaded custom collector with duplicate node IDs and a failure.
- Collection failure and a separate no-tests/exit-five case.
- Built-in doctest and unittest integration, retaining an intentional unittest failure.
- A fixed application-work negative control, not a claimed speed measurement.

These JUnit expectations do **not** supply authoritative node identities or
individual setup/call/teardown reports. Duplicate XML occurrences are preserved,
not deduplicated, but a phase-level observer/comparator is still required by WP03.
Passing expected process/probe checks does not mean the intentional test failures
were passes, and cannot qualify PT.

## Two clean offline installations

From the repository root, after the normal locked harness setup has populated uv's
cache, use a **new** output directory under an existing parent:

```sh
directory="$(mktemp -d /tmp/opencode/pt-serial-core.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/corpus/serial_core/materialize.py --output "$directory/run" --execute
```

This explicitly authorizes two new isolated venv installs and twenty pytest
invocations. It never installs into a user/system environment, changes the lock,
downloads dependencies/interpreters during the run, builds an sdist, clears shared
caches, adopts a service or retries already-started work. Missing offline artifacts
fail and retain the partial output. Use a new directory for a new development check;
the tool refuses existing outputs.

The tool freezes original manifest/project/lock/fixture bytes before execution,
creates each venv from the same observed pinned interpreter, uses `uv sync
--offline --locked` against the frozen project and forces `UV_LINK_MODE=copy`.
The two installs use the same locked artifacts/cache, **not independent builds**.
The cache location is queried explicitly; user configuration is disabled.

The optional `--base-python FIRST SECOND` selects an explicit absolute executable
for each venv and records both paths; invalid/missing selections fail before setup
instead of substituting another interpreter. Without that option, the original
same-observed-base behavior is unchanged. The separate [pinned private-base
check](../interpreter/README.md) verifies complete archive-derived base prefixes
before/after running this corpus; that evidence is not inferred from a binary
hash or this tool's site-packages comparison alone.

Each case gets a fresh file copy and a fresh subprocess. There is no preflight
collection. A separate runtime metadata check reads Python/package versions and
pytest entry points, not the project or pytest collection. The subject environment
is an explicit minimal profile: private HOME/TMPDIR, C.UTF-8 locale, no inherited
PYTHONPATH/PYTHONHOME/PYTEST_ADDOPTS/PYTEST_PLUGINS, and `PYTHONDONTWRITEBYTECODE=1`.
Plugin autoload is **not disabled**; unexpected installed pytest entry points stop
the profile rather than being silently disabled. This controlled environment is
not a change to PT's eventual user environment policy.

The existing independent process observer provides bounded raw-output capture,
timeouts and owned-process cleanup. `/usr/bin/env -i` supplies the declared child
environment without shell interpolation or mutating the coordinator environment.
Setup and command intervals are diagnostics, not product latency or an overhead
estimate. Truncation, timeout or uncertain output fails the unit.

Every regular file under each environment's `site-packages`, including unlisted
files, is hashed before and after its ten cases. Cross-environment comparison
excludes only `*.dist-info/RECORD`, whose generated entrypoint hashes can depend on
the environment path; those RECORD bytes remain retained and checked for mutation
within their own environment. Package contents and other metadata are not broadly
normalized. The interpreter byte hashes must match across environments. This is
not an audit of all stdlib/system-library/venv-bin files, authentication of wheels
or proof that installed state was immutable between observations.

The private output retains the frozen inputs, both environments, work copies,
bounded command observations/raw bytes, all JUnit/sentinel files and `result.json`.
All twenty planned case rows remain. A mismatch or uncertainty stops later cases
and the second environment without retry; known-not-run rows and lost-return
unknowns remain distinct. Complete-looking files do not recover lost API returns.
The six representative/artifact/environment/oracle/backend/release qualifications
remain null and confirmatory eligibility false.

The source inventory must include every fixture file, with no extra/missing files,
unsafe paths or symlinks/FIFOs. Frozen and original inputs must still match at the
end. File observations are bounded to 4 MiB each and 8192 files / 64 MiB per scanned
tree. This is not a disk quota, sandbox, atomic snapshot, authenticated interpreter
or a hostile-directory boundary; root ancestors are caller-owned. Review retained
raw paths/output before sharing and do not commit generated environments/results.

See [WP02 progress and remaining gates](../../../docs/wp02-status.md).
