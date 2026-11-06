# Option F — Two-Level Fixed-Pressure Evaluation

**Author**: M4
**Status**: `OFFLINE_DESIGN_ANALYSIS` — no GPU, no new run, Protocol v3 unmodified, no Gate declared passed, **F not approved**.
**Revision**: RC10, plus the follow-up corrections to RC10-1 / RC10-5 / evidence delivery (2026-11-06).
**Companion**: `g4-reachability-analysis-and-revision-proposal.md`, and the committed outputs in `outputs/` (`option-f-report.json`, `h3-report.json`, `noise-selection-report.json`, `nesting-report.json`, `g-e-report.json`, `evidence-inventory.json`).

### 0.0 What changed in this follow-up

| Item | Previous | Now |
|---|---|---|
| G-E | `hash_lcp_tokens == native_c` used as proof of `E == C`; `evidence_failure_count` hardcoded 0; a global zero contribution asserted | **Three quantities reported separately** (hash LCP / native C / independently qualified E). E summarized on the **36 qualified rows only**; the 4 pending rows stay `PENDING_EARLIER_FORWARD_ORDER_PROOF` with **no established E**. Contribution is `0 tokens over 36 rows` and `UNDETERMINED_PENDING_QUALIFICATION` on 4. Failures **counted** from the audit's own list plus per-row integrity checks. §1 |
| Noise variance | "pooled within-cell SD, df 20" with weights described loosely | **One frozen estimator**, an explicit **common-variance** assumption with three justifications, target-population stratum weights stated and shown **not** to be the cell weights, stratified outputs required as **`DIAGNOSTIC_ONLY`**, and a no-post-run-change clause. §7.3 |
| Evidence delivery | Manifest committed, described as if delivery were complete | Delivery status stated as **`raw_pack_transferred_to_m1 = false`**; GPU raw evidence, offline audits and derived analysis classified in `evidence-inventory.json`; explicit statement that CPU tests are **not** GPU reproduction. Appendix D |

---

## 0. What F is, and what F is not

**F is:** keep all 20 groups; keep the two pressures iteration 1 actually executed (256 and 1024 blocks); keep the six arms; stop treating the designed `rho0` bands as an admission rule; report band attainment as a **manipulation check**.

**F is not:** a relaxation of any threshold. `[0.05, 0.15]`, `[0.25, 0.45]`, `ρ0 ≥ 5 %`, `R0 ≥ 512`, `≥ 8` discriminable decisions — all unchanged, and all applied at the pressure they were measured at. No cell moves, no band moves, no group is added.

What F changes is the **operational definition of the condition**:

| | v3 / A′ / E | F |
|---|---|---|
| Condition means | "a level of a controlled variable" | "a **fixed operating point**" |
| Design requirement | the two conditions must be distinguishable states | the two conditions must be *runnable and measurable* |
| Band attainment | admission rule (implicitly) | manipulation check (reported, never gates) |
| Evidence for the level | model-reached or measured band placement | the fact that the run happened at that pressure |

**Naming rule (RC10-7).** Formal outputs use **C1 = 256 blocks** and **C2 = 1024 blocks**. The frozen source labels `L_LOW` / `L_HIGH` are retained only as provenance in the input files, and the script records the mapping in `cell-classification.json:condition_labels`. The words "low pressure" and "high pressure" are prohibited in F's results tables: the measured `Δρ` is below 0.10 for 11 of 20 groups, so for those groups the two conditions are not distinguishable states of a manipulated variable.

**One procedural finding.** Protocol v3 never wrote band attainment as a gate. §5.2 defines L-low/L-high **target baselines** for choosing `required_blocks`; §3.6 defines the **Headroom** gate; §9 G4 consumes the *Headroom* list. "The campaign cannot proceed unless both bands are hit" was our inference. F therefore needs **less** protocol change than A′ or E — but it still changes what a condition *means*, so it is not free.

---

## 1. RC10-1 — Current state of G-E

Two rounds of evidence exist and they answer **different questions**. Both are reported; the older one is kept as history.

### 1.1 Round 2 — current

Source: `phase3-same-batch-physical-qualification-audit-v1`, M6 recompute at git `712b3fc628c5bbebe95a782119654834c741149`.

| Field | Value |
|---|---|
| Question | Do producer and consumer resolve the same **physical prefix blocks** under a bound forward-batch source, and is the pair therefore eligible? |
| Rows | 40 |
| `QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR` | **36** |
| `PENDING_EARLIER_FORWARD_ORDER_PROOF` | **4** |
| `hash_lcp_tokens` | 112 on all **40** rows |
| `native_c` | 112 on all **40** rows |
| `independently_qualified_e` | 112 on **36** rows; **undefined on the 4 pending rows** |
| Evidence failures | **0 recorded + 0 per-row integrity = 0** |

The four pending pairs are **g08 C1, g08 C2, g20 C1, g20 C2**, all carrying `forward_relation = EARLIER_FORWARD_ORDER_NEEDS_SEPARATE_PROOF` and `scheduler_relation = EARLIER_SCHEDULER_ITERATION`. They are *pending an additional proof*, not rejected, and they have **no established E**.

### 1.2 Round 1 — history, retained

Source: `phase3-concurrent-eligibility-rejection-audit-v1`.

