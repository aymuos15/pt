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

## Explicit private control capability

`control_channel_pair()` creates connected close-on-exec Unix stream endpoints,
without a named listener. The parent endpoint is caller-owned; the single-use
`ChildControl` can be consumed by `supervise_with_control()` to map only that
capability to child **fd 3**. Neither argv/environment nor standard streams are
rewritten. `supervise()` / the existing `pt exec` path still inject no descriptor.
Closed standard-stream descriptors are outside this new handoff profile.

The child-only mapping uses explicitly pinned **command-fds 0.3.3** rather than
changing parent-wide inheritable flags or adding an unsafe Rust block. Its
pre-exec implementation and transitive dependencies remain external native code,
not a claim that all dependencies are unsafe-free or security-qualified. The
`Command` is dropped immediately after spawn so its owned parent-side duplicate
cannot hide the child's EOF. Failed/invalid/cancelled launches close that unused
capability, and timeout/cleanup still own the original execution process group.

The caller must drain/validate control data concurrently with explicit bounds
and deadlines. **A process-only report does not validate the stream, a terminal
pytest event, artifacts or current generations.** The bridge component's framing
checks are documented in [`python/pt_bridge`](../../python/pt_bridge/README.md);
there is no production session adapter or `pt run` integration yet.

The later [`pt-session`](../pt-session/README.md) development component joins
that reader/ledger with the same fresh native process. Its
`supervise_with_control_checked` path accepts a distinct observer-failure flag:
known prelaunch failure starts no work; live control failure kills/reaps the
owned group without pretending a user signal occurred. Original raw leader
status stays available. Existing `supervise`/`pt exec` paths have no such flag
and stay process-only. Metadata-only `ProcessRequest::validate` launches no
interpreter or hidden collection. Neither API qualifies a supported launcher,
complete environment, required artifacts or generations.

The worker must mark the descriptor non-inheritable before project imports.
The native fixture checks that after the explicit framing component adopts it,
and ordinary exec descendants cannot inherit it. This is **not** proof about
earlier interpreter startup: `.pth`, sitecustomize, PYTHONPATH and native startup
hooks still require an actual supported-launcher identity/startup qualification
before a backend claim. Do not silently disable site/plugin loading or substitute
an entrypoint to conceal that gate. Raw fork, detached descendants and hostile
same-user code remain outside close-on-exec guarantees.

## Checks

From the repository root (Python's standard library is enough for these tests):

```sh
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" cargo test --locked --workspace </dev/null
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
