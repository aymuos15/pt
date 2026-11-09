# WP01 whole-session replay resource diagnostics

Status: **bounded opt-in execution/inspection implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `af29661`. This combines
[managed replay](wp01-managed-replay.md) with the existing
[fresh-cgroup resource observer](wp01-resources.md). It is diagnostic profiling,
not shipping-mode timing, a semantic oracle or qualified support. `pt run`, the
real backend and qualification/release gates remain unavailable. No test-runner
speedup has been measured.

## One fresh resource boundary for one complete replay

[`replay_resources.py`](../bench/harness/replay_resources.py) executes a **new,
explicitly requested diagnostic replay once**. It never reruns a retained latency
observation, adds metrics from another invocation, or wraps an entire paired
campaign and divides the result into fictional per-arm costs.

The resource unit is `complete_managed_session_replay`, with scope
`fresh_cgroup_replay_driver_and_all_future_inheriting_descendants`:

1. Freeze/validate the managed plan and resource configuration; publish the exact
   request before subject work. Validate the cwd, private new output and watchdog.
2. Use the existing observer to create **one fresh exclusive child** under the
   caller's explicit already-delegated cgroup-v2 parent. Check capabilities, zero
   initial counters and empty population. Do not move existing services into it.
3. The existing isolated `-I -S` enrollment launcher moves itself before exec of
   the new trusted [`replay_resource_driver.py`](../bench/harness/replay_resource_driver.py).
   The driver's `-I` bootstrap, dependencies and explicit trusted harness imports
   happen **after enrollment**. It invokes the unchanged managed replay API once.
4. Preparation, all requested idle waits, future inheriting background workers,
   serial fresh interaction processes and the original required shutdown share
   this **same cgroup**. No per-interaction boundary resets or historical maxima
   are added. Background workers with closed pipes/new process groups remain in
   the resource boundary even when the command timer cannot see them.
5. Inner report/archive/sample publication/final checks, returned receipt
   construction, driver record publication/read-back and its transport also stay
   charged until the driver exits. The outer observer samples through its usual
   residual-work check, at most one recursive kill, final counters and group removal.

The exact existing kernel resource endpoint remains
`resource_api_entry_through_empty_cgroup_final_counters_and_group_removal_v1`.
CPU is the whole-group counter delta; memory is **cgroup-v2 charged memory**, not
RSS/PSS or a sum of per-process historical peaks. Sampled current maximum remains
a lower-bound diagnostic and never substitutes for absent kernel `memory.peak`.
Persistent work during idle is included in total CPU/current-memory observations;
there is **no isolated idle-only attribution**, energy result or resource-budget
qualification. Precharged/shared pages may be charged elsewhere, and pre-existing
external services or cgroup escapes are unsupported. This is not a hostile sandbox.

### Observer overhead is explicit, not subtracted

The enrolled driver includes substantial harness work: Python/dependency startup,
plan/schema validation, command timers, hashing, archival, managed publication and
its own reporting. All of its charged work stays in the totals. The original
launcher's pre-enrollment bootstrap and the **outer** observer/sampling thread,
capability/counter reads and resource-record publication are outside cgroup CPU/
memory totals. The outer resource wall clock still includes its observer lifecycle.
No estimated tax is subtracted. These are not unmodified product-latency samples,
nor a measurement of overhead-free subject-only CPU/memory.

Subject argv, cwd and inherited environment are preserved. Driver isolation and
`sys.path` do not rewrite subject flags/environment, install dependencies, disable
plugins or import harness code into test workers. There is no extra pytest
collection or automatic replay. A test fixture verifies argument boundaries,
environment/cwd and absence of harness imports in the actual command process.

## Separate deadlines and process-specific clocks

The existing inner execution budget still starts at managed API entry and reserves
the original shutdown's finite timeout. Failure stops later interactions without
retry; shutdown is attempted once after successful inner plan publication, including
after execution-budget expiry. Resource diagnostics do not replace that command.

An explicit `--outer-timeout` is a separate **hard command-wait watchdog** for the
driver. Input validation requires at least:

```text
execution_timeout_seconds + shutdown.timeout_seconds + 5 seconds
```

It must also fit the existing resource maximum **86400 seconds**. Some otherwise
valid one-day replay plans cannot fit this diagnostic profile and are rejected
before execution. Five seconds is a minimum bootstrap/reporting allowance, **not
a measured universal overhead bound or a guarantee**: filesystem/archival work is
not all finitely bounded by the inner command deadlines. Callers must choose an
appropriate larger finite watchdog for their explicit workload.

