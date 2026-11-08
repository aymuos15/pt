# First cloud-agent task: WP00

Read `AGENTS.md` and section 21 of `docs/pt-implementation-spec.md`. Complete
WP00 only; do not implement the runner or claim benchmark results.

1. Propose the exact initial OS, CPython, pytest, and invocation profiles and
   clearly mark decisions needing owner approval. Unsupported profiles must not
   inherit a conformance claim.
2. Draft the execution contracts, full-run completion boundary, stdout and exit
   behavior, typed outcomes, and unsupported-case policy. Preserve C01–C12.
3. Produce the WP00 deliverables listed in the spec: `docs/contracts.md`,
   `support-matrix.toml`, a protocol draft, threat model, ADR001–ADR006, and a
   benchmark charter. Identify proposed decisions versus reviewed decisions.
4. Check the acceptance criteria and section 14.3 adverse cases; list gaps and
   questions rather than pretending they are resolved or tested.
5. Document checks performed and open a reviewable pull request. Do not begin
   subsequent work packages without an explicit assignment.

The repository currently has no implementation, pinned toolchains, CI, or test
commands. Propose reproducible environment and CI choices informed by the WP00
matrix; do not imply they already exist.
