# WP00 review and readiness register

Status: **WP00 definition and engineering acceptance review complete for the
conservative baseline; no support or release qualification**.

Review date: **2026-11-09**. Reviewer: **implementation agent in the technical-lead
role, reviewing its own design**. Review input: specification v0.1, repository
revision `40ff2b1`, the earlier baseline decision and protocol revision 1. No
independent reviewer, human owner sign-off, security audit, benchmark review or
release approval is claimed. Specification §21 permits combined engineering
roles; WP17's non-author review remains mandatory for release evidence.

## Acceptance decision and scope

**Accept the baseline definitions**, not their future implementation. The WP00
criteria in [specification §21](pt-implementation-spec.md) are reviewed below.
The former draft questions now have explicit conservative dispositions; none
authorizes arbitrary serialization/reset, unqualified green, or a performance
transformation. Unknown capabilities stay disabled, unsupported required features
fail, and unresolved identity/cleanup cannot justify success. There is no current
baseline compatibility disagreement left open by this review. A new disagreement
reopens the affected contract and blocks its transformation, not a quiet waiver.

WP01–WP03, WP04 completion, a real WP05 backend, production protocol/security,
generation assurance and qualification remain **open** under their original
dependencies. **M0, M1 and release are not complete; `pt run` remains unavailable.**
Closing a definition package does not invent a real-pytest observer or oracle.

| Acceptance ID | Specification requirement | Decision and review evidence | What this does not establish |
|---|---|---|---|
| A01 | Freeze initial versions, invocation profiles, unsupported/output policy (§§1.4, 2.1, 11, WP00) | **Accepted design.** Linux x86-64, GIL-enabled CPython 3.12.12, pytest 8.4.2, bridge skeleton 0.0.0 and Rust 1.99.1; console/module profiles separate. [Matrix](../support-matrix.toml), [contracts](contracts.md), [development](development.md). Non-terminal stdin only; no implemented passthrough. | No authenticated distribution, installed runtime, plugin/kernel/libc or neighboring-version support (G02/G04/G05/G09). |
| A02 | Every optimization has a named permission and reference contract (§§2.2 C04/C10, 6, WP00 acceptance) | **Accepted design.** All nine [capabilities](capability-policy.md) name their reference/default; initial scope is session, deny/unknown only. Required/preferred, provenance and conflicting/nested scopes have explicit conservative dispositions. | No policy engine/issuer trust or permission to optimize; future allow needs G07 and its feature gate. |
| A03 | Every exit path has a typed outcome (§§2.2 C06/C09, 10–11, WP00 acceptance) | **Accepted design.** [Contracts](contracts.md), [baseline precedence](baseline-contract-v1.md) and [final schema](final-result-v0.schema.json) distinguish all ten test outcomes, raw statuses/secondary causes, diagnostic process exits and non-test control operations. | Schemas do not implement all CLI I/O, bridge, recovery or error paths; their actual tests remain G03–G05/G08/G09. |
| A04 | No implied arbitrary collection serialization or state reset (§§3.3, 5.3, 7, WP00 acceptance) | **Accepted design.** [Contracts](contracts.md), [ADR001/002/005](adr/README.md), capabilities and T06/T09 prohibit treating metadata as runtime objects, reusing/resetting executed sessions or replaying effects. | No cache/runtime reconstruction, seed, reset or retry adapter is qualified. |
| A05 | Review C01–C12 and adverse examples (§§2.2, 14.3, WP00 acceptance) | **Accepted design review.** [Invariant/adverse map](invariant-review.md) covers all twelve invariants and every fixture/plugin, identity/edit and fault group; scope/work/generation/cleanup failures remain visible, not exclusions. | Synthetic ledger/probe tests are not actual WP03 adverse parity or current-generation proof (G01–G06/G08/G09). |
| A06 | Contract/protocol/threat/ADR deliverables (§§10–11, WP00 deliverables) | **Accepted design.** [Protocol](protocol-draft.md) has 32 kinds and completion arithmetic; [threat review](threat-model.md) resolves T01–T12, with mandatory controls and implementation gates. [All six ADRs](adr/README.md) review rejected alternatives, costs and later prerequisites. | No authenticated transport, safe store, finalized artifact verification, containment, or universal plugin support. |
| A07 | Freeze benchmark taxonomy/endpoint and review measurement policy (§§12–20, WP00) | **Accepted design.** [Charter](benchmark-charter.md) explicitly reviews each section 12–20: three claim families, independent full endpoint, layers, resets, denominators, resources, paired analysis and non-author review. | No qualified/confirmatory campaign; [release checklist](benchmark-review-checklist.md) remains unchecked (G01/G02/G10). |
| A08 | Stop on unresolved compatibility disagreements; preserve dependency gates (WP00 stop condition, §§21–22) | **Accepted baseline disposition.** Only fresh serial real pytest is eligible; other transformations/profiles remain off/deferred. The gate register below assigns later implementation/evidence obligations rather than calling them solved. | WP00 acceptance is not WP03/WP05 completion, default feature enablement, an independence claim or release authorization. |

