# Exploratory harness prototype

This is an independent command timer and supporting prototype. It does **not**
qualify outcomes, compare work, capture resource totals in its default paired path,
semantically validate campaign manifests, reset state, retain raw output by default, or implement
the benchmark protocol. It cannot issue confirmatory or performance claims.
Known-delay regression tests cover process startup, shutdown, pipe drainage,
controlled real-pytest collection/teardown, test-owned reporting, real coverage.py
combine/save/JSON reporting, cooperative resource release, and opt-in raw-capture
publication/spool cleanup. These are instrumented harness fixtures, not PT
conformance or coverage qualification. They do not validate every product or
campaign timing boundary. See [WP01 evidence and open gates](../../docs/wp01-status.md).
On Linux, a separate timer test exercises timeout termination of an ordinary
owned child process group. It does not establish PT process supervision or
containment of hostile or detached descendants.
On POSIX, output is hashed and counted in bounded-memory chunks; it is not
retained. Timeout cleanup kills the process group and bounds pipe drainage.
Detached descendants may escape cleanup, and incomplete drainage is reported
as `output_complete: false`; the timer is not a sandbox. On non-POSIX systems
legacy `measure()` still uses in-memory pipes and process-tree cleanup is not
covered; the new standalone publication-inclusive endpoint requires safe POSIX lookup.
Unexpected harness errors and interruptions trigger bounded, best-effort child
termination; cleanup is not guaranteed if OS process control fails.

`resource_run.py` is a **separate, opt-in diagnostic resource pass**, not a silent
change to the paired timer. It creates a fresh private child of an explicitly
supplied, already delegated cgroup-v2 parent on Linux x86-64. An isolated observer
launcher enrolls itself before `exec` of the unchanged subject command; all future
inheriting descendants are counted, including detached/nested-cgroup workers.
It records raw `cpu.stat`, `memory.current`, `memory.peak` when available,
`memory.events`, recursive population and bounded current-memory samples. CPU
totals are whole-cgroup counter deltas; kernel peak charged memory is **not**
RSS/PSS or a sum of historical per-process maxima. The sample maximum is only a
lower bound on charged current memory and is never promoted to a measured peak.

Default resource mode requires every capability and starts **no subject work**
if peak accounting/delegation/enrollment/cleanup is unavailable. Only the explicit
`--allow-missing-peak` diagnostic may retain CPU/current observations without a
peak; its status is `partial_unsupported`, peak is `null`, and complete-accounting
and confirmatory flags remain false. Unknown dynamic-loader environment profiles
also block enrollment without silently changing the subject's environment.
No controllers, limits, host caches or existing process memberships are modified.
No pre-existing daemon/service is adopted. Background work outliving the leader
is retained as a failure, followed by one recursive cgroup kill and bounded empty
checks; forced termination or uncertain counters/cleanup cannot become success.

Resource passes use the distinct closed
[`resource-observation-v1.schema.json`](resource-observation-v1.schema.json), not
an extension of v2 paired records. `inspect_resources.py <record>` validates
historical types, scopes, capabilities, clocks, counter arithmetic, samples and
failure accounting; inspection exit zero never means the subject passed. It
cannot authenticate the history or account for escaped/external pre-existing
work. A whole replay can be one fresh resource unit; a whole paired-campaign
wrapper is **not** per-arm accounting and must not be divided into per-arm peaks.
See [resource scope, CLI exit codes, native capability limits and evidence](../../docs/wp01-resources.md).

`replay_resources.py --plan <fixed-replay.json> --output <new-directory>
--outer-timeout <seconds>` now observes **one complete managed replay in one fresh
cgroup**, through a separate enrolled harness driver. This is a new opt-in
diagnostic invocation, not an automatic rerun or extra metrics attached to a
latency observation. Preparation, requested idle waits, future background
descendants, ordered interactions, required shutdown, inner publication and
driver reporting all remain inside that resource group. Driver imports and
observer work performed by that driver are included without subtraction; the
outer observer/sampler remain outside cgroup CPU/memory totals.

Use an explicit existing `--cgroup-parent`; no controllers/limits are changed.
Strict mode starts no driver if a required capability, including `memory.peak`,
is unavailable. Only `--allow-missing-peak` permits a partial observation, retaining
a null peak and false complete-accounting. The separate outer watchdog must cover
the execution budget, reserved shutdown and at least five seconds of slack. It
can still interrupt shutdown or reporting; a missing receipt never proves cleanup.
Detached work outliving even a successful replay is counted, killed and failed.

