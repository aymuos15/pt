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
available; neither observes or executes pytest test sessions. The initial
supervisor rejects terminal stdin until foreground job control is qualified.
Most proposed product commands, including `pt run`, are not implemented yet.

## Start here

- [Implementation specification](docs/pt-implementation-spec.md): contracts,
  architecture, benchmark protocol, and dependency-ordered work packages.
- [Agent instructions](AGENTS.md): repository-wide working rules.
- [First task](docs/first-agent-task.md): the initial WP00 assignment.
- [Execution contracts](docs/contracts.md): the first, unreviewed WP00 draft.
- [Proposed support matrix](support-matrix.toml), [protocol](docs/protocol-draft.md),
  [threat model](docs/threat-model.md), [benchmark charter](docs/benchmark-charter.md),
  and [architecture decisions](docs/adr/README.md): unreviewed WP00 drafts.
- [WP00 review register](docs/wp00-review.md): outstanding decisions and evidence.
- [Protocol/result contract tests](tests/contracts/README.md): synthetic WP00
  accounting and failure checks; not a bridge, semantic oracle or qualification.
- [Baseline contract v1](docs/baseline-contract-v1.md): self-reviewed process,
  exit, transport, and target decisions for WP04; not support qualification.
- [Development environment](docs/development.md): provisional toolchain pins
  and reproducible prototype checks.
- [Invariant review map](docs/invariant-review.md): adverse evidence still
  required for C01–C12.
- [Capability policy](docs/capability-policy.md): proposed transformation
  permissions and conservative fallbacks, not implementation evidence.
- [Exploratory harness prototype](bench/harness/README.md) and
  [initial corpus probes](bench/corpus/README.md): incomplete WP01/WP02 work.
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

Git is sufficient to read and review the handoff. The support matrix proposes
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
