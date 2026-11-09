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

`uv sync` creates or updates the ignored `bench/harness/.venv`; it may download
the requested interpreter and locked packages into uv-managed locations. It
does not install them into system Python. Tests execute subprocesses and create
temporary files; intentional pytest failures are contained in subprocess smoke
checks. The bytecode negative control uses only its own temporary directory.

Outstanding: verify downloadable interpreter, Rust distribution, and dependency
artifacts against recorded digests; establish platform-specific environment
identity and clean materialization; configure CI and run conformance. These steps
are required before treating the environment as benchmark or support evidence.