The distinct closed [`replay-resource-v1.schema.json`](replay-resource-v1.schema.json)
binds the request, raw resource record, driver receipt/transport and complete
nested session bytes. Save the returned stdout receipt **outside** the bundle.
`inspect_replay_resources.py --directory <run> --receipt <receipt.json>` checks
historical evidence without worktree/cgroup access or another command invocation.
Failed/unsupported/not-run/unknown phases, missing counters, publication faults
and driver/observer clock provenance remain explicit. There is no cross-process
clock arithmetic, per-interaction resource imputation, idle-only attribution,
latency ratio/bootstrap or qualification upgrade. Producer exits are 0 for complete
unqualified accounting, 1 for explicit partial support, 2 for failure/invalid
evidence and 3 for unsupported/no subject; inspector exit 0 is consistency only.
The standalone mode does not add paired replay resource campaigns/cards; existing
latency and card formats, including their null qualification fields, are unchanged.
See [reproduction, exact scope, watchdog limits and native controls](../../docs/wp01-replay-resources.md).

`paired_replay_resources.py --baseline-plan <replay.json> --candidate-plan
<replay.json> --output <new-directory> --blocks N --seed S --outer-timeout T`
now pairs **new whole-session resource diagnostics**, using the separate closed
[`paired-replay-resource-v1.schema.json`](paired-replay-resource-v1.schema.json).
Each considered arm uses one fresh group through preparation, idle/background
work, shutdown and driver reporting. The matched-workflow declarations, separate
arm cwds, common timeout/capture policies and shared input/edit/state declarations
reuse the existing replay contract, not its latency observations or estimators.

Use `--cgroup-parent` or per-arm `--baseline-cgroup-parent` /
`--candidate-cgroup-parent` for already-delegated parents. Only explicit
`--allow-missing-peak` permits partial diagnostics. A clean unsupported check
continues to the next scheduled arm; a failed or unconfirmed observation,
cleanup or publication stops **all later sessions** without retry. Their planned
not-run rows remain visible. Lost returns retain unknown effects and metrics,
even if a diagnostic unit file exists; publication copies cannot invent commits.

`inspect_run.py` and `summarize_run.py` route this kind explicitly. Inspection
checks every nested resource/replay binding, exact arm settings/driver, unique
group paths/invocation IDs, same-process call order and abort cause, with bounded
before/after snapshots. It accesses neither current worktrees nor cgroups and
executes no commands. Every planned combined diagnostic and underlying replay
outcome remains visible, with separate resource/session invocation certainty.

Per-arm summaries retain observed CPU sums **including failed-unit costs**, metric
observation/missing counts, and maxima per observed **whole session**. They never
invent a campaign-wide peak or replace missing data with zero. Unsupported,
partial, failed, unknown, unconfirmed or unguarded/incompletely declared campaigns
have blocked summaries. Even fully observed diagnostic campaigns have null latency
ratio/absolute comparison/bootstrap and unknown verified independence. Bootstrap
requests are rejected. The subsequent resource-card integration below adds a
distinct reporting format, never relabelling existing cards/schemas; old cards
require their matching reader revision after routing changes.
See [layout, status accounting, native controls and reproduction](../../docs/wp01-paired-replay-resources.md).

The separate `scenario_replay.py run --plan <scenario.json> --payloads <blobs>
--output <new-directory> --apply` now validates an explicit declared-file scenario:
reset, guarded create/replace/delete edits, seed-bearing request-file delivery,
fresh serial request commands and required shutdown. The distinct closed
[`scenario-replay-v1.schema.json`](scenario-replay-v1.schema.json) preserves exact
bytes/modes/presence before and after each phase, full planned denominators,
partial/unknown effects and failed/not-run outcomes. Reset/edit effects are
nontransactional and never retried or rolled back. Roots must be separate;
parents must already exist. No service reset, dependency mutation, global-cache
operation or hidden pytest collection is added.

`scenario_replay.py inspect --directory <run> --receipt <external-receipt.json>`
reconstructs offline from retained blobs, never later worktree state. The `compare`
subcommand checks two retained arms' exact declared reset/edit/input/seed/cache/
timeout policies while retaining all outcomes. Matching files are not proof of
input consumption, actual loaded code, equal work, cache state, resets or independent
units. Those qualifications stay null. Environment-change, affected-watch and
OS-cold profiles (S6/S7/S9) are explicitly unsupported before effects. Scenario
validation is a correctness-instrumented layer, not a latency/resource sample or
a new card format; latency estimators reject it. See [scope, CLI, safety and
adverse controls](../../docs/wp01-scenario-replay.md).

`paired_scenarios.py --baseline-plan <scenario.json> --candidate-plan <scenario.json>
--payloads <input-blobs> --output <new-campaign> --blocks N --seed S --apply`
integrates those observations into balanced seeded AB/BA **scenario-validation**
campaigns. Separate arm worktrees and exact matching reset/edit/input/seed/cache/
timeout/exit policies are mandatory; arm commands may differ and remain individually
bound. Shared payload bytes are validated and frozen before any arm runs. Each
scheduled arm gets a new standalone scenario unit, not an independently sampled
request. Clean S6/S7/S9 unsupported checks continue; a failed or unconfirmed unit
stops all later sessions without retry or rollback.

