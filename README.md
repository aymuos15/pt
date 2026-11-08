# PT — Incremental Python Test Engine

PT is a proposed local-first test execution coordinator. The design uses a Rust
control plane and fresh Python sessions running real pytest; it does not replace
pytest's semantics. Correctness and independent measurement come before speed.

## Status

This repository contains the initial handoff only. There is **no runner,
benchmark harness, support matrix, or measured performance claim yet**. The
specification is a design proposal, not evidence of implementation or support.
Its example commands are proposed interfaces and cannot be run yet.

## Start here

- [Implementation specification](docs/pt-implementation-spec.md): contracts,
  architecture, benchmark protocol, and dependency-ordered work packages.
- [Agent instructions](AGENTS.md): repository-wide working rules.
- [First task](docs/first-agent-task.md): the initial WP00 assignment.
- [Execution contracts](docs/contracts.md): the first, unreviewed WP00 draft.
- [Benchmark review checklist](docs/benchmark-review-checklist.md): review
  criteria, all initially unreviewed.
- [Campaign template](bench/benchmark-campaign.template.yaml) and
  [schema](bench/benchmark-campaign.schema.json): draft benchmark inputs, not an
  executable benchmark or proof of results.

## Development setup

Git is sufficient to read and review the handoff. Rust, Python, pytest, and
other versions are **not yet pinned**: WP00 must decide the initial support
matrix before an implementation environment and CI are established. No build
or test commands are available yet. Subsequent work should document reproducible
setup and checks alongside the code that introduces them.

## Initial sequence

Start with WP00 (contracts and architecture). WP01–WP03 establish independent
measurement and semantic qualification; WP04 may follow WP00 in parallel with
that track. WP05 depends on WP03 and WP04. See section 21 of the specification
for the authoritative dependencies and acceptance criteria.
