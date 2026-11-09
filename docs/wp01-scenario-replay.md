# WP01 declared-file scenario, reset and edit validation

Status: **bounded execution/historical validation implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `765c043`. This adds concrete reset/edit/input evidence
where the earlier [managed replay](wp01-managed-replay.md) and shared pairing
declarations did not verify those files. It is **correctness-instrumented scenario
validation**, not a semantic oracle, shipping-mode benchmark or qualified runner.
`pt run`, WP02–WP04 completion and qualification/release remain unavailable.

## Exact declared-file inputs, not a complete program-input claim

[`scenario_replay.py`](../bench/harness/scenario_replay.py) uses the new closed
[`scenario-replay-v1.schema.json`](../bench/harness/scenario-replay-v1.schema.json).
It records `measurement_layer: scenario_validation` and
`sample_unit: complete_scenario_edit_replay`; latency estimators explicitly refuse
either label. The ten scenario IDs S0–S9 and all eight cache-state axes must be
present. Axes may explicitly be unknown; naming a warm/cold policy does not prove
that cache, coordinator, service or generation state was established.

The supported scope is a finite explicit set of **ordinary, single-link files**
under one caller-owned cwd. Each expected value binds exact SHA-256, bytes and
permission mode; null means that final path must be absent. Missing parent
directories, symlinks, hardlinks, FIFOs, oversized files and unreadable observations
are **unknown**, never fabricated absence or zero bytes. Parent directories must
already exist. Ancestors of the root remain caller-owned; this is not a sandbox.

The plan declares:

- One sorted unique reset target per tracked file, including expected absences.
  Reset is an executable, explicit file-effect contract, not an assumed successful
  arbitrary script. It creates/replaces/removes only those final names.
- An integer input seed and 1–16 ordered request IDs. Each request has a sorted
  guarded edit list, one input-file delivery and an exact argv/timeout/exit/artifact/
  optional stdout guard contract. No shell interpolation is introduced.
- Each edit's exact before/after content/mode/presence. The complete chain must
  agree with the reset and previous transitions before execution. Creates, deletes,
  replacements, mode changes and edit-and-revert sequences are explicit; no-op
  edits, duplicate/out-of-domain paths and input/edit path overlap are rejected.
- A single tracked request-input path, delivered before each request. Its retained
  JSON bytes contain exactly `schema_version`, `request_id`, `input_seed` and
  `data`; ID/seed must match the frozen plan. The bytes are actually installed and
  observed, not merely copied into a pairing declaration. Whether the subject
  consumed the file remains unverified.
- A required original shutdown command, with its own timeout (at most 60 seconds)
  and expected exit zero. Requests may explicitly expect nonzero outcomes.

All expected reset/edit/input blobs are validated and frozen before effects.
Payloads, worktree and evidence roots must be separate and nonnested. The CLI
requires **`--apply`** to authorize file mutations. Default behavior never mutates
the worktree. No controller/cache tuning, environment installation, pre-existing
service adoption, plugin changes or hidden collection is performed.

S0/S1/S2 reject source-edit lists; S3/S4/S5 require at least one declared edit.
These are bounded declaration checks, not a language-aware classifier of test,
application or configuration semantics. S8 can retain explicit failure-oriented
requests. **S6 environment changes, S7 affected-watch sequences and S9 OS-cold
procedures are unsupported**: all planned phases remain known not run, no reset,
request or shutdown starts, and no shared-host state is changed. The selected
scenario label never upgrades this finite-file profile to full scenario qualification.

## Explicit effects and a complete ledger

Each run has one reset phase, a transition and request phase for each request,
then one shutdown phase. Every considered phase observes **all tracked files
before and after**. Observed bytes, including dirty reset inputs and mismatches,
are retained as blobs. Exact content, size and mode are compared; same-size/
same-mtime changes cannot pass merely because timestamps match.

Reset/transition effects are sequential and **not transactional**. Their operation
ledger distinguishes returned applied, returned unchanged, unknown return and
known not run. Preconditions and target fingerprints are checked before an effect.
New-file installation uses Linux no-overwrite rename; an appeared final name is
not overwritten. Existing-file replacement/deletion uses safe relative lookup
and immediate identity checks, not a hostile-process atomic compare-and-swap.
Private staging files are cleaned without removing successful final effects.

A partial reset/edit, unknown file observation or returned mismatch stops all
later non-shutdown phases. No retry, rollback, repair, alternate command or favorable
subset is allowed. An error after an installed file can leave its bytes known in
the post-snapshot while the operation's API return remains **unknown**; matching
post-state does not manufacture a confirmed return. Unlisted files are untouched
by the harness and outside this input-domain assertion. Subject commands are not
contained from changing them.