Routed `inspect_run.py <campaign>` and `summarize_run.py <campaign>` retain each
actual returned reset ledger, request-input snapshot, publication certainty and
all planned session/request/phase/file-effect denominators. Lost whole-unit returns
retain null observations and `unknown_unobserved` effects, never reconstructed
success from complete-looking files. Summaries are offline with six required null
qualifications and null latency/resource statistics; bootstrap and result-card
relabelling are rejected. This adds no shipping latency endpoint, native resource
pass, semantic oracle or reset-equivalence qualification. See [layout, CLI exits,
controls and reproduction](../../docs/wp01-paired-scenarios.md).

The existing `result_card.py <retained-campaign> --output <new-card.json>` and
`inspect_result_card.py <card.json> --run <retained-campaign>` now route paired
whole-session resource evidence to
[`replay_resource_card.py`](replay_resource_card.py) and its distinct closed
[`replay-resource-card-v1.schema.json`](replay-resource-card-v1.schema.json).
Generation/reconstruction is offline: no commands, resets, resource passes or
current-worktree checks. Every planned session and nested retained byte/directory
is bound, including fragments after a lost return; diagnostic files alone never
become confirmed outcomes or metrics.

Cards preserve combined diagnostic/managed replay statuses, separate boundary/
session invocation certainty, phase/interaction counts, publication flags, errors,
cleanup and descriptive observed costs. Failed-unit CPU remains counted; missing
metrics stay null and memory maxima stay per observed session. All **24**
qualification fields remain required null, even with complete diagnostic accounting.
There is no latency ratio/bootstrap, campaign-wide peak, isolated idle attribution,
verified independence or qualification upgrade. Full source-bound reconstruction,
not schema validation or a matching digest alone, is required. Publish outside
the evidence tree; output is private/no-overwrite and observed source/reader
mutation fails without retries. Generator exit 1 retains a blocked card; inspector
exit 0 is consistency only. See [scope, reproduction and adverse controls](../../docs/wp01-replay-resource-cards.md).

`paired.py --timing-endpoint resource` now integrates these observations into a
**distinct resource-diagnostic campaign**, not an extra run attached to a latency
sample. Its closed [`paired-resource-v1.schema.json`](paired-resource-v1.schema.json)
plan binds exact per-stage commands, contracts, guards and resource settings.
Each requested preparation/probe/measurement uses one fresh resource invocation;
stage metadata binds its retained raw observation by name/size/SHA-256. File checks
and declared-byte archival follow that resource endpoint as observer work, not
as a falsely relabelled publication-inclusive latency. Default lifecycle and
legacy command modes and their schemas remain separate and unchanged.

Use `--resource-cgroup-parent`, or per-arm `--baseline-resource-cgroup-parent` /
`--candidate-resource-cgroup-parent`, for existing delegated parents. Only
`--resource-allow-missing-peak` permits partial diagnostics; optional resource
sample/grace settings have their own `--resource-*` flags. Resource options in
other timing modes, and raw-prefix capture in resource mode, fail before work.
`inspect_run.py` validates contexts, settings, byte bindings, distinct groups,
interval order, guard/file/archive evidence, abort causes and every planned arm.
Unsupported preparation/probes skip their arm; resource/finalization/storage
failures stop later work without replay. Valid diagnostic abort copies preserve
observations when observer publication fails; corrupt/unexplained fragments are
not deleted or approved to make a campaign complete.

Resource summaries expose all measurement arms and requested stages, including
unsupported, partial, failed, skipped, aborted and uncertain-invocation outcomes.
Per-arm resource statistics describe **measurement stages only**; preparation and
probe costs remain separately visible. Observed CPU sums retain failed-unit costs
and report unknown-unit counts; they are not complete-campaign cost estimates.
Memory fields are maxima **per observed unit**, never summed process maxima or
an invented campaign-wide peak. No missing metric is imputed as zero.
Resource-mode ratio/absolute-latency/bootstrap fields stay null, even for complete
diagnostic data; bootstrap requests and direct latency-estimator use of resource
endpoints are rejected. Partial/unsupported/failing campaigns have blocked
summaries, not favorable complete-subset estimates. See
[format, exit codes, denominators and verified limits](../../docs/wp01-paired-resources.md).

