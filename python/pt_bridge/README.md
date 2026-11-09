# Bridge distribution skeleton (WP04)

Local development package `pt-bridge==0.0.0`, module `pt_bridge`. There are **no
pytest hooks, execution backend, or protocol implementation yet**. It has no
`pytest11` entry point and does not replace/shadow a package called `pytest`.
Installing it is an explicit operator action, never something `pt exec` or
`pt doctor` does. The selected development target is exactly CPython 3.12.12
and pytest 8.4.2; that is not conformance qualification.

Build a wheel outside the source tree, then explicitly check its installation
in a disposable environment (requires the documented uv cache/setup):

```sh
cargo build --locked --release -p pt-cli
uv build --python 3.12.12 --wheel --out-dir /tmp/opencode/pt-bridge-wheels python/pt_bridge
uv run --locked --project bench/harness --python 3.12.12 python tests/packaging/check_bridge_install.py --wheel /tmp/opencode/pt-bridge-wheels/pt_bridge-0.0.0-py3-none-any.whl
```

The hatchling version is pinned, but independent build/provenance qualification
is not established. Installation checks compare ordinary pytest before/after,
verify no auto-plugin registration, and exercise `pt doctor`. They do not import
PT's benchmark harness into measured workers or establish WP03/WP05 conformance.
