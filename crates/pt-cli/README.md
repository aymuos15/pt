# Development CLI (WP04)

`pt exec` is a **process-only diagnostic**, not the PT pytest backend. It is
implemented only for Linux x86-64 and has no daemon, cache, seed, or bridge yet.
`pt run` fails as an unavailable command instead of returning a false pass.

From the repository root:

```sh
cargo build --locked --release -p pt-cli
./target/release/pt --help
./target/release/pt exec --timeout-seconds 10 -- python3 -c 'print("hello")'
```

PT options appear before a required `--`; executable and argument OS bytes after
it are forwarded as-is, without a shell. Cwd (or `--cwd`) and environment are
preserved. Inherited standard streams preserve TTY/capture behavior and don't
create an internal PT output buffer. The process crate owns timeout, cancellation,
and ordinary process-group cleanup; see `../pt-process/README.md` for limits.

Optional `--report NEW_FILE` reserves a mode-0600 hidden lock before launch and
publishes JSON without overwrite after required process cleanup. An existing
record or lock rejects the invocation before code executes. Failed publication
returns 3 even after child zero, never retries work, and preserves competing
records. A crash may leave a hidden lock; inspect it before manual removal. This
is not a power-loss-durable store or protection against malicious same-user path
races. Report files contain process metadata and are not conformance artifacts.

Execution timeout defaults to 300 s; cleanup defaults to 1 s and must be in
`(0, 30 s]`. SIGINT/SIGTERM requests cancellation and maps to exit 2 after cleanup;
hard timeout maps to 3. Raw child code/signal and cleanup evidence are retained
in requested reports. A normal child code is preserved only after verified
process cleanup. None of this establishes source/generation integrity or test
work completeness. No benchmark gain or support qualification is claimed.