`schedule.py` independently generates reproducible balanced AB/BA block orders;
it does not establish independent observations. `paired.py` can run those
orders sequentially and preserve individual unqualified observations. It checks
declared finalization evidence, not general state or test work. Optional per-arm `--baseline-prepare-json` and
`--candidate-prepare-json` commands run before each arm, with separate timing
and records; failed preparation prevents that arm from running. Preparation is
not measured in the arm's elapsed time and is not proof of a valid reset. A zero
exit from the paired driver means only that records were written, not that
either command succeeded or was equivalent.
Optional `--baseline-cwd` and `--candidate-cwd` choose separate working
directories for each arm's preparation, probe, and measurement; otherwise both
use `--cwd`. Separate paths do not prove isolated or equivalent input states.
Optional `--baseline-probe-json` and `--candidate-probe-json` commands run after
successful preparation and before the corresponding measurement. Their output
hashes and statuses are recorded separately; nonzero exits or timeouts skip the
arm. A zero probe exit does not itself verify or certify equivalent state.
Optional `--baseline-probe-guard-json` and `--candidate-probe-guard-json` also
compare probe stdout to an explicit expected byte count and SHA-256; a mismatch
skips the arm even if the probe exited zero. Guarded probes must expect exit zero.
This is an observation check, not proof of equivalent starting state.
`state_probe.py --root <directory> --file <relative-path> [...]` hashes explicit
regular files, rejecting symlinks in listed paths and the root's final component.
It emits deterministic JSON suitable for a probe guard, but does not inspect
undeclared inputs, reject symlinks in ancestors of the supplied root, or provide
an atomic snapshot. File names and even hashes may disclose sensitive information.
`../resets/restore_declared_files.py` is a separately documented, opt-in reset
prototype for disposable worktrees; it can be supplied as a preparation command.
If a preparation or measurement reports incomplete output drainage or an
unreaped direct process, the runner preserves the arm record and aborts before
starting later arms. Reaped direct processes and drained pipes still do not prove
that detached descendants have exited.
`inspect_run.py <run-directory>` checks planned block order, record presence,
arm identities, arm-record schema, output metadata shape, and preparation/result
consistency. The default version-2 format also requires bound lifecycle receipts
and retained declared artifact bytes. A consistent recorded abort accounts for
all planned arms as observed or not run; unexplained partial runs and unexpected
files are rejected. Inspection exit zero means consistency, not a completed or
qualified campaign; `record_consistency: aborted` always blocks analysis.
Inspection cannot authenticate records or verify unobserved work/current state.
When all stage intervals are available, inspection rejects recorded overlap or
out-of-order stages; legacy records with missing intervals are labelled
`incomplete` for that check. Recorded non-overlap cannot prove actual resource
isolation or rule out detached descendants.
`guards.py` compares a timer result to an expected exit and stdout sentinel;
even a match cannot prove equal work, correct generation, or artifact validity.
The paired driver accepts `--baseline-guard-json` and `--candidate-guard-json`
with explicit `expected_exit_code`, `expected_stdout_bytes`, and
`expected_stdout_sha256` fields. It retains matching and mismatching outcomes;
inspection recomputes guard verdicts rather than trusting recorded booleans.
`summarize_run.py <run-directory>` can calculate an exploratory paired point
estimate only when every arm completed and matched a requested guard; any
missing guard, mismatch, failed lifecycle or measurement blocks the estimate instead of
dropping pairs. Recorded aborts, missing interval ordering or explicitly truncated raw captures
also block the estimate. A matching sentinel still does not establish equal work, and
the summary is neither authenticated nor confirmatory.
The summary includes absolute mean arm latencies and can optionally run a
whole-block percentile bootstrap using `--bootstrap-resamples N --bootstrap-seed
S`. These values remain exploratory: input independence, equal work, sample
adequacy, and release criteria are not established by the calculation.
`sample.schema.json` describes legacy version-1 command-only arm records. New
version-2 plans, samples, receipts and aborts use `paired-plan-v2.schema.json`,
`sample-v2.schema.json`, `receipt-v2.schema.json` and `paired-abort-v2.schema.json`,
with shared definitions in `lifecycle-v2.schema.json`. `evidence.validate_v2()`
resolves only bundled schema URNs, rejects unknown/missing fields and requires
actual integer tokens (not booleans or `1.0`) for integer fields. Strict decoding
also rejects duplicate keys, nonfinite/overflowed numbers and nesting beyond 64
levels. A standard JSON Schema validator alone does not enforce that integer-token
policy. Production and inspection validate these formats, then check stage
context, contracts, guards, both finalization observations, clocks and exact
sample/retained-byte bindings. Valid failed or skipped observations remain
inspectable and unqualified; unexplained omissions and contradictory evidence do
not. None is the complete WP01 raw-evidence format or establishes benchmark
validity. See [the schema contract and retained failures](../../docs/wp01-evidence-v2.md).
`junit_inventory.py` compares ordered JUnit classname/name/outcome attributes,
preserving duplicates. JUnit is not authoritative pytest collection or phase
evidence; the comparison omits tracebacks and must not be used as an oracle.
`coverage_lines.py` compares exact paths and executed/missing/excluded line sets
from no-context, non-branch coverage.py JSON reports. It does not verify coverage
core, configuration, subprocess behavior, source identity, or PT conformance.
The schedule records basic host and harness-Python metadata, including the
harness executable's path and digest. It does not record environment variables,
inspect arm interpreters, or establish machine limits. Paths and command arguments
may contain sensitive information; review records before sharing.
New timer records include start/end monotonic nanoseconds and their clock domain;
only differences within the recorded harness process are meaningful. Older v1
records without these optional fields remain readable.
`elapsed_ns` starts immediately before process launch, after argument/cwd checks,
and ends after leader/pipe handling and any opt-in raw-capture finalization.
The standalone sample JSON and paired arm/schedule records are published **after**
their **command** intervals. The standalone CLI now also emits a post-commit
JSON receipt on stdout, with a separate `lifecycle.elapsed_ns` covering API-entry
validation, the command, sample publication/temp cleanup/read-back and declared
finalization checks. The receipt is bound to the sample's exact digest/size; the
sample alone does not claim this larger interval completed. Receipt serialization
and stdout transport are observer bookkeeping outside that declared endpoint.
See [the endpoint contract and failure controls](../../docs/wp01-lifecycle.md).
The paired driver now defaults to publication-inclusive stage samples and saved
receipts. Preparation, probe and measurement each include declared report
archival, guard checking, sample publication, cleanup/read-back and finalization
verification. Analysis uses the measured arm's **lifecycle** interval, not its
inner command interval. `--timing-endpoint command` explicitly retains legacy
command-only behavior; finalization contracts are rejected in that mode. Plans,
receipts and summaries name their endpoint, and mixed/relabeled or partly
unlabelled observations cannot be combined. Receipt-file persistence and initial
schedule publication are observer bookkeeping outside the stage interval, but
must finish before the next stage; neither is claimed part of an amortized replay.
See [paired lifecycle format, failures and historical validation](../../docs/wp01-paired-lifecycle.md).
Neither endpoint establishes a complete generation-valid result, watch/replay
lifecycle, resource containment or confirmatory eligibility.

