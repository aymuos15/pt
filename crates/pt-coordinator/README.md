# Owned request and failure-result integration

**Development-only Linux component**, not a usable qualified pytest backend,
full coordinator catalog, supported launcher or successful `pt run`. There is
no release/support/performance upgrade. This layer has **no authority to certify
complete environments or current immutable generations** and cannot construct a
`backend_completed`, current-full-success or zero-CLI test result.

## Requests and launch separation

`RunRequest::new` captures one explicit `SerialRequest`, requested `full` or
`explicit` scope, distinct coordinator producer ID and owned report declarations.
Metadata/process checks, IDs, exact artifact-ID membership, argument/budget and
lifetime bounds are checked before execution. The request is read-only and is
consumed once; observations cannot be attached later by matching strings or
loading a saved process report. PT-chosen affected execution is not implemented.

- `reject_qualified()` consumes the request and returns **unsupported_profile /
  CLI 4 before any child, store or interpreter probe**. Complete environment /
  startup/private-FD handoff, current immutable declared-input generation and
  supported-profile evidence are genuine unresolved prerequisites, not booleans
  a caller may set to true.
- `observe_development(retention, cancelled)` is a **separately and explicitly
  requested unqualified diagnostic**, never an automatic fallback from rejection.
  It creates a new private owned report store rooted in the exact requested cwd,
  then calls the existing single fresh session observer. It does not choose or
  bootstrap Python, inject/rewrite environment/argv, suppress plugins, interpret
  pytest selectors, add a preflight collection or replay work.

The exact executable/cwd/argv limits are 4,096 bytes for executable/cwd, 16,384
arguments, 65,536 bytes/argument and 1 MiB aggregate argument bytes. Empty and
non-UTF-8 arguments survive; NUL and unsupported relative cwd fail. Existing
serial/process/store limits and the one finite retention/finalization deadline
remain. A command digest, available only by explicit accessor, hashes literal
`b"pt-command-bytes-v1\0"`, length-delimited raw executable/cwd, u64 argument
count and length-delimited raw argv (u64 big-endian lengths). It is **only command
byte identity**, not complete request/environment/source identity. Neither raw
environment nor commands are automatically exported in final/event records;
even an unkeyed digest is not safe secret provenance or authentication.

## Actual finalization and retained failures

`ObservedRun::finish()` consumes its own request, live native session and store.
It cannot adopt another process/store/snapshot or a caller-provided hash:

1. Preserve observed inventory/phase/not-run accounting, raw exit/signal and
   cleanup. Normal accounted exit remains a session prerequisite, not a test
   completion verdict. Known death/stop explains incomplete transport; independent
   corruption, native failures and required publication failure stay primary.
2. Commit only this live reader's **observed artifact_ready claims**, after actual
   writer reaping/group cleanup. Derive a matching pinned JUnit expectation from
   the same owned normal snapshot where possible. Native content/hash/path /
   no-replace/readback/deadline checks still apply. Unavailable JUnit context can
   retain partial content, with its exact reason in `artifact_diagnostics()`;
   it cannot satisfy required completeness. Optional failures are not relabelled
   required, and partial/unknown/pending/failed/committed states stay distinct.
3. Produce a read-only revision-1 **failure** record when its facts can be
   represented. Environment remains unverified; a requested full-scope label
   alone cannot establish effective full work. Explicit complete execution /
   collect-only can retain their necessary `work_complete` observation, distinct
   from passing tests and all external gates. No-tests never becomes full success.
4. If observer accounting is unknown, return **final record unavailable**, retaining
   the owned session and its unknown counters. Revision 1 requires numeric counts;
   fabricating zero or relaxing the schema would destroy that distinction. The
   same unavailable path preserves the session/store on record-limit or association
   failures. No saved-file recovery, reattachment, retry or mutable terminal state
   exists.

`finish_with_live_tree(tree)` requires this request's exact cwd binding. It can
report only **uncertain/live_tree**, with `declared_inputs_complete: false`.
Neither that endpoint manifest nor an unrelated root can mint immutable/current
assurance. The final result's raw backend code remains visible even when the
coordinator CLI failure code is 3, 4, 2 or a signal mapping. Artifact publication
may exist after a lost/failed return; the native state preserves that uncertainty,
and filesystem appearance is never used to reconstruct success.

The local diagnostic elapsed duration includes store preparation, the live
session and this finalization. It is not the independent harness's authoritative
product stopwatch. Final JSON is bounded at 16 MiB; error summaries at 1,024 and
65,536 characters/message. Unrepresentable summaries fail rather than truncate
to a deceptively complete record.

## Coordinator records are not a complete qualified trace

Bounded request/rejection, report declaration/commit/failure, actual worker exit,
cleanup and optional live-tree observation records use the **existing protocol
0 / revision 1 shapes**, with contiguous coordinator-owned sequences. The bound
is 4,096 records / 16 MiB including framing allowance / 1 MiB per record.

No `environment_resolved` is invented when a complete interpreter/installed/host
identity is unavailable. This is therefore a **coordinator-origin diagnostic
subset**, not a complete merged qualified event stream. It is not accepted as
an environment-resolved transcript by claiming that each record passes a schema.
No bridge raw-event archive or unbounded stdout buffer is added. Complete event
catalog negotiation, capability provenance, abandonment/durable final publication,
environment/generation/launch support and release qualifications remain open.

## Reproduction

```sh
PT_TEST_PYTHON="$PWD/bench/harness/.venv/bin/python" \
  cargo test --locked --offline --release -p pt-coordinator </dev/null
cargo clippy --locked --offline --workspace --all-targets -- -D warnings
cargo fmt --all --check
```

`PT_OBSERVER_TEST_PYTHON` selects the already prepared pinned subject interpreter.
`PT_COORDINATOR_CASE_ROOT` optionally retains new exclusive test cases, actual
process returns, owned observations, coordinator/final records and independent
offline JSON-schema process reports. Tests neither install dependencies nor
suppress plugin autoload. The schema control imports no PT code and uses only
the two local schemas, pinned CPython 3.12.12 / jsonschema 4.25.1. It checks
**shape only**, not actual work, complete trace causality or qualified truth.
It separately checks that raw exit/signal, stop cause and cleanup match the
retained actual process record; that does not authenticate fabricated records.

Native synthetic controls exercise request/observation association, unknown
counters, report publication/missing readiness/partial/optional states, no-replace,
raw failures/stops, exact argv, finite record budgets and endpoint-only generation.
Actual fresh pytest controls exercise both entrypoints, shared fixture/global /
import effects, failure, fail-fast, collect-only/no-tests, interruption/death and
unsupported outer finalization without inventing qualified success. An actual
JUnit file without a bridge readiness event remains pending; its existence is not
permission to substitute an independent test oracle's hash as a live claim.

All production dependencies are existing local/pinned workspace identities; no
new registry package/version is introduced.
