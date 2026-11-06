# Option F — Two-Level Fixed-Pressure Evaluation

**Author**: M4
**Status**: `OFFLINE_DESIGN_ANALYSIS` — no GPU, no new run, Protocol v3 unmodified, no Gate declared passed.
**Responds to**: M1's request to reopen the single-load decision, 2026-11-06.
**Companion**: `g4-reachability-analysis-and-revision-proposal.md` (reachability evidence), `outputs/option-f-report.json` (all numbers below).

---

## 0. What F is, and what F is not

**F is:** keep all 20 groups; keep the two pressures that iteration 1 actually executed (256 and 1024 blocks); keep the six arms; stop treating the designed `rho0` bands as an admission rule; report band attainment as a **manipulation check**.

**F is not:** a relaxation of any threshold. `[0.05, 0.15]`, `[0.25, 0.45]`, `ρ0 ≥ 5 %`, `R0 ≥ 512`, `≥ 8` discriminable decisions — all unchanged, and all applied at the same pressure they were measured at. No cell moves, no band moves, no group is added.

What F changes is the **operational definition of the condition**:

| | v3 / A′ / E | F |
|---|---|---|
| Condition means | "a level of a controlled variable" | "a **fixed operating point**" |
| Design requirement | the two conditions must be distinguishable states | the two conditions must be *runnable and measurable* |
| Band attainment | admission rule (implicitly) | manipulation check (reported, never gates) |
| Evidence for the level | model-reached or measured band placement | the fact that the run happened at that pressure |

That distinction is the whole of F. It is a real change of claim and it has real costs (§5), which is why F is presented as a peer of A′ and E rather than as a correction of them.

**One procedural finding worth recording.** Protocol v3 never actually wrote band attainment as a gate. §5.2 defines L-low/L-high **target baselines** for choosing `required_blocks`; §3.6 defines the **Headroom** gate; §9 G4 consumes the *Headroom* list. The requirement "the campaign cannot proceed unless both bands are hit" was inferred by us, and G4's `PENDING_LOAD_PARAMETER_FREEZE` status follows from that inference, not from a written rule. So F requires **less** protocol change than A′ or E. It still changes the *semantics* of the condition labels, so it is not free.

---

## 1. Q1 — Can F stand without a new A0 calibration?

**Yes, exactly and by construction.**

| Fact | Value |
|---|---|
| Pressures F uses | 256 and 1024 blocks |
| Pressures iteration 1 executed | 256 and 1024 blocks |
| A0 runs already available at those pressures | 40 (20 groups × 2) |
| Cells in F's design | 40 |
| Cells whose `ρ0` and `R0` were measured at the pressure F will run them at | **40 / 40** |
| New calibration runs required | **0** |

F is the only candidate design for which *every* cell in the analysis has been measured at exactly the pressure it will be run at. By contrast:

- **Option A** runs cells at iteration-2 proposed pressures. 27 of 40 of those lie outside `[256, 1024]` and 25 clamp to the 16-block floor, so Headroom has never been evaluated there. That is why A carries a `2 × cells` calibration charge.
- **A′ and E** pick one of the two measured pressures, so they need no new calibration — but they use only 12 and 15 of the 40 cells that were already paid for.
- **F** uses all 40.

The 40 executed runs are therefore not "stale calibration data" under F; they are **the condition set itself**.

---

## 2. Q2 — How Headroom combines with a two-condition paired design

### 2.1 Headroom is evaluated per cell, at F's own pressures

Protocol v3 §3.6: `ρ0 ≥ 5 %` **and** `R0 ≥ 512 tokens`. Recomputed from the frozen observation file (the stored flag is not trusted):

| Condition | Candidate cells | Eligible | Excluded |
|---|---:|---:|---:|
| C1 (256 blocks) | 20 | **18** | 2 |
| C2 (1024 blocks) | 20 | **20** | 0 |
| **Total** | **40** | **38** | **2** |

| Excluded cell | `ρ0` | `R0` | Cause |
|---|---:|---:|---|
| g09 C1 | 0.0448 | 1,552 | ratio 4.48 % < 5 % |
| g18 C1 | 0.0000 | 0 | both (no recomputation at all) |

