# Bounded bridge-channel foundation

Development-only **protocol 0 / contract revision 1** necessary-condition checks.
This crate is not a complete runner, result certifier, supported launcher or WP09
acceptance. It neither imports Python nor depends on the independent test oracle.
There is deliberately **no full-success API**. `pt run` remains unavailable.

## Layers and ownership

- `decode_bridge(raw, identity)` accepts only the 18 bridge-owned closed payloads
  in the [revision-1 schema](../../docs/protocol-v0.schema.json), including required
  nullable fields, nested terminal counts, exact handshake versions, integer-only
  numbers, Unicode text and artifact-ID bounds. Duplicate keys, unknown fields,
  invalid UTF-8/surrogates and coordinator-owned kinds fail. Raw bytes are retained
  without normalization. Decoding does not prove a message came from any socket.
- Linux `FrameReader` owns one unnamed connected Unix socket-pair endpoint. It
  normalizes blocking mode, enforces nonzero big-endian framing, explicit event /
  wire-byte budgets, absolute local `Instant` deadlines and contiguous sequence.
  It reads one frame at a time; no unbounded queue, stdio parsing, redelivery,
  automatic replay or reattachment exists. Reading, decoding or budget faults
  permanently poison it. Confirmed counters omit uncertain partial consumption.
- `StreamEnd` is opaque evidence of **actually read clean EOF**, not a terminal
  event or process result. Every framed message and its EOF share a private
  per-reader binding. Even an identical second stream's identity/count/size cannot
  satisfy the first ledger. Publicly decoded/unframed messages can exercise a
  ledger but cannot satisfy its normal-exit gate. Mixed streams fail permanently.
- `SerialLedger` receives explicit coordinator-owned invocation/mode/limits and
  declared artifact IDs. It checks handshake, raw collector/error correspondence,
  duplicate-preserving ordinal inventory, disjoint exhaustive selection chunks,
  the backend's final selection order, one serial attempt, applicable phase order,
  explicit not-run reasons and exact terminal arithmetic. It cannot enable
  retries, extensions, scheduling, lease reuse or any optimization.
- `snapshot()` retains partial observed inventory, exact phases/reasons/xfail /
  strict-XPASS data, interruptions, error details, not-run reasons and artifact
  readiness **claims**. Collector report/error arrival order is preserved; attempt
  and not-run observations are exposed in selected order, with raw frames remaining
  the source for exact event interleaving. Collection absence means unknown/not
  observed, not a verified empty suite.
- `validate_normal_exit(eof, actual_code)` checks that every frame was consumed
  from that actual reader, a matching terminal was received, reporting is claimed
  complete, and documented pytest exits have consistent failure/work context.
  Collect-only, no-tests and failed/fail-fast sessions stay distinguishable. A
  normal exit of one cannot excuse missing phases/work. Signals/timeouts instead
  retain `snapshot()` and the independent process-owned cause; they do not need a
  fabricated terminal, a replay or an independent protocol-failure explanation.

`Ok(snapshot)` still does **not** verify work truth, process cleanup, required
artifact bytes/commit, installed environments, source scope or current immutable
generations. The caller must actually observe the process return; a saved trace,
JUnit or complete-looking artifact cannot recover a lost return. Readiness is
never publication. The API has no current/full-success, artifact-committed or
environment-verified field. No signal/timeout can be upgraded by a later zero.

The later [`pt-session`](../pt-session/README.md) layer owns concurrent reader /
ledger/process lifetimes. `ProtocolError::kind()` distinguishes complete invalid
data/limits from truncation, deadline, I/O or closed-reader faults, so known
timeout/death incompleteness need not invent an unrelated corruption cause.
`terminal_observed()` reports presence only, without cloning the snapshot or
certifying completion. No wire-version/catalog/support claim is changed.

## Finite ceilings

1 MiB/frame; 64 MiB total **wire bytes including four-byte headers**; one million
events; JSON container depth 32 and 65,536 lexical tokens; at most 65,536 Unicode
characters per contract text field. The frame/token bounds apply even when an
individual catalog array permits more elements. Typed counts fit uint64; attempts
fit the revision-1 0–31 shape but this ledger permits **only attempt zero**.

The caller chooses positive bounds no larger than 100,000 item occurrences /
collector reports and 16 MiB aggregate item-node-ID UTF-8 bytes. Artifacts and
combined collection/session error summaries are capped at 1,024; each selection
chunk permits 4,096 unique ordinals. Bounds fail visibly, never trim the inventory
or restart already-started work. Retained decoded objects have finite per-field,
event and aggregate bounds; these are not measured native peak-memory guarantees.

The raw socket endpoint and request identity come from the coordinator, not a
message's role field. This does not sandbox project code, prevent raw-fork FD
inheritance, qualify Python's pre-adoption startup window or supply IPC role
authentication against code in the same process. See [startup evidence and open
gates](../../docs/wp04-status.md) and the [protocol contract](../../docs/protocol-draft.md).

## Reproduction and test boundaries

From the repository root, with the explicitly prepared locked harness interpreter:

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --release --workspace </dev/null
```

Tests cover all bridge payloads, missing nullable/duplicate/nested fields, malformed
and bounded JSON, actual fragmented sockets, deadlines, truncation, budget and
sequence faults, no recovery, selected-order/duplicate inventory, setup skips /
failures, teardown failure, strict/non-strict XPASS, fail-fast, collect-only,
collection errors, interruption, missing terminal, contradictory exits, EOF
provenance and finite retention. An independent pinned Python/jsonschema control
constructs thousands of schema/wire-shape adversaries; it is a **test dependency**,
not production validation. Native process tests exercise actual `_wire` bytes,
all 18 shapes, failed synthetic work and effect-before-death/truncation/timeout.
Those synthetic payloads are not real-pytest or ecosystem qualification.

The separate `tests/real_pytest.rs` now also feeds the explicitly loaded
[development observer](../../python/pt_bridge/README.md) through actual native
supervision/frames/ledger checks. Its small same-session, mode, failure and death
fixtures remain finite component controls, not an integrated supported launcher.
Optionally set `PT_OBSERVER_TEST_PYTHON` to an already prepared matching minimal
environment; the native test itself does not install packages or disable plugins.

No external dependency version is changed. `serde_json`'s pinned `raw_value`
feature is enabled to avoid erasing duplicate fields before typed decoding. The
new crate uses existing pinned serde/serde_json; dev-only supervisor/tempfile
dependencies supply bounded real-process tests. No benchmark or speedup is inferred.
