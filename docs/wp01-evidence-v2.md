# WP01 version-2 evidence schemas and strict validation

Status: **focused format/consistency implementation; WP01 remains open**.
Date: **2026-11-09**. Base: `cbf6a0a`. This follows the
[paired lifecycle integration](wp01-paired-lifecycle.md); it does not implement
PT's backend, semantic oracle, resource accounting, qualified support or release.
`pt run` remains unavailable and **no test-runner speedup is established**.

## Explicit formats, not a silent legacy upgrade

All paths below are in [`bench/harness/`](../bench/harness/README.md):

| Record | Schema | Important variants |
|---|---|---|
| `schedule.json` | [`paired-plan-v2.schema.json`](../bench/harness/paired-plan-v2.schema.json) | Exact per-arm/per-stage commands, contracts, guards, schedule, timeout, capture configuration, incomplete host metadata and limitations |
| Invoked or skipped stage sample | [`sample-v2.schema.json`](../bench/harness/sample-v2.schema.json) | Invoked `exploratory` observations; separate `exploratory_unqualified` measurement records skipped after preparation/probe failure |
| Post-commit receipt | [`receipt-v2.schema.json`](../bench/harness/receipt-v2.schema.json) | Finalized-unqualified or failed lifecycle; a measurement failure can have null result/binding/observations; a publication failure can retain a result without a confirmed binding |
| `abort.json` | [`paired-abort-v2.schema.json`](../bench/harness/paired-abort-v2.schema.json) | Pre-return harness error without a receipt, or publication/finalization abort with a diagnostic receipt |

Shared definitions are in
[`lifecycle-v2.schema.json`](../bench/harness/lifecycle-v2.schema.json).
They include typed process/launch-error results, required clocks, canonical
contract shapes, guard verdicts, check variants, stat fingerprints, archive
references/errors and sample-byte bindings. Objects are closed: extension fields
are not silently accepted. Format evolution requires an explicit contract change.
The untouched [`sample.schema.json`](../bench/harness/sample.schema.json) remains
the legacy **version-1 paired command-only** schema; it is not the standalone
v1 lifecycle sample schema and is not repurposed for v2.

[`evidence.validate_v2()`](../bench/harness/evidence.py) uses the locked
JSON Schema implementation and a registry containing only the bundled URNs.
It never retrieves schema references over HTTP or from record-specified paths.
Integer fields require actual JSON integer tokens: `true`, `1.0` and `1e0` cannot
stand in for an integer, even though standard JSON Schema permits integral
floating-point values. Boolean fields cannot be replaced by zero/one. Timeout
is a finite positive number, not a string or boolean. Metadata observation errors
remain nullable, explicitly paired with missing metadata; incomplete metadata
never becomes host qualification.

Strict record decoding rejects duplicate keys, NaN/infinity, exponent overflow
such as `1e999`, non-object records and nesting beyond 64 levels. API validation
also rejects non-JSON/cyclic inputs. Existing byte bounds remain: 1 MiB plans and
samples, 4 MiB receipts/abort records, 128 MiB per declared artifact and 512 MiB
aggregate declared artifacts. Path/digest/reference bounds are not relaxed.

## Enforcement and semantic checks

- Plans validate before output creation or subject execution. Plans, skipped
  samples, receipts and aborts validate before observer publication.
- Invoked sample validation is **inside** the publication-inclusive interval.
  Receipt construction/schema validation and persistence remain post-endpoint
  observer bookkeeping. Any schema loading incurred inside a standalone API
  invocation is charged there; no estimated overhead is subtracted.
- Both inspectors validate v2 receipts and bound samples before accessing their
  nested fields. Paired inspection also validates plans, skipped samples and
  embedded abort receipts. Confirmed samples are checked against their exact
  bytes/digest; a visible but unconfirmed failed-publication fragment remains
  bounded diagnostic data, not an approved sample.
- Schema acceptance does not establish consistency across records. Seed/order,
  stage/arm/block/position, contract/guard, cwd, command, sample-name/digest/size,
  archive budgets/bytes, clock arithmetic/enclosure and serial order are still
  independently checked. Actual source identities or execution are not inferred.
