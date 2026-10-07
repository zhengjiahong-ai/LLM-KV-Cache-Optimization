# Phase 2A M6 — H2 Calibration Review

Status: **READY FOR M1/M4 REVIEW — NO FORMAL THRESHOLDS FROZEN**

This note summarizes the completed H2 calibration pilot required by
`docs/phase2a-m6-h2-measurement-design.md`. It does not authorize formal H2
measurement, produce an H2 verdict, or unlock B1.

## Evidence identity

- Campaign: `phase2a-h2-cost-curve-calibration-v1`
- Campaign artifact: `artifacts/phase2a-h2-calibration-pilot-v2/campaign.json`
- Campaign SHA-256: `b1f3f5dd15dde6c66c478569c2ed04e0238c32bd7508b2df71101c8020b586bb`
- Run root: `artifacts/phase2a-h2-calibration-pilot-runs-v3/`
- Calibration report: `artifacts/phase2a-h2-calibration-pilot-runs-v3/calibration-report.json`
- Report SHA-256: `dec9f8f53ce6f66f1cabc054709dacfafe1cffce2b3f201f6639340cf73cbcf3`
- Code revision: `37656a2831ff85eecf5d077f57dcd3530a053052`
- Execution coverage: 119/119 planned runs completed successfully: 34 warmups and
  85 measured runs, with 5 measured repetitions at each of 17 grid points.

The report verifies one clean code revision, matching configuration hashes,
successful terminal status, one request per measured run, and available timing
fields for every included repetition.

## Measurement availability

The requested primary observation,
`isolated_native_prefill_elapsed_seconds`, is **UNAVAILABLE**. The available
`native_prefill_to_first_token_seconds` measurement includes work between
scheduler admission and first token and is therefore retained only as a
sensitivity candidate pending M1/M4 review.

Median native queue delay remained approximately 0.116--0.144 ms across the
grid. This supports the empty-queue control, but it does not turn the available
timing candidate into the requested isolated prefill measurement.

## Pilot results

All requested grid points fit and executed, including the three points above
24,576 tokens.

| Prefix tokens | Median (ms) | MAD (ms) | Max absolute deviation (ms) |
| ---: | ---: | ---: | ---: |
| 16 | 346.518 | 7.124 | 227.198 |
| 32 | 131.978 | 3.771 | 166.107 |
| 64 | 133.045 | 5.105 | 172.506 |
| 128 | 262.043 | 26.997 | 116.898 |
| 256 | 145.878 | 0.886 | 5.506 |
| 512 | 177.552 | 10.613 | 189.172 |
| 1,024 | 227.432 | 4.309 | 84.061 |
| 2,048 | 392.400 | 48.029 | 110.560 |
| 4,096 | 612.253 | 55.515 | 153.676 |
| 8,192 | 1,256.143 | 3.124 | 15.432 |
| 12,288 | 2,168.092 | 38.492 | 51.172 |
| 16,384 | 3,022.491 | 4.760 | 18.270 |
| 20,480 | 4,470.696 | 10.676 | 93.488 |
| 24,576 | 6,181.436 | 47.990 | 262.583 |
| 26,624 | 7,139.105 | 50.662 | 89.030 |
| 28,672 | 8,147.097 | 20.385 | 40.866 |
| 30,720 | 9,267.635 | 78.354 | 80.801 |

The maximum per-point MAD is 78.354 ms and the maximum absolute deviation from
a point median is 262.583 ms. The short-prefix region is non-monotonic and has
large isolated deviations: for example, the 16-token median exceeds the
32-token and 64-token medians. Process startup, Metal compilation, or another
fixed-cost component can dominate this region. These values must not be treated
as a clean `C(r)` curve without resolving the observation limitation.

The long-context medians rise consistently from 8,192 through 30,720 tokens,
but that visible trend is not a formal curvature result. No model fitting,
bootstrap interval, PASS threshold, or verdict is authorized at this stage.

## M6 recommendation for review

1. Retain the complete 17-point grid. Every point is executable on the reviewed
   model and backend.
2. Use 9 measured repetitions per point if formal timing measurement is
   authorized. This is the conservative predeclared candidate because the pilot
   contains material per-point dispersion and isolated deviations; it is a
   recommendation, not yet a frozen repeat count.
3. Treat 78.354 ms as the observed worst robust sensitivity noise statistic and
   262.583 ms as the conservative observed maximum-deviation bound. Neither is
   an approved formal effect threshold.
4. Do not use `native_prefill_to_first_token_seconds` as the primary M1 input
   unless M1/M4 explicitly revise the observation contract. Prefer adding the
   requested isolated native prefill/reload elapsed-time seam.
5. Do not materialize formal H2 verdict outcomes or begin B1 until the freeze
   record below is complete.

## Required M1/M4 rulings before formal measurement

- **Observation:** add a direct isolated native prefill/reload elapsed-time seam,
  or explicitly constrain the current timing candidate to sensitivity evidence.
- **Repeat count:** accept or revise the proposed 9 measured repetitions per
  point.
- **Resolution rule:** define how baseline MAD and maximum deviations determine
  the pairwise effect-resolution floor.
- **M1 threshold:** freeze the material-improvement statistic, critical value,
  confidence level, and resampling scheme for the positive quadratic term.
- **M2 tolerance:** freeze the token-count tolerance used for cached-prefix and
  recomputed-suffix equality.
- **M3 threshold:** freeze the minimum distinguishable leading-versus-trailing
  realized effect.
- **M4 threshold and aggregation:** freeze the entry-level comparison,
  cross-entry aggregation rule, and minimum extra-headroom effect.

Until these items are approved and recorded, the machine-readable design
remains `formal_measurement_authorized: false`,
`formal_verdict_authorized: false`, and `numeric_thresholds_frozen: null`.

