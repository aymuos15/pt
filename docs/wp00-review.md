# WP00 review and readiness register

Status: **incomplete; bounded engineering self-review, no qualification**. This register records current gaps;
it is not independent review, a support claim, or an authorization to enable
optimizations. The acceptance criteria are in section 21 of the implementation
specification.

2026-11-09: [baseline contract v1](baseline-contract-v1.md) records an explicit
engineering self-review and resolves the initial WP04 target, process/output
boundary, typed terminal precedence, and private descriptor transport. This
supersedes the corresponding open choices below for baseline development only.
It is not independent review or support qualification. The revision-1
[protocol contract](protocol-draft.md) now specifies 32 typed event kinds and a
[final-result schema](final-result-v0.schema.json). Its collection, deselection,
attempt/phase, artifact and terminal arithmetic have synthetic contract tests.
Production framing/validation and actual work/environment/generation evidence
are not supplied by those tests. WP01–03 acceptance and product conformance
remain open; M0 is not complete.

| Deliverable or gate | Current evidence | Remaining work |
|---|---|---|
| Execution contracts and C01–C12 | `baseline-contract-v1.md`, the protocol and final-result schemas resolve baseline typed outcomes, precedence and completion arithmetic; `invariant-review.md` maps adverse obligations. | Review the complete contract together; implement and independently observe actual same-session work/generation/finalization before product claims. Synthetic consistency is not semantic proof. |
| Support matrix | `../support-matrix.toml` selects Linux x86-64, CPython 3.12.12, pytest 8.4.2 as an unqualified target. Module and console entrypoints remain distinct. | Verify installation artifacts, actual PT behavior for both profiles and full conformance; distinguish explicitly tested plugins and unsupported cases. Terminal stdin is rejected, not implicitly supported. |
| Toolchain | `development.md` records provisional Rust and Python choices; harness dependencies are locked. An optional offline check compares two disposable environments, interpreter bytes, hashed RECORD entries and current synthetic smoke cases. | Authenticate distribution and interpreter artifacts, account for unhashed/unlisted installed files, complete representative corpus materialization and platform identity. Pins alone are not verified benchmark artifacts. |
| Protocol v0 | Revision 1 defines all 32 catalog shapes, exact target handshake, producer identity/order, bounded normalized traces, collection/attempt accounting, artifacts and typed final results. `tests/contracts/` supplies synthetic valid/mutation checks, separate from per-message schema checks. | Review the specified design; implement and fault-test framing/decoder, deduplication, private descriptor ownership, queue bounds and real artifact/environment/generation verification in the relevant packages. No production validator or WP03 oracle is claimed. |
| Threat model | `threat-model.md` identifies trust boundaries and unresolved items | Review adversaries, IPC credentials, path races, artifact retention, resource limits, and supported platform mitigations. |
| ADR001–ADR006 | `adr/` records proposed architecture | Review decisions, alternatives, consequences, and unresolved integration risks; retain later changes in history. |
| Benchmark charter | `benchmark-charter.md` summarizes claim families and timing | Review against sections 12–20, reset and artifact evidence requirements, exclusion policy, and independent-review procedures. |
| Output and exits | Baseline mapping and final-result schema cover pytest 0–5, prelaunch configuration/unsupported/launch errors, signal/undocumented status, timeout, cancellation, infrastructure, invalid generation and abandonment. Process-only CLI has separate evidence in `wp04-status.md`. | Qualify actual pytest output/plugin/error behavior and foreground terminal job control before broadening support; recovery outcome is schema-only, not an implemented recovery path. |
| Capability permissions | `capability-policy.md` names all nine permissions/reference contracts and conservative composition/invalidation; the serial schema permits only deny/unknown with session scope. | Implement evidence/trust and nested-scope composition before any future allow. A typed extension/resource event grants no capability. Required unavailable features fail before work; preferred ones stay conservative. |
| Adverse-case review | `invariant-review.md` maps section 14.3 to baseline disposition, synthetic checks and still-required real evidence. | Execute the complete mandatory real-pytest and fault-injection matrix after its infrastructure exists; keep uncertain/unsupported cases visible. |

## Verified protocol/accounting batch: a7a7bac

2026-11-09, selected Linux development host, locked CPython 3.12.12 environment:

- **58** separate contract tests passed, including schema checks for all ten
  terminal outcomes and mutation checks for collection/selection, phases,
  retries, artifacts, stop/exit precedence and false full-success assertions.
- **42 hand-written synthetic scenarios**, each with/without a required artifact,
  reconciled successfully. These are 84 example configurations within the
  checks, not 84 independent real-pytest sessions or qualification observations.
- **160** independent-harness tests passed, including all 32 event-shape examples
  and exact target-handshake checks. An earlier full run failed on a procfs
  disappearance race in the harness's cleanup test; fix/regression `e76e8df` and
  `tests/contracts/README.md` preserve the cause and correction. No benchmark
  exclusion rule or production cleanup guarantee was relaxed.
- **28** Rust release tests, rustfmt and clippy with `-D warnings` passed again.
  They remain WP04 process/CLI evidence, not pytest semantic qualification.

Commands are in `development.md` and `tests/contracts/README.md`. Local Markdown
links and both offline schemas were also checked. No production wire framing,
actual artifact/environment/generation verification, WP03 oracle, or PT
conformance/campaign was exercised. Packaging checks were not rerun in this
protocol-only batch; their earlier bounded evidence remains in `wp04-status.md`.

Until these gates are reviewed, WP00 is not complete. Prototyping can identify
gaps but cannot turn drafts into supported behavior, performance claims, or
default-enabled optimizations.
