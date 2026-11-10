# Development environment — provisional

These are reproducibility choices for developing the current prototype, not a
qualified PT support matrix or proof of artifact provenance. WP00's conservative
definition/engineering self-review is complete (`wp00-review.md`), not independent
qualification. The selected initial target is Linux x86-64,
GIL-enabled CPython 3.12.12 and pytest 8.4.2.

- `rust-toolchain.toml` selects Rust **1.99.1** with rustfmt and clippy. With
  rustup installed, invoking Rust tools from the repository may download this
  toolchain into the user's rustup installation. An initial Linux x86-64 check
  observed rustc commit `58cf8f9c35b355199727627d07ae34a4e2846d67`; this is not
  a verified distribution-artifact digest. A workspace now contains WP04
  process-only primitives; it is not yet a qualified pytest backend.
- The independent harness uses CPython **3.12.12** for the initial development
  check and pytest **8.4.2** for its controlled corpus smoke tests. Coverage.py
  **7.17.2** is a test-only development dependency for instrumented timing-boundary
  fixtures on Python >=3.11, not a qualified PT coverage profile. Its Python
  dependencies are locked in `bench/harness/uv.lock`. The local `uv` used for
  these instructions was **0.12.3**; installer provenance and interpreter
  artifact hashes still require independent verification for a campaign.
- The private native socket handoff explicitly adds **command-fds 0.3.3** as a
  Cargo-locked build dependency. The workspace still forbids unsafe Rust blocks;
  the external crate implements child-only pre-exec mapping without changing
  parent descriptor flags. This is not an authenticated-build/security claim or
  a change to the Python/pytest target or application dependency environments.

From the repository root, with rustup and uv already installed:

```sh
rustc --version --verbose
cargo fmt --version
cargo clippy --version
uv sync --locked --project bench/harness --python 3.12.12
uv run --locked --project bench/harness --python 3.12.12 python -c 'import sys, pytest; print(sys.version); print("pytest", pytest.__version__)'
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --workspace </dev/null
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo build --locked --release -p pt-cli
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/conformance -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/integration -v
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/corpus_inventory.py bench/corpus/manifest.toml
```

Create the harness environment before using its interpreter for Rust integration
tests (or explicitly set `PT_TEST_PYTHON` to another available Python). The Rust
process tests need only Python's standard library, not pytest. `pt exec` is a
diagnostic process launcher; `pt run` is not implemented, and there is no qualified
pytest or generation-valid full-run result. See `../crates/pt-cli/README.md`.

The separate `tests/contracts` suite checks synthetic decoded protocol/result
assertions using schemas and a test-only ledger. It does not implement the
production bridge, artifact/environment/generation verification, or WP03's real
semantic oracle. See `../tests/contracts/README.md`.

The separate [WP03 reference oracle](wp03-status.md) now observes real pytest's
same-session occurrences/phases and independently checks adverse controls,
declared effects, artifacts and coverage sets. It is test-only instrumentation,
not a production bridge or support qualification. Its README gives an explicit
source-frozen, raw-evidence-retaining command; no dependency pins are changed.

The [WP02 private interpreter preparation](../bench/corpus/interpreter/README.md)
can create two new archive-pinned prefixes and run the locked core corpus on
explicitly selected bases. It is offline, operator-requested setup, not a runtime
installer or permission to repair a managed Python. Whole-prefix equality still
does not establish host-library identity, startup handoff or immutable generations.

The optional `pt doctor --python ... --startup-profile pytest_module` (or
`pytest_console`) rejects known unreviewed startup inputs without importing them.
It is a static prerequisite inspection, **not backend launch approval**; see the
[development CLI](../crates/pt-cli/README.md) for exact bounds/exclusions.

The standalone exploratory timer now emits a post-commit lifecycle receipt in
addition to its immutable sample. Its bounded declared-file/absence checks do
not qualify pytest work or generations. The paired driver now defaults to
publication-inclusive version-2 stage receipts with retained report bytes;
explicit command-only mode remains for legacy observations. See the
[standalone](wp01-lifecycle.md) and [paired endpoint contracts](wp01-paired-lifecycle.md).
Version-2 production/inspection now also enforce [closed evidence schemas and
strict type/consistency checks](wp01-evidence-v2.md); schema acceptance is not
semantic qualification or complete WP01 acceptance.

An opt-in [cgroup resource pass](wp01-resources.md) now records whole-cgroup CPU
and charged-memory observations without changing default paired timing. The
Linux native tests may create/remove private `pt-bench-<uuid>` children under an
already delegated, owned, memory-enabled ancestor of the current cgroup, or the
explicit `PT_BENCH_CGROUP_PARENT` test setting. They do not enable controllers,
change limits, clear caches or adopt existing processes. Native peak checks skip
with the exact capability reason when `memory.peak` is unavailable; synthetic
counter checks are not kernel or PT qualification. Only an explicit diagnostic
option permits partial CPU/current observations, with peak remaining unknown.

