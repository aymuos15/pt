# WP04 progress and evidence

2026-11-10: **partial, development-only**. The Rust process boundary now exists;
WP04 and M1 are not declared complete. No PT pytest backend or qualified support
profile exists. The baseline choices are in `baseline-contract-v1.md`.

## Implemented and checked

- `crates/pt-process`: direct argv launch, fresh Linux process group, inherited
  environment and non-terminal standard input/output, timeout/cancellation,
  bounded group cleanup, direct-child reaping, raw exit/signal and typed outcomes.
- `crates/pt-cli`: explicit diagnostic `pt exec`, no-daemon/no-cache/no-preload
  by construction, exact argument boundaries, optional no-overwrite reports,
  SIGINT/SIGTERM handling. Publication failure cannot become process success.
- `pt doctor --python <absolute-venv-python>`: explicit isolated metadata check
  of the selected versions and absence of a bridge auto-plugin. The private
  bounded reply must agree with the process status; `/bin/true` is not accepted
  as an interpreter/profile just because it returns zero. No project modules,
  site initialization, `.pth` code, or ordinary pytest runtime are imported by
  this check. It is **not** runtime import-graph/environment qualification.
- `python/pt_bridge`: installable local package skeleton, without a `pytest11`
  entry point or a replacement package named pytest. No observer/hooks yet; the
  separate `_wire` module now provides private framing/envelope primitives only.

## Private-channel foundation follow-up

The native library can now create a connected Unix socket pair and consume a
single-launch child capability at fd 3. It uses explicitly pinned **command-fds
0.3.3** and keeps the workspace's unsafe-code prohibition. Mapping occurs only
in the child, not by toggling parent-wide inheritance flags. Dropping `Command`
immediately after spawn releases the parent's duplicate, permitting genuine EOF
before the leader exits. Existing `supervise` / `pt exec` remain descriptor-free.
No argv, environment, stdio, plugin policy, dependency environment or retry
behavior is silently rewritten.

The independent Python framing component enforces length/UTF-8/JSON/depth/node /
aggregate bounds, explicit budgets, bridge-only closed envelopes, bound IDs,
sequence and absolute I/O deadlines. Uncertain partial I/O cannot be retried or
inferred complete. It does **not** validate all payload shapes/session arithmetic
or turn EOF into a verdict. Final checks are recorded below; neither the native
nor Python component tests qualify a complete protocol or backend.

The actual supervisor-to-source-component fixture checks wire bytes and the
descriptor's non-inheritability before a test-owned project import. Packaging
additionally checks the installed component without importing pytest. **Earlier
interpreter startup remains an explicit gate**: `.pth`, sitecustomize, PYTHONPATH
or native startup can precede an explicitly loaded plugin. Nothing here proves
their safety, suppresses them or changes entrypoint semantics to hide the issue.
The supported launcher must qualify that startup path before a backend claim.
Raw-fork inheritance and hostile/detached code remain outside close-on-exec.

This advances WP04's process/packaging boundary; it is not WP05 or complete WP09.
`pt run` remains unavailable, and the original strict full-success gates remain.

Rust tests cover fresh PIDs/Python state, cwd, empty/unicode/non-UTF-8 arguments,
binary I/O, large output, inherited environment, nonzero/signal exits, ordinary
descendants after success and timeout, cancellation/escalation, PTY input
rejection, missing executables, and competing/replaced report files. The
packaging smoke check runs ordinary pytest before/after installation and checks
missing/wrong metadata, auto-plugin rejection, and project/site import sentinels.

Reproduction (see `development.md` for prerequisite setup):

```sh
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --workspace </dev/null
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo build --locked --release -p pt-cli
uv build --python 3.12.12 --wheel --out-dir /tmp/opencode/pt-bridge-wheels python/pt_bridge
uv run --locked --project bench/harness --python 3.12.12 python tests/packaging/check_bridge_install.py --wheel /tmp/opencode/pt-bridge-wheels/pt_bridge-0.0.0-py3-none-any.whl
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
```

## Local verification at code revision a4ecbd5

On the selected Linux development host, `cargo test --locked --release
--workspace` passed **28 Rust tests**; rustfmt and clippy (`-D warnings`) passed.
The independent Python harness passed **154 tests** with ResourceWarning treated
as an error. Two repeated disposable packaging checks passed with `qualified:
false`, including unchanged ordinary-pytest auto-plugin entries before/after.
A direct release-binary smoke test produced two distinct fresh PIDs and complete
process cleanup. These are functional/development checks, not PT conformance or
benchmark evidence. Observed local artifact hashes (not authenticated builds):

- `target/release/pt`: `df1ff5542e40e5f9f9aa0b1990bc36f6b3ce46fe1a9036023c5443936ce66b10`.
- Bridge wheel: `af4efd67543bdcb5370ecb0b1f34d816b7a996c4d9242cf5cff2ed866db5243f`.

