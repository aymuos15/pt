# Public source metadata preserved during cleanup

These are exact public HTTPS source responses retained before deleting the
downloaded libc6 archive. They contain the original Launchpad build metadata and
changes-file checksums, not package payloads, credentials, an installed environment
or PT benchmark results.

- `glibc-build-26742694.json`: Launchpad build API response.
- `glibc_2.35-0ubuntu3.4_amd64.changes`: official build changes file, including
  the selected libc6 archive's advertised size and SHA-256.

Their observed hashes and original/final URLs are recorded in
[`host-glibc-checkpoint.json`](../host-glibc-checkpoint.json).
They establish observed identity under HTTPS source trust, **not signed archive
authentication or independent build provenance**. The historical package is
diagnostic data, not an installation/upgrade recommendation.
