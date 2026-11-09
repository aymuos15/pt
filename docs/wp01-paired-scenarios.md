# WP01 paired scenario/reset/edit evidence

Status: **bounded paired validation implemented; WP01 acceptance remains open**.
Date: **2026-11-09**. Base: `a7f76e8`. This integrates the existing
[declared-file scenario validator](wp01-scenario-replay.md) into a distinct paired
campaign, not into shipping-mode latency or native resource measurements. No PT
backend, semantic oracle, representative corpus qualification or speedup is supplied.
`pt run` and the original work-package/release gates remain open.

## Freeze once, then validate each arm's actual observations

[`paired_scenarios.py`](../bench/harness/paired_scenarios.py) uses a new closed
[`paired-scenario-v1.schema.json`](../bench/harness/paired-scenario-v1.schema.json).
The campaign kind is `paired_scenario_replay_campaign`; its layer remains
`scenario_validation` and its unit remains `complete_scenario_edit_replay`.
It schedules 1–64 balanced randomized AB/BA blocks with a declared integer seed.
Odd counts differ by one; order is never rewritten to force baseline first.

Every arm has a separate, nonnested, caller-owned worktree. Payload source,
worktrees and new evidence root must also be separate/nonnested. Explicit
**`--apply`** is mandatory. Commands are argv arrays in fresh serial processes,
with inherited environment and no hidden collection or dependency mutation.

Before effects, both standalone plans and every shared expected input blob are
validated. Paired declarations must match **exactly**: scenario and all cache axes,
input seed, reset bytes/mode/presence, ordered edit preconditions/results, request
IDs and delivered input files, execution/request/shutdown budgets and expected
exit codes. Commands, guards and required reports may differ by arm and stay bound
to that arm's exact plan; their equality is not assumed. No language-aware edit
classification, external-state identity or equal-work permission is inferred.

Shared payload bytes are frozen into the campaign's `payloads/` **before any arm
runs**, with an exact content inventory and a domain-separated canonical workflow
digest (`pt:paired-scenario:declared-workflow:v1\n`). Later changes to the original
payload source cannot alter a campaign. Frozen plan/payload fingerprints are checked
before each API call. A changed frozen input stops later calls without repair;
corrupt bytes still make historical inspection fail, rather than becoming an
acceptable exclusion. A byte-identical identity replacement can retain an explicit
pre-call binding failure without inventing subject work.

Each scheduled arm creates one **new standalone scenario unit**. Its interval
includes the explicit reset, guarded edits, request-input delivery, full pre/post
tracked-file observations, requests, shutdown and evidence publication. Request
and transition rows are correlated diagnostics, never independent samples. A
new evidence directory or matching files does not establish independently reset
services, caches, environments, Python state or complete program inputs.

The standalone profile is unchanged: 32 tracked ordinary single-link files,
create/replace/delete and mode effects, guarded edit chains and one seed-bearing
request JSON path. Effects are sequential and nontransactional. Partial installation
may survive an error; no rollback, automatic repair, replay or retry occurs. S6
environment changes, S7 affected-watch and S9 OS-cold remain unsupported before
effects. All their planned units are checked and retained without subject execution.

## No favorable subset, recovered return or fabricated reset

Clean unsupported units continue. A failed or unconfirmed unit **stops all later
sessions**, including the other arm and later blocks. The frozen schedule and
required abort record retain every not-run session, request, phase and file effect.
Shutdown is attempted only as specified by the standalone unit; an outer lost
return never triggers a second cleanup/session invocation.

Reports distinguish:

- **Returned scenario observations**: actual reset phase, full pre/post tracked
  file metadata and effect ledger; per-request delivered-input metadata, expected
  input and returned input-operation status; request and shutdown invocation
  certainty. These are read from the validated unit, not projected from expected
  reset values. Dirty arm inputs can differ even when their reset targets match.
- **Inner command-return loss**: the whole scenario can return an aborted ledger
  with one unknown request, later requests not run and known reset/shutdown evidence.
  A complete command sample is only a diagnostic fragment when its return was lost.
- **Whole scenario-return loss**: `harness_error` plus all requests/phases/effects
  `unknown_unobserved`. Reset evidence and observed input metadata remain null;
  shutdown invocation remains unknown. Files left by the attempted API call are
  recursively inventoried but **never reconstructed as returned observations**.
  Even a complete-looking `unit.json` cannot recover success or a confirmed reset.
