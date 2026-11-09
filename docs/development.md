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

`uv sync` creates or updates the ignored `bench/harness/.venv`; it may download
the requested interpreter and locked packages into uv-managed locations. It
does not install them into system Python. Tests execute subprocesses and create
temporary files; intentional pytest failures are contained in subprocess smoke
checks. The bytecode negative control uses only its own temporary directory.

Outstanding: verify downloadable interpreter, Rust distribution, and dependency
artifacts against recorded digests; establish platform-specific environment
identity and clean materialization; configure CI and run conformance. These steps
are required before treating the environment as benchmark or support evidence.
