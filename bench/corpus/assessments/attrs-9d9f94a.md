# Candidate assessment: python-attrs/attrs at 9d9f94a

Status: **unqualified; incompatible with the provisional pytest 8.4.2 profile**.
This is a local installation and pytest-only feasibility check, not PT
conformance or a performance measurement. The candidate remains unassigned in
`../candidates.toml`.

## Candidate and environment

- Source: `https://github.com/python-attrs/attrs.git`, revision
  `9d9f94a043de7fc4012459853a4ed597a5577855`, tree
  `eaa403097ba83b1b5a5e39790501105e31e5f192`.
- The pinned repository's `uv.lock` SHA-256 is
  `617977f3b91f711e94b46bd6a61c879109631c8dab54150b2fb1af376dbe292d`.
- Its `tests` dependency group declares **pytest > 9**, so it cannot satisfy
  PT's *proposed* exact pytest 8.4.2 profile without changing the candidate's
  declared dependency contract. No altered-dependency comparison was attempted.
- Local check completed 2026-11-08 UTC on Linux x86-64, CPython 3.12.12;
  interpreter binary SHA-256 was
  `3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66`.
  That digest identifies observed bytes, not verified distribution provenance.
- The upstream lock resolved pytest 9.1.1, hypothesis 6.168.1, pytest-xdist
  3.8.0, cloudpickle 3.1.2, pympler 1.1 and their locked dependencies. The
  candidate wheel installed as `attrs==26.1.1.dev83`.

## Procedure and observations

Two disposable virtual environments were created from the pinned source using
`uv sync --locked --python 3.12.12 --group tests --no-default-groups
--no-editable`; the second used `--offline` and the same local cache. Both
installations used the **same source checkout and cached build artifacts**, not
independent builds. Two separate detached worktrees at the same revision were
used for test execution. Git reported no tracked modifications afterward;
ignored files were not independently audited.

Each environment ran serially, with plugin autoload left enabled, inherited
`PYTHONPATH`, `PYTHONHOME`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, and
`PYTEST_DISABLE_PLUGIN_AUTOLOAD` removed, and `PYTHONDONTWRITEBYTECODE=1`:

```text
<environment>/bin/python -m pytest -q --hypothesis-seed=42017 --junitxml=<external-output>
```

Both commands exited 0 and pytest reported **1,401 passed, 10 skipped, and
1 xfailed**. The skip reasons included Python-version conditions, missing
pyright, and a PyPy-specific case; these remain part of the observed denominator.
The environments contained the hypothesis and xdist pytest entry points; no
`-n` option was supplied, so this was a serial feasibility check.

The ordered JUnit classname/name and outcome tag/type/message observations
matched across both runs: 1,412 occurrences, normalized SHA-256
`6416f67fde06915acc44e81303291fb02ae1196dd3b3efa7d60189936651eb48`.
The sanitized normalized record is
[`attrs-9d9f94a-junit-normalized.json`](attrs-9d9f94a-junit-normalized.json)
(file SHA-256 `ef92e0548b603c94380cb62e0cbbd824a44dfc7d6b9aa91d00a954fe33b105db`).
The original JUnit files remained in the local temporary assessment directory
and were not committed; their SHA-256 values were
`dae4b19d0a99fbe24332362ed27134943677ecc17a5f57523eefe7c9b90571f4` and
`89526e172a0410a12a03ab71672ffc350ea634fb9ef14c45f81856978a603ee3`.
They include local runtime metadata and may not remain available indefinitely.

After the runs, the local installed-file checker reported matching inventories:
783 hashed `RECORD` entries verified per environment, 779 compared entries,
13 unhashed `RECORD` files and four generated entrypoints excluded from
cross-directory comparison. The comparable inventory digest was
`8f38fae36923921a55f17c942051e094e3787610f82b070e1928abc72d90ad61`.
This did not authenticate package `RECORD` files, verify unlisted files, or
establish that installation state remained immutable during execution.

## Decision and remaining work

Keep eligibility **unassessed** for any future supported profile. Before use in
a campaign, select and review a compatible pytest profile, independently
materialize pinned artifacts, establish reset and source-generation guarantees,
qualify plugin behavior and actual test-work identity, and assign the candidate
to a preregistered corpus split. JUnit classname/name records are not
authoritative pytest node IDs; the comparison does not preserve individual
setup/call/teardown reports or prove equivalent fixture effects. No benchmark
timings, PT execution, or speed claims are made here.
