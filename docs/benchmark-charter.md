# Benchmark charter — WP00 draft

Status: proposed, unreviewed; no measurements or performance claims exist.
Section 12–20 of the implementation specification defines the full protocol.

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
