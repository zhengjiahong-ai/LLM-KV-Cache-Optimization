# Phase 3 Algorithm Exposure Audit Data

These files are deterministic, read-only derivatives of the immutable Phase 3
Option F archive. The source archive is not committed because it is about
802 MiB; its SHA-256 is bound in `summary.json`.

## Files

- `global-summary.csv`: one row per arm.
- `group-condition-summary.csv`: all 20 × 2 × 6 Group/Condition/arm cells,
  including zero-decision cells, with frozen pressure-response stratum and A0
  `rho0`.
- `decision-audit.csv`: one row per actual Forced Release, traceable to Run ID,
  Decision ID, and event indices.
- `strategy-pairwise-comparison.csv`: ordinal paired program selections. Rows
  after a first divergence are explicitly marked diagnostic.
- `fallback-reason-distribution.csv`: fallback counts by arm and reason.
- `summary.json`: compact headline counts and source identities.
- `sha256-manifest.txt`: hashes of every machine-generated derivative above.

## Denominators

- Main runs: 240.
- Release-enabled arm decisions: 127 per arm.
- A3 multi-candidate and multi-scored opportunities: 7 decisions.
- Physical outcome and recomputation are separate evidence tiers.

Blank CSV cells mean the field is not applicable or not independently
observable for that arm; they do not mean zero.