- Both before/after finalization observations must have exactly the contract's
  ordered check references, consistent process/exit verdicts, byte/digest
  verdicts, fingerprint sizes and aggregate status—even when the lifecycle
  already failed. Changed observations and archival failures must agree with
  error evidence. Historical retained-byte reconstruction must agree with the
  initial observation; archive errors cannot name unobserved files.

Failed observations are not malformed merely because their process exited
nonzero, timed out, failed to launch, could not publish a sample or could not
finish cleanup. Explicitly expected nonzero outcomes remain possible and remain
unqualified. Skipped/aborted arms stay in the planned denominator. Consistent
aborts are inspectable but block every ratio, absolute comparison and bootstrap;
missing, corrupt or contradictory evidence is rejected, not excluded to improve
an estimate. Historical absence/stat claims are still unauthenticated observations,
not current-state or generation proof.

## Verification and retained development failures

Reproduce from the repository root, with the unchanged lock:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests -p test_evidence_v2.py -v
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s bench/harness/tests
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/contracts
```

On the selected Linux x86-64, GIL-enabled CPython 3.12.12 development host:

- **248 full locked harness tests passed** (`Ran 248 tests in 66.298s`, `OK`).
- **68 separate contract/audit tests passed** (`Ran 68 tests in 8.382s`, `OK`).
- `git diff --check` and **54 edited-document local links** passed. All **6**
  changed/new Python files parse with Python 3.10 grammar; this is not Python
  3.10 runtime qualification. The legacy schema and dependency/toolchain/support
  pins are unchanged.
- The **23 new evidence test methods** include recursive mutations of required
  and unknown fields at every observed object depth, integer/boolean/float
  ambiguity through schema references, malformed/null types, paths/digests,
  clocks, after-publication failure evidence, valid skipped/aborted observations,
  null failure receipts, raw-capture contradictions and legacy separation.
  Schema files and every bundled reference are checked offline. Subcases and
  synthetic record mutations are not independent benchmark or PT observations.
- The existing **20 paired lifecycle tests** also passed with validation enabled,
  including expected nonzero exits, bounded wrong bytes, publication/archive
  failures, timing holds, abort denominators and unchanged strict blob checks.
- Direct default-CLI bundles retained **4/4** receipts with released markers.
  Leaving a marker unreleased, despite exit zero and a matching stdout guard,
  retained **1/4** measured receipts plus **3** not-run arms. Inspection accepted
  the accounted abort; analysis blocked ratios/absolute comparisons/bootstrap.
  Three copied malformed bundles (unknown host field, boolean byte count,
  missing receipt errors) each made inspection and summary exit **2**, with a
  schema diagnostic and no traceback. All observations remain unqualified.
  Local functional evidence is retained at
  `/tmp/opencode/pt-v2-schema-evidence-7jdabinh`, not committed as a benchmark.

Retained failures: the first new targeted **23-test** run reported **23 setup
errors** because the fixture removed its temporary import path before loading
the optional `raw_capture` module. Loading that module during fixture import
fixes the test setup without changing production import semantics. The next run
had **one failure**: a deep JSON object did not necessarily trigger the Python
decoder's recursion exception. An explicit 64-level traversal check now enforces
the record bound independently of the decoder's recursion limit. The subsequent
targeted run passed all 23 methods; the full locked runs above include the fix.
No failure was deleted, retried into benchmark evidence or treated as an exclusion.

## Remaining gates

This completes the focused v2 structural-validation gap, **not WP01 acceptance**.
Complete semantic manifests/evidence/result cards, scenario/request/replay
endpoints, work/generation/non-file resource validation, whole-boundary CPU/memory,
broader broken-runner controls, overhead characterization and campaign governance
remain open. WP02 corpus pins/materializations/partitions, WP03's real oracle,
WP04 completion and the backend/qualification/release dependencies are unchanged
in the [prerequisite register](wp01-status.md).

Rust/bridge, corpus materializations, PT conformance and performance campaigns
were not rerun or qualified. No dependency, lock, toolchain or support pins changed.

The subsequent [resource-accounting follow-up](wp01-resources.md) adds a separate
diagnostic resource record type, not new fields in these closed v2 formats. Its
native peak path is still unqualified on this development host and does not close
the resource/campaign acceptance gaps above.
