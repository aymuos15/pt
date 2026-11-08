# Candidate assessment: pallets/click at 8abb77a

Status: **unqualified; local feasibility only**. The candidate remains
unassigned in `../candidates.toml`. This is neither PT conformance nor a
performance comparison.

## Source and profiles

- Source: `https://github.com/pallets/click.git`, revision
  `8abb77a8432e03ed14a95f972b44f905279415a7`, tree
  `84808be7a7674fe64b97f058372ae36a14b9eca6`.
- Upstream `uv.lock` SHA-256:
  `742507a6bbb80c093d2ebefc073357e3ef0cb504e9299def5348377f0d585d54`.
  Its locked `tests` group resolves **pytest 9.0.2**, not the proposed PT
  profile's pytest 8.4.2. The project declares `pytest` without an exact version.
- Two additional environments used an **adapted**, locally generated
  [pytest 8.4.2 requirements lock](click-8abb77a-pytest842.requirements.txt),
  SHA-256 `fdcf1aa3905b569bf05d170acfe795dfd87c63e43ee6bc67afa9301cfca3d5d8`,
  installed with `uv pip sync --require-hashes`. This is not the upstream lock.
  It resolved iniconfig 2.3.1, packaging 26.3, pluggy 1.7.0, and pygments 2.21.0.
- The adapted environments installed the same locally built
  `click-8.6.0.dev0-py3-none-any.whl` with `--no-deps --no-index`; the wheel's
  observed SHA-256 was
  `2f6f07747046de500f246e1a74df4617dde0dc460e69b61d4019586edbf5e878`.
  The build environment was not independently pinned or reproduced, and the
  wheel was not committed. Its observed digest is not provenance verification.
- Local check completed 2026-11-08 UTC on Linux x86-64 with CPython 3.12.12;
  each interpreter binary's observed SHA-256 was
  `3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66`.

## Procedure and results

Two upstream-lock environments and two adapted environments were installed.
Each profile used a shared source build or wheel and local cache; they were not
independent builds. Four separate detached worktrees at the pinned revision were
used for execution. Git reported no tracked modifications afterward, but
ignored files and all external inputs were not independently audited.

For each environment, inherited `PYTHONPATH`, `PYTHONHOME`, `PYTEST_ADDOPTS`,
`PYTEST_PLUGINS`, and `PYTEST_DISABLE_PLUGIN_AUTOLOAD` were removed;
`PYTHONDONTWRITEBYTECODE=1` was set. Plugin autoload remained enabled. Each ran:

```text
<environment>/bin/python -m pytest -q --junitxml=<external-output>
```

All four commands exited 0. Each reported **2,623 passed, 24 skipped, 1 xfailed,
and 31,000 deselected**. The repository's own pytest configuration supplies
`-m 'not stress'`; the deselected stress cases are **not** included in the JUnit
testcase inventory. This was a serial, selected-scope feasibility run, not a
full-suite result. Warning-as-error configuration was left intact.

Ordered JUnit classname/name and outcome tag/type/message observations matched
across all four runs: **2,648 reported occurrences**, normalized SHA-256
`27cd861f50bd5af6b5dd28940f738b43f44078312a95033411ed446fb6c7c3b9`.
The [normalized observation](click-8abb77a-junit-normalized.json) has file
SHA-256 `dfa85b9d0c5ecc3cf6483e833590a3c8785e33dc51209a322b931ffd74260634`.
Its parameter IDs include public synthetic test strings from the source tree.
The raw JUnit files remain only in the local temporary assessment directory;
their SHA-256 values, in run order, were:

1. `229ff55a37a960ca98a59d550fcb41bd957635ec4d65a5a4e09565883c581c11`
2. `695739d6f9fc2d3955d1c547c8cad47813f1eb021c5eef3861a9a949ba52233e`
3. `ff14953290745ee497ec4a045d3f07f46ea6fa8208667e24ad367d869724d03c`
4. `869ad31a4111d75a80f27614dea0c2dd4cbb73822c091297e7a8d39023fa7c79`

After execution, the installed-file checks matched within each profile. The
upstream pair verified 509 hashed RECORD entries, of which 506 were comparable;
the adapted pair verified 521, of which 518 were comparable. Each had six
unhashed RECORD entries and three generated entrypoints excluded from
cross-directory comparison. The respective comparable inventory digests were
`1a2a3a67893835f2dd912acc36bb09de04f2d6c482a4a5d5b49cfc8ec7ed93b6` and
`89d82f688385a7e49e1fe7fff00281239c4e65a4d8c98fa12989d016751af670`.
RECORD provenance and unlisted installed files were not verified.

## Decision and limitations

Keep eligibility **unassessed**. The adapted pytest 8.4.2 run is useful evidence
for planning, but its dependency lock differs from upstream and its wheel build
was not independently reproduced. A matching JUnit inventory does not establish
authoritative pytest node IDs, fixture lifetimes, phase-level equivalence,
equal work, or PT compatibility. Before any campaign, pin and verify build
artifacts, qualify the actual invocation and plugin contract, decide how the
31,000 deselected cases affect the claim, define reset/source boundaries, and
assign the repository to an appropriate preregistered split. No benchmark
timings or speed claims are made here.