| Field | Value |
|---|---|
| Question | Is the producer's prefill **complete and visible** to a same-wave consumer before the lookup? |
| Rows | 40 |
| Qualified | 0 |
| Rejected | 40 |
| Status | `FAIL_CLOSED` |
| Result | `REJECTED_SAME_WAVE_PREFILL_NOT_COMPLETE_BEFORE_CONSUMER_LOOKUP` |
| `uses_c_to_compute_e` | false |
| `independently_qualified_e` | 0 |

### 1.3 Why the two are not a correction of one another

> Round 1 asks about **visibility and completion timing** of the producer's prefill. Round 2 asks about **physical block identity and forward-batch source binding**, and additionally requires the **forward-order proof** before a pair counts as eligible. A pair can bind the same physical prefix while still failing round 1's visibility criterion, and a pair can bind the same physical prefix while still being *pending* the order proof.

So the previous document's sentence — "40/40 rejected, FAIL_CLOSED" — is **no longer a correct description of the current state**, even though no round-1 row changed. It is now reported as history, with its own question attached.

### 1.4 What does not change, and what must not be asserted

Not asserted any more (RC10-1 fix):

- **`hash_lcp_tokens == native_c` does not prove `E == C`.** Those are content-hash and native-prefix measurements; eligibility additionally needs the forward-order proof. Physical prefix equality is **necessary but not sufficient**.
- **A null `independent_e` is not a conservative zero.** On the 4 pending rows E was never established, so neither equality nor a zero contribution may be claimed; the correct state is `UNDETERMINED_PENDING_QUALIFICATION`.
- **`evidence_failure_count` is not a constant.** It is derived from the audit's own `evidence-failures.json` (0 records) plus per-row integrity checks (0 failures) — currently 0 + 0 = 0.

What does hold:

- `Σ(E−C)` is judged **only** where the pair was qualified and E was produced: **0 tokens over 36 rows**. Overall verdict `PARTIAL_DETERMINATE`.
- `uses_c_to_compute_e` is false in both rounds, so §3.2's arm-independence requirement on `E` is **not** violated. That is a separate claim from whether an `E` value exists.
- The audit covers **one pair per cell**, so the remaining request pairs are unverified in either round.
- **G-E remains independent of G4 and of the design choice.** It must not block, and must not be blocked by, the A′/E/F decision.

---

## 2. Q1 — Can F stand without a new A0 calibration?

**Yes, exactly and by construction.**

| Fact | Value |
|---|---|
| Pressures F uses | 256 and 1024 blocks |
| Pressures iteration 1 executed | 256 and 1024 blocks |
| A0 runs already available at those pressures | 40 (20 groups × 2) |
| Cells in F's campaign | 40 |
| Cells whose `ρ0` and `R0` were measured at the pressure F will run them at | **40 / 40** |
| New calibration runs required | **0** |

F is the only candidate for which every analysed cell has been measured at exactly the pressure it will be run at. **Option A** runs cells at iteration-2 proposed pressures, 27 of 40 of which lie outside `[256, 1024]` and 25 of which clamp to the 16-block floor, so Headroom has never been evaluated there — hence its `2 × cells` calibration charge. **A′ / E** use only measured pressures but need only 12 / 15 of the 40 cells already paid for.

The 40 executed runs are therefore not "stale calibration data" under F; they **are** the condition set.

---

## 3. Q2 — How Headroom combines with a two-condition paired design

### 3.1 Headroom is evaluated per cell, at F's own pressures

`ρ0 ≥ 5 %` **and** `R0 ≥ 512 tokens`, recomputed from the frozen observation file (the stored flag is not trusted):

| Condition | Candidate cells | Eligible | Excluded |
|---|---:|---:|---:|
| C1 (256 blocks) | 20 | **18** | 2 |
| C2 (1024 blocks) | 20 | **20** | 0 |
| **Total** | **40** | **38** | **2** |

| Excluded cell | `ρ0` | `R0` | Cause |
|---|---:|---:|---|
| g09 C1 | 0.0448 | 1,552 | ratio 4.48 % < 5 % |
| g18 C1 | 0.0000 | 0 | both (no recomputation at all) |

### 3.2 Four populations, never merged (RC10-6)

| Level | Groups | Cells | Meaning |
|---|---:|---:|---|
| **Campaign (executed)** | **20** | **40** | everything that runs; not an analysis population |
| **C1 analysed** | 18 | **18** | Headroom-qualified C1 cells |
| **C2 analysed** | 20 | **20** | Headroom-qualified C2 cells |
| **Paired primary** | **18** | 36 | groups qualified in **both** conditions |

> The paired primary estimates the **18-group paired population**, **NOT** the 20-group pool. g09 and g18 are executed and enter the C2 estimate and H3-0, but they do not exist in the paired estimand's population. Any sentence that pairs "full pool" with the paired number is wrong.

The two groups lose only their **pair**, not their participation. Nothing is discarded.

### 3.3 Why Headroom is the right gate here

Under F, Headroom is not screening for "the interesting cases". It is screening for **"is there anything to measure"**: `ρ0 < 5 %` means the baseline recomputation is too small for an arm delta to be anything but 0, and `R0 < 512` means it is below 32 blocks of quantisation. g18 C1 has `R0 = 0` — literally zero recomputation, so no arm can differ from A0 there, and "no effect" would be uninformative rather than negative. That is exactly the failure Phase 3 was built to avoid.

---

## 4. Q3 — H1 / H2 statistics, and the two interactions

### 4.1 What F measures

Two conditions × 6 arms, paired within group by condition and within cell by arm.

