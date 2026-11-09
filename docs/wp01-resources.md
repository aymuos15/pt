# WP01 whole-cgroup CPU and charged-memory observations

Status: **implemented opt-in diagnostic pass; native peak qualification and WP01
acceptance remain open**. Date: **2026-11-09**. Base: `1c5d5ce`.
There is still no PT pytest backend, independent semantic oracle, qualified
support profile or release campaign. `pt run` remains unavailable. These changes
do not establish a test-runner speedup.

The later [whole-session managed-replay integration](wp01-replay-resources.md)
uses this observer around one entire freshly enrolled replay driver, including
preparation, idle/background work, shutdown and driver publication. It is a
separate diagnostic mode, not a rerun or relabelling of existing latency evidence;
this original raw resource schema and strict/partial capability policy are unchanged.

## Resource unit and execution boundary

[`resource_run.py`](../bench/harness/resource_run.py) observes **one fresh command
invocation or complete replay**. It does not change default paired timing or
silently add resource fields to the closed v2 plan/sample/receipt formats. Its
counter scope is
`subject_exec_and_all_future_inheriting_cgroup_descendants`:

1. Create a new exclusive `pt-bench-<uuid>` child under the caller's explicit,
   already delegated cgroup-v2 parent. Validate the real cgroup2 filesystem,
   counter/cleanup capabilities and zero initial accounting/population. Never
   reuse an old group, reset its peak or adopt a pre-existing process.
2. Start a trusted observer launcher in isolated Python (`-I -S`), outside project
   import paths/site initialization. It moves **itself only**, using `0` on the
   private `cgroup.procs` descriptor, then `exec`s the exact subject argv with
   unchanged cwd/environment. Private control/enrollment descriptors close on
   subject exec. A separate control pipe distinguishes failed enrollment/exec
   from a command result; subject stdout never carries control messages.
3. Read kernel whole-cgroup counters, including inheriting workers that detach
   sessions, close pipes or move into descendant cgroups. Sample current memory
   from the independent outer observer, not from test imports.
4. After leader/pipe completion, observe recursive `cgroup.events` population.
   Background work still present is a retained failure, not free work after the
   stopwatch. Allow only the declared bounded cleanup grace, then request one
   recursive `cgroup.kill` when needed and observe a bounded empty deadline.
   Forced termination, OOM, uncertain counters, truncation and incomplete cleanup
   prevent complete-accounting status. Do not replay commands or retry kills.
5. Stop sampling, retain final counters, remove only empty cgroups inside the
   owned private child, and close observer descriptors. Removal failures preserve
   the group path/error for diagnosis, not a false successful boundary.

The resource lifecycle clock starts at API entry and ends after counter
derivation, including setup, the command, required cleanup and group removal.
The narrower process interval is retained separately. Resource-record
validation/publication/read-back is observer bookkeeping **outside** this named
resource endpoint; this is not the primary publication-inclusive paired endpoint.
Launcher bootstrap and the outer observer are excluded from CPU/memory counters;
post-enrollment launcher overhead is included without subtraction. No project
work is intentionally performed by that bootstrap. Dynamic-loader environment
profiles are unsupported before work rather than stripped from the subject or
allowed to load project code before enrollment; no environment values are stored.

This initial backend requires safe Linux x86-64 cgroup-v2 access and an explicit
parent. It never enables controllers, changes limits, clears global caches,
requests root privileges or reconfigures systemd. CPU counter availability is
checked directly; absence of the CPU **scheduling** controller alone is not
treated as absence of `cpu.stat` accounting. This host exposes CPU accounting
even though only memory/pids controllers are delegated to its user service.

## Metrics and unsupported capabilities

