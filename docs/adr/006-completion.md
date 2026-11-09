# ADR006: completion is an accounted terminal state

Status: adopted for conservative baseline engineering by WP00 self-review,
2026-11-09; real-work/generation/artifact verification is not supplied by schemas.
See [review](../wp00-review.md) and [protocol](../protocol-draft.md).

Full success requires complete requested-work accounting,
valid current generation, required finalized artifacts, and owned process and
resource cleanup. Preserve a completed pytest session's exit status and expose
typed PT failures separately. Missing events or uncertain finalization cannot be
interpreted as passes. Affected-run success certifies only the selected scope.
