# Corpus development

These synthetic probes are **not** a representative corpus or evidence of PT
compatibility. They are initial material for WP02 and WP03. They have no frozen
training, confirmatory, or holdout assignments; no environment locks or reset
contracts have been established.

`probes/noop_cases.py` contains one successful test. `probes/phase_cases.py` is
intentionally nonzero: it includes a passing test, setup failure, teardown
failure after a passing call, and strict XPASS. Run it explicitly, for example:

```sh
python -m pytest -p no:cacheprovider bench/corpus/probes/phase_cases.py
```

The probe alone does not prove a comparator can distinguish the phases. Future
oracle tests must verify actual phase reports, multiplicity, and exit status,
including broken-runner negative controls. Direct pytest behavior must be pinned
and qualified before use in a confirmatory campaign.
