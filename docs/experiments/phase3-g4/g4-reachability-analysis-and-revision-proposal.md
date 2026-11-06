# Phase 3 — G4 Reachability Analysis, Revision Proposal, Downstream Gate Impact

**Author**: M4
**Revision**: RC1–RC10 response to M1's PR #97 reviews (2026-11-05, 2026-11-06)
**Status**: `ANALYSIS_ONLY` — awaiting M1 adjudication. **No GPU execution. No frozen input modified.** Option F is **not approved**.
**Evidence pack**: `local/phase3-g4-reachability-analysis-pack-v1` (created 2026-11-05, git `712b3fc`, `gpu_execution_included: false`)
**Analysis script**: `scripts/probes/phase3_g4_reachability/reachability_analysis.py`
**CPU tests**: `tests/test_g4_reachability_analysis.py` — **87 passed**, no GPU, no network
**Committed outputs**: `docs/experiments/phase3-g4/outputs/` (20 JSON/CSV artifacts + test log + pack manifest)

**Scope boundary honoured**: no second calibration round, no new 40-run configuration, no workload/pool/input change, no noise calibration, no main campaign, iteration-1 evidence untouched, Protocol v3 unmodified, no G4 PASS declared.

---

## 0. Revision log

### 0.1 RC1–RC5 (previous revision, accepted by M1)

| RC | Change | Verdict |
|---|---|---|
| RC1 | Original G4 separated from the §5.2 load target | **Passed** |
| RC2 | Measured vs extrapolated separated; ratio renamed; prediction labels added | **Basically passed** |
| RC3 | Option E re-counted; L_HIGH corrected to 16; 9-vs-10 explained from the file | **Basically passed** |
| RC4 | Option E fully specified: estimands, selection, noise, runs, budget, precision limits | Passed |
| RC5 | Model-based reachability, schema/completeness/uniqueness/SHA-256, CPU tests | Passed |

### 0.2 RC6–RC9 (this revision)

| RC | Problem M1 raised | What changed |
|---|---|---|
| **RC6** | `_band_points()` traversed the whole legal grid, so G4-a's 7/20 could rest on extrapolated pressures | Two-level feasibility is now reported at **three nested evidence levels**. Verdicts renamed away from an unqualified `SUPPORTED`. **The count drops from 7 to 1 measured / 2 interpolated / 4 model-only.** §1.6 |
| RC6 | G4-b only guarded the 16-block floor | G4-b now guards **every** `EXTRAPOLATED` operating point; the floor is treated as the commonest case, not a special one. §2.3 |
| RC6 | Negative extrapolations fed physical metrics | `rho0_at_minimum_blocks` is retained but flagged `physically_valid = false`, and `floor_share_of_low_measurement` is `None` for those 4 groups. §1.5 |
| **RC7** | H3 population contradicted itself across §2.4 / §2.5.2 / §3.2 | **Superseded by RC10-2** (§0.3). The RC7 rule excluded FLAT on a prediction, which M1 rejected. |
| **RC8** | Option A was costed as if new pressures needed no calibration | Option A is charged **2 × cells** new A0 runs. Because only 1 group supports a measured two-level contrast, Option A cannot reach G3-CM at all. §2.4, §2.5.5 |
| RC8 | A′/E operating points not tied to the Headroom condition | Selection now requires `MEASURED` evidence **and** the §3.6 two-condition test; full Group–Load–Pressure map published. §2.5.2 |
| **RC9** | `35cd...` replaced by the observation CSV without explanation | The proposal manifest hash is **restored** as a designated input; the observation CSV is carried as an additional fifth input, not a substitute. §Appendix A |
| RC9 | Reproduction materials incomplete | `pack-provenance.json` (names attached to hashes), committed 40-cell outputs, committed CPU test log. §Appendix A |

Three numbers M1 should re-read against the previous revision:

1. **Two-level support falls from 7 groups to 1 measured + 2 interpolated.** The 4 remaining groups (g03, g05, g10, g19) are model-only.
2. **Option A loses its basis.** It now covers 1 group on measured evidence (or 3 including interpolation), so the 8-decision G3-CM threshold is unreachable by construction.
3. **Option A′ is unchanged at 12 groups**, and every one of its operating points is a measured pressure that already passes Headroom.

### 0.3 RC10 (this revision)

| RC | Problem M1 raised | What changed |
|---|---|---|
| **RC10-1** | §3.4 still cited the round-1 40/40 rejection as current | Round 2 (`phase3-same-batch-physical-qualification-audit-v1`, M6 at `712b3fc`) is now the **current** state: **36 qualified, 4 pending** (g08/g20, both conditions), 40/40 physical prefix equal, **0 evidence failures**. Round 1 is retained as history with its own, different question. §3.4; `outputs/g-e-report.json` |
| **RC10-2** | H3 primary was RESPONSIVE-only and FLAT was excluded on a prediction | **H3-0** is now the primary population (all Headroom-qualified cells, **all strata**, 20 groups / 38 cells). **H3-R** (RESPONSIVE, 9 groups / 16 cells) is a separate pre-registered hypothesis with its own estimand. Strata are descriptive. Group-level weights stated. `h3_report()` no longer derives anything from `paired_groups`. §2.5.4 |
| **RC10-3** | Interaction derived `ΔD ≈ 0` for FLAT from `Δρ` | **Withdrawn.** Two separate analyses: **Interaction-A** over all **18** complete pairs (primary), **Interaction-B** over the **7** RESPONSIVE pairs (heterogeneity). No `Δρ ⇒ ΔD = 0` inference. §2.5.3 |
| **RC10-4** | `F ⊃ E ⊃ A′` | Corrected to **F ⊃ E and F ⊃ A′**; E and A′ are **neither nested nor disjoint** — g03 (C2→C1) and g16 (C1→C2) change operating point. §2.6; `outputs/nesting-report.json` |
| **RC10-5** | “Still 30 runs” used to justify §6.4 compliance | Two readings separated: **decision independence preserved**, **population independence not preserved**. Deterministic hash rule, 2/2/1 stratum allocation, pooled-SD weights and df stated, 4 v4 amendments required. §2.5.5; `outputs/noise-selection-report.json` |
| **RC10-6** | Population described as a 20-group estimate; §5.4 cross-load rule not reconciled | Four explicit levels (campaign 20/40, C1 18, C2 20, paired 18) with a scope warning that the paired primary is **not** a 20-group estimate. v3 **§5.4 is replaced** in the v4 draft by a five-rule pairing/merge section consistent with the group-averaged estimand. §2.5.3, §2.5.6 |
| **RC10-7** | Formal outputs still used L_LOW/L_HIGH; reproduction incomplete | All formal tables use **C1/C2**, with the mapping recorded as provenance. Pack manifest (250 entries) and metadata committed; verification procedure documented; **72 tests** reported. §Appendix A |

Two numbers to re-read against RC1–RC9:

1. **H3's primary is no longer 9 groups.** It is **20 groups / 38 cells** (H3-0), with 9 groups / 16 cells as the separate H3-R.
2. **The interaction is no longer one number.** Interaction-A has 18 pairs and clears the ≥ 8 minimum; Interaction-B has 7 and does not.

### 0.4 Follow-up corrections to RC10

M1 asked for three limited fixes on top of RC10. The H3, interaction and nesting revisions above are
**closed and unchanged**; what follows only corrects how G-E, the noise variance and the evidence
package are described.