- **Paired receipt/metadata publication uncertainty**: the returned observations
  remain visible, but publication flags stay false and the campaign aborts. A
  visible matching copy is diagnostic, not proof that its publisher returned.
  A conflicting visible copy fails inspection. A failed abort write leaves an
  unexplained prefix, not an approved shortened campaign.
- **Known skips**: every later session remains known not called after abort.
  `unit_call_attempted` describes the coordinator API-call attempt, not proof that
  a subject process started. Request/shutdown certainty and file effects are separate.

The denominator for file effects is each reset target plus each declared edit and
each input-file delivery. Counts retain `applied`, `unchanged`, `unknown`, `not_run`
and `unknown_unobserved` as applicable. A complete post-state never converts a lost
effect return into `applied`; input observation is distinct from a returned effect.
Session, request, phase and file-effect counts all sum to their entire plans.

## Retained layout and offline readers

```text
schedule.json                      # exact arm plans, schedule, workflow and payload bindings
payloads/<sha256>                   # shared immutable expected bytes, frozen before effects
session-NNNNNN-{arm}/               # standalone scenario plan, phases, command samples, blobs
receipt-NNNNNN-{arm}.json           # external returned standalone receipt
block-NNNNNN-{arm}.json             # context, receipt binding and call/publication clocks
abort.json                         # when required: cause, context and attributable diagnostics
```

`inspect_run.py` dispatches lazily to recursive paired scenario inspection. It
validates closed schemas, exact scheduled arm plans, frozen inventories/digests,
nested standalone ledgers/receipts, command bindings, call enclosure and serial
receipt-publication order, abort evidence and all planned rows. Missing evidence,
extra evidence after abort, mismatched arms, omitted reset/edit/request/shutdown,
bad input snapshots, corrupt blobs and contradictory publication copies are rejected.
Before/after fingerprints detect observed history mutation without retries.

`summarize_run.py` returns the full ledger and per-arm counts of returned units,
complete scenarios, matched declared-file resets and observed expected payloads.
Subset, duplicated, reordered and step-relabeled observations are refused.
`ratio`, `absolute_latency_ns`, `bootstrap` and `resource_observation` are null;
bootstrap requests are rejected, not ignored. Existing result-card tools explicitly
refuse this kind rather than relabel it as a latency/resource card. All six standalone
qualification fields remain mandatory nulls: complete input domain, loaded code,
semantic equal work, reset equivalence, generation validity and independent units.
Complete file observations do not mean tests passed or a runner qualified.

Readers run **no subjects, resets or edits**, use no later worktree state and do
not query native resource controllers. Byte-identical evidence may relocate. These
are unauthenticated historical assertions, not hostile-directory protection or an
atomic filesystem snapshot. Caller-owned root ancestors, disappearance races,
SIGKILL, host/storage loss and repeated interruption cannot guarantee observation
or cleanup. Commands are not sandboxed from other files or frozen evidence.

Clock arithmetic uses only the declared same coordinator-process API calls.
The standalone scenario endpoint is unchanged. Initial campaign scheduling,
shared-payload freezing and paired receipt/metadata persistence are **outside**
that endpoint; no observer overhead is subtracted. Receipt persistence must end
before the next call. Metadata writes are serial bookkeeping, with no invented
separate timestamp or cross-process alignment. No edit-to-valid-result, native
resources, overhead characterization or end-to-end performance claim is implied.

Limits are **1–64 blocks**, **8192 retained files / 1 GiB actual campaign evidence**,
**512 MiB repeated declared input/artifact budget**, **1 MiB schedule/metadata**,
**4 MiB paired receipts/aborts**, plus all stricter standalone and blob limits.
These are accepted-evidence bounds, not filesystem quotas. Overflow fails without
trimming outcomes. Evidence may contain sensitive paths, inputs, errors or reports;
retain privately, review before sharing and do not commit raw campaigns.

Producer CLI exits: **0** complete unqualified declared-file observations;
**3** all units clean unsupported; **2** aborted, invalid or unconfirmed campaign;
**1** any other blocked complete campaign. A consistent accounted abort inspects
with **0**; malformed evidence inspects with **2**. Summary exits **0** for complete
declared-file observations, **1** for blocked and **2** for malformed evidence.
None is a backend/test-pass or qualification decision.

## Reproduce with disposable file worktrees

From the repository root (no PT executable or special host privileges needed):

