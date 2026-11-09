# WP01 evidence-bound paired resource-replay cards

Status: **bounded offline reporting/reconstruction implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `3857899`. This adds a distinct reporting format for
[paired whole-session resource campaigns](wp01-paired-replay-resources.md), not a
semantic oracle, resource-budget qualifier or release. `pt run` and the real
pytest backend/oracle remain unavailable. No test-runner speedup is established.

## Existing card commands, a separate diagnostic format

[`result_card.py`](../bench/harness/result_card.py) dispatches the retained
`paired_replay_resource_campaign` kind to
[`replay_resource_card.py`](../bench/harness/replay_resource_card.py). The distinct
closed [`replay-resource-card-v1.schema.json`](../bench/harness/replay-resource-card-v1.schema.json)
names `kind: paired_replay_resource_exploratory_result_card`,
`measurement_layer: resource_diagnostic` and
`sample_unit: complete_managed_session_replay`. It cannot be relabelled as a
legacy command/per-stage resource card, latency replay or independent interaction.
Existing execution/card schemas, dependency locks and support pins are unchanged.

Generation uses the existing read-only whole-campaign inspection/summary path
**once**. It never invokes subjects, resets, edits, collection, resource passes or
current-worktree checks, and never imports project code. Reconstruction is offline
too. All card work is outside the original diagnostic endpoint. Driver overhead
remains charged in the retained observation; outer observer/card overhead stays
outside cgroup CPU/memory totals without subtraction. Driver and outer-observer
clock provenance stay separate; no cross-process arithmetic is introduced.