### 2.2 A paired design needs *pairs*, so two groups lose theirs

This is the cost of applying Headroom honestly to a paired design, and it is not small:

| | Count |
|---|---:|
| Groups in the design | 20 |
| Groups with both cells eligible (**paired**) | **18** |
| Groups that keep only one condition | 2 — g09, g18 |

F therefore has **two analysis populations**, and both must be reported:

| Purpose | Population | n |
|---|---|---:|
| Per-condition estimate, C1 | cells eligible in C1 | **18** |
| Per-condition estimate, C2 | cells eligible in C2 | **20** |
| Group-averaged estimand | groups with a pair | **18** |
| H3 (per-cell, no pair needed) | eligible cells in the stratum | 16 in primary |
| Manipulation check | all 40 cells | 40 |

g09 and g18 are **not** dropped from the campaign: they run, they are archived, and their C2 cells enter H3 and the per-condition C2 estimate. They simply cannot supply a two-condition pair. Nothing is discarded; one specific contrast is unavailable for them.

### 2.3 Why Headroom is the right gate here, and why it is not a formality

Under F, Headroom is not screening for "the interesting cases". It is screening for **"is there anything to measure"**: `ρ0 < 5 %` means the baseline recomputation is too small for an arm delta to be anything but 0, and `R0 < 512` means it is below 32 blocks of quantisation. g18 C1 has `R0 = 0` — literally zero recomputation, so no arm can differ from A0 there and "no effect" would be uninformative rather than negative. That is the exact failure Phase 3 was built to avoid, and it is why F keeps this gate rather than using band attainment.

---

## 3. Q3 — H1 / H2 statistics, and the interaction

### 3.1 What F measures

Two conditions × 6 arms × 18–20 groups. Within each group, the same workload runs under both conditions, so the conditions are **paired within group**, and the arms are **paired within cell**.

### 3.2 Estimands

| Estimand | Definition | n | Role |
|---|---|---:|---|
| Per-condition Δ | mean / median `Σ(E−C)` difference, arm vs A0, bootstrapped over groups analysed in that condition | 18 / 20 | descriptive, and the only honest answer to "what happens at 256 / at 1024" |
| **Group-averaged Δ** | per group, average the two condition deltas **first**, then bootstrap over the 18 paired groups | **18** | **primary** |
| Stratum Δ | the group-averaged Δ computed inside FLAT / WEAK / RESPONSIVE | 9 / 8 / 3 groups | mechanistic claim |
| Interaction ΔD | `Δ_g(C2) − Δ_g(C1)`, bootstrapped over paired groups | 18, of which 7 RESPONSIVE | secondary |

Two things must **not** be done, and both are tempting:

1. **Do not pool C1 and C2 as if they were 38 independent observations.** They are the same groups. That would halve the interval for free and is the standard pseudo-replication error.
2. **Do not read the two per-condition estimates as two replications of one quantity.** They estimate different quantities (the effect at 256 and at 1024), and for 11 groups those quantities are close to identical.

Averaging inside the group first is what makes the group-averaged estimand legitimate: group remains the resampling unit, and the average is of two condition-specific effects, not of 38 cells.

### 3.3 Precision: averaging inside a group partly cancels noise

`Var(mean) = sd² · (1 + ρ) / 2`, where `ρ` is the within-group correlation of the two condition deltas. `ρ` is not measured by this analysis, so the whole range is reported:

| `ρ` | SD | Planned CI half-width (n=18) | vs single level, n=20 | Equivalent single-level n |
|---:|---:|---:|---:|---:|
| 0.0 | 1,414 | **±653** | 0.74× | 36.0 |
| 0.5 | 1,732 | **±800** | 0.91× | 24.0 |
| 0.8 | 1,897 | **±877** | 1.00× | 20.0 |
| 1.0 | 2,000 | **±924** | 1.05× | 18.0 |

For comparison: A′ n=12 → ±1,132; E n=15 → ±1,012; v3 n=20 → ±876.

