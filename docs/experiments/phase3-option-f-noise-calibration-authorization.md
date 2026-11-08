# M1 G0 Acceptance and Noise Calibration Authorization

**Date:** 2026-11-07  
**Repository:** `zhengjiahong-ai/LLM-KV-Cache-Optimization`  
**Accepted implementation HEAD:** `6f77f7178d366a259e14285469f9419e05afaa5f`  
**PR:** #99 (merged as `a7fe138354720412b393ac584e8d1d6ed8cd4709`)  
**G0 bundle:** `docs/experiments/phase3-option-f-g0-v3/`

## Decision

M1 accepts G0 v3 as the final frozen G0 evidence package and authorizes exactly the next execution stage:

**A0 Noise Calibration — 30 runs.**

This is an explicit stage authorization, not a blanket authorization for the complete 270-run budget.

## Frozen bindings

- G0 freeze manifest SHA-256: `db9ebb8a388d30f6d9bc1c58a19dd8b97b9ce0a7afdafea124987754fbcde971`
- Noise plan SHA-256: `2107d1fc42d7e37c0528d681cb5c1ff2dc703e7e8573376e8ffadae76e6f33f5`
- Noise input manifest SHA-256: `061b91e49abf912ec86b4d75f37b844654c39db8fd08fe9fcabff6b0bc8bb54a`
- Noise groups: `g01, g04, g06, g07, g10`
- Conditions: `C1, C2`
- Arm: `A0` only
- Repeats: `1, 2, 3` per Group × Condition cell
- Total: `5 × 2 × 3 = 30` runs

## Execution constraints

1. Execute only the exact 30 Run IDs and frozen configurations bound by the Noise input manifest.
2. Verify the G0 manifest, Noise plan, input manifest, configuration hashes, and external evidence archive before launch. Any mismatch is FAIL-CLOSED; do not regenerate, repair, or substitute inputs under this authorization.
3. Do not rerun the existing 40-run A0 Load Calibration.
4. Do not reacquire or replace cohort tasks, alter Group selection, conditions, repeats, or estimator.
5. Capture complete per-run native evidence and execution records. No partial or inferred result may be counted as a completed run.
6. After execution, run the independent Noise evaluator against the exact frozen Run-ID set and report the pooled `sigma_run`, `sigma_delta`, and tied threshold, with per-stratum diagnostics only.
7. Preserve the raw results and evidence immutably; submit the result package and hashes to M1 for review.

## Explicitly not authorized

- The 240-run six-arm Main Campaign remains **LOCKED**.
- No A1/A2/A3/E0/N0 execution under this authorization.
- No changes to Protocol v4, cohort, run plan, or statistical estimator.
- No campaign expansion beyond these 30 A0 Noise Calibration runs.

Main Campaign requires a separate M1 decision after Noise Calibration is complete, its estimator and tied threshold are frozen, and all applicable G1/G2/G3-CM/G4 gates are satisfied.

## Status

`G0_ACCEPTED`  
`NOISE_CALIBRATION_AUTHORIZED = true`  
`MAIN_CAMPAIGN_AUTHORIZED = false`

This record authorizes the M6 execution owner to launch the bounded Noise Calibration stage under the constraints above.