For an already retained paired resource campaign (replace the placeholder), or
evidence deliberately created using the separate
[campaign reproduction](wp01-paired-replay-resources.md#reproduction-disposable-test-owned-sessions-not-a-benchmark):

```sh
run="/path/to/retained/paired-resource-replay"
directory="$(mktemp -d /tmp/opencode/pt-replay-resource-card.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/result_card.py "$run" --output "$directory/card.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_result_card.py "$directory/card.json" --run "$run"
```

The generator exits **0** for a nonblocked diagnostic card, **1** after publishing
a preserved blocked card, or **2** for invalid evidence/options/publication.
Inspector exit **0** means exact unqualified reconstruction, including consistent
failures, not passing tests or qualified native support; malformed cards exit **2**.
Do not add bootstrap options: either nonnull bootstrap argument is rejected before
recursive capture. The analysis request contains two required null fields.

## Outcomes and qualification before descriptive costs

| Card section | Preserved evidence and limits |
|---|---|
| `qualification` | Always `not_established`, zero qualified sessions and **24 required null fields**, including whole-session resource qualification. |
| `denominators` | The complete planned session/phase/interaction ledger, combined diagnostic and underlying replay status counts, observed/unknown/not-invoked accounting, and null verified independence. |
| `session_observations` | Every scheduled session, separate boundary/session invocation certainty, phase/interaction counts, guards, shutdown, counters, capabilities, errors, group/cleanup details and publication/accounting flags. |
| `campaign` / `blockers` | Complete/aborted recording state, declared interval order, diagnostic-accounting flag, abort context/cause/error and diagnostic-presence flags, plus every existing summary blocker. |
| `statistics` | Unmodified resource-only summary: observed CPU sums including failed-unit costs, observation/missing counts and per-observed-session memory maxima. No latency estimator or campaign peak. |
| `context` | Exact arm plans/commands, schedule/seed, shared input/edit/state declarations, resource settings, driver declaration, observer process, original root and host observations, not verified arm environments or matching work. |
| `evidence` / `generator` | Recursive source-byte/directory inventory, selected reader/schema/driver/lock bytes, generator runtime versions and exact analysis request, not authenticity or executed-code provenance. |

`session_status_counts` describes the **combined diagnostic** outcome; the separate
`replay_session_status_counts` describes managed replay outcomes. A resource failure
can coexist with a completed inner replay. `unit_observation_count` includes clean
unsupported checks, whereas `observed_sessions` counts returned managed receipts,
including aborted replays. Neither is a passed-test or independently reset sample
count. Known, unknown and not-invoked boundary/session counts each sum to the
planned sessions; phase and interaction status counts retain their full plans too.

The original 21 unresolved qualification fields remain null: arm revisions/binary
digests; actual Python/pytest/plugin identities; repository and scenario/cache
identity; machine/resource budget; semantic contract/equal work; collection and
execution occurrences; independence; generation; resets; coverage; fallbacks and
exclusions; full-session/idle cost qualification; observer effects; corpus eligibility/
partitions; preregistration/review. The three replay additions also stay null:
**actual matching inputs/external state, independent block count and whole-session
resource accounting**. The schema reuses the unchanged 24-field null contract from
[latency replay cards](wp01-replay-result-cards.md), not their estimators.

Even `all_session_accounting_complete: true` means only consistent complete
diagnostics and publication in the declared scope. It does not qualify native
peak support, valid resets, equal resource budgets, independent units, occurrence-aware
semantic work, qualified artifacts or an accepted corpus. Generator runtime/host
metadata are not measured-arm Python/plugin identities. Observed resource costs do
not fill `full_session_and_idle_cost` or `observer_effects` qualification.

### Unsupported, failed, not-run and unknown stay different

- A clean unsupported check retains known-not-invoked phases and null resource
  metrics; it is not an executed zero-cost session. Explicit partial mode retains
  CPU/current/event observations but null kernel peak and incomplete accounting.
- A failed session retains failed/skipped phase outcomes, required shutdown,
  prior observations and all later not-run sessions. Failed-unit CPU remains in
  the descriptive observed sum, not filtered out to form a favorable subset.
- A leftover worker after matching shutdown sentinels remains a failed diagnostic,
  even with a completed inner replay. Kill/removal/residual and error details stay
  visible when a whole-unit observation returned.
- A lost **whole-unit API return** leaves its session effects, metrics and detailed
  observations unknown, even if complete-looking resource/driver/unit files exist.
  Those bytes stay bound as diagnostics only; no offline recovery promotes them.
- When a wrapper observation returned but its **managed replay return** is missing,
  resource counters can remain known while managed phases/shutdown remain unknown.
  The driver error remains explicit. The card does not equate boundary invocation
  with confirmed application work.
- Unconfirmed paired receipt/session publication retains returned observations and
  matching diagnostic copies with false commit flags, an accounted abort and a
  blocked card. Visible bytes do not retroactively confirm a failed API return.
  Inner resource publication faults similarly retain returned diagnostic counters
  and observer errors, without inventing a resource-record commit.

Per-arm `unknown_units` counts every missing metric, including unsupported,
known-not-run and lost-return units; causes remain in the rows. Observed CPU sum is
not a whole-campaign total if any unit is missing. Memory maxima are **per observed
whole session**, never summed historical maxima or a simultaneous campaign peak.
With no observations for a metric, its aggregate is null, not zero. Sampled current
never replaces absent `memory.peak`. Strict mode here cannot start a native subject
without that capability.

Both blocked and nonblocked diagnostic cards require **ratio, absolute latency,
bootstrap, campaign-wide peak, idle-only and per-phase resource metrics to be null**.
Row elapsed time also stays null; retained driver/resource clocks are not latency
samples. Expected nonzero fixture outcomes may be consistent diagnostics, not
passing tests. No tail, break-even, resource-efficiency or release claim follows.

## Recursive bindings and independent reconstruction

The inventory includes every root record and every nested unit/session/blob file:
schedule, abort, returned receipts, paired metadata, requests, resource/driver
records, managed plans/steps/units, artifacts, raw prefixes and diagnostic fragments.
Full relative prefixes are retained even for identical blob bytes. Actual unit,
session and blob directories, including empty ones, are listed. There is no
ignored hidden file or filtered failed observation. Existing inspectors reject
unexplained extras, missing records, mixed bindings, contradictory rebound records,
unaccounted aborts, corrupt blobs and nonregular inputs before a card is approved.

The inventory format is
`sha256_canonical_recursive_resource_replay_inventory_v1`. Its digest input is
the ASCII prefix `pt:replay-resource-card:inventory:v1\n` followed by canonical
sorted JSON of the full sorted directory/file inventory. Entries bind relative
path, byte count and SHA-256. Total byte count is recorded and reconstructed too.
The same format binds the explicitly listed implementation files: common readers/
schemas/analysis/lock, resource/session readers and schemas, enrolled driver and
launcher, and blob/raw-capture code. Tests and subject fixtures are not treated as
executed-code provenance. These hashes are not an authenticity or executable audit.

`reconstruction_sha256` hashes the ASCII prefix
`pt:replay-resource-card:reconstruction:v1\n` plus canonical JSON containing the
evidence digest, implementation digest, generator runtime and analysis request.
It is not a signature or a sufficient validation of the card's other contents.
`inspect_result_card.py` validates strict closed schemas, independently rebuilds
from the source bundle and recorded null options, then compares **the entire
expected card**, including outcomes, counters, errors, contexts, inventories,
runtime/reader identities and qualification fields. Editing only a digest or
passing structural validation cannot approve a plausible forged statistic.

Byte-identical relocated history reconstructs identically while retaining its
historical origin declarations. Before/after fingerprints reject observed source
or reader mutation without retry, including identity-only changes. A byte change
that leaves the summary equivalent still changes the evidence binding. Historic
cards require their matching reader/schema/runtime revision: this routing change
changes `result_card.py` bytes; `3857899` is the preceding reader base. Keep the
matching environment/lock when reconstructing. No historical evidence is rewritten.

## Publication, limits and safety boundary

Publish the card **outside** the bound campaign tree, including through directory
aliases. Existing output is refused before reconstruction. Shared publication
creates a private **0600**, no-overwrite file, reads back expected bytes and
rechecks evidence/implementation fingerprints. A fault after visible publication
may leave an unconfirmed card file; the API reports failure and does not delete
files to manufacture success. A later reconstruction still checks the source.

The closed profile accepts at most **128 sessions / 64 blocks**, **8192 evidence
files / 1 GiB**, **384 unit/session/blob directories**, **128 MiB per blob**, and a
**4 MiB card**, with all stricter campaign/unit/record/plan/sampling bounds retained.
Large plans/inventories may hit the card limit earlier than campaign limits.
Oversize cards fail rather than drop sessions, fragments or inventory entries.
These are accepted-evidence limits, not a disk quota or a guarantee that failing
storage leaves no oversized partial file.

Safe bounded final-path lookups, fingerprints, private output and byte hashes are
not an atomic snapshot, hostile-filesystem boundary, provenance service or
power-loss-durability guarantee. Caller-owned ancestors remain outside the lookup
boundary. Paths, argv, errors, reports, raw prefixes and hashes can reveal secrets;
review before sharing. Raw evidence/cards stay outside the repository.

## Verification

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_resource_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The new card tests use disposable explicitly synthetic counter/enrollment fixtures
and cached source copies to exercise offline reporting. Synthetic peak checks are
not native qualification. Retained native diagnostics are inspected offline, not
rerun for card generation. Full-suite native capability outcomes must be reported
separately from these card controls.

**43 new targeted card tests passed** (`Ran 43 tests in 120.664s`, `OK`). They
cover complete, partial, unsupported, failed, not-run and unknown sessions; missing
metrics/returns; pre-launch and shutdown failures; leftover workers; publication
faults; guard/raw/pairing blockers; exact reconstruction, strict types/closed
schemas, forged costs/qualification/cleanup, relocation, identity/byte mutation,
safe output and bounded evidence. None is a native peak qualification test.

Retained development failure: the initial **40-test** card run had **one error**,
not an accepted adverse result. The legacy-kind relabel rejection test removed
its temporary harness import path and then lazily imported the alternate latency
reader; it raised `ModuleNotFoundError` instead of the expected schema rejection.
An independently run paired-card dispatch regression exposed the analogous
test-isolation issue. Both tests now temporarily restore the CLI-equivalent
import path for their lazy dispatch calls. No production policy or adverse case
was weakened. Three added controls distinguish pre-launch setup failure, known
not-run work after a frozen-driver change, and lost resource returns with known
managed outcomes. The updated paired-card dispatch control passed independently
(`Ran 1 test in 1.587s`, `OK`).

- **591 full locked harness tests ran: 590 passed and one existing native-peak
  capability test was skipped** (`Ran 591 tests in 683.638s`, `OK (skipped=1)`).
  This includes all **43 new card controls** and the updated paired-card dispatch
  regression. The capability skip is not native peak support qualification.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.613s`, `OK`).
- `git diff --check` and **147 edited-document local links** passed. All **4**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block was run directly from this document against retained
  no-parent evidence: four unsupported/not-invoked sessions, all 24 qualification
  fields null, no subject rerun, and exact blocked-card inspection exit **0**.
  Evidence is at `/tmp/opencode/pt-replay-resource-card-doc-smoke-4dwlo5pf`.
- A retained latency replay card with a post-unit lost return also reconstructs
  unchanged using an isolated copy of its matching `af29661` reader: one unknown
  session, three later not run, blocked and unqualified. No historical subject
  was rerun. That check is at `/tmp/opencode/pt-resource-card-history-pqlyr9qc`;
  the new reader does not rewrite old cards to fit its different source bindings.

Direct offline CLI evidence is outside the repository at
`/tmp/opencode/pt-replay-resource-card-evidence-n9z3zpff`, using the retained
`3857899` paired-resource campaigns without running them again:

- **13 source campaigns** produced and reconstructed cards with every planned
  outcome and all **24** qualification fields null. The inputs include seven
  explicitly synthetic campaigns, five retained native campaigns and one no-parent
  refusal campaign. Source bytes/directories were unchanged, and repeated card
  files were byte-identical. Only the synthetic complete campaign had a nonblocked
  diagnostic summary; no synthetic peak was presented as native support.
- Retained strict-native evidence stays **two unsupported sessions** with null
  metrics; retained explicit-partial evidence stays **two partial sessions** with
  null peak and incomplete accounting. A leftover-worker failure plus a later
  not-run arm retains cleanup details; a later interaction failure retains the
  prior partial observation, failed-unit costs and two later not-run sessions.
- Missing whole-unit returns before observation or after a complete-looking unit
  commit remain **one unknown + three not run**, with null unconfirmed metrics.
  Failed paired receipt publication remains visible with false commit flags.
  Neither a diagnostic file nor an inventory entry recovers a lost API return.
- **22 forged cards** were rejected with inspection exit **2**, without traceback.
  Controls cover qualification promotion/missing fields, false native zero peak,
  complete-accounting promotion, erased failed costs/missing metrics/cleanup,
  unknown-as-not-run/zero/completed, fake commits/execution, reordered ledgers,
  float/bool tokens, invented independence/latency/campaign peak, wrong runtime,
  a forged reconstruction hash and an omitted evidence entry. Several remain
  structurally plausible but fail full reconstruction.
- **12 malformed source campaigns** made generation exit **2** without a card:
  malformed schedule, missing/wrong receipt binding, early call clock, omitted
  shutdown with rebound transport/digests, reused group, invented zero peak,
  wrong coordinator provenance, missing abort, unexpected later unit, extra file
  and false failure abort. Three unsupported bootstrap option combinations also
  failed before card publication. No failure became a favorable subset.

## Remaining prerequisites

This completes the focused resource-replay reporting step, **not WP01 acceptance**.
The subsequent [declared-file scenario validator](wp01-scenario-replay.md) now
binds reset/edit/request-input evidence separately, without upgrading these cards.
Integration with latency/resource campaigns, actual semantic/work/generation/input/reset
validation, non-file finalization, complete manifest/qualification/evidence
integration, native peak qualification, resource budgets, observer-overhead
characterization, frozen campaigns, corpus governance and independent review
remain open. Missing `memory.peak` gates native peak qualification only, not
continued implementation. WP02–WP04 completion, the real pytest backend/oracle and
qualification/release dependencies remain in the [prerequisite register](wp01-status.md).
Rust/bridge builds, qualified materializations and real PT conformance/performance
campaigns are not part of this harness-only reporting batch.
