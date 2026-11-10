# Bounded real-pytest reference oracle

This is **test-only WP03 development infrastructure**, independent of the product
bridge. It runs real pytest in fresh processes; it is not a pytest replacement,
production protocol, qualified backend, universal semantic proof or a timing score.
WP01/WP02 acceptance and broader WP03 qualification remain open. Nothing here
enables `pt run`, a plugin adapter, an optimization or a release claim.

## Reproduction and retained evidence

Use the existing locked development environment; no new dependency is added:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -W error::ResourceWarning -m unittest discover -s tests/conformance -v
```

To retain the actual fresh-pytest traces, control projects, stdout/stderr,
process statuses, malformed copies, coverage databases and per-test outcomes,
provide a **new** output directory under an existing parent, outside this repo:

```sh
directory="$(mktemp -d /tmp/opencode/pt-oracle.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python tests/conformance/check_oracle.py --output "$directory/run" --execute
```

The driver first copies/hashes the conformance sources, the serial-core corpus
and the independent outer observer's Python sources/lock into a private `frozen`
tree. It executes that copy, not an evolving test tree. All test methods and
subtest outcomes remain in `checks.json`; skipped, failed, not-run and lost-return
units are not promoted to passes. The outer observer retains bounded raw output
and its process observation. Complete-looking child files cannot recover a lost
observer return. Original/frozen source bytes must still match after execution.
Existing outputs are never overwritten and work is never automatically retried.
The frozen inputs also include the separate Flask assessment/phase-plan tools
and their requirements, so their synthetic failure controls run from recorded
source rather than an external mutable checkout.

This is an explicit correctness experiment: it creates only private files and
subprocesses, installs nothing, disables no pytest plugins and changes no global
cache or system policy. The environment is deliberately minimal (private HOME /
TMPDIR, C.UTF-8, no inherited pytest/Python options); the explicit test observer
path is recorded. It is **not PT's production environment policy**. The pinned
reader/runtime is Linux x86-64, GIL-enabled CPython **3.12.12**, pytest **8.4.2**;
coverage **7.17.2** and jsonschema **4.25.1** are existing test dependencies.

The copied tree is not a kernel-enforced immutable snapshot. Ancestors are
caller-owned, tests run with the caller's authority, and source end checks cannot
prove no transient edit occurred. Complete interpreter/stdlib/environment identity,
artifact trust, external resources and production process containment remain
separate gates. All seven qualification fields stay null and confirmatory
eligibility stays false. Review raw diagnostics/paths before sharing; do not
commit generated results or environments.

## Same-session observation

`pt_reference_observer.py` is loaded explicitly with `-p pt_reference_observer`
and one `--pt-reference-trace=<new-private-file>` option. It has no pytest11 entry
point, custom run loop, selection policy, hidden preflight collection or replay.
It observes:

- The collected live item objects before ordinary selection hooks, assigning
  consecutive occurrence ordinals. Duplicate node IDs remain distinct.
- Exact final selected order and deselection partition from that same session.
- Collector outcomes/errors, separate setup/call/teardown reports, xfail/XPASS
  reasons, warnings and pytest's captured output sections.
- Actual protocol starts/finishes, internal errors, interruptions, stop reason,
  terminal report arithmetic and backend status. Ordinary collection failure's
  `Interrupted` is a backend event, not an observer failure.

Unknown report representations, added/replaced/repeated live item objects,
parallel/retry/subtest protocols, missing phases and overflowing traces cannot
silently become complete supported observations. Late unsupported conditions may
already have effects; retain them rather than retrying. A pre-inventory usage or
internal failure has no supported authoritative inventory and is rejected by
this finite trace reader, not reclassified as an empty passing session.

## Canonical trace and normalization

[`reference-event-v2.schema.json`](reference-event-v2.schema.json) specifies one
closed JSON object per UTF-8 line, with an explicit profile in the start event.
The original [version-1 schema](reference-event-v1.schema.json) is unchanged and
its 256-item traces remain readable. Mixed/unknown versions are rejected.
`trace_oracle.py` independently checks duplicate
JSON keys, finite numbers, strict integer/boolean types, schema/session/sequence,
clock monotonicity, identity partitions, serial ordering, applicable phases,
terminal counts and an externally observed process return. Schema acceptance
alone does not establish these relationships or producer honesty.

Limits fail closed: the default **`serial-core-v1` retains its 256-occurrence
ceiling**. The separately selected **`--pt-reference-profile=serial-repository-v1`**
permits at most **1024 occurrences**, not an automatically inferred larger limit
or truncated subset. Both retain **25,000 events, 128 KiB per event, 8 MiB per
trace and JSON depth 32**. A trace must end with a newline and terminal event.
Regular stable files only; linked/FIFO paths, partial writes and bound violations
are rejected. Larger projects need another reviewed profile, not silent truncation.

Compared exactly:

| Observable | Comparison |
|---|---|
| Request | Exact finite reference profile and pytest argv except the single observer trace destination; collect-only, maxfail and continue-on-collection-errors policy |
| Inventory | All exact node IDs/ordinals, final selection order and deselection membership |
| Execution | Starts, completed/incomplete/not-run occurrences; separate ordered phase/outcome/wasxfail records and stable failure messages |
| Diagnostics | Exact warnings, captured sections, backend error/interruption type/message, stop reason and process exit |
| External effects | Explicit bounded string-list sentinels, including presence versus absence |

Raw session UUIDs, PIDs, clocks, phase durations and full traceback diagnostics
remain retained but are not equality targets. Failure comparison uses pytest's
crash/skip/string message, **not full traceback equivalence**; custom unsupported
representations are rejected, not converted using arbitrary project `repr` calls.
Node IDs, user paths, reasons and captured output are never broadly stripped.
Test fault-plugin argv exclusions must be supplied exactly and are listed in the
comparison; ordinary comparisons exclude none. The CLI accepts externally supplied
exit integers; those alone are not authenticated process evidence. The real tests
feed actual subprocess returns and retain them separately.

Fail-fast retains unstarted selected work rather than dropping its denominator.
A real interrupt may retain a valid phase prefix and incomplete occurrence; it
cannot turn missing teardown into normal completion. Undocumented exits and
unexplained success/failure/no-tests statuses are rejected. Repeated references
that disagree are `baseline_uncertain`; the candidate is not qualified or scored.
Passing repetitions still do not prove determinism or statistical independence.

**Phase reports cannot prove that a test body or finalizer ran.** The independent
broken plugin deliberately replaces those operations while pytest can still
report matching passes. Import/fixture/loaded-value sentinels detect those faults,
extra preflight imports and stale timestamp bytecode. Effects not covered by a
declared sentinel remain unverified, even when traces match.

## Required artifacts and coverage controls

`artifact_oracle.py` reads actual declared bytes rather than a producer's
`verified` flag. It checks external size/hash expectations and required absences,
using no-follow relative file lookup. A leftover or dangling-symlink lease fails.
Limits: 256 paths, 8 MiB/file and 32 MiB total declared bytes. This is not an audit
of every output, an atomic snapshot, a disk quota or external-service cleanup.

`coverage_oracle.py` copies a bounded real coverage database before reading it
with the pinned coverage API. Only an explicitly supplied source root is mapped
between work copies; each declared source file's bytes must match. It compares
measured file identities, exact executed line/arc sets and per-line contexts, not
rounded percentages. Missing required files/contexts fail even if both arms omit
them. A separate test-owned runtime observation records effective tracer/version/
branch policy; requested configuration alone is insufficient.

The actual pytest coverage fixture runs a subprocess, saves separate parent/child
shards and performs the required merge. Controls omit subprocess measurement,
branch mode, child contexts or merge **without omitting the application work**.
Matching pytest reports and side effects cannot waive the resulting coverage
mismatch. These are WP03 oracle self-tests, **not WP15 pytest-cov, automatic
subprocess coverage, core fallback, plugin coexistence or production qualification**.
Source/generation/resource/finalization gates remain independent.

## Real-repository reference follow-up

The explicit [Flask phase-reference tool](../../bench/corpus/assessments/check_flask_phases_49943b5.py)
consumes the separately prepared [pinned two-environment Flask assessment](../../bench/corpus/assessments/flask-49943b5.md).
It performs no installation. Four predeclared fresh pytest sessions use the named
repository profile, with two repetitions in each environment. Each work copy is
archived by rename before recreating the **same literal cwd** from the source
archive, so reference diagnostics and arguments are comparable without stripping
user paths or erasing outputs. Unknown returns stop later work without retry.
The two within-environment comparisons retain mismatches as `baseline_uncertain`.
This is actual reference-phase evidence, not PT parity, external body-effect
verification, full environment identity, immutable generations or product timing.

See [WP03 evidence and open gates](../../docs/wp03-status.md) and the unchanged
[strict full-success contract](../../docs/contracts.md).
