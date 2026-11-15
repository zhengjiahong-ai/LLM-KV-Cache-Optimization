# Post-Phase-4 Research Analysis: Why Cost-Aware Did Not Separate from A0, and What the Next Round Must Test

**Author:** M4  
**Status:** `RESEARCH_ANALYSIS_ONLY` — no algorithm implementation, no GPU run, no Native smoke, no Protocol v5, no new data acquisition.  
**Base:** `main` after PR #104/#109/#110, `edf9b80103803d49edb803747a69094292ec1051`.  
**Primary inputs:** Phase 3 null-mechanism analysis, Phase 3 actual-order audit, P2 depth study, R1.3 cross-phase synthesis, W1-C feasibility pilot, Phase 4 session-continuation study.  
**Related protocol:** Protocol v4 remains frozen; this document does not amend it.

---

## 0. Executive answer

The current Cost-Aware policies did not produce an incremental benefit over A0 because the experiment rarely created a decision in which a different policy could produce a different, measurable outcome. The primary problem is not that the cost formulas were insufficiently complex. It is that:

1. **candidate exposure was low** — 120 of 127 forced-release events had one legal Entry candidate; only 7 had two;
2. **the competing candidates were ordered identically by the tested keys** — deadline, `q`, and the suffix proxy all selected the same Entry in the seven competitive events;
3. **the branch ladder that could distinguish A1/A3 was unreachable** — `new_blocks >= need` was true for 134/134 candidates, so every decision stopped at Step 2;
4. **Entry granularity removed the “how much to release” dimension** — one entry unlocked 389–1850 blocks against a need of 36–128, and the physical release quantum was 128 blocks in 19/127 decisions;
5. **the tested value models did not target the actual downstream victim set** — A1/A3 used `q`, `new_blocks`, and suffix geometry, while the realized damage depends on which Native blocks are evicted and how deep the truncated chain is later reused;
6. **the measurable outcome surface was thin** — the A0−N0 difference appeared only at the last request in 20/40 cells, and only 7 competitive decisions carried the possible selection effect.

The correct conclusion from the current campaign is therefore:

> **No observed incremental benefit under a design with seven competitive opportunities.**  
> This is not evidence that Cost-Aware eviction is universally ineffective, and it is not evidence that A1/A2/A3 are equivalent to A0.

The next round should not add another score to the same degenerate decision geometry. It should first establish that a **natural, representative workload actually exposes multiple legal, content-verified candidates with distinguishable downstream victim sets**, and only then test a value model on those states.

My route recommendation is:

- **P1 (candidate exposure) is the primary direction**, but only as a **natural-exposure audit**, not as “increase pressure until candidates appear.”
- **P2 (cost/value model) should run in parallel only as a deterministic, CPU-only diagnostic**, not as a full independent research line. Learned depth predictors should wait for P1 to produce a real decision population.
- **A1/A3 should remain paused as optimization targets.** A0/E0 remain comparators; A1/A3 code remains an analysis reference.
- **A2 should remain a diagnostic/negative control**, not the main optimization target.
- **P3 (partial/granular release) should remain deferred**, but it is a real alternative if P1 shows that the binding constraint is entry granularity rather than workload geometry.
- **A capacity/serving-level objective may be more valuable than another depth model** if P1 confirms that the current loss-only objective misses the actual system benefit.

---

## 1. Current mechanism diagnosis

### 1.1 The zero is a selection-agreement zero, not a result-collapse zero

The Phase 3 null-mechanism analysis establishes a precise distinction:

- all release-enabled arms had 127 forced-release decision events across 39 cells;
- A0/A1/A2/A3/E0 produced **3,840 identical request-level N/E/C comparisons** in the paired event set;
- predicted victims were a subset of the physical eviction set (`12,545 = 12,545`), and `predicted_victim_count == need` in 127/127 decisions;
- therefore the choice **does** determine the physical eviction set and the truncation depth;
- the arm policies simply **never chose different objects**.

This rules out “the downstream Native LRU erased the selection effect.” It locates the null at the decision layer, not at the execution layer.

The same pattern appears in the follow-up studies:

- **Stage 0** found the A0-Anchored Prefix-State Loss Oracle upper bound to be **0 tokens** on the seven real competitive decisions; capacity gain was `NOT_EVALUATED`.
- **P2** found that P2-A/B flipped all five valid REAL decisions but produced **zero positive-gain flips**; P2-C did not flip, with zero gain. Prediction error was not the same as decision value.

### 1.2 Candidate exposure was structurally low

The key exposure facts are:

| Observation | Value | Consequence |
|---|---:|---|
| Forced-release decision events | 127 across 39 cells | Resource pressure existed |
| Single-candidate events | 120 / 127 (94.5%) | No Entry choice in most events |
| Two-candidate events | 7 / 127 (5.5%) | Only seven real competition opportunities |
| Cells with no candidate choice | 32 / 39 | Most cells never exposed a choice |
| Downstream requests after last decision | 1–2 per cell | Only a thin outcome surface |
| A0−N0 differences | 20 / 40 cells, all at the last request | The mechanism effect is real but narrow |

The campaign had **high resource pressure but low algorithm-decision exposure**. A policy invocation is not an algorithm opportunity. The relevant denominator for “could a different ordering matter?” is the 7 competitive decisions, not 127 invocations.

The reason is geometric. The Phase 3 cohort is a controlled two-session, 12-checkpoint, fixed-pressure replay with a TTL that is self-calibrated close to the inter-arrival interval. In that regime, usually only one protected Entry is still inside its retention window at the pressure moment. The problem is not a lack of memory pressure; it is a lack of **simultaneously protected, legal, distinguishable candidates**.

### 1.3 The tested ranking keys collapsed to the same order

The four Entry keys are not mathematically identical, but on this sample they produced the same program order:

- A0: `(deadline, min Native LRU rank over newly eligible blocks, identity)`;
- E0: `(deadline, identity)`;
- A1: Step 2 `q · [λN + (1−λ) min(need, N)]`;
- A3: Step 2 `(L, deadline, identity)`, with `L = q · prefill · S / m`;
- `q = sigmoid((deadline − t)/τ)` is strictly monotone in deadline.

In the seven competitive decisions:

- `q` ratios were 10.4×–874× in 6/7 cases, dominating `prefill` and `S/m`;
- g10-C1 was the exception: `q` differed by only 1.034×, A3's `L` agreed with the deadline order by only a 2.0% margin, and A1's `expected` margin was 51.6%;
- all 134 candidates had distinct deadlines, so A0's `min native rank` and E0's `identity` tie-breakers never activated;
- A3 and A1 selected the same Entry in 127/127 events;
- A2, which used a different block-level selector, produced **0 victim-sequence divergences** from Native LRU in 127/127 events.

This is a sample-specific selection agreement. The g10-C1 near-tie is important: it shows that the system was close to a divergence boundary, not that the keys are universally equivalent. But near-ties are not enough; the design needs a population of decisions where the non-deadline terms can actually change the order.

### 1.4 The branch ladder was unreachable, and the release amount was not a free variable

The A1/A3 ladder assumes it may need to choose among `step2_sufficient`, `step3_per_unit`, `step4_pair_lookahead`, and `step5_deadline_fallback`. In this archive:

- `new_blocks >= need` held for **134/134** candidates;
- every decision terminated at Step 2 (`127/127 step2_sufficient`);
- Steps 3–5 were never triggered;
- `suffix_blocks >= need` also held for all 134 candidates, with `S = need` in 122/134 and `S > need` in 12/134;
- a single Entry unlocked 389–1850 blocks against `required_blocks` of 36–128;
- in 19/127 decisions, physical eviction still released the 128-block quantum when `need < 128`.

Consequences:

1. **“Release how much” was not an available decision dimension.** Only “release whom” remained.
2. **The A1/A3 differences were compressed into the Step-2 sort key.** The part of the ladder that could have distinguished them was never reached.
3. **The value density is inverted.** Because the physical quantum over-release is `128 − need`, small-`need` decisions can be worth up to `128/need` times more per block. The seven competitive decisions all had `need ≥ 97`, the least valuable end of the distribution.

This is a design/granularity issue, not evidence that suffix-cost reasoning is theoretically wrong.

### 1.5 The value target was misaligned with the real damage

