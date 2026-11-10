# Bridge distribution skeleton (WP04)

Local development package `pt-bridge==0.0.0`, module `pt_bridge`. There are **no
pytest hooks, execution backend, or complete session protocol yet**. It has no
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

## Private framing component, not a pytest plugin

The explicitly imported `pt_bridge._wire` module now provides `ControlStream`
over an owned connected Unix stream socket. `take_fd` consumes a declared socket
descriptor >=3 and marks it non-inheritable; it never adopts stdin/stdout/stderr
or alters an ordinary file supplied by mistake. There is no named listener,
global registration, pytest import, project collection or execution loop.

The component implements 32-bit big-endian nonzero framing, **1 MiB per frame**,
explicit positive event/byte budgets (at most one million events / 64 MiB wire
bytes including headers), strict UTF-8/integer-only JSON, closed revision-1
bridge envelopes, channel-bound opaque IDs and contiguous zero-based sequence.
Only bridge-origin kinds are accepted; a coordinator role/event cannot be
smuggled through that channel. JSON containers/tokens are bounded before generic
decoding (**depth 32 / 65,536 nodes**), and aggregate encoded size is checked
before serialization. Unicode IDs/strings are preserved; unknown Python objects
are rejected without calling their project `repr`.

Every send/receive requires a finite **absolute local-monotonic deadline**.
Partial reads do not reset it. Truncation, invalid frames, budget exhaustion,
closed peers and backpressure fail the stream permanently; no automatic retry,
redelivery recovery or reattachment occurs. Confirmed counters exclude uncertain
partial bytes/effects; zero confirmed messages is not proof nothing was sent.
An EOF is just EOF, **not successful terminal accounting**.

These are framing/envelope primitives, **not validation of all payload catalog
shapes, handshake truth, same-session item/phase arithmetic, producer honesty,
required artifacts/environment, cleanup or generation assurance**. Those remain
independent mandatory production gates. This is not a replacement for the
independent real-pytest oracle or a claim of supported plugin/session semantics.
Decoded data and process results must never be promoted to full test success.

`take_fd` assumes an explicitly owned descriptor in the supported bootstrap; it
is not a hostile-FD/thread/OS security boundary. Early `.pth`/site/custom/native
startup may precede this call and still requires qualification in the actual
launcher. Marking the descriptor here does not justify suppressing those hooks,
changing normal pytest entrypoint semantics, or claiming raw-fork isolation.

Component checks, separate from actual pytest conformance:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/integration -v
```

The packaging smoke also explicitly exercises the **installed** framing module
in its disposable venv, without importing pytest, while ordinary pytest still
runs without any PT auto-plugin. Native supervisor tests separately hand the
actual inherited socket to the source component and check its wire bytes and
non-inheritability before a test-owned project sentinel. Neither is a complete
production backend/transport qualification or overhead measurement.