### 4.2 Estimands, units and weights (RC10-6)

| Estimand | Statistical unit | Weight | n | Role |
|---|---|---|---|---|
| Per-condition Δ | cell | 1 per cell (equal) | C1 18, C2 20 | descriptive; the honest answer to "what happens at 256 / at 1024" |
| **Group-averaged Δ** | **group** | **1 / 18 per group**; within a group the two condition deltas are **1/2 each** | **18** | **primary** |
| Stratum Δ | group | 1 / stratum size | 9 / 8 / 3 | mechanistic reading |
| Interaction-A | group | 1 / 18 | 18 | interaction, primary |
| Interaction-B | group | 1 / 7 | 7 | interaction, heterogeneity |
| H3-0 | group | 1 / 20; within-group cells 1/2 each | 20 groups / 38 cells | H3 primary |
| Manipulation check | cell | unweighted count | 40 | reporting only |

Two things must **not** be done:

1. **Do not pool C1 and C2 as 38 independent observations.** They are the same groups. That would shrink the interval for free — the standard pseudo-replication error.
2. **Do not read the two per-condition estimates as two replications of one quantity.** They estimate different quantities (the effect at 256 and at 1024), and for 11 groups those quantities are close to identical.

Averaging inside the group first is what makes the group-averaged estimand legitimate: the group stays the resampling unit, and the average is of two condition-specific effects, not of 38 cells.

### 4.3 Precision: averaging inside a group partly cancels noise

`Var(mean) = sd² · (1 + ρ) / 2`, where `ρ` is the within-group correlation of the two condition deltas. `ρ` is unmeasured here, so the whole range is reported:

| `ρ` | SD | Planned CI half-width (n=18) | vs single level, n=20 | Equivalent single-level n |
|---:|---:|---:|---:|---:|
| 0.0 | 1,414 | **±653** | 0.74× | 36.0 |
| 0.5 | 1,732 | **±800** | 0.91× | 24.0 |
| 0.8 | 1,897 | **±877** | 1.00× | 20.0 |
| 1.0 | 2,000 | **±924** | 1.05× | 18.0 |

Comparison: A′ n=12 → ±1,132; E n=15 → ±1,012; v3 n=20 → ±876. These are **planning** figures from an assumed SD of 2,000 tokens, not achieved precision.

### 4.4 Two interactions, two conclusions (RC10-3)

The previous revision reported one interaction number and justified ignoring FLAT groups with "`ΔD ≈ 0` by construction". **That inference was invalid and is withdrawn.** `Δρ` describes how much **A0's own recomputation** moves between conditions; it says nothing about how an **arm's difference from A0** moves between them. A small `Δρ` is not evidence that a group's `ΔD` is zero.

| Analysis | Population | n | Minimum 8 met | Role |
|---|---|---:|---|---|
| **Interaction-A** | all 18 complete pairs | **18** | **yes** | **primary interaction analysis** |
| **Interaction-B** | RESPONSIVE pairs only | **7** | **no** | pre-registered heterogeneity analysis |

Interaction-B groups: g03, g04, g05, g10, g12, g16, g19 (g09 and g18 lose their pair to Headroom).

`sd(ΔD) = √2 · sd_delta · √(1 − ρ)`, so the difference of differences is *less* precise than either main effect unless the conditions are positively correlated:

| `ρ` | SD | Planned CI half-width (n=18) |
|---:|---:|---:|
| 0.0 | 2,828 | ±1,307 |
| 0.5 | 2,000 | ±924 |
| 0.8 | 1,265 | ±584 |

Three further problems, none fixable by more runs:

1. **`n = 18` pairs, not 20**, and the two losses (g09, g18) are the two groups with the smallest C1 — so the loss is **not random with respect to pressure response**.
2. **Interaction-B is below the 8-group minimum**, so its interval must be reported with `N_analyzed` and no verdict.
3. **Attribution fails for 11 groups.** A condition-by-arm interaction can only be attributed to pressure intensity where the two conditions *are* two levels of pressure.

**These are two different research statements and must never be merged into one conclusion.** A difference between Interaction-A and Interaction-B is a statement about *where the interaction is visible*, not a contradiction.

---

## 5. Q4 — H3 restructured (RC10-2)

### 5.1 What was wrong

The previous revision promoted RESPONSIVE to H3's primary population and dropped FLAT because `A0 − N0` was *predicted* to be near zero there. That inference is wrong in kind: a small `Δρ` describes how much **A0's own recomputation** moves with pressure and says nothing about what a force-release arm does **relative to A0**. Prediction is not a reason to remove a group from a hypothesis.

### 5.2 The structure now

| Role | ID | Population | Groups | Cells (C1 / C2) | Carries a verdict |
|---|---|---|---:|---|---|
| **Primary** | **H3-0** | every Headroom-qualified cell, both conditions, **all strata incl. FLAT** | **20** | **38** (18 / 20) | **yes** |
| **Separate hypothesis** | **H3-R** | RESPONSIVE only | **9** | **16** (7 / 9) | yes, on its own estimand |
| Heterogeneity | — | WEAK | 8 | 16 (8 / 8) | descriptive |
| Heterogeneity | — | FLAT | 3 | 6 (3 / 3) | descriptive |

**H3-0's question:** does forced release (A0 vs N0) have a net cost on recomputation, across the Headroom-qualified workload pool?