The realized damage from releasing Entry X is not “how many blocks X unlocks.” It is a function of:

- which blocks are actually evicted: `evict(X)`, not `unlock(X)`;
- whether, and how deeply, the truncated chain is reused later;
- the per-block recomputation cost;
- whether the changed release changes capacity/admission and therefore queueing or TTFT.

The tested models miss different factors:

| Arm | What it uses | What it misses |
|---|---|---|
| A0 | deadline, native rank, identity | future reuse depth, actual victim set, block cost |
| A1 | `q` and a slow-varying `expected` term | actual `evict(X)`, depth beyond suffix, block cost |
| A3 | `q · prefill · S/m` | actual `evict(X)`, depth distribution, absolute per-block cost |
| A2 | block-level cost with Native-LRU-like ranking | content identity coverage, a state where the greedy set differs, downstream attribution |

The critical numeric mismatch is `unlock(X) = 999` versus `evict(X) = 97` in the g09 example: the policy is scoring the wrong set. A3's `S/m` attempts to correct this, but `S` was equal or nearly equal across candidates, so the correction had almost no discriminating power.

### 1.6 The outcome surface was thin

The A0−N0 mechanism effect is real:

- H3-0: A0−N0 = **−3,123.2 tokens/group** over 20 Groups / 38 cells;
- primary paired N0−A0 = **+1,918.22 tokens/group** over 18 Groups;
- 20/40 cells had a difference, all at the last request;
- g18-c1 had zero release events but still a −544 token A0−N0 difference, showing that not every difference is attributable to a release choice.

But the part of the surface that could carry an **Entry-ordering** difference was much smaller:

- 7 competitive decisions;
- 1–2 downstream requests after the last decision;
- the actual difference was carried by the last request in each affected cell;
- Stage 0's loss-only oracle found zero avoidable-prefix-loss headroom on those seven decisions.

The current experiment therefore had enough pressure to test “protection vs no protection,” but not enough competition to test “which Entry to release.”

### 1.7 Workload geometry, not a universal workload fact

The Phase 3 cohort is a **controlled projection**, not a production Agent serving trace:

- 20 Groups × 2 conditions;
- 2 sessions per Group;
- 12 selected checkpoints per session;
- one controlled pressure boundary per cell;
- TTL calibrated from server-gap history to near the inter-arrival interval;
- a 2048-block pool;
- Native scheduler in all arms.

The null-mechanism analysis is explicit that “this workload lacks exploitable differences” is a statement about this geometry, not about all Agent workloads. The W1-C pilot shows long exact-prefix reuse and strong context growth, but it is a **single-Agent-worker trajectory pilot**; it does not observe Native candidate count, residency, eviction, or recomputation. W1-C therefore proves **logical reuse potential**, not **natural candidate competition**.

The actual-order audit adds a separate constraint: frozen replay conformance failed in 32/40 cells. The actual-order reconstruction supports a bounded paired-effect interpretation (E unchanged for 5,760/5,760 observations; fixed effects reproduced), but it does not make the execution conformance PASS. Any next round must preserve its own actual-order record and must not inherit the claim that the frozen order was executed.

---

## 2. Evidence assessment

### 2.1 What the evidence supports

| Claim | Evidence | Strength / boundary |
|---|---|---|
| Forced Entry Release can reduce eligible-prefix recomputation relative to no release | H3-0 −3,123.2; N0−A0 +1,918.22 | Supported within the controlled Phase 3 cohort; not full-system or production |
| The Phase 3 zero is a selection-agreement zero | 127/127 same program; 7/127 dual; A3/A1 same; A2 0 divergence | Strong within the frozen cohort |
| Candidate exposure is a distinct bottleneck from resource pressure | 127 events vs 7 dual candidates; 32/39 cells no choice | Strong descriptive evidence |
| A3's suffix proxy did not produce a different order | 7 dual; Cost/Deadline ranks identical; `S` equal or ±1 block | Strong in this cohort; not universal |
| A2 did not change the Native LRU victim set | 53 cost-known, 74 fallback, 127/127 same sequence | Strong in tested campaigns; not universal |
| Local victim-selection headroom can exist | Phase 2D shared-protected fixture, 64-token N−C difference | Local fixture only; online predictability not shown |
| Token savings do not automatically improve TTFT | Phase 2E −192 tokens/scenario, no comparable TTFT gain | Queue-dominated synthetic prefill workload |
| Current loss-only oracle has zero avoidable-prefix-loss headroom | Stage 0, seven real decisions | Capacity gain `NOT_EVALUATED`; not all Entry ordering |
| P2 depth prediction did not produce positive decision value | 5 valid REAL decisions; A/B 0 positive-gain flips | Small REAL sample; constructed scenarios separate |
| Session Continuation is not identifiable | No session_id; session≡program; no multi-session program | Data gap, not model failure |

