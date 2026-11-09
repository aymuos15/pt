# WP01 managed serial-command session replay

Status: **bounded execution/inspection implemented; WP01 acceptance remains open**.
Date: **2026-11-09**. Base: `eea5e41`. This adds a distinct exploratory endpoint
alongside [paired lifecycle observations](wp01-paired-lifecycle.md) and
[evidence-bound result cards](wp01-result-cards.md). It does not implement or
qualify PT's real pytest backend, semantic oracle, daemon reuse or release.
`pt run` remains unavailable; no test-runner speedup is established.

## One session, not a bag of independent interactions

[`managed_replay.py`](../bench/harness/managed_replay.py) executes an explicit
predeclared sequence **once**: preparation, 1–32 interactions, then required
shutdown. Every command uses a fresh serial subprocess, preserving argv boundaries
and using one declared cwd with inherited environment. Shared files/external state
can persist between commands; execution interpreters are not reused. There is no
hidden collection, dependency mutation, implicit reset, automatic retry, changed
plugin policy or default-enabled product optimization.

The closed [`managed-replay-v1.schema.json`](../bench/harness/managed-replay-v1.schema.json)
names `sample_unit: complete_managed_session_replay` and
`scope: fresh_serial_commands_with_declared_state`. Step contracts explicitly
declare argv, ID, timeout, idle delay, optional exit/stdout guard and canonical
required artifacts/absences. Preparation and shutdown require expected exit zero;
interactions can explicitly expect nonzero. The final session file contract uses
`expected_exit_code: null`: there is no fictional process return code for the
whole multi-process session. The aggregate checks are file-only, not an external
resource lease or cleanup proof.

There is exactly **one observed session unit**, even when it aborts. The summary
retains every planned phase/interaction and known attempted/not-invoked/unknown
invocation counts. `verified_independent_units` remains null. Phase rows carry
`measurement_layer: managed_replay_step` and `sample_unit: replay_step`; the
standalone point/bootstrap estimators reject either label. No session comparison,
ratio, bootstrap, break-even estimate or independent-unit claim is produced.
Unlabelled arbitrary data cannot acquire verified independence from this guard.

## Endpoint and budgets

The endpoint is
`managed_session_api_entry_through_shutdown_unit_publication_and_declared_finalization_v1`.
The enclosing harness-process monotonic wall interval includes:

1. API-entry validation, freezing the requested plan, cwd checks and private bundle
   creation; exact plan publication/read-back before project commands.
2. Preparation, requested idle waits and ordered interactions, with each command's
   pipe/leader handling, declared artifact archival, guards, phase sample
   publication and validation. Phase receipts are embedded in the aggregate unit.
3. Required shutdown, even when the execution budget expires or an earlier
   command fails, followed by final declared-file observations and archival.
4. Complete retained-input inventory, aggregate `unit.json` publication/read-back,
   post-publication file rechecks and retained-plan/input/unit consistency checks.

Recorded subclocks expose plan publication, each considered phase and its idle
wait, post-shutdown reporting, aggregate publication and final checks. Inspection
requires exact interval arithmetic, enclosure and serial ordering; moving the
session endpoint before publication fails even if all stdout guards match.
Do not add overlapping inner lifecycle/command durations to the total again.

`execution_timeout_seconds` is at most one day and starts at API entry, including
validation and publication. Before preparation/each interaction, an expired
budget prevents invocation. Otherwise the command timeout is the smaller of its
declared timeout and the observed remaining budget. A timestamp binds that
calculation for inspection. Shutdown has its **own reserved command timeout**, at
most 60 seconds, independent of the exhausted execution budget, with no idle wait.
An expired budget before preparation still leads to one shutdown attempt after
successful plan publication. Plans must make that cleanup safe for partial state.

These are command-wait/stop-start budgets, **not a hard bound on all filesystem
operations or total wall time**. The existing timer can additionally spend its
bounded process/pipe cleanup grace; archival and observer publication remain
charged actual work. No arbitrary estimated overhead is subtracted.

The post-endpoint receipt's construction, validation, serialization and transport
are observer bookkeeping outside the named interval. The CLI reads/decodes the
requested plan before calling the timed API; that CLI input transport is not
mislabelled as measured request latency. This is not a watch edit-to-result or
generation-valid product-request endpoint.

## Failure policy and retained evidence

- Failed preparation, interaction, stdout guard, lifecycle/file check or handled
  observation error stops later interactions. Their ledger entries remain
  `not_run_prior_failure`; no effects are retried or rolled back.
