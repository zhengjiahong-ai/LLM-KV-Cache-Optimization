# Phase 2A M6 H2 Measurement Evidence

`isolated-calibration-numeric-audit.json` contains all 40 measured elapsed
values in original run order, with run IDs, code SHA, configuration/trace hashes,
and hashes of the raw manifests and events. Warmups are excluded.

Independent reproduction uses `scripts/audit_h2_bootstrap.py`, which does not
import the production bootstrap implementation. It reproduces every per-point
delta and the exact maximum `0.19029591700382298` seconds. Statistical controls
remain 10,000 resamples of size nine, seed 20261007 reset per point, median,
and nearest-rank 95th percentile. Reproduction command:

```bash
python scripts/audit_h2_bootstrap.py docs/experiments/phase2a-m6-h2/isolated-calibration-numeric-audit.json
```

The elapsed observation measures synchronized native forward execution at the
submit/completion boundary. It excludes token sampling and request completion;
it is not end-to-end request latency. The timing may include lazy forward graph
evaluation and execution-related compilation. A smaller value than
admission-to-first-token timing alone does not prove these boundaries; the
profiling hook implementation and its ordering tests establish the boundaries.

The immutable authorization submission binds the numeric audit, independent
verifier, prior freeze record, calibration evidence, rule spec, and execution
configuration hashes. Formal H2 measurement and verdict authorization remain
false pending the M1/M4 ruling.

`isolated-seam-validation-summary.json` records the clean single-point runtime
validation of the profiling-only Metal prefill timing seam at 8,192 prefix
tokens. The synchronized isolated measurement was present, positive, and lower
than scheduler-admission-to-first-token timing. Queue delay remained negligible.

This validates the observation seam only. It is not the eight-point calibration,
does not freeze `delta_M1`, is not formal H2 measurement, and does not produce a
verdict.
