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

## Early-startup rejection follow-up (base c93de25)

The optional `doctor --startup-profile pytest_module|pytest_console` performs
bounded static **necessary-condition** checks without executing inspected hooks
or project code. Existing doctor remains metadata-only and `exec` remains
descriptor-free. This does not enable a runner; five startup assurances stay null.

Rust rejects explicit native loader overrides/unknown system preload input before
invoking selected Python. Its isolated probe rejects unreviewed startup/path /
warning inputs, site domains, hooks, alternative/cached shim origins and
profile-specific import shadowing. The observed uv shim is identified by source
hash, not assumed safe by name. No cache/hook is deleted or silently disabled.
Console wrapper bytes and interpreter must match; there is no module substitution.
See the [CLI bounds and trust boundary](../crates/pt-cli/README.md).

Actual startup fixtures run both installed pytest entrypoints with a test-only
framing plugin. `.pth` and PYTHONPATH sitecustomize run **before adoption** and
can leak the capability to a real exec descendant before a later valid frame.
Early abort stays nonzero with no bridge/body execution or retry. A project
`pytest.py` exits 42 in the module profile while separately requested console
execution succeeds; those are separate observations, not fallback. These controls
expose the unsafe window, not proof that detecting it qualifies arbitrary startup.

The first expanded packaging check incorrectly expected the harness environment
to pass. The guard correctly rejected coverage's `a1_coverage.pth` and existing
shim bytecode. The corrected fixture retains that rejection and uses a **separate
declared minimal environment** for positive static checks; no hook/cache was
deleted, disabled or normalized to force success. The smoke-only bytecode policy
is explicit and symmetric, not a production flag. Original ordinary-pytest and
installed-component checks remain enforced.

Initial final checks: **37 locked release Rust tests passed**, rustfmt/clippy
`-D warnings` passed, and **39 integration checks passed** (`4.097s`): six actual
startup methods, twelve static-guard controls and 21 framing checks. **55
conformance checks passed** (`28.510s`) and **68 contract/audit checks passed**
(`8.195s`). The unchanged harness's last full result is **762 tests, 761 passed /
one native-peak skip** (`858.817s`), not another startup qualification. Final
retained startup and installed-smoke results are recorded below.

The retained startup check then passed **all six actual methods** (`7.358s`) on
an explicitly selected, archive-pinned private base, preserving **ten real pytest
requests**: eight zero exits, the intended module-shadow exit **42**, and the
early-startup abort exit **1**. Evidence:
`/tmp/opencode/pt-startup-retained-s0ukqibm`. Source hashes stayed unchanged;
`qualified` and confirmatory eligibility remained false. These expected adverse
outcomes were retained, not removed from the denominator.

**Two corrected disposable packaging checks passed**, preserving the harness
startup rejection, separate minimal-profile static checks, unknown-hook refusal
without imports/suppression, unchanged ordinary pytest/pytest11 entries and the
installed framing check. The final locked release workspace rerun again passed
**37 Rust tests**. Static checks covered **five Python sources**, **21 local
links** and **six unchanged Cargo/Python/support/toolchain pin files**.
The local release binary SHA-256 is
`ab199ba90796191cb49f8c4dae218b962ff9cb4368bf9a7220704ed74a5ca51a`;
the unchanged bridge wheel remains
`69865a9add885523e2916aeeeea51b0df13acc02c7f6f245a6eb4888fa2911b4`.
These are local artifact identities, not authenticated release builds.

## Rust bridge decoder/accounting follow-up (base 61c2355)

[`pt-protocol`](../crates/pt-protocol/README.md) now supplies typed decoding for
all **18 bridge-owned revision-1 payloads**, bounded unnamed-socket framing and
a fresh-serial occurrence/attempt ledger. This is minimal M1 boundary engineering,
**not completion of WP05/WP09**. No coordinator final-result, artifact/environment /
generation certification or successful `pt run` is enabled.

The decoder rejects duplicate keys, omitted nullable fields, unknown nested
fields, unsupported versions/roles/identities, non-integer JSON and size/depth /
token faults. Framing applies absolute deadlines and explicit budgets; confirmed
counters exclude uncertain consumption. A private per-reader binding ties every
actual framed message to an opaque clean-EOF receipt: another **identical** stream
or manually decoded bytes cannot forge this by matching IDs/counts. EOF still
proves no process exit or successful work. A failed reader/ledger is never resumed.

The ledger preserves duplicate Unicode node IDs, final selected order, actual
phases/reasons/xfail/strict-XPASS data and collector arrival order. It checks
collection/error/partition barriers, applicable phases and terminal arithmetic;
retries/extensions remain unsupported. Failed, collect-only, no-tests, interrupted
and not-run outcomes remain distinct. Artifact-ready entries stay **claims**.
Normal-exit validation requires the actual process return and bound EOF; known
signals/timeouts instead retain the snapshot and independent process-owned cause.

The retained final locked release workspace run passed **79 tests**, no skips:
the prior **37** plus **42** protocol methods (eight decoding, nine actual framing,
21 serial-ledger and four native Python/schema checks). Rustfmt and clippy
`-D warnings` passed. Sources stayed fixed in
`/tmp/opencode/pt-protocol-verification-gd_rg6cl`, alongside actual command returns
and complete raw logs. Native controls exercised all 18 Python `_wire` shapes,
intentional synthetic failed work, effect-before-exit-17, truncation and actual
supervisor timeout/cleanup. Synthetic payloads are **not pytest qualification**.

The independent Python/jsonschema control and Rust decoder agreed on **2,372
schema/wire-shape mutations: 42 accepted / 2,330 rejected**. Separate retained
read-back is `/tmp/opencode/pt-protocol-schema-controls-s299kn7n`. All **37 prior
Cargo package identities/checksums** remain unchanged; only local `pt-protocol`
is added, with the pinned serde_json `raw_value` feature enabled. Four existing
Python/support/toolchain pin files also remain unchanged. This is dependency
identity evidence, not a vulnerability audit.

**39 integration checks passed** (`4.040s`) and **68 contract/audit checks passed**
(`8.783s`). The full independent harness was not needlessly rerun; its unchanged
last result remains **762 tests: 761 passed / one native-peak skip**. Installed
bridge behavior was not changed. The first expanded native build used a test
helper's incorrect `cleanup_grace` field instead of `cleanup_timeout`; compilation
stopped before the new process checks ran. The corrected helper and final checks
above do not change process policy or conceal a project-test retry.

The actual observer, supported launch boundary, required artifacts/environment,
immutable generations, broader backend and independent release gates stay open.

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
  session integration and coordinator-owned catalog/final-result handling remain unimplemented. Process-only
  results cannot be labelled complete generation-valid test results.
  WP00 now specifies the 32-kind revision-1 catalog and final-result/accounting
  schemas with synthetic tests (`protocol-draft.md`, `tests/contracts`); those
  checks do not implement this production boundary or its external verification.
- The release-profile binary can be built locally, but authenticated builds,
  installable release artifacts, CI/platform qualification, independent review,
  resource accounting, and overhead qualification remain open. No measured speed
  or release-confirmatory claim is made.