| Item | Defect | Fix | Where |
|---|---|---|---|
| **G-E evidence semantics** | `hash_lcp_tokens == native_c` was used as proof that `E == C`; `evidence_failure_count` was a literal `0`; a zero contribution to `Σ(E−C)` was asserted for all 40 pairs | Hash LCP, native C and independently qualified E are now **three separate quantities**. E is summarized on the **36 qualified rows only**; the 4 pending rows keep `PENDING_EARLIER_FORWARD_ORDER_PROOF` with **no established E**. Contribution is *0 tokens over 36 rows* plus `UNDETERMINED_PENDING_QUALIFICATION` on 4 → verdict `PARTIAL_DETERMINATE`. Failures are **counted** from the audit's own list + per-row integrity checks | §3.4 |
| **Noise variance** | "pooled within-cell SD, df 20" with loosely described weights, leaving room to re-specify after the run | **One frozen estimator**; an explicit common-variance assumption with three justifications; target-population stratum weights stated and shown **not** to be the cell weights; stratified outputs required as `DIAGNOSTIC_ONLY`; no-post-run-change clause | §2.5.5 |
| **Evidence delivery** | The 250-entry manifest was presented as if it were delivery of the pack | `raw_pack_transferred_to_m1 = false` is stated; GPU raw evidence / offline audits / derived analysis are classified in `outputs/evidence-inventory.json`; CPU tests are explicitly **not** GPU reproduction | §3.4, `option-f-two-level-fixed-pressure.md` Appendix D |

Two numbers to re-read: **`Σ(E−C)` is determinate on 36 pairs, not 40**, and the noise `σ_run` is a
design-based summary of the sampled cells, **not** a population-weighted variance.

---

## Part I — Three separate measurements

### 1.1 Measurement A: the original Headroom gate and G4 (Protocol v3 §3.6, §9)

Protocol v3 §3.6 freezes one gate: `rho0 >= 5 %` **and** `R0 >= 512 tokens`, evaluated per cell on the independent A0-only load-calibration set. §9 G4 consumes that frozen list; its rule is "cells outside the list do not enter the estimate".

Recomputed from the frozen observation file (the `iteration1_headroom_eligible` flag is not trusted — the script recomputes it from `R0` and `W0` and requires agreement):

| Load | Candidate cells | Eligible | Excluded |
|---|---:|---:|---:|
| L_LOW | 20 | **18** | 2 |
| L_HIGH | 20 | **20** | 0 |
| **Total** | **40** | **38** | **2** |

| Cell | `rho0` | `R0` | Fails |
|---|---:|---:|---|
| g09 L_LOW | 0.0448 | 1,552 | ratio only (4.48 % < 5 %) |
| g18 L_LOW | 0.0000 | 0 | both |

**The original G4 is therefore not what fails.** On the current frozen parameters it would admit 38 of 40 cells. Its status is:

> `G4_ORIGINAL = PENDING_LOAD_PARAMETER_FREEZE` — threshold satisfied on the data that exists (38/40), precondition (frozen load parameters) unmet. **No statement that the original G4 "fails" is supported, and none is made.**

**Crucially, Headroom has only ever been evaluated at 256 and 1024 blocks.** Any design that moves a cell to a different pressure has no Headroom verdict at that pressure — this is the basis of the RC8 recalibration charge in §2.5.5.

### 1.2 Measurement B: the L_LOW / L_HIGH load-calibration target (§5.2)

A different question: did `required_blocks` place `rho0` inside `[0.05, 0.15]` / `[0.25, 0.45]`? Evaluated at three evidence levels on `required_blocks ∈ [16, 2032]`, quantum 16:

| Level | What it means | Cells |
|---|---|---:|
| **Own run measured in band** | the cell's own pressure lands in its band | **8** |
| **Band contains a measured pressure** | 256 or 1024 blocks places `rho0` in that cell's band (own load 8 + 5 at the other load's pressure) | **13** |
| **In bracket** | reachable at a measured or interpolated pressure, i.e. inside `[256, 1024]` | **18** |
| **Full grid** | reachable somewhere legal, requiring extrapolation outside `[256, 1024]` | **23** |

Per load:

| Load | Own run in band | Band contains a measured pressure | Reachable in bracket | Reachable on full grid |
|---|---:|---:|---:|---:|
| L_LOW | **1** (g16) | 1 | 3 | 7 |
| L_HIGH | **7** (g03, g04, g08, g09, g12, g16, g18) | 12 | 15 | 16 |
| **Total cells** | **8** | 13 | 18 | 23 |

The 8 own-run passes match the pack's own `iteration1_target_pass_count: 8`. The 13 count is larger because five L_HIGH cells reach the L_HIGH band at the **other** load's pressure of 256 blocks (g02, g06, g11, g13, g17) — a real fact about the band, but not a pass recorded at iteration 1.

**L_HIGH reachability is 16 groups, not 18** (RC3, retained): g01, g07, g14, g20 cannot reach `[0.25, 0.45]` — **g07 is the group the previous count missed**, its model value at 16 blocks being 0.5200, above the 0.45 ceiling. g15 reaches the band at only 2 grid points, one of which is the 16-block floor.

**L_LOW reachability is 7 groups** on the full grid (g03, g05, g09, g10, g16, g18, g19), but only **3** of those inside the measured bracket (g09, g16, g18) — the other four need a pressure below 256 blocks.

### 1.3 Cell-level classification

| Category | Cells | Which cells |
|---|---:|---|
| **Legal-range infeasibility** (responds, but no legal pressure reaches the band) | **11** | g02 L_LOW, g04 L_LOW, g06 L_LOW, g07 L_LOW, g07 L_HIGH, g08 L_LOW, g11 L_LOW, g12 L_LOW, g13 L_LOW, g15 L_LOW, g17 L_LOW |
| **Pressure-insensitive response** (`Δρ < 0.01`) | **6** | g01 L_LOW/L_HIGH, g14 L_LOW/L_HIGH, g20 L_LOW/L_HIGH |
| **L_LOW / L_HIGH non-discriminability** | **0 at cell level** | a property of a pair; §1.7 |
| **Predicted reachable — measured** | **13** | the band contains a measured pressure (§1.2) |
| **Predicted reachable — interpolated** | **5** | g05 L_HIGH, g09 L_LOW, g10 L_HIGH, g18 L_LOW, g19 L_HIGH |
| **Predicted reachable — extrapolated** | **5** | g03 L_LOW, g05 L_LOW, g10 L_LOW, g15 L_HIGH, g19 L_LOW |
| **Total** | **40** | |

g07 fails **both** bands and is counted once.

### 1.4 Group verdicts

| Verdict | Groups | List |
|---|---:|---|
| **Two-level contrast, both levels measured** | **1** | g16 |
| **Two-level contrast, interpolated** | **2** | g09, g18 |
| **Two-level contrast, model-only** (needs an extrapolated pressure) | **4** | g03, g05, g10, g19 |
| **Both loads resolve to the same proposed pressure** | **10** | g01, g02, g06, g07, g11, g13, g14, g15, g17, g20 |
| **Unavailable** (L_LOW infeasible, no collision) | **3** | g04, g08, g12 |
| **Total** | **20** | |

Pressure-response strata (`Δρ` between the two *measured* points):

| Stratum | Definition | Groups |
|---|---|---:|
| **FLAT** | `Δρ < 0.01` | 3 — g01, g14, g20 |
| **WEAK** | `0.01 ≤ Δρ < 0.10` | 8 — g02, g06, g07, g08, g11, g13, g15, g17 |
| **RESPONSIVE** | `Δρ ≥ 0.10` | 9 — g03, g04, g05, g09, g10, g12, g16, g18, g19 |

### 1.5 Evidence class, and why the "floor" cannot be called measured

| Metric | Value | Class |
|---|---|---|
| `rho0` at 256 / 1024 | the two observations | **MEASURED** |
| `empirical_marginal_response_ratio` | slope between the two observations ÷ 16 | **MEASURED** (a secant over measured points) |
| `rho0_at_minimum_blocks` | the same secant evaluated at 16 blocks | **EXTRAPOLATED**, and *suppressed from ratios when negative* |

