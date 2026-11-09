# WP01 campaign declaration consistency and strict YAML input

Status: **bounded input/declaration checks implemented; WP01 remains open**.
Date: **2026-11-09**. Base: `9e29e20`. This follows the
[paired resource integration](wp01-paired-resources.md); it does not qualify a
benchmark manifest, PT runner, semantic oracle or release. `pt run` remains
unavailable and no test-runner speedup is established.

## Structure is not a consistent or verified experiment

[`manifest.py`](../bench/harness/manifest.py) still uses the unchanged
[`benchmark-campaign.schema.json`](../bench/benchmark-campaign.schema.json).
Its output distinguishes `structure: valid` from `declaration_consistency` and
lists deterministic `declaration_conflicts` by code and affected fields. It
implements only direct contradictions from the specification's contracts:

| Declared combination | Reported conflict |
|---|---|
| Equal-work family with affected scope | An affected-selection workflow cannot be relabelled as equal-work execution; matched explicit-selection comparisons remain possible |
| Equal-work family, two non-null but different interpreter digests | Matched interpreter/build is required for the controlled comparison |
| `serial-pytest-v1` with workers other than one | The named serial contract cannot imply parallel semantics |
| Prepared-session amortization without a complete replay or complete-session endpoint | A best single invocation cannot stand in for complete amortized cost |
| Complete-session endpoint with an invocation-only sample unit | Declared endpoint and resource/analysis unit disagree |
| Non-cluster resampling unit different from the declared independent analysis unit | Resampling cannot silently relabel independent blocks as sessions, or vice versa |

Unknown contract IDs remain explicitly unrecognized for these contract checks;
their semantics are **not** invented from a worker count. Higher-level-cluster
resampling is a declaration, not proof that clusters or enough independent
sessions exist. Matching interpreter declarations, explicit-selection scopes
and corrected replay units likewise do not establish real equal work or valid
cost accounting. No selectors, arbitrary command bodies or reset scripts are
executed or interpreted to infer those claims.

The checker always retains `confirmatory_eligible: false` and explicitly lists
unverified provenance/artifact semantics, source/environment identities, actual
work/generation validity, reset/resource equivalence, corpus/independence and
freeze/review requirements. Even a structurally frozen, internally consistent
manifest is not qualified. The original template remains a draft with unresolved
pins. No template, schema, dependency, toolchain or support pin changes here.

## Strict and bounded input policy

- Reuse the existing safe relative-file reader: require a bounded regular file
  of at most **1 MiB**, reject final symlinks/FIFOs/directories, and check the
  file/name fingerprint and bytes through the read. Safe POSIX lookup is
  required; unsupported access fails rather than falling back. Caller-owned
  ancestor paths are not a hostile-directory boundary or an atomic snapshot.
- Preserve duplicate-key and YAML-alias rejection. Enforce the **64-level**
  nesting bound during composition as well as subsequent JSON-type validation;
  do not rely on the Python decoder's recursion exception.
- Require JSON-compatible typed YAML values. Dates, sets, binary objects,
  nonfinite/overflowed floats and arbitrary Python objects cannot become evidence.
  Integer fields reject booleans and integral floating-point values. Finite
  floating-point numbers remain valid for numeric fields such as CPU budgets.
- The historical schema's untyped integer/boolean constants also enforce their
  expected types: `schema_version: true`/`1.0` and numeric substitutes for boolean
  publication gates are rejected. Ordinary JSON Schema equality alone is not
  this stricter validator policy.
- Pin/revision declarations require a full lowercase-hex match; a trailing
  newline cannot exploit a regular-expression end anchor. Commands/cwds cannot
  contain NUL. Schema diagnostics report field and violated rule without echoing
  rejected command or pin values.

Loading is read-only and never changes manifest bytes/status, resolves commands,
downloads artifacts or invokes project code. `load_structural_manifest()`
retains its structural-loader API for the separate digest checker. That tool
still checks listed bytes only; a matching-digests exit is not a substitute for
this declaration report or actual artifact/content qualification.

## Reproduction and observed controls

From the repository root, with the unchanged lock:

```sh
uv run --locked --project bench/harness --python 3.12.12 python bench/harness/manifest.py bench/benchmark-campaign.template.yaml
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_manifest.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

CLI exit **0** means no known declaration contradiction, **1** means structurally
valid but conflicting declarations, and **2** means malformed/unsupported input.
None is an eligible benchmark or test-pass result.

The **22 targeted manifest tests passed**, including **15 new methods** covering
type/constant ambiguity, malformed pins/commands, non-JSON and deeply nested
YAML, unsafe input files, scope/contract/unit conflicts, valid corrections,
unknown-contract limitations, deterministic replay of the checker and unchanged
manifest bytes. A frozen-looking file with fake hashes still cannot qualify.

- **322 full locked harness tests ran: 321 passed and one native-peak capability
  check was skipped** (`Ran 322 tests in 97.418s`, `OK (skipped=1)`).
- **68 contract/audit tests passed** (`Ran 68 tests in 9.057s`, `OK`).
- `git diff --check` and **59 edited-document local links** passed; both changed
  Python files parse with Python 3.10 grammar, not runtime qualification. All
  existing schemas/template and dependency, lock, toolchain and support pins are
  unchanged.

Direct functional CLI evidence is retained outside the repository at
`/tmp/opencode/pt-manifest-declarations-ene74xg6`:

- The unchanged draft declarations return **0**, with unresolved frozen-schema
  fields and false confirmatory eligibility.
- Five conflicting copies (affected-as-equal-work, parallel-as-serial, changed
  resampling unit, different interpreter pins and single-run amortization) each
  return **1**, retaining their field-specific conflict codes.
- Boolean schema version and floating-point paired-block count each return
  **2**, with no traceback.
- Every input remains byte-identical. A deliberately executable command marker
  is absent: none of these checks executes the declared subject.

These are input/format controls, not conformance or benchmark observations. No
failure was excluded or retried into favorable evidence.

## Remaining prerequisites

This narrows the campaign-input gap; it does not complete semantic manifests,
artifact provenance, frozen-campaign production, result cards, managed replay,
native peak qualification, resource budgets, observer-overhead evidence or
independent review. The WP02 corpus/partition/materialization, WP03 real oracle,
WP04 completion and backend/qualification/release dependencies remain open in
the [prerequisite register](wp01-status.md). Rust/bridge, qualified corpus
materializations, real PT conformance and performance campaigns were not rerun.
