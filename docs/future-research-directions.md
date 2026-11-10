# Potential Future Research Directions

**Status:** Research reserve only — not part of the frozen Phase 3 Protocol v4 campaign.  
**Authority:** M1 has accepted these four ideas as potential future directions for preservation and later consideration. This document does **not** authorize implementation, new experimental arms, data acquisition, GPU runs, or changes to the current 270-run pipeline.  
**Current priority:** Complete the already-authorized Phase 3 pipeline and its independent analysis first. Any follow-on study requires a separate project-level decision, available time, a defined evidence source, and a predeclared protocol.

This document consolidates the four ideas proposed by M2 into the current project narrative. It is the canonical index for their research questions, code overlap, unresolved work, prerequisites, and future evaluation requirements. The ideas remain hypotheses, not completed algorithms or demonstrated improvements.

## 1. Position within the project

The project studies cost-aware decisions inside a project-side Continuum-style, program-aware KV cache-management adaptation on vLLM 0.27.1. The current Phase 3 campaign evaluates only the frozen six arms N0/A0/A1/A2/A3/E0. The four directions below are **outside** that campaign.

| Direction | Decision layer | Research question |
| --- | --- | --- |
| **Idea 1 — Evidence-aware Block intervention** | L1: physical Block Victim Selection policy control | When should a custom Block selector replace the actual Native-LRU decision, and when should it fall back? |
| **Idea 2 — Workflow-aware Block signals** | L1: physical Block Victim Selection inputs/model | Do online workflow/runtime signals add predictive or decision value beyond the existing TTL-derived deadline proxy? |
| **Idea 3 — Downstream-cost-aware Entry Release** | L3: logical Entry Release ordering | Which Entry release produces the best downstream physical victim set and lowest recomputation loss? |
| **Idea 4 — Partial-tail Entry unpinning** | L3: logical Entry protection granularity | Can a suffix of an Entry be unprotected while preserving a valuable shallow prefix? |

The four ideas must not be collapsed into one proposed algorithm. Ideas 1 and 2 concern Block-level policy control and information; Ideas 3 and 4 concern Entry-level release order and granularity. They should be isolated first and combined only if independent evidence justifies it.

### Evidence labels

- **[I] Implementation fact:** verified against the current repository source or frozen design.
- **[E] Accepted evidence:** a result already recorded in the project's accepted evidence.
- **[P] Proposal:** a design or hypothesis requiring future implementation and validation.
- **[N] Not established:** a claim for which the project currently has no accepted supporting evidence.

## 2. Current status at a glance

| Direction | Existing code overlap | What is not implemented | Evidence boundary |
| --- | --- | --- | --- |
| **1. Evidence-aware intervention** | A2 runtime selector, native-LRU fallback families, candidate/plan validation, decision audit | A runtime gate based on evidence sufficiency, candidate completeness, victim-set divergence, calibrated incremental benefit, and policy overhead | Existing fallback is input/contract safety, not a benefit-aware intervention policy. A2 bounded evidence is inconclusive; no independent benefit is established. |
| **2. Workflow-aware signals** | Server-gap, queue-delay, ETA, and prefill/reload signals feed TTL estimation; A2 derives a reuse proxy from the resulting deadline | A Block-level consumer of intermediate signals, decision-time contract extension, censoring-aware estimator, missingness policy, no-future-leakage checks, and conditional ablations | No intermediate signal is currently consumed by the Block selector. External tool duration is recorded but has no production consumer. |
| **3. Downstream-aware Entry order** | A1 Entry scoring; A0 pressure ordering; newly eligible Block computation; deterministic pressure replay | Simulation of the actual downstream victim set, victim-to-recomputation mapping, fixed lookahead semantics, and downstream-aware release order | A1's proxy does not model the physical victim set. The historical 54/54 selection reproduction by a simple rule cautions against assuming the cost score adds value. |
| **4. Partial-tail unpin** | Whole-Entry Boolean protection, flat Block association, reverse ownership index, whole-Entry release | Range/depth-level protection, shared physical ownership correctness, prefix-continuity accounting, native integration, and concurrency safety | No partial-tail implementation or Native evaluation exists. The reviewed H1 archive had no cross-candidate shared Blocks (0/6,220), so its shared-prefix hypothesis could not be tested there. |