```sh
directory="$(mktemp -d /tmp/opencode/pt-paired-scenarios.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
payloads = root / "inputs"
payloads.mkdir()
def value(raw):
    digest = hashlib.sha256(raw).hexdigest()
    (payloads / digest).write_bytes(raw)
    return {"bytes": len(raw), "sha256": digest, "mode": 0o600}
old, new = value(b"old\n"), value(b"new\n")
payload = value(json.dumps({"schema_version": 1, "request_id": "change", "input_seed": 17,
                            "data": {"expected": "new\n"}}).encode())
def command(code):
    return {"argv": [sys.executable, "-c", code], "timeout_seconds": 5,
            "guard_expectations": {"expected_exit_code": 0, "expected_stdout_bytes": 6,
                                   "expected_stdout_sha256": hashlib.sha256(b"ready\n").hexdigest()},
            "required_finalization": {"expected_exit_code": 0, "artifacts": [], "absent": []}}
code = ("import json; from pathlib import Path; p=json.loads(Path('payload.json').read_text()); "
        "assert Path('value.txt').read_text()==p['data']['expected']; print('ready')")
sys.path.insert(0, str(Path("bench/harness").resolve()))
from scenario_replay import ENDPOINT, LIMITATIONS
axes = ("coordinator", "framework_seed", "pt_metadata", "python_bytecode", "filesystem_cache",
        "application_service", "dependency_observations", "source")
for arm in ("baseline", "candidate"):
    cwd = root / arm
    cwd.mkdir()
    plan = {"schema_version": 1, "kind": "scenario_edit_replay_plan", "mode": "exploratory_unqualified",
            "measurement_layer": "scenario_validation", "sample_unit": "complete_scenario_edit_replay",
            "timing_endpoint": ENDPOINT, "cwd": str(cwd), "input_seed": 17, "execution_timeout_seconds": 20,
            "scenario": {"id": "S3", "cache_state": {key: "unknown" for key in axes}},
            "reset": [{"path": "payload.json", "value": None}, {"path": "value.txt", "value": old}],
            "requests": [{"id": "change", "edits": [{"path": "value.txt", "before": old, "after": new}],
                          "input": {"path": "payload.json", "value": payload}, "command": command(code)}],
            "shutdown": command("print('ready')"), "limitations": LIMITATIONS.copy()}
    (root / (arm + ".json")).write_text(json.dumps(plan))
PY
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/paired_scenarios.py --baseline-plan "$directory/baseline.json" --candidate-plan "$directory/candidate.json" --payloads "$directory/inputs" --output "$directory/run" --blocks 2 --seed 0 --apply > "$directory/producer-summary.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_run.py "$directory/run"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/summarize_run.py "$directory/run"
```

This is a real disposable file/process mechanism check, not a benchmark, corpus
materialization or PT conformance run. The producer creates four scenario units;
each independently performs its declared file reset before one edit/input/request
and shutdown. Delete nothing to rerun it: use a new directory instead. Offline
readers never create another unit or repair state.

## Verification and remaining prerequisites

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_scenarios.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

Development evidence: the initial two-block smoke retained four sessions, eight
requests, 24 phases and 48 file effects, with actual per-arm reset/input projections.
The first targeted run retained **39 tests, four failures**: three fixture assertions
incorrectly assumed AB order for seed 0's odd block (which correctly chooses BA),
and the generic summary CLI lacked this new complete status in its exit mapping.
The mapping and fixture seeds were corrected; the scheduler was not relaxed. A
separate BA-failure regression retains the candidate-first behavior.

The expanded **42 targeted tests passed** (`Ran 42 tests in 76.996s`, `OK`), with
ResourceWarning treated as an error. They cover exact paired declarations, early
payload freezing, observed dirty reset inputs, partial mutations, inner/whole
missing returns, publication/abort faults, unsupported/failed/not-run denominators,
mutation/relocation, changed clocks/bindings, malformed histories, CLI routing and
refusal of bootstrap/card relabelling. Four requested fresh pytest invocations
across two arms each emitted exactly one import/collection sentinel and one test
call, with distinct PIDs. Both arms used the same explicitly controlled test-only
plugin-autoload environment; this is not a general plugin or semantic qualification.

