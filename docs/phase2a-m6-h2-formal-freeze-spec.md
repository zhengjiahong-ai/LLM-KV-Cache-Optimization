# Phase 2A M6 — H2 Formal Freeze Specification

Status: **RULES FROZEN — ISOLATED-SEAM CALIBRATION STILL REQUIRED**

This document records the exact M1/M4 ruling without overwriting the earlier
calibration-stage design. Its machine-readable companion is
`configs/phase2/h2-formal-freeze-spec.json`.

Formal H2 measurement and verdict computation remain unauthorized. B1 remains
locked.

## Common execution discipline

- Complete C(r) grid: 17 approved points from 16 through 30,720 tokens.
- Formal repetitions: 2 warmups plus exactly 9 measured repetitions.
- Repetitions estimate noise and reproducibility; they are not independent
  scientific samples.

## M1 isolated-seam calibration and curvature rule

The primary observation is `isolated_native_prefill_elapsed_seconds`. The
existing scheduler-admission-to-first-token measurement remains sensitivity
only.

Before formal measurement, run only the fixed eight-point region at or above
8,192 tokens with 2 warmups and 5 measured repetitions. At each point, use
10,000 bootstrap resamples of size 9, median statistic, and seed 20261007.
`delta_M1` is the maximum across points of the 95th percentile absolute
difference between each bootstrap median and its calibration median.

Formal C(r) is the median of nine isolated measurements. L0, L1, and L2 are
reported on the full grid; the confirmatory L1/L2 comparison uses the fixed
eight-point region. `Delta_fit` is LOPO-CV-RMSE(L1) minus LOPO-CV-RMSE(L2).
PASS requires observed `Delta_fit > delta_M1`, a positive 95% bootstrap lower
bound for `Delta_fit`, and a positive lower bound for quadratic gamma. A
non-positive upper bound for either statistic is FAIL; all other cases are
INCONCLUSIVE.

## M2 exact native-token rule

Use a 64-block prefix, 16-token blocks, retained leading block counts
`{0,16,32,48,64}`, a one-token fresh suffix, and a separate no-eviction full-hit
control. Token tolerance is zero. Every valid repetition must exactly match the
expected cached prefix and recomputed suffix.

## M3 position rule

For the frozen 4-prefix by 3-j grid, each of 12 cells contains nine paired
leading/trailing measurements. A cell supports position when at least 8/9
differences are at least 16 tokens. PASS requires at least 10/12 supporting
cells; FAIL requires at least 10/12 cells with no resolved effect; otherwise the
result is INCONCLUSIVE.

## M4 single-prefix headroom rule

The comparator is no longer an unresolved cross-entry formula. Within the same
prefix state and j, compare actual recomputation from logical entry release plus
native LRU (`R_entry`) against the controlled trailing-j offline mechanism
oracle (`R_block`). `H = R_entry - R_block`.

A cell supports headroom when at least 8/9 paired H values are at least 16
tokens. PASS requires at least 10/12 supporting cells; FAIL requires at least
10/12 cells with no resolved headroom; otherwise the result is INCONCLUSIVE.
The oracle is not a B1 runtime policy, and cross-entry aggregation remains a
future design question only if every H2 gate passes.

## Remaining freeze boundary

The exact rules and repeat count are frozen, but the numeric `delta_M1` is not.
After the profiling-only isolated seam is implemented and the eight-point
calibration completes, a final immutable record must bind `delta_M1` and all
code/config/runtime hashes. Only review of that record may authorize formal H2
measurement. No threshold may change after the first formal outcome is
materialized.
