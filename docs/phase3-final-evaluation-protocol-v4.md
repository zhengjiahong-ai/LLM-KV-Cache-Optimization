# Phase 3 Final Evaluation Protocol v4 — Option F

**Status:** G0 freeze candidate; no GPU execution is authorized by this file.  
**Decision:** M1 final ruling, Issue #98; design evidence in PR #97.  
**Supersession:** Protocol v3 remains an immutable historical protocol. This is
the independent v4 protocol for the final campaign.

## 1. Research objective and invariants

Phase 3 compares N0, A0, A1, A2, A3, and E0 on the sealed 20-group Agent
cohort. The primary metric remains aggregate recomputed tokens, `Σ(E-C)`. N,
E, and C retain their independent definitions; E must never be completed from
C. The model, tokenizer, 2048-block KV pool, 16-token block size, request
order, replay timeline, profile, explicit token IDs, and pressure token IDs are
arm-invariant.

The statistical unit is the Workload Group. A condition is never treated as an
independent group. Missing evidence fails closed and may not be imputed from a
different arm, condition, or run.

## 2. Fixed operating points

The campaign uses exactly the two operating points already measured by the
iteration-1 A0 calibration:

| Condition | Provenance label | `required_blocks` | KV pool |
|---|---|---:|---:|
| C1 | `L_LOW` (input provenance only) | 256 | 2048 |
| C2 | `L_HIGH` (input provenance only) | 1024 | 2048 |

Formal outputs call these conditions **C1** and **C2**. They must not be
renamed “low pressure” and “high pressure”. The historical labels remain only
to trace the existing A0 input and evidence files.

The designed rho bands `[0.05, 0.15]` and `[0.25, 0.45]` are a non-gating
manipulation check. Every one of the 40 cells remains in the execution grid,
regardless of band attainment. No group or cell may be selected after observing
another arm.

## 3. Headroom and pressure-response strata

Headroom remains a strict eligibility rule per cell:

- `rho0 >= 0.05`; and
- `R0 >= 512` recomputed tokens.

The frozen A0 evidence yields C1 18/20, C2 20/20, and 38/40 qualified cells.
The complete paired population therefore contains 18 Groups. g09/C1 and
g18/C1 remain executed and reported but are excluded wherever the estimand
requires C1 Headroom.

Pressure-response strata are computed exclusively from the two measured A0
rho values before any six-arm run:

- FLAT: `Δrho < 0.01`;
- WEAK: `0.01 <= Δrho < 0.10`;
- RESPONSIVE: `Δrho >= 0.10`.

The frozen counts are FLAT 3, WEAK 8, RESPONSIVE 9. Strata are reporting and
pre-registered subgroup metadata, not a mechanism for discarding groups.

## 4. Pairing and merge rules

1. Within a `(group, condition)` cell, all six arms share the same request,
   trace, timeline, pressure, profile, model, and plan bindings.
2. C1 and C2 are repeated conditions on the same Group. They are never pooled
   as independent observations.
3. The primary arm-minus-A0 delta first averages C1/C2 with weight 1/2 inside
   each complete Group and then averages 18 Group values with weight 1/18.
4. C1 and C2 descriptive estimates use their own Headroom-qualified cells:
   C1 `n=18`, C2 `n=20`.
5. A Group qualified in only one condition contributes to that condition’s
   estimate and to applicable H3 analyses, but not to the paired primary.

Missing data may not change these populations or weights. Resampling, when
used, is by Group rather than by cell.

## 5. Registered estimands

### 5.1 Primary arm effects

For each non-A0 arm, compute `arm - A0` within each condition. For the 18
complete Groups, average the two condition deltas inside Group and average the
18 Group values. Each Group has weight 1/18 and each condition weight 1/2.

Report the C1 (`n=18`) and C2 (`n=20`) estimates separately as descriptive
operating-point results. Report FLAT, WEAK, and RESPONSIVE estimates as
pre-registered heterogeneity outputs.

### 5.2 H3

**H3-0** is `A0 - N0` over every Headroom-qualified cell: 20 Groups and 38
cells. Each Group has weight 1/20; a two-cell Group weights each cell 1/2, and
a one-cell Group gives that cell weight 1. FLAT is included.