| Field | Definition and limitation |
|---|---|
| `cpu_delta_usec` | Final minus fresh initial `cpu.stat` usage/user/system microseconds over the whole cgroup hierarchy, through required cleanup. Kernel rounding/snapshot accounting can make total usage differ slightly from user plus system. Never a direct-leader-only `getrusage` substitute. |
| `peak_charged_bytes` | Final kernel `memory.peak` for this newly created, never-reset cgroup hierarchy. Not RSS, PSS, a sampled peak or summed historical process maxima. Null when unavailable or invalid. |
| `sampled_current_max_bytes` | Maximum of the retained `memory.current` readings, including boundary snapshots. Only a lower bound on observed charged current memory; it never substitutes for `memory.peak`. |
| `memory_events_delta` | Retained OOM/other kernel memory-event deltas; OOM outcomes remain failures even with apparently complete leader output. |
| `snapshots` / `sampling` | Raw bounded counter snapshots and timestamped current-memory readings, in the outer harness monotonic domain. Sampling defaults to 20 ms, with at most 4096 readings; read errors/truncation remain visible failures. |

Charged memory may include cache/kernel charges, while shared/precharged pages
can be charged elsewhere. Final cache charges can outlive processes and be
reparented on cgroup removal. These values are **not** total physical ownership
or proof all memory/resources were released. No RSS-summing fallback, CPU/memory
budget qualification or arbitrary overhead subtraction is provided.

Every required capability is checked before subject work. Missing/unreadable
CPU/current-memory/events/population, enrollment or recursive-kill capabilities
block execution, as does missing peak accounting in the default strict mode.
Only explicit `--allow-missing-peak` permits a partial diagnostic invocation.
It does **not** permit any other missing capability. Missing data is null, not
zero; a null peak cannot be promoted to a sampled or invented peak.

| Record status | Resource CLI exit | Meaning |
|---|---|---|
| `unsupported` | 3 | Required capability/profile unavailable; no subject invocation and no invented resource totals |
| `partial_unsupported` | 1 | Explicit CPU/current diagnostic ran, but native peak remains unsupported; complete-accounting flag is false |
| `observed_unqualified` | 0 for subject exit zero, otherwise 1 | Full declared counter scope observed consistently; complete **accounting**, not a test pass or qualified benchmark |
| `failed` | 2 | Measurement/enrollment/read/cleanup failure, outliving background work, forced termination, OOM or uncertain accounting retained |

CLI validation or observer-publication errors also exit 2; publication cannot
replay work or overwrite/adopt an existing output. A consistent nonzero subject
outcome can retain complete resource accounting without becoming test success.
Every record remains `confirmatory_eligible: false`.

## Evidence format and use

[`resource-observation-v1.schema.json`](../bench/harness/resource-observation-v1.schema.json)
is a distinct, closed resource record. It reuses typed host/process definitions
but does not relabel v1/v2 paired evidence. Offline schema resolution and strict
integer/boolean/nonfinite/depth checks apply. The inspector separately checks
scope/parent binding, fresh initial values, timing order/enclosure, raw/derived
counter agreement, nondecreasing cumulative counters, sample maxima, capability
gaps, enrollment, residual-work flags and failure classification.

[`inspect_resources.py`](../bench/harness/inspect_resources.py) uses retained
historical evidence, never later-mutated live cgroups. Inspection exit zero
means consistency, **including** consistent failed/unsupported observations;
check `status`, `run_attempted` and `whole_boundary_accounting_complete` rather
than treating that exit as a passing test. Malformed or contradictory records
exit 2. Resource observations cannot authenticate the kernel/history or prove
equal work, stable inputs, generation validity or independence.

Example, from the repository root, using an existing delegated experiment
parent supplied by the operator (the placeholder is not a setup script):

```sh
parent="/path/to/existing/delegated/cgroup"
directory="$(mktemp -d /tmp/opencode/pt-resource.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/resource_run.py --cgroup-parent "$parent" --cwd . --timeout 10 --output "$directory/resource.json" -- bench/harness/.venv/bin/python -c 'print("ready")'
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_resources.py "$directory/resource.json"
```

Use `--allow-missing-peak` only for an intentionally partial diagnostic. Outputs
are no-overwrite private files; args, paths and hashes can reveal sensitive data,
so review before sharing. External pre-existing daemons/services and cgroup
escapes are unsupported, not invisible free capacity. This is non-hostile,
caller-owned delegation, **not a sandbox** or production supervisor qualification.

