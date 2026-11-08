# Declared-file reset prototype

`restore_declared_files.py` is an explicit POSIX-only preparation tool for
**disposable benchmark worktrees**, not a general backup or synchronization
utility. It replaces only existing declared regular files in a separate target
root with bytes from a hash-pinned seed root. It requires `--apply`; it does
not remove undeclared files or create missing targets.

Example manifest:

```json
{
  "schema_version": 1,
  "files": [{"path": "data/input.txt", "sha256": "<64-lowercase-hex-digest>"}]
}
```

The displayed digest is a placeholder and must be replaced by the actual seed
SHA-256. Paths are normalized POSIX-style relative paths. Seed and target roots
must be separate and non-overlapping; symlinks in declared paths and the final
root components are rejected. The tool limits each seed's size and accepts at
most 128 declared files. It stages and validates all seed bytes before any
replacement and checks target identity before each rename.

**Limitations:** replacements across multiple files are not transactional. A
late failure can leave a partially reset target; the command reports the number
of replacements and exits nonzero, so the paired runner skips that arm. It does
not protect against concurrent edits racing after the identity check. Replacement
changes inodes and may change ownership, ACLs, extended attributes, and hard-link
relationships; it preserves only ordinary permission bits. Directory entries are
not fsynced for power-loss durability. Do not use this on irreplaceable work.

The result is labelled `applied_unqualified`: it does not verify undeclared
inputs, services, caches, filesystem state, or equivalent arm environments.
Follow preparation with an explicit guarded state probe where appropriate. Even
a matching probe does not make a confirmatory campaign.