**F's group-averaged estimand is the most precise of all options, for `ρ < 0.8`** — but read §5.3 before treating that as an advantage: it is more precise *about a broader and more diluted quantity*.

### 3.4 Is the pressure × algorithm interaction estimable?

**Estimable: yes. Reportable as a confirmatory claim: no.**

| Item | Value |
|---|---|
| Pairs available | 18 |
| RESPONSIVE pairs | **7** — g03, g04, g05, g10, g12, g16, g19 |
| Protocol §6.2 minimum | 8 |
| Status | below the minimum → `INSUFFICIENT_ANALYZED_CELLS` on the RESPONSIVE interaction |

`sd(ΔD) = √2 · sd_delta · √(1 − ρ)`, so the difference of differences is *less* precise than either main effect unless the conditions are positively correlated:

| `ρ` | SD | Planned CI half-width (n=18) |
|---:|---:|---:|
| 0.0 | 2,828 | ±1,307 |
| 0.5 | 2,000 | ±924 |
| 0.8 | 1,265 | ±584 |

Three further problems, none of which can be fixed by more runs:

1. **g09 and g18 lose their pair to Headroom**, so the interaction population is 7 RESPONSIVE groups, not 9 — and the two losses are the *two* groups whose C1 is smallest, i.e. the loss is not random with respect to pressure response.
2. **The 3 FLAT groups contribute `ΔD ≈ 0` by construction.** Their high correlation means they add little variance but a lot of bias toward zero. So a pooled `ΔD` near 0 is **not** evidence of no interaction; it is partly arithmetic. A pooled interaction result would have to be pre-declared as diluted, and the stratum-by-stratum values reported instead.
3. **Attribution fails for 11 groups.** A condition-by-arm interaction can only be attributed to pressure intensity where the two conditions *are* two levels of pressure. For the 8 WEAK and 3 FLAT groups they are two similar operating points.

**Recommendation:** declare the interaction **exploratory**, report it per stratum with `N_analyzed`, and never let a pooled interaction number carry a verdict. If a confirmatory interaction is genuinely required, that is an argument for a *third* condition or for more groups (Option B), not for F.

---

## 4. Q4 — Can H3 be split RESPONSIVE / WEAK / FLAT?

**Yes, and F is the best of the three candidates for it** — because H3 is a per-cell `A0 vs N0` comparison that needs no pair, so the two groups that lost their pair still contribute.

Rule (identical to the RC7 rule already established, so no new constant):

| Role | Population | Groups | Cells |
|---|---|---:|---:|
| **Primary — carries the verdict** | RESPONSIVE (`Δρ ≥ 0.10`) | **9** — g03, g04, g05, g09, g10, g12, g16, g18, g19 | **16** |
| **Secondary — descriptive only** | paired groups minus FLAT | **15** | — |
| **FLAT — separate description** | `Δρ < 0.01` | **3** — g01, g14, g20 | 6 |

Why FLAT is neither primary nor secondary: its `empirical_marginal_response_ratio` is 0.00–0.15, so forced release is *predicted* to cost almost nothing and `A0 − N0` is predicted near 0. **No N0 arm has ever run**, so this is a prediction, not an observed null. A FLAT result would be dominated by the construction rather than by physics. FLAT is reported as its own stratum with that explanation attached — which is more informative than dropping it silently, and is what F buys over A′ (which excludes FLAT groups entirely).

Two caveats: the primary has 16 cells across 9 groups, so the cluster structure is non-trivial and the bootstrap must resample **groups**, not cells; and H3's primary on F is larger than on A′ (6 groups) and equal to E (9), so F dominates both on this hypothesis.

---

## 5. Q5 — F versus A′, E

### 5.1 Head-to-head

