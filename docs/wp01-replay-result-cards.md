# WP01 evidence-bound paired-replay result cards

Status: **bounded reporting/reconstruction implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `fe8adbe`. This extends
[paired complete-session replay](wp01-paired-replay.md) with a distinct card format,
not a semantic oracle, native resource integration or qualification of support.
`pt run` and qualification/release gates remain unavailable. No test-runner speedup
has been measured.

## Same commands, a separate closed replay format

[`result_card.py`](../bench/harness/result_card.py) now dispatches the retained
paired-replay campaign kind to
[`replay_result_card.py`](../bench/harness/replay_result_card.py). The new
[`replay-result-card-v1.schema.json`](../bench/harness/replay-result-card-v1.schema.json)
names `kind: paired_replay_exploratory_result_card` and
`sample_unit: complete_managed_session_replay`. Existing command/lifecycle/resource
cards and all existing execution schemas are unchanged. A replay cannot be
relabeled as a legacy command card or an independent interaction sample.

Generation uses the existing read-only inspection/summary path **once**, retaining
every planned session in schedule order. It does not rerun sessions, collect tests,
invoke resets, apply edits, change dependencies, launch resource passes or import
project code. It does not replace historical observations with later worktree
files. All card generation/reconstruction/publication is offline observer work
outside the named managed-session endpoint; no estimated reporting tax is deducted.

For an existing replay bundle (replace the placeholder), or a disposable fixture
created with the [paired-replay reproduction](wp01-paired-replay.md):

```sh
run="/path/to/retained/paired-replay"
directory="$(mktemp -d /tmp/opencode/pt-replay-card.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/result_card.py "$run" --output "$directory/card.json" --bootstrap-resamples 30 --bootstrap-seed 7
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_result_card.py "$directory/card.json" --run "$run"
```

The example resample count is a functional demonstration, not confirmatory policy.
Omit both bootstrap options if not requested. Missing/failed/unknown sessions or
other summary blockers still produce a **blocked** card with null comparisons,
not a favorable subset. The generator exits **0** for a nonblocked exploratory
card, **1** for a preserved blocked card and **2** for invalid evidence/options or
publication failure. Inspector exit **0** means consistent reconstruction,
including consistent failures, not passing tests; malformed cards exit **2**.

## Outcome and qualification come before statistics

| Card section | Retained facts and explicit limits |
|---|---|
| `qualification` | Always `not_established`, zero qualified sessions and **24 required null fields**. No switch upgrades this format to qualified or release-confirmatory. |
| `denominators` | Planned blocks/sessions/phases/interactions, every session outcome, observed/unknown/not-run accounting, and null verified independent session/block counts. |
| `session_observations` | Every planned session, ordered context, source status, invocation certainty, receipt/metadata publication flags, observed wall interval or null, phase/interaction statuses, guard counts, shutdown, fragment/truncation counts and failure/outcome reasons. |
| `campaign` / `blockers` | Recorded complete/aborted state, observer-failure flag, abort cause/context/error and diagnostic-presence flags; all existing analysis blockers. Full diagnostic bytes remain bound in the evidence inventory. |
| `statistics` | The existing whole-session summary, not a new estimator. All blocked ratios, absolute comparisons and bootstraps remain null; resources remain unknown even for a complete guarded campaign. |
| `context` | Exact declared baseline/candidate replay plans, schedule/seed, shared input/edit/state declarations and basic host observations, not verified environments or matching work. |
| `evidence` / `generator` | Complete recursive source-byte inventory, reader/schema/lock bytes, generator runtime versions and exact analysis request, not authenticity or executed-code provenance. |

The original **21** unresolved fields remain mandatory: candidate/baseline
revisions/binary hashes; actual arm Python/pytest/plugins; repository identity;
scenario/cache vector; machine/resource budget; semantic contract/equal work;
collection/execution occurrences; independent sessions; generation; resets;
coverage; fallbacks/exclusions; full-session/idle cost qualification; observer
effects; corpus eligibility/partitions; and preregistration/review. Replay adds
**actual matching inputs/external state, independent block count and whole-session
resource accounting**. Every value is null. Known wall intervals are not a
qualification of all full-session/idle/resource costs or semantic work.

Shared declared hashes and input seed are retained under `context`, never copied
into verified qualification fields. Generator Python and basic host metadata are
not measured-arm identities. Unknown work/exclusions/fallbacks/resources are not
imputed as zero. A complete stdout/file sentinel or explicitly expected nonzero
exit is an unqualified observation, not occurrence-aware test conformance.

### Failure, not-run and unknown are different