Three facts force the relabelling:

1. **The extrapolation distance is large.** 16 blocks is 240 blocks below the lowest measured pressure — the model is asked to run at **6.25 %** of the smallest pressure it was fitted to.
2. **For four groups the extrapolation is physically impossible.** The secant returns a *negative* recomputation ratio: **g09 −0.0743, g16 −0.1022, g18 −0.1357, g19 −0.0401**. A negative rate cannot be measured, so it cannot be called "the pressure-independent recomputation". These values are **retained as diagnostics**, flagged `physically_valid = false`, and **excluded from `floor_share_of_low_measurement` and every other ratio**.
3. **The frozen proposal is two-thirds extrapolation.** 25 of 40 proposed pressures clamp to the 16-block floor and 27 of 40 fall outside `[256, 1024]`.

What survives, restricted to the 16 groups with a valid floor: for the **13 whose floor exceeds the L_LOW ceiling**, the floor accounts for **80.5 %–100 % of the recomputation measured at 256 blocks, median 93.6 %**. This is a **model-conditional** statement. Confirming it directly needs an A0 run at `required_blocks = 16`, which is a new calibration run and is not authorised.

`empirical_marginal_response_ratio` is an **observed slope ratio**, not a claimed fraction of forced releases that cost a block — that interpretation would need per-block eviction evidence the pack does not contain.

| Ratio | Groups |
|---|---|
| exactly 1.00 (within 1 %) | 7 — g03, g04, g06, g07, g08, g09, g12 |
| super-marginal (> 1.15) | 5 — g02 1.31, g05 1.67, g10 1.97, g16 1.96, g19 2.15 |
| 0.90–1.00 | 3 — g11 0.92, g18 0.96, g13 0.99 |
| far below 1 (≤ 0.71) | 5 — g01 0.15, g14 0.00, g20 0.11, g15 0.70, g17 0.65 |

The single decisive datum is **g14**: `R0 = 113,792` and `W0 = 178,200` **identically at 256 and 1024 blocks**. Two measured runs that agree exactly — zero response is measured there, not predicted.

### 1.6 RC6: two-level feasibility by evidence tier

The previous revision reported "7 of 20 groups support a two-level contrast". That number came from a full-grid search, so it silently included groups whose L_LOW level exists only at an unmeasured pressure. Corrected:

| Tier | Groups | List | What the claim is |
|---|---:|---|---|
| **MEASURED** — both bands contain a pressure that was run | **1** | g16 | an experimental result |
| **INTERPOLATED** — both bands reachable inside `[256, 1024]` | **2** | g09, g18 | bounded by the measured endpoints; still a model value |
| **EXTRAPOLATED** — at least one band only outside `[256, 1024]` | **4** | g03, g05, g10, g19 | a model prediction, not support |
| **NONE** | **13** | the remaining groups | no two-level contrast at any legal pressure |

**So the honest headline is: 1 group has a measured two-level contrast; 3 groups have one supportable within the measured bracket; 7 is a model count.** The word `SUPPORTED` is now qualified everywhere (`MEASURED_SUPPORTED`, `INTERPOLATED_SUPPORTED`, `MODEL_ONLY`), and no model-only group is described as experimentally supported.

### 1.7 The 9-versus-10 collision count, resolved from the file

```
unrestricted                                      : 10 -> g01 g02 g06 g07 g11 g13 g14 g15 g17 g20
both rows tagged TARGET_PREDICTED_BELOW_MINIMUM.. :  9 -> g01 g02 g06 g07 g11 g13     g15 g17 g20
only outside the tagged subset                    : g14
  g14 tags: L_LOW=FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE_FROM_ITERATION1
            L_HIGH=FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE_FROM_ITERATION1
```

The difference is **g14**, whose rows carry `FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE` instead of `TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE`. This is read from the frozen file (`collision-report.json`), not inferred. One residual possibility remains that M1 was reading a different field; the script prints both counts and the difference set so the disagreement localises immediately rather than being argued about.

---

## Part II — G4 Revision Proposal

### 2.1 Which assumption is actually violated

| Assumption | Status |
|---|---|
| "`required_blocks` can place `rho0` anywhere in `[0.05, 0.45]`" (§5.2) | **Violated** — unreachable for 13 groups toward the lower band, 4 toward the upper |
| "The Headroom gate can select measurable cells" (§3.6 / G4) | **Not violated** — 38 of 40 on existing data |
| "The two-point linear model is usable at 16 blocks" | **Violated for 4 groups** (negative `rho0`), and unverified for the rest |
| "A model-reachable pressure is a demonstrated level" | **Violated** — 4 of the 7 two-level groups depend on it |

### 2.2 Separating base contention from controlled pressure

| Metric | Definition | Evidence class |
|---|---|---|
| `rho0_measured_at_256` / `_at_1024` | the two observations | **MEASURED** |
| `empirical_marginal_response_ratio` | secant slope ÷ `block_size` | **MEASURED** |
| `rho0_at_minimum_blocks` | same secant at 16 blocks | **EXTRAPOLATED**; suppressed when negative |
| `rho0_pressure = rho0(N) − rho0_at_minimum_blocks` | decomposition | **MODEL-CONDITIONAL** |

### 2.3 Q3: what should change — RC6-compliant gate structure

**The evaluation object, not the thresholds.**

| # | Gate | Criterion | Fails → |
|---|---|---|---|
| **G4-a Level separability** | per group, **tiered** | exists a legal pressure pair ≥ 1 quantum apart that places one level in each frozen band; reported at `MEASURED`, `INTERPOLATED`, `EXTRAPOLATED` | group classified `LEVEL_SEPARATION_UNAVAILABLE` or `MODEL_ONLY`; **retained in the report** |
| **G4-b Placement** | per cell | the chosen pressure places `rho0` in band; **if that pressure is `EXTRAPOLATED` — which includes every 16-block clamp — the cell counts only if its group passes G4-a at `MEASURED` or `INTERPOLATED`** | cell not admitted to the two-level estimand |
| **G4-c Transparency** | per cell | `rho0_at_minimum_blocks` with its `physically_valid` flag, `empirical_marginal_response_ratio`, and `evidence_class` all published | calibration report incomplete |

RC6 is satisfied by the second half of G4-b: the floor is no longer a special case, it is simply the most frequent extrapolated operating point. A negative extrapolation is additionally disqualified from any ratio-based metric.

Rules that keep this from becoming a relaxation:

1. **Bands unchanged** — `[0.05, 0.15]`, `[0.25, 0.45]`, `ρ0 ≥ 5 %`, `R0 ≥ 512`, `≥ 8` decisions all stand.
2. **A model-reached level cannot establish separability**; it may only be an operating point inside a group whose separability is already shown within the bracket.
3. **Collisions dominate.** If both loads resolve to the same pressure there is no contrast, whatever the model says.
4. **Group selection stays blind to algorithm outcomes** — calibration is A0-only; this belongs in G0 so it cannot drift.
5. **The estimand is restated, not silently shrunk** (§2.5.3).

### 2.4 Options, with the RC6 consequence for Option A

| Option | What it does | Groups | New constant | New GPU |
|---|---|---:|---|---|
| **A** | two-level design on the supported groups | **1 measured** / 3 incl. interpolation / 4 model-only | none | **yes — 2 × cells runs** |
| **A′** | one level per group at a **measured** pressure inside a frozen band | **12** | none | no |
| **B** | reselect groups from the 80 unmaterialised candidates | ≤ 20 | new acquisition | **yes — 40-run calibration** |
| **C** | move the pressure axis to KV pool size | — | — | **rejected**: violates the frozen 2048-block pool |
| **D** | decision-level (G3-CM) only, no token estimand | 12–20 | none | no |
| **E** | one level per group with a **new contiguous band `[0.15, 0.45]`** | **15** | **yes, one** | no |
| **F** | **two fixed operating points** (the two executed pressures), band attainment demoted to a manipulation check | **20 groups / 18 pairs** | **none** | **no** |

