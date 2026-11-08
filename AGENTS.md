# Agent instructions

Read `README.md` and `docs/pt-implementation-spec.md` before making design or
implementation decisions. The specification is a proposal; distinguish its
requirements and targets from implemented, tested, or measured facts. Follow its
work-package dependencies and acceptance criteria. Record open decisions and
unsupported cases rather than inventing conformance claims.

## Non-negotiable boundaries

- Use real pytest as the initial semantic backend, with a fresh execution
  process per run. The Rust coordinator must not import project Python code.
- Preserve authoritative same-session pytest collection and execution; do not
  add a hidden preflight collection run. Preserve plugin behavior and argument
  boundaries. Never silently disable plugins or install/upgrade dependencies.
- Unknown capabilities disable the relevant optimization. Never automatically
  replay work once it has started. Do not report stale, incomplete, uncertain,
  or affected-only work as a successful full run.
- Keep the benchmark harness independent of the product's own timing. Preserve
  failed samples and distinguish correctness qualification, unmodified product
  timing, and diagnostic profiling. Do not assert unmeasured speedups.
- Follow the rest of the C01–C12 invariants and the security, lifecycle, and
  reporting requirements in the specification.

## Working practices

- Keep changes focused on the requested work package. Do not implement later
  optimizations ahead of their prerequisites and gates.
- Choose and document exact toolchain and support versions as part of WP00;
  don't claim untested platforms or versions are supported.
- Add reproducible setup, build, and test commands as they become available;
  run relevant checks and report failures, limitations, and checks not run.
- Do not commit credentials, local environments, generated caches, or raw
  benchmark results containing sensitive data. Preserve source handoff files
  and avoid changing benchmark draft status without the required evidence.
- Ask for clarification when a decision exceeds the task or requires an
  explicit product or security tradeoff.
