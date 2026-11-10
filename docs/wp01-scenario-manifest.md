# WP01 campaign-manifest to scenario evidence binding

Status: **bounded offline association implemented; WP01 acceptance remains open**.
Date: **2026-11-10**. Base: `c2ffd37`. The existing
[manifest checker](wp01-manifest-checks.md) checks declarations, while
[paired scenario campaigns](wp01-paired-scenarios.md) retain actual declared-file
reset/edit/input observations. This batch binds the two without changing their
formats, rerunning subjects or upgrading missing qualification.

## Bind bytes and observations, not an invented qualified benchmark

[`scenario_manifest.py`](../bench/harness/scenario_manifest.py) uses the distinct
closed [`scenario-manifest-v1.schema.json`](../bench/harness/scenario-manifest-v1.schema.json).
The kind is `campaign_manifest_scenario_evidence_binding`, with classification
`exploratory`, measurement layer `scenario_validation` and the existing whole
scenario unit. **Status is always `blocked`, confirmatory eligibility always false.**

The original [campaign manifest schema](../bench/benchmark-campaign.schema.json)
and [draft template](../bench/benchmark-campaign.template.yaml) are unchanged.
Binding preserves the full parsed declaration, including every null pin, plus
exact original file bytes/size/SHA-256. YAML comments and spelling changes remain
byte changes even when the parsed declaration is identical. Strict existing
bounded YAML/type/constant/duplicate/alias checks are reused. Original declaration
conflicts and missing frozen-schema fields remain visible. A file labelled
`frozen` with plausible hashes is not proof of preregistration or verified artifacts.

The report also binds the entire paired plan, schedule, input inventory, actual
abort, all session/request/reset/input projections and publication flags, complete
session/request/phase/file-effect denominators, and a recursive inventory of **all**
retained campaign files/directories. Shared `payloads/`, unit `blobs/`, diagnostic
fragments and known-not-run rows are included. Full transition/request/shutdown
ledgers remain in their bound raw units; no successful subset is selected.
The redundant standalone summary inside each paired row is not copied; all
outcome/certainty counts and actual reset/input projections are retained.

A domain-separated reconstruction digest binds manifest bytes, recursive evidence,
the exact reader/schema source inventory, generator runtime and association policy.
An inspector reconstructs the entire report from those sources; matching or
recomputed hashes alone cannot authorize edited verdicts, counts or observations.
The before/after evidence, manifest and reader fingerprints must remain unchanged,
without automatic retry. Exact evidence/manifest bytes can relocate; names and
later worktree contents do not replace their historical meaning.

## Bounded field relations

The report distinguishes `matched_declaration`, `conflicting_declaration`,
`unresolved_manifest_declaration`, `unknown_evidence_declaration` and
`not_observed_by_profile`. None is a semantic qualification.

| Manifest field | Bounded relation to the paired scenario |
|---|---|
| `scenario.id` | Exact S0–S9 declaration for each arm; a human-readable campaign label is not silently guessed/mapped |
| All eight `scenario.cache_state` axes | Exact declared values; a scenario's explicit `unknown` stays unknown even if the manifest claims a warm/cold state |
| `experiment.paired_blocks`, `random_seed` | Exact full planned schedule count and order seed, never the successful/returned subset |
| `experiment.sample_unit` | `complete_session_replay` associates whole-session **scope only**; `complete_invocation` conflicts; independence and the actual shipping endpoint remain unverified |
| Per-arm `cwd` | Exact frozen arm declaration; null remains unresolved; no current worktree is opened |
| Per-arm `argv` | The single manifest argv must match **every request** in that arm; a heterogeneous sequence cannot be represented by choosing only its first/best request |
| `scenario.expected_exit_code` | Compared with every request's declared expected exit, not inferred from a passing count or shutdown's mandatory zero |
| `experiment.timeout_seconds` | Compared only with each declared non-shutdown execution dispatch budget; not proof of a hard wall limit or the reserved shutdown budget |

The original v1 manifest cannot express the complete per-request argv, guarded
edit/input/reset chain, request/shutdown budgets or distinct expected exits of a
general scenario. Those exact declarations remain in the bound paired plan, not
fabricated inside v1. Null argv/budget fields remain unresolved; differing request
commands/exits remain conflicts. An association is still published with its full
conflict and outcome ledger, rather than pruning the incompatible requests.

Original manifest claim/scope/contract, repository/source/environment/binary pins,
worker count, artifact/coverage/output expectations, generation assurance,
snapshot cost, CPU/memory budgets, warming/exclusion/pilot/time-window policies,
analysis/bootstrap settings and publication/preregistration assertions remain
unverified. They are not silently applied to or proven by the scenario. In
particular, no hash of built-in file effects is mislabelled as an executed arbitrary
`reset_script_sha256`, `state_probe_sha256` or reset-policy document.