**H3-R's question:** is that cost observable in the subset whose **baseline** recomputation itself responds to pressure? Its rationale is that a non-trivial empirical marginal response ratio is a *necessary* condition for the mechanism to have anywhere to act. It is an **additional** hypothesis, not a replacement: if the cost appears only here, that is a finding about the mechanism's domain; if it appears in H3-0 and not here, that is a finding about sensitivity, not a contradiction.

### 5.3 Unit and weights for 9 groups / 16 cells (RC10-2 item 5)

| Item | Rule |
|---|---|
| Resampling unit | **group** |
| Group weight | **1/9** each — equal group weight, **not** proportional to cell count |
| Within-group weight | **1/2** per cell for the 7 two-cell groups; **1** for the two one-cell groups (g09 C2, g18 C2) |
| Estimator | mean of Headroom-eligible cells inside the group, then mean / bootstrap over the 9 groups |

Cell-weighted averaging is deliberately **not** used: it would give two-cell groups twice the influence of one-cell groups, making the inference depend on Headroom's per-condition count rather than on the workload pool. The report must state this, because the unweighted and cell-weighted values will differ.

### 5.4 Why H3 does not depend on the paired set (RC10-2 item 6)

H3 is a per-cell `A0 − N0` comparison, so it needs no pair. `h3_report()` therefore no longer derives any population from `paired_groups`: H3-0 has **20 groups / 38 cells**, and g09 / g18 each contribute their single eligible C2 cell at full within-group weight. The previous "secondary = paired groups minus FLAT" logic was inconsistent with the per-cell definition and has been removed.

**FLAT is not excluded from H3-0.** It is retained and additionally reported as its own stratum, with its own interval, precisely because "predicted to be small" is not "measured as zero".

---

## 6. Q5 — F versus A′, E

### 6.1 Head-to-head

| Dimension | **F** | **A′** | **E** |
|---|---|---|---|
| Groups / cells in campaign | **20 / 40** | 12 / 12 | 15 / 15 |
| Conditions per group | **2** | 1 | 1 |
| New calibration runs | **0** | 0 | 0 |
| New runs total | **270** | 99 | 117 |
| Analysis n for headline | **18 pairs** | 12 | 15 |
| Planned half-width | **±653 – ±924** (ρ-dependent) | ±1,132 | ±1,012 |
| H3-0 | **20 groups / 38 cells** | 12 groups | 15 groups |
| H3-R | **9 groups / 16 cells** | 6 (below min 8) | 9 |
| G3-CM | **40 decisions, 8/40 = 20 %** | 12 → 67 % | 15 → 53 % |
| Interaction-A | **18 pairs → confirmatory-eligible** | none | none |
| New constants | **none** | none | one band (3 groups) |
| Manipulation validity | **weakest** | strongest | strong |
| External validity | **full 20-group execution pool; 18-group paired estimand** | in-band workloads only | in-band workloads only |
| Mechanistic interpretability | **weakest** | strongest | strong |

### 6.2 Nesting, corrected (RC10-4)

The previous document wrote `F ⊃ E ⊃ A′`. **That was wrong.** The correct statement is:

> **F ⊃ E and F ⊃ A′. E and A′ are neither nested nor disjoint.**

What *is* true: every A′ and every E operating point is one of F's 40 cells, so F can host both as pre-registered subgroups. What is *not* true: E and A′ pick the **same** operating point for every group. They do not:

| Group | A′ | E | Remark |
|---|---|---|---|
| g03 | C2 @ 1024, ρ0 = 0.3557 | **C1 @ 256, ρ0 = 0.1821** | moves into the 0.15–0.25 gap |
| g16 | C1 @ 256, ρ0 = 0.1070 | **C2 @ 1024, ρ0 = 0.4444** | moves to the in-band C2 cell |

So the same group is studied at a **different condition** in the two designs. E-only groups are g05, g10, g19; A′-only groups: none. The consequence is that A′ and E are **not** a subset/superset pair, their estimates are not nested comparisons, and only F's relation to each of them is nested.

### 6.3 Where F is worse, stated plainly

1. **Dilution of the pooled estimate.** The group-averaged delta is a **population average** over groups whose baseline sensitivity spans an order of magnitude. It is not an effect size, and a small value is **not** evidence that the mechanism is weak. Stratum estimates carry the mechanistic reading.
2. **Weak manipulation validity.** Only **1 of 20 groups** (g16) has both conditions inside their designed bands; **13 of 20** have neither. Reporting the conditions as "low"/"high" pressure would assert a separation the data contradicts. They are C1/C2 with block counts.
3. **Interaction-B is below the 8-pair minimum** (7 pairs), so the RESPONSIVE interaction carries no verdict.
4. **18 pairs, not 20**, from applying Headroom honestly — and the losses are the two groups with the smallest C1.

### 6.4 Where F is better

1. **Cheapest defensible design** at 270 new runs and **no new calibration**.
2. **Largest n** and the only design with a precision advantage over v3 for plausible `ρ`.
3. **Broadest external validity among the reachable designs**: the estimand covers the 18-group paired population drawn from the full 20-group execution pool, rather than only in-band workloads.
4. **Best H3**, because per-cell comparisons survive the loss of pairs — 20 groups / 38 cells for H3-0, versus 12 and 15 groups for A′ and E.
5. **Nothing invented**: no new band, no new threshold, no new pressure, and no model-extrapolated operating point anywhere in the design.

---

## 7. Q6 — Noise calibration: the rule closed (RC10-5)

### 7.1 Does drawing from the 18 paired groups change §6.4?