Every request must begin with the exact declared state from the reset/edit chain.
After the request, tracked files must still match that state; a subject modifying
them fails validation even with matching stdout. This profile does not silently
allow mutable tracked inputs. Reports, leases and other declared command outputs
must be outside the tracked file set. Shutdown can run after partial state and
must not change tracked input files; its output/artifact/absence contract remains
separate from input observations.

The original shutdown is attempted **once after successful plan publication**,
even if reset, edits, requests or the execution budget fail. It has a reserved
command budget. No shutdown is invoked for a clean unsupported profile before
effects. Host loss, SIGKILL, repeated interruption, inaccessible storage and
uninterruptible I/O cannot guarantee cleanup or a returned receipt. File absences
and process groups do not prove external-service release or hostile containment.

Requests use the existing independent lifecycle observer, preserving argv, cwd,
inherited environment, drainage/reaping, guards, report archival and publication.
A missing command return before or after a complete-looking sample stays unknown;
the subject is not run again to recover an observation. Its attributable files
are bound as diagnostic fragments only. Missing returns are not known non-invocation;
known skips require a prior failure, exhausted budget, unsupported profile or
pre-call plan-binding failure. All later requests remain in the denominator.

## Endpoint, retained evidence and offline reconstruction

The diagnostic endpoint is
`scenario_api_entry_through_explicit_reset_edits_requests_shutdown_and_evidence_publication_v1`.
Its harness-process monotonic interval includes validation, payload freezing,
plan publication, snapshots, reset/edit/input operations, requested commands,
shutdown and unit publication/read-back/retained-input checks. Hashing and observer
work are charged, never subtracted. This is **not** watch edit-to-valid-result or
shipping request latency, and it does not measure native resources.

The finite execution budget starts at API entry and limits starting phases and
request command waits; filesystem/hash/fsync work is not hard-wall bounded by it.
Each command timeout is the lesser of the declared timeout and remaining budget;
shutdown uses its reserved original timeout. The calculation has a recorded local
timestamp. A budget exhausted during input observation prevents command launch.
Only serial same-process enclosure/order arithmetic is used; no driver clock is
silently aligned with a separate process's clock.

The private evidence bundle contains:

```text
plan.json             # frozen scenario, exact reset/edit/input/command declarations
command-NNNN.json     # actual returned request/shutdown lifecycle samples, if reached
unit.json             # complete reset/transition/request/shutdown ledger and snapshots
blobs/                # expected and observed file/input bytes plus command report artifacts
```

Save the returned stdout receipt **outside** the bundle. It binds plan and unit
bytes, clocks, publication errors, status and explicit null qualifications. If
unit publication is unconfirmed, a bounded diagnostic unit may remain in the
receipt; a visible conflicting copy is rejected. No receipt means no confirmed
whole-run return, even if files exist. Evidence is private/no-overwrite, not
authenticated or power-loss durable.

`inspect` validates closed schemas and strict JSON tokens, canonical plans and
edit chains, all expected/observed blobs, exact snapshot path sets, state verdicts,
operation order and unknown/skipped effects, nested command contracts, clocks/
budgets, final shutdown, attributable fragments and terminal outcome. It rechecks
before/after evidence fingerprints without retries. It opens **no current worktree
file**, invokes no reset/edit/request and does not replace history with a later
state. Byte-identical evidence can relocate. Hash/stat/absence/clock assertions
remain unauthenticated and are not an atomic snapshot or executed-code identity.

`compare` inspects two retained runs and checks exact declared scenario/cache axes,
reset values, edit order/preconditions, input seed/payloads and timeout/expected-exit
policies, with separate nonnested arm working directories. Both complete file-domain
observations are retained; different or incomplete inputs make the comparison
blocked rather than selecting successful requests. No actual independent reset,
semantic equivalence, loaded-code or artifact qualification follows from matching
declared files. The standalone comparison is not paired scheduling or a new
latency/resource/card profile. The subsequent [paired scenario integration](wp01-paired-scenarios.md)
adds a distinct campaign with frozen payloads and per-arm observations, without
relabelling earlier latency/resource evidence.

All six qualification fields remain required **null**: complete input domain,
actual loaded code, semantic equal work, reset equivalence, generation validity
and independent units. Ratios/bootstrap are null. Cache axes and input-file
delivery are not proof of arbitrary code/data/environment consumption. Implicit
bytecode/import caches, plugins, native dependencies and external services remain
outside this finite-file claim; actual pytest semantics require WP03/WP05.

