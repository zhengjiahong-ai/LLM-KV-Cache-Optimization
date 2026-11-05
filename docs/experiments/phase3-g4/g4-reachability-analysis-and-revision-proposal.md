# Phase 3 — G4 Reachability Analysis, G4 Revision Proposal, Downstream Gate Impact

**Author**: M4
**Status**: `ANALYSIS_ONLY` — awaiting M1 adjudication. **No GPU execution.** No frozen input modified.
**Evidence pack**: `local/phase3-g4-reachability-analysis-pack-v1` (created 2026-11-05, git `712b3fb`, `gpu_execution_included: false`)
**Analysis script**: `scripts/probes/phase3_g4_reachability/reachability_analysis.py` (read-only, reproducible)
**Scope boundary honoured**: no second calibration round, no new 40-run configuration, no workload/pool/input change, no noise calibration, no main campaign, iteration-1 data untouched, Protocol v3 unmodified, no G4 PASS declared.

> **Headline.** The G4 load target is not reachable for 13 of 20 groups, and the cause is structural rather than parametric: for those groups **80.5 %–100 % of measured recomputation is independent of controlled pressure** (median 93.7 %). At the minimum legal pressure (16 blocks) the metric still sits at 0.22–0.64, far above the L_LOW ceiling of 0.15. `required_blocks` therefore cannot place those cells into the L_LOW band at any legal setting. This is a property of the frozen workload against a 2048-block pool, not a defect in the harness and not a tuning shortfall.

---

## Part I — Reachability Analysis

### 1.1 What the iteration-1 data actually contains

40 A0-only Native runs succeeded (`40_OF_40_SUCCESS`, zero evidence failures), covering 20 groups × two pressure settings:

| Load | `required_blocks` | Purpose in Protocol v3 |
|---|---:|---|
| L_LOW | 256 | target `rho0 ∈ [0.05, 0.15]` |
| L_HIGH | 1024 | target `rho0 ∈ [0.25, 0.45]` |

Legal parameter range: `required_blocks ∈ [16, 2032]`, quantum 16 blocks, `block_size = 16` tokens, KV pool 2048 blocks.

Only **8 of 40 cells** landed in band (1 L_LOW cell, 7 L_HIGH cells), consistent with `iteration1_target_pass_count: 8`.

### 1.2 The two quantities that separate pressure from base contention

Both are computable from the two measured points per group, with no new run:

**Slope** — `dR0 / d(required_blocks)`, in tokens of recompute per block of pressure.

The mechanically expected value is exactly one block of recompute per block of forced pressure, i.e. **16 tokens/block**. So `slope / 16` is the **marginality ratio**: the fraction of forced releases that cost a block that would not otherwise have been evicted. A ratio near 0 means the forced release is free — the block was going to be evicted anyway.

**Pressure-independent floor** — `rho0` extrapolated to the minimum legal pressure (16 blocks), which is the value the iteration-2 proposal already publishes as `predicted_rho0` on clamped rows. This is the recomputation the frozen workload incurs with controlled pressure essentially switched off.

### 1.3 Group-level measurements

