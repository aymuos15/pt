# PT development handoff

Updated: 2026-11-10. Feature work is **paused at the user's request**. This
handoff/cleanup does not declare the project finished. Resume implementation only
when asked; continue the conservative runner and its prerequisites, not later
optimizations ahead of their gates.

## Start here

1. Read [AGENTS.md](AGENTS.md), [README.md](README.md) and the
   [implementation specification](docs/pt-implementation-spec.md). The spec is a
   proposal, not an implementation or performance claim.
2. Read [WP06](docs/wp06-status.md), [WP09](docs/wp09-status.md),
   [WP05](docs/wp05-status.md) and the relevant WP01–WP03 status notes.
3. Check `git status --short --branch` and the remote before making changes.
   The last implementation commit is **`fafa33b9b44e217c5ff786d1d2eb19af307e784d`**
   on `main`, pushed to <https://github.com/aymuos15/pt.git>. Handoff-only commits
   follow it. There was no unfinished feature patch or running background job.
4. Read the committed [development checkpoint](docs/handoff/development-checkpoint.json),
   [host-library checkpoint](docs/handoff/host-glibc-checkpoint.json) and
   [cleanup receipt](docs/handoff/cleanup.json).

**Do not depend on old temporary paths.** The user explicitly requested removal
of the project's temporary data after preserving important information in Git.
Cleanup is complete: **108 PT directories and one generated XML file removed**,
five reproduction scripts archived in Git, and no PT-specific entries left in
`/tmp/opencode`. The 75 unrelated entries were left untouched. The receipt also
retains the initial zero-removal cleanup API failure and the corrected successful
operation. Paths under `/tmp/opencode/pt-*` in older
status notes and archived tools are historical evidence identifiers, not usable
inputs. Raw bundles, prepared interpreters, downloaded archives, disposable
environments and candidate checkouts are not retained by this handoff. Summaries
and hashes cannot replace those raw bundles or recover an execution return.

## What is implemented

- Fresh-process supervision, explicit bridge hooks and owned session/coordinator
  **failure-only** integration; real pytest still owns authoritative same-session
  collection/execution and plugin behavior.
- Bounded private framing/accounting, artifact publication and the exact
  `pytest-8.4.2-xunit2-no-extra-data-v1` JUnit projection.
- Readiness is bound to the actual XML buffer; pending bytes are rehashed after
  validation before publication. Prepublication failure and possible publication
  after a lost return remain distinct.
- Producer finalization waits for the original pinned Config ExitStack to drain,
  preserving callback order, nested registrations and exceptions. This does not
  certify arbitrary interpreter `atexit` or native shutdown.
- Exhaustive native two-walk tree identity, opt-in declared relative-link graph
  closure, non-executing ELF input projection and native live-file association.

Recent implementation commits:

| Commit | Change |
|---|---|
| `683c23d` | Declared JUnit readiness and post-validation byte checks |
| `f2bb2de` | Config cleanup before readiness/terminal emission |
| `a2bad37` | Declared relative-link target closure |
| `c8e96db` | Supplied-byte ELF metadata projection |
| `fafa33b` | Pinned native ELF file association and post-parse rehash |

Important source entrypoints:

- [Identity library](crates/pt-identity/README.md), especially
  [`elf.rs`](crates/pt-identity/src/linux/elf.rs),
  [`elf_file.rs`](crates/pt-identity/src/linux/elf_file.rs) and their controls.
- [Explicit prefix reproduction](crates/pt-identity/tests/private_prefix.rs) and
  [independent readelf/struct control](crates/pt-identity/tests/elf_reference.py).
- [Protected-input setup](tests/packaging/readonly_interpreter_setup.py) and
  [12-stage verification driver](tests/packaging/verify_declared_junit.py).
- [Bridge finalization](python/pt_bridge/src/pt_bridge/_finalization.py),
  [artifacts](python/pt_bridge/src/pt_bridge/_artifacts.py),
  [coordinator](crates/pt-coordinator/README.md) and
  [artifact store](crates/pt-report/README.md).

## Last completed verification—not a new qualification

The final implementation run returned zero for **all 12 stages**, with zero
not-run stages: **225 release Rust tests**, **74 integration / 63 oracle / 68
contract checks**, strict clippy/fmt, CLI/wheel builds and installed-wheel smoke.
The full workspace had no skips. Its 48 identity library methods include 16
live-file controls. The later prefix-only command intentionally filters the
separate evidence-name control, which already ran in the complete workspace.