## 3. Shared implementation and evidence baseline

The following facts constrain all future work.

### 3.1 Block-level decision contract

[I] The current runtime decision-time structures are:

- **EvictionCandidate:** block_id, ref_cnt, has_block_hash, lru_rank, and content_hash;
- **EvictionContext:** required_blocks, free_blocks, total_blocks, and timestamp.

No intermediate workflow-history signal is currently a field of either structure. ref_cnt and native content identity are correctness evidence, not optional scoring hints.

The actual baseline must be reproduced through the real eligibility plan and the corresponding adapters:

- **NativeLRUAdapter** for native free-queue LRU;
- **RetentionAwareLRUAdapter** for the A0 eligibility-tier ordering.

Internal helpers that sort by native_rank alone are not substitutes for the actual A0 decision path.

### 3.2 Evidence chain

A future study must preserve the distinction between:

1. decision snapshot and eligible candidate set;
2. logical Entry Release / protection change;
3. physical Native hashed Block eviction;
4. subsequent APC hit or miss and surviving reusable prefix;
5. request-level recomputation and prefill work.

A logical release is not a physical eviction. A newly eligible Block is not necessarily selected as a victim. A selected victim is not, by itself, proof of a later APC miss. Missing evidence must remain missing and fail closed.

For requests with complete Native hash/APC evidence, retain the common metric definitions:

- N: Native prompt tokens;
- E: independently qualified reusable eligible native-prefix tokens;
- C: Native cached-prefix tokens;
- R = E - C: eligible-prefix recomputation;
- W = N - C: actual prefill work;
- S = N - E: genuinely new suffix;
- 0 <= C <= E <= N and W = R + S.

Use independent scenario draws or independently sampled task/session groups as the unit of inference. Runtime repeats, turns, and request rows are not additional independent samples.

### 3.3 Shared evaluation requirements

Any future study must:

- receive explicit M1 authorization and a study-specific frozen protocol;
- use the actual Native eligibility plan and downstream selector, not simplified internal helpers;
- compare methods on the same trace, candidate set, capacity target, pressure events, and runtime;
- preserve content identity, prefix topology, ownership, ref_cnt, provenance, and decision-time availability;
- report missingness and right-censoring by conditioning cell; never use post-decision or realized outcomes as prediction features;
- use held-out tasks/workloads, paired comparisons, uncertainty intervals, and thresholds frozen on validation data;
- report decision changes and downstream outcomes separately, including policy/metadata overhead;
- leave Native vLLM BlockPool, free-queue, hash, refcount, allocation, and cleanup ownership unchanged.

No expected numerical speedup or token reduction is claimed for any direction.

## 4. Idea 1 — Evidence-aware Block-level intervention

### 4.1 Research question

**[P]** Under what conditions should a custom cost-aware Block selector replace the actual Native-LRU victim set, and when should the system retain the baseline decision?

This is a policy-selection problem, not merely a scoring problem. Even a valid custom selector should not intervene unless there is trustworthy evidence that it will make a materially different and beneficial decision.

### 4.2 Existing implementation and gap

[I] A2NativeBlockAdapter.select_victims() already runs the A2 selector and has fail-closed Native-LRU fallback families for cases such as:

- request-factory failure;
- adapter-contract mismatch;
- invalid or inconsistent candidate/plan data;
- unverified content identity;
- missing reuse weights.

The implementation also records native and selected sets for audit.

[N] This is a per-decision validity fallback: it asks whether the selector's inputs satisfy its contract. It does **not** decide whether a valid custom decision is expected to improve on the baseline. There is no runtime intervention policy based on evidence sufficiency, candidate-set completeness, victim-set divergence, calibrated expected incremental benefit, or decision overhead.

[E] The bounded A2 evaluation was inconclusive (0 better / 3 worse / 33 tied in 36 draws). W1-B was bounded smoke evidence; A2−A0 was zero in every group and no victim-set divergence was observed. Neither result establishes an independent Native performance benefit.

### 4.3 Proposed future design

**[P] Future hypothesis:** intervene only when every required evidence and benefit condition passes; otherwise preserve the actual baseline victim set.

A complete gate should distinguish these components:

1. **Evidence sufficiency:** content identity, ownership, prefix depth, and cost evidence have explicit validity/confidence states.
2. **Candidate-set completeness:** the custom selector and baseline see the same legal candidate set, including eligibility tiers and ref_cnt constraints.
3. **Physical identity:** hashed Block identity and prefix-chain membership are verified against Native residency, without future knowledge.
4. **Victim-set divergence:** the proposed victim set differs materially from the actual baseline set under the same capacity target.
5. **Expected incremental benefit:** an independently validated estimate of recomputation/latency benefit exceeds a predeclared threshold.
6. **Policy overhead:** decision latency, metadata, and memory overhead remain below predeclared bounds and are included in the comparison.
7. **Native fallback:** any failed condition returns the actual baseline decision and records a structured reason.

The expected-benefit estimator must be calibrated against measured downstream outcomes. A2's own score or an unvalidated proxy cannot be used to prove that A2 should be enabled.

### 4.4 Requirements and evaluation

- Construct the exact eligible set from the real vLLM bridge and runtime eligibility plan.
- Compute the actual Native/A0 baseline victim set on the same immutable candidate snapshot and capacity target.
- Compare Native LRU, always-on A2, a structural-diagnostics gate, and a gate using a validated expected-loss estimate.
- Freeze gate thresholds on validation traces; evaluate on held-out tasks and independent scenario groups.
- Record both victim sets, evidence status, gate/fallback reason, divergence, overhead, subsequent Native eviction, APC outcome, and N/E/C/R/W/S.

Primary metrics include intervention/fallback rates, reason distributions, victim-set divergence, predicted-versus-measured loss calibration, TTFT, JCT, throughput, and policy overhead.

**Falsification conditions:** frequent intervention without changing the victim set; predicted benefit uncorrelated with measured benefit; identity uncertainty causing near-total fallback; overhead erasing any gain; or no improvement over always-on A2 on held-out workloads.

### 4.5 Scope boundary

The existing A2 fallback remains part of the current implementation. The benefit-aware gate is not implemented, not a Phase 3 arm, and not authorized.

## 5. Idea 2 — Workflow-aware signals for Block Victim Selection

### 5.1 Research question

**[P]** Can runtime signals recorded or consumed before they are compressed into a final TTL deadline add predictive or decision value to Block victim selection, beyond the existing deadline-derived proxy?

Here, "workflow-aware" means online Agent lifecycle observations (tool context, inter-request gaps, queue delay, and program progress). It does not mean importing external AEG/ASG workflow graphs as used by SAGA or KVFlow.

### 5.2 Existing implementation and gap

[I] The current lifecycle has several signal paths:

| Signal | Current use |
| --- | --- |
| Server inter-request gap history | Collected and consumed by TTL estimation |
| Queue delay | Collected and consumed by TTL estimation |
| ETA / memoryfulness | Consumed by TTL estimation |
| Prefill/reload cost | Supplied to TTL estimation |
| External tool duration | Recorded in ExternalToolDurationHistory, but no production consumer |
| Final TTL deadline | Output of TTL estimation; A2 derives a reuse proxy from it |

None of these intermediate history signals is currently a field in EvictionCandidate or EvictionContext, and the Block selector does not directly consume them. A0's Block ordering uses eligibility tier and native LRU rank; A2's reuse proxy is derived from the final retention deadline.

The three time quantities must not be conflated:

1. tool invocation to tool completion;
2. turn completion to next request arrival;
3. remaining time to next arrival, conditional on no arrival yet.

External tool duration and server inter-request gap are different random variables.

### 5.3 Proposed future design

**[P]** Separate two questions:

- **Reuse timing:** when might a prefix be used again, conditional on the observed tool/workflow context?
- **Eviction cost:** how much reusable prefix and recomputation work would be lost if a particular physical victim set were removed?

A conceptual expected-loss abstraction is:

**L(S) = sum over prefix chains c of P_c(reuse within horizon H | X_c) × [C_c(m_c) - C_c(j_c(S))]**

where S is the physical victim set, X_c is the decision-time signal vector, m_c is the currently reusable prefix length, and j_c(S) is the longest reusable prefix remaining after the hypothetical eviction. This is a research abstraction; the project has no calibrated per-chain probability/cost model yet.

Time-to-next-use must condition on elapsed time and non-arrival. If total inter-arrival gap is G, elapsed time is e, horizon is h, and F_X is the gap CDF conditional on observed context X, then:

