# ADR003: serial default

Status: proposed. The default contract is serial execution against the matching
fresh pytest invocation. Parallelism and subset selection are opt-in, separately
named contracts. This avoids silently changing ordering and fixture behavior, at
the cost of foregoing default parallel speedups.