§6.4 requires the noise set to be "independent of the main campaign and of the Headroom screening". Two readings exist and they are **not** equivalent:

| Reading | Preserved? | Why |
|---|---|---|
| **Decision independence** — the noise set must not influence which cells are analysable | **yes** | Headroom is computed from A0 calibration data and frozen before any noise run; selecting from the resulting paired set cannot feed back into that decision |
| **Population independence** — the noise set must be a sample of all 20 groups regardless of Headroom | **no** | a paired-only draw is conditional on Headroom passing at both conditions, so `σ_run` describes the paired population and not all 20 groups; g09 and g18 are never sampled |

F needs pairs, so its noise sample **must** come from the 18 paired groups: a `σ_run` estimated on cells outside the analysis population would not describe the `tied` threshold applied to that population. The report therefore takes the **first** reading, states the cost of the second, and asks for an explicit v4 amendment. **"Still 30 runs" is not sufficient justification**, and the previous document's "unchanged from v3" claim is withdrawn as worded.

### 7.2 Frozen selection rule

| Item | Frozen value |
|---|---|
| Candidate set | the 18 Headroom-paired groups |
| Ordering key | `sha256("phase3-noise-selection-v1:" + group_id)`, ascending |
| Why not random | a frozen hash permutation is reproducible without stored random state and cannot be steered after seeing a measurement |
| Stratum allocation | **RESPONSIVE 2, WEAK 2, FLAT 1** |
| Allocation rationale | proportional to paired strata (7 / 8 / 3) with the smallest stratum rounded up to 1 so no stratum is unrepresented |
| Design | 5 groups × 2 conditions × R=3 = **30 runs**, A0 only |
| Frozen by | must be written into G0 with the salt and the allocation |

Current draw: **g01, g04, g06, g07, g10** (FLAT: g01; RESPONSIVE: g04, g10; WEAK: g06, g07).

### 7.3 Variance estimation — one frozen rule (RC10-5 item 2)

> **Frozen rule.** `σ_run` is the **pooled within-cell SD** of per-run `Σ(E−C)` over the **10 sampled cells** (5 groups × 2 conditions), with **equal weight per cell** and **df = 10 × (3 − 1) = 20**. `σ_δ = √2·σ_run`; `tied = 2√2·σ_run`. No other estimator is permitted for this campaign, and the rule may not be revised once the noise runs exist.

| Item | Value |
|---|---|
| Assumption adopted | **common within-cell variance** (homoscedastic) across strata and conditions |
| Justification 1 | every sampled cell has the same `R = 3`, so the pooled estimator is balanced rather than weighted by unequal cell counts |
| Justification 2 | the design needs **one** absolute `tied` threshold applied uniformly to the paired population; per-stratum thresholds would make "tied" depend on which stratum a cell landed in, and no protocol section defines that |
| Justification 3 | per-stratum estimates would rest on 4 cells (df 4) each — too unstable to freeze as a threshold |
| df | **20**; relative SE of `σ_run` ≈ **15.8 %** |
| Weights (cell) | equal per cell — **not** proportional to the population stratum shares |
| Target-population stratum weights | `RESPONSIVE 7/18 = 0.389`, `WEAK 8/18 = 0.444`, `FLAT 3/18 = 0.167` |
| Why the two differ | FLAT supplies **2 of 10 cells (20 %)** while being **3 of 18 groups (16.7 %)**; the pooled value is a design-based summary of the sampled cells, not a population-weighted variance |
| Stratified outputs | per-stratum `σ_run` and the max/min stratum ratio are **required** |
| Status of stratified outputs | **`DIAGNOSTIC_ONLY`** — the pooled rule stands regardless of the ratio; switching to per-stratum thresholds after seeing the diagnostic would violate S9 and would need a fresh amendment *before* the run |
| Interaction | **no `tied` classification**: it needs the within-group correlation of the two condition deltas, which is unmeasured → `UNDEFINED_ASSUMPTION` |

### 7.4 v4 noise clause changes

1. Replace "independent of the Headroom screening" with "independent of the Headroom **decision procedure**, conditioned on its outcome, drawn by the G0-frozen deterministic rule".
2. State that `σ_run` estimates the **paired** population and that groups failing Headroom at either condition are not sampled.
3. Require stratum-specific `σ_run` and the max/min ratio **as `DIAGNOSTIC_ONLY`**, explicitly stating that the pooled rule stands regardless.
4. **Freeze the estimator in the protocol text**: pooled within-cell SD, equal cell weight, df 20, `σ_δ = √2·σ_run`, `tied = 2√2·σ_run`, common-variance assumption with its three justifications, and no post-run change.
5. Keep the 30-run budget and A0-only design unchanged; only the sampling frame, the estimator text and the reporting obligations change.

---

## 8. Q7 — Budget, estimand, gate changes, Protocol v4 draft

### 8.1 Budget

| Run set | Cells / groups | Runs | Note |
|---|---:|---:|---|
| A0 calibration | — | **0** | the 40 executed runs *are* the condition set |
| Noise calibration | 5 groups × 2 conditions × R=3 | **30** | v3 budget, new sampling frame (§7) |
| Main campaign | 6 arms × 40 cells × R=1 | **240** | unchanged |
| **Total new runs** | | **270** | identical to v3 |

G3-CM headroom: **40 decisions available, 8 required → 20 %** must discriminate (A′ 67 %, E 53 %, E∩G4-a 89 %). GPU-hours are not quoted: M6's measured per-run cost is not available to M4.