### 2.2 What the evidence does **not** support

- **“Cost-Aware is universally ineffective.”** There were only seven competitive decisions; the experiment did not create a population where the tested value models could separate.
- **“A1/A2/A3 are equivalent to A0.”** No arm made a different selection in a competitive event; equivalence would require divergence, not only identical choices.
- **“The current workload proves natural Agent workloads lack candidates.”** It proves the controlled two-session/TTL geometry lacks candidates.
- **“W1-C proves Native candidate competition exists.”** It proves logical prefix reuse potential, not candidate count, residency, eviction, or recomputation.
- **“P2 can be fixed by a better depth estimator.”** P2's failure is partly the target/identity problem; prediction MAE and ranking accuracy did not translate into decision value.
- **“Token reduction equals serving improvement.”** Phase 2E explicitly found the opposite in its queue-dominated workload.
- **“The Stage 0 zero closes Entry ordering.”** It closes the loss-only current-cohort headroom; capacity and new natural geometries remain open.

### 2.3 What is missing

To decide whether Cost-Aware can produce a real benefit, the project still needs:

1. a **representative multi-session serving trace** with session identity, arrival times, tool gaps, concurrency, and capacity;
2. **Native candidate snapshots**: actual candidate count, legality, content identity, refcount, `need`, newly eligible blocks, and victim set;
3. **downstream per-block evidence** linking an eviction decision to later reuse depth and recomputation, not just cell-level correlations;
4. a **value target** that includes actual victim set and, if relevant, capacity/admission/TTFT effects;
5. an **exposure population** large enough to compare policies: not 7 decisions, but enough independent groups/events to distinguish “no effect” from “no opportunity.”

Without (1) and (2), a new GPU campaign would repeat the same exposure problem. Without (3), a value model can fit predictions without proving downstream value. Without (4), the project may optimize tokens that do not affect serving.

---

## 3. P1 research proposal: natural candidate exposure

### 3.1 Hypothesis

**H-P1:** The Phase 3 cohort's 5.5% multi-candidate rate is a property of its controlled two-session/TTL geometry, not of Agent/Coding workloads in general. A representative multi-session serving workload will expose a materially higher rate of legal, content-verified, distinguishable Entry candidates.

This is a hypothesis, not a premise. P1 must be able to fail.

### 3.2 P1-A: CPU-only logical exposure audit (no GPU, no Native claim)

**Question:** Under pre-registered deployment geometries, do existing Agent traces contain windows where multiple sessions/programs have live, overlapping prefix chains and a later request that could use them?

**Data:**

- W1-C S50/S100 trajectories (20 tasks, 40 runs, 12 repos);
- Phase 3 archive timelines and TTL/server-gap history;
- no new acquisition in P1-A.

**Method:**

1. Reconstruct each session's request timeline, prefix length, exact-token LCP, context growth, tool/inter-request gap.
2. Pre-register a small set of **deployment models**: session arrival/concurrency, TTL multiplier, capacity, and number of concurrent programs. These are scenario assumptions, not oracle-selected conditions.
3. For each model, compute a **logical co-residency potential**: at each decision time, how many sessions/programs have a live prefix chain that could be protected, and how many have a later request within the horizon.
4. Report the distribution of candidate potential, not a single “best” setting.

**Outputs:**

- `logical_multi_candidate_rate` by model;
- active-session/program distribution;
- prefix-overlap and context-growth distributions;
- TTL-survival probability;
- downstream-request count after candidate windows;
- sensitivity to TTL, concurrency, and capacity.