## Failure retained and corrected

The initial packaging wrong-version negative control wrote installed METADATA
in-place. uv's hard-link materialization shared that inode with its cache; a
subsequent clean install correctly failed with `Wheel version does not match
filename (9.9.9 != 0.0.0)`. This was a test-isolation bug, not silently waived
qualification. The test now sets `UV_LINK_MODE=copy`, atomically replaces only
the test-owned installed file, and verifies it has a single link before using
the corrupted metadata. Only the cache METADATA entry created from this local
wheel was restored, and its bytes checked against the original wheel archive.
Repeated clean disposable installations were then rerun. No user environment or
unrelated cache was reset; no performance/corpus result is inferred from this.

## Final private-channel verification (base a44feab)

- **35 Rust tests passed**, including the locked release workspace run:
  `PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --release --workspace </dev/null`.
  This includes seven new native channel/component controls, not seven new pytest
  conformance cases. Rustfmt, clippy with `-D warnings` and the locked CLI release
  build passed.
- **21 Python framing component checks passed** (`0.277s`), including malformed /
  truncated frames, duplicate keys, identity/role spoofing, lost sequences, bounds,
  absolute deadlines, closed peers, real backpressure and permanent no-retry faults.
- **Two disposable installed-wheel smoke checks passed**, both with `qualified:
  false`. Ordinary pytest behavior and pytest11 entries remained unchanged; the
  installed framing component was explicitly exercised without importing pytest.
- **735 harness tests ran: 734 passed / one existing native-peak capability skip**
  (`850.899s`). **55 conformance checks passed** (`29.127s`) and **68 contract/audit
  checks passed** (`8.305s`). These completed suites are retained development
  regressions, not qualified native peak accounting or release measurements.
- Static checks covered Python 3.12 grammar and **67 local links**. All **32
  pre-existing locked Cargo package identities remain unchanged**. Additions are
  exactly `command-fds 0.3.3`, `nix 0.31.3`, `syn 3.0.10`, `thiserror 2.0.21` and
  `thiserror-impl 2.0.21`; the prior `nix 0.30.1` is retained. The command-fds
  registry checksum matches
  `1b60b5124979fccd9addd89d8b97a1d6eebb4950694520c75ddd722535ea443f`.
  Harness/bridge Python dependencies, support matrix and Rust toolchain pins are
  unchanged. This dependency-identity check is not a vulnerability/security audit.

Observed local artifacts, **not authenticated release builds**:

- `target/release/pt` SHA-256:
  `9ac70ed65a5273b148d796e21e57b9ad56e8a85d0975200e925f3dadbe23db4a`.
- Offline-built `pt_bridge-0.0.0-py3-none-any.whl` SHA-256:
  `69865a9add885523e2916aeeeea51b0df13acc02c7f6f245a6eb4888fa2911b4`.
  The local wheel is retained at `/tmp/opencode/pt-wire-build-k8q_6eyg`.

Production framing remains **protocol 0 / contract revision 1**, distinct from
the independent test oracle's **reference trace version 2**. Framing acceptance
does not resolve startup, complete payload/session validation, artifact/environment
identity, immutable generations or any backend/release gate below.

## Open gates

- Interactive stdin is refused before work; inherited descriptors alone do not
  implement terminal foreground job control. Detached/hostile descendants,
  coordinator SIGKILL recovery, restrictive procfs, foreign child reapers, and
  uninterruptible kernel waits retain explicit limits (`pt-process/README.md`).
- No implicit interpreter substitution, auto-installation, or `pt run` fallback.
  Actual pytest entrypoint/profile enforcement and bridge compatibility must be
  integrated with the same-session backend, not inferred from `doctor` output.
- WP01/WP02 acceptance remains incomplete. [WP03's bounded reference oracle](wp03-status.md)
  now observes real same-session occurrences/phases and exercises independent
  broken controls, but its qualified corpus/environment/ecosystem acceptance
  remains open. WP05 cannot claim parity from JUnit, phase equality alone or
  limited training coverage comparisons.
- Required work/artifact/generation accounting, complete production bridge IPC /
  session integration and full protocol catalog/fault handling remain unimplemented. Process-only
  results cannot be labelled complete generation-valid test results.
  WP00 now specifies the 32-kind revision-1 catalog and final-result/accounting
  schemas with synthetic tests (`protocol-draft.md`, `tests/contracts`); those
  checks do not implement this production boundary or its external verification.
- The release-profile binary can be built locally, but authenticated builds,
  installable release artifacts, CI/platform qualification, independent review,
  resource accounting, and overhead qualification remain open. No measured speed
  or release-confirmatory claim is made.
