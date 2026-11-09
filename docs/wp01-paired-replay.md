# WP01 paired complete-session replay

Status: **bounded pairing/inspection/analysis implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `ffd6568`. This builds on
[managed replay](wp01-managed-replay.md), not a new execution backend or a
qualification of daemon reuse. `pt run`, the real semantic oracle, qualified
support and release remain unavailable. No measured test-runner speedup exists.

## Whole sessions and matched declarations

[`paired_replay.py`](../bench/harness/paired_replay.py) schedules complete baseline
and candidate replay observations in the existing seeded balanced AB/BA order.
Each arm creates a new private managed-replay directory, running its own
preparation, fixed interactions and required shutdown once. No competing arm runs
concurrently. Preparation is **inside** its session clock, not a free campaign
warmup or an omitted cost. Interactions are never promoted into separate samples.

The new closed [`paired-replay-v1.schema.json`](../bench/harness/paired-replay-v1.schema.json)
stores both canonical managed plans, schedule/seed, basic host observations and
three shared pairing declarations. Before any output directory or project
execution, the producer checks:

- Distinct, nonnested resolved arm cwds, including rejection of obvious symlink
  aliases. These paths are not proof of isolated external state or a sandbox.
- Matching phase IDs/order/count, idle waits, per-phase timeouts and expected exit
  classes, plus matching overall execution budgets and raw-capture policies.
  Preparation/shutdown retain the standalone exit-zero rule. Interaction commands
  may differ by implementation; each may explicitly expect the same nonzero class.
- Typed shared `input_seed`, `edit_sequence_sha256` and `external_state_sha256`
  declarations. Omitting the pairing option records all three as **null**; a
  supplied object must name every field. Non-null digests require a
  full lowercase SHA-256 match; booleans/floats do not replace integer seeds.

The declaration is deliberately **not** actual input/state qualification. The
harness does not apply edits, inspect those hashes' semantic content, inject a
seed into commands, reset arbitrary services or establish equal work. Preparation
must implement the caller's intended bootstrap/reset, and repeated cwds can still
share hidden state. Matching-looking hashes only permit an exploratory calculation,
never a verified-work, independent-session or confirmatory claim.

## Evidence layout and stop policy

The root contains:

```text
schedule.json
session-000001-baseline/       # plan, steps, unit and blobs from one managed replay
receipt-000001-baseline.json   # returned post-endpoint receipt, outside that replay
block-000001-baseline.json     # context, campaign/receipt byte bindings, call/publication clocks
...                           # other actually observed scheduled sessions
abort.json                    # required if execution stops; absent after complete observation
```

Each metadata row binds the exact campaign plan and raw receipt by name, bytes
and SHA-256. Its receipt binds the session's plan/unit and retained inputs using
the unchanged managed-replay contract. Call clocks enclose the entire timed API
and its returned receipt construction; separate receipt-publication clocks follow
the call. The next session cannot start before the previous receipt and metadata
are published/read back and the current session has been inspected.

**Stop after the first failed or unconfirmed session**, including failed
preparation, interaction, guard, deadline, shutdown, archival, observation or
publication. Shutdown is still attempted by the managed executor under its
reserved budget before the paired controller receives a terminal observation.
No failed command/session is automatically retried, resumed, rolled back or
replaced by a favorable pair. The campaign's fixed schedule plus required abort
record reconstructs every remaining `not_run_run_aborted` session without creating
fake execution directories or elapsed times for those sessions.

The inspector retains completed/aborted session outcomes separately from observer
publication flags. A completed replay whose receipt or paired metadata could not
be confirmed is not a successful campaign or eligible sample. Matching diagnostic
copies can preserve that observation in an aborted report; a visible conflicting
copy is rejected. A missing API return leaves a **harness-error/unknown** session,
even if its unconfirmed unit file exists. Its retained bytes can be inventoried
as diagnostics but cannot invent a completed endpoint or known phase outcomes.

Plan mutation stops later calls using the original frozen plan. Contradictory
bindings remain invalid rather than being approved merely because an abort file
exists. An abort-write/storage failure can leave an uninspectable incomplete
campaign; files are preserved, no later work starts, and no subset is reported
as complete. Host loss, SIGKILL, unhandled signals and repeated interrupts cannot
guarantee cleanup or final records. No power-loss durability/authentication claim
is made, and the process-group/file checks do not establish descendant containment
or external-resource release.

## Routed inspection, denominators and whole-pair analysis

[`inspect_run.py`](../bench/harness/inspect_run.py) recognizes this distinct kind;
legacy command, v2 lifecycle and resource diagnostics keep their existing formats.
It recursively invokes read-only managed inspection for every returned session,
then checks the fixed arm plan, context, byte bindings, call/publication enclosure,
nonoverlapping order, abort causality and exact expected files/directories.
Before/after root and nested fingerprints reject observed mutations, with no retry.
Later worktree files are not reread as past results; copied byte-identical bundles
can relocate. Historical timestamps/stat/absence observations are unauthenticated,
and these checks are not an atomic snapshot or hostile-directory boundary.