| Group | `rho0`@256 | `rho0`@1024 | Δρ | slope (tok/blk) | marginality | floor | floor share of `rho0`@256 | proposed L_LOW / L_HIGH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| g01 | 0.5531 | 0.5589 | 0.0058 | 2.38 | 0.15 | 0.5513 | **99.7 %** | 16 / 16 |
| g02 | 0.4076 | 0.5061 | 0.0985 | 20.96 | 1.31 | 0.3682 | **90.3 %** | 16 / 16 |
| g03 | 0.1821 | 0.3557 | 0.1736 | 16.00 | 1.00 | 0.1069 | 58.7 % | 16 / 1024 |
| g04 | 0.2787 | 0.4108 | 0.1322 | 16.00 | 1.00 | 0.2243 | **80.5 %** | 16 / 1024 |
| g05 | 0.2316 | 0.4504 | 0.2187 | 26.67 | 1.67 | 0.1225 | 52.9 % | 16 / 608 |
| g06 | 0.4081 | 0.4926 | 0.0845 | 16.00 | 1.00 | 0.3756 | **92.0 %** | 16 / 16 |
| g07 | 0.5373 | 0.5852 | 0.0479 | 16.00 | 1.00 | 0.5200 | **96.8 %** | 16 / 16 |
| g08 | 0.3504 | 0.4490 | 0.0986 | 16.00 | 1.00 | 0.3119 | **89.0 %** | 16 / 1024 |
| g09 | 0.0448 | 0.2949 | 0.2501 | 16.00 | 1.00 | — | — | 384 / 1024 |
| g10 | 0.2105 | 0.4727 | 0.2622 | 31.54 | 1.97 | — | — | 64 / 592 |
| g11 | 0.4121 | 0.4826 | 0.0705 | 14.75 | 0.92 | 0.3859 | **93.7 %** | 16 / 16 |
| g12 | 0.3349 | 0.4450 | 0.1101 | 16.00 | 1.00 | 0.2909 | **86.9 %** | 16 / 1024 |
| g13 | 0.3927 | 0.4700 | 0.0772 | 15.90 | 0.99 | 0.3638 | **92.6 %** | 16 / 16 |
| g14 | 0.6386 | 0.6386 | **0.0000** | **0.00** | **0.00** | 0.6386 | **100.0 %** | 16 / 16 |
| g15 | 0.4633 | 0.5051 | 0.0418 | 11.23 | 0.70 | 0.4488 | **96.9 %** | 16 / 16 |
| g16 | 0.1070 | 0.4444 | 0.3374 | 31.33 | 1.96 | — | — | 256 / 1024 |
| g17 | 0.4293 | 0.4746 | 0.0452 | 10.40 | 0.65 | 0.4136 | **96.3 %** | 16 / 16 |
| g18 | 0.0000 | 0.2765 | 0.2765 | 15.35 | 0.96 | — | — | 480 / 1024 |
| g19 | 0.1575 | 0.4760 | 0.3185 | 34.42 | 2.15 | — | — | 176 / 624 |
| g20 | 0.6201 | 0.6232 | 0.0031 | 1.69 | 0.10 | 0.6191 | **99.8 %** | 16 / 16 |

"floor share" is blank where the proposal did not clamp to the 16-block floor, i.e. where a legal pressure already reaches the band and no floor extrapolation was needed.

### 1.4 The four categories M1 asked for

Cell level (40 cells; categories are mutually exclusive, assigned in this priority order):

| Category | Cells | Which cells |
|---|---:|---|
| **Legal-range infeasibility** (floor outside band, metric responds) | 11 | g02 L_LOW, g04 L_LOW, g06 L_LOW, g07 L_LOW, g07 L_HIGH, g08 L_LOW, g11 L_LOW, g12 L_LOW, g13 L_LOW, g15 L_LOW, g17 L_LOW |
| **Pressure-insensitive response** (Δρ < 0.01, floor clause also fails) | 6 | g01 L_LOW, g01 L_HIGH, g14 L_LOW, g14 L_HIGH, g20 L_LOW, g20 L_HIGH |
| **L_LOW / L_HIGH non-discriminability** | 0 (at cell level) | — this failure only exists at group level, §1.5 |
| **Predicted reachable** | 23 | 15 genuinely controlled + 8 floor accidents (§1.6) |
| **Total** | **40** | |

Note that **g07 fails both bands**, not just L_LOW: its floor is 0.5200, above the L_HIGH ceiling of 0.45. It is counted once, under infeasibility.

**Important correction to the framing.** "Non-discriminability" is not a cell-level property here. A cell cannot be non-discriminable on its own — the failure is that a *pair* of cells collapses to the same pressure. That is a group-level verdict, so it is reported in §1.5 instead of being forced into the cell table. The 23 "reachable" cells also need qualification, because 8 of them are only in band by accident.

### 1.5 Group-level verdicts (the decision-relevant view)

| Verdict | Groups | List |
|---|---:|---|
| **Two-level contrast supported** | **7** | g03, g05, g09, g10, g16, g18, g19 |
| **Both loads collapse to the floor** (proposed L_LOW pressure == L_HIGH pressure) | **10** | g01, g02, g06, g07, g11, g13, g14, g15, g17, g20 |
| **Two-level contrast unsupported** (L_LOW infeasible, L_HIGH fine) | **3** | g04, g08, g12 |
| **Total** | **20** | |

