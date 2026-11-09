# ADR004: explicit parallel contract

Status: adopted as a **deferred** architecture by WP00 self-review, 2026-11-09.
Parallelism is unavailable in the initial serial profile; this is not permission
to implement or enable it ahead of WP10 prerequisites. See
[review](../wp00-review.md).

When qualified, initially delegate parallel work to a pinned pytest-xdist
configuration, and compare against the same declared parallel policy and resource
budget. Parallel behavior is not claimed equivalent to serial for arbitrary
order-dependent tests. Scheduling changes require independent capability and
conformance evidence.