`managed_replay.py --plan <fixed-plan.json> --output <new-directory>` now provides
a **separate bounded whole-session replay endpoint**, not a change to paired
timing. Its closed [`managed-replay-v1.schema.json`](managed-replay-v1.schema.json)
requires preparation, 1–32 ordered interactions and shutdown, with explicit argv,
timeouts, idle waits, optional stdout guards and canonical file contracts. It
uses fresh serial processes and shared declared state, not a reused execution
interpreter, daemon/service manager or semantic oracle. Preparation/shutdown
must expect exit zero; an interaction can explicitly expect a nonzero outcome.

One API-entry wall clock includes validation, plan publication, preparation,
idle waits, interactions, required shutdown, declared-byte archival, aggregate
unit publication/read-back and final checks. Failure stops later interactions
without retry; shutdown is attempted once using its own reserved finite command
timeout even after the execution budget expires. A missing observation preserves
unknown invocation certainty. Failed/skipped phases remain in the complete ledger.
Declared file absences do not prove process containment or external-resource release.

The private bundle contains `plan.json`, observed `step-NNNN.json` files,
`unit.json` and `blobs/`. The aggregate unit embeds phase receipts and binds every
retained input by path/bytes/SHA-256. The **post-endpoint session receipt is returned
on stdout**, not saved into its own measured bundle. Capture it outside that
directory and pass it separately to
`inspect_replay.py --directory <run> --receipt <receipt.json>`. Inspection checks
historical bytes, order, enclosing clocks, budgets, contracts, failure/skip causes,
publication and shutdown without rerunning commands or rereading a later worktree.
Missing/corrupt/mixed evidence is not repaired or treated as a completed subset.

Each replay is **one observed session**, with verified independence unknown.
Phase rows are labelled `managed_replay_step` / `replay_step`; direct latency and
bootstrap estimators reject either label. Replay summaries have null comparisons,
bootstraps and resources, and false confirmatory eligibility. Declared bounded
raw-prefix truncation remains visible, not a claim to have retained full output.
The standalone profile does not itself add result-card, native resource,
edit/generation or frozen-campaign integration. Generator exits are 0 for completed
unqualified observation, 1 for observed failure/timeout/deadline, and 2 for observer,
publication or invalid-input errors. Inspector exit 0 means consistent evidence,
including an accounted abort, not successful tests. See
[reproduction, boundaries, failure controls and remaining gates](../../docs/wp01-managed-replay.md).

`paired_replay.py --baseline-plan <replay.json> --candidate-plan <replay.json>
--output <new-directory> --blocks N --seed S` now pairs **complete managed
sessions**, using a separate closed
[`paired-replay-v1.schema.json`](paired-replay-v1.schema.json). Each scheduled
AB/BA arm creates a new replay bundle and includes its own preparation, fixed
interactions and reserved shutdown. Arm cwds must be separate/nonnested; IDs,
order, idle waits, timeouts, expected exits and capture policies must match.
Shared `--pairing-json` declarations name `input_seed`, `edit_sequence_sha256`
and `external_state_sha256`; omitting the option records all three as explicit
unknowns, while a supplied object must name every field. They are
not verified identities, applied edits, injected environment seeds or reset proof.