- **676 full locked harness tests ran: 675 passed and one existing native-peak
  capability test was skipped** (`Ran 676 tests in 770.506s`, `OK (skipped=1)`).
  This includes all **42 paired-scenario controls**. The capability skip is not
  native peak support qualification.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.807s`, `OK`).
- `git diff --check` and **109 edited-document local links** passed. All **5**
  changed/new Python files parse with Python 3.10 grammar (not execution support).
  Existing schemas, standalone scenario sources and dependency/lock/toolchain/
  support pins are unchanged.
- The reproduction block was executed directly from this document: **4 sessions,
  4 requests, 16 phases and 16 file effects**, with identical producer/offline
  summaries, exact expected bytes and six null qualifications. Evidence:
  `/tmp/opencode/pt-paired-scenarios-doc-smoke-51y9jml8`.
- Four retained historical resource cards reconstruct with their matching
  `765c043` reader, preserving unsupported/partial/failed/not-run/unknown outcomes
  and missing native metrics. Four prior standalone scenario summaries reconstruct
  unchanged with the current unchanged standalone reader. No subjects were rerun
  and history was not rewritten. Evidence:
  `/tmp/opencode/pt-paired-scenario-history-z5mr8fkd`.

Direct CLI/API evidence is retained privately outside the repository at
`/tmp/opencode/pt-paired-scenario-evidence-cl3bevoq` (generator script:
`/tmp/opencode/build-paired-scenario-evidence.py`):

- **17 campaigns**: nine producer CLI cases and eight explicitly injected API
  fault cases. Each retains all **4 sessions / 8 requests / 24 phases / 48 file
  effects**. The cases cover complete/failed/candidate-failed/expected-nonzero,
  unreleased shutdown, deadline, three unsupported profiles, partial reset/edit,
  inner return loss, whole return loss before/after commit, unconfirmed receipt/
  metadata publication and byte-identical frozen payload identity replacement.
- Every valid bundle inspected with exit **0**. Complete and expected-nonzero
  summaries exited **0** as unqualified observations; the other fifteen summaries
  exited **1** as blocked. Repeated summaries were identical and offline reads
  left retained bytes/fingerprints unchanged. All qualification fields stayed null;
  no latency/resource statistic was invented.
- Failed requests remain **failed + not run**, and later sessions remain not
  called. A failed candidate retains the earlier baseline observations. Partial
  reset/edit return loss retains **one unknown effect**, even though installation
  occurred. Inner command return loss retains **one unknown request**, with its
  returned reset evidence separate from command certainty.
- Whole-unit return loss before and after complete-looking publication both keep
  **one unconfirmed API call, two unknown requests, six unknown phases and twelve
  `unknown_unobserved` effects**; the other three sessions remain not called.
  Reset/input observations stay null. The after-commit diagnostic inventory is
  bound, not used to recover outcomes. Unconfirmed paired publication instead
  preserves returned reset/request evidence with false publication flags and an
  abort; those observations are not erased or silently promoted to a confirmed run.
- All three S6/S7/S9 campaigns retain four unsupported units and 48 known-not-run
  effects. Missing `--apply` exits **2** before creating output or starting a unit.
- **16 malformed copies** each inspect with exit **2**, without traceback: omitted
  reset/transition/shutdown/input snapshot, wrong pre-request bytes, reordered
  operations, early clock, relabelled arm, overlapping calls, missing receipt,
  changed lost-return diagnostics, later work after abort, missing abort,
  qualification promotion, corrupt frozen payload and a false failure exclusion.
  Nested/outer inventory and byte bindings were updated where applicable, so
  recomputing a digest cannot hide contradictory evidence or select a favorable
  subset. No malformed case triggers a subject rerun.
- Direct summary-bootstrap and result-card CLI attempts each exit **2** with an
  explicit refusal, without producing a card or rerunning subjects. A complete
  scenario bundle is not relabelled as latency/resource evidence.

This integration closes bounded paired **declared-file evidence** work only.
Qualified shipping latency/resource scenario linkage and real product request/edit
endpoints, full loaded-input/environment/cache/service/reset evidence, semantic
work/generation checks, non-file finalization, artifact/materialization identity,
native peak capability, resource budgets, observer-effect measurements, independent
units, frozen corpus/campaign governance and independent review remain open.
WP02–WP04 completion, WP03's oracle, WP05's backend and release dependencies remain
as recorded in the [prerequisite register](wp01-status.md). No new optimization,
Serc integration, dependency/pin change, bridge build or Rust qualification is claimed.

Existing latency/resource schemas and their null qualification contracts are
unchanged. Routing/card refusal changes reader-source bytes, so historical cards
require their matching revision (`a7f76e8` is this batch's base); never rewrite
old cards to fit a changed reader or rerun their subjects to fabricate missing returns.
