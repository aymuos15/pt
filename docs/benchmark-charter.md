# Benchmark charter — accepted design, no qualified campaign

Status: adopted by the 2026-11-09 WP00 engineering self-review. No qualified
campaign or performance claim is established; earlier feasibility/exploratory
observations retain their limitations. Sections 12–20 of the implementation
specification define the full protocol. See [acceptance](wp00-review.md).

Report exactly one primary claim family per result: equal-work execution,
prepared-session amortization, or incremental feedback. A selected subset is
never called a faster full suite. The primary endpoint is request submission to
complete, generation-valid result for the declared scope; watch mode starts at
the harness-confirmed edit boundary. Required identity validation, startup,
reporting, artifacts, and cleanup are within the applicable endpoint.

The independent outer harness runs direct pinned pytest and PT without relying
on PT's timer. Correctness qualification, unmodified shipping-mode timings, and
diagnostic profiling are separate layers. Preserve wrong results, failures,
timeouts, exclusions and denominators; an incorrect result is never a speedup.
Equal-work comparisons match selected inventory, backend contract, resources,
coverage, state, and output policy. Strong comparisons include pinned xdist and,
for applicable incremental workflows, testmon.

Preregister artifacts, scenarios, reset policies, sample counts, pairing,
randomization, analysis, and exclusion criteria before confirmatory timing.
Report absolute and relative effects, uncertainty, all workload cells, resource
accounting, and limitations. Reproduce critical findings on an independent host
or machine session and obtain non-author review. Inconclusive remains inconclusive.
The companion campaign template is a draft, not a runnable or frozen campaign.

## Acceptance review against specification §§12–20

This accepts the **measurement contract**, not a harness implementation or any
result. The release [review checklist](benchmark-review-checklist.md) stays
unreviewed/unchecked until an actual campaign supplies its evidence.

| Specification | Adopted requirement / prohibited shortcut |
|---|---|
| §12 | Exactly one primary claim family and a complete declared-scope endpoint; freeze campaign/artifacts and hypotheses before confirmation. Selection is not faster equal work; tuning/changed protocols require new confirmation. |
| §13 | Pinned direct pytest, matched entrypoint/environment/plugins/output/resources and strong xdist/testmon references where applicable; disclose build settings. Shipping baseline has no auto-loaded PT bridge or harness imports. |
| §14 | Mechanism, representative and adverse corpus; partition before tuning, qualify exact revisions, retain unsupported/crash/wrong-result coverage. A small synthetic corpus cannot justify broad claims. |
| §15 | Explicit state vectors, per-arm resets/probes and bytecode policy; preparation/invalidation/required background costs stay in the relevant lifecycle. No global OS-cache clearing or privileged tuning on shared machines. |
| §16 | Separate shipping timing, correctness instrumentation and profiling. Independent argv/timing/validation; balanced randomized paired reset units; freeze sample size from a separate pilot. Preserve failed observations, censor timeouts, reject incomplete samples and account for observer effects. |
| §17 | Paired log-ratio direction plus absolute cost, uncertainty and whole-boundary CPU/memory; declared weights, dependence/resampling units and multiplicity. Repeated interactions are not independent sessions; no ratios of minima or sum-of-peak-RSS fiction. |
| §18 | Effective coverage core/configuration, actual file/line/arc/context and subprocess/merge evidence; required merge/reporting costs are included. Matching rounded percentages or a limited line comparator does not qualify full coverage semantics. |
| §19 | Audited same-source full oracles for selected edits; retain misses/unstable cases, scope and training/invalidation/amortization costs. The 300-edit target or a visibly narrower report is not a zero-miss population proof. Full CI remains default. |
| §20 | Result cards/bundles include correctness and denominators before speed, deliberately broken-candidate controls, timing-boundary delay tests, deterministic analysis and independent reconstruction. Unresolved fields prohibit higher evidence classes. |

Section 22 numerical gates remain proposed product thresholds, not measured
achievements; chosen campaign thresholds/methods must be frozen before inspecting
confirmatory results. WP17 requires non-author review and independent host/session
reproduction; this WP00 self-review cannot substitute for either. No pass/fail/
inconclusive release decision or default-enabled optimization is issued here.