The [paired resource-diagnostic mode](wp01-paired-resources.md) now binds those
observations to a fixed paired stage plan and preserves unsupported, failed,
skipped and uncertain outcomes in summaries. Select it explicitly with
`--timing-endpoint resource`; no existing latency sample is replayed or upgraded.
It does not qualify a native peak, frozen benchmark campaign or PT execution.

The [campaign declaration checker](wp01-manifest-checks.md) now rejects ambiguous
typed YAML and reports direct scope/serial-contract/replay/resampling conflicts
separately from structure. It is read-only, requires safe POSIX manifest lookup,
and cannot freeze or qualify a campaign. No subject command or reset script runs.

The [evidence-bound result-card tools](wp01-result-cards.md) can now produce and
independently reconstruct exploratory JSON cards from validated paired bundles.
Publish cards outside their source run. All failed/unsupported/not-run outcomes
and unresolved qualification fields remain visible; neither generator runtime
metadata nor matching sentinels establish product support or a qualified result.

The separate [managed-replay profile](wp01-managed-replay.md) now accounts for
preparation, fixed ordered interactions and required shutdown as one wall-timed,
evidence-bound unit. Capture its stdout receipt outside the run directory for
read-only historical inspection. Its fresh serial commands do not qualify daemon
reuse, reset semantics, generations or resource totals. The
[paired complete-session follow-up](wp01-paired-replay.md) now balances whole
replays and preserves failed/not-run/unknown sessions through routed inspection
and exploratory summaries. [Paired-replay result cards](wp01-replay-result-cards.md)
now recursively bind those campaigns, preserving failed/not-run/unknown sessions
and all qualification gaps through independent reconstruction. The separate
[whole-session resource mode](wp01-replay-resources.md) now covers preparation,
idle/background descendants, shutdown and driver reporting in a fresh cgroup.
Driver overhead is included; outer observer/sampler overhead is excluded from
cgroup totals. Missing peak remains unsupported unless explicitly accepted as a
partial diagnostic. [Paired whole-session resource campaigns](wp01-paired-replay-resources.md)
now schedule fresh diagnostic units and preserve unsupported/failed/not-run/unknown
sessions through routed inspection and resource-only summaries. The distinct
[resource-replay cards](wp01-replay-resource-cards.md) now bind those campaigns
offline, preserving all outcomes, missing metrics and 24 null qualification fields.
Existing latency observations are not rerun or relabelled, and steps are not
independent samples.

The separate [scenario/reset/edit validator](wp01-scenario-replay.md) now binds
explicit file reset targets, guarded edits and actual seed-bearing request-file
bytes before and after each command. Mutations require `--apply`, operate only on
declared ordinary files and stop on uncertainty without retry/rollback. Offline
inspection/comparison does not execute work. This is bounded file-domain evidence,
not environment/service/cache, loaded-code, semantic or reset-equivalence qualification.
The [paired scenario campaign](wp01-paired-scenarios.md) now freezes shared payload
bytes before execution and retains each arm's actual reset/input observations with
complete failure/unknown/not-run accounting. It remains a separate instrumented
validation profile: no latency/resource estimates or qualification upgrade.
The separate [manifest-to-scenario binding](wp01-scenario-manifest.md) now binds
the original manifest bytes to those retained outcomes offline. Matching
declarations do not resolve artifact, semantic, preregistration or reset qualifications;
no manifest/template, existing evidence or dependency pins are rewritten.

`uv sync` creates or updates the ignored `bench/harness/.venv`; it may download
the requested interpreter and locked packages into uv-managed locations. It
does not install them into system Python. Tests execute subprocesses and create
temporary files; intentional pytest failures are contained in subprocess smoke
checks. The bytecode negative control uses only its own temporary directory.

Outstanding: verify downloadable interpreter, Rust distribution, and dependency
artifacts against recorded digests; establish platform-specific environment
identity and clean materialization; configure CI and run conformance. These steps
are required before treating the environment as benchmark or support evidence.

## Deferred optimization watchlist: Serc

[Serc (`astral-experiments/serc`)](https://github.com/astral-experiments/serc) is an
experimental CPython bytecode compiler written in Rust. Track it as a possible
**opt-in environment-preparation optimization**, not a PT dependency, supported
feature or prerequisite for the real pytest backend. Upstream explicitly warns
that it may emit incorrect bytecode; its compilation benchmarks are not PT
test-runner speedup evidence.

Potential benefit is reducing `.py`-to-`.pyc` compilation during preparation or
cold imports, not module execution, pytest collection logic, fixtures or test
bodies. Runs with valid bytecode caches may gain little. Before integration,
verify compatibility with PT's exact CPython **3.12.12** pin, optimization flags,
pytest assertion rewriting, tracebacks and cache invalidation, including
same-size/same-mtime edits. Keep fresh same-session real pytest as the backend.
Any evaluation must declare matching bytecode/cache state and compilation resource
budgets for both arms, charge preparation to the relevant lifecycle and retain
failures. No integration, measured PT benefit or future uv availability is assumed.