- Deadline and interrupted/failed idle waits preserve distinct not-run causes.
  A returned process observation establishes an invocation attempt, including
  launch failure; a missing return leaves `invocation_attempted: null`. An error
  after a returned observation does not erase its known attempt.
- The originally frozen shutdown command is attempted **once** after plan
  publication, using its own budget. Failed/nonzero/hung/unreleased shutdown
  remains failure regardless of earlier interaction results or matching stdout.
- Plan fingerprint/content checks precede later non-shutdown commands. A changed
  plan stops those commands but does not replace the original cleanup. Mixed or
  corrupt bindings are still rejected by inspection; an abort flag is not a
  permission to approve contradictory bytes.
- Handled OS/value/runtime errors and `KeyboardInterrupt` in observation, idle,
  validation or publication paths preserve errors where a record can be formed.
  SIGKILL, host loss, unhandled signals, repeated interruption or unusable evidence
  storage can leave an incomplete bundle with no confirming receipt. No general
  cleanup or record-durability guarantee is made.

The private bundle contains `plan.json`, observed `step-NNNN.json` files,
`unit.json` and `blobs/`. The unit embeds the returned v2 phase receipts, final
file observations, archival references, errors and a path/size/SHA-256 inventory
of **every retained input except itself**. The inventory reuses the
[result-card canonical digest policy](wp01-result-cards.md); `unit.json` is instead
bound by the post-endpoint receipt to avoid circular/self-publication claims.
The receipt is returned by the API or emitted on stdout, **not saved inside its
own measured bundle**. A unit without its receipt cannot certify the endpoint.

When aggregate publication is unconfirmed, a bounded diagnostic sample can be
returned in the receipt. An existing visible unit must agree with that diagnostic
copy; malformed/wrong bytes are rejected. Unconfirmed phase files or leftover
blobs attributable to a missing observer return/archive failure may be retained
as explicit diagnostic fragments in an aborted unit. They are not promoted to
confirmed phase samples. Unexplained extras, omitted work, corrupt archives or
contradictory returned receipts cannot be approved as favorable subsets.

[`inspect_replay.py`](../bench/harness/inspect_replay.py) requires both the retained
bundle and external receipt. It validates closed schemas, strict JSON token types,
the plan, step identities/order, exact byte bindings, clocks/budgets, historical
guards/file contracts, failure/skip causes and terminal outcome. Before/after
input fingerprints also reject observed mutation during inspection. It runs no
commands and never rereads a later worktree as past evidence; byte-identical
copied bundles can be relocated. Historical stat/absence assertions and receipt
timestamps are unauthenticated. Checks are not an atomic snapshot or hostile-path
security boundary, and do not bind the actual executed source/environment identity.

Default output is counted/hashed, not retained. Explicit raw-prefix capture keeps
its declared per-stream cap, full-stream hashes and truncation flags. A completed
unqualified replay with truncated prefixes means the declared bounded-capture
contract was observed, **not that full output or semantic work was retained**.
The truncation count stays visible; no estimator or qualified claim consumes it.

Limits: **256 KiB plan**, **32 interactions**, **3 MiB aggregate unit**, **4 MiB
receipt**, **1000 aggregate declared artifact entries**, and **384 MiB declared
artifact/raw-prefix budget**. Existing safe-input limits also apply: **4096
files**, **128 MiB per blob**, **512 MiB aggregate source bytes**, plus stricter
v2 phase-record bounds. Exceeding bounds fails, never drops ledger entries or
silently truncates an evidence record. Even diagnostic receipt overflow leaves
the unit unconfirmed. Safe POSIX file lookup and the existing Linux native blob
publisher are required; no unsafe publication fallback is added. Bundle/file
publication is private and no-overwrite, not power-loss durable or authenticated.
Do not place the receipt inside the bundle; review paths, commands, reports and
raw output for secrets before sharing. Raw evidence is not committed.

## Reproduction: test-owned shared state, not a benchmark

From the repository root, this creates a disposable plan using the
[`replay_probe.py` fixture](../bench/harness/tests/fixtures/replay_probe.py):

```sh
directory="$(mktemp -d /tmp/opencode/pt-replay.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
cwd = root / "work"
cwd.mkdir()
probe = Path("bench/harness/tests/fixtures/replay_probe.py").resolve()
digest = hashlib.sha256(b"ready\n").hexdigest()
def artifact(name):
    return {"path": name, "bytes": 6, "sha256": digest}
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
(root / "requested.json").write_text(json.dumps(plan))
PY
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/managed_replay.py --plan "$directory/requested.json" --output "$directory/run" > "$directory/receipt.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_replay.py --directory "$directory/run" --receipt "$directory/receipt.json"
```

