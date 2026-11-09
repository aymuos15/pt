# WP01 paired resource-diagnostic campaigns

Status: **implemented bounded integration; WP01 and native peak qualification
remain open**. Date: **2026-11-09**. Base: `0cba0b6`. This integrates the
[resource observer](wp01-resources.md) into paired production, validation and
summaries. It does not implement PT's backend/oracle, qualify support or complete
benchmark/release governance. `pt run` remains unavailable; no speedup is established.

## Explicit measurement layer and fixed plan

`paired.py --timing-endpoint resource` selects a **resource diagnostic**, not a
latency campaign and not an automatic second execution of a previously timed
arm. Each requested preparation, probe and measurement invokes the existing
resource observer once, in scheduled balanced order, with a fresh private cgroup.
No hidden collection, project import in the coordinator, dependency mutation,
automatic replay or default-enabled optimization is introduced.

The new [`paired-resource-v1.schema.json`](../bench/harness/paired-resource-v1.schema.json)
is a distinct closed format. Its plan names `kind: paired_resource_campaign`,
`measurement_layer: resource_diagnostic` and the existing resource endpoint.
Shared command/contract/guard validation is reused; the legacy command and v2
lifecycle schemas are untouched. Resource flags in other modes are rejected,
not silently enabled or ignored. Raw-prefix capture is explicitly unsupported
in this diagnostic mode; ordinary lifecycle/command capture remains separate.

Before work, the plan fixes schedule/seed, cwd per arm, commands/contracts/guards
per stage, timeout, delegated parent per arm, partial-peak policy, sampling
interval and cleanup grace. The plan is validated and committed before any
resource invocation. No parent controller, quota, cache or existing process
membership is reconfigured. Unknown dynamic-loader profiles or missing required
capabilities remain unsupported under the standalone observer's contract.

Use an existing delegated experiment parent, not this placeholder:

```sh
parent="/path/to/existing/delegated/cgroup"
directory="$(mktemp -d /tmp/opencode/pt-paired-resource.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/paired.py --timing-endpoint resource --resource-cgroup-parent "$parent" --cwd . --timeout 10 --blocks 2 --seed 0 --output "$directory/run" --baseline-json '["bench/harness/.venv/bin/python","-c","pass"]' --candidate-json '["bench/harness/.venv/bin/python","-c","pass"]' --baseline-guard-json '{"expected_exit_code":0,"expected_stdout_bytes":0,"expected_stdout_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}' --candidate-guard-json '{"expected_exit_code":0,"expected_stdout_bytes":0,"expected_stdout_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}'
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_run.py "$directory/run"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/summarize_run.py "$directory/run"
```

`--baseline-resource-cgroup-parent` / `--candidate-resource-cgroup-parent` override
the shared parent. With no parent, the corresponding unit is unsupported, not
executed without accounting. Only explicit `--resource-allow-missing-peak` permits
CPU/current diagnostics without a native peak; no other missing capability is
waived. `--resource-sample-interval` and `--resource-cleanup-grace` select the same
bounded settings as the standalone observer. The ordinary finalization and
preparation/probe guard options still apply, with their exact stage meanings.

## Bound records and endpoint separation

```text
schedule.json                         # fixed resource-diagnostic plan
resource-preparation-000001-baseline.json
preparation-000001-baseline.json       # context + exact resource-byte binding
resource-probe-000001-baseline.json
probe-000001-baseline.json
resource-block-000001-baseline.json
block-000001-baseline.json             # stage metadata or explicit not-run record
blobs/<sha256>                        # observed declared report bytes
abort.json                            # optional stop point/cause/diagnostic copy
...                                   # deterministic names for each block/arm
```

Stage metadata binds the raw resource record's **name, bytes and SHA-256**, exact
context, contract and guard. Inspection validates both closed envelopes and the
existing raw resource schema/semantics. It cross-checks every requested setting,
seed/order, distinct private group paths, positive nonoverlapping resource
intervals and following observer intervals. Missing/unknown/malformed records,
changed bindings/settings, reused groups and unsupported relabelling are rejected.
Schema references resolve only through the bundled offline registry.

The resource clock remains **API entry through cgroup cleanup/final counters/
removal**, not publication-inclusive valid-result latency. After that endpoint:

1. Publish and read back the exact raw observation.
2. Observe the declared exit/files/absences, recompute requested stdout guards and
   archive bounded declared bytes with the unchanged strict blob publisher.
3. Record that observer interval, then publish/read back stage metadata.

File checks/archival/publication are observer work **outside** the resource
endpoint. They are not hidden inside a falsely renamed latency measurement.
The metadata's observer interval does not include its own publication. Inspection
uses typed historical file/absence checks and retained bytes, not later-mutated
worktrees; it is not an authenticated snapshot/current-state or generation proof.
No file evidence is invented when the subject was not observed to execute.

Resource data is never attached to earlier latency records as if it described
the same execution. Even complete resource diagnostics keep ratio, absolute
latency comparison and bootstrap fields **null**. Bootstrap requests and direct
latency-estimator inputs carrying this resource endpoint/layer are rejected.
Default lifecycle and explicit command-only timing/analysis remain unchanged.

## Failure policy and full denominators

`planned_arm_count` always equals twice the planned block count. Summaries expose
one measurement entry per planned arm and one entry per requested stage, including
later work not run after an abort. States are never filtered into a favorable subset:

- Strict unsupported measurement records retain capability reasons, no invocation
  and unknown metrics. Other arms may collect diagnostics, but the comparison is
  blocked. Unsupported preparation/probes explicitly skip their arm's later work.
