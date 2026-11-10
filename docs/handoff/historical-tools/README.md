# Archived reproduction sources

These five one-off PT development scripts were moved out of temporary storage
during the user-requested 2026-11-10 cleanup. Their source bytes are preserved,
not silently upgraded to production tools or qualification evidence.

**Do not execute them unchanged.** They contain historical absolute paths,
retired input directories, fixed counts and version-specific expectations.
Some generate and run test-owned controls; others only read existing bundles.
The original input bundles were intentionally deleted. Missing execution returns
cannot be recovered by applying these readers to complete-looking files.

- `build-paired-scenario-evidence.py`: historical paired scenario/fault controls.
- `build-scenario-manifest-evidence.py`: historical offline binding controls.
- `check-reference-oracle.py`: early serial-core reference experiment.
- `check-flask-phase-oracle.py`: historical four-reference Flask experiment.
- `check-declared-elf-bundle.py`: independent archive/tree/link/ELF read-back used
  in the final identity batches, including native live-file associations.

Current supported development reproduction instructions are in the root
[handoff](../../../handoff.md), [development guide](../../development.md), and
the relevant committed test-driver READMEs. Use fresh exclusive outputs and
explicitly recreate all pinned inputs before adapting any historical script.