- A failed session remains `aborted`; prior completed sessions and every later
  `not_run_run_aborted` session remain in the denominator. Nothing is retried or
  discarded to calculate a complete-subset estimate.
- A missing replay API return remains `harness_error` with null invocation
  certainty, elapsed time, phase/interaction observations and shutdown status.
  Even a retained complete `unit.json` without its returned confirming receipt
  is diagnostic bytes, not a known completed endpoint.
- Known not-invoked sessions also have null observed clocks/status maps, but their
  planned phases/interactions are counted as **not run**, not unknown effects.
- A returned session may itself have unknown phase invocations. Its per-session
  `phase_invocation_counts` retain that distinction; campaign `unknown_phase_count`
  instead counts phases whose entire session observation is missing.
- A completed session with unconfirmed receipt/metadata publication stays visible
  with false commit flags and a blocked campaign. An inventory entry is not proof
  that a failed publication was confirmed. Diagnostic fragments are not promoted
  to independent samples, and explicit raw-prefix truncation cannot disappear.

Session counts sum to planned sessions; observed phase statuses plus known-not-run
and unknown phases sum to planned phases. Interaction counts have the analogous
accounting. These are harness ledger counts, **not executed-test denominators**.

Only the existing all-session guarded summary can produce an exploratory point
estimate. Bootstrapping draws **whole paired complete sessions**, never individual
interactions; verified independence stays null. Declared input agreement does not
establish actual equivalent work or valid inferential assumptions. No native peak,
CPU, idle-residency, break-even, tail-latency or release claim is inferred.

## Recursive bindings and independent reconstruction

The generator inventories **every retained root record and nested session file**:
campaign/abort/receipt/metadata records, session plans, steps, units, declared
artifact/raw blobs and attributable diagnostics. Relative paths retain their full
session prefix; equal blob hashes in different sessions do not erase path entries.
Actual session directories and retained `blobs/` directories, including empty ones,
are listed too. There is no ignored hidden file or filtered failed sample.
Existing inspectors still reject unexplained extras, missing records, mixed plans,
corrupt bytes and unaccounted aborts before a card can be approved.

The new inventory format is `sha256_canonical_recursive_replay_inventory_v1`.
Its SHA-256 input is the ASCII prefix `pt:replay-result-card:inventory:v1\n`
followed by canonical JSON of sorted `directories` and path-sorted `files`, each
entry containing `path`, `bytes` and `sha256`. Canonical JSON uses sorted object
keys, compact separators, ASCII escaping and finite JSON numbers. The digest
includes paths/sizes, not just a commutative bag of content hashes. Filesystem
fingerprints guard reads but are not part of the portable card identity.

`generator.implementation` inventories the explicit reader/analysis Python files,
all needed closed schemas and dependency/lock bytes, including replay and common
card readers. `generator.runtime` retains Python/jsonschema/referencing/PyYAML
versions; missing package identity is an error rather than an invented version.
The reconstruction digest is SHA-256 of
`pt:replay-result-card:reconstruction:v1\n` plus the same canonical JSON policy
over `evidence_sha256`, `implementation_sha256`, `runtime` and `analysis_request`.
Different analysis options therefore have a different reconstruction identity
even when the raw bundle is unchanged. This does not authenticate preregistration.

[`inspect_result_card.py`](../bench/harness/inspect_result_card.py) validates the
new closed schema and reconstructs the **whole card** from retained source bytes
using the recorded analysis options and reader/runtime identities. Every field
must agree, not merely its inventory digest or statistical shape. Omitting failed
or unknown sessions, forging time/statistics/commit flags, altering reader identity,
promoting input declarations or changing qualification is rejected. A matching
schema alone is not approval. Byte-identical copied bundles can relocate; the
card does not reread later worktree files as past results.

Before/after source fingerprints cover generation and publication without retries,
including identity-only changes. These are not authenticated atomic snapshots or
a hostile-filesystem boundary. Caller-owned ancestors remain outside the safety
boundary. Hashes bind files read, not proof of which subject or reader code actually
executed; historical clocks/stat/absence observations remain unauthenticated.
Use the appropriate historical reader for old cards: `fe8adbe` is this batch's base,
and later source changes are not silently accepted for an exact reconstruction.

## Publication and limits

Reuse private no-overwrite publication, synchronization and exact read-back. Card
output must be **outside** the source bundle, and cannot replace an existing file
or follow the final output-parent symlink. The source/implementation bindings are
checked again after publication. A post-publication error may leave a stale or
unconfirmed file; the API reports failure and does not delete it or replay work.
Reconstruction rejects changed-source cards. A complete matching copy can still
be checked independently; this is not a power-loss-durability or signature claim.

