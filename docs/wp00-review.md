# WP00 review and readiness register

Status: **incomplete; drafts unreviewed**. This register records current gaps;
it is not independent review, a support claim, or an authorization to enable
optimizations. The acceptance criteria are in section 21 of the implementation
specification.

| Deliverable or gate | Current evidence | Remaining work |
|---|---|---|
| Execution contracts and C01–C12 | `contracts.md` sketches the conservative contract | Review each invariant against specific observable behavior and adverse cases; resolve typed outcomes and complete all exit paths. |
| Support matrix | `../support-matrix.toml` proposes Linux x86-64, CPython 3.12.12, pytest 8.4.2 | Verify installation artifacts and both entrypoint profiles; run conformance; distinguish explicitly tested plugins and unsupported cases; review before any support claim. |
| Toolchain | Local interpreter and Rust were observed during development | Establish reproducible Rust compiler, interpreter, dependencies and hashes; document installation without mutating user environments. A proposal is not an environment lock. |
| Protocol v0 | `protocol-draft.md` defines candidate framing and envelope | Specify exact event schemas, version negotiation, failure handling, authentication, backpressure, limits, platform transport, and compatibility tests. |
| Threat model | `threat-model.md` identifies trust boundaries and unresolved items | Review adversaries, IPC credentials, path races, artifact retention, resource limits, and supported platform mitigations. |
| ADR001–ADR006 | `adr/` records proposed architecture | Review decisions, alternatives, consequences, and unresolved integration risks; retain later changes in history. |
| Benchmark charter | `benchmark-charter.md` summarizes claim families and timing | Review against sections 12–20, reset and artifact evidence requirements, exclusion policy, and independent-review procedures. |
| Output and exits | `contracts.md` sketches preservation and typed errors | Define an explicit mapping for all pytest exit codes, PT errors, child signals, timeout, cancellation, incomplete reports and cleanup failures; qualify output behavior under supported TTY/capture profiles. |
| Capability permissions | `contracts.md` states unknown means deny | Define each capability's issuer, evidence, scope, invalidation and reference contract; ensure denied preferred versus required behavior is explicit. |
| Adverse-case review | Cases are listed in section 14.3 | Map each case to its contract, required test, failure disposition, and tested profiles; execute after the relevant test infrastructure exists. |

Until these gates are reviewed, WP00 is not complete. Prototyping can identify
gaps but cannot turn drafts into supported behavior, performance claims, or
default-enabled optimizations.
