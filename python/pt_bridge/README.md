# Explicit development bridge (WP04/WP05)

Local development package `pt-bridge==0.0.0`, module `pt_bridge`. Explicit
observational pytest hooks now exist, but there is **no integrated coordinator
backend or full-result certification**. It has no
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

## Explicit same-session observer

Only `-p pt_bridge.pytest_observer` loads the hook module. Importing `pt_bridge`
or installing the wheel does not load pytest or register a plugin. The observer
wraps pytest's existing collection/run/finalization hooks; it does not call a
second collection, replace the run loop, schedule, select, reorder or retry work.
Ordinary pytest/plugin configuration and argument boundaries remain authoritative.

The caller must already own a private socket and supply **explicit**
`PT_BRIDGE_CONTROL` JSON, not stdout control lines or a named listener. This is
a development component configuration, not a supported standalone launcher:

```json
{
  "schema_version": 1,
  "fd": 3,
  "identity": {"request_id":"r1","run_id":"r1","generation_id":"g1","session_id":"s1","producer_id":"b1"},
  "invocation_profile":"pytest_module",
  "mode":"run",
  "max_items":256,
  "max_collection_reports":1024,
  "max_nodeid_bytes":1048576,
  "byte_budget":8388608,
  "event_budget":25000,
  "timeout_seconds":30
}
```

Every key is required; unknown/duplicate keys and coerced boolean/floating counts
fail. Configuration is capped at 8 KiB. The exact revision-1 target tuple is checked
and an owned non-stdio socket is adopted at explicit module import, before normal
conftest/test imports in the exercised launch paths. One local absolute deadline
is fixed for the observer's whole lifetime; it is not reset for each event.
`pytest_console` and `pytest_module`, and `run` and `collect_only`, stay distinct.
The bootstrap's profile is a coordinator-owned request fact, **not independent
proof of invocation or environment identity**. Missing configuration does not
create a socket, silently install anything or choose an alternative invocation.

### Opt-in required JUnit readiness (bootstrap schema 2)

Bootstrap **schema 1 remains closed and unchanged**: it does not discover, read
or claim reports. Explicit **bootstrap schema 2** requires all the same keys,
with `schema_version: 2` and exactly one additional key:

```json
"junit_artifact": {
  "artifact_id": "junit",
  "source": "requested.xml",
  "max_bytes": 1048576,
  "required": true
}
```

This is a configuration version, **not protocol version 2**. Wire envelopes
remain **protocol 0 / contract revision 1** and use the already specified
`artifact_ready` kind. It is also separate from the independent oracle's trace
version 2. Optional/coverage/arbitrary report discovery is not implemented by
this bootstrap. False/unknown/nonboolean `required`, extra fields, aliases,
traversal and coerced byte limits are rejected, not repaired.

The caller must explicitly request pytest's JUnit output as usual. At session
start the bridge requires the actual enabled pinned pytest formatter and its
exact effective destination to match the declaration. It never enables a
disabled plugin, changes options/family/properties/capture, redirects output or
reruns a request. A missing/different formatter is unsupported; earlier ordinary
startup/plugin effects are not pretended absent.

The declared source is canonical relative to the actual cwd: at most **4,096
UTF-8 bytes / 24 components**. Root/ancestor directories are pinned through
no-follow native operations, with non-inheritable descriptors. After underlying
unconfigure hooks and the pinned Config cleanup stack finish, the bridge reads
only that exact declared file in
**64 KiB chunks**, under its original absolute deadline, with a positive byte
ceiling of **at most 128 MiB**. File type, owner, single link, non-other-writable
mode, length, open/named bindings and before/after mutation stamps are checked.
Root/parent substitution fails; symlinks, directories, FIFOs and hardlinks are not
followed as output. No content/permission changes, file creation, cache deletion,
path repair or arbitrary object serialization occurs. In particular, an unsafe
umask/output mode is not fixed silently. Tests prepare only their own new output
files as 0600; a production output-preparation policy is not supplied here.

The resulting ID/length/SHA-256/complete value is **producer readiness only**,
not a trusted artifact commit, XML completeness, actual work or environment /
generation certificate. Ordinary interrupted reports assert partial readiness.
Read failures retain a session infrastructure error and incomplete reporting;
they do not change pytest's actual raw return into a fabricated complete report.
The coordinator still needs actual process return/cleanup and independent native
copy/hash/JUnit-context checks. Unsupported report data stays intact and can
fail that independent adapter even when producer hash/readiness agree.

The extra hashing/read/validation is real explicitly requested work, not free
preparation or a benchmark speedup. Endpoint metadata/hashes do not exclude all
transient changes. Uninterruptible kernel I/O, hostile same-process/FUSE/device
behavior, raw-fork leakage, early site/loader initialization and complete immutable
input domains retain their separate exclusions/gates.