**Option F is specified separately** in `option-f-two-level-fixed-pressure.md`: it keeps both pressures iteration 1 actually ran and stops treating the designed bands as an admission rule. It is the only option whose every cell was measured at the pressure it will be run at. The cell relation is **F ⊃ E and F ⊃ A′** — but **E and A′ are neither nested nor disjoint**, because they choose different operating points for g03 (C2→C1) and g16 (C1→C2).

**Option A collapses under RC6.** With 1 measured group it produces 1 cell, so G3-CM (which needs ≥ 8 discriminable decisions) is unreachable by construction; with interpolation it reaches 3, still short. Option A is only viable if M1 accepts model-only levels, which is precisely what RC6 forbids. **The previous "Option A costs 114 runs and reuses calibration" was wrong on both counts** — it needs 2 × cells new calibration runs (see §2.5.5).

**Option E's band is not a subset of the frozen design**, and this must be adjudicated explicitly: `[0.15, 0.45]` **adds** `(0.15, 0.25)` and **removes** `[0.05, 0.15]`. Exactly **3 groups** (g05, g10, g19) depend on the added sub-interval, and `15 − 12 = 3` closes the arithmetic. Option E is therefore "**A′ + a new 0.15–0.25 sub-interval**", separable as its own decision.

**Why a single-level design may drop G4-a.** G4-a answers "can pressure move the level?", which is needed only for a claim *about pressure*. A single-level design claims "at this pre-registered operating point, A3 differs from A0/E0 by Δ" — that needs measurability (Headroom, which admits 38/40), not motion. Dropping G4-a is a **claim change, not a threshold change**, and it does not license adding WEAK groups to H3 (§2.5.4).

### 2.5 RC4 + RC8: full specification of A′ and E

#### 2.5.1 Selection rule

| Step | Rule | Frozen before? |
|---|---|---|
| 1 | Pool = the 20 iteration-1 groups | yes |
| 2 | Candidate operating point = a **measured** pressure (256 or 1024) whose `rho0` lies in a frozen band (A′: `[0.05,0.15] ∪ [0.25,0.45]`; E: `[0.15,0.45]`) | must enter G0 |
| 3 | Candidate must pass the §3.6 Headroom two-condition test **at that pressure** | yes (§3.6) |
| 4 | Tie-break: lower `R0`, then lower pressure, then group id | must enter G0 |
| 5 | Groups with no qualifying point drop out | must enter G0 |
| 6 | Selection uses A0 calibration data only; rule + result SHA-256 bound into G0 | holds by construction |

Because step 2 restricts to measured pressures, **the Headroom test has actually been evaluated there** — no group is admitted on an untested operating point.

#### 2.5.2 Group–Load–Pressure map

**Option A′ (12 groups).** Every entry is `MEASURED` and `headroom_eligible = true`.

| Group | Load label | Pressure | `rho0` | `R0` | Band matched |
|---|---|---:|---:|---:|---|
| g02 | L_LOW | 256 | 0.4076 | 32,880 | L_HIGH |
| g03 | L_HIGH | 1024 | 0.3557 | 20,592 | L_HIGH |
| g04 | L_LOW | 256 | 0.2787 | 15,264 | L_HIGH |
| g06 | L_LOW | 256 | 0.4081 | 30,128 | L_HIGH |
| g08 | L_LOW | 256 | 0.3504 | 24,064 | L_HIGH |
| g09 | L_HIGH | 1024 | 0.2949 | 13,840 | L_HIGH |
| g11 | L_LOW | 256 | 0.4121 | 34,240 | L_HIGH |
| g12 | L_LOW | 256 | 0.3349 | 20,736 | L_HIGH |
| g13 | L_LOW | 256 | 0.3927 | 32,896 | L_HIGH |
| g16 | L_LOW | 256 | 0.1070 | 4,240 | L_LOW |
| g17 | L_LOW | 256 | 0.4293 | 39,824 | L_HIGH |
| g18 | L_HIGH | 1024 | 0.2765 | 11,792 | L_HIGH |

**Option E (15 groups)** = the 12 above **plus** the 3 whose only qualifying point lies in the new `(0.15, 0.25)` gap:

| Group | Pressure | `rho0` | `R0` | Why it is E-only |
|---|---:|---:|---:|---|
| g05 | 256 | 0.2316 | 11,920 | in the gap, which no frozen band covers |
| g10 | 256 | 0.2105 | 10,256 | same |
| g19 | 256 | 0.1575 | 6,848 | same |

Under E, two groups' operating points move relative to A′ because the wider band admits a cheaper one: **g03 → 256** (`ρ0 = 0.1821`, in the gap) and **g16 → 1024** (`ρ0 = 0.4444`). Both are still measured and still Headroom-eligible, but the mapping is not identical, and the two designs are therefore not strictly nested cell-for-cell. `option-report.json` carries both maps.

#### 2.5.3 Estimands

| Hypothesis | v3 | A′ (12) | E (15) |
|---|---|---|---|
| **H1** A3 vs A0, token Δ | 40 cells / 2 levels | 12 cells / 1 level | 15 cells / 1 level |
| **H2** A3 vs E0, token Δ | 40 cells | 12 | 15 |
| **H2** decision-level | 40 decisions | 12 | 15 |
| **H3-0** A0 vs N0, all Headroom cells | 40 cells | see §2.5.4 | see §2.5.4 |
| **H3-R** A0 vs N0, RESPONSIVE only | — (new) | 6 groups (below min) | 9 groups |
| Dose-response | supported | **lost** | **lost** |
| Arm × pressure interaction | supported | **lost** | **lost** |

The estimand sentence to freeze:

> "Mean per-request difference in `Σ(E−C)` between arm and A0, for agent-style workloads whose prefill recomputation is at least 5 % of prefill and 512 tokens at a pre-registered, measured operating point in a 2048-block KV pool."

v3's implicit "…at two controlled pressure levels" is gone, and with it any claim of the form "A3 helps more when pressure is high".

**RC10-6: §5.4 must be replaced, not reinterpreted.** v3 §5.4 reads "cross-load 不配对：只做平行报告，不做合并检验", and §6.1 says "两档同 group，不得合并为 40". That remains correct as a ban on pooling *cells*, but it is incompatible with F's group-averaged estimand unless the one permitted merge is written down. The v4 draft therefore replaces §5.4 with five rules:

1. within-cell paired — six arms share one plan SHA-256 per (group, condition);
2. **across conditions, never pool C1 and C2 as independent observations** — they are the same groups, and no interval may come from a pooled C1 ∪ C2 sample;
3. **across conditions, the group-level average is permitted and is F's primary estimand** — a group qualified in both conditions contributes the mean of its two condition deltas at weight 1/2 each, and the group keeps weight 1/G as the resampling unit;
4. per-condition estimates are reported separately and are **not replications** of one quantity;
5. a group qualified in only one condition contributes to that condition's estimate and to H3, but not to the group-averaged estimand.

**Statistical units and weights, stated once (RC10-6).**

| Analysis | Unit | Weight | n |
|---|---|---|---|
| Per-condition Δ | cell | 1 per cell | C1 18, C2 20 |
| **Group-averaged Δ (primary)** | **group** | **1/18**; within-group 1/2 per condition | **18** |
| Stratum Δ | group | 1 / stratum size | 9 / 8 / 3 |
| Interaction-A | group | 1/18 | 18 |
| Interaction-B | group | 1/7 | 7 |
| **H3-0** | **group** | **1/20**; within-group 1/2 per cell | 20 groups / 38 cells |
| H3-R | group | 1/9; within-group 1/2 per cell, one-cell groups get 1 | 9 groups / 16 cells |
| Manipulation check | cell | unweighted count | 40 |