| Dimension | **F** | **A′** | **E** |
|---|---|---|---|
| Groups / cells in design | **20 / 40** | 12 / 12 | 15 / 15 |
| Conditions per group | **2** | 1 | 1 |
| New calibration runs | **0** | 0 | 0 |
| New runs total (calib + noise + main) | **270** | 99 | 117 |
| Analysis n for headline | **18 groups** (paired) | 12 | 15 |
| Planned half-width (headline) | **±653 – ±924** (ρ-dependent) | ±1,132 | ±1,012 |
| H3 primary | **9 groups / 16 cells** | 6 (below min 8) | 9 |
| G3-CM | **40 decisions, 8/40 = 20 %** | 12 → 67 % | 15 → 53 % |
| Dose-response | 2 points, not interpretable as a gradient | none | none |
| Interaction | 7 RESPONSIVE pairs → **not confirmatory** | n/a | n/a |
| New constants required | **none** | **none** | one band (3 groups) |
| Manipulation validity | **weakest** | strongest | strong |
| External validity (population) | **full 20-group pool** | in-band workloads only | in-band workloads only |
| Mechanistic interpretability | **weakest** (diluted pool mean) | strongest | strong |

### 5.2 The structural fact that changes the decision: the designs are nested

Every operating point used by A′ (12) and by E (15) is one of the **40 cells F already contains** — they are all at 256 or 1024 blocks. So:

> **F ⊃ E ⊃ A′ at the cell level.**

| Design | Cells used | Cells of F used |
|---|---:|---:|
| F | 40 | 40 (100 %) |
| E | 15 | 15 (38 %) |
| A′ | 12 | 12 (30 %) |

This has a consequence that neither of the earlier analyses made explicit: **choosing F does not foreclose A′ or E.** Both become *pre-registered subgroup analyses* of the same campaign, at zero additional GPU cost. Conversely, choosing A′ or E discards 25–28 cells that were already paid for and that carry the pool-level information.

The legitimacy condition is strict and must go into G0: **the subgroup must be defined from A0 calibration data only, frozen before the campaign, and written into G0 with its own estimator.** Post-hoc subgroup extraction after seeing an arm result is precisely what §10 S9 forbids. The selection here *can* be blind — in-band membership is a property of `ρ0` measured on A0 — but "can be" is not "is", so it must be pre-registered, not discovered later.

### 5.3 Where F is genuinely worse, stated plainly

1. **Dilution.** F's headline is the mean over all paired groups. For 3 FLAT groups the mechanism cannot act (`Δρ = 0`, `A0 − N0` predicted ≈ 0), and for 8 WEAK groups it acts weakly. A small pooled mean is therefore **not** evidence of a small mechanistic effect, and a large one would be hard to attribute. A′/E avoid this by construction; F must handle it by reporting strata and by *naming* the pooled estimate as a population average rather than an effect size.
2. **Manipulation failure relabelled as design.** In only **1 of 20 groups** (g16) do both conditions land inside their designed bands; 13 groups land in neither. Reporting F's conditions as "low pressure" and "high pressure" would assert a state separation the data contradicts for 14 groups. The labels must be `C1 = 256 blocks` / `C2 = 1024 blocks`, full stop. This is the single largest interpretive risk in F and the reason the words "L_LOW"/"L_HIGH" must not appear in F's results tables.
3. **Interaction is not confirmatory** (7 RESPONSIVE pairs). If the paper's contribution depends on "the benefit grows with pressure", F cannot deliver it and neither can A′/E.
4. **Two fewer pairs than v3 assumed** (18, not 20), from applying Headroom honestly.

### 5.4 Where F is genuinely better

1. **Cheapest defensible design**: 270 new runs, no new calibration, and the **noise design is the v3 design unchanged** (§6).
2. **Largest n** and the **only** design with a precision advantage over v3 for plausible `ρ`.
3. **Full-pool external validity**: the estimand is about the 20-group agent-workload pool, not about workloads that happened to land in a band. That is a real scientific advantage if the claim is "does the depth signal reduce recomputation in this setting".
4. **Best H3**, because per-cell comparisons survive the loss of pairs.
5. **Nothing invented**: no new band, no new threshold, no new pressure, and no model-extrapolated operating point anywhere in the design.

---

## 6. Q6 — Can noise calibration stay at 5 × 2 × 3 = 30?

**Yes — F is the only candidate for which the v3 noise design is used literally unchanged.**

| Item | v3 | F |
|---|---|---|
| Design | 5 groups × 2 conditions × R=3 = 30 | **identical** |
| Conditions | 256, 1024 | 256, 1024 |
| Output | `σ_run` → `σ_δ = √2 σ_run` → `tied = 2√2 σ_run` | identical |
| Re-specification needed | — | **none** |

