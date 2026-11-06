# Phase 3 Option F Engineering Status

## Current state

- M1 design decision: Option F accepted (Issue #98; PR #97).
- Protocol: v4 implemented as an independent document; v3 remains historical.
- Existing A0 calibration: reused, not rerun.
- G0 tooling: implemented. The v1 review bundle is retained as historical
  preparation evidence. The replacement v2 bundle was generated on clean HEAD
  `1e210f681ae257858a33f295b2e7ef118e218e62` after the strengthened mapping
  checks passed against the real server evidence.
- Noise Calibration: locked pending M1 G0 review.
- Main Campaign: locked pending Noise Calibration and applicable gates.
- GPU executions performed by this change: zero.

## Implemented engineering scope

1. C1/C2 fixed at 256/1024 `required_blocks`, with source labels retained only
   as provenance.
2. Calibration band attainment is a non-gating manipulation check; Headroom
   remains explicit and gating.
3. A0-only FLAT/WEAK/RESPONSIVE classification and the 18-pair/38-cell
   populations are fail-closed against the accepted counts.
4. Deterministic stratified Noise selection produces g01/g04/g06/g07/g10 and
   exactly 30 unauthorized A0 runs.
5. Main planning produces the complete 20×2×6 grid and exactly 240
   unauthorized runs.
6. G0 binds the Cohort Seal, 40-run A0 manifest, per-cell config/freeze/trace/
   profile evidence, 40 reports, successful 40-run execution summary,
   formal-to-Native mapping, immutable Native and analysis archives, Protocol
   v4, M1 record, and generated inputs.
7. The Noise evaluator requires the exact frozen Run-ID set and repeats
   `{1,2,3}` for every selected `(group, condition)`, binds all three frozen
   pressure-response strata, retains the Protocol v4 pooled within-cell
   estimator, and reports all stratum sigmas plus an explicit max/min ratio
   status when a denominator is zero.
8. The Main evaluator rejects any deviation from the complete 20×2×6 frozen
   grid. Its FLAT/WEAK/RESPONSIVE effects first average C1/C2 within each Group,
   so Cells are not treated as independent statistical units.
9. Pressure-response classification follows Protocol v4 exactly: every
   `delta_rho < 0.01`, including a negative value, is FLAT.
10. G0 independently verifies the Formal/Native Run-ID bijection, the complete
    calibration 20×2 Cell set, Native run schema/identity/success, and each
    calibration report's schema, A0 identity, status, and Manifest membership.
11. The primary paired population is independently recomputed from the two
    frozen Headroom booleans and must exactly match the frozen 18-Group list.
    Stratum effects use its FLAT/WEAK/RESPONSIVE intersections (3/8/7 Groups),
    while H3-R remains the separate registered 9-Group/16-Cell population.
12. G0 additionally requires 20 unique Cohort Seal Group IDs exactly equal to
    the A0 calibration Manifest Group-ID set.

## Validation state

Targeted Option F, calibration, N/E/C, materializer, and accepted G4 analysis
tests pass (`161 passed, 7 skipped`), including negative tests for
repeat/Run-ID/stratum drift, incomplete or duplicate Main grids, negative
`delta_rho`, malformed report identities, and non-bijective Formal/Native
mappings, paired-population tampering, and altered or duplicate Seal Group IDs.
Full CPU regression on clean implementation HEAD
`4e2f4c325c0e812d66d8a30090631b74194d4a37` passed with
`1918 passed, 15 skipped`; Ruff and `git diff --check` passed.

The v2 G0 artifact was regenerated on the server holding the Cohort Seal, 40
calibration inputs, and v7 reports, without reacquiring tasks or rerunning A0.
Its freeze manifest SHA-256 is
`db9ebb8a388d30f6d9bc1c58a19dd8b97b9ce0a7afdafea124987754fbcde971`;
the external archive SHA-256 is
`ea1a49037543c850471b1e94b1b0cf4b3a67935de097c908fd2552026f53b47a`.
Local archive validation passed. Every generated input remains unauthorized.
It remains immutable historical review evidence. The final implementation
generated and locally validated a v3 bundle exercising the added Seal Group-ID
check. Its core freeze hashes equal v2 because the real Seal and A0 Manifest
identities are consistent; its archive SHA-256 is
`7b3a78c8e582067e6a236885aa91980cf51a77bf2787d774b82733612cd94529`.
Every generated input remains unauthorized. Noise Calibration and the Main
Campaign remain locked until their respective M1 gate decisions.