Cell-weighted averaging is deliberately **not** used for any group-level estimand: it would give two-cell groups twice the influence of one-cell groups, making the inference depend on Headroom's per-condition count rather than on the workload pool.

#### 2.5.4 RC10-2: H3 restructured (supersedes the RC7 rule)

The RC7 rule promoted RESPONSIVE to H3's primary population and excluded FLAT because `A0 − N0` was *predicted* to be near zero. **That inference is withdrawn.** A small `Δρ` describes how much **A0's own recomputation** moves with pressure; it says nothing about what a force-release arm does **relative to A0**. Prediction is not a reason to remove a group from a hypothesis.

> **H3-0 (primary, the hypothesis as written):** every Headroom-qualified cell, both conditions, **all strata including FLAT**. 20 groups / 38 cells (C1 18, C2 20). Unit = group, weight 1/20; within a group the two cells are weighted 1/2 each.
>
> **H3-R (separate, pre-registered):** RESPONSIVE only (`Δρ ≥ 0.10`, the same threshold G4-a uses). 9 groups / 16 cells (C1 7, C2 9). Unit = group, weight 1/9; within-group cells 1/2 each, with g09 and g18 contributing one cell at weight 1. It answers a *different* question — is the forced-release cost observable where the baseline itself responds to pressure — and cannot replace H3-0.
>
> **Heterogeneity (pre-registered, descriptive):** WEAK 8 groups / 16 cells, FLAT 3 groups / 6 cells, reported side by side. No stratum gates another.

Because H3 is a per-cell `A0 − N0` comparison it needs no pair, so the two groups that lose their pair to Headroom (g09, g18) still contribute one full cell each. The previous "secondary = paired groups minus FLAT" logic was inconsistent with the per-cell definition and has been removed.

| Design | H3-0 population | H3-R population | A′/E note |
|---|---|---|---|
| **F** | 20 groups / 38 cells | 9 groups / 16 cells | — |
| **A′** | 12 groups / 12 cells | 6 groups | below the §6.2 minimum of 8 → `INSUFFICIENT_ANALYZED_CELLS` if an interval is required |
| **E** | 15 groups / 15 cells | 9 groups | clears the minimum |

Full definition and per-cell accounting: `option-f-two-level-fixed-pressure.md` §5, `outputs/h3-report.json`.

#### 2.5.5 RC8: run accounting and the calibration charge

The 40 executed A0 runs cover exactly two pressures per group (256, 1024). A design that moves a cell elsewhere has **no Headroom verdict there**, so calibration must be charged.

| Design | Cells | A0 calibration | Noise | Main | **Total new** | 8/cells |
|---|---:|---:|---:|---:|---:|---:|
| v3 as written | 40 | 0 | 30 | 240 | **270** | 0.20 |
| **Option A — measured only** | **1** | **2** | 30 | 6 | **38** | 8.00 |
| Option A — incl. interpolation | 3 | 6 | 30 | 18 | **54** | 2.67 |
| Option A — model only | 4 | 8 | 30 | 24 | **62** | 2.00 |
| **Option A′** | **12** | **0** | 27 | 72 | **99** | 0.67 |
| **Option E** | **15** | **0** | 27 | 90 | **117** | 0.53 |
| Option E ∩ G4-a | 9 | 0 | 27 | 54 | **81** | 0.89 |
| Option B | 40 | 40 | 30 | 240 | **310** | 0.20 |

Reading:

- **Option A′ and E reuse the 40 executed runs because they only ever use 256/1024.** No new calibration.
- **Option A needs 2 × cells new runs.** At 1 measured group that is 2 runs but 1 cell — useless. At 4 model-only groups it is 8 runs and 4 cells — still below G3-CM.
- **Option B is the only option needing a full 40-run recalibration.**
- **G3-CM is the binding constraint, not the CI**: 8 of 12 cells must differ (67 %), 8 of 15 (53 %), 8 of 9 (89 %). Repeats do not help — `R` is explicitly not an independent unit (§6.3).
- **GPU-hours are deliberately not quoted.** M6's measured per-run cost (§5.1 item 3) is not available to M4, and inventing one is the kind of number M1 has been rejecting.

**Noise calibration (RC10-5).** §6.4's independence requirement has two readings, and they are not equivalent:

| Reading | A′ / E | F |
|---|---|---|
| **Decision independence** — the noise set must not influence which cells are analysable | preserved | **preserved** (Headroom is decided from A0 calibration before any noise run) |
| **Population independence** — the noise set must be a sample of the full group pool regardless of Headroom | preserved (5 of 12 / 15) | **not preserved** (5 of the 18 paired groups; g09 and g18 are never sampled) |

For a **single-level** design (A′ / E) the v3 30-run design (5 groups × 2 conditions × R=3) cannot be reused as written, because there is only one condition per group: **9 groups × 1 condition × R=3 = 27 runs**, df 18, relative SE of `σ_run` ≈ 16.7 % (v3: df 20, ≈ 15.8 %).

For **F** the 30-run design is retained in shape but two things change and must be frozen.

**Sampling frame.** 5 groups × 2 conditions × R=3, drawn from the **18 paired groups** by a G0-frozen deterministic rule (`sha256("phase3-noise-selection-v1:" + group_id)`, ascending), stratified **2 RESPONSIVE / 2 WEAK / 1 FLAT**. Current draw: g01, g04, g06, g07, g10.

**Variance estimator — one frozen rule (RC10-5 item 2).**

> `σ_run` is the **pooled within-cell SD** of per-run `Σ(E−C)` over the **10 sampled cells** (5 groups × 2 conditions), with **equal weight per cell** and **df = 10 × (3 − 1) = 20**. `σ_δ = √2·σ_run`, `tied = 2√2·σ_run`. No other estimator is permitted for this campaign, and the rule may not be revised once the noise runs exist.

| Assumption | Statement |
|---|---|
| **Common within-cell variance** (homoscedastic) across strata and conditions | adopted |
| Justification 1 | every sampled cell has the same `R = 3`, so the pooled estimator is balanced rather than weighted by unequal cell counts |
| Justification 2 | the design needs **one** absolute `tied` threshold applied uniformly to the paired population; per-stratum thresholds would make "tied" depend on which stratum a cell fell into, and no protocol section defines that |
| Justification 3 | per-stratum estimates would rest on 4 cells (df 4) each — too unstable to freeze as a threshold |

**Weights, stated because they are not population weights.** With a fixed stratified allocation the cell weights are **not** proportional to the population stratum shares: FLAT supplies 2 of 10 cells (20 %) while being 3 of 18 groups (16.7 %). Target-population stratum weights are `RESPONSIVE 7/18`, `WEAK 8/18`, `FLAT 3/18`; the pooled value is a design-based summary of the sampled cells, not a population-weighted variance.

**Stratified results are required, and are diagnostic only.** Report per-stratum `σ_run` and the max/min stratum ratio. The pooled rule stands regardless of that ratio; switching to per-stratum thresholds after seeing the diagnostic would violate S9, so any such switch needs a fresh protocol amendment *before* the run.

`σ_run` therefore estimates the **paired** population, and `tied` applies to it. The interaction gets **no `tied` classification**: its noise floor needs the within-group correlation of the two condition deltas, which is unmeasured → `UNDEFINED_ASSUMPTION`. Four explicit v4 §6.4 amendments follow — see `option-f-two-level-fixed-pressure.md` §7.4.

#### 2.5.6 Statistical precision: planning values, not guarantees

