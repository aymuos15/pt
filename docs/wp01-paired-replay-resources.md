# WP01 paired whole-session replay resource campaigns

Status: **bounded pairing/inspection/resource summaries implemented; WP01 remains
open**. Date: **2026-11-09**. Base: `97fb1b6`. This integrates
[whole-session resource diagnostics](wp01-replay-resources.md) with the existing
[matched replay workflow declarations](wp01-paired-replay.md), not the latency
observations or their estimators. There is no PT backend/oracle, qualified support
or release. `pt run` remains unavailable; no test-runner speedup is established.

## A separate diagnostic campaign, one group per complete session

[`paired_replay_resources.py`](../bench/harness/paired_replay_resources.py) fixes a
balanced seeded AB/BA schedule and invokes a **new diagnostic observation once**
per considered arm. Each unit includes its own preparation, fixed ordered
interactions, requested idle waits, future inheriting background descendants,
required shutdown, inner archival/publication/final checks and driver reporting
inside one fresh private cgroup. The next arm does not start concurrently.

Driver bootstrap/harness work is charged, without subtraction. The outer sampler,
counter observer and paired publication/inspection are outside cgroup CPU/memory
totals. The original resource endpoint and charged-memory metric are unchanged;
neither a whole campaign peak nor a sum of process peaks becomes a session peak.
This is diagnostic profiling, not unmodified shipping-mode latency. It does not
rerun or attach resource totals to a retained latency replay.

The new closed
[`paired-replay-resource-v1.schema.json`](../bench/harness/paired-replay-resource-v1.schema.json)
names `kind: paired_replay_resource_campaign`,
`measurement_layer: resource_diagnostic` and
`sample_unit: complete_managed_session_replay`. Existing command, lifecycle,
per-stage resource, latency replay and result-card schemas remain unchanged.

Before output creation or subject work, validation reuses the fixed workflow
declaration contract: separate nonnested resolved arm cwds, matching phase IDs/
order/count, idle waits, expected exit classes, timeouts, execution budgets and
capture policy. Shared `input_seed`, `edit_sequence_sha256` and
`external_state_sha256` remain explicit nullable declarations, not verified work,
applied edits, injected seeds, reset compliance or actual equivalent external state.
The harness never installs/upgrades dependencies, adds hidden collection, changes
plugin policy or imports harness code into actual test workers.

Resource settings fix a common outer watchdog, peak policy, sample interval and
cleanup grace, plus a shared or per-arm existing delegated parent. Different
parent paths do **not** establish equal CPU/memory allocations. No controllers,
limits, unrelated memberships, shared-host caches or host tuning are changed.
The watchdog must cover each execution budget, reserved shutdown and at least
five seconds slack, within the existing one-day limit. As in standalone mode,
outer timeout/cancellation can interrupt shutdown/reporting and leave work unknown.

## Continue unsupported checks; stop failed or uncertain work

| Observed state | Scheduling rule |
|---|---|
| Clean `unsupported`, no subject/driver invoked | Retain the capability check and continue to the next scheduled arm. This allows another arm's usable parent/capabilities to remain visible. |
| Explicit `partial_unsupported`, otherwise complete replay/cleanup/protocol | Retain partial metrics and continue. Peak stays null and complete-accounting stays false. |
| Fully observed unqualified diagnostic | Continue after validation and paired receipt/metadata publication. No qualification or latency claim follows. |
| Failed replay, guard, timeout/cancel, counter/sampler/cleanup failure, lingering worker or missing return | Stop **all later sessions**, without retry, rollback, alternate boundary or favorable subset. |
| Receipt/metadata validation or publication unconfirmed | Stop, retain matching diagnostic evidence where possible, and do not invent confirmed commits. |

The unchanged managed executor attempts the original shutdown once after its
inner plan publication, with reserved timeout even after execution-budget expiry.
A detached worker still alive after matching shutdown sentinels is counted,
recursively killed and **failed**, not ignored as post-timer work. Empty final
population is not proof of successful application shutdown. SIGKILL, host loss,
repeated interruption or storage/cleanup failure cannot guarantee final evidence.