### 8.2 Estimand sentence to freeze

> **Primary.** For agent-style workloads in a 2048-block KV pool executed at two pre-registered fixed operating points (**C1 = 256** and **C2 = 1024** blocks of `required_blocks`), the mean per-request difference in `Σ(E−C)` between each arm and A0, averaged over the two conditions **within each group** and reported over the **18 groups** that pass Headroom at both conditions. The statistical unit is the group; the group weight is 1/18; within a group the two condition deltas are weighted 1/2 each.

> **Secondary (pre-registered, not confirmatory).** (a) the same quantity restricted to the 12 A′-eligible in-band cells; (b) stratum estimates for FLAT / WEAK / RESPONSIVE; (c) the C1 and C2 per-condition estimates; (d) **Interaction-A** over all 18 complete pairs (primary interaction analysis) and **Interaction-B** over the 7 RESPONSIVE pairs (heterogeneity), reported separately and never merged.

> **H3-0 (primary).** Forced-release cost `A0 − N0` over every Headroom-qualified cell: 20 groups / 38 cells (C1 18, C2 20); unit = group, weight 1/20, within-group cells 1/2 each. FLAT included.

> **H3-R (separate).** The same quantity over RESPONSIVE groups: 9 groups / 16 cells (C1 7, C2 9); unit = group, weight 1/9.

> **Manipulation check (reported, never gating).** `ρ0` at both conditions for all 20 groups, `Δρ`, and band attainment: **8 of 40** cells in band; **1 of 20** groups (g16) with both; **13 of 20** with neither; strata 9 / 8 / 3.

### 8.3 Gate modification list

| Gate | v3 | Under F |
|---|---|---|
| **G0 freeze** | arms, metrics, 20 groups, load params, Headroom list, profile, replay rules | **add**: C1/C2 defined as 256/1024 blocks; strata frozen from A0-only data; manipulation-check fields; pre-registered A′ subgroup and its estimator; noise-selection salt and allocation; prohibition on post-hoc group or stratum reselection |
| **G1 isolation** | unchanged | **unchanged** |
| **G2 branch composition** | per campaign and per load | **unchanged**, reported per condition |
| **G3-CM** | ≥ 8 discriminable decisions | **unchanged**; 40 available |
| **G4** | Headroom list only | **reaffirmed as Headroom-only**; band attainment explicitly *not* an admission rule |
| **G4-M (new)** | — | **manipulation check**: report band attainment, `Δρ`, strata; **failure does not block and does not exclude any cell** |
| **S9** | no post-hoc adjustment of Headroom/thresholds | **unchanged**, extended to groups and strata |
| **S10 (new)** | — | no relabelling C1/C2 as "low"/"high"; no pooling C1 and C2 as independent; no post-hoc subgroup extraction; no inferring an arm-vs-A0 interaction from `Δρ` |

Nothing here relaxes a threshold. G4 becomes *narrower* (Headroom only, explicitly), and reporting constraints are added.

### 8.4 Protocol v4 draft — amendment text

> **Status: DRAFT. Not authorised. Prepared for M1 adjudication; v3 is unmodified.**

**§3.6 (Headroom) — unchanged** in threshold and timing.

**§5.2 (Load conditions) — replaced.** Two fixed operating points: C1 at `required_blocks = 256`, C2 at 1024. These are the two pressures measured in iteration-1 calibration. The designed `rho0` bands are retained **as a manipulation check and reporting target only**; they admit or exclude no cell and are not a condition for the campaign proceeding. Conditions are labelled C1/C2 in every table and must not be described as low/high pressure.

**§5.2.1 (Pressure-response strata) — new.** FLAT (`Δρ < 0.01`), WEAK (`0.01 ≤ Δρ < 0.10`), RESPONSIVE (`Δρ ≥ 0.10`), computed from the two measured `ρ0` values before any arm runs and frozen in G0. Used to **report** heterogeneity and to define H3-R; not used to select groups for the token estimand.

**§5.4 (Pairing) — REPLACED (RC10-6).** v3 says "cross-load 不配对：只做平行报告，不做合并检验". That wording is incompatible with the group-averaged estimand and must be rewritten, not left to interpretation:

> **§5.4 pair and merge rules.**
> 1. **Within-cell paired**: the six arms share one plan SHA-256 per (group, condition).
> 2. **Across conditions, never pool as independent observations.** C1 and C2 are the same groups; they are never treated as 38 independent cells, and no interval may be computed from a pooled C1 ∪ C2 sample.
> 3. **Across conditions, the group-level average is permitted and is the primary estimand of Option F.** For a group qualified in both conditions, the estimator is the mean of its two condition deltas; the two deltas enter at weight 1/2. The group remains the resampling unit and receives weight 1/G.
> 4. **Per-condition estimates are reported separately and are not replications.** They answer "what happens at 256" and "what happens at 1024", and for 11 of 20 groups those two answers are close to identical.
> 5. A group qualified in only one condition contributes to that condition's estimate and to H3, but not to the group-averaged estimand.

v3 §6.1's row "每个 load 档的独立 group 数 = 20；两档同 group，不得合并为 40" remains correct as a prohibition on pooling *cells*; §5.4.3 above adds the one permitted merge, at group level, with group weight.