Two conditions to fix:

1. **The 5 groups must be drawn from the 18 paired groups**, not from all 20, or `σ_run` is partly estimated on cells whose pair does not exist. Recommended: one group per stratum as far as possible (e.g. 3 RESPONSIVE, 1 WEAK, 1 FLAT), chosen by a rule frozen in G0 — not by convenience.
2. **`σ_run` estimates single-arm variance, not the interaction's variance.** If the interaction is reported (exploratory, §3.4), its own noise floor is `√2 σ_δ √(1 − ρ_g)` and `ρ_g` is unmeasured. Report the interaction without a `tied` classification, or mark it `tied = UNDEFINED_ASSUMPTION`.

A′/E cannot reuse the v3 noise design, because their designs have one level per group; they need re-specification to 5×1×3 or 9×1×3. F therefore saves the ~12 % relative-SE loss that a 15-run noise set would incur (df 10 vs 20).

---

## 7. Q7 — Budget, estimand, gate changes, Protocol v4 draft

### 7.1 Budget

| Run set | Cells / groups | Runs | Note |
|---|---:|---:|---|
| A0 calibration | — | **0** | the 40 executed runs *are* the condition set |
| Noise calibration | 5 groups × 2 conditions × R=3 | **30** | unchanged from v3 |
| Main campaign | 6 arms × 40 cells × R=1 | **240** | unchanged from v3 |
| **Total new runs** | | **270** | **identical to v3** |

Per design, for comparison: A′ 99, E 117, A (measured-only) 38 but on 1 cell, B 310. GPU-hours are not quoted: M6's measured per-run cost (§5.1 item 3) is not available to M4, and estimating one would be the kind of number this review has been rejecting.

G3-CM headroom: **40 decisions available, 8 required → 20 %** must discriminate. Compare A′ 67 %, E 53 %, E∩G4-a 89 %. F is the only design where this gate is comfortable.

### 7.2 Estimand sentence to freeze

> **Primary.** For agent-style workloads in a 2048-block KV pool, run at two pre-registered fixed operating points (C1 = 256 blocks, C2 = 1024 blocks of `required_blocks`), the mean per-request difference in `Σ(E−C)` between each arm and A0, averaged over the two conditions within each group and reported over the 18 groups that pass Headroom at both conditions.

> **Secondary (pre-registered, not confirmatory).** (a) the same quantity restricted to the 12 A′-eligible in-band cells; (b) stratum estimates for FLAT / WEAK / RESPONSIVE; (c) the C1 and C2 per-condition estimates; (d) an exploratory `ΔD` interaction, reported per stratum, never pooled into a verdict.

> **Manipulation check (reported, never gating).** `ρ0` at both conditions for all 20 groups, `Δρ`, and band attainment: 8 of 40 cells land in their designed band; 1 of 20 groups (g16) lands in both; 13 of 20 land in neither.

The words "low pressure" and "high pressure" are **prohibited** in F's results tables. The conditions are C1/C2 with their block counts.

### 7.3 Gate modification list

| Gate | v3 | Under F |
|---|---|---|
| **G0 freeze** | arms, metrics, 20 groups, load params, Headroom list, profile, replay rules | **add**: C1/C2 defined as 256/1024 blocks; strata frozen from A0-only data; manipulation-check fields; the pre-registered A′ subgroup and its estimator; the prohibition on post-hoc group or stratum reselection |
| **G1 isolation** | unchanged | **unchanged** |
| **G2 branch composition** | per campaign and per load | **unchanged**, reported per condition |
| **G3-CM** | ≥ 8 discriminable decisions | **unchanged**; 40 available |
| **G4** | Headroom list only | **reaffirmed as Headroom-only**; band attainment explicitly *not* an admission rule |
| **G4-M (new)** | — | **manipulation check**: report band attainment, `Δρ`, strata; **failure does not block and does not exclude any cell** |
| **S9** | no post-hoc adjustment of Headroom/thresholds | **unchanged**, extended to groups and strata |
| **S10 (new)** | — | no relabelling C1/C2 as L_LOW/L_HIGH; no pooling C1 and C2 as independent; no post-hoc subgroup extraction |

