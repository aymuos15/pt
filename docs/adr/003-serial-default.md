# ADR003: serial default

Status: adopted for conservative baseline engineering by WP00 self-review,
2026-11-09; no optimization enablement. See [review](../wp00-review.md).

The default contract is serial execution against the matching
fresh pytest invocation. Parallelism and subset selection are opt-in, separately
named contracts. This avoids silently changing ordering and fixture behavior, at
the cost of foregoing default parallel speedups.