An unsupported resource check is not a failed test or an executed session. A
missing observation is not known not-run work. Failures are never converted into
registered exclusions to make a complete subset look comparable.

## Bound evidence, aborts and clock provenance

The private campaign root contains:

```text
schedule.json                 # frozen matched plans, order, settings, driver and observer declarations
unit-000001-baseline/          # standalone resource request/resource/driver/session tree, if reached
receipt-000001-baseline.json   # returned wrapper receipt, outside the unit's own endpoint
block-000001-baseline.json     # context, plan/receipt byte bindings and observer call/publication clocks
...                           # other actually considered scheduled units
abort.json                    # required after stopping; later not-run rows derive from the fixed plan
```

The plan binds the original output root and trusted driver path/hash/interpreter.
The producer rechecks frozen plan/driver bytes before later calls. Paired metadata
binds exact schedule and wrapper-receipt bytes; that receipt binds the complete
nested resource/replay evidence, driver protocol and raw counter observation.
Every returned request must match its scheduled arm's exact plan, resource
configuration, driver and original unit path. Copies may relocate without
rewriting those historical origin declarations.

`inspect_run.py` explicitly routes this kind to read-only nested inspection. It
also rejects reused private cgroup **paths** and replay invocation IDs across
units. Kernel inode numbers may legitimately be reused after removal, so those
numbers are not counted as independent-session identities. Fresh paths/IDs and
zero initial counters are consistency checks, not proof of independence or a
hostile-process containment boundary.

Paired call clocks and receipt-publication clocks belong to the declared
coordinator/outer-observer process. Their provenance must match the wrapper
receipts; recorded calls cannot overlap or precede earlier receipt persistence.
The next call actually waits for validation and metadata publication too; metadata
does not make a circular claim to time its own commit. Driver-local replay clocks
retain their separate provenance. Inspection never aligns or subtracts timestamps
across those process domains. Campaign publication and these observer clocks do
not become a latency endpoint or an overhead estimate to subtract.

The abort record accounts for missing returns, pre-call plan binding failure,
receipt/session publication failure, interrupted validation or observed unit
failure. A matching diagnostic receipt/session copy can preserve a returned unit
without claiming its paired publication was confirmed. A visible conflicting
copy is rejected. An abort saying `session_failed` needs an actual failed unit;
partial/unsupported/completed observations cannot be silently excluded that way.

If the whole-unit API return is lost, the abort binds any retained nested bytes as
**diagnostics only**. Even an existing `resource.json` or completed inner `unit.json`
cannot manufacture a returned wrapper receipt, known phase outcomes or confirmed
resource metrics. The row remains `harness_error`, underlying session unknown,
with null metrics. An abort-write failure can leave an incomplete uninspectable
bundle; later work still stops and files are not deleted to create success.

Before/after bounded snapshots cover all root records and nested unit/session/blob
files, including diagnostic fragments. Missing/unexplained extras, corrupt/mixed
bindings, nonregular files and observed mutations fail without retries. Inspection
executes no commands and opens neither cgroups nor current worktree files as past
results. Historical hashes/clocks/stat observations are unauthenticated; checks
are not an atomic snapshot or hostile-filesystem boundary. Caller-owned ancestors
remain outside that boundary. No power-loss-durability guarantee is made.

## Complete denominators and resource-only summaries

Every planned arm has one ordered row, including all later not-run sessions.
The report separately exposes:

- `session_status_counts`: **combined diagnostic** outcomes (observed, partial,
  unsupported, failed, harness-error and planned not-run).
- `replay_session_status_counts`: underlying managed outcomes, including completed,
  aborted, known-not-run/unsupported and **unknown** sessions. A failed resource
  boundary can have a completed inner replay; that never makes the unit successful.
- `unit_observation_count`: returned diagnostic API observations, including clean
  unsupported checks; `observed_session_count` counts returned managed receipts,
  including aborted replays, not passing tests.
- Known/unknown/not-invoked **session** and **resource-boundary** invocation counts,
  each summing to the entire planned set. A launched driver does not establish a
  returned managed session or known phase outcomes.
