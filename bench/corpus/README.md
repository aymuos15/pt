# Corpus development

These synthetic probes are **not** a representative corpus or evidence of PT
compatibility. They are initial material for WP02 and WP03. They have no frozen
training, confirmatory, or holdout assignments; no environment locks or reset
contracts have been established.

`manifest.toml` records draft file hashes and leaves all probes unassigned. The
independent inventory checker verifies declared files only; it does not detect
unlisted files, establish an immutable snapshot, or qualify probe behavior:

```sh
uv run --locked --project bench/harness python bench/harness/corpus_inventory.py bench/corpus/manifest.toml
```

`probes/noop_cases.py` contains one successful test. `probes/phase_cases.py` is
intentionally nonzero: it includes a passing test, setup failure, teardown
failure after a passing call, and strict XPASS. Run it explicitly, for example:

```sh
python -m pytest -p no:cacheprovider bench/corpus/probes/phase_cases.py
```

The probe alone does not prove a comparator can distinguish the phases. Future
oracle tests must verify actual phase reports, multiplicity, and exit status,
including broken-runner negative controls. Direct pytest behavior must be pinned
and qualified before use in a confirmatory campaign.

The harness test suite includes a smoke check of these probes using pinned
pytest, with external plugin autoload disabled for this controlled check. It
inspects JUnit output and expected exits; it is not a detailed phase oracle,
qualification of external plugins, or a benchmark baseline configuration.

`probes/lifecycle_cases.py` uses collection-time parametrization with Unicode IDs
and records session/function fixture setup, calls, and teardown to the path in
`PT_PROBE_EVENT_FILE`. Its smoke check confirms collection does not execute
fixtures and checks exact event order. Collection and execution are deliberately
separate invocations **only for this corpus check**; a PT run must not add a
hidden preflight collection invocation.

`probes/import_effect_cases.py` appends an import sentinel and a test-call
sentinel to `PT_PROBE_IMPORT_EVENTS`. Its smoke check includes a negative control
showing that separate collection and execution cause an additional import. This
validates the probe against pytest, not PT's future same-session behavior.

`probes/custom_collector_plugin.py` is explicitly loaded in a controlled smoke
check; it is not registered for ordinary pytest. The smoke check creates a
temporary `.ptcase` file containing two identically named passing items and one
intentional failure, and checks both duplicate collection and JUnit occurrences.
This remains an isolated synthetic case, not ecosystem qualification.

`probes/bytecode_integrity_probe.py` creates same-size, same-mtime edits in its
own temporary directory. On the tested CPython profile its timestamp-based pyc
negative control loads stale code, while a checked-hash pyc detects the edit.
It does not purge shared caches, establish a benchmark reset policy, or test PT.

`probes/invocation_profile_plugin.py` records whether the current directory is
on `sys.path` at pytest session start. A controlled Linux smoke test loads it
explicitly for both `python -m pytest` and the pytest console script, with
plugin autoload disabled and an otherwise empty temporary working directory.
It checks the observed distinction on this profile; it does not claim all
plugins or environments behave identically.

`probes/fixture_lookup_cases.py` is copied into a temporary project with a
test-owned `conftest.py`. Its smoke check exercises dynamic fixture lookup,
autouse fixtures, an overridden fixture, and the exact setup/teardown sequence.
The temporary project is a synthetic probe, not full pytest conformance evidence.

`probes/dynamic_plugin_probe.py` is explicitly loaded for a controlled smoke
check and registers another plugin during collection. The test records its later
setup and teardown hooks. A negative control omits the plugin and still returns
zero, demonstrating why the exit code alone is insufficient. This does not yet
test PT capability fallback or plugin preservation.

For an optional offline local reproducibility smoke check, first populate uv's
cache with the documented locked setup, then run:

```sh
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/materialize_check.py --temp-root /tmp/opencode
```

The check creates two disposable environments, installs the lock from local uv
cache, and compares Python/distribution versions, interpreter bytes, and
phase-probe occurrences. It verifies hashed distribution RECORD entries before
and after the probe, compares non-entrypoint file inventories, and lists unhashed
entries and generated entrypoints excluded from cross-directory comparison.
It deletes only its own temporary directory. It does not authenticate RECORD,
check unlisted files, create an immutable snapshot, or qualify the full corpus.
