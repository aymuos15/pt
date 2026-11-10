# Owned serial session lifecycle foundation

**Development component**, not `pt run`, a qualified pytest launcher, a complete
coordinator or a final-result certifier. The caller explicitly supplies an exact
`ProcessRequest`, channel identity, serial contract and finite budgets. This crate
does not select/probe Python, inject/rewrite argv/environment, install packages,
suppress plugins, add collection, retry effects, certify source/environment or
recover execution from a saved trace. Ordinary user stdout/stderr remain inherited.

## What is joined

`observe_serial(request, cancelled)` owns one new private socket pair and fresh
native process launch. A concurrently owned `FrameReader` drains into a serial
ledger under a single absolute deadline. Before launch, metadata/process checks,
channel/contract bounds and the observer thread must be available; failure there
starts no work. The process supervisor consumes the child-only capability once.

- Framing/decoding/accounting faults, or clean EOF without a terminal, trip a
  **separate observer-failure flag**, not a fake SIGINT/SIGTERM. If execution is
  still live, native supervision kills/reaps the owned group. One bounded
  supervisor tick allows descriptor closure during `do_exit` to become waitable
  status before declaring a still-live control failure. This is neither a replay
  nor a promise about the unknowable precise instant of an external death.
- Channel-only completion never returns early: actual process exit and required
  group cleanup are awaited, including finalizers after valid channel EOF.
  Already-written frames are drained rather than discarded just because the
  process exited first. No unbounded raw-event queue or stdio control parsing
  exists; raw wire/output retention is not silently enabled.
- Same-reader opaque EOF, exact counters and actual documented normal exit are
  reconciled by the protocol ledger. Terminal zero cannot override an actual
  mismatch, timeout, signal, later protocol frame or incomplete reporting.
- Complete malformed data/limits/ledger contradictions are independent failure.
  Missing/truncated transport on a **known observed** timeout, interruption or
  abnormal death stays secondary incomplete evidence, not an automatically
  invented unrelated protocol failure. Raw exit/signal/cause/cleanup remain.
- A panicking observer trips the stop flag through RAII. On lost return, snapshot
  and counters remain **None/unknown**, not reconstructed as empty, passed or
  complete from a file. No failure triggers automatic second execution.

`SessionObservation` is constructed only through this live flow and is read-only
via accessors. Terminal observations are not resumable or editable. `snapshot()`
retains partial inventory/phases/reasons/not-run work. `normal_snapshot()` exists
only for `NormalExitAccounted`: **necessary channel/accounting plus actual normal
OS-return/cleanup**, not complete requested execution or successful tests. Exit
1/2/3/4/5, collect-only, fail-fast and interrupted attempts remain distinct. An
ordinary OS exit 2 can have valid accounted interruption while JUnit is incomplete.

There is deliberately **no `backend_completed`, CLI-result, environment-verified,
generation-current or full-success API**. The final-result schema requires more
than these prerequisites. Tests compose `normal_snapshot()` and the actual
process report with `pt-report` for requested JUnit publication, but artifact
completion does not certify a passing/current/full run.

## Bounds and limits

Existing protocol frame/aggregate/token/item/phase/error bounds apply. The first
bounded-frame-derived transport issue is retained; confirmed counters exclude
uncertain partial consumption. A pending frame never becomes confirmed merely
because the process ended. No producer chooses an arbitrary path or command.

Positive execution/cleanup limits and an explicit drain allowance (**at most 30
seconds**) form one initial local-monotonic window of **at most one hour**. It
never resets per frame. Reconciliation and reader join remain inside the local
diagnostic duration, not the independent harness's authoritative stopwatch. A
peer outside the supported group holding the channel open can consume the
remaining finite window; EOF is not silently inferred.

This is the supervisor's ordinary non-detached Linux group contract, not a
sandbox for hostile raw-fork/escaped descendants. Uninterruptible kernel waits,
foreign reapers, compromised loaders/hosts and interactive job control retain
their exclusions. Supported bootstrap/private-FD startup, complete installed /
host identity and immutable declared-input generation assurance are **not
provided** by an explicitly handed invocation. The env executable in real-pytest
controls is declared test setup, not a hidden supported production launcher.

## Reproduction

```sh
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --release --workspace </dev/null
```

`PT_OBSERVER_TEST_PYTHON` selects an already prepared matching minimal subject.
Tests do not install dependencies or suppress autoload. `PT_SESSION_CASE_ROOT`
optionally retains exclusive synthetic/real-pytest directories, actual process
records, partial observation details, reports and independent XML/hash/publication
probes. Synthetic transport controls are labelled, not pytest qualification.

Production dependencies are only existing local `pt-process`/`pt-protocol`.
JUnit composition uses `pt-report` as a **test dependency**, avoiding implicit
reporting/required-output policy in this layer. No new external registry identity
or dependency version is introduced.
