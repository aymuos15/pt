# Architectural decisions

The 2026-11-09 [WP00 acceptance review](../wp00-review.md) adopts ADR001–ADR006
for conservative engineering (ADR004 as a deferred parallel contract), extending
the earlier [baseline self-review](../baseline-contract-v1.md). The original
proposals remain in git history. This is author self-review, not independent
review, implementation, compatibility, performance evidence or enablement.
Revisions require explicit review and retained history.

1. [ADR001: subprocess boundary](001-subprocess.md)
2. [ADR002: real pytest backend](002-real-pytest.md)
3. [ADR003: serial default](003-serial-default.md)
4. [ADR004: parallel contract](004-parallel-contract.md)
5. [ADR005: no automatic replay](005-no-replay.md)
6. [ADR006: completion and outcomes](006-completion.md)

## Alternatives and consequences reviewed

| ADR | Alternative not selected | Reason and accepted cost | Gate not waived |
|---|---|---|---|
| ADR001 | Embed Python in Rust, or reset/reuse an executed interpreter | Avoid tying coordinator integrity/lifetime to project state; accept fresh-process startup and ownership/cleanup costs. A future seed is a separate capability, never an executed child. | WP04 lifecycle and WP03/WP05 state/import sentinels; optional preload requires WP11 and all its prerequisites. |
| ADR002 | Replace pytest semantics, shadow pytest, globally autoload a bridge, or preflight-collect into serialized runtime objects | Preserve real hook/plugin/fixture behavior in one session; accept observer integration/overhead risk and possible unsupported introspection. Metadata is not runnable collection. | WP03/WP05 real differential parity and packaging negative controls; WP18 research needs measured justification and cannot become a V1 prerequisite. |
| ADR003 | Default parallelism, PT reordering or invisible affected subsets | Preserve the named serial request's ordering, scope and fixture multiplicity; accept foregoing those speed opportunities. Backend-native hooks are still preserved. | Separate permissions, scope reporting and feature-specific qualification before any transformation. |
| ADR004 | Claim arbitrary xdist work equivalent to serial, or write an early custom scheduler | Use a separately named/version-pinned parallel reference at equal resources; no xdist version or support profile is selected/qualified in the serial baseline. | WP10 dependencies and inventory/fixture/fail-fast tests; unknown ordering constraints deny scheduling changes. |
| ADR005 | Replay automatically after a missing acknowledgement or late capability failure | External effects cannot be rolled back or proved absent; retain original attempts and fail/continue conservatively in the existing session. Accept less automatic recovery. | Crash/side-effect and retry-plugin adapter tests; only an explicitly requested, qualified backend retry contract may retry. |
| ADR006 | Treat backend zero, pass totals, a valid terminal event or report readiness as full success | Require scope/work/phase/generation/artifact/cleanup evidence within the endpoint; accept verification/reporting/shutdown cost and visible incomplete results. | WP03, WP05, WP08/WP09/WP15/WP16 evidence as applicable; no assertions-only green or stale/current substitution. |