Reports retain **all planned sessions** and per-session rows, including failures,
not-run sessions and unknown returns. `planned_session_count` equals completed,
aborted, harness-error and not-run status counts together. Known invoked, unknown
and known-not-invoked counts separately sum to the planned sessions. Planned phases
are accounted as observed phase statuses, known-not-run phases or unknown phases;
missing observations are not recast as zero-duration work. Collection/execution
occurrence counts are not inferred from these phase/session denominators.

[`summarize_run.py`](../bench/harness/summarize_run.py) routes replay explicitly.
Only a complete fixed set with every session/phase guard matched, confirmed
receipt/metadata publication, positive whole-session wall intervals, untruncated
raw capture and all shared declarations present can produce an **exploratory**
point estimate. Missing guards, unresolved declarations, failed/not-run/unknown
sessions, truncation or any campaign abort leave ratio, absolute comparison and
bootstrap **null**. No favorable complete-subset analysis is substituted.

The ratio is baseline-over-candidate geometric mean over **complete session
pairs**. Absolute means/differences use each receipt's session clock, including
preparation, idle, interactions, shutdown, archival and unit publication/final
checks. Do not sum nested interaction/command/lifecycle clocks on top. Campaign
plan publication, receipt persistence, paired metadata and subsequent inspection
are separate observer costs outside the named managed endpoint; no claim that the
entire paired campaign is included in each arm's latency is made.

Optional `--bootstrap-resamples N --bootstrap-seed S` draws whole paired sessions,
never individual interactions. At least two pairs and the existing 10-million-draw
computation budget are required. This is an exploratory arithmetic resampling
exercise: actual independent sessions/blocks remain **null**, not the number of
interactions or a presumed reset count. Shared host/worktree effects can still
invalidate an inferential interpretation. Every output stays exploratory and
`confirmatory_eligible: false`, with no release/tail/break-even claim.

Whole-session CPU, memory, idle residency, resource budgets, generations, actual
matching work and reset equivalence remain unknown. Existing resource counters
are not copied from other runs or imputed as zero. At `fe8adbe`, the card CLI
explicitly rejected replay rather than relabelling it as command/lifecycle latency.
The subsequent [paired-replay card follow-up](wp01-replay-result-cards.md) now
adds a distinct closed recursive reporting format, including no-return aborts.
The later [whole-session resource mode](wp01-replay-resources.md) now accounts for
one separate diagnostic replay, not these latency samples. The subsequent
[paired resource integration](wp01-paired-replay-resources.md) adds resource-only
campaigns without relabelling latency replays; resource replay cards remain open.
Changed reader source bytes require the
appropriate historical reader to reconstruct older result cards; `ffd6568` is
the base reader for this batch.

## Bounds and CLI exits

Version 1 allows **1–64 paired blocks**, with the standalone maximum **32
interactions per session**. The campaign's repeated declared artifact/raw budget
is at most **512 MiB**; actual retained evidence is capped at **8192 files / 1 GiB**.
Root entries are bounded, and each nested managed bundle keeps its stricter limits.
Campaign plans/session metadata are at most **1 MiB**; raw receipts/abort records
are at most **4 MiB**. Oversize data fails without dropping sessions or truncating
records. Safe POSIX lookup and the existing Linux native blob publisher remain
required. Paths, arguments, reports and raw prefixes may contain secrets; retain
bundles privately and review before sharing. Raw evidence is not committed.

Executor exit **0** means all requested session observations completed unqualified;
unresolved shared declarations or missing guards can still block the later summary.
Exit **1** means a recorded session failure/deadline with all later sessions not run.
Exit **2** means observer, validation, publication or invalid-input/evidence failure;
an accounted infrastructure abort can still emit JSON with that exit. Inspector
exit **0** means consistent evidence, including an accounted abort, not passing
tests. Summary exit **0** is a nonblocked exploratory estimate, **1** is blocked
with null estimates, and **2** is malformed/unsupported input or options.

## Reproduction: disposable test-owned state only

From the repository root, generate two plans for the existing shared-state probe:

```sh
directory="$(mktemp -d /tmp/opencode/pt-paired-replay.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
probe = Path("bench/harness/tests/fixtures/replay_probe.py").resolve()
digest = hashlib.sha256(b"ready\n").hexdigest()
def artifact(name):
    return {"path": name, "bytes": 6, "sha256": digest}
for arm in ("baseline", "candidate"):
    cwd = root / arm
    cwd.mkdir()
    def step(role, name):
        return {"id": name, "argv": [sys.executable, str(probe), str(cwd), role, name, "normal"],
                "timeout_seconds": 5, "idle_before_seconds": 0,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": digest},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [artifact("report-" + name)],
                                          "absent": ["lease"] if role == "shutdown" else []}}
    plan = {"schema_version": 1, "kind": "managed_session_replay_plan", "mode": "exploratory_unqualified",
            "sample_unit": "complete_managed_session_replay", "measurement_layer": "managed_replay",
            "timing_endpoint": "managed_session_api_entry_through_shutdown_unit_publication_and_declared_finalization_v1",
            "scope": "fresh_serial_commands_with_declared_state", "cwd": str(cwd), "execution_timeout_seconds": 20,
            "preparation": step("preparation", "preparation"),
            "interactions": [step("interaction", "first"), step("interaction", "second")],
            "shutdown": step("shutdown", "shutdown"),
            "finalization": {"expected_exit_code": None, "artifacts": [artifact("report-shutdown")], "absent": ["lease"]},
            "capture_raw": False, "raw_limit_bytes": 1024}
    (root / (arm + "-plan.json")).write_text(json.dumps(plan))
pairing = {"input_seed": 0, "edit_sequence_sha256": hashlib.sha256(b"fixture-no-edits").hexdigest(),
           "external_state_sha256": hashlib.sha256(b"fixture-empty-state").hexdigest()}
(root / "pairing.json").write_text(json.dumps(pairing))
PY
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/paired_replay.py --output "$directory/run" --baseline-plan "$directory/baseline-plan.json" --candidate-plan "$directory/candidate-plan.json" --blocks 2 --seed 0 --pairing-json "$(cat "$directory/pairing.json")" > "$directory/execution.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_run.py "$directory/run" > "$directory/inspection.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/summarize_run.py "$directory/run" --bootstrap-resamples 30 --bootstrap-seed 7 > "$directory/summary.json"
```

This is a functional fixture with two paired blocks, not a corpus, semantic oracle,
pilot or performance campaign. Any computed toy ratio/interval is not a PT speedup.

## Verification and direct controls

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The initial **38 targeted tests passed** (`Ran 38 tests in 64.156s`, `OK`). The
full suite additionally covers the summary's added whole-unit/count guard: omitted
pairs, duplicate arms and relabelled interaction units cannot enter analysis.
Tests include failure/timeout/shutdown cleanup, prior success retention, missing
returns before/after unit commit, interrupted validation, raw-prefix limitations,
receipt/session/abort publication faults, matching declarations, unsafe paths and
bounds, seeded whole-pair bootstrap, label-swap direction, held preparation and
receipt publication, historical relocation and rebound malformed evidence. These
are regression/synthetic controls, not conformance or native resource qualification.

- **433 full locked harness tests ran: 432 passed and one existing native-peak
  capability test was skipped** (`Ran 433 tests in 198.542s`, `OK (skipped=1)`).
  This includes all **39 new paired-replay methods**.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.687s`, `OK`).
- `git diff --check` and **85 edited-document local links** passed. All **5**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block above was executed directly from this document and
  passed with four observed sessions, two whole bootstrap blocks and no residual
  fixture leases. Separate functional evidence is retained at
  `/tmp/opencode/pt-paired-replay-doc-smoke-o2dxnsxz`.

Direct CLI evidence is retained outside the repository at
`/tmp/opencode/pt-paired-replay-evidence-24w0p3q1`:

| Two planned blocks / four sessions | Execution / inspection / summary exits | Retained session states |
|---|---|---|
| Complete, guarded plans | 0 / 0 / 0 | Four completed-unqualified sessions; bootstrap has two blocks |
| Failed preparation | 1 / 0 / 1 | One aborted plus three not run |
| Later interaction failure | 1 / 0 / 1 | Prior completed session, aborted session and two not run |
| Explicit expected nonzero | 0 / 0 / 0 | Four completed-unqualified observations, not passing-test claims |
| Guard mismatch, interaction timeout, unreleased shutdown, exhausted execution budget | 1 / 0 / 1 each | One aborted plus three not run in each case |
| Unresolved shared identities | 0 / 0 / 1 | Four completed sessions retained, comparison blocked |
| Bounded raw prefix | 0 / 0 / 1 | Four completed sessions with truncation, comparison blocked |

All **ten cases** preserve four sessions/sixteen phases, unchanged source bundle
bytes, null verified independent counts and resources, and false confirmatory
eligibility. Repeated summaries of the same complete evidence/seed are byte-identical.
Eight malformed copies (bad schedule, missing receipt, wrong receipt binding,
early call clock, omitted shutdown with rebound unit/receipt digests, unexpected
later executed session, missing abort and corrupt blob) each make inspection exit
**2** without traceback. A mismatched idle declaration is rejected before output
creation/project execution. At that commit, the card CLI explicitly rejected replay
without creating a card; the linked follow-up adds the separate format. No failed
control is excluded into a favorable estimate.

## Remaining prerequisites

This closes the focused bounded pairing/whole-session-analysis implementation
step, **not WP01 acceptance**. Actual work/generation/reset/input-state validation,
replay resource integration, semantic manifests, scenario/edit
replays, overhead characterization, frozen campaigns and independent review remain
open. Native `memory.peak` is still unavailable here; that gates native peak
qualification, not further implementation. WP02–WP04 completion, the real backend/
oracle and qualification/release gates retain the dependencies in the
[prerequisite register](wp01-status.md). Rust/bridge builds, qualified corpus
materializations and real PT conformance/performance campaigns were not rerun.
