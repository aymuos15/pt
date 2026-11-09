# WP01 evidence-bound exploratory result cards

Status: **implemented bounded reporting/reconstruction; WP01 remains open**.
Date: **2026-11-09**. Base: `7b5cfcd`. This follows
[paired resource diagnostics](wp01-paired-resources.md) and
[campaign declaration checks](wp01-manifest-checks.md). It does not qualify a
runner, oracle, benchmark campaign, support profile or release. `pt run` remains
unavailable; no test-runner speedup is established.

The later [paired-replay card integration](wp01-replay-result-cards.md) uses a
distinct closed schema and recursive evidence inventory through the same commands.
The original command/lifecycle/resource format and historical verification below
remain distinct; reader source changes require the appropriate historical reader.

## Generate from evidence, not another subject invocation

[`result_card.py`](../bench/harness/result_card.py) consumes one retained paired
run and writes a new JSON card **outside** that run. It calls the existing
inspection/summary path once, then uses its complete ordered observations. It
does not replay commands, import project code, collect tests, run resets, mutate
dependencies or launch another resource pass. It does not use PT's own timing.

```sh
run="/path/to/retained/paired-run"
directory="$(mktemp -d /tmp/opencode/pt-card.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/result_card.py "$run" --output "$directory/card.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/inspect_result_card.py "$directory/card.json" --run "$run"
```

Use a real retained run in place of the placeholder. The generator handles the
existing command-only, publication-inclusive lifecycle and separate resource
formats without relabelling their endpoints. It emits no card for unexplained
missing/corrupt input; an explicitly accounted abort is valid input for a
**blocked** card. No incomplete favorable subset is used as a replacement run.

An optional `--bootstrap-resamples N --bootstrap-seed S` records the exact request
for the existing exploratory whole-block latency bootstrap. Existing bounds and
blockers still apply. Resource-mode bootstrap requests remain unsupported, not
silently ignored or converted to latency observations. Caller-selected analysis
options are not proof of preregistration or independent units.

## Card fields and unresolved qualification

[`result-card-v1.schema.json`](../bench/harness/result-card-v1.schema.json) is a
new, closed, offline record type; existing run schemas are unchanged. The card
contains:

| Section | What is retained and what is not inferred |
|---|---|
| `classification` / `qualification` | Always exploratory, not established, false confirmatory eligibility and zero qualified arms. No option upgrades this format to qualified/release-confirmatory. |
| `denominators` | Planned blocks/arms, every source status count, known attempted/not-invoked/unknown invocation counts, guard counts and available stage counts. |
| `measurement_observations` | Exactly one entry per planned arm, in schedule order: context, source status, observed return code, named elapsed interval where available, guard/finalization state, errors and resource observations. |
| `stage_resource_observations` | Every requested resource stage, including preparation/probe costs and later stages not run. These overlap measurement entries; they are views of the same units, not extra independent replicates or additive costs. |
| `blockers` | The complete existing summary's causes and contexts, including abort/storage/finalization/guard/capability limitations. |
| `statistics` | The existing unqualified summary, not a new estimator. Blocked estimates remain null. Resource CPU sums retain unknown-unit counts; memory maxima are per observed unit. |
| `context` | The plan's exact requested argv/cwd/stage guards/timeout/seed, actual named endpoint/layer and retained host observations. These are historical declarations/observations, not proof of work or arm-environment identity. |
| `evidence` / `generator` | Complete input byte inventory, reader/analysis source/schema/lock inventory and generator-runtime versions, not product-artifact provenance. |

All **21 required qualification fields** are explicitly null: candidate/baseline
revisions and binary digests; arm Python/pytest/plugins; repository revision;
scenario/cache state; machine profile/resource budget; semantic contract/equal
work; collection/execution occurrences; independent-session count; generation;
reset; coverage; fallback/exclusion accounting; full-session/idle costs;
observer effects; corpus eligibility/partitions; preregistration/review. Existing
evidence does not establish those facts. Unknown work/exclusions/fallbacks are
not replaced with zero. A matching stdout sentinel is not occurrence-aware work
or a passing full-suite result.

This first card format consumes **no campaign declaration or qualification
attachment**. It does not copy plausible-looking manifest pins into verified
fields, infer identity from command names, or substitute generator Python for
subject Python. Manifest/real-oracle/frozen-campaign integration remains open.

