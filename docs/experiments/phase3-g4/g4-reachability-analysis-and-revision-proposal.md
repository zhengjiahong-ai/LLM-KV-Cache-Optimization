# Phase 3 — G4 Reachability Analysis, Revision Proposal, Downstream Gate Impact

**Author**: M4
**Revision**: RC1–RC5 response to M1's PR #97 review (2026-11-05)
**Status**: `ANALYSIS_ONLY` — awaiting M1 adjudication. **No GPU execution. No frozen input modified.**
**Evidence pack**: `local/phase3-g4-reachability-analysis-pack-v1` (created 2026-11-05, git `712b3fc`, `gpu_execution_included: false`)
**Analysis script**: `scripts/probes/phase3_g4_reachability/reachability_analysis.py` (read-only, SHA-256 verified inputs)
**CPU tests**: `tests/test_g4_reachability_analysis.py` (38 tests, no GPU, no network)

**Scope boundary honoured**: no second calibration round, no new 40-run configuration, no workload/pool/input change, no noise calibration, no main campaign, iteration-1 data untouched, Protocol v3 unmodified, no G4 PASS declared.

---

## 0. What changed in this revision

The previous submission conflated two different gates and overstated the status of the model's
extrapolations. Both are corrected here, and one of the previous headline claims is withdrawn.

| RC | Previous submission | This revision |
|---|---|---|
| **RC1** | Implied the original G4 fails, because L_LOW is unreachable for 13 groups | **Withdrawn.** G4 and the L_LOW/L_HIGH load target are computed separately. On the frozen parameters the Headroom gate admits **38 of 40** cells — the original gate's own threshold is *satisfied*. What fails is §5.2's load target. §1.1 |
| **RC2** | Called the 16-block value a "pressure-independent floor", i.e. a measured workload property | **Withdrawn as a measured quantity.** It is a two-point linear extrapolation 240 blocks below the lowest measured pressure, and for 4 groups it returns a **negative** recomputation ratio, which is physically impossible. §1.5 |
| **RC2** | "marginality" described as the fraction of forced releases that cost a block | Renamed **empirical marginal response ratio**: an observed slope ratio, not a release-cost coefficient. §1.5 |
| **RC2** | `A0 − N0 ≈ 0` stated as a consequence | Restated as a **prediction**, since no N0 arm has ever been run. §3.2 |
| **RC3** | "L_HIGH achievable in 18 groups" | **Wrong — corrected to 16.** g07 is excluded as well as g01/g14/g20, because its floor is above the 0.45 ceiling. §1.2 |
| **RC3** | Option E = 15 groups, presented without the G4-a condition | Option E is re-derived in **both** variants: 15 groups without G4-a, **9** with it. The 6 weak groups inside the 15 are named. §2.4 |
| **RC3** | "9 vs 10 collision difference is likely a boundary convention" | **Replaced with a reproducible explanation** from the frozen file: g14's rows carry `FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE` instead of `TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE`. §1.4 |
| **RC4** | Option E cost described in one sentence | Full specification: estimands, selection rules, noise sample, run counts, budget, and the precision assumptions with their limits. §2.5 |
| **RC5** | Script used `at_floor and not in_band` as a proxy for infeasibility; no integrity checks | Model-based reachability, separate G4-a/G4-b implementation, schema + completeness + uniqueness + SHA-256 verification, 38 CPU tests. Appendix A |

Nothing in this revision widens a band, drops a cell, or reinterprets a null in the analysis
direction. Three claims were **narrowed** relative to the previous submission, which is the
direction M1 asked for.

---

## Part I — Three separate measurements

### 1.1 Measurement A: the original Headroom gate and G4 (Protocol v3 §3.6, §9)

Protocol v3 §3.6 freezes one gate: `rho0 >= 5%` **and** `R0 >= 512 tokens`, evaluated per cell on
the independent A0-only load-calibration set. §9 G4 consumes that frozen list; its rule is
"cells outside the list do not enter the estimate", not "every cell must land in a band".

Recomputed from the frozen observation file (the `iteration1_headroom_eligible` flag is not
trusted — the script recomputes it from `R0` and `W0` and requires the two to agree):

| Load | Candidate cells | Eligible | Excluded |
|---|---:|---:|---:|
| L_LOW | 20 | **18** | 2 |
| L_HIGH | 20 | **20** | 0 |
| **Total** | **40** | **38** | **2** |

The two exclusions, with their cause:

| Cell | `rho0` | `R0` | Fails |
|---|---:|---:|---|
| g09 L_LOW | 0.0448 | 1,552 | ratio only (4.48 % < 5 %) |
| g18 L_LOW | 0.0000 | 0 | both (zero recomputation) |

**Therefore the original G4 is not what fails.** On the current frozen parameters it would admit
38 of 40 cells and exclude 2, both on the L_LOW arm. If the Headroom list were frozen today from
iteration-1 data, G4 would be satisfied.