- Complete phase/interaction status counts and phase invocation certainty, including
  known not-run and unknown phases. They sum to the planned ledger, not inferred
  collection/execution occurrences or independent samples.

Paired receipt/session commit flags remain separate from inner outcome and
accounting flags. A returned completed diagnostic whose paired publication failed
can remain `observed_unqualified` in its row, with false commit flags, an aborted
campaign and blocked summary; it is not a successful campaign or qualified unit.

`summarize_run.py` uses exactly the full inspected ordered set. Per arm, CPU usage
shows observed-unit count, unknown-metric count and **observed sum**, including
failed or paired-publication-faulted unit costs. It is not a whole-campaign total
when anything is missing. Memory shows a **maximum per observed whole session**,
never a sum of historical maxima or a simultaneous campaign peak. No observed
values means null, not zero. `unknown_units` includes every missing metric,
including unsupported, known-not-run and lost-return units; their causes stay in
the complete rows. Detailed user/system/event counters also remain in those rows.

A fully observed, fully guarded set with confirmed publications and resolved
shared declarations has summary status `diagnostic_resource_observations`, still
exploratory and **not qualified**. Missing guards, truncation, unresolved pairing,
unsupported/partial support, failure, unknowns or publication/abort uncertainty
make it `blocked`. Recorded declarations do not establish actual matching work.
`all_session_accounting_complete` concerns the diagnostic scope and publication
only; it cannot fill semantic, budget or independence qualification fields.

Both kinds of summary keep **ratio, absolute latency comparison, bootstrap,
campaign-wide peak, isolated idle metrics and per-phase resource metrics null**.
Bootstrap requests are rejected. `per_arm_resources_unit` explicitly names
complete sessions including driver overhead, not the older measurement-stage-only
scope. Verified independent session/block counts remain null and
`confirmatory_eligible` stays false. No successful-subset, tail or release claim
can follow from this profile.

## Bounds, CLI exits and result-card boundary

Version 1 permits **1–64 paired blocks** and the existing **32 interactions per
session**. Repeated declared artifact/raw budget is at most **512 MiB**. Actual
campaign evidence is bounded by **8192 files / 1 GiB**, with each standalone unit's
stricter **4096 files / 512 MiB**, **128 MiB blob**, plan/record/sample and sampling
bounds still applied. Campaign plan/session metadata are at most **1 MiB**;
receipts/abort records are at most **4 MiB**. These are validation/accepted-evidence
limits, not a disk quota or a guarantee that failed storage operations leave no
larger private files. Oversize evidence fails without dropping sessions, trimming
diagnostics or silently truncating records.

Producer exit **0** means an unblocked diagnostic-only summary, **1** means a
complete recorded campaign with blocked/partial/otherwise ineligible observations,
**2** means an accounted abort or invalid input/evidence/publication, and **3** means
all considered sessions were cleanly unsupported without subjects. Inspector exit
**0** means internally consistent evidence, including an accounted abort, not
passing tests. Summary exit **0** means nonblocked diagnostics, **1** means blocked
with retained observations, and **2** means malformed evidence/unsupported options.