Bounds: **32 tracked files**, **16 requests / 34 phases**, **1 MiB per input
file**, **128 MiB declared input/artifact budget**, **2048 blob files / 128 MiB**,
**256 KiB plan**, **3 MiB published unit**, **4 MiB external receipt** (including any
unconfirmed diagnostic unit), and the existing stricter
command/finalization and complete evidence limits. Growth/oversize is rejected,
never trimmed or dropped. These are accepted-evidence limits, not a disk quota.
Paths, commands, input bytes, errors and reports may contain secrets; retain privately
and review before sharing. Raw evidence is not committed.

CLI exits: `run` returns **0** for complete unqualified file-domain validation,
**1** for a retained aborted run, **2** for invalid input/evidence/publication,
and **3** for clean unsupported/no-effects profiles. `inspect` returns **0** for
consistent evidence, including an accounted abort, otherwise **2**. `compare`
returns **0** for matching unqualified file-domain observations, **1** for blocked
comparison and **2** for malformed evidence. None means passing tests or acceptance
of WP01, reset equivalence, complete scenarios or the PT backend.

## Reproduction: disposable explicit file edits

From the repository root:

```sh
directory="$(mktemp -d /tmp/opencode/pt-scenario-replay.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
cwd, payloads = root / "work", root / "payloads"
cwd.mkdir()
payloads.mkdir()
def value(raw):
    digest = hashlib.sha256(raw).hexdigest()
    (payloads / digest).write_bytes(raw)
    return {"bytes": len(raw), "sha256": digest, "mode": 0o600}
old, new = value(b"old\n"), value(b"new\n")
payload = value(json.dumps({"schema_version": 1, "request_id": "change", "input_seed": 17,
                            "data": {"expected": "new\n"}}).encode())
guard = {"expected_exit_code": 0, "expected_stdout_bytes": 6,
         "expected_stdout_sha256": hashlib.sha256(b"ready\n").hexdigest()}
def command(argv):
    return {"argv": argv, "timeout_seconds": 5, "guard_expectations": guard,
            "required_finalization": {"expected_exit_code": 0, "artifacts": [], "absent": []}}
code = ("import json; from pathlib import Path; "
        "p=json.loads(Path('payload.json').read_text()); "
        "assert Path('value.txt').read_text()==p['data']['expected']; print('ready')")
axes = ("coordinator", "framework_seed", "pt_metadata", "python_bytecode", "filesystem_cache",
        "application_service", "dependency_observations", "source")
sys.path.insert(0, str(Path("bench/harness").resolve()))
from scenario_replay import ENDPOINT, LIMITATIONS
plan = {"schema_version": 1, "kind": "scenario_edit_replay_plan", "mode": "exploratory_unqualified",
        "measurement_layer": "scenario_validation", "sample_unit": "complete_scenario_edit_replay",
        "timing_endpoint": ENDPOINT, "cwd": str(cwd), "input_seed": 17, "execution_timeout_seconds": 20,
        "scenario": {"id": "S3", "cache_state": {key: "unknown" for key in axes}},
        "reset": [{"path": "payload.json", "value": None}, {"path": "value.txt", "value": old}],
        "requests": [{"id": "change", "edits": [{"path": "value.txt", "before": old, "after": new}],
                      "input": {"path": "payload.json", "value": payload}, "command": command([sys.executable, "-c", code])}],
        "shutdown": command([sys.executable, "-c", "print('ready')"]), "limitations": LIMITATIONS.copy()}
(root / "plan.json").write_text(json.dumps(plan))
PY
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/scenario_replay.py run --plan "$directory/plan.json" --payloads "$directory/payloads" --output "$directory/run" --apply > "$directory/receipt.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/scenario_replay.py inspect --directory "$directory/run" --receipt "$directory/receipt.json"
```

This runs one test-owned command after explicit reset/edit/input delivery, then
shutdown. It is not a corpus, pilot, native resource pass or product benchmark.
Omitting `--apply` fails before output creation or effects. To compare existing
retained runs, use `compare --baseline <run> --baseline-receipt <receipt.json>
--candidate <run> --candidate-receipt <receipt.json>`; it does not execute either arm.

## Verification and remaining gates

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_scenario_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The first **33 targeted controls passed** (`Ran 33 tests in 16.562s`, `OK`). They
exercise actual file and command effects, not mocked native resource counters.
Development failure retained: an initial pre-execution smoke rejected a malformed
new schema (one missing closing brace). No reset/request ran; schema closure was
corrected before the targeted suite. Review then tightened missing-command
certainty, permitted only attributable missing-return command fragments, bounded
blob evidence on inspection, and added comparison/real-pytest controls.

