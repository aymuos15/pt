# Candidate assessment: Textualize/Rich at 3a109cc

**Unqualified local feasibility assessment**, not PT conformance or benchmark
evidence. Eligibility remains unassessed and allocation unassigned.

The observed revision is `3a109ccdffe5b2d0e30684a304fbd388e99ce57b`, tree
`013d80d7365a5f6954628eb8b4263154ebf9cae7`. The upstream `uv.lock` SHA-256 is
`79e045d1ae56de4c7256d5f25ae92ea4a98337cbb086f2f07929bd93abd4d1e9`.
Two upstream-lock environments selected pytest 9.2.0; two others used the
separately generated [adapted pytest 8.4.2 lock](rich-3a109cc-pytest842.requirements.txt),
SHA-256 `85a7f304eb2f56ddef96227429e7ad03303c62de085886dd52303fdeaba8d3ca`.
Both profiles included pytest-cov 7.1.0 and coverage.py 7.17.2. The adapted
environments shared a locally built wheel with SHA-256
`a93558b972eb2ce7f567876fdf4bbb29043099a338aea3e617be4a68798b1759`;
its build environment was not independently pinned. The observed CPython
3.12.12 interpreter SHA-256 was
`3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66`.
These hashes do not authenticate artifacts.

Four separate source worktrees were run with the pytest console entrypoint,
`-q --cov=rich --cov-report=json:<external-path> --junitxml=<external-path> tests/`,
with inherited pytest/Python path overrides removed and bytecode writing
disabled. Each reported **956 passed and 25 skipped**. Coverage database paths
show all 96 measured files came from the respective source worktrees, not
simply the installed wheel. These runs do not establish immutable source or
installed environment identity during execution.

Within each profile, ordered limited JUnit observations matched: 981 occurrences.
Across profiles, **eight occurrences differ**: parameter IDs for four
`test_panel::test_render_panel` and four
`test_table::test_placement_table_box_elements` cases. Pytest 9 reported
`expectedN` IDs while pytest 8 reported escaped rendered strings. Their recorded
outcome fields matched; the IDs are preserved, not normalized away. The separate
reviewed observations are:

| Profile | Normalized records SHA-256 | JSON file SHA-256 |
|---|---|---|
| [pytest 9.2.0](rich-3a109cc-pytest920-junit-normalized.json) | `5bfabf7006ed2eadfb021967c65150c9dbad0317e654e810b928bf0e2098c4a7` | `e24eafafd2f15957b9e9ba011c8a95591022fc7b5ec8bcade4200736b4608054` |
| [pytest 8.4.2](rich-3a109cc-pytest842-junit-normalized.json) | `fd027f99a48e6d656b0db956da3267b6f4997d1d8c5b578230ac2ddaa35e956e` | `4927c8e5ed82252ae3cb016938fa66d68e6e4a6c5f786f526d57e7fb87648e35` |

All four limited no-context, non-branch coverage line inventories matched:
96 files, digest `997fc8836ed3d75ae91630f8f1e387e44beaa71b58c9ba64c067f60dfceeeaf0`.
This does not qualify branch, context, subprocess, source integrity, or PT
coverage. JUnit does not preserve authoritative node IDs or phase reports.

Installed RECORD inventories matched within each profile after execution:
upstream verified 2,856 hashed entries, 2,838 comparable, 30 unhashed and 18
entrypoints excluded; adapted verified 810, 803 comparable, 12 unhashed and
seven excluded entrypoints. Comparable digests respectively:
`2889858bc591619037cda8ef593f43f19e6be23178849ad45700a0e18280acd3` and
`a557ee9c6bfe8df20ddf2d37892ab9f66ec15265597cb47498e3129bca218ab9`.
RECORD provenance and unlisted files were not verified.

Raw JUnit and coverage reports remain in temporary storage, not committed. In
run order their SHA-256 values are:

| Run | JUnit | Coverage JSON |
|---|---|---|
| upstream 1 | `3d568c533afa801219581bda1afceccc18caccad1db92a69adfac7d4323a5959` | `233a50240ddf87469539ad4b192827e913a614641f69b0b12a548a478b1d7d56` |
| upstream 2 | `8828bdae77b4f37526cfef32ac1aaaf06639d7ed87a5a8c18ceb914cf1c4b2b6` | `88a5409278691aed841e900526e8cedb6085ef7b2b19dc75f0079312be47e5d2` |
| adapted 1 | `5fb07173e053d30d802ef7bf02ea775255f52aa12b4235a99c446f8994a60579` | `990accb02a5a4f24a26cb65f56fda0f815dc390ee0f0c06706d7b416c9284b3b` |
| adapted 2 | `7be128e991cdb38186e962cef115925c168b71ece88c84a635cfbeef327ebaec` | `b35b71fc824dfaf8ccbb69b82a366d502128c263c7f41d878bef83cf5a21b3e4` |

Further work requires independently authenticated builds, reset and source
integrity validation, phase-level work comparison, reviewed profile and corpus
split decisions, and PT conformance. No performance or full qualification
claim follows from these observations.