Nothing in this list relaxes a threshold. G4 becomes *narrower* (Headroom only, explicitly), and two reporting constraints are added.

### 7.4 Protocol v4 draft — amendment text

> **Status: DRAFT. Not authorised. Prepared for M1 adjudication; v3 is unmodified.**

**§3.6 (Headroom) — unchanged** in threshold and timing: `ρ0 ≥ 5 %` and `R0 ≥ 512 tokens`, evaluated per cell on the independent A0 calibration set, frozen into G0.

**§5.2 (Load conditions) — replaced.**

> Phase 3 executes two **fixed operating points**: C1 at `required_blocks = 256`, C2 at `required_blocks = 1024`. These are the two pressures measured in iteration-1 calibration, so `ρ0` and `R0` are known at each. The designed `rho0` bands `[0.05, 0.15]` and `[0.25, 0.45]` are retained **as a manipulation check and reporting target only**; they do not admit or exclude any cell, and they are not conditions of the campaign proceeding.
>
> Conditions are labelled `C1` / `C2` in every table. They must not be described as "low" or "high" pressure: the measured `Δρ` is below 0.10 for 11 of 20 groups, so for those groups the two conditions are not distinguishable states of a manipulated variable.

**§5.2.1 (Pressure-response strata) — new.**

> Each group is classified from the two measured `ρ0` values, before any arm is run: **FLAT** (`Δρ < 0.01`), **WEAK** (`0.01 ≤ Δρ < 0.10`), **RESPONSIVE** (`Δρ ≥ 0.10`). The classification is frozen in G0. It is used to *report* heterogeneity and to define H3's primary population; it must not be used to select groups for the token estimand.

**§6.2 (Estimation) — extended.**

> Three estimates are required: (a) per-condition Δ (C1 n=18, C2 n=20), (b) the **group-averaged** Δ over the 18 paired groups — the primary estimate — and (c) stratum Δ. Resampling is by **group**, never by cell, and C1 and C2 are never pooled as independent observations. Every interval is reported with `N_analyzed`, the number of discriminable decisions, and the S2A count, as in v3.

**§6.3 (Power) — extended.**

> The group-averaged estimand has `Var = sd²(1+ρ)/2`. `ρ` is not measured in this phase; the report must state which `ρ` was assumed for planning and must not present the planned half-width as achieved precision.

**§6.4 (Noise) — unchanged**, with the sample drawn from the 18 paired groups under a rule frozen in G0.

**§9 (Gates) — G4 replaced by G4 + G4-M.** G4 keeps its v3 text (Headroom list only). G4-M adds the manipulation check as a reporting requirement with no exclusion power.

**§10 (Stop conditions) — S9 unchanged; S10 added** as in §7.3.

**H3 tiering** as §4 of this document (primary RESPONSIVE, secondary paired-minus-FLAT, FLAT separately described).

---

## 8. Decision matrix — when F is the right choice

F is **not** automatically better. The choice turns on which claim the phase exists to support.

| If the primary claim is… | Best design | Why |
|---|---|---|
| "Does the depth signal reduce recomputation for this agent-workload pool in a 2048-block KV pool?" | **F** | full pool, largest n, cheapest, no new constant |
| "Does the cost model change decisions under *controlled* pressure intensity?" | **A′** | only A′ has measured levels; F cannot separate pressure from fixed-point effects |
| "…and across the widest defensible population of controllable workloads" | **E** | 15 groups vs 12, at the price of one new band edge |
| "…with a two-level contrast proven by direct measurement" | **A′** (1 group) — i.e. **none of them** | only 1 group has a measured two-level contrast (RC6) |
| "…including dose-response" | **B** only | needs new acquisition + calibration |

**Recommendation.** If M1's lean toward A′ is driven by wanting an unambiguous mechanistic claim, A′ remains the right choice and F does not displace it. If the phase's purpose is the pool-level question — which is what H1/H2 as written actually ask — **F is the better design**, and it does not cost the A′ estimate: A′ becomes a pre-registered subgroup of F.

