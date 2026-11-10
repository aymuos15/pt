# Pinned private interpreter preparation (WP02)

These are **explicit offline development setup tools**, not PT runtime installation,
a supported launcher, a sandbox or release qualification. They create new private
prefixes instead of repairing, patching or deleting a user-managed interpreter.
No dependency download, environment upgrade or test retry occurs.

## Artifact identity and trust boundary

[`artifact.json`](artifact.json) pins the original python-build-standalone GitHub
release **20260211**, asset **354545704**, GIL-enabled CPython **3.12.12**, Linux
x86-64 GNU `install_only_stripped` archive:

- Archive: **33,887,801 bytes**, SHA-256
  `1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c`.
- `bin/python3.12`: **27,817,640 bytes**, SHA-256
  `3008abbb48c1e2b0fa3072ae72334b9b352e1346ea3a20d34126a455f0c7bc66`.

The digest/size were advertised by the original release's HTTPS GitHub API and
checked against a separately downloaded artifact. This establishes observed
artifact identity under that source trust, **not signed/independent build
attestation**; the declaration retains that field as null. A matching binary
alone does not identify its stdlib, startup code or installed environment.

The initial read-only comparison found that the managed interpreter's binary
matched, but its complete prefix did not: four files differed, with 215 extra
files/links and 25 extra directories after deriving implicit archive parents.
Those differences remain untouched. The original audit and correction are
retained at `/tmp/opencode/pt-python-artifact-audit-jg77j34z`; the first audit
overcounted implicit directories and used ordinary imports that could write pyc
caches. The correction used `-I -S -B`, retained both reports and did not repair
any cache or normalize away an actual byte mismatch. Neither audit was atomic.

## Two fresh, complete prefixes

Obtain the exact archive from the pinned `source.download_url` as a separate,
explicit artifact-preparation action. `materialize.py` accepts an already
downloaded local regular file and **never accesses the network**:

```sh
directory="$(mktemp -d /tmp/opencode/pt-python-prefixes.XXXXXX)"
uv run --locked --project bench/harness --python 3.12.12 python -B bench/corpus/interpreter/materialize.py --archive /absolute/path/to/the/pinned/archive.tar.gz --output "$directory/prepared" --execute
```

`--execute` authorizes extraction and **two** ordinary-startup setup probes in
new prefixes. The archive is copied with no-follow/no-overwrite semantics into
the private evidence root, checked against the exact hash/size, and inspected
fully before extraction. The executable has its own independently checked byte
pin. Every prefix includes the original pip files/metadata shipped in that
artifact; pip is not invoked or upgraded.

The bounded extractor supports regular files, relative in-prefix file-alias
symlinks and directories. It rejects traversal, foreign roots, duplicate members,
linked parent components, dangling/external/cyclic/directory symlinks, hardlinks,
devices, FIFOs, sparse files, special permissions and world-writable regular
files. It never invokes tar's extraction API, changes ownership, rewrites
sysconfig, regenerates bytecode or calls a package manager. Files retain their
exact bytes, modes and mtimes; symlink targets remain exact. Implicit parent
directories are synthesized as 0755, explicitly included in the manifest, not
misclassified as extra installed paths. The outer evidence directory is 0700.

Limits are **128 MiB compressed**, **256 MiB complete inflated tar stream**
(including metadata/padding), **128 MiB/file**, **512 MiB regular-file total**,
**16,384 entries including implicit parents**, **24 path components**, 1024
characters per path/target and 40 link-resolution steps. Bounds fail rather than
truncate work. Gzip trailers/CRC are read and checked too. These controls are
finite data handling, not hostile-concurrency isolation or an on-disk quota.

Every actual file, exact link target, directory, mode and regular-file mtime is
compared to the manifest before and after the probe. Unlisted entries count as
differences. No paths, caches or generated files are silently excluded or repaired.
Source inputs and the private archive are checked again before a matched result.
Ancestors are caller-owned; identity/end checks cannot prove that no transient
change occurred while the interpreter ran. Root ownership/xattrs and dynamic
loader/host-library identity remain outside this finite prefix contract.

The setup probe uses **`-B` only**, a declared minimal environment, private
HOME/TMPDIR and C.UTF-8. Site initialization is **not disabled**: no `-I`, `-S`,
replacement entrypoint or hidden collection is used. It records actual version /
ABI, prefix, site flags, source origins, search paths and native-library version
diagnostics. Prefix-relative origins are mapped explicitly; unexpected external
Python import/search origins fail. This setup policy does **not** replace PT's
future caller-environment policy or prove safe socket adoption during arbitrary
`.pth`/sitecustomize/native startup. No pytest session is executed by this probe.

The output retains both prefixes, the archive, complete manifest, frozen setup
sources, actual process observations/raw output and two predeclared outcome rows.
Lost returns remain unknown; complete-looking runtime files cannot recover them.
Failures stop later work without retry. Existing outputs are never overwritten.
All seven provenance/environment/startup/oracle/backend/generation/release
qualification fields remain null and confirmatory eligibility false.

## Locked corpus on explicitly selected private bases

[`check_serial_core.py`](check_serial_core.py) rechecks the archived bytes and
derives its own manifest, then independently reads **both entire prefixes**;
saved status/verification flags cannot waive changed bytes. It then explicitly
selects one base per new locked serial-core venv:

```sh
uv run --locked --project bench/harness --python 3.12.12 python -B bench/corpus/interpreter/check_serial_core.py --prepared "$directory/prepared" --output "$directory/corpus-check" --execute
```

This authorizes two new **offline** dependency installations and all **20**
declared fresh real-pytest requests, retaining intentional exits 0, 1, 2 and 5.
Both base prefixes must still match afterward, alongside the existing
site-packages, source, JUnit and effect checks. A failed/unknown corpus return is
retained, never reconstructed from files or promoted by a clean final prefix.
The underlying [serial-core tool](../serial_core/README.md) also accepts
`--base-python FIRST SECOND` explicitly; no missing selection falls back to a
different interpreter. With no such option, its original base-selection behavior
is unchanged and now recorded. None of this enables `pt run` or qualifies the
phase oracle, external projects, complete host environment or immutable generation.

See [WP02 evidence and open gates](../../../docs/wp02-status.md). Do not commit
generated interpreters, environments or raw diagnostic paths.