The first failed or unconfirmed session stops the campaign without retry. The
fixed schedule and required abort record account for every later not-run session;
missing returns retain unknown session/effect certainty and bound diagnostic
bytes where available. Receipts are persisted outside their measured replay
directories before another session starts. Publication failures cannot invent a
confirmed commit, and malformed/mixed evidence cannot be approved as an abort.

`inspect_run.py` and `summarize_run.py` route this format explicitly. Analysis
uses each replay receipt's **whole-session** wall clock, not interaction times or
a sum of nested clocks. A point estimate/optional seeded bootstrap is exploratory
only and requires all planned complete sessions, confirmed publication, guards
on every phase, untruncated raw capture and resolved shared declarations. Any
failure/not-run/unknown session blocks the entire comparison, not just its pair.
Bootstrap draws whole paired sessions; verified independent sessions/blocks,
work/generation validity and whole-session resources remain unknown. Paired-replay
result cards now have the distinct format described below; command, lifecycle
and resource formats are unchanged. See
[layout, reproducible controls, limits and remaining gates](../../docs/wp01-paired-replay.md).

`analysis.py` implements a paired geometric point estimator and exploratory
whole-block percentile bootstrap for caller-qualified samples. It rejects invalid
or incomplete blocks but cannot verify qualification, independence, statistical
adequacy, or publication gates; calculated intervals are not release evidence.
`manifest.py` checks bounded regular-file YAML input, strict JSON-compatible
types and the unchanged campaign schema. Integer fields do not accept booleans
or integral floats, and numeric/boolean constants retain their declared types.
Aliases, duplicate keys, excessive nesting, nonfinite/non-JSON values, malformed
pin strings and NUL command/cwd values are rejected. The reader requires safe
POSIX relative lookup and does not follow the manifest's final symlink.
For drafts it still lists paths that fail frozen-schema requirements; this is
a structural preview, not verification of referenced files or hashes.

The checker now separately reports bounded **declaration** conflicts: affected
scope labelled equal work, differing declared interpreters for equal work,
parallel workers under `serial-pytest-v1`, invocation-only amortization/session
cost, or inconsistent non-cluster resampling and analysis units. It does not
invent semantics for unknown contracts, parse selectors, run commands, inspect
actual interpreter builds or prove resets, budgets, work or independence.
CLI exits are 0 for no known declaration conflict, 1 for structurally valid but
conflicting declarations, and 2 for malformed/unsupported input. Every output,
even a structurally frozen manifest with matching-looking pins, remains
`confirmatory_eligible: false` and lists unchecked requirements. The structural
loader used by the separate artifact tool remains a structural API; its digest
checks do not implicitly apply or replace this declaration report. See
[rules, input policy and observed controls](../../docs/wp01-manifest-checks.md).

`result_card.py <run-directory> --output <new-card.json>` now generates a closed,
evidence-bound **exploratory JSON result card** from one inspected paired run.
It reuses the existing summary/inspection once; no subject, reset, collection,
resource pass or artifact-producing command is run again. Command-only,
publication-inclusive lifecycle and resource-diagnostic endpoints remain distinct.
Every planned measurement arm is retained, including failed, unsupported,
partial, skipped, aborted and uncertain-invocation outcomes. Resource-stage costs
remain separately visible. Missing qualification fields are explicit nulls,
never zero counts, inferred version pins or successful full-run assertions.

The card inventories every retained record and blob by relative path, bytes and
SHA-256, plus empty `blobs/` when present. It binds the reader/analysis source and
schema/lock bytes, generator runtime versions and exact optional bootstrap
request. A domain-separated reconstruction digest combines those inputs.
Before/after file fingerprints reject observed mutation during generation and
publication without retries. The output must be outside the run directory and
cannot overwrite an existing file. In the original command/lifecycle/resource
card format, limits are 4096 evidence files, 128 MiB per
blob, 512 MiB aggregate input and 4 MiB per card; oversize evidence/cards fail
instead of dropping arms or truncating entries. Existing stricter record limits
still apply. This is safe POSIX, caller-owned-path bookkeeping, not authentication
or an atomic snapshot.

`inspect_result_card.py <card.json> --run <run-directory>` validates the distinct
closed card schema (`result-card-v1.schema.json` for command/lifecycle/resource
cards), then independently
reconstructs the whole card from the source bundle with the recorded analysis
request. A standalone schema match or edited inventory hash cannot approve a
card. Changed source bytes, omitted outcomes/null fields, fabricated metrics,
reader/runtime differences and qualification upgrades are rejected. Byte-identical
copies of a retained bundle can be relocated without changing the card.

