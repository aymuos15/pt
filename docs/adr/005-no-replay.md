# ADR005: no automatic replay after effects

Status: adopted for conservative baseline engineering by WP00 self-review,
2026-11-09; not an implementation claim. See [review](../wp00-review.md).

Capability checks happen before affected work starts where
possible. Once work starts, a fallback must not transparently replay it: external
effects cannot be rolled back from an absent acknowledgement. Unknown capability
denies the optimization, not the plugin; prefer conservative execution or a
visible failure. Preserve the original attempt and diagnostic information.