Fourteen qualification fields are required **null**. They retain all six scenario
unknowns (complete input domain, actual loaded code, semantic equal work, reset
equivalence, generation validity, independent units) and add manifest preregistration,
artifact provenance, source/environment identities, resource-budget equivalence,
corpus eligibility, coverage equivalence, time-window adequacy and independent
review. All latency/ratio/bootstrap/resource statistics are null. Matching
declarations, plausible fully populated pins and expected nonzero process exits
never imply passing tests, independent units or release-confirmatory evidence.

## Offline failure accounting and publication

No subject command, reset, edit, artifact-producing script, controller query,
environment preparation or dependency mutation is performed. The association is
post hoc and cannot establish that the manifest preceded execution. It is outside
every subject endpoint; no cost is subtracted from previous observations.

Failed/unsupported/unknown/not-run outcomes remain complete. A partial file effect
keeps its unknown return even when post-state bytes are known. A whole scenario
API return lost after a complete-looking unit leaves reset/input observations
null and effects `unknown_unobserved`; the diagnostic inventory is bound, never
reconstructed as returned success. Paired publication uncertainty retains actual
returned observations with false commit flags and the original abort. Missing,
corrupt, inconsistent or unexplained evidence fails inspection, not a smaller report.

`bind` publishes one private no-overwrite JSON file **outside** the source campaign.
Existing paths are never overwritten; omission, conflicting bytes or an error
after publication cannot be reported as a confirmed publisher return. `inspect`
checks historical consistency only, not proof that any earlier publisher returned.
Limits are **1 MiB original YAML**, **4 MiB complete binding**, and all existing
paired/standalone evidence limits. Oversize fails rather than trimming declarations
or outcomes. These are accepted-evidence bounds, not disk quotas.

Evidence and source hashes are not authentication, artifact provenance or a hostile
directory boundary. Caller-owned ancestors and trusted local storage remain required;
fingerprints are not atomic snapshots. No power-loss durability, guaranteed cleanup
under host/SIGKILL/storage loss or sandboxing of subject commands is claimed.
Manifests, argv, inputs, paths and reports may contain secrets: retain privately,
review before sharing and do not commit raw bindings/campaigns.

CLI `bind` exits **0** for no known declaration conflict, **1** for a retained
conflicting association and **2** for malformed input/evidence or unconfirmed
publication. Exit 0 can retain an aborted campaign or unresolved declarations;
it is not a successful benchmark or test run. `inspect` exits **0** for a report
matching full source reconstruction (including conflicts/aborts), otherwise **2**.
There is no bootstrap, arbitrary field map, unknown-field bypass or execution mode.
Existing result-card tools continue refusing scenario campaigns.

## Reproduction from a retained paired campaign

