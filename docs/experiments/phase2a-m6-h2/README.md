# Phase 2A M6 H2 Measurement Evidence

`isolated-seam-validation-summary.json` records the clean single-point runtime
validation of the profiling-only Metal prefill timing seam at 8,192 prefix
tokens. The synchronized isolated measurement was present, positive, and lower
than scheduler-admission-to-first-token timing. Queue delay remained negligible.

This validates the observation seam only. It is not the eight-point calibration,
does not freeze `delta_M1`, is not formal H2 measurement, and does not produce a
verdict.
