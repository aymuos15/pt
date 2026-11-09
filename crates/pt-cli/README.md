# Development CLI (WP04)

`pt exec` is a **process-only diagnostic**, not the PT pytest backend. It is
implemented only for Linux x86-64 and has no daemon, cache, seed, or bridge yet.
`pt run` fails as an unavailable command instead of returning a false pass.

From the repository root:

```sh
cargo build --locked --release -p pt-cli
./target/release/pt --help
./target/release/pt exec --timeout-seconds 10 -- python3 -c 'print("hello")' </dev/null
./target/release/pt doctor --python /absolute/path/to/venv/bin/python </dev/null
```

PT options appear before a required `--`; executable and argument OS bytes after
it are forwarded as-is, without a shell. Cwd (or `--cwd`) and environment are
preserved. Standard streams are inherited without an internal PT output buffer.
Terminal stdin is explicitly rejected until foreground job control is qualified;
there is no automatic redirection or claim of interactive terminal equivalence.
The process crate owns timeout, cancellation,
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

`doctor` explicitly runs the selected interpreter with `-I -S -B` for metadata
inspection of a standard virtual environment. It requires the exact selected
interpreter, pytest, and bridge versions, and rejects a bridge auto-plugin entry.
It does not import pytest/project modules, execute site initialization or `.pth`
code, install anything, or certify the ordinary runtime's environment/import graph.
A zero doctor exit means only the target installation metadata is present. The
probe must also produce a bounded private JSON reply matching its process exit;
an invalid interpreter that merely returns zero fails instead of passing.
The
bridge is currently a skeleton with **no observer/backend**. See
`../../python/pt_bridge/README.md` for the disposable installation smoke check.