`source_summary_observed_arms` retains the earlier summary's own counter, whose
legacy meaning can include not-run records. The separate known/unknown
invocation counters describe the card's measurement rows and sum to the planned
arms. `source_summary_guard_counts` retains the earlier labels;
`guard_status_counts` distinguishes unrequested from requested-but-unobserved
guards in the card's rows. None is a collected/executed-test denominator.

When a measurement observer returns no process/resource result, invocation can
remain unknown. A known preparation-stage abort does not imply measurement
started. Resource diagnostic copies retain their publication flags; a diagnostic
copy is not promoted to a confirmed commit. Expected nonzero outcomes can be
observed consistently without being called passing tests.

Qualification and outcome/unsupported coverage are explicit before the card's
statistics. Even an all-guard-matched latency card is exploratory only. Resource
cards never acquire latency ratios, absolute comparisons or bootstrap intervals;
partial/unsupported/failed campaigns retain blocked statistics and null peaks
where unavailable. Missing `memory.peak` does not block this reporting work.

## Byte bindings and reconstruction

The generator inventories **all** retained records, abort/diagnostic fragments
and blobs after bounded safe file lookup. There are no ignored hidden files,
unreferenced favorable samples or omitted failed arms. Existing inspectors
still reject unexplained extras. An empty `blobs/` directory is also represented.
Each file entry records normalized relative path, byte count and SHA-256.

The inventory digest is SHA-256 of the ASCII prefix
`pt:result-card:inventory:v1\n` followed by canonical JSON of `directories` and
`files`: sorted object keys, sorted directory/path lists, compact separators,
ASCII escaping, finite numbers only. It includes paths and sizes, not just a
commutative collection of file digests. Filesystem inode/timestamp identities
are checked during generation but excluded from this portable byte identity.

`generator.implementation` similarly binds the explicit reader/analysis Python
sources, their schemas, `pyproject.toml` and `uv.lock`. `generator.runtime` records
the reader's Python implementation/version and jsonschema/referencing/PyYAML
versions. Missing package identity is an error, not an invented version.

`reconstruction_sha256` is SHA-256 of the ASCII prefix
`pt:result-card:reconstruction:v1\n` followed by the same canonical JSON policy
over `evidence_sha256`, `implementation_sha256`, `runtime` and `analysis_request`.
A changed analysis request creates a different reconstruction identity even
when the raw evidence is unchanged. Hashes do not authenticate that request or
prove which producer/subject code actually ran.

Before/after source fingerprints and named directory identities must agree
across inspection, card construction and publication. Observed ctime-only,
content, name, directory or implementation changes fail without retry. These
checks are not an atomic snapshot or a defense against a hostile filesystem.
Caller-owned ancestor paths remain outside the trust boundary.

[`inspect_result_card.py`](../bench/harness/inspect_result_card.py) requires the
retained run and reconstructs the **entire card** using the recorded options.
Standalone schema acceptance or internally plausible hashes cannot validate a
forged report. Changed numbers, order, omitted outcomes/null fields, source
bytes, runtime/code identity and qualification upgrades fail comparison. Use the
recorded reader sources/lock/runtime to reconstruct an older card; a changed
reader is not silently accepted. Byte-identical copies of the run can relocate
without changing a card, since external source-directory names/stat identities
are not part of the inventory. Later-mutated worktrees are not reread as past
results: existing archived-byte checks remain authoritative for these bounded
historical observations.

## Publication and limits

Card publication reuses private no-overwrite observer-record writing, fsync and
exact byte read-back. Source bindings are checked again after publication. The
card cannot live inside the input run, overwrite an existing output, or follow
the final output-parent symlink. A post-publication failure can leave a visible
unconfirmed/stale card; the tool reports failure and retains it rather than
deleting evidence or replaying subjects. Reconstruction will reject changed
sources. No power-loss durability or signature/authentication claim is made.

Limits: **4096 input files**, **128 MiB per blob**, **512 MiB aggregate source
bytes**, **4 MiB per card**. Existing stricter plan/sample/resource/abort bounds
remain in force. Over-budget cards/bundles fail; no entry is truncated or dropped
to make the report fit. Safe POSIX access is required; FIFOs, symlinks and
unexpected nested directories fail without being read as ordinary evidence.
All generation/reconstruction work is **offline observer cost outside subject
endpoints**. No claimed product latency is reduced by an estimated reporting tax.

