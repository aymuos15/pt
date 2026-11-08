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
