# WP09 core protocol/reporting progress

Status: **partial development foundation; WP09/M1 acceptance remain open**.
This does not implement a complete coordinator result, secure store, qualified
launcher, backend, generation assurance or successful `pt run`.

## Existing component evidence

- [Native bounded bridge reader and serial ledger](../crates/pt-protocol/README.md):
  18 bridge payloads, actual EOF provenance, typed same-session necessary accounting
  and no full-success API. Base `d17fc99` passed 79 locked release Rust methods and
  2,372 independent schema/wire-shape adversaries. These are not all coordinator
  event/catalog/final-result requirements.
- [Explicit real-pytest observer](wp05-status.md): base `78ef9f9` has actual native /
  plain/reference/bridge tests, with 85 Rust checks and the corrected 56-check /
  76-request integration run. Rich artifact/report/coverage semantics remain
  explicitly separate, not inferred from matching phase counts or JUnit.

## Verified artifact component checks (base 78ef9f9)

The new [`pt-report`](../crates/pt-report/README.md) component pins native directory
and file identities, rejects unsafe traversal/links/types/ownership, independently
copies/hashes/rereads declared bytes, and publishes privately without replacement
only after actual writer reaping/cleanup evidence. Bounds and one absolute
lifetime deadline fail visibly. No source repair, arbitrary overwrite/delete,
started-work replay or stale-root recovery exists.

Crucially, readiness/hash agreement alone cannot establish required completeness.
An independent coordinator exact-byte contract is the only completeness policy
implemented here; unknown variable reports can be retained as content but stay
**ineligible for required-complete status**. Generic JUnit/coverage/exception
format and semantic adapters, actual coordinator request/process association,
complete environments and immutable generations remain open. This component
cannot certify any full test result.

The selected digest dependency is explicitly pinned `sha2 0.11.1` with default
features disabled and its lock/checksums retained. The existing nix 0.30.1 gains
filesystem/user features, not a version substitution. Final dependency identity
and native verification records follow actual returns, not estimates.

Development failures are retained: the first fixture pass created directories /
files using the inherited group-writable umask, so the product correctly rejected
12 purported positive controls at the private-parent guard (four other controls
passed). The fixture now explicitly creates **its own new** private entries; the
guard was not relaxed and no user output/cache was repaired. A subsequent helper
compile failed because its private `fs` wrapper omitted `hard_link`; that import
was corrected before those new controls could execute. These are setup corrections,
not eliminated benchmark samples or automatic project-test retries.

The final retained locked release workspace run passed **104 tests**, no skips:
the prior 85 plus **18 artifact controls and one real pytest/JUnit/hash case**.
Clippy `-D warnings` and rustfmt passed. Sources stayed fixed; actual command
returns and full stdout/stderr are retained at
`/tmp/opencode/pt-artifact-final-verification-mvv4nrep`. The real JUnit scenario
retains the actual pytest assertion-failure exit **1**, fixture cleanup and exact
published bytes; independent stdlib XML/hash inspection does not silently become
a production generic-completeness adapter. Unknown required completeness stays
blocked despite a true ready claim.

All **38 prior Cargo package identities/checksums** remain unchanged. The new
local crate adds exactly seven registry identities: sha2 **0.11.1**, digest
**0.11.3**, block-buffer **0.12.1**, crypto-common **0.2.2**, cpufeatures **0.3.1**,
hybrid-array **0.4.15** and typenum **1.20.1**. Every cached `.crate` archive's
independently rehashed SHA-256 matched its lock checksum. sha2's is
`47d7069beb7d6ac7b9acd1039986e73443f24234f41074da099d6f994ac9ad19`.
This is pinned artifact identity, not signed-build authentication or an
independent supply-chain/security audit. Python/package/support/toolchain pins
and bridge source bytes are unchanged by this batch.

The unchanged Python bridge retains its latest **56 integration checks / 76
observer requests**, **63 oracle checks** and **68 contract checks** from WP05.
The unchanged independent harness retains **762 tests: 761 passed / one native
peak capability skip**. Those large suites were not needlessly relabelled/rerun
as artifact-native or resource qualification. Complete format adapters,
coordinator integration, environments/generations and release gates below remain
open; no successful `pt run` is enabled by the component.
Static read-back checked **74 local links**, five unchanged Python/support /
toolchain/candidate pin files and all unchanged bridge source modules.

## Required before acceptance

- Wire the complete coordinator-owned request, environment, artifact, process /
  cleanup, generation and final-result catalog to actual independent evidence.
- Implement supported required report/coverage/exception completeness and request
  accounting adapters. Unknown required output cannot pass on a ready flag.
- Preserve argument/entrypoint/plugin semantics and qualify the actual supported
  launcher's early initialization/private-descriptor boundary.
- Fault-test complete integrated execution, output/backpressure, publication loss,
  coordinator death/abandonment, ordinary descendants and required cleanup.
- Complete declared-input/current immutable-generation and installed/host identity
  assurance; end hashes/live-tree observation do not waive edit-and-revert risks.
- Qualify the finite claimed corpus/profile and independent resource, review,
  release-build/provenance and reproducibility gates. Native peak absence remains
  unknown/blocked, not an invented zero or synthetic qualification.

No production speedup, complete work-package acceptance or release claim follows
from these components.