All card formats are `classification: exploratory`, with false confirmatory
eligibility and zero qualified units. The original format's 21 unresolved fields include real arm/source pins,
pytest/plugins, test-work counts, independence, generation, budgets, reset,
coverage, fallbacks, exclusions, full-session/idle costs and review. Generator
Python and plan host metadata are not measured-arm identities. No campaign
manifest/qualification attachment is consumed by this first card format.
Guard-only latency estimates stay explicitly exploratory; blocked cards retain
null estimates, and resource cards never get latency ratios or bootstraps.
Generator exit 0 means a nonblocked exploratory report, 1 means a preserved
blocked report, and 2 means invalid evidence/publication. Inspector exit 0 means
consistent reconstruction, including consistent failures, not a qualified result.
See [bindings, denominators, CLI examples and retained limits](../../docs/wp01-result-cards.md).

The same card commands now dispatch paired-replay campaigns to
[`replay_result_card.py`](replay_result_card.py) and the separate closed
[`replay-result-card-v1.schema.json`](replay-result-card-v1.schema.json). They do
not rerun any session or reinterpret interactions as independent samples. Every
planned session remains in schedule order, including aborted, not-run and unknown
returns. Phase/interaction counts, shutdown outcomes, publication flags, diagnostic
fragments and abort causes remain visible; unknown elapsed/phase observations
remain null. The existing whole-session summary and all its blockers are retained.

Replay cards bind every root record and nested session file/blob by full relative
path, byte count and SHA-256, including diagnostics and empty retained directories.
The new recursive inventory and reconstruction digests also bind reader/schema/lock
bytes, runtime versions and exact analysis options. Before/after snapshots span
generation and publication; independently reconstructed cards must match in full.
Changing just a digest, omitting failed sessions, relabelling unknown effects or
inventing independence/resources cannot approve a card. Limits are 8192 files,
1 GiB source bytes and 4 MiB per card, with the stricter replay/record limits still
enforced. Oversize data fails without truncating records or dropping sessions.

All **24** replay qualification fields are mandatory nulls: the original 21 plus
actual matching replay inputs/state, independent block count and whole-session
resource accounting. Shared declared pins do not fill them. The card includes
complete declared arm plans and basic host observations, not verified arm identities.
Qualified-session count remains zero; CPU/memory/idle resources and verified
independent counts remain unknown. Existing card generator/inspector exit rules
remain unchanged; replay generator output reports `planned_session_count` rather
than relabelling sessions as command arms. See
[replay-card fields, reproduction and observed controls](../../docs/wp01-replay-result-cards.md).

`artifact_check.py <manifest> <bundle>` separately checks the manifest's listed
artifact digests against regular files named by SHA-256 in a supplied local
bundle (safe POSIX lookup only). It rejects symlink targets and reports unresolved
or mismatched fields. It cannot verify revisions, provenance, semantic content,
reset equivalence, or a stable snapshot; even all matches remain unqualified.
`blob_store.py` provides bounded, content-addressed, no-overwrite publication.
Blob files are now published with Linux `renameat2(RENAME_NOREPLACE)`, requiring
a libc wrapper and kernel/filesystem support. The synchronized staging file is
moved atomically, so a newly visible inode has no staging alias for its creator
to unlink during a duplicate reader's verification. Unsupported native operations
fail visibly; there is no hard-link, overwrite-rename or check-then-rename
fallback. Existing-blob verification still rejects any device/inode/size/mtime/
ctime change or wrong digest; it does not retry away evidence of mutation.
Content-addressed names and blob record fields are unchanged. This remains a
caller-owned-directory prototype, not a hostile-directory/parent-path security
boundary or a power-loss-durable store.
The standalone timer can optionally retain bounded stdout/stderr prefixes with
`--raw-output-bundle <existing-directory> --raw-limit-bytes <per-stream-limit>`
on Linux with that native publication support. Truncation is explicit and full
observed-stream hashes remain separate;
spooling and blob publication are inside the timer, so this is instrumented
timing, not an unmodified product benchmark. The paired driver can opt in with
`--capture-raw --raw-limit-bytes <per-stream-limit>` and stores blobs in its run
directory for each preparation, probe, and measured arm. Inspection verifies
referenced blob sizes and hashes but cannot authenticate the records or files.
Blob publication does not authenticate content or guarantee
power-loss durability. A blob-publication failure aborts the sample instead of
publishing a successful record; previously published blobs may remain. Raw output
can contain secrets; enable it deliberately.
Declared finalization artifacts in version-2 paired runs are separately retained
by digest even without `--capture-raw`. This explicit file declaration is an
opt-in to retain those report bytes, including bounded mismatches. The run root
is created privately; review its reports, arguments, paths and hashes before
sharing. Later stages may overwrite worktree outputs: paired inspection checks
the retained historical bytes and typed observations, not current worktree state.

