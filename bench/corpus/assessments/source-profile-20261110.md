# Remaining nine candidate source profiles

Date: **2026-11-10**. Status: **read-only source inspection, unqualified**.
The original [twelve-candidate inventory](../candidates.toml), revisions,
unassessed eligibility and unassigned allocation are unchanged. Earlier
attrs/Click/Rich feasibility evidence remains in its own files, including all
conflicts, skips and Click's 31,000 default-deselected stress cases.

All nine previously uninspected revisions were fetched into new private repos
using `git fetch --depth=1 --no-tags <original-url> <exact-revision>` and a detached
checkout of that fetched object. Exact HEAD and tree IDs were checked; no updated
HEAD, replacement revision, installation or project execution was substituted.
Original commands/outputs are retained at
`/tmp/opencode/pt-candidate-sources-qj5dgr88`.

[`source-profile-20261110.json`](source-profile-20261110.json) records all nine
exact revisions/trees and **22 original configuration-file byte hashes**, declared
Python/build/test requirements and observed pytest lock entries. This is intended
source metadata, not installed-file verification, license review, signed artifact
authentication or semantic eligibility. The first local extraction assumed every
lock entry had a version and rejected pytest's editable self-package entry with
`KeyError`; the corrected record preserves that version as **null**, not an
invented release version. No candidate execution failed or was omitted by that
metadata-reader correction.

| Candidate | Actual source observation | Initial-target disposition, not qualification |
|---|---|---|
| psf/requests `3c7baaa` | `tests` declarations permit pytest >=3; requirements-dev permits >=2.8,<10; local HTTP/TLS fixtures and additional pytest plugins are required. | Potential adapted 8.4.2 profile; installation, owned-service reset and oracle qualification not run here. |
| encode/httpx `b5addb6` | Original `requirements.txt` pins **pytest==8.4.1**. | The declared tooling profile conflicts with exact 8.4.2. Do not silently replace that pin. |
| pallets/flask `49943b5` | Test declaration permits pytest; upstream lock resolves **9.1.1**. | A separately labelled adapted 8.4.2 environment is permitted by the range. The [subsequent Flask feasibility check](flask-49943b5.md) reproduces 494 reference outcomes; it remains unqualified. |
| fastapi/fastapi `ba47d6d` | Test dependency group requires **pytest>=9.0.0,<9.2**. | Direct declared-range conflict; no weakened-dependency run attempted. |
| django/django `a1f2b45` | tox invokes **`tests/runtests.py`**, not the proposed pytest entrypoint, with native database/test initialization. | Requires a separately defined/qualified adapter/reference contract; do not claim pytest equivalence from an invented invocation. |
| sqlalchemy/sqlalchemy `cfc856e` | Test group permits **pytest>=7,<10**; test bootstrap loads its own plugin and default DB is in-memory SQLite. | Potential adapted SQLite profile; native build/extra DB/async/plugin matrices and reset contracts remain unassessed. |
| numpy/numpy `80049a0` | `test-core` requires **pytest==9.1.1**; build/native/threading/BLAS inputs are also required. | Direct declared test-pin conflict. No substitute NumPy wheel/revision or weakened dependency run. |
| python-trio/trio `3cb6acd` | Original test input permits **pytest>=8.4**, but generated requirements pin **9.2.0**. | Potential explicitly adapted input-based profile, not its original lock. Async/SSL/optional/slow/tooling scope and original skips must be qualified. |
| pytest-dev/pytest `bc14038` | The project under test is the **pytest distribution itself** and is an editable self-package in its lock. | Cannot silently replace PT's selected installed pytest 8.4.2 with this different source revision; self-hosting needs its own reference profile. |

These observations preserve difficult/excluded candidates instead of replacing
them with synthetic no-ops. They do not close representative eligibility,
training/confirmatory/holdout, artifact/environment/reset, WP02 or release gates.
No competitor timing, PT conformance or performance comparison was attempted.