For a warm replay, create the coordinator/seed/services inside this fresh unit
and keep all interactions, idle periods and required shutdown inside the same
command. The peak is the whole independent session's peak, never a secretly
reset per-request peak. Wrapping a complete paired driver measures the **whole
campaign**, not per-arm resources; do not divide its peak into arm values. A
separate resource pass must never be attached to earlier latency observations as
if it measured that same execution. The subsequent
[paired-resource follow-up](wp01-paired-resources.md) implements explicit stage
units and campaign validation/summaries without changing this counter format.
Frozen-campaign/scenario governance, latency/resource qualification and
observer-effect characterization remain open. Verification below is historical
to this standalone-resource batch; the follow-up records current suite results.

## Verified controls and remaining limits

Run from the repository root with the unchanged lock:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_cgroup_accounting.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

On the selected Linux x86-64, GIL-enabled CPython 3.12.12 development host:

- **280 full locked harness tests ran: 279 passed and one was explicitly skipped**
  (`Ran 280 tests in 71.497s`, `OK (skipped=1)`).
- **68 separate contract/audit tests passed** (`Ran 68 tests in 8.223s`, `OK`).
- `git diff --check` and **61 edited-document local links** passed. All **8**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing v1/v2 schemas and dependency/toolchain/support pins are
  unchanged.
- The **32 resource methods** cover capability failures, fresh/non-adopted
  boundaries, startup/read/cancellation/cleanup faults, decreasing counters,
  transient native-peak versus sampled-current distinction, unsupported promotion,
  malformed scope/types, immutable publication and preserved nonzero outcomes.
  **Seven** methods are native/capability-gated; the other **25** use explicitly
  synthetic counter states. Synthetic peak checks are not native peak evidence.
- On this **5.15.0-203-generic** host, native CPU/current/event/population/kill
  capabilities are usable, but `memory.peak` is absent. The native sequential
  child-peak test is explicitly skipped with that reason. No peak measurement,
  complete native accounting profile or peak support qualification is claimed.
- Native controlled workers allocate/touch 64 MiB and consume at least 200 ms
  of their own CPU time. Whole-cgroup accounting exposes that descendant work,
  including a deliberately detached, pipe-closing worker and a worker in a
  nested cgroup after its leader exits zero. Both negative controls require
  recursive kill, retained failure status, empty final hierarchy and removal of
  the owned group. Subject argv/cwd/environment and private-FD closure are also
  checked. These are resource fixtures, not PT conformance or benchmark samples.

Direct CLI evidence is retained locally at
`/tmp/opencode/pt-resource-accounting-evidence-a9_c_mew`, outside the repository:

| Functional case | Producer / inspector exits | CPU usage delta (µs) | Maximum sampled current (bytes) | Classification |
|---|---|---:|---:|---|
| Strict missing-peak control | 3 / 0 | null | null | Unsupported; marker proves no subject ran |
| Cooperative descendant | 1 / 0 | 320939 | 79360000 | Explicit partial diagnostic; no kill |
| Detached worker, leader exit zero | 2 / 0 | 310740 | 79515648 | Failed; recursive kill and group removal |
| Nested-cgroup detached worker | 2 / 0 | 330361 | 79523840 | Failed; recursive kill and subtree removal |

Every row has **null native peak** and false complete-accounting/confirmatory
flags. These numbers demonstrate functional observation only, not a performance
comparison. Four retained mutations (leader-only CPU, invented zero peak,
missing final counter and direct-process-only scope) each make the inspector
exit **2**, without traceback. Failed/unsupported records were not dropped.

Retained development limitation: an initial read-only host probe assumed
`cgroup.type` existed at the unified root and failed with `FileNotFoundError`.
The corrected probe recorded root absence rather than changing the host. The
resource tests themselves have not had a failing run in this batch; unsupported
peak remains the visible capability skip, not a waived success.

WP01 still requires native peak qualification, full resource budgets and
scenario/campaign integration, overhead characterization, broader broken-runner
controls, semantic/work/generation validation and complete evidence/result cards.
WP02/WP03, WP04 completion and backend/qualification/release gates remain open in
the [prerequisite register](wp01-status.md). Rust/bridge, qualified corpus
materializations, PT conformance and performance campaigns were not rerun.
Dependency/lock, toolchain and support pins and the v2 schemas are unchanged.