**Discrepancy note.** M1's review cited **9** groups with colliding L_LOW/L_HIGH proposed pressures; the frozen proposal file yields **10**. The list above is reproducible from `iteration2-required-blocks-proposal.json` and enumerated by the analysis script. The one-group difference is most likely a boundary convention (whether a group that also appears in the pressure-insensitive list is counted twice). It does not change any conclusion; it is reported rather than silently reconciled so the count can be checked.

### 1.6 Pressure-response stratification, and why 23 "passes" overstate controllability

| Stratum | Groups | List |
|---|---:|---|
| **Flat** (Δρ < 0.01) | 3 | g01, g14, g20 — matches M1's identification exactly |
| **Weak** (0.01 ≤ Δρ < 0.10, cannot span the 0.25 gap between bands) | 8 | g02, g06, g07, g08, g11, g13, g15, g17 |
| **Responsive** (Δρ ≥ 0.10) | 9 | g03, g04, g05, g09, g10, g12, g16, g18, g19 |

Threshold justification: the L_LOW ceiling is 0.15 and the L_HIGH floor is 0.25, so a group must move `rho0` by at least 0.10 just to touch both bands, and by 0.25 to traverse their midpoints. Δρ < 0.01 is smaller than the design's own block granularity at these prefill magnitudes (under 0.7 tokens of recompute per block, i.e. under 4 % marginality).

**8 of the 23 in-band cells are floor accidents** — they sit in band only because the workload's own floor happens to land there, at the minimum legal pressure:

| Cell | predicted `rho0` at 16 blocks | band |
|---|---:|---|
| g02 L_HIGH | 0.3682 | [0.25, 0.45] |
| g03 L_LOW | 0.1069 | [0.05, 0.15] |
| g05 L_LOW | 0.1225 | [0.05, 0.15] |
| g06 L_HIGH | 0.3756 | [0.25, 0.45] |
| g11 L_HIGH | 0.3859 | [0.25, 0.45] |
| g13 L_HIGH | 0.3638 | [0.25, 0.45] |
| g15 L_HIGH | 0.4488 | [0.25, 0.45] |
| g17 L_HIGH | 0.4136 | [0.25, 0.45] |

None of these demonstrates that pressure controlled the level. Reporting them as "PASS" without this qualifier would overstate controllability by roughly a third (8 of 23).

The eight split cleanly in two, and the distinction matters for the rule in §2.3:

| Accident belongs to | Cells | Reading |
|---|---|---|
| a **weak** group (Δρ < 0.10, fails controllability) | g02 L_HIGH, g06 L_HIGH, g11 L_HIGH, g13 L_HIGH, g15 L_HIGH, g17 L_HIGH | the band was hit by luck; the group cannot support a level contrast |
| a **responsive** group (Δρ ≥ 0.10, controllability established) | g03 L_LOW, g05 L_LOW | the floor cell is a legitimate *operating point*; controllability is established by Δρ, not by that cell |

### 1.7 Effect on the original load target

| Load target element | Effect |
|---|---|
| L_LOW band `[0.05, 0.15]` | Reachable by distinct legal pressure in only **7 groups**; 13 groups have a floor above 0.15 |
| L_HIGH band `[0.25, 0.45]` | Achievable in **18 groups** (all except g01, g14, g20 whose floors already exceed 0.45 — and there the *floor*, not pressure, is what exceeds it) |
| **Two-level contrast** | Supported in **7 of 20 groups** (35 %) |
| H3's premise ("forced release has a cost") | Vacuous in the 3 flat groups, where marginality is 0.00–0.15, i.e. forced release is essentially free |

---

## Part II — G4 Protocol Revision Proposal

### 2.1 Q1: Is the current Load Target built on an invalid controllability assumption?

**Yes, and specifically on two of them.**

Protocol v3 §3.6 and G4 treat `rho0` as if `required_blocks` could place it anywhere in `[0.05, 0.45]`. The measurement contradicts this. The correct model is

$$\rho_0(N)\;\approx\;\rho_{\text{floor}}+k\,N,\qquad \rho_{\text{floor}}=\rho_0(N_{\min}),$$

where `rho_floor` is a **workload property** — the recomputation caused by the frozen workload's natural footprint against the 2048-block pool — and only the term `kN` is under experimental control.

Two assumptions fail:

1. **`rho_floor ≈ 0`.** It is not. Across the 13 infeasible groups it is 0.22–0.64, and it accounts for a **median 93.7 %** of the recomputation measured at the low pressure.
2. **`k` is large enough to span the bands.** It is not for 11 of 20 groups. `k` is bounded above by the marginality of forced release: at most 16 tokens/block (one block per block), and often less when the released block would have been evicted anyway. **Seven groups sit at exactly 16.00** (full marginality: g03, g04, g06, g07, g08, g09, g12), two more within 0.7 % of it (g13 15.90, g18 15.35), **five are super-marginal** (1.31–2.15×, where one forced block breaks a longer suffix), and **eight are sub-marginal** (0.00–0.99×, where the released block was going to be evicted anyway).

The decisive datum is **g14**: `R0 = 113,792` and `W0 = 178,200` **identically at both 256 and 1024 blocks**. That is not "weak response"; it is zero marginal effect of the pressure parameter, in a run that succeeded with complete evidence. Any model in which `required_blocks` controls recomputation is falsified for that workload.

### 2.2 Q2: How should base contention be separated from controlled pressure?

Separate them **by construction**, from the two points already measured, and report both as first-class metrics in every calibration cell — not only at calibration time:

| Metric | Definition | Meaning |
|---|---|---|
| `rho0_floor` | `rho0` at minimum legal pressure (16 blocks), via the frozen linear model | base resource contention: recomputation that occurs with controlled pressure off |
| `rho0_pressure` | `rho0(N) − rho0_floor` | controlled-pressure-induced recomputation |
| `marginality` | `slope / block_size` = `slope / 16` | fraction of forced releases that actually cost a block |

Three properties make this defensible:

1. **Non-parametric in spirit.** Both quantities come from the two measured points; no fitted curve beyond the linear interpolation the proposal already uses and already records.
2. **Mechanistically anchored.** `marginality = 1` is the 1:1 signature (one forced block, one block of recompute). Values above 1 are super-marginal and reflect suffix breakage — releasing an interior block invalidates the blocks behind it, which is exactly the mechanism Phase 2I modelled. Seven groups sit at 1.00, five are super-marginal (1.31–2.15), eight are sub-marginal, three of those near zero (g14 0.00, g20 0.11, g01 0.15).
3. **Falsifiable.** A group with `marginality ≈ 0` and a high `rho0_floor` cannot be made pressure-responsive at any legal setting. This is a prediction that the already-frozen experiment cannot escape.

**Consequence for interpretation.** Recomputation is not one quantity. Part is the frozen workload's own contention at a 2048-block pool; part is what the pressure loop causes. The protocol's estimand was implicitly the second, but the metric reported the sum. That is the origin of the "full-zero" difficulty, and it should be stated in the final report as a design finding about pool sizing, not buried.

### 2.3 Q3: What should change — object, decision logic, or prerequisites?

**All three, but in a way that narrows claims rather than loosens thresholds.** Recommended replacement for G4:

| # | New gate | Criterion | Fails → |
|---|---|---|---|
| **G4-a Controllability** | per group | `Δρ` achievable between the two chosen legal pressures `≥ 0.10` **and** both pressures distinct by `≥ 16` blocks | group classified `BASE_CONTENTION_DOMINATED`, excluded from the two-level estimand, **retained in the report** |
| **G4-b Level placement** | per cell | the chosen legal pressure places `rho0` inside its intended band; a floor cell counts only if the group already passes G4-a | cell not admitted to the estimand |
| **G4-c Floor transparency** | per cell | `rho0_floor`, `rho0_pressure`, `marginality` all published | calibration incomplete |

Rules that must accompany them, each closing a specific way the old gate could be gamed:

1. **The bands are not widened.** `[0.05, 0.15]` and `[0.25, 0.45]` stay. Changing them would be the manufacturing of PASS that M1 asked us to avoid.
2. **A floor cell cannot establish controllability** (§1.6). An in-band cell sitting at the 16-block floor is a lucky landing, not evidence that pressure moved the metric. It may still serve as an *operating point* inside a group whose controllability is already established by Δρ ≥ 0.10 — g03 and g05 are exactly this case, and excluding them would be the mirror error of admitting g02.
3. **Colliding pressures disqualify the contrast.** If the two loads resolve to the same `required_blocks`, the group cannot support a two-level claim regardless of whether both cells are individually in band.
4. **Group selection is blind to algorithm outcomes.** Any reselection of groups must be decided from A0-only calibration data under a rule frozen before the campaign. This is already true by construction — calibration runs A0 only — but it must be written into G0 so it cannot drift.
5. **The estimand must be restated, not silently shrunk.** See §2.5.