G4 is nonetheless blocked, and the reason is procedural rather than threshold-based: §3.6 requires
the list to be frozen **at frozen load parameters**, and §5.2's load calibration never settled
those parameters. So the honest status is:

> `G4_ORIGINAL = PENDING_LOAD_PARAMETER_FREEZE` — its threshold is satisfied on the data that
> exists (38/40), but its precondition (frozen load parameters) is not met. **No statement that
> the original G4 "fails" is supported, and none is made here.**

### 1.2 Measurement B: the L_LOW / L_HIGH load-calibration target (§5.2)

This is a different quantity: did `required_blocks` place `rho0` inside `[0.05, 0.15]` /
`[0.25, 0.45]`? Evaluated on the legal grid `required_blocks ∈ [16, 2032]`, quantum 16, using the
same two-point secant the frozen iteration-2 proposal uses.

| Load | Measured inside target | Reachable at some legal pressure | Reachable off the 16-block floor |
|---|---:|---:|---:|
| L_LOW | 1 of 20 (g16) | **7 of 20** | 7 |
| L_HIGH | 7 of 20 (g03, g04, g08, g09, g12, g16, g18) | **16 of 20** | 16 |
| **Total** | **8 of 40** | **23 of 40** | **23 of 40** |

The 8 measured passes match the pack's own `iteration1_target_pass_count: 8`.

**Correction (RC3).** The previous submission claimed L_HIGH was achievable in 18 groups. It is
**16**. The four groups that cannot reach `[0.25, 0.45]` are:

| Group | floor (extrapolated) | why it cannot reach L_HIGH |
|---|---:|---|
| g01 | 0.5513 | floor already above the 0.45 ceiling |
| g07 | 0.5200 | floor already above the 0.45 ceiling — **this is the group the previous count missed** |
| g14 | 0.6386 | floor already above the 0.45 ceiling |
| g20 | 0.6191 | floor already above the 0.45 ceiling |

g15 is counted as reachable but flagged: its L_HIGH window is **2 grid points**, one of which is
the 16-block floor itself. Under the G4-b floor clause it contributes one usable point at 32
blocks. It should not be treated as a comfortable L_HIGH group.

**Groups supporting a genuine two-level contrast** (both bands reachable at pressures separated by
at least one quantum): **7 of 20** — g03, g05, g09, g10, g16, g18, g19.

### 1.3 Cell-level classification (the four categories M1 asked for)

| Category | Cells | Which cells |
|---|---:|---|
| **Legal-range infeasibility** (responds, but no legal pressure reaches the band) | **11** | g02 L_LOW, g04 L_LOW, g06 L_LOW, g07 L_LOW, g07 L_HIGH, g08 L_LOW, g11 L_LOW, g12 L_LOW, g13 L_LOW, g15 L_LOW, g17 L_LOW |
| **Pressure-insensitive response** (`Δρ < 0.01`) | **6** | g01 L_LOW, g01 L_HIGH, g14 L_LOW, g14 L_HIGH, g20 L_LOW, g20 L_HIGH |
| **L_LOW / L_HIGH non-discriminability** | **0 at cell level** | the failure is a property of a *pair*, reported in §1.4 |
| **Predicted reachable** | **23** | 13 measured + 5 interpolated + 5 extrapolated (§1.5) |
| **Total** | **40** | |

g07 fails **both** bands and is counted once. The 23 "reachable" cells are not evidence of control
until the evidence class of each is stated — that is §1.5.

### 1.4 Group-level verdicts

| Verdict | Groups | List |
|---|---:|---|
| **Two-level contrast supported** | **7** | g03, g05, g09, g10, g16, g18, g19 |
| **Both loads resolve to the same proposed pressure** | **10** | g01, g02, g06, g07, g11, g13, g14, g15, g17, g20 |
| **L_LOW infeasible, L_HIGH fine** | **3** | g04, g08, g12 |
| **Total** | **20** | |

**The 9-versus-10 count, resolved without speculation.** The frozen proposal tags each row with a
`limitation` string. Counting *all* colliding groups gives **10**. Counting only collisions where
**both** rows carry `TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE` gives **9**. The single group
outside the second count is **g14**, whose two rows carry
`FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE_FROM_ITERATION1` instead.

```
unrestricted                                      : 10 -> g01 g02 g06 g07 g11 g13 g14 g15 g17 g20
both rows tagged TARGET_PREDICTED_BELOW_MINIMUM.. :  9 -> g01 g02 g06 g07 g11 g13     g15 g17 g20
only outside the tagged subset                    : g14
  g14 tags: L_LOW=FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE_FROM_ITERATION1
            L_HIGH=FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE_FROM_ITERATION1
```

This is a property of the frozen file, reproducible with `collision-report.json`, not a boundary
convention. **A residual possibility remains that M1 was reading a different field.** If so, the
script prints both counts side by side and the difference set, so the disagreement localises
immediately instead of being argued about.

### 1.5 Measurement C: evidence class, and why the "floor" cannot be called measured

Every derived value now carries an evidence class:

| Class | Definition | Count (of 40 cells' reachability verdicts) |
|---|---|---:|
| `MEASURED` | the band contains 256 or 1024 blocks | 13 |
| `INTERPOLATED` | the band is reached strictly between 256 and 1024 | 5 |
| `EXTRAPOLATED` | the band is reached only outside `[256, 1024]` | 5 |
| `NONE` | the band is unreachable on the grid | 17 |

Two facts force the "floor" to be relabelled:

1. **The extrapolation distance is large.** 16 blocks is 240 blocks below the lowest measured
   pressure, i.e. the model is asked to run at **6.25 %** of the smallest pressure it was fitted to.
2. **For four groups the extrapolation is physically impossible.** The two-point secant returns a
   *negative* `rho0` at 16 blocks:

| Group | `rho0` at 16 blocks (extrapolated) | Reading |
|---|---:|---|
| g09 | **−0.0743** | negative recomputation ratio — not a physical quantity |
| g16 | **−0.1022** | same |
| g18 | **−0.1357** | same |
| g19 | **−0.0401** | same |

A negative recomputation rate cannot be measured, so it certainly cannot be called "the
pressure-independent recomputation". For these four groups the model is simply invalid below the
measured range; the g09/g16/g18/g19 L_LOW rows are exactly the ones whose "reachable at 384/256/
480/176 blocks" claims the previous submission reported confidently. Those remain *predictions
under a model that is already known to break in that regime*.

**Where the floor story survives, it survives as a model-conditional statement.** For the 13
groups whose floor is finite, positive and above the L_LOW ceiling, the floor accounts for
**80.5 %–100 % of the recomputation measured at 256 blocks, median 93.6 %**. That is the honest
version: *within the two-point linear model*, most of what is measured at low pressure is not
explained by the pressure parameter. Establishing it directly would require an A0 run at
`required_blocks = 16`, which is a new calibration run and is not authorised.

**Terminology.** `slope / 16` is now called the **empirical marginal response ratio** — it is the
observed recomputation growth per block of pressure, expressed as a multiple of the 1:1 value. It
is *not* asserted to be the fraction of forced releases that cost a block; that interpretation
would need per-block eviction evidence the pack does not contain.

| Ratio | Groups |
|---|---|
| exactly 1.00 (within 1 %) | 7 — g03, g04, g06, g07, g08, g09, g12 |
| super-marginal (> 1.15) | 5 — g05 1.67, g10 1.97, g16 1.96, g19 2.15, g02 1.31 |
| sub-marginal 0.9–1.0 | 3 — g11 0.92, g18 0.96, g13 0.99 |
| far below 1 (≤ 0.71) | 5 — g01 0.15, g14 0.00, g20 0.11, g15 0.70, g17 0.65 |

Pressure-response strata (`Δρ` = difference between the two *measured* points):

| Stratum | Definition | Groups |
|---|---|---:|
| **FLAT** | `Δρ < 0.01` | 3 — g01, g14, g20 |
| **WEAK** | `0.01 ≤ Δρ < 0.10` | 8 — g02, g06, g07, g08, g11, g13, g15, g17 |
| **RESPONSIVE** | `Δρ ≥ 0.10` | 9 — g03, g04, g05, g09, g10, g12, g16, g18, g19 |

The decisive single datum remains **g14**: `R0 = 113,792` and `W0 = 178,200` **identically** at 256
and 1024 blocks. This one is not an extrapolation — it is two measured runs that agree exactly.
Zero response is measured there, not predicted.

**8 of the 23 predicted in-band cells sit at the 16-block floor**, i.e. they are in band only
because the extrapolated value happens to land there:
g02 L_HIGH 0.3682, g03 L_LOW 0.1069, g05 L_LOW 0.1225, g06 L_HIGH 0.3756, g11 L_HIGH 0.3859,
g13 L_HIGH 0.3638, g15 L_HIGH 0.4488, g17 L_HIGH 0.4136. These are **predictions at an
extrapolated pressure**, not controlled measurements, and 6 of the 8 belong to WEAK groups.

**Scale of the extrapolation in the frozen proposal.** 25 of 40 proposed pressures are clamped to
the 16-block floor, and 27 of 40 lie outside `[256, 1024]`. The iteration-2 proposal is
**two-thirds extrapolation**. That is a fact about the proposal, not a criticism of it, and it is
the main reason its predictions should not be treated as measurements.

---

## Part II — G4 Revision Proposal

### 2.1 Q1 restated: which assumption is actually violated?

With the gates separated, the answer is narrower than in the previous submission:

| Assumption | Status |
|---|---|
| "`required_blocks` can place `rho0` anywhere in `[0.05, 0.45]`" (§5.2) | **Violated for 13 of 20 groups** in the direction of the lower band, and for 4 groups in the direction of the upper band. This is the load-target failure. |
| "The Headroom gate can select measurable cells" (§3.6 / G4) | **Not violated** — it admits 38 of 40 on existing data. |
| "The two-point linear model is usable at 16 blocks" | **Violated for at least 4 groups** (negative `rho0`). Extrapolation must be labelled, not trusted. |

So the revision is about the **load target and its evidence class**, not about G4's threshold.

### 2.2 Q2: separating base contention from controlled pressure

Do it by construction, report it as first-class, and label the evidence class:

| Metric | Definition | Evidence class |
|---|---|---|
| `rho0_measured_at_256` / `_at_1024` | the two observations | **MEASURED** |
| `empirical_marginal_response_ratio` | `slope / block_size` from the two observations | **MEASURED** (a secant over measured points) |
| `rho0_model_at_16` | the same secant evaluated at 16 blocks | **EXTRAPOLATED** — must never be published without this label, and must be suppressed when negative |
| `rho0_pressure = rho0(N) − rho0_model_at_16` | decomposition of the model | **MODEL-CONDITIONAL** |

The third row is what the previous submission got wrong by presenting it as a measured workload
property. With the label attached, the decomposition is still useful — it explains *why* the
target is unreachable — but it is an explanation of a model, not an observation of contention.

### 2.3 Q3: what should change

**The evaluation object, not the thresholds.** Proposed gate structure, with the bands untouched:

| # | Gate | Criterion | Fails → |
|---|---|---|---|
| **G4-a Level separability** | per group | there exist two legal pressures at least one quantum apart whose model `rho0` lies one in each frozen band | group cannot support a two-level claim; classified `LEVEL_SEPARATION_UNAVAILABLE`, **retained in the report** |
| **G4-b Placement and evidence class** | per cell | the chosen pressure places `rho0` in band **and the cell's evidence class is stated**; a floor/`EXTRAPOLATED` cell counts only if the group already passes G4-a | cell not admitted to the two-level estimand |
| **G4-c Transparency** | per cell | `rho0_model_at_16` (when physical), `empirical_marginal_response_ratio`, `evidence_class` all published | calibration report incomplete |

Rules that keep this from becoming a relaxation:

1. **Bands unchanged.** `[0.05, 0.15]` and `[0.25, 0.45]` stay. Any new band is a separate
   adjudication (§2.4 shows exactly what a new band would buy, so it cannot be smuggled in).
2. **A floor cell cannot establish separability**, but it may be an operating point inside a group
   whose separability is established elsewhere. Otherwise g03 and g05 are wrongly rejected — the
   mirror error of accepting g02.
3. **Negative extrapolations are disqualified outright.** A model that predicts `rho0 < 0` cannot
   be used to argue a band is reachable at that pressure.
4. **Group selection stays blind to algorithm outcomes** — calibration is A0-only, so this holds by
   construction, but it belongs in G0 so it cannot drift.
5. **The estimand must be restated**, not silently shrunk. See §2.5 and §3.1.

### 2.4 Q4 and RC3: options, and Option E re-derived

| Option | What it does | Groups | New constants? | New GPU? |
|---|---|---:|---|---|
| **A** | two-level design on the 7 separable groups | 7 | none | no (reuse calibration) |
| **A′** | one level per group, chosen at a **measured** pressure whose `rho0` lies in one of the **two frozen bands** | **12** | **none** | no |
| **B** | reselect groups from the 80 unmaterialised candidates | up to 20 | new acquisition | **yes** — new calibration |
| **C** | move the pressure axis to KV pool size | — | — | **rejected**: violates the frozen 2048-block pool |
| **D** | decision-level (G3-CM) only, no token estimand | 12–20 | none | no |
| **E** | one level per group with a **new contiguous band `[0.15, 0.45]`** | **15** | **yes, one** | no |

**Option E has a condition the previous submission omitted (RC3).** Six of the 15 groups are WEAK
(`Δρ < 0.10`): **g02, g06, g08, g11, g13, g17**. So:

- **E with G4-a required → 9 groups**: g03, g04, g05, g09, g10, g12, g16, g18, g19.
  This is exactly the RESPONSIVE set.
- **E without G4-a → 15 groups.**

**Why a single-level design can legitimately drop G4-a — and what it costs.** G4-a answers "can
pressure move the level?", which is a **design** question needed only if the claim is *about
pressure*. A single-level design claims only "at this pre-registered operating point, A3 differs
from A0/E0 by Δ". For that claim the level does not need to have been moved; it needs to be
measurable, which is exactly the Headroom condition (`ρ0 ≥ 5 %`, `R0 ≥ 512`) that already admits
38 of 40. So dropping G4-a is a **claim change, not a threshold change**, and it must be stated as
one: the estimand becomes conditional on an operating point rather than on a pressure contrast.

It does *not* license including the 6 weak groups in **H3**, which is about the cost of forced
release. That remains restricted (9 groups) — see §3.2.

**Option E's band is not a subset of the frozen design, and this must be adjudicated explicitly.**
The frozen design covers `[0.05, 0.15] ∪ [0.25, 0.45]`. `[0.15, 0.45]` **adds** `(0.15, 0.25)` and
**removes** `[0.05, 0.15]`. Exactly **3 groups** depend on the newly covered sub-interval:

| Group | measured `rho0` relied on | in a frozen band? |
|---|---:|---|
| g05 | 0.2316 | no (gap) |
| g10 | 0.2105 | no (gap) |
| g19 | 0.1575 | no (gap) |

And the arithmetic closes: `15 − 12 = 3`. So Option E is "**A′ + a new 0.15–0.25 sub-interval**",
and M1 can accept or reject that sub-interval as a separate decision without touching the rest.

**Option A′ is the option the previous submission should have found.** It needs no new constant, no
new run, and gives 12 groups instead of 7, because a measured `rho0` landing in *either* frozen
band is a legitimate single-level operating point regardless of which load label the iteration-1
row carried (e.g. g02's L_LOW-measured `ρ0 = 0.4076` sits in the L_HIGH band).

### 2.5 RC4: full specification of Option A′ / Option E

This section answers RC4 completely for the two candidates worth considering. **M1 decides; M4
recommends.**

#### 2.5.1 Operating point and group selection rule

| Step | Rule | Frozen before? |
|---|---|---|
| 1 | Candidate pool = 20 groups of iteration 1 | yes |
| 2 | For each group, the operating point is the **measured** pressure (256 or 1024) whose `rho0` lies in the target band. Ties resolved by "lower `R0`" (cheaper), then by group id. | must be written into G0 |
| 3 | Groups with no measured in-band point are excluded from the token estimand | must be written into G0 |
| 4 | Selection uses **A0 calibration data only**, never an algorithm arm | holds by construction |
| 5 | The rule and its result are SHA-256 bound into G0 | must be added |

Result: **12 groups** (A′), or **15** with the new band (E). Both counts come from data that
already exists; **neither requires a new GPU run.**

#### 2.5.2 Estimands under each design

| Hypothesis | v3 as written | Option A′ (12) | Option E (15) | Option E∩G4-a (9) |
|---|---|---|---|---|
| **H1** A3 vs A0, token Δ | 40 cells, 2 levels | 12 cells, 1 level | 15 cells, 1 level | 9 cells, 1 level |
| **H2** A3 vs E0, token Δ | 40 cells | 12 cells | 15 cells | 9 cells |
| **H2 decision-level** | 40 decisions | 12 decisions | 15 decisions | 9 decisions |
| **H3** A0 vs N0 | 40 cells | 12 cells | 15 cells | **9 cells** (weak groups excluded) |
| **Dose-response** | supported | **lost** | **lost** | **lost** |
| **Arm × pressure interaction** | supported | **lost** | **lost** | **lost** |

The estimand sentence that would have to be frozen with the design:

> "Mean per-request difference in `Σ(E−C)` between arm and A0 for agent-style workloads whose
> prefill recomputation is at least 5 % of prefill and 512 tokens at a pre-registered operating
> point in a 2048-block KV pool."

versus v3's implicit "…workloads at two controlled pressure levels". The population shrinks from
20 groups to 12 or 15, and the pressure contrast disappears.

#### 2.5.3 Run counts

Main campaign = 6 arms × cells × R=1, with 1 `FORCED_RELEASE_DECISION` per run (§5.3):

| Design | Cells | Main-campaign runs | A3 decisions available for G3-CM |
|---|---:|---:|---:|
| v3 as written | 40 | 240 | 40 |
| Option A | 14 | 84 | 14 |
| **Option A′** | **12** | **72** | **12** |
| Option E | 15 | 90 | 15 |
| Option E∩G4-a | 9 | 54 | 9 |
| Option D | 12–20 | 72–120 | 12–20 |

**G3-CM becomes the binding constraint, and it is worse than "harder".** The gate requires **≥ 8
discriminable decisions**. As a fraction of available decisions:

| Design | decisions | fraction that must differ for G3-CM |
|---|---:|---:|
| v3 | 40 | 20 % |
| A′ | 12 | **67 %** |
| E | 15 | **53 %** |
| E∩G4-a | **9** | **89 %** |

On 9 decisions, G3-CM requires 8 of 9 to differ — a single non-discriminating decision fails the
gate. **This is the strongest argument against E∩G4-a and for A′ or E**, and it is a reason the
previous submission's "Option E recommended" was under-argued.

Whether decisions can be increased without new groups is a design question for M1: `R` (repeats) is
explicitly *not* an independent unit (§6.3), so repeats do not fix this.

#### 2.5.4 Noise calibration

| Item | v3 | Single-level design |
|---|---|---|
| Sample | 5 groups × 2 loads × R=3 | 5 groups × **1 level** × R=3 = **15 runs** (df 10) |
| Better | — | **9 or 10 groups × 1 level × R=3 = 27–30 runs** (df 16–18) |
| Output | `σ_run`, `σ_δ = √2·σ_run`, `tied = 2√2·σ_run` | unchanged |
| Groups chosen from | final campaign population | final campaign population |

**Required action:** the current 30-run design cannot be reused as-is, because its sample is defined
over two levels per group. It must be re-specified over the final population and **re-run** — this
is a genuine cost of every option, including A′. Reusing iteration-1 A0 data would not measure
run-to-run variance at all (R=1).

Recommended: **9 groups × 1 level × R=3 = 27 runs**, df = 18, relative SE of `σ_run` ≈ 16.7 %
(v3: df 20, ≈ 15.8 %). Drawing 9 of 12 or 9 of 15 groups leaves the noise groups inside the effect
population; §6.4 requires independence from the *Headroom decision*, not from the group pool, but
M1 should confirm that reading.

#### 2.5.5 Total GPU budget

No GPU-hours are quoted, because M6's measured per-run cost (§5.1 item 3) is not available to me
and inventing one would be exactly the kind of number M1 has been rejecting.

| Design | Calibration | Noise | Main | **New runs** |
|---|---:|---:|---:|---:|
| v3 as written | 0 (already executed) | 30 | 240 | **270** |
| Option A | 0 | 30 | 84 | **114** |
| **Option A′** | **0** | 27 | 72 | **99** |
| Option E | 0 | 27 | 90 | **117** |
| Option E∩G4-a | 0 | 27 | 54 | **81** |
| Option B | 40 (new) | 30 | 240 | **310** |

All options reuse the 40 already-executed calibration runs, because they keep the measured
pressures. **Option B is the only one that needs new calibration.** Every option is cheaper than
v3; the previous submission's "Option E is cheaper than v3" was true but not the interesting fact.

#### 2.5.6 Statistical precision: assumptions and their limits

| Design | groups | Planned CI half-width | relative to n=20 |
|---|---:|---:|---:|
| v3 | 20 | ±876 tokens | 1.00× |
| Option E | 15 | ±1,012 tokens | 1.16× |
| **Option A′** | **12** | **±1,132 tokens** | **1.29×** |
| Option E∩G4-a | 9 | ±1,307 tokens | 1.49× |
| Option A | 7 | ±1,482 tokens | 1.69× |

**These are planning figures, not achieved precision, and the following limits apply:**

1. **The group SD = 2,000 tokens is an assumption**, inherited from Phase 2E/2G observations. It is
   not measured for Phase 3 and not measured for the 12/15 selected groups. If the selected groups
   are more homogeneous than the full pool — plausible, since they share a `ρ0` range — the true
   half-width will be *smaller*, but that is a hope, not a guarantee.
2. **A bootstrap CI has no small-sample coverage guarantee.** At n = 12 the bootstrap distribution
   of the mean is built from 12 points; the interval is an estimate, and §6.2's 10,000 resamples
   control Monte-Carlo error, not sampling error.
3. **The half-width is a *width*, not a decision.** §6.2's rule is CI-based; with a wider interval,
   `NO_DETECTABLE_EFFECT` becomes more likely for a real but modest effect. That is a loss of
   sensitivity, and it must be stated in the report rather than absorbed.
4. **Wilcoxon power degrades roughly as `n·d²`.** At n = 20, `d ≥ 0.66` gives 80 % power; the same
   product implies `d ≈ 0.76` at n = 15, `≈ 0.85` at n = 12, `≈ 0.98` at n = 9. These are
   approximations from the same scaling argument §6.3 uses, not exact power calculations — and §6.3
   already declines to make p-value claims, so they matter only as a statement of sensitivity.
5. **G3-CM is checked against available decisions (§2.5.3)**, which is the binding constraint, not
   the CI.

### 2.6 Recommendation

The trade-off is narrow and should be stated as such rather than resolved by preference.

| Consideration | Favours |
|---|---|
| No new constant, no band-coverage change | **A′** |
| G3-CM headroom (8 of 12 = 67 % vs 8 of 15 = 53 %) | **E** |
| Planned precision (±1,132 vs ±1,012) | **E** |
| Population coverage (12 vs 15 groups) | **E** |
| Avoids the exact change M1 flagged (widening what counts) | **A′** |

**Recommended: A′, with Option E as the pre-authorised fallback.** The reasoning is that the two
sides of the trade-off are not symmetric in kind. Choosing A′ risks a `NOT_EVALUABLE` verdict on
H2 — and §6.2 already prescribes that verdict as a legitimate outcome, not a failure. Choosing E
changes what counts as a measurable level, which is the specific failure mode M1 asked this
analysis to guard against. A design that risks an honest `NOT_EVALUABLE` is preferable to one that
risks an unearned `SUPPORTED`.

If M1 judges G3-CM to be the binding risk instead, **E becomes the better choice**, on condition
that the 0.15–0.25 sub-interval is adjudicated as a new constant (3 groups depend on it), and that
H3 stays restricted to the 9 RESPONSIVE groups.

**Option A (7 groups) should not be chosen** unless the two-level contrast is worth 1.69× precision.
**Option B is the statistically cleanest** and the only one requiring new authorisation.
**Option C is rejected** (violates the frozen pool). **Option D** is a legitimate fallback if the
token estimand is judged unaffordable; its H2 decision-level component survives any of the above
designs.

---

## Part III — Downstream Gate Impact

### 3.1 What survives

| Item | Status |
|---|---|
| Evidence layers L1–L4 | **Unaffected** — they describe how a claim is established, not which cells are analysed |
| H1, H2 as paired token comparisons | **Valid, narrowed population** — from 20 groups to 12 or 15; external validity narrows accordingly |
| H2's decision-level component | **Intact** and relatively more important |
| G3-CM definition | **Unchanged, harder to satisfy** — see §2.5.3; this is the binding constraint |
| Noise calibration method | **Independent of G4**, but must be re-specified and re-run |

### 3.2 What loses its basis — and what is only a prediction

| Item | Loss | Why |
|---|---|---|
| **H3 on the FLAT groups** | **Severely damaged** | Below is a **prediction**, not a measurement: with `empirical_marginal_response_ratio` 0.00–0.15 for g01/g14/g20, forced release is expected to cost almost nothing, so `A0 − N0` is predicted to be ≈ 0. **No N0 arm has ever been run**, so this is a design prediction that the campaign would confirm or refute — it is not an observed null, and it must be reported as a prediction if it is reported at all. What *is* observed is that pressure does not move recomputation for these groups. |
| **H3 on the WEAK groups** | Weakened | ratio 0.65–1.31 leaves partial leverage; H3 there is estimable but its magnitude will be small |
| **Dose-response** | **Lost** under A′, E, and E∩G4-a | one level per group cannot express it; it was never one of H1/H2/H3 |
| **Arm × pressure interaction** | **Lost** | same reason; not a stated hypothesis, but a predictable reader question |
| **"A3 helps more when pressure is high"** | **Unavailable** | no second level, and for 13 groups no low-pressure counterfactual at all |
| **Generalisation of token-delta magnitude** | **Weakened** | the estimand covers pressure-controllable or in-band workloads only |

### 3.3 What must stay locked until G4 is re-approved

| Item | State |
|---|---|
| Second GPU calibration round | **LOCKED** |
| Noise calibration | **LOCKED** — must be re-specified over the final population, then run |
| Main campaign | **LOCKED** — n and estimand unsettled |
| Protocol v3 | **UNMODIFIED** |
| G4 verdict | **NOT PASSED, NOT FAILED BY ITS OWN THRESHOLD** — it is `PENDING_LOAD_PARAMETER_FREEZE` (§1.1) |
| Frozen workload, 2048-block pool, iteration-1 evidence | **UNCHANGED** |

### 3.4 A separate blocker that must not be folded into G4

`phase3-concurrent-eligibility-rejection-audit-v1` failed closed:

```
audit_row_count: 40, qualified_count: 0, rejected_count: 40
status: FAIL_CLOSED
uses_c_to_compute_e: false
independently_qualified_e: 0   (all 40 rows)
qualification_result: REJECTED_SAME_WAVE_PREFILL_NOT_COMPLETE_BEFORE_CONSUMER_LOOKUP  (40/40)
```

- All 40 audited pairs have `hash_lcp_tokens == native_c == 112`, so `E = C` there and their
  contribution to `Σ(E−C)` is **zero** — conservative in direction.
- `uses_c_to_compute_e: false` means §3.2's arm-independence requirement for `E` is **not**
  violated by this audit.
- The audit covers **one pair per cell**, so `E` on the remaining pairs is unverified.

**This is an independent item (G-E).** It is not caused by, and is not resolved by, the reachability
question. It should be adjudicated separately and must neither block nor be blocked by G4.

### 3.5 Recommendation to M1

1. **Record G4 as `PENDING_LOAD_PARAMETER_FREEZE`**, not as failed. Its threshold is satisfied on
   existing data (38/40); its precondition is not met. Record the §5.2 load-target failure separately,
   with `LEVEL_SEPARATION_UNAVAILABLE` for 13 of 20 groups.
2. **Adopt G4-a / G4-b / G4-c**, with the bands unchanged and extrapolation explicitly labelled.
3. **Choose the design.** Recommended: **A′ (12 groups, one level, no new constant, 99 new runs)**.
   Acceptable alternative: **E (15 groups)** only with the 0.15–0.25 sub-interval adjudicated as a
   new constant. **A (7)** only if the two-level contrast is worth 1.69× precision. **B** needs new
   authorisation. **C** rejected. **D** is the fallback.
4. **Re-specify and re-run the noise calibration** on the final population (9 × 1 × 3 = 27 runs
   recommended).
5. **Restate the estimand** in the next protocol version, including the loss of dose-response.
6. **Adjudicate G-E separately.**

---

## Part IV — What I am explicitly not proposing

- Not proposing new bands as *inherited* constants; the one new interval is named, quantified
  (3 groups) and offered for adjudication.
- Not proposing to relax any threshold: `[0.05, 0.15]`, `[0.25, 0.45]`, `ρ0 ≥ 5 %`, `R0 ≥ 512`,
  `≥ 8` discriminable decisions all stay.
- Not proposing to re-run the 40-cell calibration with different parameters, or any new calibration.
- Not proposing to touch the 2048-block pool, the frozen workload, or iteration-1 data.
- Not proposing to declare G4 PASS — and no longer claiming it fails by its own threshold.
- Not proposing to modify Protocol v3.

---

## Appendix A — Reproducibility (RC5)

```bash
python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
    --pack local/phase3-g4-reachability-analysis-pack-v1 \
    --out  local/phase3-g4-reachability-m4

python -m pytest tests/test_g4_reachability_analysis.py -q   # 38 passed, CPU only
```

**Integrity.** The four frozen planning inputs are SHA-256 pinned in the script and cross-checked
against the pack manifest, and the proposal's own `source_observations_sha256` is required to bind
the pinned observation hash:

| Input | SHA-256 |
|---|---|
| `iteration1-cell-observations.json` | `a47acef4a96cbedec37d88c941c70a8ed30f3208d7cac8ec1d599acb6d876d5a` |
| `iteration1-cell-observations.csv` | `2fb77aae8dd734860e7a3664f724fad2113db263ea63f806656abad4975179ec` |
| `iteration2-required-blocks-proposal.json` | `1b59758a7ef8b5d0b42c4431fa0d2983d27062bf5d89c4a0b4b01175ff3c36a8` |
| `iteration2-required-blocks-proposal.csv` | `49738f3715a945038c566f2260eb50053b7fb68760e8ac5b60bcc9bb112d8a36` |

**Schema and completeness checks enforced before any number is computed:**

| Check | Failure mode it catches |
|---|---|
| `cell_count == 40` in both documents | truncated export |
| exactly 20 distinct groups, 2 loads each | missing group silently shrinking n |
| `(group, load)` unique in both files | duplicated cell inflating a rate |
| `rho0 == R0/W0` within 1e-9 | hand-edited ratio |
| `iteration1_headroom_eligible` recomputed and compared | a stale flag contradicting §3.6 |
| `original_required_blocks` equals the frozen 256/1024 | a silently re-parameterised iteration 1 |
| proposed pressure on `[16, 2032]` and the 16-block quantum | off-grid extrapolation |
| proposal band equals the frozen band for that load | a band changed in the data instead of the protocol |
| proposal `source_observations_sha256` == pinned observation hash | the two inputs coming from different runs |
| two-point model reproduces every frozen `predicted_rho0` to 1e-9 | model drift between M4 and the frozen proposal |

**Outputs**: `cell-classification.json`, `group-summary.json`, `headroom-report.json`,
`load-target-report.json`, `option-report.json`, `collision-report.json`,
`precision-report.json`, `cells.csv`, `groups.csv`.

**Tests** (38, CPU only, no GPU, no network): schema rejection × 9, SHA-256 integrity × 4 (missing
input, pin mismatch, manifest disagreement, clean pack), model reproduction of a frozen
`predicted_rho0`, evidence-class labelling, empirical ratio on a synthetic 1:1 group, the four
cell classifications, G4-b floor clause both ways, collision counting (the 9-vs-10 case),
option-set additivity (`E = A′ + gap`), precision-table consistency, and an end-to-end run against
the real pack that skips when `local/` is absent.

## Appendix B — Threshold provenance

| Threshold | Value | Provenance |
|---|---:|---|
| `block_size` | 16 tokens | frozen runtime config |
| `minimum_blocks` / `maximum_blocks` / `quantum` | 16 / 2032 / 16 | frozen proposal `method` block, re-validated |
| L_LOW / L_HIGH bands | `[0.05,0.15]` / `[0.25,0.45]` | Protocol v3 §5.2, frozen |
| Headroom ratio / absolute | 5 % / 512 tokens | Protocol v3 §3.6, frozen |
| G3-CM discriminable decisions | ≥ 8 | Protocol v3 §9, frozen |
| `tied` | `2√2·σ_run` | Protocol v3 §6.4, unchanged |
| FLAT | `Δρ < 0.01` | below the design's block granularity at observed prefill sizes |
| WEAK | `Δρ < 0.10` | the gap between the L_LOW ceiling and the L_HIGH floor; below it no band crossing is possible |
| Option E band | `[0.15, 0.45]` | **proposed, not inherited** — covers 0.15–0.25 which no frozen band covers; 3 groups depend on it |
| Planning group SD | 2,000 tokens | Phase 2E/2G observation, used for planning only |

## Appendix C — RC response map

| RC | Where answered |
|---|---|
| RC1 separate load target from original G4 | §1.1, §1.2, §0 |
| RC2 measured vs extrapolated, conditional conclusions, renamed ratio, prediction labels | §1.5, §2.2, §3.2, Appendix B |
| RC3 Option E re-counted, G4-a condition, L_HIGH 16, 9-vs-10 explained | §1.2, §1.4, §2.4 |
| RC4 full Option E cost and precision limits | §2.5.1–§2.5.6 |
| RC5 script fixes, schema/completeness/uniqueness/SHA-256, CPU tests | Appendix A, §0 |