**P(G - e <= h | G > e, X) = [F_X(e + h) - F_X(e)] / [1 - F_X(e)].**

This is not generally F_X(h). Traces truncated by step limits or collection termination are right-censored; treating them as completed observations biases the estimate. Where cell counts are small, prefer an empirical survival baseline with uncertainty over a high-capacity model.

### 5.4 Requirements and evaluation

1. **Data availability audit:** for each signal, record where it is collected, provenance (NATIVE, OBSERVED, EXTERNAL, APPROXIMATED, or UNAVAILABLE), whether it is available at the eviction decision point, and effective sample size after right-censoring.
2. **No future leakage:** prove every feature can be computed strictly before the victim decision.
3. **Missingness:** report per-signal missing/unavailable rates by conditioning cell; preserve missingness and fail closed rather than imputing from outcomes.
4. **Incremental-value testing:** compare Native LRU, current A2 deadline-only proxy, deadline plus one signal at a time, tool-conditioned time-to-next-use, and a multi-signal expected-loss model on identical candidates and capacity targets.
5. **Conditional ablation:** test each signal's incremental value given the deadline, because TTL already compresses several lifecycle signals.
6. **Double-counting safeguard:** test correlated signals jointly; do not assume a signal adds information merely because it exists in the repository.
7. **Contract and overhead:** extend the immutable decision-time snapshot only for justified signals; measure availability, missingness, and per-decision overhead.

Required evidence includes signal availability at decision time, provenance, censoring, content identity, ref_cnt, victim sets, Native hashed eviction, APC outcomes, and N/E/C/R/W/S.

**Falsification conditions:** no signal changes victim decisions beyond noise; no incremental value conditional on the deadline; predicted loss does not correlate with measured recomputation; gains disappear on held-out tasks; or missingness/censoring makes the estimator unusable.

### 5.5 Scope boundary

The existing TTL/history machinery remains frozen for Phase 3. No intermediate-signal consumer, decision-contract extension, or new experimental arm is authorized.

## 6. Idea 3 — Downstream-cost-aware Entry Release ordering

### 6.1 Research question

**[P]** Can Entry release order be selected using the downstream physical victim set and its resulting recomputation loss, rather than primarily using Entry deadline and a native-rank-derived secondary key?

### 6.2 Existing implementation and gap

[I] The current A0 pressure path iteratively releases Entries until the eligible Block target is met. It can compute the Blocks newly exposed by a hypothetical release. The frozen A0 ordering is based on:

**(Entry deadline, minimum native LRU rank among newly eligible Blocks, Entry identity).**

Thus A0 already includes a downstream-related quantity; a future method must beat this actual baseline, not a straw-man deadline-only order.

[I] A1 implements Entry-level cost-aware scoring branches (single_step, per_unit, pair_lookahead, and deadline_fallback). However, its score is a proxy over newly eligible Block counts and deadline-derived weights. It does not simulate the actual physical victim set selected downstream or map those victims to the resulting reusable prefix and recomputation loss.

[E] In a historical Gate 2 decision analysis, Sufficient-first + earliest-deadline reproduced 54/54 recorded A1 forced-release selections. This is a distinct count from the later 54 successful Native runs in PR #82. It shows that the A1 score term was not needed to reproduce those recorded choices; it does not prove universal equivalence or establish an outcome comparison. W1-B remains bounded smoke evidence, not a formal effect.

Runs using diagnostic_first_release_program_id bypass the ordinary release-order key for the first release. They measure a forced first release, not an ordering, and must be excluded from ordering comparisons or reported separately.

### 6.3 Historical decision-space constraints

The reviewed Phase 2A H1 archive (123 decisions / 474 candidate records) exposed constraints that any future study must recheck against its exact source archive:

- **Cold-start deadline collapse:** under the reviewed conditions, default TTL was zero for all 123 decisions and the deadline ranking collapsed to recency for the observed candidate comparisons. Until cold-start behavior is exited, the deadline may add no information beyond elapsed time.
- **Branch stratification:** the archive contained 93 single_step decisions and 30 per_unit decisions; these should not be pooled without reporting branch-specific behavior.
- **Capacity geometry:** a release can expose substantially more Blocks than the immediate deficit, so the number of newly eligible Blocks is not equivalent to the number physically evicted.
- **Shared-prefix limitation:** the reviewed H1 archive had 0 shared Blocks across candidates among 6,220 candidate Block records. It could not test shared-owner effects relevant to Ideas 3 and 4.