## Resolved deliverable decisions

| Former gap | Resolution adopted in this review | Remaining evidence gate |
|---|---|---|
| Contracts still described versions, exits, TTY and precedence as undecided | [contracts.md](contracts.md) is now the current reviewed baseline, with explicit scope classification, all terminal categories, control/process distinction, no passthrough and non-terminal stdin policy. Earlier drafts remain in git history. | G03–G06/G08/G09 |
| Capability scope/trust and explanation were open | [capability-policy.md](capability-policy.md) binds baseline deny/unknown to the session and local coordinator policy. No project/bridge/config/cache claim may enable a feature. Future all-applicable-permissions composition and invalidation/issuer validation must be tested before any allow. | G07 plus the feature's qualification gate |
| Protocol fields could be mistaken for authentication or proof | T02/T03 bind bridge roles/IDs to the inherited channel, not supplied fields; coordinator-only kinds cannot arrive from that channel. Reader bounds include queue/depth, not just per-message schema. Full flags still require external evidence. | G05/G09; artifact/environment/generation evidence G02/G06/G08 |
| Token lifecycle and attacker model were unspecified | T01/T02 select a private connected descriptor, no named/public/remote listener or reusable bearer token. Different-user access/accidental corruption are addressed by required controls; hostile same-user/project code and privileged/kernel compromise are not contained. | G04/G05/G09; new endpoints/OS/trust models require new review |
| Paths, retention, secrets and quotas were open | T04/T05/T08/T11 require private owned roots/files, race-resistant traversal and no-replace publication, independent artifact verification, explicit positive storage budgets, allowlisted/keyed metadata, opt-in private retention/export and safe owned-only reclamation. No silent output rewrite, infinite capture, perfect-redaction or disk-sandbox claim. | G06–G09 and distribution/provenance G02/G10 |
| Cache/recovery, source uncertainty and detached children were open | T06/T07/T09/T12 prohibit executable cache data/reset/replay/reattachment and false current success. Ordinary process groups are not hostile containment or SIGKILL recovery. Unverifiable inputs/cleanup fail or stay visibly unverified. | G03/G04/G06/G07/G09 |
| Supply-chain/profile trust could be mistaken for a version check | T10 distinguishes explicit installation trust, artifact authentication, installed files and runtime imports. Locks, METADATA, RECORD checks and doctor are limited observations; none permits automatic dependency mutation or plugin suppression. | G02/G04/G05/G09/G10 |
| ADR adoption lacked explicit alternatives/consequences | [ADR review table](adr/README.md) records six decisions and costs. ADR004 is deferred; it selects neither an xdist version nor an enabled parallel profile. | G04/G05 and each optional feature's dependencies |
| Charter adoption might be confused with campaign approval | The [charter review](benchmark-charter.md) accepts requirements only; exploratory observations and all failures retain their evidence class. Numerical gates are not achievements, and no campaign fields/checklist boxes are promoted. | G01/G02/G10 |

## Explicit remaining implementation and qualification gates

All rows are **open**, including rows with partial development evidence. The
owners below are the accountable roles in the specification, not newly assigned
people. Follow the specification's dependency graph; listing a gate here does
not authorize implementing a later feature early.