**H3-R** is the same contrast over the 9 RESPONSIVE Groups and 16 qualified
cells. It is a separate hypothesis, not a replacement for H3-0.

### 5.3 Interactions

**Interaction-A** uses all 18 complete pairs and is the primary interaction
analysis. **Interaction-B** uses the 7 complete RESPONSIVE pairs and is a
heterogeneity diagnostic. Because 7 is below the registered minimum of 8,
Interaction-B must report `N_analyzed=7` and must not issue a verdict.

Delta-rho is A0-only manipulation evidence and must not be used to infer an
arm-vs-A0 interaction.

## 6. Noise calibration

The candidate set is the 18 complete paired Groups. Within each frozen stratum,
sort ascending by:

`SHA-256("phase3-noise-selection-v1:<group_id>")`.

Take RESPONSIVE 2, WEAK 2, and FLAT 1. The frozen selection is g01, g04, g06,
g07, and g10. Both conditions are run with A0 at three repeats:

`5 Groups × 2 conditions × 3 repeats = 30 runs`.

The sole campaign estimator is the pooled within-cell standard deviation of
`Σ(E-C)` over the ten sampled cells. Cells have equal weight and
`df = 10 × (3-1) = 20`.

- `sigma_delta = sqrt(2) × sigma_run`;
- `tied = 2 × sqrt(2) × sigma_run`.

Per-stratum sigma values and their max/min ratio are `DIAGNOSTIC_ONLY`. They
cannot replace the pooled estimator after observing results. The interaction
has no tied classification because the required within-Group cross-condition
correlation is not measured.

## 7. Execution grid and budget

- Existing A0 load calibration: 40 runs, reused; no rerun.
- Noise calibration: 30 new A0 runs.
- Main campaign: `20 Groups × 2 conditions × 6 arms = 240` new runs.
- Total new budget: 270 runs.

All generated inputs remain `execution_authorized=false` through G0 review.
Noise execution requires M1 acceptance of G0. Main execution additionally
requires completion of Noise Calibration, a frozen tied threshold, and every
applicable G1/G2/G3-CM/G4 condition.

## 8. Gates

### G0 — Freeze

Before Noise Calibration, bind with SHA-256:

- final Cohort Seal and 40 tasks/20 Groups/repository coverage;
- C1/C2 identities and the complete six-arm grid;
- existing 40-run A0 manifest, all per-run reports, frozen inputs, traces,
  profiles, configurations, and evidence hashes;
- Headroom list, A0-only strata, manipulation-check values, and the registered
  subgroup estimators;
- noise salt, candidate population, allocation, selected Groups, repeats, and
  variance estimator;
- unauthorized 30-run and 240-run input manifests.

A binding mismatch, missing file, cohort mismatch, or unregistered inventory
file fails G0 closed. It does not authorize reacquisition, replacement, or an
A0 calibration rerun.

### G1/G2/G3-CM/G4

G1 isolation, G2 branch composition, and G3-CM retain their v3 meanings.
G3-CM requires at least 8 discriminable decisions among 40 available
decisions. G4 is Headroom only. G4-M reports band attainment, delta-rho, and
strata but is never an admission gate.

## 9. Reporting constraints (S10)

- Report all 20 Groups/40 cells, plus the 18-Group/36-cell primary population.
- Never relabel C1/C2 as low/high pressure.
- Never analyse C1 and C2 as independent Group samples.
- Never extract a favourable subgroup after seeing arm outcomes.
- Never infer an arm interaction from A0 delta-rho.
- Report absent E, missing evidence, insufficient sample size, or an
  unestablished physical claim explicitly; never convert it to PASS.

## 10. Frozen implementation mapping

- `phase3_load_calibration.py`: evidence-valid A0 evaluation plus non-gating
  manipulation-check status and strict Headroom.
- `phase3_option_f.py`: classification, G0 evidence binding, deterministic
  Noise selection, unauthorized run materialization, noise estimator, and
  registered statistical populations.
- `phase3_materialize.py`: unchanged six-arm policy bindings and fixed pressure
  request identity.
- `phase3_nec.py`: independent N/E/C evaluation and physical identity proof.

The accepted M4 design and reachability evidence remain in
`docs/experiments/phase3-g4/`. This protocol freezes their approved Option F
semantics into the executable Phase 3 contract.