Executor exit **0** means completed unqualified observation, **1** means an
observed failure/timeout/deadline, and **2** means invalid input/evidence or an
observer/publication error. A receipt can still be emitted with exit 2. Inspector
exit **0** means internally consistent evidence, including an accounted abort;
invalid/contradictory evidence exits **2**. None is a qualified test-success exit.

## Verification and retained development failure

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_managed_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

**39 targeted replay tests passed** (`Ran 39 tests in 22.146s`, `OK`). They
cover preparation/interaction/shutdown holds, validation/publication/archival/final
check holds, idle timing, reserved shutdown and remaining execution budgets,
expected and unexpected nonzero outcomes, mismatching guards, launch errors,
timeouts, interrupted/missing observer returns, mutations, historical inspection,
publication/size faults, strict types and correlated-step estimator rejection.
These fixture and explicitly synthetic record/fingerprint controls are not native
resource qualification, real pytest conformance or performance observations.

- **394 full locked harness tests ran: 393 passed and one existing native-peak
  capability test was skipped** (`Ran 394 tests in 133.577s`, `OK (skipped=1)`).
  This includes all **39 new replay methods** and the final API receipt-size check.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.794s`, `OK`).
- `git diff --check` and **73 edited-document local links** passed. All **5**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block above was executed directly from this document and
  passed, retaining one session/four phases, state `2` and an absent lease. Its
  separate functional evidence is at
  `/tmp/opencode/pt-managed-replay-doc-smoke-jkwzh2s9`, not a benchmark campaign.

Retained development failure: the first **26-method** run had **one assertion
failure**. A test incorrectly expected a nonzero shutdown to match an exit-zero
guard. The guard correctly rejected it. The corrected test checks matching stdout
separately and requires guard failure for nonzero shutdown, while zero-exit
unreleased cleanup still matches the guard but fails finalization. No adverse
case was removed; the expanded 36- and 39-method runs passed.

Direct CLI evidence is retained outside the repository at
`/tmp/opencode/pt-managed-replay-evidence-if12eujj`:

- **12 plans**: success, failed preparation, failed interaction, explicitly expected
  nonzero, guard mismatch, interaction timeout, launch error, shutdown failure,
  unreleased marker, shutdown timeout, execution deadline and bounded raw prefix.
  Each inspection returned **0**, preserved **one session / four planned phases /
  two planned interactions**, and left source bundle bytes unchanged. Executor
  exit was **0** for the three completed-unqualified cases and **1** for the nine
  adverse cases; failed cleanup was never converted into success.
- Every summary retains null verified independence, comparisons, bootstrap and
  resources, and false confirmatory eligibility. The raw-prefix case reports
  **four truncated phases**, not four independent latency observations.
- **Eight malformed bundles/receipts** (qualification upgrade, early endpoint,
  missing shutdown, reordered steps, invented budget, changed inventory,
  unexpected file and corrupt blob) each make inspection exit **2**, without
  traceback. Several unit mutations recompute the unit's byte digest; reconstruction
  rejects semantic inconsistency, not just stale hashes.
- An invalid boolean shutdown timeout makes execution exit **2** before creating
  the output bundle or starting subject work.

## Remaining gates

This implements the focused bounded session-replay execution deliverable, not a
qualified amortized-workflow result. Paired complete sessions, matching edit/input
seeds and external state, replay result cards, real scenario/request/edit endpoints,
generation/work validation, semantic manifests, non-file resource release and
frozen-campaign governance remain open. The existing command/lifecycle/resource
and paired result-card formats remain distinct; no replay record is silently
accepted by those tools. Existing result cards bind reader source bytes; historical
`eea5e41` cards still require that reader for exact reconstruction after the
analysis guard change.

Whole-session CPU/memory/idle residency and resource-budget equivalence remain
unknown. A separate future native resource integration must include preparation,
idle/background work and shutdown without inventing per-step independent units.
Missing `memory.peak` gates native peak qualification, **not further implementation**.
WP02/WP03, WP04 completion, the real backend and qualification/release dependencies
remain open in the [prerequisite register](wp01-status.md). Rust/bridge builds,
qualified corpus materializations, real PT conformance and performance campaigns
were not rerun by this harness-only batch.