Outer watchdog expiry/cancellation can kill the driver **before required shutdown
or publication finishes**. The observer then attempts owned-cgroup cleanup; a missing
driver/session receipt leaves invocation effects and shutdown **unknown**, not
silently not run or successfully cleaned. Empty final population is evidence of
boundary cleanup, not a completed application shutdown. SIGKILL, host loss,
repeated interruption, inaccessible storage or failed cgroup cleanup cannot
guarantee a final receipt. Partial files/groups are not erased to invent success.

Existing clocks retain their `harness_process_monotonic` local tag. The new format
records **observer and driver PIDs, monotonic implementation/resolution and clock
properties separately**, with
`clock_alignment: distinct_process_domains_no_cross_process_arithmetic`.
Inner replay/phase clocks belong to the driver; resource counters/samples/process
clocks belong to the outer observer. Inspection checks enclosure/arithmetic only
within each declared process. It never silently treats those clocks as the same
authority or subtracts a driver timestamp from an outer timestamp.

The wrapper's `observer_clock` is orchestration bookkeeping through request setup,
the resource call, raw-resource publication and retained-input capture. Receipt
construction/validation, subsequent inspection and stdout transport follow it;
CLI request-file decoding also precedes API entry. Neither that clock nor a sum
of nested clocks is promoted to a replay latency comparison.

## Closed evidence and read-only inspection

The distinct [`replay-resource-v1.schema.json`](../bench/harness/replay-resource-v1.schema.json)
defines request, driver record and post-endpoint receipt. The private bundle is:

```text
request.json       # frozen replay plan, resource settings, invocation ID, driver path/hash
session/           # inner plan/steps/unit/blobs if execution reached them
driver.json        # returned replay receipt OR a retained managed-observation error
resource.json      # unchanged raw whole-cgroup resource record
```

Non-invoked/unsupported observations have no fabricated session/driver files. A
failed or lost return can leave a diagnostic partial session; it is retained and
inventoried, not promoted to a confirmed completed observation. The external
receipt is returned by the API or emitted on stdout: **save it outside the bundle**.
The bundle without its post-endpoint receipt cannot confirm wrapper publication.

The request has a fresh invocation ID and exact driver-source hash. The driver
checks the request/source bindings before entering replay. Its record binds the
request bytes and returned managed receipt; its final stdout transport names the
invocation and driver-record hash. The outer process observation must have complete
drainage/reaping, expected exit and matching transport digest/size to confirm the
driver's completion. Matching stdout alone does not verify test work.

The wrapper receipt binds every root/nested retained file by full relative path,
size and SHA-256, including diagnostics and empty session/blob directories. This
uses the existing canonical path/size/digest inventory hash policy under a new
closed schema that permits this one nested tree; existing schemas are unchanged.
An unconfirmed resource-record publication can retain its full raw observation
in the receipt. A visible copy must agree; malformed/conflicting bytes cannot be
approved merely because a diagnostic failure was recorded.

[`inspect_replay_resources.py`](../bench/harness/inspect_replay_resources.py)
checks strict types/closed schemas, all byte bindings, the exact boundary command
and settings, raw counter derivations/capabilities/cleanup, driver protocol and
same-process clock arithmetic. For a returned managed receipt it recursively
checks the inner plan, every phase, publication/archive/guard evidence and shutdown.
The actual executed session plan must match the frozen request. Before/after
fingerprints reject observed evidence mutation with **no retry**. Missing records,
unexplained extras, nonregular inputs and contradictory rebound evidence fail.

Inspection launches no commands, reads no later worktree files as past results,
and opens no cgroup. Byte-identical copies can relocate. A source hash binds bytes
read, not authenticity, complete executed-code identity or a qualified artifact.
Driver/outer clocks and file observations remain unauthenticated; safe final-path
lookups/fingerprints are not an atomic snapshot or hostile-directory boundary.
Caller-owned ancestors remain outside that safety boundary.

## Status, denominators and unknown metrics

Every result is `resource_diagnostic`, exploratory and
`confirmatory_eligible: false`. There is one planned session and the complete
planned phase/interaction denominator, including failed and skipped phases.