- Explicit partial diagnostics retain actual CPU/current readings with **null
  native peak**. A valid partial preparation/probe may proceed; every incomplete
  resource stage still blocks complete-diagnostic status.
- Ordinary unsuccessful preparation/probe exits or guards skip their measurement,
  retaining stage costs and the measurement denominator. Explicitly expected
  nonzero measurement outcomes remain possible, never ordinary test passes.
- Resource failures (including background workers after leader exit), failed
  declared file/absence checks, archival or observer-storage failure abort before
  subsequent work. Surviving favorable pairs cannot produce estimates.
- Valid diagnostic copies in `abort.json` retain resource/stage/skipped metadata
  when its ordinary publication fails. Such copies are not confirmed publications.
  Inconsistent visible fragments, missing aborts or unexplained omissions invalidate
  the bundle instead of being cleaned up or excluded to make it look complete.
- If the observer raises without returning a resource record, invocation status
  is **unknown**, not asserted false: the current `run_attempted` is null and
  `unknown_invocation_arm_count` / stage counterpart expose that uncertainty.
  Later serial work is explicitly not run. No missing cost is imputed as zero.

`observed_arm_count` counts recovered measurement resource-invocation attempts,
not executed tests, valid work or proved subject startup. Resource-record counts
also include unsupported observations where no invocation occurred. Publication
flags distinguish committed resource/stage/not-run metadata from diagnostic or
manifest-derived states. None authenticates unobserved history.

`per_arm_resources` covers **measurement stages only**. Preparation and probe
entries remain in `stage_resource_observations`, not free or folded into arm
peaks. Observed CPU sums include retained failed-unit costs and report known and
unknown unit counts; they are not estimates for unknown units or full-work means.
Peak/current fields report maxima **per observed resource unit**, not summed RSS,
summed peaks or campaign-wide simultaneous memory. Sampled current remains only
a lower bound; unknown peaks remain unknown. Complete *accounting* alone never
means guard/file validity, semantic equivalence or qualification.

Producer exits: **0** for complete consistent diagnostic evidence, **1** for
partial/incomplete diagnostics or guard/expected-outcome blockers, **3** when no
measurement was attempted and unsupported capabilities caused the blocked plan,
and **2** for abort/invalid configuration or publication failure. Inspector exit
zero means consistency, including recorded aborts/unsupported cases. Summary
exit zero means complete diagnostic observations, **not a speed result**; blocked
summaries exit 1 and malformed evidence exits 2.

## Verification and retained limits

From the repository root, with unchanged pins/lock:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

- **307 harness tests ran: 306 passed and one native-peak capability check was
  explicitly skipped** (`Ran 307 tests in 92.710s`, `OK (skipped=1)`).
- **68 contract/audit tests passed** (`Ran 68 tests in 8.858s`, `OK`).
- `git diff --check` and **63 edited-document local links** passed. All **9**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing v1/v2/resource-observation schemas and dependency,
  lock, toolchain and support pins are unchanged.
- **27 new paired-resource methods passed**, including four native/capability
  controls and 23 unit/format controls using explicitly synthetic counter states.
  Complete/peak-positive synthetic cases are not native peak evidence. The
  **20 existing paired-lifecycle methods also passed** after sharing only stage
  request validation; the default timing path was not replaced or rerun per arm.
- Controls cover unsupported/asymmetric/partial outcomes, all stage/arm counts,
  uncertain invocations, expected/unexpected exits, background/timeout/cancel
  aborts, missing/corrupt/rebound evidence, resource/stage/skipped publication,
  wrong report bytes, historical archives, overlapping intervals, group reuse,
  schema/type ambiguity and prohibition of latency analysis for resource data.

Direct CLI evidence is retained outside the repository at
`/tmp/opencode/pt-paired-resource-evidence-oc_vbrjq` (functional checks only):

| Case, two blocks | Producer / inspector / summary exits | Planned / observed attempts | Measurement resource states |
|---|---|---|---|
| Strict missing peak | 3 / 0 / 1 | 4 / 0 | 4 unsupported; no command markers |
| Explicit partial diagnostics | 1 / 0 / 1 | 4 / 4 | 4 partial; exactly two invocations per arm |
| Baseline parent unsupported | 1 / 0 / 1 | 4 / 2 | 2 unsupported + 2 partial; no baseline invocations |
| Detached worker, leader exit zero and matching guard | 2 / 0 / 1 | 4 / 1 | 1 failed + 3 not run; consumed CPU retained |
| Unreleased declared marker, matching guard | 2 / 0 / 1 | 4 / 1 | 1 partial resource observation with failed finalization + 3 not run |

Every case retains four planned arms, unknown native peaks and null estimates.
Later-mutated worktree reports/markers leave the archived partial summary
unchanged. Four retained malformed copies (wrong binding, invented zero peak,
removed unsupported arm and relabelled endpoint) make both inspection and summary
exit **2**, without traceback. No unfavorable unit or failure was dropped.
All targeted/full test runs in this batch passed; the existing native peak skip
is a retained hardware-capability limitation, not a waived successful test.

This completes the focused paired-resource integration gap, **not WP01
acceptance**. Native peak qualification, full resource budgets, managed replay
endpoints, semantic manifests/result cards, work/generation validation, observer
overhead, frozen-campaign/scenario governance and independent review remain open.
WP02/WP03, WP04 completion and the real backend/qualification/release dependencies
remain in the [prerequisite register](wp01-status.md). Rust/bridge, qualified corpus
materializations, real PT conformance and performance campaigns were not rerun.
