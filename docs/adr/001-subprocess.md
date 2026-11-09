# ADR001: subprocess boundary

Status: adopted for conservative baseline engineering by WP00 self-review,
2026-11-09; not support qualification. See [review](../wp00-review.md).

Run project pytest in a disposable Python subprocess; the Rust
coordinator does not import project code or embed the interpreter. Reusing a
session that ran tests risks leaking mutable state. Each invocation therefore
incurs process startup and requires explicit supervision and cleanup. A future
preload experiment requires a separate audited contract and disposable children.