**§6.2 (Estimation) — extended.** Three estimates required: (a) per-condition Δ (C1 n=18, C2 n=20); (b) the group-averaged Δ over 18 pairs — **primary**; (c) stratum Δ. Resampling by group, never by cell. Every interval reported with `N_analyzed`, discriminable decisions and S2A count.

**§6.2.1 (H3 populations) — new.** H3-0 over all Headroom-qualified cells (20 groups / 38 cells), FLAT included; H3-R over RESPONSIVE only (9 groups / 16 cells) as a separate hypothesis; strata reported as pre-registered heterogeneity. Unit = group; within-group cells 1/2 each.

**§6.3 (Power) — extended.** Group-averaged variance is `sd²(1+ρ)/2`; `ρ` is unmeasured, so the report must state the assumed `ρ` and must not present the planned half-width as achieved precision.

**§6.4 (Noise) — amended** per §7.4 above.

**§9 (Gates) — G4 retained; G4-M added.**

**§10 (Stop conditions) — S9 unchanged; S10 added** per §8.3.

---

## 9. Decision matrix — when F is the right choice

| If the primary claim is… | Best design | Why |
|---|---|---|
| "Does the depth signal reduce recomputation for this agent-workload pool in a 2048-block KV pool?" | **F** | broadest population, largest n, cheapest, no new constant |
| "Does the cost model change decisions under *controlled* pressure intensity?" | **A′** | only A′ has measured levels; F cannot separate pressure from fixed-point effects |
| "…and across the widest defensible population of controllable workloads" | **E** | 15 groups vs 12, at the price of one new band edge |
| "…with a two-level contrast proven by direct measurement" | **none of them** | only 1 group has a measured two-level contrast (RC6) |
| "…including dose-response" | **B** only | needs new acquisition + calibration |

**F does not foreclose A′ or E.** Every A′ and E operating point is one of F's 40 cells, so choosing F and pre-registering A′ as a frozen subgroup delivers both estimates for the same 270 runs. The relation is one-directional: **F ⊃ E and F ⊃ A′**, while E and A′ are neither nested nor disjoint (§6.2). The subgroup is legitimate only if defined from A0-only data and frozen in G0 — not extracted after seeing an arm (§10 S9).

