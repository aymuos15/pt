# ADR002: real pytest backend

Status: adopted for conservative baseline engineering by WP00 self-review,
2026-11-09; observer/backend implementation is still missing. See
[review](../wp00-review.md).

Delegate collection and execution to real pytest with an
explicitly loaded observational bridge, rather than replace pytest semantics.
Both phases occur in the same session; the bridge must not autoload into ordinary
pytest. This limits early speedups and requires compatibility qualification.
Bridge introspection or plugin conflicts may require an unsupported classification
or a future explicitly qualified passthrough rather than an unearned equivalence
claim. No passthrough profile is implemented in the initial baseline.