| Gate | Owner/package | Evidence needed before the corresponding claim |
|---|---|---|
| G01 | Performance engineer, WP01 | Complete independent harness boundary/resource/broken-candidate checks and overhead characterization; reject incomplete samples and preserve failures. The concurrent existing-blob verification race reproduced below remains open, not waived. Current synthetic/JUnit/coverage-line checks are not the semantic oracle or a confirmatory campaign. |
| G02 | Test infrastructure engineer, WP02 | Authenticate/pin interpreter, distributions, repository revisions and host/platform identities; two clean materializations with inventories/outcomes, partitions, reset/state probes and visible eligibility/exclusions. Lockfiles/METADATA alone are insufficient. |
| G03 | Compatibility engineer, WP03 | Real-pytest occurrence/phase oracle, narrowly defined normalizer, independent fixture/import/work sentinels and deliberately broken-runner controls, including stale source, collection failures and subprocess coverage. Retain raw evidence and instability. |
| G04 | Systems engineer, WP04 | Complete actual entrypoint/profile/interpreter checks without project imports; qualify the diagnostic switches, output/I/O failure paths, cancellation and native ownership boundaries. Earlier process/packaging evidence is partial in [wp04-status.md](wp04-status.md); interactive stdin stays unavailable. |
| G05 | Pytest integration and reliability engineers, WP05/WP09 core | Explicit real observer and private minimal channel; one same-session collection/execution, ordinary plugins/options preserved, no hidden probe or replay, causal/terminal accounting and required finalization. WP05 still depends on WP03/WP04; full WP09 also retains its WP07 dependency. |
| G06 | Identity/runtime engineers, WP06/WP08 and backend integration | Verify actual installed/input domain and current generation under the declared assurance, including edited/deleted/symlink/external/bytecode cases. A backend observation is not current full success without this evidence; general snapshot/watch machinery is not supplied by WP05 or assertions in fixtures. |
| G07 | Runtime architect, WP07 | Policy/issuer/scope binding, conservative composition/revocation, progressive plans, transactions, schema migrations, quotas and corruption/lease recovery. No allow or authoritative reuse until implemented and feature-qualified. |
| G08 | Reporting/compatibility engineers, WP09/WP15 | Verify actual safe artifact locations/types/ownership/bytes and effective coverage core/file/line/arc/context/subprocess/merge/report behavior. Required artifacts finalize inside the endpoint; unsafe/unverifiable paths/plugins are not rewritten, omitted or silently certified. |
| G09 | Reliability engineer, WP16 with required WP09 core safeguards | Implement/fault-test all applicable T01–T12 controls, platform path/encoding/native limits, real queue/storage bounds, IPC role spoofing, races, I/O/resource exhaustion and crash/recovery/endurance. Required core safeguards cannot be postponed merely because later hardening has its own package. |
| G10 | Performance lead/non-author reviewer/release engineer, WP17/WP19 | Freeze and run qualified campaigns, reproduce independently, decide every release gate pass/fail/inconclusive, publish installable authenticated artifacts/docs and regression controls. No independent review, performance or release sign-off has occurred. |

WP10–WP14 accelerators/services and WP18 native research remain disabled/deferred
under their own dependencies and permission/evidence gates; WP14/WP18 must not
become hidden conservative-product requirements. Only a later tested support
decision may expand the selected matrix. A genuine new product/security tradeoff
outside these conservative defaults requires explicit review/owner direction.

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

## Current review verification

This change is a contract/threat-model acceptance review, not implementation of
G01–G10. Verification checks document links/traceability, exact target pins against
the existing schemas/toolchain/package, capability/outcome/invariant/ADR coverage,
and preservation of unqualified support/campaign status. The existing contract
and harness suites are regression evidence only. No new runtime, packaging,
wire/security fault, actual artifact/input or benchmark qualification is claimed.

2026-11-09 verification of this review:

- **10 documentation/pin traceability tests passed**, covering A01–A08, the exact
  selected tuple/package/toolchain/lock, nine capability references, ten test
  outcomes, C01–C12, T01–T12, all six ADRs, benchmark §§12–20, G01–G10, local links
  and unchanged unqualified/campaign status. These guards do not evaluate the
  quality of authored reasoning or prove a control is implemented.
- **68 total contract/audit tests passed** (the existing 58 plus those ten), with
  ResourceWarning treated as an error. The source specification and original
  handoff are unchanged; no runtime, bridge or harness source changed here.
- **160 harness tests ran: 159 passed and one errored**, in
  `test_blob_store.BlobStoreTests.test_concurrent_publishers_do_not_overwrite`.
  This failure is retained as G01 work; a prior successful full run is not proof
  the race cannot occur. Do not describe this review's full-harness run as green.
- A controlled local diagnostic fixture reproduced the failure: create content
  and its publication hard link, begin `_verify_existing`, then unlink the
  original staging alias during the read. Device/inode/size/mtime and SHA-256
  stayed unchanged while link count went **2 -> 1** and ctime changed; the helper
  raised `BlobError: existing blob changed or does not match its digest`.
  The implicated paths are `bench/harness/blob_store.py` and its concurrency
  test. This diagnoses a benign-publication metadata race, not a product
  conformance or security result. No ctime/digest check was relaxed, no failure
  reclassified/excluded, and no runtime fix is included in the WP00 review.
- Markdown/TOML checks passed; Rust, packaging and real wire/security/semantic
  qualification were not rerun or claimed in this documentation-only review.

Reproduce the documentation audit with the locked environment:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -m unittest discover -s tests/contracts -p test_wp00_review.py -v
```

The full suite commands remain in [development.md](development.md); the
concurrent test can be nondeterministic and must not be rerun-until-green to
erase the original failure. G01 requires a focused safe fix with regression
coverage, not merely a changed expected outcome.

**Disposition:** WP00's conservative definition/review gate is closed by this
engineering self-review. All implementation/qualification gates above remain
open. Do not read the earlier protocol test counts as proof of a usable runner.