### 2.4 Q4: How to avoid manufacturing PASS?

Five specific protections, each tied to a failure mode this analysis actually found:

| Failure mode | Protection |
|---|---|
| Widen the bands until cells fit | Bands frozen at v3 values; any change requires a new M1 decision and is not proposed here |
| Count floor accidents as control | G4-b floor clause; report accident count explicitly (8 of 23 today) |
| Count one passing cell as a passing group | Group verdict requires **both** loads in band with **distinct** pressures and `Δρ ≥ 0.10` |
| Drop failures from the report | Non-controllable groups are reclassified and **retained**; report must state the excluded fraction (13/20 today) |
| Change the pressure axis mid-flight | KV pool stays at 2048 blocks; changing it would alter the frozen workload and is explicitly out of bounds |

The governing principle: **a reclassification is legitimate when it changes what is claimed; it is illegitimate when it changes what counts as evidence.** Everything proposed here moves a group from "calibration failure" to "documented workload property", which narrows the claim. Nothing here widens a band, drops a cell, or reinterprets a null.

### 2.5 Options, with the one I recommend

| Option | What it does | n per level | Verdict |
|---|---|---:|---|
| **A. Run only the 7 supported groups** | keeps the two-level design exactly as frozen | 7 | Honest but weak: half-width ≈ ±1,482 tokens (vs ±875 at n=20), and the estimand is now the 35 % of workloads that happen to be pressure-controllable |
| **B. Reselect groups from the 80 unmaterialised candidates** | measure controllability on new tasks, keep only those that pass | up to 20 | Methodologically sound (selection uses A0-only data) but needs new acquisition **and** a second GPU calibration, both currently unauthorised |
| **C. Change the pressure axis to KV pool size** | vary `block_override` instead of `required_blocks` | — | **Rejected**: violates the frozen 2048-block capacity |
| **D. Drop token deltas, keep decision-level (G3-CM) only** | measure discriminable decisions, not `Σ(E−C)` | 20 | Cheap, uses existing data, but abandons H1/H3 and answers only H2 |
| **E. Replace the two-level design with one measurable band per group** | require `rho0 ∈ [0.15, 0.45]` at one legal pressure, per group | **15** | **Recommended** — see below |

**Recommended: Option E.** Replace "two specific bands" with "one measurable band", and keep everything else from v3.

- **Band `[0.15, 0.45]`.** The lower edge is the old L_LOW ceiling (below it, arm deltas shrink to a block and the floor dominates); the upper edge is the old L_HIGH ceiling (above it the pool is saturated and natural eviction dominates). Both edges are inherited, not invented.
- **Why 15 groups.** Fifteen groups already have a **measured** `rho0` inside `[0.15, 0.45]` at one of the two pressures that iteration 1 actually ran: g02, g03, g04, g05, g06, g08, g09, g10, g11, g12, g13, g16, g17, g18, g19. No extrapolation is needed for this count. The five that cannot reach it are g01, g07, g14, g15, g20 — the same set whose floors exceed the ceiling or sit within 0.02 of it. g15 could reach 0.4488 only at the 16-block floor and is therefore excluded by the G4-b floor clause rather than admitted.
- **What is lost.** The dose-response claim: with one pressure level per group there is no "effect grows with pressure" statement. That was never one of H1/H2/H3; it was an extra. Dropping it narrows the claim and must be stated as such.
- **What is gained.** n = 15 groups instead of 7, so per-group CI half-width ≈ ±1,012 tokens rather than ±1,482 — and the estimand covers 75 % of the pool instead of 35 %.
- **Optional addendum.** For the 7 two-level-capable groups, keep both levels as a dose-response appendix. That appendix can never carry an H1/H2 verdict.

**The five non-controllable groups are a finding, not waste.** In a 2048-block pool these workloads already recompute 46–64 % of prefill with controlled pressure switched off. That belongs in the final report as a statement about pool sizing, and it directly informs any future work on capacity rather than on victim selection.

### 2.6 What I am explicitly not proposing

