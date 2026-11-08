# ADR002: real pytest backend

Status: proposed. Delegate collection and execution to real pytest with an
explicitly loaded observational bridge, rather than replace pytest semantics.
Both phases occur in the same session; the bridge must not autoload into ordinary
pytest. This limits early speedups and requires compatibility qualification.
Bridge introspection or plugin conflicts may require an unsupported classification
or explicit passthrough rather than an unearned equivalence claim.
