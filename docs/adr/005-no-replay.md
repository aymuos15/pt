# ADR005: no automatic replay after effects

Status: proposed. Capability checks happen before affected work starts where
possible. Once work starts, a fallback must not transparently replay it: external
effects cannot be rolled back from an absent acknowledgement. Unknown capability
denies the optimization, not the plugin; prefer conservative execution or a
visible failure. Preserve the original attempt and diagnostic information.