| Design | Groups | Planned CI half-width | vs n=20 |
|---|---:|---:|---:|
| v3 | 20 | ±876 tokens | 1.00× |
| Option E | 15 | ±1,012 tokens | 1.16× |
| **Option A′** | **12** | **±1,132 tokens** | **1.29×** |
| Option E ∩ G4-a | 9 | ±1,307 tokens | 1.49× |
| Option A (measured only) | 1 | ±3,920 tokens | 4.47× |

Limits, stated so they cannot be quoted as precision:

1. **Group SD = 2,000 tokens is an assumption**, inherited from Phase 2E/2G, not measured for Phase 3 or for these 12/15 groups. A more homogeneous selection would narrow the interval — that is a hope, not a guarantee.
2. **A bootstrap CI of a mean has no small-sample coverage guarantee**; at n = 12 the interval is an estimate, and 10,000 resamples control Monte-Carlo error, not sampling error.
3. **A wider interval raises the probability of `NO_DETECTABLE_EFFECT`** for a real but modest effect. That is a loss of sensitivity and must be stated in the report rather than absorbed.
4. **Wilcoxon power scales roughly as `n·d²`** — `d ≥ 0.66` at n = 20, `≈ 0.85` at n = 12, `≈ 0.98` at n = 9. These follow §6.3's own scaling argument and are approximations; §6.3 already declines p-value claims.

### 2.6 Recommendation

| Consideration | Favours |
|---|---|
| No new constant, no band-coverage change | **A′** |
| G3-CM headroom (8/12 = 67 % vs 8/15 = 53 %) | **E** |
| Planned precision (±1,132 vs ±1,012) | **E** |
| H3 primary size (6 for A′, below the §6.2 minimum of 8; 9 for E, above it) | **E** |
| Full-pool population, largest n, cheapest, and the only design without a model-extrapolated operating point | **F** |
| Unambiguous mechanistic claim at a measured level | **A′** |

**Recommended: A′, with E as the pre-authorised fallback — and F preferred instead if the phase's primary claim is the pool-level one.** M1's stated lean matches A′, and RC6 has made the alternative heavier than before: with only 1 measured two-level group, Option A is no longer a serious contender.

The case for E is now stronger on one specific point that the previous revision under-weighted: **A′'s H3 primary is 6 groups, below the protocol's own minimum of 8**, so an H3 interval on A′ would have to be labelled `INSUFFICIENT_ANALYZED_CELLS`. E's primary is 9 and clears it. If M1 weighs H3 as a primary hypothesis rather than a descriptive one, **E becomes the better choice**, at the cost of adjudicating the 0.15–0.25 sub-interval as a new constant.

**Option F changes the shape of this decision rather than sitting beside it.** Because every A′ and E operating point is one of the 40 cells F already contains (**F ⊃ E** and **F ⊃ A′**; note that **E and A′ are not nested in each other** — see `option-f-two-level-fixed-pressure.md` §6.2), choosing F and pre-registering A′ as a frozen subgroup delivers both estimands for the same 270 runs. That relation is one-directional: A′ cannot recover F's estimand. The condition is strict — the subgroup must be defined from A0-only data and frozen in G0, not discovered after seeing an arm (§10 S9). F's own costs are listed in `option-f-two-level-fixed-pressure.md` §6.3: dilution of the pooled estimate, weak manipulation validity (only 1 of 20 groups has both conditions in band), and RESPONSIVE interaction at 7 pairs, below the minimum of 8.

Option A should not be chosen: it cannot satisfy G3-CM without accepting model-only levels. Option B is the statistically cleanest and needs new authorisation. Option C is rejected. Option D remains the fallback if the token estimand is judged unaffordable; its H2 decision-level component survives every design above.

---

## Part III — Downstream Gate Impact

### 3.1 What survives

| Item | Status |
|---|---|
| Evidence layers L1–L4 | **Unaffected** |
| H1, H2 as paired token comparisons | **Valid, narrowed population** (12 or 15 groups) |
| H2 decision-level component | **Intact** and relatively more important |
| G3-CM definition | **Unchanged, harder** — §2.5.5; the binding constraint |
| Noise calibration method | **Independent of G4**, but must be re-specified and re-run |

### 3.2 What loses its basis — and what is only a prediction

| Item | Loss | Why |
|---|---|---|
| **H3 on FLAT groups** | **Not removed; expected to be uninformative** (RC10-2) | Ratios are 0.00–0.15, so `A0 − N0` is *predicted* to be near zero. **No N0 arm has ever been run**, so this is a design prediction the campaign would confirm or refute — not a reason to drop the group. FLAT stays in H3-0 and is additionally reported as its own stratum, because "predicted small" is not "measured zero". |
| **H3 on WEAK groups** | Expected small, retained in H3-0 | ratio 0.65–1.31 leaves real but small leverage; §2.5.4 gives the population and the weights |
| **Dose-response** | **Lost** under A′, E, and F | A′/E have one level; F has two fixed points, not two levels of a manipulated variable, so it cannot express a gradient |
| **Arm × pressure interaction** | **Weakened, not lost** | available under F as Interaction-A (18 pairs, clears the ≥ 8 minimum) and Interaction-B (7 RESPONSIVE pairs, does not). Unavailable under A′ and E. |
| **"A3 helps more when pressure is high"** | **Unavailable** | C1/C2 are not levels of one variable for 11 groups, so the contrast cannot be read as pressure intensity |
| **Generalisation of token-delta magnitude** | **Weakened** | under A′/E it covers in-band workloads only; under F it is a population average over the paired groups, which is not an effect size |
| **Two-level contrast on 4 further groups** | **Demoted to model-only** | RC6: their level exists only at an unmeasured pressure |

### 3.3 What must stay locked until G4 is re-approved

| Item | State |
|---|---|
| Second GPU calibration round | **LOCKED** |
| Noise calibration | **LOCKED** — must be re-specified over the final population, then run |
| Main campaign | **LOCKED** |
| Protocol v3 | **UNMODIFIED** |
| G4 verdict | **NOT PASSED, NOT FAILED BY ITS OWN THRESHOLD** — `PENDING_LOAD_PARAMETER_FREEZE` (§1.1) |
| Frozen workload, 2048-block pool, iteration-1 evidence | **UNCHANGED** |

### 3.4 A separate item that must not be folded into G4

**Current state (round 2, M6 recompute at `712b3fc`).** `phase3-same-batch-physical-qualification-audit-v1` asks whether producer and consumer resolve the same **physical prefix blocks** under a bound forward-batch source:

```
row_count: 40
QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR : 36
PENDING_EARLIER_FORWARD_ORDER_PROOF     :  4   (g08 C1, g08 C2, g20 C1, g20 C2)
```

**Three quantities, reported separately (RC10-1 fix).**

| Quantity | Rows | Token values | What it is |
|---|---:|---|---|
| `hash_lcp_tokens` | 40 | `[112]` | prefix shared by content hash — **not** an eligibility test |
| `native_c` | 40 | `[112]` | native prefix computed by the engine — **not** E |
| `independently_qualified_e` | **36** | `[112]` | E as established by the qualification procedure; **undefined on the 4 pending rows** |

The previous revision used `hash_lcp_tokens == native_c` as proof that `E == C` across all 40
pairs and hardcoded `evidence_failure_count = 0`. Both are withdrawn. Physical prefix equality is
**necessary but not sufficient** for eligibility: it still needs the forward-order proof. On a
`PENDING_EARLIER_FORWARD_ORDER_PROOF` row `independent_e` is null, so **E is not established** —
neither equality nor a conservative zero may be asserted there.

**Primary metric.** `Σ(E−C)` is judged only where the audit qualified the pair *and* produced E:

| State | Rows | Contribution |
|---|---:|---|
| Qualified with E == native C | **36** | **0 tokens** |
| Qualified with E ≠ native C | 0 | — (would be reported non-zero and would trigger a contradiction) |
| Pending | **4** | `UNDETERMINED_PENDING_QUALIFICATION` |

Overall verdict: **`PARTIAL_DETERMINATE`** — determinate on 36 pairs, undetermined on 4.

**Evidence failures are counted, not assumed.** `recorded_failure_records` is the length of the
audit's own `evidence-failures.json` (0 entries); `rows_failing_integrity_checks` is computed per
row from the invariant columns (prefix completeness/equality, block-id equality, hash
function/process match, `required_shared_blocks == hash_lcp_blocks`, token fields present). Current
total: **0 + 0 = 0**. Any non-zero value raises a contradiction and is surfaced, not absorbed.

**History (round 1, retained).** `phase3-concurrent-eligibility-rejection-audit-v1` asked a
*different* question — is the producer's prefill **complete and visible** before a same-wave
consumer looks it up — and failed closed:

```
audit_row_count: 40, qualified_count: 0, rejected_count: 40
status: FAIL_CLOSED
uses_c_to_compute_e: false
independently_qualified_e: 0   (all 40 rows)
qualification_result: REJECTED_SAME_WAVE_PREFILL_NOT_COMPLETE_BEFORE_CONSUMER_LOOKUP  (40/40)
```

**The two rounds are not a correction of one another.** Round 1 is about visibility and completion
timing; round 2 is about physical block identity and forward-batch binding, and additionally
requires the forward-order proof before a pair counts as eligible. A pair can bind the same
physical prefix while still failing round 1, and a pair can bind the same physical prefix while
still being pending the order proof. **"40/40 rejected" is therefore no longer a correct
description of the current state**, even though no round-1 row changed.

What does not change either way: `uses_c_to_compute_e: false` in both rounds, so §3.2's
arm-independence requirement on `E` is not violated — which is a separate claim from whether an
`E` value exists for a given pair. The audit covers **one pair per cell**, so the remaining request
pairs are unverified in either round.

**G-E is independent of G4.** It must neither block nor be blocked by the design decision. Full
record: `outputs/g-e-report.json`.

### 3.5 Recommendation to M1

1. **Record G4 as `PENDING_LOAD_PARAMETER_FREEZE`.** Threshold satisfied on existing data (38/40); precondition unmet. Record the §5.2 load-target failure separately: `LEVEL_SEPARATION_UNAVAILABLE` for 13 groups, `MODEL_ONLY` for 4.
2. **Adopt G4-a (tiered) / G4-b (generalized) / G4-c**, bands unchanged, extrapolation labelled, negative extrapolations excluded from ratios.
3. **Choose the design.** Recommended **A′**; **E** if H3-R size matters more than the band-coverage change; **F** if the phase's primary claim is the pool-level one (it is the only option that can also deliver A′ as a pre-registered subgroup, since F ⊃ E and F ⊃ A′ — see `option-f-two-level-fixed-pressure.md`); **A** no longer viable; **B** needs new authorisation; **C** rejected; **D** the fallback.
4. **Re-specify and re-run the noise calibration** before the main campaign: 9 × 1 × R=3 = 27 runs for a single-level design; 5 × 2 × 3 = 30 runs under F with the paired-group sampling rule of §2.5.5.
5. **Restate the estimand**, including the loss of dose-response and the qualification of two-level claims.
6. **Adjudicate G-E separately**, on round 2's evidence (36 qualified / 4 pending), not on round 1's 40/40 rejection.

---

## Part IV — What I am explicitly not proposing

- Not proposing new bands as *inherited* constants: the one new interval is named, quantified (3 groups) and offered for adjudication.
- Not proposing to relax any threshold.
- Not proposing to re-run the 40-cell calibration with different parameters, or any new calibration.
- Not proposing to touch the 2048-block pool, the frozen workload, or iteration-1 evidence.
- Not proposing to declare G4 PASS — and no longer claiming it fails by its own threshold.
- Not proposing to modify Protocol v3.
- Not proposing to treat a model-reached pressure as a demonstrated level.

---

## Appendix A — Reproducibility (RC5, RC9)

```bash
python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
    --pack local/phase3-g4-reachability-analysis-pack-v1 \
    --out  docs/experiments/phase3-g4/outputs

python -m pytest tests/test_g4_reachability_analysis.py -q
```

### A.1 Frozen inputs, with file names attached to each hash

| File | SHA-256 | Designated by M1 |
|---|---|---|
| `iteration1-cell-observations.json` | `a47acef4a96cbedec37d88c941c70a8ed30f3208d7cac8ec1d599acb6d876d5a` | **yes** |
| `iteration2-required-blocks-proposal.json` | `1b59758a7ef8b5d0b42c4431fa0d2983d27062bf5d89c4a0b4b01175ff3c36a8` | **yes** |
| `iteration2-required-blocks-proposal.csv` | `49738f3715a945038c566f2260eb50053b7fb68760e8ac5b60bcc9bb112d8a36` | **yes** |
| `sha256-manifest-iteration2-proposal.txt` | `35cd5eead7706a29006a423bfe7be5141a91b96b9fd3c0933d615d9cd3a0bf99` | **yes** |
| `iteration1-cell-observations.csv` | `2fb77aae8dd734860e7a3664f724fad2113db263ea63f806656abad4975179ec` | additional (cross-check) |

**RC9 explained.** The previous revision had replaced the M1-designated proposal manifest (`35cd...`) with the observation CSV. That substitution was not justified and is reverted: **all four designated inputs are now pinned**, and the observation CSV is carried as a **fifth** input so the JSON and CSV views can disagree loudly. Each hash is cross-checked against `sha256-manifest.txt`, and the proposal's own `source_observations_sha256` must bind the pinned observation hash.

### A.2 Where the evidence pack lives

| Item | Value |
|---|---|
| Path | `local/phase3-g4-reachability-analysis-pack-v1/` |
| Tracked by git | **no** — `local/` is gitignored by repository policy |
| Size | 260 files, 209.4 MiB |
| Integrity | the pack ships its own `sha256-manifest.txt` (250 entries) |
| Provenance | M1-provided read-only bundle, `created_at_utc 2026-11-05T12:28:20Z`, git `712b3fc`, `gpu_execution_included: false` |

Because the pack is 209 MiB and untracked, **the derived artifacts are committed instead** (`docs/experiments/phase3-g4/outputs/`), together with the exact input hashes above, so every number in this document can be checked against a file in the repository. `pack-provenance.json` records all five paths and hashes.

### A.3 Committed 40-cell analysis output

`docs/experiments/phase3-g4/outputs/` contains:

| File | Content |
|---|---|
| `cell-classification.json` / `cells.csv` | all 40 cells with classification, evidence class and Headroom status |
| `group-summary.json` / `groups.csv` | all 20 groups with the three feasibility tiers |
| `headroom-report.json` | §3.6 gate: 38/40 eligible, the 2 exclusions |
| `load-target-report.json` | §5.2 target at measured / bracket / full-grid levels |
| `option-report.json` | A′ and E operating-point maps, group counts, F design block |
| `option-f-report.json` | F: manipulation check, four populations, estimands, precision, interaction A/B, threats |
| `h3-report.json` | H3-0 primary, H3-R separate hypothesis, WEAK/FLAT heterogeneity |
| `noise-selection-report.json` | §6.4 independence reading, frozen selection rule, variance and weights, 4 v4 amendments |
| `nesting-report.json` | F ⊃ E, F ⊃ A′, and the g03/g16 operating-point moves |
| `g-e-report.json` | round 2 as current (36 qualified / 4 pending, E established on 36 only), round 1 as history, evidence-failure derivation, contradiction list |
| `evidence-inventory.json` | which directories are GPU raw evidence, which are offline audits, which are derived; delivery status |
| `calibration-cost-report.json` | run accounting per design, incl. Option A's calibration charge |
| `collision-report.json` | the 9-vs-10 counts and the difference set |
| `precision-report.json` | planning half-widths with their caveat |
| `pack-provenance.json` | pack path, file count, five inputs with hashes |
| `pack-sha256-manifest.txt` / `pack-metadata.json` | the pack's own 250-entry manifest and metadata, for verifying a transfer |
| `cpu-test-run.txt` | actual pytest run |