The expanded **43 targeted tests passed** (`Ran 43 tests in 24.133s`, `OK`). The
real-pytest fixture uses the pinned interpreter and an explicitly controlled test
environment with external plugin autoload disabled only for that fixture. Its two
requested fresh invocations each produced one import/collection sentinel and one
test-call sentinel; no hidden preflight was added. This is a mechanism check,
not the occurrence-aware semantic oracle or ecosystem qualification. Other controls
cover exact reset/edit/input chains, modes, same-mtime edits/reverts, partial and
unknown effects, command/publication loss, shutdown, unsafe files, caps, altered
history, complete denominators and offline relocation/comparison.

- **634 full locked harness tests ran: 633 passed and one existing native-peak
  capability test was skipped** (`Ran 634 tests in 697.723s`, `OK (skipped=1)`).
  This includes all **43 new scenario controls**, including the real-pytest
  same-session mechanism check. The capability skip is not native peak qualification.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.292s`, `OK`).
- `git diff --check` and **108 edited-document local links** passed. All **5**
  changed/new Python files parse with Python 3.10 grammar, not runtime qualification.
  Existing schemas/template and dependency, lock, toolchain and support pins are
  unchanged. No Serc integration or dependency change was made.
- The reproduction block was executed directly from this document: one declared
  edit/request, all four phases accounted, exact changed bytes retained and all
  six qualification fields null. Evidence is at
  `/tmp/opencode/pt-scenario-replay-doc-smoke-potjhu9s`.
- Retained strict-native and lost-return resource cards still reconstruct unchanged
  with an isolated copy of their matching `765c043` reader, including null native
  peak and unknown/not-run outcomes. No historical subject was rerun. That check
  is at `/tmp/opencode/pt-scenario-reader-history-pnlbhgn6`; source-bound history
  was not rewritten to fit the changed analysis guard.

Direct execution/API and read-only CLI controls are retained outside the repository
at `/tmp/opencode/pt-scenario-replay-evidence-us0qasji`:

- **14 source cases** retain all two-request/six-phase plans: two complete runs,
  a failed request, expected nonzero, unreleased shutdown, changed input, deadline,
  three clean unsupported profiles and four explicit file-return/command-return/
  unit-publication faults. Ten cases use producer CLI invocations; four use
  explicitly injected API faults. Every valid retained bundle inspected with exit
  **0**, without rerunning subjects, changing source bytes or changing repeated
  summary output. These are test-owned file/process controls, not benchmarks.
- Failed requests remain **failed + not run**. A subject's tracked-file mutation
  fails despite matching stdout. Partial reset/edit effects retain one unknown
  effect return and no later request execution, without rollback. A command return
  lost after sample commit retains **unknown + not run**, not recovered success.
  Unconfirmed unit publication stays aborted even with completed phase observations.
- S6/S7/S9 each exit **3**, retaining all phases not invoked and no worktree effects.
  Missing `--apply` exits **2** before output creation or invocation. Deadlines
  preserve the required shutdown rather than pretending it completed implicitly.
- Two offline comparison CLI controls retain both full ledgers: exact declared
  inputs match only as unqualified file-domain evidence; a failed candidate blocks
  comparison with its failed/not-run requests still visible. Semantic/reset/
  independence qualification and ratios/bootstrap remain null.
- **12 malformed copies** (omitted reset/edit/shutdown, reordered operations,
  omitted input snapshot entry, wrong pre-request bytes, invented known non-invocation,
  early clock, extra file, corrupt blob, qualification promotion and an unattributed
  later command after a lost return) each exit **2** without traceback. Inventory/
  unit digests were rebound, so typed plausible contradictions cannot pass merely
  by updating a hash. No failure becomes a favorable subset.

This closes a bounded **declared-file validation prerequisite**, not WP01 acceptance.
Paired scenario validation is now integrated separately, as linked above.
Latency/resource campaign qualification, real product request/edit endpoints,
complete loaded-input/environment/cache/service/reset qualification, semantic
work/generation validation, resource budgets, observer-overhead characterization,
frozen corpus/campaign governance and independent review remain open. The existing
card schemas and qualification nulls are unchanged. Changing the analysis guard
does change reader-source bytes; older cards need their matching reader revision
(`765c043` is this batch's base), not rewritten history.

WP02–WP04 completion, the real pytest backend/oracle and qualification/release
dependencies remain in the [prerequisite register](wp01-status.md). Missing native
`memory.peak` gates peak qualification, not this implementation. No Rust/bridge
build, qualified materialization or real PT conformance/performance campaign is
implied by these harness checks.
