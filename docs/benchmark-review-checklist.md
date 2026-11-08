# PT benchmark review checklist

This checklist accompanies the implementation specification. It is a release-review aid, not evidence that a benchmark has already passed. All gates begin **unreviewed**.

## A. Claim and experiment freeze

- [ ] The claim is identified as equal-work execution, prepared-session amortization, or incremental feedback; these are not blended.
- [ ] The exact hypothesis, primary endpoint, practical-effect threshold, sample size, and analysis are committed before confirmatory measurement.
- [ ] Candidate, baseline, interpreter, dependencies, repository revisions, and analysis code have verified artifact digests.
- [ ] Training, confirmatory, and holdout workloads are separated; baseline tuning uses only the training allocation.
- [ ] Protocol changes create a new campaign; earlier unfavorable results remain available.

## B. Equal semantics and work

- [ ] The reference is a pinned invocation/profile, not an unspecified “pytest.”
- [ ] Collection identities, multiplicity, ordering constraints, selectors, fixtures, plugins, and expected outcomes are qualified.
- [ ] Setup, call, teardown, collection, and infrastructure failures cannot collapse into a pass count.
- [ ] Instrumented correctness runs and unmodified product timings are distinguished; observer overhead is measured.
- [ ] Coverage matches effective core, line/branch/context semantics, subprocess collection, and required merge/report outputs.
- [ ] Unsupported, wrong-result, timeout, and crash cases remain in corpus coverage/reliability denominators.
- [ ] Failed or started work is not transparently replayed to conceal compatibility problems.

## C. State, timing, and resources

- [ ] “Cold” and “warm” specify coordinator, seed, metadata, bytecode, filesystem, services, dependency training, and source state.
- [ ] Per-arm reset and probe procedures establish equivalent declared starting conditions.
- [ ] First-run timing includes coordinator/seed preparation; warm measurements declare their preparation history.
- [ ] Identity checks, cache validation, snapshot creation, execution, required reports, coverage merge, and cleanup are inside the applicable endpoint.
- [ ] Dependencies are not resolved or installed for only one arm; compiler/build settings are disclosed.
- [ ] Total CPU and memory budgets include coordinator, seed, workers, services, and native-library threads.
- [ ] Peak and idle memory use an explicitly named accounting metric; independent process RSS maxima are not summed as a simultaneous peak.
- [ ] Persistent background work and training/rebuild costs appear in replay/amortization results.

## D. Statistical validity

- [ ] Paired block order is balanced and randomized with a committed seed; arms are not measured concurrently.
- [ ] A fresh invocation or complete newly bootstrapped replay is the sample unit; interactions within one daemon are not counted as independent sessions.
- [ ] The final sample size was fixed from separate pilot evidence, not extended until favorable significance appeared.
- [ ] Time-order, dependence, and host-state checks support the resampling unit; effective independent sample counts are disclosed.
- [ ] Slow samples remain unless a preregistered, independently evidenced exclusion applies to the complete pair.
- [ ] Timeouts are censored/failing observations, not successful samples at the timeout threshold.
- [ ] Effect sizes include absolute latency and uncertainty, not just ratios of minima.
- [ ] Aggregate weights were fixed in advance; all cells and regressions are published.
- [ ] Secondary claims are exploratory or use a declared multiplicity adjustment.
- [ ] Tail-latency claims have enough observations and independent sessions for the stated uncertainty.

## E. Affected execution and generation integrity

- [ ] Selected-run success cannot be described as full-suite success.
- [ ] Every result names a source generation and assurance model; live-tree results do not claim atomic-snapshot guarantees.
- [ ] Failure-inducing edits are audited against clean full oracles with the same source/tests/environment.
- [ ] Failure recall, missed failures, selection size, fallback rate, and unstable-oracle cases are published with denominators.
- [ ] Zero observed misses are not claimed to prove zero miss probability; independence/representativeness limits are stated.
- [ ] Training and instrumentation overhead, invalidation costs, and sequence break-even are included.

## F. Harness integrity and release decision

- [ ] Deliberately broken candidates that skip work, omit coverage, return stale results, or leak workers are rejected.
- [ ] Known delays in startup, teardown, merging, and shutdown appear in the correct endpoint.
- [ ] Deterministic analysis tests include ratio direction, missing data, duplicated samples, and correlated session observations.
- [ ] An independent reviewer can reconstruct the headline from the raw bundle.
- [ ] Critical findings reproduce on an independent host or session within the claim's scope.
- [ ] Every release gate is explicitly pass, fail, or inconclusive; inconclusive is not treated as pass.

## Decision record

Campaign ID: **unassigned**  
Candidate artifact: **unresolved**  
Reviewer: **unassigned**  
Decision: **unreviewed**  
Blocking correctness issues: **not evaluated**  
Performance conclusion: **not measured**  
Unsupported/uncertain scope: **not yet qualified**