| Observation | Summary |
|---|---|
| Required capability unavailable before launch | `unsupported`; all phases known not invoked, metrics null; no subject/driver starts. |
| Only missing peak explicitly allowed, replay/protocol/counters/cleanup otherwise complete | `partial_unsupported`; CPU/current/event observations retained, peak null and complete-accounting false. |
| Full capability/counters/cleanup, completed replay and confirmed publication/transport | `observed_unqualified`; accounting complete for this diagnostic scope only, never semantic/resource-budget qualification. |
| Failed replay, lingering worker, timeout/cancel, counter/sampler/cleanup/publication failure or missing return | `failed`; retain observed metrics, failures, known not-run work and unknowns separately. |

Known attempted, unknown and known-not-invoked phases sum to planned phases. A
missing managed return cannot derive phase/shutdown outcomes even when `unit.json`
exists; all such phase invocations remain unknown. Conversely, a returned managed
receipt is retained when only the **outer** resource return was lost, but its
resource metrics remain null. Missing enrollment/exec confirmation is conservatively
unknown rather than inventing proof that the driver/subject did no work.

`counter_boundary_accounting_complete` describes the original resource boundary;
`whole_session_accounting_complete` additionally requires completed replay and
confirmed observation/publication. A fully counted failed replay can therefore
have the first true and the second false. Observed failed-unit CPU is not erased.
`per_phase_resource_metrics`, `idle_only_resource_metrics`, verified independence,
ratio and bootstrap remain null; direct latency estimators reject this layer.

Producer exit **0** means complete unqualified diagnostic accounting, **1** means
explicit partial support, **2** means failure/invalid input/evidence/publication,
and **3** means unsupported with no subject launched. A failed but internally
consistent observation can still emit its receipt. Inspector exit **0** means
consistent unqualified evidence, including accounted failures; malformed input
exits **2**. None means passing tests, equivalent work or qualified native peak.

Bounds: existing **32 interactions**, **256 KiB managed plan**, **1 MiB request**,
**4 MiB driver/resource/external receipt**, **4096 aggregate files / 512 MiB total
retained evidence**, **128 MiB per blob**, and the stricter inner record/artifact
bounds. Sampling stays **1 ms–1 s**, at most **4096 samples**, and cleanup grace
**0–10 s**. A long replay can exhaust the sample cap and must remain failed, not
claim complete sampled accounting. Oversize records fail without dropping phases
or truncating evidence. Private no-overwrite publication is not power-loss durable
or authenticated. Paths, arguments, reports, hashes and raw prefixes may reveal
secrets; review before sharing. Raw evidence is not committed.

## Reproduction: new disposable resource fixture

From the repository root:

```sh
directory="$(mktemp -d /tmp/opencode/pt-replay-resources.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
cwd = root / "work"
cwd.mkdir()
probe = Path("bench/harness/tests/fixtures/replay_resource_probe.py").resolve()
digest = hashlib.sha256(b"ready\n").hexdigest()
def artifact(role):
    return {"path": "report-" + role, "bytes": 6, "sha256": digest}
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
(root / "requested.json").write_text(json.dumps(plan))
PY
resource_options=()
if [ -n "${PT_BENCH_CGROUP_PARENT:-}" ]; then
  resource_options=(--cgroup-parent "$PT_BENCH_CGROUP_PARENT" --allow-missing-peak)
fi
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/replay_resources.py --plan "$directory/requested.json" --output "$directory/run" --outer-timeout 30 "${resource_options[@]}" > "$directory/receipt.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_replay_resources.py --directory "$directory/run" --receipt "$directory/receipt.json"
```

Without an explicit parent, this intentionally records unsupported/no work and
producer exit **3**; inspection still returns **0**. For a deliberate **partial**
native diagnostic, set `PT_BENCH_CGROUP_PARENT` to your existing writable delegated
memory-enabled parent before running the example. The script explicitly adds
`--allow-missing-peak`; remove that flag to require a native peak. Never create
privileged delegation, change controllers/limits, move unrelated processes or
tune shared-host caches to make the example pass. The test-owned fixture allocates
a 64 MiB worker across idle and 32 MiB during shutdown, then releases the worker.
This is a functional control, not a pilot/corpus/performance comparison.

## Verification and retained development evidence

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

**39 targeted tests passed** (`Ran 39 tests in 74.506s`, `OK`). Seven are
capability-gated native controls; 32 use synthetic counters/enrollment, isolated
real commands, refusal paths or record/clock faults. Synthetic peaks are **not
native peak qualification**. Tests cover CPU/residency across idle, charged shutdown,
leftover workers, strict peak refusal, argv/environment, cancellation, outer watchdog,
reserved shutdown, failure/not-run/unknown outcomes, before/after-commit missing
returns, counter/sampler/cleanup/OOM faults, publication, schema/type/bounds,
history relocation, mutation and rejection as latency samples.

