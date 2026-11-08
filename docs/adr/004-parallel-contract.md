# ADR004: explicit parallel contract

Status: proposed. Initially delegate parallel work to a pinned pytest-xdist
configuration, and compare against the same declared parallel policy and resource
budget. Parallel behavior is not claimed equivalent to serial for arbitrary
order-dependent tests. Scheduling changes require independent capability and
conformance evidence.
