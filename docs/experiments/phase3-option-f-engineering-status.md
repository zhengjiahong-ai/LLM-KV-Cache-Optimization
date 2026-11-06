# Phase 3 Option F Engineering Status

## Current state

- M1 design decision: Option F accepted (Issue #98; PR #97).
- Protocol: v4 implemented as an independent document; v3 remains historical.
- Existing A0 calibration: reused, not rerun.
- G0 tooling: implemented; real-server freeze candidate not yet generated.
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
7. Noise and statistical evaluators implement the frozen pooled variance,
   primary Group weighting, per-condition descriptions, H3-0/H3-R, and the two
   interaction populations.

## Validation state

Targeted Option F, calibration, N/E/C, materializer, and accepted G4 analysis
tests pass. Full CPU regression is expected to have one deliberate failure
while the worktree is dirty: the Phase 2E authorization test correctly rejects
an uncommitted tree. It must be rerun after commit on a clean HEAD.

The real G0 artifact must be generated on the server holding the Cohort Seal,
40 calibration inputs, and v7 reports. A mismatch is a stop condition; the
tool does not reacquire tasks or recreate A0 evidence.
