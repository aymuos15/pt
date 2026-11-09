# Capability policy — conservative baseline

Status: adopted in the 2026-11-09 WP00 engineering self-review. This expands
specification section 6; it does not implement a policy engine, authorize any
transformation or imply that an adapter exists. See `wp00-review.md`.

Each decision records a capability name, `allow`, `deny`, or `unknown`, scope,
issuer and version, evidence digest, bounded input domain, reason, and expiry or
invalidation conditions. Policy composes conservatively: every relevant project,
plugin, fixture, backend, and resource constraint must permit the transformation.
Unknown or conflicting evidence disables that transformation, never the plugin.
Project declarations are assertions with an explicit trust level, not proof.

| Capability | Permission sought | Reference contract and conservative default |
|---|---|---|
| `collection.metadata_reuse` | Reuse a validated inventory as metadata for a bounded input domain. | Same-session pytest collection remains authoritative; no skipping collection based solely on metadata. |
| `collection.runtime_reconstruction` | Reconstruct usable runtime collection state from persisted preparation. | Fresh real-pytest session and collection; a serialized plan alone cannot recreate Python objects. |
| `execution.partition` | Split work into authorized execution sessions or workers. | Serial same-session pytest; parallel work requires a separately named pinned parallel contract. |
| `execution.reorder` | Change order within the scope expressly allowed by the contract. | Preserve the chosen backend's ordering. |
| `execution.fork_framework_seed` | Create disposable children from an audited framework-only Python seed. | Fresh process without preloading; no test-executing child becomes a seed. |
| `execution.fork_project_snapshot` | Fork from an explicitly bounded project state snapshot. | Disabled research capability; fresh real-pytest execution. |
| `fixtures.replicate_scope` | Replicate a fixture's instances across authorized sessions. | Preserve the chosen backend's fixture lifetime and multiplicity. |
| `resources.reuse_service` | Reuse a managed external service under a declared lease/reset contract. | No cross-run service reuse; never cache or share Python fixture instances. |
| `selection.declared_inputs_complete` | Select based on an explicitly bounded declared-input dependency contract. | Full requested scope when dependency evidence is missing or broad inputs are unknown. Affected results remain partial. |

The evidence must be tied to relevant versions and identities. Plugin upgrades,
changed policy, changed declared inputs, expired evidence, and scope mismatch
invalidate applicable decisions. Missing inputs prevent authoritative reuse.
There is no general inference of safety from the absence of observed hooks or
file reads.

A user may request an optimization as **preferred** or **required**. When it is
denied or unknown, preferred uses the conservative path and records why; required
fails before affected work starts. If new information arises after effects begin,
stop or continue conservatively in the same session as appropriate, retain the
original attempt, and never transparently replay started work. If the necessary
safe transition cannot be established, report failure instead of guessing.

## Review resolutions

The initial serial encoding is **session scope, deny/unknown only**, bound to the
request/run/generation/session and resolved environment. Every declared feature
request must receive a decision/reason; a required unavailable feature is a
prelaunch configuration/unsupported failure, while preferred retains the serial
reference. Omitted or malformed evidence is unknown, never an implicit allow.
The protocol schema is data validation, not provenance authentication.

Coordinator policy decisions must come from coordinator-owned policy, not a
bridge/project field that claims that role. Project assertions are labelled as
assertions; neither an issuer string nor a digest makes them trusted. For the
baseline, no project assertion, user configuration, environment variable, cached
plan or plugin-supplied record can turn an unavailable transformation on.

Future nested-scope composition is all-applicable-permissions, with deny/conflict
or unknown at any relevant scope overriding an allow. A narrower assertion does
not erase a session/global constraint. Identity/plugin/policy/input changes,
expiry or loss of provenance invalidate evidence; absence of known invalidation
is not new positive evidence. Before any implementation accepts `allow`, WP07
must define/version its trusted issuer registry, scope/evidence binding and
invalidation checks and test conflicting/expired/forged evidence. The enabling
feature also needs its own oracle and measurement gate. This is a deferred
enablement prerequisite, not an unresolved permission to optimize the baseline.

The same decision/reason must be available in structured results and user-facing
explanations (WP07/WP09). A requested explanation or unknown plugin never causes
an extra project import, dependency install, plugin disablement or replay. Those
production behaviors and explanation commands remain unimplemented.