The original concurrent-publication failure is retained in
[`docs/wp00-review.md`](../../docs/wp00-review.md). The link/unlink publication
protocol changed ctime when the creator removed its staging alias, even though
the blob's bytes matched. A deterministic regression pauses the creator after
publication and finishes it during a duplicate verification; it fails the old
protocol even on coarse ctime clocks by exposing its second link. Tests also
preserve rejection of ctime-only/other fingerprint changes with matching bytes,
corrupt/non-regular/symlink entries, fsync/native failures and unsupported
publication, and exercise multi-threaded and multi-process callers. This is
functional harness evidence, not completion of WP01 or PT qualification.

Targeted regression command (run from the repository root):

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_blob_store.py -v
```

Timing-boundary regression command:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_timing_boundaries.py -v
```

Publication/finalization regression commands:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_lifecycle.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_finalization.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_lifecycle.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_evidence_v2.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_cgroup_accounting.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_result_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_managed_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_result_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_replay_resources.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_resource_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_scenario_replay.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_paired_scenarios.py -v
```

For each arm, `--baseline-finalization-json` / `--candidate-finalization-json`
declare measurement requirements. `--baseline-prepare-finalization-json` and
`--baseline-probe-finalization-json` (and candidate equivalents) apply separately
to those stages. All use the standalone contract's three fields. Preparation and
probe require exit zero; a measurement guard's explicit exit is also bound into
its finalization contract. Conflicts fail before execution. Publication/archival
failure or uncertain cleanup stops later arms without replay. An abort blocks
point estimates/bootstrap/absolute comparisons for the entire planned set.

`--finalization-json` optionally declares `expected_exit_code` (an integer or
`null`), `artifacts` (relative paths with exact byte counts/SHA-256), and `absent`
(relative paths that must not exist). All three fields are required when supplying
the option. These checks run before and after publication, without retries or
repair. The final sample is also re-read after validation. Opt-in raw blob
references are checked against actual bytes, including the explicit prefix limit.
An omitted contract defaults to no expected exit or external-file/absence checks;
undeclared test work/resources are never implied verified. A lifecycle receipt
with `finalized_unqualified` is an observation, **not a test-pass result**.
Safe POSIX relative lookup is required for this new endpoint; unsupported systems
fail visibly. Legacy `measure()` itself is unchanged.

The parent holds each observed stage for 0.15 seconds, requires the command to
remain pending, then checks that its own monotonic hold interval is enclosed by
the timer. Exact stage order, fixture phases, reports, merged line sets and
resource-release evidence are checked separately. Six omitted-wait controls and
six prematurely ended record mutations must be rejected, as must an unreleased
resource despite zero exit and complete reports. These checks are local to the
fixture; `measure()` does not acquire a semantic or resource validator from them.
Coverage.py **7.17.2** is a locked, test-only development dependency on Python
>=3.11; the coverage-backed stage checks explicitly skip on Python 3.10. Only the
selected CPython 3.12.12 development profile was exercised. No pytest-cov plugin
or product dependency was added, and no effective coverage core, branch/context,
subprocess-coverage or ecosystem support claim follows.

Install the pinned prototype dependencies and run tests from the repository root
with `uv` (the environment is local to `bench/harness`):

```sh
uv sync --locked --project bench/harness --python 3.12.12
uv run --locked --project bench/harness --python 3.12.12 python -m unittest discover -s bench/harness/tests -v
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/manifest.py bench/benchmark-campaign.template.yaml
```

Example exploratory observation and receipt check (write outside the repository):

```sh
directory="$(mktemp -d /tmp/opencode/pt-bench.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/pt_bench.py --cwd . --timeout 5 --output "$directory/sample.json" --finalization-json '{"expected_exit_code":0,"artifacts":[],"absent":[]}' -- bench/harness/.venv/bin/python -c 'print("hello")' > "$directory/receipt.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_lifecycle.py --sample "$directory/sample.json" --receipt "$directory/receipt.json"
```

An `exited_unqualified` observation means only that the process exited; even a
zero exit is not evidence that expected work happened. By default, output hashes
and sizes are recorded instead of content.
Records are published via a same-filesystem hard link after serialization and
file synchronization, without overwriting existing paths. A crash can leave a
hidden temporary file, and directory entries are not synced for power-loss
durability. Filesystems without hard-link support reject publication.
The CLI returns 1 for timeout/launch failure or unmatched declared checks, and 2
for preflight, measurement/publication or receipt-output errors. Failure receipts
and failed sample observations are retained when possible. A failure can leave
partial blobs, a staging file or a visible sample without a valid receipt; none
is a finalized lifecycle. Existing paths are never overwritten or automatically
adopted, and publication failure never replays command work.