### A.4 CPU test results (RC10-7)

`pytest tests/test_g4_reachability_analysis.py -q` → **87 passed**, no GPU, no network, no writes outside `tmp_path`. The committed log is `outputs/cpu-test-run.txt`.

This **supersedes the 72 figure** quoted before this revision; the G-E semantics, noise-variance
rule and evidence-inventory changes added 15 tests.

Coverage of the RC items:

| Area | Tests |
|---|---:|
| Schema rejection (cell count, duplicates, `rho0 ≠ R0/W0`, headroom flag, group count, pressure range/quantum, band equality, source binding, method constants) | 9 |
| SHA-256 integrity (missing input, pin mismatch, manifest disagreement, clean pack) | 4 |
| Model reproduction of a frozen `predicted_rho0`; evidence-class labelling; 1:1 ratio | 3 |
| Cell classifications (measured / interpolated / extrapolated / infeasible) | 4 |
| **RC6** — extrapolated operating point rejected without in-bracket feasibility; admitted with it; model-only labelled; measured vs interpolated distinguished; negative floor flagged and excluded from share | 6 |
| **RC10-2** — H3-0 keeps FLAT; FLAT is a stratum not an exclusion; H3-R separate with its own estimand; per-condition counts; group-vs-cell weighting; H3 independent of the paired set; per-design populations | 7 |
| **RC10-3** — interaction A/B separated; no `Δρ ⇒ ΔD = 0` inference; “by construction” absent | 3 |
| **RC10-1** — round 2 current (36/4, 0 failures, E==C) **only on qualified rows**, round 1 retained as history, pending/missing/contradictory evidence cases | 12 |
| **RC10-5** — single frozen variance estimator, common-variance justification, stratum weights, diagnostic-only status | 2 |
| **evidence inventory** — GPU raw vs offline audit vs derived separation, delivery status, synthetic classification | 2 |
| **RC10-4** — F ⊃ E and F ⊃ A′; E and A′ not nested; g03/g16 move | 1 |
| **RC10-5** — decision vs population independence; allocation; determinism; df; 4 amendments | 1 |
| **RC8** — Option A calibration = 2 × cells, A′/E = 0, B = 40; run totals add up; operating points measured and Headroom-eligible | 4 |
| **RC9** — the M1-designated four are pinned; `35cd...` not replaced | 2 |
| Collision counting (9-vs-10); option additivity; precision table | 3 |
| End-to-end against the real pack (1 measured / 3 in-bracket / 7 model-only; g14 identity; F's 18 pairs; 4 population levels; nesting; noise; G-E) | 4 |
| Inputs / helpers / cross-checks (remainder) | 22 |

### A.5 Schema and completeness checks enforced before any number is computed

| Check | Failure it catches |
|---|---|
| `cell_count == 40` in both documents | truncated export |
| exactly 20 distinct groups, 2 loads each | missing group silently shrinking n |
| `(group, load)` unique in both files | duplicated cell inflating a rate |
| `rho0 == R0/W0` within 1e-9 | hand-edited ratio |
| `iteration1_headroom_eligible` recomputed and compared | a stale flag contradicting §3.6 |
| `original_required_blocks` equals 256/1024 | a silently re-parameterised iteration 1 |
| proposed pressure on `[16, 2032]`, on the 16-block quantum | off-grid extrapolation |
| proposal band equals the frozen band for that load | a band changed in the data instead of the protocol |
| proposal `source_observations_sha256` == pinned observation hash | inputs from different runs |
| two-point model reproduces every frozen `predicted_rho0` to 1e-9 | model drift between M4 and the frozen proposal |

## Appendix B — Threshold provenance

| Threshold | Value | Provenance |
|---|---:|---|
| `block_size` | 16 tokens | frozen runtime config |
| `minimum_blocks` / `maximum_blocks` / `quantum` | 16 / 2032 / 16 | frozen proposal `method`, re-validated |
| L_LOW / L_HIGH bands | `[0.05,0.15]` / `[0.25,0.45]` | Protocol v3 §5.2, frozen |
| Headroom ratio / absolute | 5 % / 512 tokens | Protocol v3 §3.6, frozen |
| G3-CM discriminable decisions | ≥ 8 | Protocol v3 §9, frozen |
| Minimum analysable cells per load | 8 | Protocol v3 §6.2, frozen |
| `tied` | `2√2·σ_run` | Protocol v3 §6.4, unchanged |
| FLAT | `Δρ < 0.01` | below the design's block granularity at observed prefill sizes |
| WEAK / RESPONSIVE split | `Δρ < 0.10` | the gap between the L_LOW ceiling and the L_HIGH floor; below it no band crossing is possible. Reused for **H3-R** (and for G4-a) so no new constant is introduced |
| Option E band | `[0.15, 0.45]` | **proposed, not inherited** — covers 0.15–0.25, which no frozen band covers; 3 groups depend on it |
| Noise selection salt | `phase3-noise-selection-v1` | **proposed** pre-registration constant; allocation 2/2/1 follows the paired strata |
| Planning group SD | 2,000 tokens | Phase 2E/2G observation, planning only |

## Appendix C — RC response map

| RC | Where answered |
|---|---|
| RC6 model vs evidence reachability | §1.6, §2.3, §2.4, §2.5.2 |
| RC6 G4-b generalized to all extrapolated points | §2.3 |
| RC6 negative extrapolations excluded from physical metrics | §1.5, Appendix A §A.4 |
| RC7 unified H3 estimand | **superseded by RC10-2** — §2.5.4, §3.2 |
| RC8 Option A calibration charge, Headroom intersection, full mapping | §2.5.1, §2.5.2, §2.5.5 |
| RC9 hashes with names, pack location, 40-cell output, test result | Appendix A |
| **RC10-1** G-E current state | §0.3, §3.4, `outputs/g-e-report.json` |
| **RC10-2** H3-0 / H3-R / heterogeneity, units and weights | §0.3, §2.5.4, §3.2, `outputs/h3-report.json` |
| **RC10-3** interaction A vs B | §0.3, §2.5.3, `option-f-two-level-fixed-pressure.md` §4.4 |
| **RC10-4** nesting corrected | §0.3, §2.6, `outputs/nesting-report.json` |
| **RC10-5** noise rule closed | §0.3, §2.5.5, `outputs/noise-selection-report.json` |
| **RC10-6** §5.4 replaced, four populations, units and weights | §0.3, §2.5.3, `option-f-two-level-fixed-pressure.md` §3.2 / §8.4 |
| **RC10-7** C1/C2 naming, outputs, 87 tests, pack transfer | §0.3, Appendix A, `option-f-two-level-fixed-pressure.md` Appendix D |
| **G-E semantics fix** hash LCP / native C / qualified E separated; pending rows keep no E; failures counted | §0.4, §3.4, `outputs/g-e-report.json` |
| **Noise variance fix** one frozen estimator, common-variance justification, stratum weights, diagnostic-only | §0.4, §2.5.5, `outputs/noise-selection-report.json` |
| **Evidence delivery fix** raw pack not delivered, GPU vs offline vs derived classification | §0.4, `outputs/evidence-inventory.json`, `option-f-two-level-fixed-pressure.md` Appendix D |