- Not proposing new bands, new thresholds, or a new target ratio.
- Not proposing to re-run the 40-cell calibration with different parameters — the reachability answer does not depend on which legal pressure is chosen.
- Not proposing to touch the 2048-block pool, the frozen workload, or iteration-1 data.
- Not proposing to declare G4 PASS. **G4 as written in v3 is not passed and cannot be passed by parameter choice.**
- Not proposing to modify Protocol v3. This is a proposal for M1.

---

## Part III — Downstream Gate Impact Report

### 3.1 What remains independently meaningful

| Item | Status | Reasoning |
|---|---|---|
| **Noise calibration** (30 run) | **Methodologically independent** | It estimates A0 run-to-run variance only; it depends on neither the bands nor `rho0` placement. `tied = 2√2·σ_run` remains derivable. **But** its 5-group sample must be drawn from whichever population the main campaign uses, so it must be re-scoped once the design is settled, and re-run rather than reused. |
| **Evidence layers L1–L4** | **Unaffected** | They describe how a depth / eviction / content / recompute claim is established. Reachability changes which cells are analysed, not what an evidence level means. |
| **G3-CM (cost-model discriminability)** | **Unaffected in definition, harder to satisfy** | It counts decisions where A3 and E0 pick differently. Fewer groups ⇒ fewer decisions ⇒ reaching the ≥ 8 threshold gets harder, but the gate itself is unchanged and still computable on `FORCED_RELEASE_DECISION` payloads. |
| **H2's decision-level component** | **Intact and relatively more important** | Whether the cost model changes a choice is measurable per decision. This survives even where token deltas are too small to estimate. |
| **H1 (A3 vs A0), H2 (A3 vs E0) as paired token comparisons** | **Valid in principle, narrowed in scope** | Pairing within group is unaffected. What changes is the population: only pressure-controllable workloads. External validity narrows from "vLLM agent workloads" to "workloads whose recomputation is pressure-controllable at a 2048-block pool". |

### 3.2 What loses its explanatory basis

| Item | Loss | Why |
|---|---|---|
| **H3 (A0 vs N0) on non-controllable groups** | **Severely damaged — the most affected item** | H3 asks whether forced release has a net cost. For the 3 flat groups the marginality is 0.00–0.15, so forced release is essentially free and `A0 − N0 ≈ 0` **by construction**. That is not "no effect"; it is "no measurable lever". For the 8 weak groups, marginality 0.65–1.31 leaves partial leverage. H3 should be reported only on groups where G4-a passes. |
| **Dose-response ("effect grows with pressure")** | Lost entirely under Option E | One level per group cannot express it. Must be declared as out of scope, or carried only in the 7-group appendix. |
| **Two-level interaction (arm × pressure)** | Lost under Option E | Same reason. Not a stated hypothesis, but readers will ask. |
| **Any claim of the form "A3 helps when pressure is high"** | Unavailable | There is no low-pressure counterfactual for 13 groups, and no second level at all under Option E. |
| **Token-delta magnitude generalisation** | Weakened | The estimand narrows to controllable workloads, so the mean delta is not a statement about the pool of 20 or about agent workloads generally. |

### 3.3 Numeric impact on the planned campaign

| Design | Groups per level | CI half-width (group SD 2000) | Precision vs v3 |
|---|---:|---:|---|
| v3 as written (20 × 2 levels) | 20 | ±875 tokens | 1.00× |
| Option A (7 supported, two levels) | 7 | ±1,482 tokens | **0.59×** (1.7× worse) |
| Option B (reselect to 20) | up to 20 | ±875 tokens | 1.00× — but requires new acquisition + a second GPU calibration |
| **Option E (15 groups, one level)** | **15** | **±1,012 tokens** | **0.86×** |
| Option D (decision-level only) | 15–20 | not applicable | token estimand abandoned |

Run counts change only under B and E: Option A keeps 240 + 30, Option E keeps the same per-cell structure but at one level per group (15 groups × 6 arms = 90 campaign runs, plus a 15-cell calibration set), so **Option E is cheaper than v3**, not more expensive. Option B is the only option that would require additional GPU budget.

### 3.4 What must stay locked until G4 is re-approved

Per M1's execution boundary, and independently of which option is chosen:

