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

## Optional static startup rejection checks

```sh
./target/release/pt doctor --python /absolute/path/to/venv/bin/python --startup-profile pytest_module </dev/null
./target/release/pt doctor --python /absolute/path/to/venv/bin/python --startup-profile pytest_console </dev/null
```

These requested checks reject known unreviewed early-startup inputs without
executing inspected hooks or project code. They do **not** execute pytest,
establish immutable inputs or authorize a private-channel launch. All five startup
assurance fields stay null and `qualified` stays false. Original `doctor` without
this option remains metadata-only; `exec` remains a raw process diagnostic.

The Rust front end refuses explicit `LD_PRELOAD`, `LD_AUDIT`, `LD_LIBRARY_PATH`
and unknown `/etc/ld.so.preload` input before invoking selected Python; `-I/-S`
alone cannot stop native-loader effects. This cannot undo the native CLI's own
loading or identify every host-loader input. Environment values are not exported.
The isolated Python probe reads the venv config, `.pth` files, customization and
shadowing names instead of importing them. Unreviewed Python startup/path/warning
inputs, system/user-site domains, hooks, special files and bound overflows fail.

Only the exact development uv `_virtualenv.pth` / `_virtualenv.py` source-hash
pair is recognized by engineering inspection, **not a security audit**.
Alternative package/native/sourceless origins and existing shim pycs are
unreviewed, never purged or equated to source by timestamp. Coverage's
`a1_coverage.pth` also remains unreviewed. The guard does not remove those files,
disable plugins or rewrite the runtime environment to force a passing result.

The module profile checks cwd startup/backend import shadowing; the console
profile checks its installed script directory and exact recognized wrapper /
shebang. Neither entrypoint substitutes for the other. Limits: 1 MiB/file, 64
entries/directory, 16 retained files/findings and a bounded reply. Excess inputs
fail rather than being omitted from a passing inspection.

Actual controls demonstrate why this is necessary: `.pth` and PYTHONPATH
sitecustomize can import code or leak a socket across exec **before** a later
explicit bridge marks it non-inheritable. Project `pytest.py` can replace module
execution while the installed console still runs real pytest. Late complete
frames cannot certify that earlier window. Complete environment identity,
immutable inputs, native initialization and supported-launcher integration remain
independent gates; `pt run` is still unavailable.