Retained development failures: an initial native smoke reached completed replay
but the wrapper schema incorrectly reused the old inventory's `blobs`-only
directory restriction. It rejected the new `session/` tree and returned no
confirming receipt. The new schema now defines its own bounded nested inventory;
the old schema was not loosened. The first **31-test** run then had **one assertion
failure**: the test expected text `resource diagnostics`, while the existing
latency guard correctly rejected it as `resource diagnostic observations are not
latency samples`. That expectation was corrected; no adverse case was removed.
All six native controls in that initial run passed; the expanded suite adds a
seventh native transport check and more fault controls.

- **509 full locked harness tests ran: 508 passed and one existing native-peak
  capability test was skipped** (`Ran 509 tests in 362.929s`, `OK (skipped=1)`).
  This includes all **39 new resource-replay controls**, including the seven native
  controls on this host; it does not qualify native peak support.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.334s`, `OK`).
- `git diff --check` and **120 edited-document local links** passed. All **6**
  new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block above was executed directly from this document in its
  documented no-parent mode: three phases remained not invoked, no worker ran,
  metrics stayed null, and read-only inspection returned **0**. Separate evidence
  is retained at `/tmp/opencode/pt-replay-resource-doc-smoke-dakfk6dw`.
- A retained `af29661` replay card with a lost post-unit return still reconstructs
  identically as blocked, with one unknown session and three not run. Existing
  reader sources, schemas and its reconstruction digest are unchanged.

Direct execution/API and inspector-CLI controls are retained outside the repository
at `/tmp/opencode/pt-replay-resource-evidence-o38xi2yc`:

- **15 source cases**: two non-invoked capability refusals, four explicitly
  synthetic cases, six native CLI cases and three native-counter cases with
  explicit test-only driver/publication faults. Every inspection returned **0**
  as unqualified consistency, preserving one planned session and every phase/
  interaction with unchanged source bytes. Synthetic cases are identified in
  separate evidence-class records, never cited as kernel peak measurements.
- On this host, strict native peak mode returned **3**, with all three planned
  phases not invoked and null CPU/peak/current observations. `memory.peak` remains
  absent, not an implementation blocker.
- Explicit native partial mode included the resident worker through idle and
  charged shutdown: **1,843,712 µs whole-boundary CPU delta** and **130,064,384 bytes
  maximum sampled current**, with null peak, false complete-accounting and no
  forced kill. These are one diagnostic's functional values including driver
  overhead, **not a performance comparison or qualified resource profile**.
- A deliberately retained worker after matching shutdown sentinels required
  recursive kill and stayed **failed**, despite a completed inner replay. Failed
  interaction/shutdown and exhausted execution budgets retained their outcomes.
  An explicitly substituted finite-hang test driver and a post-unit lost return
  each kept all phase/shutdown observations unknown. Resource publication failure
  retained counters but could not invent a confirmed commit. Owned native groups
  were empty and removed in every retained case.
- **Twelve malformed copies** (qualification promotion, invented zero peak,
  wrong boundary command, omitted shutdown with rebound bindings/transport,
  wrong invocation ID, shared-clock assumption, omitted inventory entry/driver,
  unexpected file, corrupt blob, early outer clock and missing publication-failure
  evidence) made inspection exit **2**, without traceback. A too-small watchdog
  was rejected before output creation or subject work.

## Remaining prerequisites

This completes the focused **single whole-session resource boundary** deliverable,
not WP01 acceptance. Paired resource replay scheduling/closed reporting and replay
resource cards remain separate work. Existing latency replays/cards retain their
unknown resource fields; their 24 qualification fields are not filled by another
diagnostic. No existing reader source/schema/lock is changed by this integration.

Native peak qualification, idle-only attribution, resource-budget equivalence,
actual work/generation/input/reset validation, semantic manifests, scenario/edit
replays, observer overhead characterization, frozen campaigns and independent
review remain open. WP02–WP04 completion, the real backend/oracle and qualification/
release dependencies remain in the [prerequisite register](wp01-status.md).
Rust/bridge builds, qualified materializations and real PT conformance/performance
campaigns were not rerun by this harness-only batch.