| Item | State |
|---|---|
| Second GPU calibration round | **LOCKED** — no new 40-run configuration generated or executed |
| Noise calibration | **LOCKED** — must be re-scoped to the final population and then re-run |
| Main campaign | **LOCKED** — n and the estimand are not settled |
| Protocol v3 | **UNMODIFIED** — this document is a proposal, not an amendment |
| G4 verdict | **NOT PASSED** — and not passable by parameter choice |
| Frozen workload, 2048-block pool, iteration-1 data | **UNCHANGED** |

### 3.5 A separate blocker that must not be folded into G4

The evidence pack also contains `phase3-concurrent-eligibility-rejection-audit-v1`, which failed closed:

```
audit_row_count: 40, qualified_count: 0, rejected_count: 40
conclusion: M1_AUTHORIZED_COMPUTED_AND_VISIBLE_INFLIGHT_QUALIFICATION_NOT_SATISFIED
status: FAIL_CLOSED
uses_c_to_compute_e: false
independently_qualified_e: 0   (all 40 rows)
qualification_result: REJECTED_SAME_WAVE_PREFILL_NOT_COMPLETE_BEFORE_CONSUMER_LOOKUP  (40/40)
```

Reading it precisely:

- All 40 audited pairs have `hash_lcp_tokens = native_c = 112`, so `E = C` at those pairs and they contribute **zero** to `Σ(E−C)`. The direction of the error, at those pairs, is conservative.
- `uses_c_to_compute_e: false` means `E` is not derived from `C`, so the §3.2 requirement that `E` be arm-independent is **not** violated by this audit.
- The audit covers **one pair per cell** (40 pairs from 40 cells), so it says nothing about the remaining request pairs. `E` on unaudited pairs remains unverified.

**This is an independent open item (call it G-E), not caused by and not resolved by the reachability question.** It bears on whether the primary metric's numerator overstates eligibility where content was computed but not yet visible to a same-wave consumer. It should be adjudicated separately and should not be allowed to block or to be blocked by the G4 decision. No GPU work is required to state it; resolving it may require an evidence-side change to how `E` is qualified.

### 3.6 Recommendation to M1

1. **Record G4 as NOT PASSED, with cause `BASE_CONTENTION_DOMINATED` for 13 of 20 groups**, and accept the reachability decomposition as the explanation rather than a tuning shortfall.
2. **Adopt G4-a / G4-b / G4-c** as the replacement gate structure, with bands unchanged and the floor clause added.
3. **Choose the design**: Option A (defensible, weak), B (best statistics, needs new authorisation), or **E (recommended, n = 15, no extra GPU)**.
4. **Re-scope and re-run the noise calibration** on the chosen population before the main campaign.
5. **Restate the estimand** in whichever protocol version is frozen: results would describe pressure-controllable agent workloads in a 2048-block pool, not agent workloads generally.
6. **Adjudicate G-E separately** from the reachability decision.

---

## Appendix A — Reproducibility

```bash
python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
    --pack local/phase3-g4-reachability-analysis-pack-v1 \
    --out  local/phase3-g4-reachability-m4
```

Outputs: `cell-classification.json`, `group-summary.json`, `cells.csv`, `groups.csv`. Read-only; no GPU, no network, no write outside `--out`.

Inputs consumed, verbatim:
- `artifacts/phase3-load-calibration-iteration2-planning-v1/iteration1-cell-observations.json`
- `artifacts/phase3-load-calibration-iteration2-planning-v1/iteration2-required-blocks-proposal.json`

Frozen constants read from the proposal's own `method` block: `minimum_blocks = 16`, `maximum_blocks = 2032`, `quantum_blocks = 16`, target bands.

## Appendix B — Threshold provenance

| Threshold | Value | Provenance |
|---|---:|---|
| `block_size` | 16 tokens | frozen runtime config |
| mechanically expected slope | 16 tokens/block | 1:1 block-for-block |
| FLAT | Δρ < 0.01 | below the design's block granularity at observed prefill sizes (< 0.7 tokens/block, < 4 % marginality) |
| WEAK | Δρ < 0.10 | the gap between the L_LOW ceiling and the L_HIGH floor; below it, no band crossing is possible |
| INFEASIBLE | floor > 0.15 | floor is a lower bound on achievable `rho0`; if it exceeds the L_LOW ceiling the band is unreachable |
| Proposed Option E band | [0.15, 0.45] | inherited edges: old L_LOW ceiling and old L_HIGH ceiling. No new constants invented. |