Generator exits: **0** for a nonblocked exploratory card, **1** for a preserved
blocked card, **2** for invalid evidence/configuration/publication. Inspector
exit **0** means consistent reconstruction, including consistent failures;
invalid cards exit **2**. These are not test-success or qualified-support exits.
Card commands/paths/hashes and retained reports may reveal sensitive data;
review before sharing. Raw results/cards are not committed as benchmarks.

## Verification and retained development failures

Run from the repository root with unchanged pins:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_result_card.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

The expanded targeted **32-method** run passed (`17.754s`, `OK`); the subsequent
full suite also covers the added missing-generator-dependency control. The tests
exercise all three endpoints, failed/skipped/aborted and uncertain invocations,
capability asymmetry, resource-stage costs, diagnostic publication recovery,
deterministic bootstrap/copy reconstruction, false qualification/zero peaks,
edited statistics/bindings/order, nonregular/oversize inputs, source changes and
publication faults. Synthetic counter/fingerprint mutations are explicitly
format controls, not native peak or PT qualification.

- **355 full locked harness tests ran: 354 passed and one existing native-peak
  capability test was skipped** (`Ran 355 tests in 110.153s`, `OK (skipped=1)`).
  This includes **33 new result-card test methods**.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.343s`, `OK`).
- `git diff --check` and **66 edited-document local links** passed. All **4**
  changed/new Python files parse with Python 3.10 grammar, not Python 3.10 runtime
  qualification. Existing schemas/template and dependency, lock, toolchain and
  support pins are unchanged.

Retained development failure: the first **29-method** targeted run had **26
import errors** because the isolated test fixture restored its temporary import
path before loading the paired lifecycle/resource modules. Explicitly loading
those modules during fixture import fixes the setup without changing production
lazy imports. The next 29-method run passed; the later expanded run above passed.
No failed observation was excluded or turned into favorable benchmark evidence.

Direct CLI reporting evidence is retained outside the repository at
`/tmp/opencode/pt-result-card-evidence-8smkkbq5` (functional checks only):

| Source case, two planned blocks | Card / inspector exits | Planned / known attempts / not invoked | Retained outcome coverage |
|---|---|---|---|
| Guarded lifecycle | 0 / 0 | 4 / 4 / 0 | Four exited-unqualified observations; exploratory bootstrap only |
| Lifecycle finalization abort | 1 / 0 | 4 / 1 / 3 | Failed finalization and three not-run arms |
| Legacy failed preparation | 1 / 0 | 4 / 2 / 2 | Two not-run and two exited-unqualified arms |
| Strict resource capability refusal | 1 / 0 | 4 / 0 / 4 | Four unsupported observations |
| Explicit partial resources | 1 / 0 | 4 / 4 / 0 | Four partial observations, all native peaks null |
| Asymmetric parent capability | 1 / 0 | 4 / 2 / 2 | Two unsupported plus two partial observations |
| Detached worker | 1 / 0 | 4 / 1 / 3 | One failed resource unit plus three not-run arms |
| Unreleased declared marker | 1 / 0 | 4 / 1 / 3 | Failed finalization despite matching guard, plus three not-run arms |

Every card retains all four planned arms, exploratory classification, false
confirmatory eligibility and all **21** unresolved fields. Every source bundle
remains byte-identical after reporting. Resource cases reuse copied native
diagnostics retained by the earlier batch; no resource subject was rerun to make
a card or relabelled as a timing sample. Five malformed cards (qualification
upgrade, removed not-run arm, invented zero peak, omitted unknown generation
field and changed evidence digest) each make inspection exit **2**, without
traceback. These observations are not a conformance or performance campaign.

## Remaining gates

This implements the focused evidence-bound exploratory result-card deliverable,
**not WP01 acceptance**. Managed request/edit/session replay, full semantic
manifest/qualification attachment, work/generation validity, native peak
qualification, real resource budgets, observer overhead, corpus governance and
independent review remain open. Missing `memory.peak` gates native peak
qualification only; reporting/replay/oracle implementation can continue.
WP02/WP03, WP04 completion and backend/qualification/release dependencies remain
in the [prerequisite register](wp01-status.md). Rust/bridge, qualified corpus
materializations, real PT conformance and performance campaigns were not rerun.