**What P1-A can prove:** whether the existing traces contain **logical** opportunities under explicit assumptions.  
**What it cannot prove:** Native candidate count, legal release, residency, eviction, or recomputation.

**Important limitation:** W1-C is a single-Agent-worker pilot. Composing independent W1-C tasks into a multi-session serving trace is a **modeling choice**, not an observed production workload. If no representative session-arrival/concurrency trace exists, P1-A must label its multi-session models **semi-synthetic** and must not claim natural exposure.

### 3.3 P1-B: minimal Native exposure audit (conditional; requires new authorization)

**Question:** In a frozen, representative subset, do actual Native decision snapshots contain ≥2 legal, content-verified candidates with distinguishable victim sets and downstream requests?

**Design:**

- freeze a small subset by pre-declared workload/geometry criteria, not by oracle gain;
- run A0 only (no policy treatment);
- capture per-decision snapshots: candidate list, program/chain identity, content verification, `ref_cnt`, `need`, newly eligible blocks, Native victim set, downstream request count;
- record actual submission order and verify conformance or explicitly model deviation;
- no A1/A2/A3 comparison in this audit.

**Why A0-only:** the question is whether a choice exists, not whether a policy is better. Running multiple policies on a single-candidate population repeats Phase 3.

**Representativeness:** if the Native audit uses a composed/synthetic session mix, label it `SEMI_SYNTHETIC`; only a trace with observed session arrivals/concurrency can support a `NATURAL` claim.

### 3.4 P1 gates (provisional; to be frozen by M1)

Do not force the result by increasing pressure or TTL. Pre-register the decision rule:

- **P1-A pass to P1-B:** at least one pre-declared realistic deployment model shows a materially higher logical multi-candidate rate than the Phase 3 baseline, with enough downstream requests to matter. If all plausible models remain single-candidate, stop: the trace does not support P1.
- **P1-B pass to policy work:** at least **8 independent Groups** with at least one actual multi-candidate event, at least **30** multi-candidate events total, and at least **10%** of multi-candidate events with distinct predicted/actual victim sets. These numbers are provisional; the final thresholds should be derived from the intended comparison’s power, not chosen after seeing outcomes.
- **P1-B fail:** if actual multi-candidate events or victim divergence remain near zero, stop Entry-ordering research on this workload family and report the exposure/evidence result. Do not lower thresholds to keep the route alive.

The gates must be evaluated on **independent Groups/Sessions**, not on turns, requests, or repeated runs.

---

## 4. P2 research proposal: cost/value model

### 4.1 The target contract

A useful value model must separate four quantities:

1. **Continuation/identity:** `P_cont(chain c | H)` — will this chain/program be reused within horizon H? This is not the same as “does any prefix overlap exist.”
2. **Depth:** `D_c` — if reused, how deep is the demand?
3. **Retained depth after the candidate:** `R_c(S)` — what remains after candidate S is released and the Native victim set is applied?
4. **Per-block cost:** `c_b` — recomputation cost per block/token, not just a prefill scalar.

The minimal form is:

```text
EL(S) = Σ_c P_cont(c | H) · E[ max(0, D_c − R_c(S)) | c continues ] · c
```

or, at block level:

```text
EL(S) = Σ_{b ∈ evict(S)} P(reuse depth of b > position(b) | H) · c_b
```

The first form is easier to estimate; the second makes the actual victim set explicit. Neither should be replaced by `unlock(S)` or by a single `q` term.

### 4.2 P2-D: deterministic downstream-loss diagnostic (CPU-only, immediate)

Before training another predictor, test whether a **deterministic victim-set-aware** score would change any decision on the existing seven competitive decisions.

**Method:**

- for each candidate, simulate the same starting eligible set, capacity target, pressure event, and Native selector;
- compute the predicted victim set and the resulting retained depth for each chain;
- compute `EL(S)` with a simple historical continuation/depth estimate or a uniform prior;
- compare the choice with A0 and E0 on the full 24-request trajectory.

**Metrics:**

- flip rate on the 7 real decisions;
- positive-gain flips and full-trajectory oracle gain;
- regret vs the best candidate;
- not MAE.

**Interpretation gate:** Stage 0 already established that the current seven decisions have zero positive loss-only headroom. Therefore **0 positive gain on these seven is expected and is not a P2 failure**. P2-D is a logic/implementation diagnostic, not a value test. It should establish:

- the score is computable from pre-decision information plus a simulated Native victim set;
- it produces a deterministic, auditable ranking;
- it can distinguish candidates where the victim sets differ;
- any positive gain on the current seven would be surprising and must be reconciled with Stage 0 before it is believed.

**Stop:** if the deterministic model cannot produce a distinguishable ranking, requires future information, or cannot be reconciled with the Stage 0 zero, do not train a learned model. A flip with zero or negative gain on the current seven is not evidence of P2 value; the value test belongs to the P1-B population.

### 4.3 P2-L: learned continuation/depth model only after P1

If P1-B produces a real multi-candidate population, then train a simple model with:

- only pre-decision features;
- group/session-isolated validation;
- labels from Native-verified future reuse (not prefix overlap);
- separate metrics for calibration/MAE and decision gain;
- comparison against A0, E0, and a simple `Sufficient-first + earliest-deadline` rule.

Do not use future victim sets, future request identity, oracle choices, or constructed scenarios as online features. Constructed scenarios may be reported only as `CONSTRUCTED`, never as real workload evidence.

### 4.4 What P2 should not do

- Do not add `q`/λ/suffix terms to the same degenerate decision geometry.
- Do not use `future_prefix_demand_overlap` as a Native cache hit.
- Do not sum local single-decision gains and call it a joint policy effect.
- Do not tune on the seven REAL decisions and report the same seven as held-out.
- Do not use prediction MAE as the primary success criterion.

---

## 5. Alternative directions

### 5.1 Capacity/serving-level objective

Stage 0 explicitly leaves **capacity gain** `NOT_EVALUATED`: a different release choice can change which blocks remain, how many blocks are available, and whether later requests are admitted or queued. The current loss-only oracle cannot see that channel. Phase 2E also shows that token savings did not produce a comparable TTFT gain in a queue-dominated workload.

This suggests a genuinely different objective:

- **capacity-aware**: does the policy preserve more reusable prefix under the same capacity, or admit more work?
- **serving-aware**: does it reduce queue delay/TTFT, not only recomputation tokens?

This may be more valuable than another depth predictor, but it requires a different measurement design and possibly a Native capacity/admission model. It should be a **second-stage alternative**, not mixed into the current token oracle.

### 5.2 Representative workload / production trace

If the project cannot obtain a representative multi-session trace, P1 cannot make a `NATURAL` claim. The highest-value data investment may be a trace with:

- explicit session/program identity;
- arrival and tool-gap timestamps;
- concurrency and capacity;
- prefix overlap and request outcomes;
- enough independent sessions to estimate exposure.

This is a data-acquisition decision for M1, not an algorithm experiment.

### 5.3 Block-layer evidence and A2

A2's 74/127 (58.3%) `content_unverified` fallback and 0 victim divergence in 53 cost-known decisions make it a weak primary route. Keep A2 as:

- a diagnostic for whether block-level divergence exists at all;
- a negative control for “more granular cost scoring”;
- a possible follow-up only if P1-B exposes block-level victim divergence.

Do not spend the next round improving A2's selector before content identity coverage and candidate exposure are established.

### 5.4 Partial-tail / granular release (P3)

P3 addresses a real mechanism: entry over-release (389–1850 blocks vs need 36–128) and the 128-block quantum. If the binding constraint is granularity rather than workload exposure, P3 could create a decision dimension that P1/P2 cannot.

But P3 requires:

- range-level protection semantics;
- shared ownership/refcount correctness;
- prefix continuity;
- concurrency atomicity;
- a Protocol v5 design.

It should remain deferred until P1 tells us whether the problem is exposure or granularity. If P1 fails because entries are too coarse/too few, P3 becomes a more credible alternative than another value model.

### 5.5 Scheduler/concurrency as a separate axis

Changing scheduler or concurrency can create more overlapping sessions, but that is a **system/workload intervention**, not a Cost-Aware policy. Phase 3 held the Native scheduler fixed. Any scheduler claim requires a separate protocol and must not be bundled into P1/P2.

### 5.6 Conservative LRU fallback / stopping rule

