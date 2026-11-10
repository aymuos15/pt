# PT — Incremental Python Test Engine

PT is a proposed local-first test execution coordinator. The design uses a Rust
control plane and fresh Python sessions running real pytest; it does not replace
pytest's semantics. Correctness and independent measurement come before speed.

## Status

The project is in early development. A Linux-only Rust process supervisor and
diagnostic `pt exec` command now exist. There is **no PT pytest backend, qualified
support profile, complete benchmark harness, or measured performance claim yet**. The
specification is a design proposal, not evidence of implementation or support.
An explicit metadata-only `pt doctor` and bridge distribution skeleton are also
available; neither observes or executes pytest test sessions. The
private-socket handoff and bridge framing primitives are also implemented as
development components. A [bounded Rust bridge decoder and serial ledger](crates/pt-protocol/README.md)
now check necessary stream/accounting conditions, not a complete backend or
artifact/environment/generation certification. The initial
supervisor rejects terminal stdin until foreground job control is qualified.
Most proposed product commands, including `pt run`, are not implemented yet.
WP00's conservative contract/threat-model engineering self-review is complete;
this does not qualify a runner or close the later work-package/release gates.

## Start here

- [Implementation specification](docs/pt-implementation-spec.md): contracts,
  architecture, benchmark protocol, and dependency-ordered work packages.
- [Agent instructions](AGENTS.md): repository-wide working rules.
- [First task](docs/first-agent-task.md): the original, historical WP00 handoff.
- [Execution contracts](docs/contracts.md): the reviewed conservative definition,
  not implementation or qualified support.
- [Selected target matrix](support-matrix.toml), [protocol](docs/protocol-draft.md),
  [threat model](docs/threat-model.md), [benchmark charter](docs/benchmark-charter.md),
  and [architecture decisions](docs/adr/README.md): WP00 self-reviewed baseline
  definitions, with implementation/qualification gates still open.
- [WP00 acceptance register](docs/wp00-review.md): resolved review decisions,
  bounded evidence, and explicit remaining gates.
- [Protocol/result contract tests](tests/contracts/README.md): synthetic WP00
  accounting and failure checks; not a bridge, semantic oracle or qualification.
- [Baseline contract v1](docs/baseline-contract-v1.md): self-reviewed process,
  exit, transport, and target decisions for WP04; not support qualification.
- [Development environment](docs/development.md): provisional toolchain pins
  and reproducible prototype checks.
- [Invariant review map](docs/invariant-review.md): adverse evidence still
  required for C01–C12.
- [Capability policy](docs/capability-policy.md): reviewed transformation
  permissions and conservative fallbacks, not implementation evidence.
- [Exploratory harness prototype](bench/harness/README.md) and
  [initial corpus probes](bench/corpus/README.md): incomplete WP01/WP02 work.
- [WP02 serial-core corpus progress](docs/wp02-status.md): explicit test-owned
  inputs and two clean locked materializations, not representative/oracle qualification.
- [WP03 reference oracle progress](docs/wp03-status.md): same-session occurrence /
  phase traces, independent broken controls and coverage/artifact checks; no PT qualification.
- [WP01 timing evidence and open prerequisites](docs/wp01-status.md): observed
  stage boundaries, negative controls, and explicit endpoint exclusions.
- [Publication-inclusive observation endpoint](docs/wp01-lifecycle.md): committed
  samples, post-commit receipts and bounded declared-finalization checks, not PT qualification.
- [Paired lifecycle integration](docs/wp01-paired-lifecycle.md): version-2 receipts,
  retained report bytes, abort accounting and endpoint-specific analysis.
- [Version-2 evidence validation](docs/wp01-evidence-v2.md): closed plan/sample/receipt
  schemas and malformed-record controls, not completion of WP01 or the runner.
- [Whole-cgroup resource observations](docs/wp01-resources.md): opt-in CPU/charged-memory
  diagnostics, background-work controls and explicit unsupported peak accounting.
- [Paired resource campaigns](docs/wp01-paired-resources.md): bound stage observations,
  unsupported/failed/not-run denominators and resource-only summaries, not latency claims.
- [Campaign declaration checks](docs/wp01-manifest-checks.md): strict input types and
  bounded scope/contract/unit contradictions, not artifact or semantic qualification.
- [Evidence-bound result cards](docs/wp01-result-cards.md): reconstructible exploratory
  reports retaining all planned outcomes and unresolved qualification fields.
- [Managed session replay](docs/wp01-managed-replay.md): preparation, ordered
  interactions and required shutdown bound as one unqualified session unit.
- [Paired complete-session replay](docs/wp01-paired-replay.md): balanced session
  pairs, explicit abort/not-run accounting and whole-session exploratory analysis.
- [Paired-replay result cards](docs/wp01-replay-result-cards.md): recursive evidence
  bindings, preserved session uncertainty and explicit unresolved qualification.
- [Whole-session replay resources](docs/wp01-replay-resources.md): a separate
  diagnostic cgroup covering preparation, idle/background work and shutdown.
- [Paired whole-session resources](docs/wp01-paired-replay-resources.md): fresh
  per-session groups, complete planned denominators and resource-only summaries.
- [Resource-replay result cards](docs/wp01-replay-resource-cards.md): offline
  recursive bindings, preserved missing metrics and 24 unresolved qualification fields.
- [Scenario/reset/edit validation](docs/wp01-scenario-replay.md): explicit file
  effects, retained request inputs and historical reset evidence, not a semantic oracle.
- [Paired scenario campaigns](docs/wp01-paired-scenarios.md): frozen shared input
  bytes, per-arm reset observations and complete failed/unknown/not-run ledgers.
- [Manifest-to-scenario binding](docs/wp01-scenario-manifest.md): offline byte-bound
  declarations and complete scenario outcomes, with unresolved qualification preserved.
- [Development CLI](crates/pt-cli/README.md) and
  [process supervisor](crates/pt-process/README.md): partial WP04, not `pt run`.
- [WP04 evidence and open gates](docs/wp04-status.md), including the bridge
  packaging smoke check and explicit terminal/process ownership limits.
- [Benchmark review checklist](docs/benchmark-review-checklist.md): review
  criteria, all initially unreviewed.
- [Campaign template](bench/benchmark-campaign.template.yaml) and
  [schema](bench/benchmark-campaign.schema.json): draft benchmark inputs, not an
  executable benchmark or proof of results.

## Development setup

Git is sufficient to read and review the handoff. The support matrix selects
CPython 3.12.12 and pytest 8.4.2 on Linux x86-64, but no profile is qualified.
The Rust workspace uses `Cargo.lock` and the selected toolchain; setup and test
commands are in the development guide. CI qualification is not established yet.
The harness prototype has tests and a locked dependency environment; see its
README. Subsequent work must document setup and checks alongside the code.

## Initial sequence

Start with WP00 (contracts and architecture). WP01–WP03 establish independent
measurement and semantic qualification; WP04 may follow WP00 in parallel with
that track. WP05 depends on WP03 and WP04. See section 21 of the specification
for the authoritative dependencies and acceptance criteria.
