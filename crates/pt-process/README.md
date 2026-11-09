# WP04 process supervision primitives

Linux-only development implementation; **not a pytest backend or conformance
claim**. `supervise` launches an OS argv vector in a fresh process group, with
the requested cwd, inherited environment, and inherited stdin/stdout/stderr.
There is no shell, retry, Python import, plugin policy, or environment install.
The initial scope is **non-terminal stdin**. A terminal input descriptor is
rejected before execution: a new process group needs foreground job control for
interactive reads, which is not implemented/qualified yet. PT does not silently
redirect input or claim unchanged interactive behavior. Output descriptors are
inherited, but interactive terminal equivalence remains unqualified.

The execution deadline is followed by a finite cleanup period (at most 30 s).
Hard timeout sends SIGKILL to the group; cancellation sends SIGTERM then
escalates to SIGKILL. Residual group members are also terminated after a normal
leader exit. `waitid(WNOWAIT)` keeps the leader PID allocated until final group
signaling, then the direct child is reaped. Procfs verification rejects a normal
result if live group members or uncertainty remain. Zombies are not counted as
live descendants; PT can reap its direct child, not arbitrary reparented children.

The report preserves the original reason and child exit/signal. Timeout,
cancellation, and cleanup failure cannot be reversed by a later zero exit.
No record certifies source identity, authoritative collection, complete test
work, required artifacts, or a generation-valid full result.

## Checks

From the repository root (Python's standard library is enough for these tests):

```sh
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --workspace
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
```

Tests default to `python3` and `/tmp/opencode`; override `PT_TEST_PYTHON` and
`PT_TEST_TMPDIR` explicitly if needed. They create only disposable test-owned
files/process groups. Evidence includes fresh PIDs/state, exact OS arguments,
inherited environment, ordinary descendants, timeout, cancellation, escalation,
signals, failed launch, and prelaunch rejection.

## Limits

This is not a sandbox. Detached descendants, new sessions/groups, external
services, hostile same-user processes, and uninterruptible kernel waits are not
contained. Procfs must expose process records; restrictive/hidepid environments
fail closed. Another thread/handler must not reap PT's child or set SIGCHLD to
auto-reap; losing ownership is reported as uncertainty and never authorizes
signaling a recycled PID. SIGKILL of the coordinator cannot run cleanup; the
later hardening package must address that recovery boundary. Polling/verification
has overhead and is included in outer timings, not silently subtracted.