The campaign limits remain **8192 files / 1 GiB retained source bytes**, **128 MiB
per blob**, bounded root/session trees and the stricter per-record/managed-replay
limits. The new card itself is at most **4 MiB**. Oversize input/cards fail instead
of dropping ledger rows, truncating records or removing adverse evidence. Safe
POSIX lookup is required; symlinks, FIFOs and unexpected nesting are not read as
ordinary evidence. Commands, paths, report contents and hashes can reveal secrets;
keep raw bundles/cards private and review before sharing. No raw results are
committed as benchmark evidence.

## Verification and retained functional evidence

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_replay_result_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

All **37 targeted replay-card tests passed** (`Ran 37 tests in 93.840s`, `OK`).
They cover complete/failing/not-run/unknown sessions; lost returns after unit
commit; unknown inner phases; shutdown/timeout/launch failures; diagnostic and
unconfirmed publication flags; raw/guard/input-declaration blockers; whole-pair
resampling; deterministic/moved history; schema/types/qualification forgeries;
omissions; source/reader mutations; nonregular/oversize inputs; publication faults;
runtime identity errors; and CLI dispatch/rejection. These regression and explicit
synthetic fingerprint/record controls are not native resource or PT conformance
qualification. The paired-replay dispatch regression is updated to require a
blocked distinct replay card for a no-return abort, not a legacy relabelling.

- **470 full locked harness tests ran: 469 passed and one existing native-peak
  capability test was skipped** (`Ran 470 tests in 291.836s`, `OK (skipped=1)`).
  This includes all **37 new replay-card methods** and the updated dispatch control.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.297s`, `OK`).
- `git diff --check` and **106 edited-document local links** passed. All **4**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.
- The reproduction block above was executed directly from the document against
  a retained fixture campaign and passed. Its card has four sessions, two whole
  bootstrap blocks and 24 unresolved fields; separate functional evidence is at
  `/tmp/opencode/pt-replay-card-doc-smoke-u29qoogb`.

Direct CLI controls are retained outside the repository at
`/tmp/opencode/pt-replay-result-card-evidence-xymiezln`:

- **13 source cases**: complete, failed preparation, later interaction failure,
  expected nonzero, guard mismatch, interaction timeout, unreleased shutdown,
  execution deadline, unresolved identities, raw-prefix truncation, missing return
  before observation, missing return after unit commit and unconfirmed receipt
  publication. Ten reuse copied prior replay bundles; three are explicit fresh
  adverse fixture producers. Reporting reruns **none** of their subjects.
- Every card preserves **four planned sessions / sixteen phases / eight
  interactions**, **24 null qualification fields**, unknown verified independence
  and resources, false confirmatory eligibility and unchanged source bytes. The
  two all-guarded cases return generator **0**; the eleven blocked cases return
  **1** with null estimates. Every card inspection returns **0** as unqualified
  consistency, including the aborted/unknown cases.
- The same complete evidence/options produces a byte-identical second card.
- **Twelve forged cards** (classification upgrade, missing unknown field, promoted
  declaration, invented independence/resources, reordered/omitted sessions,
  unknown-as-not-run, invented commit, changed wall time, interaction resampling
  and changed reader source) each make inspection exit **2**, without traceback.
  Several have plausible typed counts/digests but fail full reconstruction.
- **Eight malformed source campaigns** (schedule, missing receipt, wrong receipt
  binding, early call clock, omitted shutdown with rebound digests, later executed
  session after abort, missing abort and corrupt blob) make generation exit **2**
  without a card. No failed observation becomes an exclusion or favorable subset.

## Remaining prerequisites

This completes the focused evidence-bound replay reporting integration, **not
WP01 acceptance**. The later [whole-session resource mode](wp01-replay-resources.md)
provides one separate diagnostic replay, without relabelling these cards or filling
their qualification fields. [Paired resource replay scheduling and summaries](wp01-paired-replay-resources.md)
are now a separate diagnostic profile, with distinct
[resource-replay cards](wp01-replay-resource-cards.md) preserving all missing metrics
and unresolved qualification fields. Native peak qualification, actual
work/generation/input/reset equivalence, semantic manifests,
scenario/edit replays,
observer overhead, frozen campaigns, corpus governance and independent review
remain open. Missing `memory.peak` gates native peak qualification only, not further
implementation. WP02–WP04 completion, the real backend/oracle and qualification/
release dependencies remain in the [prerequisite register](wp01-status.md).
Rust/bridge builds, qualified materializations and real PT conformance/performance
campaigns were not rerun by this offline reporting batch.