That last point is the constructive part of this analysis:

> **F is the only option that can deliver A′'s estimate as well as its own, at no extra cost**, because A′'s 12 cells are a subset of F's 40. The reverse is not true: choosing A′ cannot recover F's pool-level estimand.

The condition is that the subgroup is frozen in G0 from A0-only data and reported as secondary. If M1 is not willing to pre-register it, the nesting advantage disappears and the choice reduces to the claim, as in the table above.

**What would make F wrong:** if M1 requires the conditions to be two validated levels of pressure (then F fails by construction), or if the headline must be a mechanistic effect size rather than a population average (then dilution makes F's headline uninterpretable), or if the interaction must be confirmatory (7 RESPONSIVE pairs, below the minimum of 8).

---

## Appendix A — Numbers reproduced by the analysis script

```bash
python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
    --pack local/phase3-g4-reachability-analysis-pack-v1 \
    --out  docs/experiments/phase3-g4/outputs
```

| Quantity | Value | Source field |
|---|---|---|
| Groups / cells in design | 20 / 40 | `option-f-report.json:design` |
| Headroom-eligible cells | 38 (C1 18, C2 20) | `option-report.json:F` |
| Paired groups | 18 | `option-report.json:F.paired_groups_n` |
| Pairs lost | g09 C1, g18 C1 | `option-report.json:F.excluded_pairs` |
| Cells in designed band | 8 / 40 | `option-f-report.json:manipulation_check` |
| Groups with both conditions in band | 1 (g16) | same |
| Groups with neither in band | 13 | same |
| `Δρ` strata | 9 RESPONSIVE / 8 WEAK / 3 FLAT | same |
| H3 primary | 9 groups, 16 cells | `h3-report.json:F` |
| Interaction pairs | 18 total, 7 RESPONSIVE | `option-f-report.json:interaction` |
| New runs | 0 + 30 + 240 = 270 | `calibration-cost-report.json:option_F_two_level_fixed_pressure` |
| G3-CM | 40 decisions, 8/40 = 20 % | same |

Frozen inputs (SHA-256 pinned in the script, cross-checked against the pack manifest): the four M1-designated planning inputs plus the observation CSV. See the companion document, Appendix A.

## Appendix B — Tests

`pytest tests/test_g4_reachability_analysis.py -q` → **63 passed**, CPU only. Option F coverage (13 tests):

| Assertion | What it protects |
|---|---|
| both executed pressures, all groups, band attainment not a gate | F's definition |
| no new calibration; noise 30; unchanged from v3 | the cost claim |
| every frozen band and Headroom threshold unchanged | that F is not a relaxation |
| a group with neither cell in band stays in the design and in the pair set | the manipulation check has no admission power |
| only the pair whose cell fails Headroom is lost | the 18-vs-20 accounting |
| strata reported over both design and paired sets | that the two populations are not confused |
| H3 primary is RESPONSIVE and counts eligible cells (2+1=3 in the fixture) | that H3 does not require pairs |
| interaction population excludes lost pairs and is flagged below minimum | the 7-vs-9 caveat |
| run accounting 0/30/240 | budget |
| group-averaged precision improves with `ρ`; interaction worsens with independence | the two variance formulas |
| threats list names dilution, attribution, post-hoc selection | the losses are recorded, not hidden |
| real-pack check: 18 pairs, 8/40 in band, 9/16 H3 cells, 7 RESPONSIVE pairs, 270 runs | the end-to-end numbers |

## Appendix C — What F cannot deliver, in one list

1. A two-validated-levels claim for any group except g16 (the only group with both cells in band).
2. A mechanistic effect size from the pooled headline (dilution by FLAT and WEAK groups).
3. A confirmatory pressure × algorithm interaction (7 RESPONSIVE pairs, minimum 8).
4. Any dose-response statement beyond "two points were run".
5. Attribution of condition differences to pressure intensity for the 11 groups whose `Δρ < 0.10`.
6. A per-condition estimate that also generalises to the other condition — the two are separate estimands over the same groups.