If natural exposure and victim divergence remain near zero, the correct engineering conclusion may be:

> Native LRU is already a strong default for this workload family; a custom selector should intervene only under a validated safe-divergence condition.

That is a legitimate negative result, not a failure to find a positive one.

---

## 6. Comparative prioritization

| Direction | Expected information | Cost | Verifiability | Risk | Recommendation |
|---|---|---|---|---|---|
| **P1-A** CPU logical exposure audit | High: tests whether natural traces can even produce candidates | Low, CPU-only | Medium: logical, not Native | Low | **Do first** |
| **P1-B** minimal Native exposure audit | High: actual candidate/victim counts | Medium; new authorization + Native run | High | Medium | **Only after P1-A passes** |
| **P2-D** deterministic downstream loss | Medium: does victim-aware scoring change existing decisions? | Low, CPU-only | High on existing 7 | Low | **Parallel with P1-A** |
| **P2-L** learned depth/continuation | Low until exposure exists | Medium | Medium | High overfit/leakage | **Wait for P1-B** |
| **A1/A3** further tuning | Low: same degenerate geometry | Low but wasted | Low | Low | **Pause as targets** |
| **A2** block selector improvement | Low: 0 divergence, 74/127 fallback | Medium | Low | Medium | **Diagnostic only** |
| **P3** partial-tail | High potential if granularity is the constraint | High; Protocol v5 + correctness | Medium | High | **Defer; revisit after P1** |
| **Capacity/serving objective** | High if token savings do not transfer | Medium–high | Medium | Medium | **Second-stage alternative** |
| **Production multi-session trace** | Necessary for a natural claim | High acquisition | High | Medium | **M1 data decision** |

### 6.1 Route answers

1. **Should P1 be the primary next direction?**  
   **Yes, conditionally.** It is the only direction that can establish whether a meaningful decision exists. But it must be a natural-exposure audit, not a TTL/pressure inflation exercise. If P1-A/P1-B fail, stop Entry ordering rather than forcing candidates.

2. **Can P2 run in parallel?**  
   **Only P2-D, the deterministic CPU diagnostic.** A learned P2 model should wait for P1. Running a full P2 campaign now would repeat the target/identity problem on the same seven decisions.

3. **Is there a better direction than P1/P2?**  
   **Capacity/serving-level evaluation** may be more valuable if the project's real objective is TTFT/throughput rather than recomputation tokens. A **representative production trace** may be more valuable than any algorithm if P1 cannot make a natural claim. P3 is a later alternative if granularity is the binding constraint.

4. **Should A1/A3 remain paused?**  
   **Yes.** A1's ladder is unreachable in the current geometry; A3's suffix term is near-constant and lacks the actual victim set. Keep them as comparators/references, not targets.

5. **Is A2 worth keeping?**  
   **As a diagnostic/negative control, yes; as the main optimization target, no.** It has the strongest evidence of “no divergence” and a 74/127 evidence fallback. Revisit only if P1-B finds block-level divergence.

6. **Should P3 be deferred?**  
   **Yes, for now.** It is a real mechanism but requires Protocol v5 and correctness work. Revisit if P1 shows exposure is limited by entry granularity rather than workload geometry.

---

## 7. Next experiment design

### 7.1 Minimal experiment E1: CPU-only exposure + deterministic value diagnostic

**Scope:** no GPU, no Native smoke, no algorithm implementation.

**E1-A (P1-A):**

- use W1-C/Phase 3 traces;
- pre-register 3–5 deployment models (session concurrency, TTL multiplier, capacity);
- compute logical candidate potential, downstream requests, prefix overlap, TTL survival;
- report all models, not the best one.

**E1-B (P2-D):**

- on the existing 7 competitive decisions (5 of which pass P2 victim-identity eligibility), compute a deterministic victim-set-aware score;
- compare against A0, E0, and `Sufficient-first + earliest-deadline`;
- report flips, positive flips, full-trajectory gain, regret;
- no learned model.

**Success:**

- E1-A: at least one pre-declared realistic model shows materially more logical opportunities than Phase 3; otherwise stop.
- E1-B: the deterministic model is computable, auditable, and produces a distinguishable candidate ranking; 0 positive gain on the current seven is expected (Stage 0) and is not a failure. E1-B does not authorize P2-L; only P1-B can do that.

