# Threat model — WP00 draft

Status: proposed and unreviewed. PT runs tests with the invoking user's authority;
it is **not a sandbox**. Hostile test code can read, alter, or exfiltrate anything
the user can access and may escape ordinary process-tree ownership. Stronger
isolation must be provided separately.

Protect against accidental or malformed project input, stale state, corrupt
cache files, malformed protocol messages, unauthorized local IPC clients where
the platform allows, credential disclosure through metadata, and resource leaks.
The coordinator must not interpret project-supplied pickle or cache data as
executable objects. Use user-scoped permissions and session authentication where
needed; validate framing, sizes, IDs, schemas, and provenance. Secrets are not
stored as raw environment values in exported plans. Cache deletion is confined
to PT-owned metadata, never project files.

Tests, plugins, build tools, and dependencies execute arbitrary code and must be
trusted by the operator. Hashes establish artifact identity, not safety. Source
and external input identities may be incomplete; in that case no semantic cache
or snapshot assurance may be asserted. Infrastructure failure, lost finalization,
or uncertain source generation must not become a passing result.

Open review items: local attacker model by OS, secure IPC credentials and token
lifecycle, race-resistant cache path handling, artifact retention and redaction,
symlink traversal, denial-of-service limits, dependency supply-chain practices,
and cleanup behavior when descendants deliberately detach.
