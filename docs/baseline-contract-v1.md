# Baseline implementation contract v1

Engineering decision, 2026-11-09. This is the implementation agent's **self-review**
of WP00, not independent review, artifact authentication, or tested support.
It adopts the conservative choices below for WP04. Later optimizations retain
their separate prerequisite gates. The implementation specification and C01–C12
remain normative; this record resolves the earlier drafts where noted.

## Target and scope

- First target: Linux x86-64, GIL-enabled CPython 3.12.12, pytest 8.4.2,
  Rust 1.99.1. Versions are selected targets, not supported-by-proximity claims.
- `pytest_console` and `pytest_module` are separate profiles. No automatic
  substitution of `python -m pytest` for a console script, or vice versa.
- Only a fresh serial real-pytest session is eligible for the initial contract.
  Collection and execution share that session. No preflight collection or
  automatic retry. All optimization capabilities default to denied; the named
  permissions/reference contracts in `capability-policy.md` remain required.
- Unknown, conflicting, expired, or differently scoped evidence denies the
  transformation, never a plugin. Required unavailable features fail before
  project execution; preferred ones retain the conservative path and explain why.
- Parallelism, daemon/seed reuse, affected selection, resource reuse, persistent
  runtime reconstruction, and non-Linux platforms are unavailable until their
  packages qualify them. No arbitrary heap serialization or general reset.

## Process and output boundary

The Rust coordinator does not load project Python. An explicit executable and
argv vector are launched directly, without a shell, in the requested cwd with
the caller's environment and stdin/stdout/stderr inherited. No plugin suppression,
dependency installation, environment rewriting, or PT global pytest entry point
is permitted. Original OS argument bytes, including empty arguments, survive.

WP04's process-only diagnostic command is `pt exec`; it is **not `pt run`** and
cannot certify collection, work, artifacts, or generations. A zero exit there
means only the supervised command exited zero and required process cleanup
completed. Arbitrary executables are explicitly requested diagnostic code.

Each launch creates a new process group. The supervisor owns its leader and
ordinary, non-detached group members. On timeout/cancellation, terminate that
group; after an ordinary leader exit, terminate residual group members before
returning. Cleanup has a separate finite deadline. Preserve raw exit/signal and
cleanup status. Keep the leader unreaped until final group signaling is complete
to avoid signaling a newly reused leader PID. Linux procfs is required for the
initial no-live-members check; inability to verify it is cleanup uncertainty.
Zombies are not live workers, but the direct child must be reaped.

Inherited output preserves the caller's TTY/capture behavior without a new PT
output buffer, but inherited descriptors alone do not establish interactive
foreground job control. The initial WP04 implementation must reject terminal
stdin before work until that behavior is implemented and tested; explicitly
redirected/non-terminal input is the bounded target. Output can be blocked by a slow consumer; timeout control must not
depend on that consumer. No stdout control messages or pass-count scraping.
Structured artifacts, when requested later, are additive and opt-in; secrets
are not collected as raw environment metadata. Detached descendants and external
services are outside this process-group contract, not silently certified absent.

## Typed terminal outcomes and precedence

| Outcome | Condition | CLI exit |
|---|---|---|
| `configuration_error` | Invalid PT arguments, interpreter selection, cwd, or required feature before work | 4 |
| `unsupported_profile` | Unavailable platform/backend/version/profile | 4; no implicit passthrough |
| `launch_error` | OS launch fails after input validation | 3; no replay |
| `backend_completed` | Documented pytest exit 0–5 **and** all applicable completion gates pass | Original code |
| `process_exited` | Diagnostic `pt exec` only, normal process exit | Original code; not a pytest/work verdict |
| `backend_terminated` | Signal termination or undocumented pytest status | `128 + signal` for Linux signals; 3 for undocumented pytest code |
| `timeout` | PT deadline expires | 3; raw child status retained |
| `interrupted` | PT receives SIGINT/SIGTERM or explicit cancellation | 2; original signal retained |
| `infrastructure_error` | Protocol, accounting, I/O, artifact, supervision, or required cleanup failure | 3 |
| `generation_invalid` | Relevant generation superseded/unknown/uncertain for a requested qualified result | 3; never current full success |
| `abandoned` | Coordinator recovery finds unfinished work | 3; no executing-session reattachment |

Configuration/unsupported failures occur before launch. After launch, required
infrastructure/cleanup failure takes precedence, then invalid generation, then
the first observed timeout/cancellation, then signal termination, then normal
backend exit. Retain secondary causes and the raw status rather than losing a
test failure behind a cleanup error. An interruption observed before launch
does not start work. Timeout and cancellation cannot be reversed by a later zero
exit. Signal mapping is an ordinary CLI exit, not a claim that PT itself has
the child's OS `WIFSIGNALED` status.

## Full-result boundary (WP05 and later, not supplied by `pt exec`)

Success requires the same-session authoritative occurrence inventory (duplicates
preserved), explicit selection/deselection accounting, valid per-attempt phase
transitions, terminal backend status, required reports/coverage artifacts,
generation assurance for the declared input domain, and required cleanup. Setup
skip/failure may omit a call but not hide teardown; collection-only, no-tests,
fail-fast, and interrupted sessions have explicit accounting, not inferred passes.
Coverage/report plugins finalize before completion. A terminal bridge event or
backend zero alone is insufficient. A finite qualification corpus is not proof
of universal equivalence. Live-tree observation is not atomic-snapshot assurance.

## Minimal bridge transport decision

Use a private inherited Unix socket pair, not a public/named listener. The
connected descriptor is the capability: no address for unrelated clients to
connect to. In the bridge, set it non-inheritable before project imports. This
does not protect against hostile code running in the same process/user account.
The coordinator owns opaque per-run/session/generation IDs; messages must match.
Use the draft 32-bit big-endian framing with a 1 MiB payload cap, UTF-8 strict
JSON, exact version 0 and a session-start handshake. Refuse unknown versions;
never downgrade or replay after effects begin. Sequence starts at zero and is
contiguous per producer. Lost/truncated/contradictory frames or early EOF fail
closed. The five existing event shapes are a tested **subset**, not the complete
event catalog. Additions require explicit schema/version review before use.

Bound reader queues and aggregate retained data; never buffer unbounded stdout
or events. If the channel cannot progress inside the deadline, terminate the
owned group and report incomplete infrastructure, not a successful partial run.
Artifact references are not trusted filesystem paths; only coordinator-owned
bounded output locations may be committed. WP09 must harden and fault-test this
transport; choosing it is not evidence that it is implemented.

## Review disposition

ADR001–ADR006 and the benchmark charter are adopted for conservative baseline
engineering. The claim families, measurement layers, frozen campaigns, failed
denominators, and non-author WP17 review remain unchanged. The capability policy
does not enable any transformation; adapter trust, evidence validation, and
scoped composition must be implemented before an `allow` can take effect.

The adverse inventory in specification §14.3 and `invariant-review.md` was
reviewed against these decisions: same-session collection, duplicate IDs,
fixture/plugin effects, exit/failure distinctions, stale source, and lost events
are qualification obligations, not exclusions to manufacture green results.
Arbitrary concurrent input mutation is not solved by process freshness. No
generation-valid full result is authorized without its assurance checks.

WP00's baseline design choices are resolved for WP04; its complete protocol
catalog and independently reviewed qualification evidence remain open. WP01–03
must still meet their acceptance gates before WP05. This review does not declare
M0 complete, any support profile qualified, or any optimization permitted.