Observed collector reports, duplicate-preserving Item objects, final selected /
deselected order and phase reports are emitted on the dedicated bounded channel.
Ordinary custom collectors and dynamically loaded plugins are not disabled.
Repeated live Item objects, newly injected unobserved Items, parallel/retry report
adapters, extra/missing/reordered phases and metadata requiring unknown custom
representations are explicit unsupported cases. Node IDs remain exact strings;
arbitrary parameter `repr` is not requested for metadata. Limits fail visibly,
never trim work or trigger an automatic replay.

Failure reasons use supported already-rendered pytest strings/crash fields.
Warnings with an ordinary one-string exception representation are observed
without invoking project-defined `str`/`repr`. Pytest's deferred runtest warning
delivery is labelled `when: finalize`: **delivery at protocol finalization, not
an invented originating setup/call/teardown phase**. Original warning filters and
warnings-as-errors behavior remain in pytest. Rich capture/exception artifact
references and arbitrary custom warning/report representations need separate
adapters; raw pytest diagnostics still go to ordinary stdout/stderr.

The terminal records observed attempts/phases, explicit collect-only/fail-fast /
collection-failed/interrupted not-run reasons and backend exit claims. Missing
session returns (including early help/usage paths) are not fabricated. The Rust
reader independently reconciles actual frames, EOF and the actual process return.
An outer `pytest_unconfigure` wrapper is visibly unsupported for a
reporting-complete assertion; it still runs rather than being suppressed. A
valid terminal cannot waive later actual process/required cleanup verification.

Neither these hooks nor the static startup inspection qualify arbitrary `.pth`,
sitecustomize, native-loader initialization or earlier private-FD exposure. They
do not verify required artifact commits, complete installed/host environments,
immutable source generations or current full success. The packaging smoke and
source-level reference controls are finite development evidence only; **`pt run`
remains unavailable**. See [WP05 progress and open gates](../../docs/wp05-status.md).

### Config cleanup is part of the observed finalization boundary

Pinned pytest runs `Config.add_cleanup` callbacks **after** `pytest_unconfigure`.
The observer therefore defers readiness/terminal emission until the original
Config `ExitStack` drains. The CPython 3.12.12 / pytest 8.4.2 adapter registers one
new non-suppressing exit callback and moves **only that new observer entry** below
the original entries. Existing pytest/user callback order, callbacks registered
during cleanup, and exception/suppression semantics stay owned by the original
stack. No user callback is inspected, called early, removed, disabled or replayed.

An unsuppressed cleanup exception produces an infrastructure diagnostic and
incomplete reporting/partial readiness; the original exception still propagates.
A missing/replaced/transferred or undrained boundary cannot supply completion.
In particular, a zero/complete-looking JUnit file cannot recover a lost terminal;
the native observer may stop a still-live process on that channel fault.

This is a pinned **private-internals adapter**, not support for arbitrary Config /
ExitStack replacements or plugin introspection of PT's callbacks. Unknown types
are refused. It observes Config cleanup, **not all interpreter `atexit`, native
library, external-service or detached-process finalization**. Actual process
return/EOF, required cleanup, independent artifact checks and all environment /
generation/release gates remain mandatory. Ordinary pytest still does not load
the bridge; both bootstrap versions use the same deferred boundary.

### Preserving interpreter inputs during setup reproduction

`PYTHONDONTWRITEBYTECODE=1` is **not** sufficient for setup tools that invoke
isolated Python: `-I` ignores that variable. A retained post-setup identity check
found extra/changed bytecode in one private base despite passing component tests;
the input was not repaired or silently rebaselined. See the
[failure and reproduction record](../../docs/wp09-status.md).

For the explicit Linux correctness/setup reproduction, use
`tests/packaging/readonly_interpreter_setup.py --execute --prefix ABSOLUTE_PREFIX
... -- COMMAND ...` with already prepared, independently expected temporary
prefixes. It creates only a child user/private mount view and requires distinct
namespace descriptors before its read-only binds. The
`tests/packaging/verify_declared_junit.py --execute --output NEW_ABSOLUTE_DIRECTORY
--prefix-one PREFIX_A --prefix-two PREFIX_B --manifest ARCHIVE_MANIFEST
--manifest-sha256 PRIOR_SHA256` driver requires those input views already read-only,
prepares a new native subject and checks prefix bytes again after the complete
setup/test/wheel sequence. Both wrappers are explicit test tooling, **not `pt run`,
host mutation, immutable snapshots, a sandbox or release qualification**. Failed
and unknown returns are retained; no existing environment or result is repaired,
resumed, adopted or retried automatically.