Independent read-back matched 194 frozen source/pin/schema files, 50 unchanged
Cargo package identities/checksums, eight unchanged pin/candidate/schema files,
both complete interpreter prefixes, all 1,048 links per prefix and all four
readelf/struct reference processes. The 22 coordinator pytest requests, 76
observer requests and three separately declared direct-pytest cleanup references
remain development controls, not qualified backend executions.

The independent benchmark harness was **not** rerun by those 12 stages. Its last
separate full result was 762 tests: 761 passed and one native-memory-peak
capability skip. Missing `memory.peak` remains unavailable, never zero.

Earlier failures remain recorded in the status notes: the undiagnosed original
four-arm artifact failure, two deterministic byte-ordering red controls, Config
cleanup red controls and the incorrect raw-zero fault-fixture assumption, and
the first ELF strict-clippy failure with formatting not run. Later passes do not
erase them. The earlier changed prefix had 98 extra entries and three changed
encoding bytecode files; it was never repaired to manufacture agreement and was
subsequently included in the user-authorized temporary-data cleanup.

## Exact identity boundaries

Selected target: Linux x86-64, GIL-enabled CPython **3.12.12**, pytest **8.4.2**,
bridge **0.0.0**, Rust **1.99.1**. These are selected targets, not qualified support.

- Production wire protocol stays **0 / contract revision 1**. Bootstrap schemas
  **1/2** and independent reference trace **v2** are separate versions.
- Ordinary tree verification checks symlink **text only**. Optional
  `linux-declared-relative-link-closure-v1` closes relative targets through the
  declared graph; it does not follow or authenticate unknown host paths.
- `elf64le-x86_64-declared-load-inputs-v1` projects supplied bytes matching a
  declared regular file. It is not a loader, dependency resolver or general ELF
  validity checker. Preserve raw order/bytes, duplicate NEEDED names, empty search
  strings, unknown tags and unexpanded `$ORIGIN`.
- The actual interpreter has 13 program headers, 35 declared dynamic slots / 30
  through the first NULL, and a 43,370-byte string table crossing two adjacent
  LOAD segments. Do not replace the mapper with a one-segment assumption.
- `linux-live-declared-elf-file-v1` associates the metadata with pinned root /
  parent / leaf observations and a post-parse native rehash. It does not enumerate
  siblings, certify a whole live manifest or authorize a later executable open.
- Tree hashing is **191,199,150 bytes** per successful two-walk verification.
  The separate live ELF check hashes **55,635,280 bytes**. Its nested metadata's
  27,817,640-byte hash is included, not an additional third hash. None is timing
  or execution proof.

Pinned interpreter identity is already committed in
[`artifact.json`](bench/corpus/interpreter/artifact.json):

| Domain | SHA-256 |
|---|---|
| Interpreter archive | `1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c` |
| Archive-derived JSON manifest | `53d7e48554c08a0f6ee912d085cfa37a8256f7a0bb6c7d29d9dc48ac408e279e` |
| Canonical tree | `aef7ea220c93ad437c655d74c617c0b7a7a1cfc0a51c47e6a960d7185a39f499` |
| Relative-link projection | `7f38ee25958f4fc2ee5aeb9320227a947a3be244c34dbccc392a81c90fdf713d` |
| `bin/python3.12` | `3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66` |
| Last development bridge wheel | `4e973ca41e0a9f1614ebd0615f3d302fd4513a19e5a02acd1f68e4450ec286c1` |

The prefixes had 4,971 entries: 3,722 files, 1,048 symlinks, 201 directories,
root mode 0700 and 95,599,575 unique regular-file bytes. These hashes identify
different byte domains; they are not interchangeable or signed release provenance.

## Exact next work: host loader/library inputs

The interpreter declares `/lib64/ld-linux-x86-64.so.2`, RPATH `$ORIGIN/../lib`, and
ordered NEEDED names `libpthread.so.0`, `libdl.so.2`, `libutil.so.1`, `librt.so.1`,
`libm.so.6`, `libc.so.6`. Host aliases, cache/search/hwcaps/preload rules, transitive
and runtime loads remain outside the verified prefix.

The most recent work was **assessment only**, not an unfinished production patch:

- The host reported Ubuntu 22.04 and libc6 `2.35-0ubuntu3.4` amd64.
- The exact historical libc6 archive was separately downloaded from Launchpad
  build **26742694**, checked against the official HTTPS changes-file size/hash:
  **3,234,380 bytes**, SHA-256
  `00e54c06bde8531d955b3fac7dc13f4bd69e5d03515f68a72db08f9cd4cc2c06`.
- Its ar members were `debian-binary`, `control.tar.zst`, `data.tar.zst`.
  Read-only decompression observed 13,414,400 payload-tar bytes / 303 entries.
- The loader plus six named libraries matched archive-derived bytes, modes and
  timestamps at explicitly selected canonical host paths. The public URLs,
  payload descriptors, tool hashes and comparison outcomes are preserved in the
  [host-library checkpoint](docs/handoff/host-glibc-checkpoint.json).
- No package was installed/upgraded, no maintainer script ran, and no target
  loader/library was executed. HTTPS identity is **not signed authentication**.
  This old package is diagnostic input, not a recommendation to install it.

Next, implement reproducible **offline** archive inspection / explicit native
input binding with bounded malformed-archive/decompression/path/identity controls.
Do not adopt observed host files as expected truth or silently weaken the
relative-only link policy to follow absolute host aliases. Keep selected file
matching distinct from loader search or complete environment assurance. Then
continue supported startup/private-FD handoff and the remaining environment gates.

Other open gates: immutable/current declared-input generations; positive
coordinator finalization; complete coverage/rich exception reporting;
representative corpus/ecosystem qualification; native peak measurement;
independent review/reproduction and authenticated release provenance. All twelve
external candidates remain unassessed/unassigned; core/ecosystem mechanisms are
training material. **`pt run` remains unavailable. No speedup is claimed.**

## Rebuild without any old temporary state

Read [development setup](docs/development.md) and
[interpreter preparation](bench/corpus/interpreter/README.md). Explicitly prepare
the pinned toolchain, locked harness environment and required crate/wheel caches
before offline verification. Setup downloads/installations are separate requested
actions, never hidden inside PT execution. Missing caches must stop the offline
check, not trigger dependency substitution or silent flag changes.

The existing protected-input wrapper intentionally accepts only canonical
`/tmp/opencode/...` prefixes. Reproduction therefore creates **fresh disposable**
inputs; it needs no old path. Save important reviewed reports/source changes
durably and clean those new disposable inputs when finished.

Example, from the repository root after explicit tool/environment setup:

```sh
set -eu
WORK="$(mktemp -d /tmp/opencode/pt-resume.XXXXXX)"
mkdir -m 700 "$WORK/download"
curl --fail --location --proto '=https' \
  --output "$WORK/download/interpreter.tar.gz" \
  'https://github.com/astral-sh/python-build-standalone/releases/download/20260211/cpython-3.12.12%2B20260211-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
printf '%s  %s\n' \
  '1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c' \
  "$WORK/download/interpreter.tar.gz" | sha256sum --check --strict
PY="$PWD/bench/harness/.venv/bin/python"
"$PY" -B bench/corpus/interpreter/materialize.py \
  --execute --archive "$WORK/download/interpreter.tar.gz" --output "$WORK/prepared"
"$PY" -I -S -B tests/packaging/readonly_interpreter_setup.py --execute \
  --prefix "$WORK/prepared/prefix-1" --prefix "$WORK/prepared/prefix-2" -- \
  "$PY" -I -S -B tests/packaging/verify_declared_junit.py --execute \
  --output "$WORK/verification" \
  --prefix-one "$WORK/prepared/prefix-1" --prefix-two "$WORK/prepared/prefix-2" \
  --manifest "$WORK/prepared/prefix-manifest.json" \
  --manifest-sha256 53d7e48554c08a0f6ee912d085cfa37a8256f7a0bb6c7d29d9dc48ac408e279e
```

Run these as individually checked stages: if any command fails, stop and retain
its actual return and not-run denominator. The mount namespace is explicit test
setup, not a production launcher, sandbox, immutable generation or equivalent
timing arm. Never repair inputs or delete bytecode to manufacture agreement;
isolated `-I` probes ignore `PYTHONDONTWRITEBYTECODE`.

Useful historical standalone scripts were saved under
[`docs/handoff/historical-tools`](docs/handoff/historical-tools/README.md) before
cleanup. They retain old paths and assumptions, are **not current entrypoints**,
and must not be run blindly or treated as saved-proof recovery. Prefer the
committed current drivers and fresh explicit inputs above.
