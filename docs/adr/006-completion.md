# ADR006: completion is an accounted terminal state

Status: proposed. Full success requires complete requested-work accounting,
valid current generation, required finalized artifacts, and owned process and
resource cleanup. Preserve a completed pytest session's exit status and expose
typed PT failures separately. Missing events or uncertain finalization cannot be
interpreted as passes. Affected-run success certifies only the selected scope.