These are historical analysis constraints, not authorization to change A0, and not claims about every future workload.

### 6.4 Proposed future design

**[P]** For each candidate release, simulate the newly eligible Block set and run the **same downstream physical victim selector** on a consistent candidate set. Prefer the release plan that satisfies the capacity target while minimizing expected incremental loss of the resulting physical victim set, subject to retention and Native eligibility constraints.

A valid comparison must freeze one lookahead unit:

- **Marginal-step:** score only the change caused by one hypothetical release at the same loop state for every candidate; or
- **Complete-loop:** simulate the entire release loop with an identical continuation policy for every candidate.

Do not mix these units. Every candidate must use the same starting eligible set, capacity target, pressure events, and downstream Block selector. Newly eligible Blocks must not be counted as physically evicted unless the downstream selector actually chooses them.

Required comparators:

1. frozen A0 ordering;
2. Sufficient-first + earliest-deadline;
3. downstream-aware marginal-step or complete-loop lookahead.

The strong simple-rule comparator is mandatory because of the historical 54/54 reproduction result.

### 6.5 Requirements and evaluation

- Add a non-mutating simulation hook for the actual downstream selector.
- Reproduce the real pressure loop and target semantics.
- Record newly eligible Blocks separately from selected and physically evicted Blocks.
- Map the physical victim set to surviving contiguous reusable prefix, APC hit/miss, and N/E/C/R/W/S.
- Report forced-first-release cases separately.
- Measure planning overhead and redundant exposure.

Metrics must include pairwise ordering agreement and rank correlation (e.g. Spearman/Kendall), first-Entry agreement, victim-set divergence, number of releases, Blocks exposed but not evicted, downstream recomputation, TTFT/JCT, and planner overhead.

**Falsification conditions:** a changed order yields the same victim set; the complex order does not beat the strong simple comparator; predicted loss does not correlate with measured recomputation; overhead exceeds gains; or effects fail on held-out replay.

### 6.6 Scope boundary

A1 remains a frozen Phase 3 arm and must be evaluated under Protocol v4. Downstream-aware Entry ordering is a separate future idea: it is not implemented, not a registered arm, and not authorized.

## 7. Idea 4 — Partial-tail Entry unpinning

### 7.1 Research question

**[P]** When an Entry is selected for release, should the system unprotect the whole Entry or only a suffix/tail of its Blocks while retaining protection for a shallow prefix?

This is a protection-granularity problem. Partial-tail **unpinning** changes eligibility; it is not partial physical eviction.

### 7.2 Existing implementation and gap

[I] Current retention state uses a whole-Entry Boolean protected flag and a flat block_ids tuple. Pressure release unprotects the whole Entry. A reverse index records Block-to-Entry associations and existing shared-owner checks operate at Entry granularity.

The simulator's request-level KVCacheManager.free() releases all blocks allocated to a request. It has no Native refcount, APC hash, prefix, or partial-range semantics and is not a valid model of partial-tail unpinning.

[N] No sub-Entry/range protection representation, partial-tail policy, per-range shared ownership, prefix-continuity logic, or Native vLLM integration exists.

### 7.3 Proposed future design

**[P] Future hypothesis:** under pressure, release protection from a selected Entry's tail before unprotecting its full prefix, when preserving the shallow prefix has lower expected recomputation cost and the tail can contribute enough eligible Blocks to satisfy the capacity target.

Candidate baselines and variants:

1. current whole-Entry unpin;
2. fixed tail length;
3. fixed tail fraction;
4. tail length chosen to satisfy the immediate capacity target;
5. cost-aware partial-tail unpin using verified prefix depth, shared ownership, and measured/validated recomputation cost.

Do not start with an unconstrained learned policy. First prove that the runtime can accurately represent protected ranges, shared physical ownership, and the contiguous prefix remaining after each possible eviction.

### 7.4 Engineering prerequisites

All of the following are required:

1. **Sub-Entry representation:** protection by Block range/depth rather than one Boolean, with deterministic serialization and lazy-expiry semantics.
2. **Shared physical ownership:** a Block shared by multiple logical prefix chains must not become reclaimable while another owner still protects it.
3. **Refcount and eligibility correctness:** ref_cnt > 0 Blocks remain ineligible; Tier 1/Tier 2 eligibility is recomputed per range; Native BlockPool/hash bookkeeping remains authoritative.
4. **Prefix continuity:** preserve and recompute the longest contiguous reusable prefix. Keeping arbitrary later Blocks does not preserve a prefix-cache hit.
5. **Native integration:** do not emulate pinning by raising ref_cnt, moving Blocks into a hidden pool, or duplicating Native BlockPool bookkeeping.
6. **Concurrency and allocation safety:** range updates must be atomic with respect to ownership changes, pressure events, and allocation; measure metadata and planning overhead.
7. **Correctness observability:** distinguish unprotected, eligible, selected-as-victim, and physically-evicted states.

The reviewed H1 archive had no cross-candidate shared Blocks (0/6,220). A future study needs workload traces with relevant shared-prefix topology before shared-owner benefits can be evaluated.

### 7.5 Evaluation and falsification

Compare whole-Entry unpin with fixed-tail and cost-aware partial-tail variants on identical traces, pressure events, Entry choices, capacity targets, and downstream Block selectors. Record protected ranges, shared-owner maps, ref_cnt, eligibility, physical victim sets, Native hashed eviction, APC hit-prefix length, and N/E/C/R/W/S.

Metrics include reusable prefix preserved, recomputation, physical Blocks freed, Blocks exposed but not evicted, hit rate/prefix length, TTFT, prefill throughput, JCT, and metadata/planning overhead.

**Falsification conditions:** range protection cannot be represented safely; shared-owner/refcount correctness fails; prefix continuity is broken; tail release does not preserve more reusable prefix at comparable capacity; or gains vanish on held-out traces / are erased by overhead.

### 7.6 Scope boundary

The frozen baseline remains whole-Entry protection. Partial-tail unpinning is not implemented, not part of Phase 3, and not authorized. It is the highest-risk direction because its feasibility depends first on safe ownership and prefix-range representation, not merely on a better scoring function.

## 8. Relationships and possible sequencing

The ideas can interact, but no combined method is currently approved.

| Relationship | Potential interaction |
| --- | --- |
| Idea 2 → Idea 1 | A validated expected-loss model could supply the benefit estimate used by an intervention gate. |
| Idea 2 → Idea 3 | A validated Block-level loss estimator could help evaluate hypothetical downstream victim sets for candidate Entry releases. |
| Idea 3 ↔ Idea 4 | Entry ordering and partial-tail granularity both change which Blocks become eligible under pressure. |
| Idea 1 ↔ Idea 2 | The intervention gate could decide when a signal-enriched Block selector is trustworthy enough to run. |

Study each direction independently first. Do not combine all four in the first follow-on experiment. A plausible sequence is to establish signal availability and loss calibration, then test one decision-layer change at a time, and only then consider policy gating or granularity interactions. This is a research dependency map, **not** a schedule or authorization.

## 9. Decision and authorization boundary

- Phase 3 Protocol v4, its six arms, estimands, cohort, gates, and 270-run one-shot authorization remain unchanged.
- None of the four directions creates a new Phase 3 arm or modifies the current execution plan.
- No implementation, new workload acquisition, smoke test, GPU run, or threshold tuning is authorized by this document.
- Any future work requires a separate M1 decision, available time, a study-specific frozen protocol, and explicit preservation of the existing baseline and evidence boundaries.
- A direction may be rejected, simplified, or left unimplemented if its data, correctness, or measurable-value prerequisites cannot be met. A null result is a valid research outcome.

## 10. Related source-of-truth documents

- [Research Status](research-status.md) — canonical current state and authorization.
- [Research Motivation and Contributions](research-motivation-and-contributions.md) — canonical project positioning and contribution boundaries.
- [Experimental Plan](experiment-plan.md) — current Phase 3 plan and freeze.
- [Phase 3 Protocol v4](phase3-final-evaluation-protocol-v4.md) — immutable estimands, arms, and gates.
- [Baseline Freeze](baseline-freeze.md) — Native ownership and frozen Continuum-style baseline semantics.
- [Mechanism Coverage and Claim Boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md) — what current evidence can and cannot establish.
