# Development environment — provisional

These are reproducibility choices for developing the current prototype, not a
qualified PT support matrix or proof of artifact provenance. WP00 remains
unreviewed. The initial product profile under consideration is Linux x86-64,
GIL-enabled CPython 3.12.12 and pytest 8.4.2.

- `rust-toolchain.toml` selects Rust **1.99.1** with rustfmt and clippy. With
  rustup installed, invoking Rust tools from the repository may download this
  toolchain into the user's rustup installation. An initial Linux x86-64 check
  observed rustc commit `58cf8f9c35b355199727627d07ae34a4e2846d67`; this is not
  a verified distribution-artifact digest. No Rust workspace exists yet.
- The independent harness uses CPython **3.12.12** for the initial development
  check and pytest **8.4.2** for its controlled corpus smoke tests. Its Python
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
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/corpus_inventory.py bench/corpus/manifest.toml
```

`uv sync` creates or updates the ignored `bench/harness/.venv`; it may download
the requested interpreter and locked packages into uv-managed locations. It
does not install them into system Python. Tests execute subprocesses and create
temporary files; intentional pytest failures are contained in subprocess smoke
checks. The bytecode negative control uses only its own temporary directory.

Outstanding: verify downloadable interpreter, Rust distribution, and dependency
artifacts against recorded digests; establish platform-specific environment
identity and clean materialization; configure CI and run conformance. These steps
are required before treating the environment as benchmark or support evidence.