**Output:** a short evidence report and a decision: proceed to P1-B, stop, or change direction.

### 7.2 Conditional experiment E2: minimal Native exposure audit

Only if E1-A passes and M1 authorizes a Native run.

- A0-only; no policy comparison;
- frozen subset selected by pre-declared workload criteria;
- capture candidate count, legality, content identity, `ref_cnt`, `need`, victim set, downstream requests;
- record actual submission order and conformance;
- no GPU campaign; this is a bounded audit.

**Success:** ≥8 independent Groups with actual multi-candidate events, ≥30 events total, ≥10% of events with distinct victim sets (provisional; finalize by power analysis).

**Failure:** stop Entry-ordering research; report exposure/evidence result.

### 7.3 Conditional experiment E3: policy comparison

Only if E2 passes.

- arms: A0, E0, simple `Sufficient-first + earliest-deadline`, and **one** downstream-victim-aware policy;
- do not run A1/A2/A3 as separate arms until the exposure gate is passed;
- primary unit: independent Group/Session;
- primary outcome: full-trajectory recomputation (E−C), with capacity/TTFT as secondary;
- success: held-out positive gain vs A0 and simple rule, not a single outlier;
- stop: no positive gain, or no victim divergence.

### 7.4 Common guardrails

- Do not increase TTL/pressure solely to create candidates; that is an intervention, not natural exposure.
- Do not select the subset by oracle gain or by “where A3 wins.”
- Do not pool campaigns, runs, turns, or constructed scenarios.
- Do not treat prefix overlap as Native cache hit.
- Do not use future request identity/depth as an online feature.
- Preserve frozen replay conformance status; record actual order for any new run.
- Pre-register the exposure predicate and success/failure rules before running.

---

## 8. M1 decision request

I recommend the following decisions:

1. **Approve E1 (P1-A + P2-D) as the next authorized step** — CPU-only, read-only, no algorithm implementation.
2. **Do not authorize a GPU campaign or a new algorithm implementation yet.**
3. **Approve A1/A3 as paused optimization targets**; keep A0/E0 as comparators and A1/A3 code as analysis references.
4. **Keep A2 as a diagnostic/negative control**, not the main target.
5. **Defer P3** until P1 establishes whether the binding constraint is exposure or granularity; any P3 work requires a Protocol v5 design.
6. **Decide the data question:** if a representative multi-session trace is unavailable, P1-B must be labeled `SEMI_SYNTHETIC`, and the project should either acquire a trace or explicitly limit its claim to the controlled geometry.
7. **Authorize P1-B only after E1-A passes**, as a bounded Native exposure audit (A0-only), not as a policy campaign.

The decision rule is intentionally asymmetric: it is easier to stop than to start. If the natural workload does not expose multiple legal, distinguishable candidates, the correct conclusion is that this Entry-ordering problem is not the right next research question for this workload family.

---

## 9. Bottom line

The current campaign did not fail because the cost model was too simple. It failed to create a population of decisions in which a cost model could matter. The next round should therefore be designed around **decision exposure first, value alignment second, and algorithm complexity last**.

If only one direction is funded, fund **P1-A/P1-B**, with **P2-D** as a cheap parallel diagnostic. Do not fund another A1/A2/A3 tuning campaign on the current geometry. Do not start P3 before the exposure question is answered. And do not treat a better prediction MAE as evidence that the policy is useful.

---

## References

- [Phase 3 null-mechanism analysis](phase3-algorithm-null-mechanism-analysis.md)
- [Phase 3 actual-order audit](phase3-actual-order-audit.md)
- [P2 depth study](phase3-p2-depth-data/p2-depth-report.md)
- [R1.3 cross-phase synthesis](../research-consolidation/research-results-and-contributions.md)
- [R1 evidence ledger](../research-consolidation/r1-experiment-evidence-ledger.md)
- [W1-C feasibility pilot](../continuum-w1c-feasibility-pilot.md)
- [Phase 4 session-continuation study](phase4-session-continuation-data/phase4-session-continuation-report.md)
- [Protocol v4](../phase3-final-evaluation-protocol-v4.md)