At `3857899`, `result_card.py` explicitly refused this new resource-replay kind,
including no-return aborts, rather than relabelling it as legacy resources or
latency. The subsequent [resource-replay card integration](wp01-replay-resource-cards.md)
now provides its own closed recursive format. Existing 21-/24-field card schemas
are unchanged, and all 24 qualification fields stay null in the new cards too.
Routing changes do change reader source bytes: historical cards require their
matching reader revision (`3857899` for this batch's base) for exact
reconstruction. Paths, arguments, reports, raw prefixes and hashes can disclose
secrets; retain privately and review before sharing. Raw evidence is not committed.

## Reproduction: disposable test-owned sessions, not a benchmark

From the repository root:

```sh
directory="$(mktemp -d /tmp/opencode/pt-paired-replay-resources.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
probe = Path("bench/harness/tests/fixtures/replay_resource_probe.py").resolve()
digest = hashlib.sha256(b"ready\n").hexdigest()
def artifact(role):
    return {"path": "report-" + role, "bytes": 6, "sha256": digest}
for arm in ("baseline", "candidate"):
    cwd = root / arm
    cwd.mkdir()
    def step(role):
        return {"id": role, "argv": [sys.executable, str(probe), str(cwd), role, "normal"],
                "timeout_seconds": 5, "idle_before_seconds": 0.3 if role == "interaction" else 0,
                "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6, "expected_stdout_sha256": digest},
                "required_finalization": {"expected_exit_code": 0, "artifacts": [artifact(role)],
                                          "absent": ["lease"] if role == "shutdown" else []}}
    plan = {"schema_version": 1, "kind": "managed_session_replay_plan", "mode": "exploratory_unqualified",
            "sample_unit": "complete_managed_session_replay", "measurement_layer": "managed_replay",
            "timing_endpoint": "managed_session_api_entry_through_shutdown_unit_publication_and_declared_finalization_v1",
            "scope": "fresh_serial_commands_with_declared_state", "cwd": str(cwd), "execution_timeout_seconds": 20,
            "preparation": step("preparation"), "interactions": [step("interaction")], "shutdown": step("shutdown"),
            "finalization": {"expected_exit_code": None, "artifacts": [artifact("shutdown")], "absent": ["lease"]},
            "capture_raw": False, "raw_limit_bytes": 1024}
    (root / (arm + "-plan.json")).write_text(json.dumps(plan))
pairing = {"input_seed": 0, "edit_sequence_sha256": hashlib.sha256(b"fixture-no-edits").hexdigest(),
           "external_state_sha256": hashlib.sha256(b"fixture-empty-state").hexdigest()}
(root / "pairing.json").write_text(json.dumps(pairing))
PY
resource_options=()
if [ -n "${PT_BENCH_CGROUP_PARENT:-}" ]; then
  resource_options=(--cgroup-parent "$PT_BENCH_CGROUP_PARENT" --allow-missing-peak)
fi
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/paired_replay_resources.py --output "$directory/run" --baseline-plan "$directory/baseline-plan.json" --candidate-plan "$directory/candidate-plan.json" --blocks 1 --seed 1 --outer-timeout 30 --pairing-json "$(cat "$directory/pairing.json")" "${resource_options[@]}" > "$directory/execution.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_run.py "$directory/run" > "$directory/inspection.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/summarize_run.py "$directory/run" > "$directory/summary.json"
```

With no parent, the producer intentionally exits **3**, inspection exits **0** and
the blocked summary exits **1**: two sessions/six phases are not invoked and all
resource metrics are null. For an explicit partial native diagnostic, set
`PT_BENCH_CGROUP_PARENT` to an existing writable delegated memory-enabled parent;
the script deliberately adds `--allow-missing-peak`. Remove that flag to require
native peak. Never reconfigure a shared host or adopt existing services to make
the example pass. The fixture's own preparation/shutdown manages a 64 MiB worker
across idle and charges another 32 MiB during shutdown. This is not a corpus,
pilot or performance comparison, and these two observations are not qualified
independent sessions.

## Verification and retained adverse evidence

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_replay_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

**39 targeted tests passed** (`Ran 39 tests in 179.794s`, `OK`), including five
capability-gated native controls. The remaining 34 use synthetic counters/
enrollment with real isolated commands, refusal paths and evidence/publication
faults; synthetic peaks are not native qualification. A final focused rebound
control also passed (`Ran 1 test in 8.670s`, `OK`), rejecting reused group paths
and invocation IDs even after request/transport/receipt bindings are recomputed.
The final complete suite includes the separate underlying-session/boundary counts.

Controls cover complete/unsupported/partial/mixed arms, preparation/interaction/
shutdown failures, deadline, leftover workers, native cancellation, lost returns
before/after unit commit, publication and abort faults, plan/driver mutation,
settings/provenance/order, omitted shutdown, complete denominators, diagnostic-only
analysis, strict types, unsafe paths/bounds and historical relocation. No subject
is replayed by inspection or to repair an adverse result.

Retained development failure: the initial **38-test** run had **two assertion
failures** in native controls. A one-block seed **0** chooses **candidate then baseline**;
those tests incorrectly assumed baseline ran first. The observed prior partial
candidate plus failed baseline, and partial candidate before unsupported baseline,
were consistent with the actual frozen schedule. The tests now explicitly use
one-block seed **1** for baseline-first cases; scheduling policy was not changed
and no adverse case was removed. A fifth native control adds cancellation with
unknown first-session outcomes and later not-run work.

- **548 full locked harness tests ran: 547 passed and one existing native-peak
  capability test was skipped** (`Ran 548 tests in 543.664s`, `OK (skipped=1)`).
  This includes all **39 new paired-resource controls**, their final separate
  invocation/status denominators and the rebound group/invocation identity checks.
  All five new native controls ran on this host; no native peak qualification follows.
- **68 contract/audit tests passed** (`Ran 68 tests in 7.998s`, `OK`).
- `git diff --check` and **132 edited-document local links** passed. All **5**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block was executed directly from this document in documented
  no-parent mode. It retained two not-invoked sessions/six phases, empty worktrees,
  null metrics and a blocked summary; read-only inspection returned **0**.
  Separate evidence is at `/tmp/opencode/pt-paired-replay-resource-doc-smoke-ww_8_uzn`.
- A saved standalone `97fb1b6` resource diagnostic still reconstructs to exactly
  its earlier summary (completed replay, partial unsupported resources, null peak).
  That scope was not changed or relabelled by this pairing integration.

Direct CLI/API production and read-only CLI evidence is outside the repository at
`/tmp/opencode/pt-paired-replay-resource-evidence-__1r53or`:

- **13 source cases**: one non-invoked/no-parent campaign, seven explicitly
  synthetic campaigns and five native CLI campaigns. Every inspection returned
  **0** as unqualified consistency, preserving the entire two- or four-session
  planned ledger and unchanged source bytes. Repeated summaries were byte-identical.
- Synthetic complete diagnostics keep all four sessions but still have null
  latency/ratio/bootstrap/campaign peak. Partial and mixed support remain blocked;
  failed preparation retains one failed and three not run. Missing return before
  observation or after unit commit retains one unknown session, three not run and
  null unconfirmed metrics. A paired receipt-publication fault cannot invent a commit.
- Native strict mode records **two unsupported sessions**, no subjects and null
  metrics because `memory.peak` is absent here. Explicit partial mode observes
  **both complete sessions** with idle workers and charged shutdown in distinct
  removed groups, retaining null peak and false complete-accounting. No native
  peak support or resource-budget qualification is claimed.
- Native leftover-worker control records **failed + not run**, even with matching
  inner shutdown sentinels, after recursive kill/removal. An unsupported baseline
  still allows a partial candidate; a later failed interaction preserves the prior
  partial session plus failure and two later not-run sessions. Failed-unit CPU
  remains in the descriptive observed sum. Owned native groups were removed.
- **Twelve malformed copies** (schedule, missing/wrong receipt binding, early call
  clock, omitted shutdown with rebound transport/digests, reused group, invented
  zero peak, wrong coordinator provenance, missing abort, unexpected later unit,
  extra file and false failure abort) each made inspection exit **2**, without
  traceback. At `3857899`, unsupported bootstrap and resource-card requests also exit **2**;
  a too-small watchdog fails before output creation or subject work.

## Remaining prerequisites

This closes the focused **paired whole-session resource scheduling/inspection/
summary** step, not WP01 acceptance. The later
[evidence-bound resource-replay cards](wp01-replay-resource-cards.md) now preserve
all outcomes and qualification gaps through offline reconstruction. Native peak qualification,
resource-budget equivalence, idle-only attribution, actual semantic/work/generation/
input/reset validation, scenario/edit replays, observer-overhead characterization,
frozen campaigns and independent review remain open. Missing `memory.peak` gates
peak qualification, not further implementation.

WP02–WP04 completion, the real pytest backend/oracle and qualification/release
dependencies remain in the [prerequisite register](wp01-status.md). Rust/bridge
builds, qualified corpus materializations and real PT conformance/performance
campaigns were not rerun by this harness-only integration.