**What would make F wrong:** if M1 requires the conditions to be two validated levels of pressure (F fails by construction); or if the headline must be a mechanistic effect size rather than a population average (dilution makes F's headline uninterpretable); or if the interaction must be confirmatory on RESPONSIVE groups (7 pairs, below the minimum of 8).

---

## Appendix A — Numbers reproduced by the analysis script

```bash
python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
    --pack local/phase3-g4-reachability-analysis-pack-v1 \
    --out  docs/experiments/phase3-g4/outputs
```

| Quantity | Value | Source |
|---|---|---|
| Campaign groups / cells | 20 / 40 | `option-f-report.json:design` |
| C1 / C2 analysed cells | 18 / 20 | `option-f-report.json:population.levels` |
| Paired primary groups | 18 | same |
| Pairs lost | g09 C1, g18 C1 | `option-report.json:F.excluded_pairs` |
| Cells in designed band | 8 / 40 | `option-f-report.json:manipulation_check` |
| Groups both / one / neither in band | 1 / 6 / 13 | same |
| `Δρ` strata | 9 RESPONSIVE / 8 WEAK / 3 FLAT | same |
| H3-0 | 20 groups / 38 cells (C1 18, C2 20) | `h3-report.json:primary` |
| H3-R | 9 groups / 16 cells (C1 7, C2 9) | `h3-report.json:secondary_hypothesis` |
| Interaction-A / B | 18 pairs (min met) / 7 pairs (min not met) | `option-f-report.json:interaction` |
| Noise draw | g01, g04, g06, g07, g10 | `noise-selection-report.json` |
| `σ_run` df | 20 (rel. SE 0.158) | same |
| Nesting | F ⊃ E, F ⊃ A′; E ⊥̸ A′ | `nesting-report.json` |
| G-E current | 36 qualified / 4 pending, 0 failures | `g-e-report.json` |
| New runs | 0 + 30 + 240 = 270 | `calibration-cost-report.json` |
| G3-CM | 40 decisions, 8/40 = 20 % | same |

## Appendix B — Tests

`pytest tests/test_g4_reachability_analysis.py -q` → **87 passed**, CPU only, no network, no writes outside `tmp_path`. The committed log is `outputs/cpu-test-run.txt`. (This supersedes the 72 figure quoted before this revision, which added 15 tests.)

**What these tests are.** They are **unit and regression tests of the analysis code**, not a reproduction of a GPU experiment. They run against synthetic fixtures and, when present, the local copy of the pack. No GPU command is issued, and re-running the script regenerates derived outputs only — it does not regenerate the 40 executed runs.

RC10 coverage:

| RC | Tests |
|---|---|
| RC10-2 H3 restructure | H3-0 keeps FLAT; FLAT is a stratum not an exclusion; H3-R is separate with its own estimand; per-condition counts; group-vs-cell weighting; H3 independent of the paired set; per-design population sizes (7) |
| RC10-3 interaction | all-pairs vs RESPONSIVE reported separately; no `Δρ ⇒ ΔD = 0` inference; "by construction" absent from caveats (3) |
| RC10-4 nesting | F ⊃ E and F ⊃ A′; E and A′ not nested; g03 and g16 move (1) |
| RC10-5 noise | decision vs population independence; allocation; determinism across two runs; df; 4 v4 amendments (1) |
| RC10-6 population | four levels; scope warning that the paired primary is not a 20-group estimate (inside the real-pack test) |
| RC10-1 G-E | round 2 is current (36/4); E summarised **only** on qualified rows; hash LCP / native C / E reported separately; pending rows stay `NOT_ESTABLISHED`; missing and contradictory evidence cases; failures counted not assumed (12) |
| RC10-5 noise | single frozen estimator, common-variance justification, stratum weights, diagnostic-only status (2) |
| Evidence inventory | GPU raw vs offline audit vs derived; delivery status; synthetic classification (2) |
| RC10-7 conditions | `cell-classification.json` carries the `L_LOW→C1` / `L_HIGH→C2` mapping |

## Appendix C — What F cannot deliver

1. A two-validated-levels claim for any group except g16 (the only group with both cells in band).
2. A mechanistic effect size from the pooled headline (population average, not an effect size).
3. A confirmatory RESPONSIVE interaction (7 pairs, minimum 8).
4. Any dose-response statement beyond "two points were run".
5. Attribution of condition differences to pressure intensity for the 11 groups with `Δρ < 0.10`.
6. A per-condition estimate that also generalises to the other condition.
7. Any inference about the 20-group pool from the 18-group paired estimand.

## Appendix D — How M1 obtains and verifies the evidence pack

### D.1 Delivery status, stated plainly

| Item | Value |
|---|---|
| Path | `local/phase3-g4-reachability-analysis-pack-v1/` |
| Tracked by git | **no** — `local/` is gitignored by repository policy |
| Size | **260 files, 209.4 MiB** (computed by the script, not by hand) |
| Manifest | committed as `outputs/pack-sha256-manifest.txt` (**250 entries**) |
| Metadata | committed as `outputs/pack-metadata.json` |
| Provenance | M1-provided read-only bundle, `created_at_utc 2026-11-05T12:28:20Z`, git `712b3fc`, `gpu_execution_included: false` |
| **Raw pack transferred to M1** | **NO** — it cannot be committed at this size |
| Manifest committed | yes, but a manifest proves integrity only for bytes M1 already holds or obtains out of band |

**This is the honest state.** The 250-entry manifest and the derived outputs are in Git; the 209 MiB of
executed-run material is not, and no amount of manifest checking changes that. Until the directory is
transferred or located, the raw GPU evidence is **referenced, not delivered**. `outputs/evidence-inventory.json`
records this as `delivery_status.raw_pack_transferred_to_m1 = false` with the matching open action.

### D.2 What is GPU evidence and what is derived

The pack's 18 `artifacts/` directories are classified in `outputs/evidence-inventory.json`:

| Class | Directories / files | Meaning |
|---|---:|---|
| **Frozen execution inputs** | **1 directory** | `phase3-load-calibration-inputs-v1` — frozen configs, traces, prompts and freeze records; inputs, not execution outputs |
| **Per-run execution reports** | **40 files** | `phase3-load-calibration-analysis-v7/runs/` — the 40 per-cell A0 reports produced from the executed calibration runs |
| **Mixed analysis directory** | **1 directory** | `phase3-load-calibration-analysis-v7` also contains aggregate, evidence-binding, evidence-failure and qualification outputs; the script classifies these files separately instead of labelling the whole directory as raw GPU evidence |
| **Execution summary** | **1 directory** | `phase3-load-calibration-runs-v2` — status, wall time and config hashes |
| **Runtime evidence inventory** | **1 directory** | `phase3-same-batch-runtime-evidence-inventory-v1` — a runtime evidence index, not a raw run |
| **Offline audits over GPU evidence** | **13 directories** | the two eligibility audits, scheduler/run mapping audit and vLLM source audits; they read execution output but do not produce runs |
| **Offline derived analysis** | **1 directory** | `phase3-load-calibration-iteration2-planning-v1`, status `PROPOSED_NOT_EXECUTED` |
| **Unclassified files** | reported individually | any file not matching a frozen category is surfaced as `UNCLASSIFIED`; it is never silently folded into GPU evidence |

### D.3 What this analysis does not claim

- It does **not** reproduce a GPU experiment. No GPU command is issued anywhere in it.
- Its CPU tests are **unit and regression tests of the analysis code**, run against synthetic fixtures
  and, when present, the local pack. They are **not** experimental replication.
- Re-running the script regenerates the derived outputs only; it does not regenerate the 40 executed runs.

### D.4 Verification procedure for a transferred copy

```bash
# from the root of the transferred pack
python - <<'EOF'
import hashlib, pathlib, sys
manifest = pathlib.Path("sha256-manifest.txt").read_text().splitlines()
bad = 0
checked = 0
for line in manifest:
    if not line.strip():
        continue
    digest, _, rel = line.partition("  ")
    p = pathlib.Path(rel.strip())
    actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    checked += 1
    if actual != digest:
        bad += 1
        print("MISMATCH", rel, actual)
print(f"checked {checked} entries; failures: {bad}")
sys.exit(1 if bad else 0)
EOF
```

Then run the analysis against the copy. Before computing any result, the entry point verifies **all 250 manifest entries** (missing files, malformed/duplicate paths, path escapes and hash mismatches fail closed), and requires the Round-1 audit, Round-2 qualification audit and `evidence-failures.json` to be covered by that manifest. It then verifies the five pinned planning inputs and the proposal's own `source_observations_sha256`. The `analysis-v7` directory is classified file-by-file; unknown files remain explicitly `UNCLASSIFIED`.