First run the disposable example in [paired scenario reproduction](wp01-paired-scenarios.md#reproduce-with-disposable-file-worktrees),
which leaves `$directory/run` and its two arm plans. Then, in the same shell from
the repository root, create a **local demonstration draft** without changing the
repository template or any source evidence:

```sh
uv run --locked --project bench/harness --python 3.12.12 python - "$directory" <<'PY'
import json, sys, yaml
from pathlib import Path
root = Path(sys.argv[1])
plan = json.loads((root / "run/schedule.json").read_text())
data = yaml.safe_load(Path("bench/benchmark-campaign.template.yaml").read_text())
data["scenario"]["id"] = plan["sessions"]["baseline"]["scenario"]["id"]
data["experiment"].update(paired_blocks=len(plan["schedule"]), random_seed=plan["seed"],
                          sample_unit="complete_session_replay", analysis_unit="independent_paired_session",
                          timeout_seconds=plan["sessions"]["baseline"]["execution_timeout_seconds"])
data["analysis"]["resampling_unit"] = "independent_paired_session"
for arm in ("baseline", "candidate"):
    data[arm]["cwd"] = plan["sessions"][arm]["cwd"]
    data[arm]["argv"] = plan["sessions"][arm]["requests"][0]["command"]["argv"]
(root / "campaign.yaml").write_text(yaml.safe_dump(data))
PY
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/scenario_manifest.py bind --manifest "$directory/campaign.yaml" --run "$directory/run" --output "$directory/manifest-binding.json"
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/scenario_manifest.py inspect --manifest "$directory/campaign.yaml" --run "$directory/run" --binding "$directory/manifest-binding.json"
```

This local draft is explicitly created **after** a test-owned scenario, not a
preregistered experiment. The linked example has one request per arm; for a
heterogeneous multi-request sequence the single argv may conflict, and all
requests still remain. Unknown cache axes and all qualification nulls stay visible.
Neither command reexecutes or repairs the source campaign.

## Verification and remaining gates

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_scenario_manifest.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

Initial API smoke bound the unchanged draft template to an existing complete
four-session campaign: its five mismatching declarations, sixteen unknown cache
axis checks and eight unresolved argv/cwd/budget checks remained visible; all
four sessions and fourteen qualification nulls survived read-only reconstruction.
Evidence: `/tmp/opencode/pt-scenario-manifest-smoke-zfzje_hw`.

- **32 targeted tests passed** (`Ran 32 tests in 95.436s`, `OK`), with
  ResourceWarning treated as an error. Controls cover per-request argv/exit
  contradictions, exact/missing/unknown manifest relations, fake frozen pins,
  failure/unsupported/partial/lost-return ledgers, publication uncertainty,
  relocation, source mutation, strict schema/types/YAML, size bounds and forged
  observations/counts/checks/qualification. No fixture test class is imported into
  discovery globals to rerun its existing methods.
- **708 full locked harness tests ran: 707 passed and one existing native-peak
  capability test was skipped** (`Ran 708 tests in 857.796s`, `OK (skipped=1)`).
  This includes all **32 new binding controls**; the capability skip is not native
  peak support qualification.
- **68 contract/audit tests passed** (`Ran 68 tests in 8.423s`, `OK`).
- `git diff --check` and **123 edited-document local links** passed. Both new
  Python files parse with Python 3.10 grammar (not runtime qualification).
  The original manifest/schema/template, paired/scenario/readers, existing
  schemas and dependency/lock/toolchain/support pins are unchanged.
- The documentation block was executed against a byte-identical relocated copy
  of the preceding disposable scenario example, with **no subject rerun**. It
  retained **4 sessions, 4 requests, 16 phases, 16 file effects**, all fourteen
  null qualifications, unresolved draft pins/cache observations and blocked
  qualification. Both CLI calls exited **0** for consistent unqualified association.
  Evidence: `/tmp/opencode/pt-scenario-manifest-doc-smoke-oyn6r32r`.
- Five prior paired scenario summaries reconstructed unchanged (complete, partial
  reset, lost whole return after commit, unconfirmed paired publication and
  unsupported OS-cold), preserving their original outcomes and qualification
  nulls. No source or historical report was rewritten and no subjects were rerun.

Direct offline CLI/API controls are retained at
`/tmp/opencode/pt-scenario-manifest-evidence-qiv71abc`, produced by
`/tmp/opencode/build-scenario-manifest-evidence.py`:

- **22 associations over 17 previously retained campaigns**, not 22 new or
  independent observations. Seventeen source associations preserve complete,
  failed, expected-nonzero, deadline, unsupported, partial reset/edit, inner/whole
  lost-return, unconfirmed publication and pre-call binding-failure outcomes.
  Five declaration variants cover a wrong planned count, wrong scenario ID,
  first-command-only association, original scope conflict and fake frozen pins.
- Each association retains the full **4 sessions / 8 requests / 24 phases /
  48 file effects**. Six producer CLI calls exit **1** for explicit declaration
  conflicts; sixteen exit **0** for no known conflict, including aborted/unknown
  evidence. All twenty-two inspect with **0** as consistent historical bindings,
  retain blocked qualification and fourteen null fields, and reconstruct identically
  through the API without changing manifest or source evidence fingerprints.
  These exits are not test-pass or benchmark-eligibility decisions.
- Whole-session return loss after commit still retains **two unknown requests
  and twelve `unknown_unobserved` effects**, with null reset/input observations.
  Partial file return loss keeps one unknown effect, and unconfirmed paired
  publication keeps actual returned observations with false commit flags.
- **22 forged reports** each inspect with **2**, without traceback. Controls
  remove/reorder/duplicate sessions, omit requests/resets/checks/payload inventory,
  shrink denominators, invent matched checks/resolved pins/frozen readiness,
  change runtime/reader inventory, promote qualification/eligibility/latency,
  relabel the kind, recover missing-return reset/request observations, hide
  publication uncertainty or erase original declaration conflicts. Reconstruction
  digests were recomputed, not left trivially stale.
- **Six malformed source campaigns** (omitted reset/shutdown, wrong pre-request
  bytes, corrupt frozen payload, work after abort and changed lost-return
  diagnostics) each make `bind` exit **2** without publishing a report. No failed
  source is repaired or rerun. A declared executable marker remains absent:
  association compares its argv and never executes it.

This closes bounded **manifest-to-scenario association** only. Shipping endpoint
and resource integration, complete executable manifest semantics, runtime/artifact/
source identity, semantic work/generation validation, service/cache/reset qualification,
resource budgets, overhead evidence, corpus eligibility/materialization/partitions,
independent units and preregistration/review remain open. WP01 acceptance, WP02–WP04
completion, WP03's oracle, WP05's real pytest backend and release gates remain in
the [prerequisite register](wp01-status.md). No Serc integration, optimization,
dependency/pin change, bridge build, native peak or platform qualification is claimed.
The existing manifest, paired-scenario and result-card formats/readers are unchanged;
historical evidence is not rewritten to fit this new report.
