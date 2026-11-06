# Phase 3 Option F Engineering Status

## Current state

- M1 design decision: Option F accepted (Issue #98; PR #97).
- Protocol: v4 implemented as an independent document; v3 remains historical.
- Existing A0 calibration: reused, not rerun.
- G0 tooling: implemented. The v1 review bundle is retained as historical
  preparation evidence; a replacement bundle must be generated on the final
  PR HEAD after the strengthened mapping checks below pass against the server
  evidence.
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

## Validation state

Targeted Option F, calibration, N/E/C, materializer, and accepted G4 analysis
tests pass, including negative tests for repeat/Run-ID/stratum drift, incomplete
or duplicate Main grids, negative `delta_rho`, malformed report identities,
and non-bijective Formal/Native mappings. Full CPU regression must be rerun on
the final clean HEAD; the Phase 2E authorization test intentionally rejects an
uncommitted tree.

The historical v1 G0 artifact was generated on the server holding the Cohort
Seal, 40 calibration inputs, and v7 reports. Its inputs remain unauthorized,
but its hashes predate the final mapping validation and therefore are not the
final PR review evidence. Regeneration must reuse the immutable source evidence
without reacquiring tasks or rerunning A0. Noise Calibration and the Main
Campaign remain locked until their respective M1 gate decisions.
