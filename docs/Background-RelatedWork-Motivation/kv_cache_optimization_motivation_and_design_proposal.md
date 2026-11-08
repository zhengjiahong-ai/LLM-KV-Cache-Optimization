# Potential Future Research Directions: Four Optimization Ideas for Continuum-Informed KV-Cache Management

**Project:** LLM-KV-Cache-Optimization  
**Document type:** Future-research proposal. **Not** an implementation plan, **not** a report of completed work, **not** an evaluation result.  
**Scope:** Block-level intervention and victim selection; Entry-level unpin ordering and granularity.  
**Status:** **POTENTIAL FUTURE WORK — UNAUTHORIZED FOR IMPLEMENTATION.**

> **Document status — read this first.**
>
> 1. These four ideas are **potential future research directions**.
> 2. They are **not part of the frozen Phase 3 evaluation campaign** and **do not expand the current strategy implementation scope**.
> 3. They have **not all been fully implemented**; none of the four is a completed algorithm.
> 4. Their **independent performance benefits have not been established**.
> 5. Any further implementation or evaluation requires **project-level authorization and available time**.
>
> The project lead has decided to prioritize **completion of the existing Phase 3 experimental framework** and the **correct, complete evaluation of the existing experimental arms** (A0/A1/A2, extended in Phase 3 to the frozen six-arm design **N0/A0/A1/A2/A3/E0**). This document preserves Member 2's intellectual contribution; it must not be read as approval to build, schedule, or claim a result.

**Authority and reading order** (all status claims in this document defer to these):

- [`docs/research-status.md`](../research-status.md) — canonical M1 phase/gate ledger on `main`. **Unmerged PR proposals are unapproved.**
- [`docs/experiments/README.md`](../experiments/README.md) — evidence navigation index and reading boundaries.
- [`docs/baseline-freeze.md`](../baseline-freeze.md) — frozen Continuum-style baseline and excluded scope.
- [`docs/experiment-plan.md`](../experiment-plan.md) — original RQ1–RQ4 framing and its current Phase 3 execution overlay (2026-11-03).
- [`docs/team-responsibilities.md`](../team-responsibilities.md) — ownership; Phase 3 is now a frozen protocol with conditional authorization, not an open-ended roadmap.
- [`项目动机文档.md`](项目动机文档.md) — project motivation and evidence boundary; [`专业术语表.md`](专业术语表.md) — terminology; [`相关工作总结.md`](相关工作总结.md) / [`References&Notes/论文总结.md`](References&Notes/论文总结.md) — literature; [`References&Notes/参考文献/文献索引.md`](References&Notes/参考文献/文献索引.md) — single bibliographic authority.

**Evidence discipline (four levels, never mixed):** ① results reported by external paper authors (always with experimental conditions); ② design inspiration derived from a paper's mechanism; ③ hypotheses proposed in this document; ④ results actually measured by this repository. ① is never ④. A signal existing somewhere in the code is not evidence that it is consumed at the eviction decision point; a CPU/Mock or offline result is not a real-vLLM result; a real-vLLM run is not an independent Native performance conclusion.

**Protocol note.** The active Phase 3 protocol is **Protocol v4 (Option F)**, accepted by M1 on 2026-11-06 (Issue #98 / PR #97) and engineered via PR #99; **Protocol v3 remains an immutable historical protocol**. G0 was accepted on 2026-11-07: the 40-run A0 load calibration is reused (not rerun), the 30-run A0 Noise Calibration is authorized, and the 240-run Main Campaign remains locked. The frozen campaign is the six-arm design **N0/A0/A1/A2/A3/E0**. The four ideas in this document are **not part of** that campaign and are **not approved implementation work**. This document **does not modify the frozen protocol, does not create a campaign, and does not define a new arm**. Any future evaluation requires a separate M1 decision recorded in [`docs/research-status.md`](../research-status.md).

**Structure note.** Each idea uses the same 11-part structure (§5–§8): Research Question / Motivation / Related Work and Research Context / Existing Project Mechanisms / Current Implementation Status / Proposed Future Design / Engineering Requirements / Evaluation Plan / Expected Benefits / Failure Criteria and Research Risks / Relationship to the Current Phase 3 Scope. Statements are labelled **[P]** proposal (not built), **[I]** implemented in code today, **[E]** evaluated by accepted evidence, or **[N]** not established, so that proposal, implementation and evaluation are never conflated.

---

## 1. Document Positioning and Scope

### 1.1 What this document is

A record of four research questions, their motivation, their relation to prior work, the mechanisms in this repository that they build on, the engineering work they would require, and the evidence a future evaluation would need. The intent is to make each idea **testable and falsifiable** rather than to present it as an achievement.

### 1.2 What this document is not

- Not a list of approved implementation tasks, and not a schedule.
- Not a claim that any idea is implemented, integrated, or validated.
- Not a performance claim for this project; no expected improvement numbers appear anywhere below.
- Not an amendment to the frozen Phase 3 protocol, the frozen Phase 1B baseline, or any sealed experiment record.

### 1.3 Current project priority

The current priority is to finish a reliable experimental framework and evaluate the **existing** arms under controlled, real-vLLM 0.27.1 + GPU APC conditions. The frozen Phase 3 campaign evaluates six arms — **N0/A0/A1/A2/A3/E0** — with N0 as the absolute native baseline, A3 as the frozen suffix-cost Entry algorithm, and E0 as the strong simple control; see [Protocol v4 (Option F)](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/phase3-final-evaluation-protocol-v4.md) and [`docs/research-status.md`](../research-status.md) for exact semantics and authorization.

| Arm | Entry forced release | Physical block victim selection |
| --- | --- | --- |
| **A0** | Frozen Continuum-style deterministic baseline | Native LRU under existing eligibility |
| **A1** | Cost-aware Entry-level selection | Same Block-level baseline as A0 |
| **A2** | A0 Entry-level release | Cost-aware Block-level selector |

`A2` is **not** an A1+A2 combined policy. A1-versus-A0 differences cannot by themselves establish the independent value of A1's q/λ/pair-lookahead signals, and **`Sufficient-first + earliest-deadline`** remains a required strong comparator for any future formal claim. Strategy implementations are **not** being expanded.

### 1.4 Authorization rule

**[N]** No idea below is authorized. Starting any implementation or evaluation for these ideas requires an explicit project-level decision and available time; the canonical authorization state is `docs/research-status.md` on `main`. PRs or branches that have not been merged must not be presented as approved decisions.

### 1.5 Terminology

Terminology follows [`专业术语表.md`](专业术语表.md). In particular: **Entry**-level unpin / pressure release changes **eligibility** (logical layer); **Block**-level victim selection chooses objects; **eviction** removes physical Blocks (L1). Retention/TTL is L2, protection/unpin is L3, admission/scheduling is L4, prefetch/offload is L5, cluster coordination is L6, and paging/layout is L0. The four ideas live only in **L1 (Ideas 1–2)** and **L3 (Ideas 3–4)**.

---

## 2. Current Experimental Arms and Accepted Evidence Boundary

### 2.1 Canonical status ledger (summary)

From [`docs/research-status.md`](../research-status.md) (canonical, `main`, M1 reconciliation 2026-11-03): Phase 0/1A (adapter validation) and Phase 1B (Continuum-style baseline, real-runtime validated) are `CLOSED`; Phase 2A H1 is `DIAGNOSTIC_ONLY` (29 independent paired-evaluable draws, below the threshold of 30), H2 did not unlock B1; Phase 2B/2C (fidelity, workload audit) and Phase 2E (frozen Native LRU/Continuum comparability campaign) are `CLOSED`, with Phase 2E explicitly **not** a cost-aware benefit result; Phase 2G A1 is `BOUNDED EVALUATION COMPLETED`; Phase 2G A2 is `INCONCLUSIVE`; W1-B is `ACCEPTED / CLOSED — BOUNDED_SMOKE_ONLY`; W1-C is `ACCEPTED / CLOSED` (the 20-task S50/S100 pilot completed; 18 full-payload-comparable tasks fed the later bounded Native evaluation, but **all historical pilot tasks are excluded from the formal Phase 3 cohort**). The bounded Native cost-aware evaluation (PR #82) is M1 `ACCEPTED / CLOSED` with A1 **0 better / 1 worse / 8 tied** and A2 **0 better / 3 worse / 6 tied** across nine frozen groups.

**Phase 3:** The active protocol is **Protocol v4 (Option F)**: M1 accepted Option F on 2026-11-06 (Issue #98 / PR #97); the engineering adaptation merged via PR #99 (`a7fe138`); Protocol v3 remains historical. Stage 1 (PR #93, six-arm materializer, E0/N0) and Stage 2 (PR #94, independent N/E/C evaluator) are **MERGED**. G0 was accepted on 2026-11-07: the existing **40-run A0 load calibration is reused (not rerun)**, the **30-run A0 Noise Calibration is authorized**, and the **240-run Main Campaign remains locked/unauthorized**. The campaign total is 310 runs, of which **270 are new**. **No formal benefit has been demonstrated, and no six-arm Main Campaign run has started.** (The Phase 3 paragraph of `research-status.md` is dated 2026-11-03 and predates the Option F/G0 records; the later M1 authorization records govern here, and M1 should synchronize the ledger.)

### 2.2 A1 — what the accepted evidence says

**[E]** The prior Gate 2 decision analysis found **54/54** recorded A1 **Gate 2 forced-release selections** reproduced by the simple **`Sufficient-first + earliest-deadline`** heuristic: on that corpus the score term was not needed to reproduce the recorded choices. The canonical ledger therefore states A1's **independent cost-model signal is unproven**. `Sufficient-first + earliest-deadline` is a documented analysis comparator / required strong comparator; it is **not** an implemented experimental arm in `src/`.

**[E]** The bounded Native cost-aware evaluation (PR #82, M1 accepted 2026-10-27) reports **54/54 successful Native runs** over nine frozen groups with a single repeat: A1 **0 better / 1 worse / 8 tied**, A2 **0 better / 3 worse / 6 tied**, with no observed A1/A2 recomputation-token benefit in that predefined grid. It is exploratory single-repeat evidence, and content-level causal attribution is **`NOT_ESTABLISHED`**. (The earlier **54/54** selection-reproduction count is a different quantity from PR #82's 54 successful runs.) See [bounded results](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/continuum-native-cost-aware-bounded-results.md).

**[E]** W1-B (M1 accepted, merged as `fc9626da`, 2026-10-23) reports 4 groups × A0/A1/A2 = **12 successful runs**, one repeat per arm/group. Per-group A1−A0 recomputed-token deltas are **−1056, 0, −1616, −1232** (descriptive sum **−3904**). M1 acceptance explicitly does **not** establish a population benefit, superiority over `Sufficient-first`, individual physical-eviction causality, or reproduction of the Continuum paper's original serving workload. RC3 labels the mechanism evidence **temporal association only**, with content-level causal attribution **`NOT_ESTABLISHED`**. This is a bounded Native comparability/mechanism smoke, not a formal effect estimate.

### 2.3 A2 — what the accepted evidence says

**[E]** The Phase 2G A2 bounded evaluation is `INCONCLUSIVE`: **0 better / 3 worse / 33 tied** in **36 draws**, with attribution and decision-exposure limitations. It is neither proof of universal equivalence to LRU nor formal benefit. The recorded decisions include **402 of 778 (`content_unverified`, ≈51.7%)** fallbacks, and **82 of 122** forced-release windows that could not be paired or were identity-incomplete; Gate 2 v3 reports **72/72** selection pairs `NOT_OBSERVABLE`. A zero token difference does **not** prove equal decisions. W1-B reports **A2−A0 zero in every group** and no observed A2-vs-Native-LRU victim-set divergence.

### 2.4 Evidence tiers and interpretation rules

**[E]** Logical release, physical hashed eviction, subsequent APC hit/miss, and request-level recomputation are **different observations** requiring different evidence; missing evidence must be preserved and fail closed. For requests with complete native hash/APC evidence, report `N` (native prompt tokens), `E` (reusable eligible prefix tokens), `C` (cached prefix tokens), with `0 ≤ C ≤ E ≤ N`, and separately `R = E − C` (eligible-prefix recomputation), `W = N − C` (actual prefill work), `S = N − E` (genuinely new suffix), `W = R + S`. The unit of inference is independent scenario draws or independently sampled tasks/session groups — **not** runtime repeats, turns, or request rows.

### 2.5 What has NOT been demonstrated

**[N]** No accepted evidence establishes: an independent Native performance benefit for A1 or A2; a validated evidence-aware intervention policy (Idea 1); a Block selector consuming intermediate/workflow signals (Idea 2); a downstream-cost-aware Entry release ordering that models the physical victim set and resulting recomputation loss (Idea 3); or a partial-tail unpin mechanism (Idea 4). The frozen Phase 3 campaign has **not started**, so none of its hypotheses (H1/H2/H3) has been tested. The four ideas are **motivated** by the gaps above; they are **not** conclusions of those experiments.

### 2.6 Merged and unmerged material

**[E]** W1-C is **ACCEPTED / CLOSED** on `main`: the 20-task S50/S100 pilot completed, 18 tasks are full-payload comparable, and **all historical pilot tasks are excluded from the formal Phase 3 effect-estimate cohort** (they are engineering/regression data only). W1-A acquired 10 SWE-bench Verified tasks, all from Astropy, with 9/10 right-censored at the 50-step limit; W1-B replays sparse turns with controlled pressure, not the original cross-session serving arrival process.

**[N]** Approved and unapproved material must not be conflated. **Option F (PR #97) was M1-accepted on 2026-11-06** (Issue #98) and is the basis of Protocol v4; PR #99 merged its engineering adaptation (`a7fe138`). The protocol is frozen: any change or Main Campaign expansion requires a separate M1 decision. Other unmerged branches and pilot recommendations must not be presented as approved decisions.

---

## 3. Status Matrix (four ideas × seven distinctions)

> **Reading rule:** columns 4–6 refer to the **idea itself**, not to the overlapping existing mechanism. "Yes for the overlapping arm" is explicitly annotated and must **not** be equated with completion of the research idea. **Code overlap ≠ implemented idea; CPU/Mock validation ≠ real-vLLM execution; real-vLLM execution ≠ independent Native performance evaluation.**

| | **Idea 1** Evidence-aware Block intervention | **Idea 2** Workflow/runtime signals for Block victim selection | **Idea 3** Downstream-cost-aware Entry release ordering | **Idea 4** Partial-tail Entry unpinning |
| --- | --- | --- | --- | --- |
| **1. Existing code overlap** | `A2NativeBlockAdapter.select_victims()` (`a2_native.py:538`), offline `A2BlockSelector.select()`, `NativeLRUAdapter` / `RetentionAwareLRUAdapter` (`runtime/vllm/adapter.py`), `a2_contract.py` / `a2_selector.py` fallbacks | `continuum/history.py`, `runtime.py`, `ttl.py` (`TTLInput`), `a2_native.py` (`reuse_proxy`), `runtime/vllm/types.py` (decision-time contract) | `costaware/a1_entry.py`, `continuum/pressure.py` (`_release_sort_key`, `_newly_eligible_blocks_after_release`, loop, `diagnostic_first_release_program_id`), `replay.py` / `rules.py` | `continuum/snapshots.py` (`RetentionEntrySnapshot`), `retention.py` (whole-Entry release, reverse index), `pressure.py` (shared-owner check), `kv_cache/manager.py` (simulator allocator) |
| **2. What is actually implemented** **[I]** | **Fail-closed Native-LRU fallback** on adapter-contract violation, contract-invalid input, `content_unverified`, `FALLBACK_REUSE_WEIGHT_MISSING`, or request-factory failure; audit fields for native/selected sets. Always-on A2 selector exists | Collection of server inter-request gaps, queue delay, ETA, prefill/reload cost; `ExternalToolDurationHistory` **write-only**; four signals → `TTLInput` → scalar `ttl_seconds` → `deadline_timestamp`; A2 derives `reuse_proxy` from the deadline | A1 cost-aware Entry scoring (`single_step` / `per_unit` / `pair_lookahead` / `deadline_fallback`), q-based `expected_recompute` proxy; frozen A0 ordering; newly-eligible Block computation; forced-first-release diagnostic hook | Whole-Entry Boolean `protected` + flat `block_ids`; lazy TTL expiry; deterministic pressure release; per-evicted-Block association trimming; observation-derived block↔prefix mapping |
| **3. What remains unimplemented** **[P]** | No intervention **policy**: no evidence-sufficiency gate, no victim-set divergence test, no expected incremental benefit threshold, no candidate-set completeness gate, no policy-overhead accounting, no held-out threshold selection, no gated arm | No Block-level consumer of any history signal; no decision-time contract extension; no no-future-leakage check, missingness policy, time-to-next-use estimator, conditional-on-deadline ablation, or multi-signal model | No simulation of the downstream physical victim set; no victim→recomputation-loss mapping; no fixed lookahead unit with identical continuation policy; no downstream-aware ordering; comparator not an implemented arm; no pairwise ordering agreement / rank correlation reporting | No sub-Entry/range protection representation; no shared-ownership/refcount/eligibility correctness for ranges; no prefix-continuity recomputation; no native vLLM integration; no concurrency/allocation safety; no tail-length policy |
| **4. CPU/Mock validation exists?** | **Partial** — unit/functional tests for A2 adapter and fallback; offline decision analyses (Gate 2, bounded evaluation) validate plumbing, **not** the gate idea | **Partial** — unit tests for TTL estimation and history recording; offline decision analyses. No CPU/Mock validation of Block-level signal use | **Partial** — offline decision analysis (54/54 reproduction, Phase 2A M4 report) and deterministic replay. No validation of downstream-aware ordering | **Partial** — unit tests for whole-Entry release / TTL semantics and deterministic replay. Simulator `free()` is request-level, **not** partial-tail |
| **5. Real-vLLM execution exists?** | **No for the idea.** Yes for the overlapping always-on A2 + fallback (Phase 1A adapter validation, Phase 2G A2 bounded evaluation, W1-B 12 runs) | **No for the idea.** Yes for the overlapping TTL/A0/A2 path (Phase 1B real-runtime validation, W1-B) | **No for the idea.** Yes for the overlapping A1 arm (Phase 2G A1 bounded evaluation, W1-B 12 runs) | **No for the idea.** Yes for the overlapping whole-Entry A0 baseline (Phase 1B real-runtime validation, W1-B) |
| **6. Independent Native performance evaluation?** | **No** — A2 `INCONCLUSIVE` (0/3/33 in 36 draws); W1-B `BOUNDED_SMOKE_ONLY`, A2−A0 zero in every group, no observed victim-set divergence | **No** — no accepted evidence for an intermediate-signal Block selector | **No** — 54/54 reproduction by a simple heuristic; independent cost-model signal unproven; W1-B A1−A0 is descriptive only, no formal effect or content-level causal attribution | **No** — no accepted evidence for partial-tail unpin |
| **7. Current authorization status** | **NOT AUTHORIZED** — potential future research direction; not in frozen Phase 3 campaign | **NOT AUTHORIZED** — same | **NOT AUTHORIZED** — same | **NOT AUTHORIZED** — same |

**[N]** No idea in this matrix is a completed algorithm or a validated performance improvement. Column 7 is uniform by decision of the project lead: further implementation or evaluation requires project-level authorization and available time. **Phase 3's conditional authorization applies only to the frozen six-arm campaign (N0/A0/A1/A2/A3/E0), not to these four ideas.**

---

## 4. Shared Implementation Ground Truth (code-audited)

This section records facts verified against the current source tree so that each idea does not need to re-derive them. Paths are relative to the repository root; line numbers refer to the current working tree and must be rechecked at the exact commit used by any future experiment.

### 4.1 Decision layers and entry points

- **[I]** `EvictionPolicyAdapter` (`src/kvopt/runtime/vllm/adapter.py:11-25`), `NativeLRUAdapter` (`:27-39`, pure `lru_rank` order), `RetentionAwareLRUAdapter` (`:42-63`, uses `preparation.virtual_eligible_order`) are the L1 contract.
- **[I]** `EligibilityTier` and `selection_key = (eligibility_tier, native_lru_rank)` (`src/kvopt/continuum/selection.py:100-103`): Tier 1 = eligibility existing before pressure release, Tier 2 = eligibility created by a release.
- **[I]** Two distinct A2 entry points: runtime `A2NativeBlockAdapter.select_victims()` / `A2NativeSelectionCoordinator` (`a2_native.py:538,701`) over live vLLM candidates, and offline `A2BlockSelector.select()` (`a2_selector.py:327`) over a reconstructed `DecisionGeometry`. Results do not transfer automatically between them.
- **[I]** Internal helpers `native_selection()` (`a2_geometry.py`) and `native_lru_order()` (`a2_selector.py`) sort by `native_rank` alone and omit the tier constraint; they are **not** the A0 baseline. Any comparison must reproduce the actual baseline candidate set and decision path.
- **[I]** `ref_cnt` lives on the runtime candidate snapshot `EvictionCandidate` (`runtime/vllm/types.py:6-21`), populated by `VLLMEvictionBridge.build_candidates()`; `adapter.py` itself does not read it.
- **[I]** `src/kvopt/kv_cache/manager.py` is a request-level logical allocator for the simulator: `_allocations: dict[str, set[int]]`, `free()` pops and returns **all** of a request's blocks at once; no refcount, hash, prefix, or partial-release semantics exist in `kv_cache/`. **It is not a model of vLLM's refcounted prefix caching.**

### 4.2 Signal lifecycle: collection → TTL consumption → Block decision-time availability

**[I]** The runtime decision-time contract is `EvictionCandidate` = `block_id, ref_cnt, has_block_hash, lru_rank, content_hash` and `EvictionContext` = `required_blocks, free_blocks, total_blocks, timestamp` (`runtime/vllm/types.py:6-31`). **None of the history signals below is a field of either structure.**

| Signal | Collected / stored | Consumed by `estimate_ttl()`? | Available at Block decision time? |
| --- | --- | --- | --- |
| Server inter-request gap history | `ServerGapHistory` (`continuum/history.py:27-49`); `_pending_server_gaps` on turn finish, written on next `RequestArrived` (`runtime.py:290-315,451-455`) | **Yes** — `TTLInput.global/tool_server_gap_samples_seconds` (`runtime.py:365-370`, `ttl.py:44-60`) | **No** |
| External tool duration history | `ExternalToolDurationHistory` (`history.py:52-74`), written at `runtime.py:332` | **No** — write-only; **no production consumer under `src/`** (only tests read `global_samples()` / `samples_for_tool()`) | **No** |
| Queue delay | `QueueDelayHistory` (`history.py:77-104`), `record_queue_delay()` (`runtime.py:174-203`) | **Yes** — `TTLInput.queue_delay_t_seconds` (`runtime.py:371,384`) | **No** |
| ETA / memoryfulness | `CompletedProgramEtaHistory` (`history.py:107-155`) | **Yes** — `TTLInput.eta` (`runtime.py:372`) | **No** |
| Prefill/recomputation cost | `PrefillReloadProvider.estimate()` (`ttl.py:12-16`) via `runtime.py:357-364` | **Yes** — `TTLInput.prefill_reload_seconds` (`runtime.py:386`) | **No** |
| Final TTL deadline | `TTLDecision.deadline_timestamp = decision_timestamp + ttl_seconds` (`snapshots.py:286-334`); `RetentionEntrySnapshot.deadline_timestamp` | **No** — it is the *output* of TTL estimation | **Only indirectly**: A2 derives `reuse_proxy(deadline, t, tau)` from `retention_entries` (`a2_native.py:346-359`); A0/Native adapters read no deadline |

**[I]** `estimate_ttl()` consumes `global_server_gap_samples_seconds`, `tool_server_gap_samples_seconds`, `next_tool_type`, `queue_delay_t_seconds`, `eta`, `prefill_reload_seconds`, `default_ttl_seconds`, `duration_history_threshold` (`ttl.py:41-100`); its single `src/` call site is `runtime.py:436-439`. **Signal collection ≠ TTL consumption ≠ Block-level decision-time availability.** The three time quantities — tool invocation→completion, turn completion→next arrival, and remaining time conditional on no arrival yet — are different random variables.

### 4.3 Protection representation and pressure release

**[I]** `RetentionEntrySnapshot` carries `ttl_decision`, `protected: bool`, `waiting_followup: bool`, and a flat `block_ids: tuple[BlockIdentity, ...]` (`snapshots.py:152-178`). `RetentionManager` maintains a reverse index `block → set[RetentionEntryKey]` and releases **whole Entries** via `replace(protected=False)` (`retention.py:82,98-110`). There is **no** Block-range/depth-level protection field anywhere in `continuum/`, `runtime/vllm/`, or `kv_cache/`.

**[I]** `_release_sort_key()` returns `(entry.deadline_timestamp, native_key, key.sort_key)`, where `native_key` is the minimum `native_lru_rank` among Blocks a release would newly expose (`pressure.py:325-350`); the code documents this as **the frozen A0 order**. The loop runs while `len(tier_1_ids | tier_2_ids) < target`, with `target = min(required_blocks, queue_len)` (`pressure.py:83,107`). `diagnostic_first_release_program_id` (`pressure.py:61,116-130`) forces the first release and bypasses `_release_sort_key()` for that step; such runs measure one specific release, **not** an ordering.

**[I]** The frozen adaptation has no native pin API: protection is an independent project state table, protected Blocks remain native free cached Blocks with normal APC hash metadata, and `ref_cnt` must not be artificially raised (`docs/baseline-freeze.md` §4, §6).

---

## 5. Idea 1 — Evidence-aware Block-level Intervention and Native-LRU Fallback

### 5.1 Research Question

**[P]** Under what conditions should a custom cost-aware Block selector replace the native LRU victim set, and when should the system retain the native decision? This is a **policy-selection** problem, not merely a scoring problem: a custom policy can help only if it has enough trustworthy information to predict a better outcome.

### 5.2 Motivation

**[I]** A2 already has a **fail-closed Native-LRU fallback**: `request_factory` failure → `request_factory_failed:*`; adapter-contract mismatch (live candidate identity, `required_blocks`, `timestamp`) → `adapter_contract_invalid`; contract violations (`required_blocks < 0`, duplicate `block_id`, hash conflicts, `reuse_weight` out of range, …) → `FALLBACK_CONTRACT_INVALID`; identity gaps → `FALLBACK_CONTENT_UNVERIFIED`; missing reuse weights → `FALLBACK_REUSE_WEIGHT_MISSING` (`a2_native.py:548-567`, `a2_contract.py:253-390`, `a2_selector.py:349-404`).

**[N]** **This is not the full proposed intervention policy.** The existing fallback is a per-decision validity check: it asks "is this input trustworthy enough to run the custom selector?" It does not ask "should the custom policy intervene at all, given that the input is valid?" **[N]** There is no gate based on evidence sufficiency, candidate-set completeness, victim-set divergence, expected incremental benefit, or policy execution overhead; native and selected sets are written to audit but never compared (`a2_native.py:543,581-582,639`). Offline screening gates (`a2_compare.py`) and deployment switches (`ContinuumConfig.enabled`) are evaluation/deployment layers, not runtime intervention decisions.

**[E]** The counter-evidence matters: *When Fancy Eviction Fails* reports that simple LRU is surprisingly robust against sophisticated policies on production prefix-reuse traces, with a capacity/trace-dependent counterexample (24 GiB, Qwen To-B: S3-FIFO/ARC 0.491 vs LRU 0.403). **[N]** Nothing in the project's accepted evidence shows that an always-on custom selector, or a gate over it, improves Native outcomes.

### 5.3 Related Work and Research Context

- *When Fancy Eviction Fails* (arXiv:2609.28870v2): §3 *Fancy Algorithms Do Not Work Well*, §5.1 *Quick Demotion*, §5.2 *Compute-awareness*, §5.3 *Block-Level vs. Session-Level Eviction*. Supports retaining a strong LRU baseline and evaluating conditional use; **does not** validate this project's gate.
- RLT / LBGR (arXiv:2601.18999v1): randomization improves worst-case competitive ratio without a cost model, so "better than LRU" does not require cost-awareness — ablation must isolate the source of any gain.
- Full per-paper context and conditions: [`References&Notes/论文总结.md`](References&Notes/论文总结.md) §8; comparisons: [`References&Notes/对比笔记.md`](References&Notes/对比笔记.md).

### 5.4 Existing Project Mechanisms

**[I]** `NativeLRUAdapter` (pure free-queue LRU) and `RetentionAwareLRUAdapter` (actual A0 path over `virtual_eligible_order`, ordered by `(eligibility_tier, native_lru_rank)`) define the baseline decision. `A2NativeSelectionCoordinator` filters candidates by `preparation.virtual_eligible_order` and constructs the decision context (`a2_native.py:701-737`); `VLLMEvictionBridge` snapshots the vLLM free queue and validates the returned victim set. Audit structures (`A2NativeEvidenceAudit`, `proxy_weighted_loss`, `cost_known`, `search_truncated`) exist but are diagnostic, not decision inputs.

### 5.5 Current Implementation Status

**[I]** Implemented: the always-on A2 runtime selector; the four fail-closed fallback families above; candidate/plan validation; audit export under `audit_sink`.
**[P]** Not implemented: any of the seven gate components below, a gated variant, a divergence detector, an expected-benefit estimator, an overhead counter, or a held-out threshold selection procedure.
**[E]** Evaluated: A2 always-on and its fallbacks in bounded/offline studies; A2 `INCONCLUSIVE` (0/3/33 in 36 draws), W1-B `BOUNDED_SMOKE_ONLY` with A2−A0 zero in every group and no observed victim-set divergence.
**[N]** Independent Native performance benefit: not established. **See §3 matrix, row Idea 1.**

### 5.6 Proposed Future Design

**[P]** **H1 — Evidence-aware conditional intervention:** intervene only when all of the following hold, otherwise preserve the actual native LRU decision. The design must distinguish **seven separate components** (the current code only implements the last one):

1. **Evidence sufficiency** — content identity, ownership, prefix depth and cost evidence are adequate, with explicit confidence/missingness status rather than a binary `content_unverified` flag.
2. **Candidate-set completeness** — the eligible candidate set equals the set the real baseline sees, including Tier 1/Tier 2 eligibility and `ref_cnt` constraints.
3. **Physical content identity** — hashed Block identity and prefix-chain membership are verified against native residency; no future knowledge.
4. **Victim-set divergence** — the proposed victim set differs materially from the actual baseline victim set computed on the **same** candidate set and capacity target.
5. **Expected incremental benefit** — an offline/validated estimate of the recomputation–latency benefit exceeds a **predeclared** threshold.
6. **Policy execution overhead** — measured decision latency, metadata and memory overhead are below a predeclared bound, and are included in the comparison.
7. **Native-LRU fallback** — when any condition fails, use `NativeLRUAdapter` / `RetentionAwareLRUAdapter` over the actual eligibility plan; record the fallback reason.

**[P]** Algorithm sketch (unchanged in substance from the original proposal):

1. Construct the exact eligible candidate set from `VLLMEvictionBridge.build_candidates()` restricted by the runtime eligibility plan.
2. Compute the actual baseline victim set for the same capacity target using the real adapters — never `native_rank`-only helpers.
3. Evaluate components 1–3; if any fails, fall back with a recorded reason.
4. Compute the proposed victim set and expected loss difference (components 4–6).
5. Intervene only if the divergence and expected-gain conditions pass; otherwise use the actual baseline decision.
6. Record gate reason, selected set, fallback reason, divergence, overhead and later outcome.

**[P]** The existing A2 D/Q-style structural diagnostics may serve as *candidate-scenario detectors*, never as sufficient evidence to intervene: a large reuse-proxy difference does not imply a different victim set, and a different victim set does not imply lower recomputation cost. A gate must not rely on an offline proxy until that proxy has been validated against measured recomputation and latency outcomes.

### 5.7 Engineering Requirements

**[P]** A gate component in the runtime `EvictionPolicyAdapter` path with access to both the baseline and proposed victim sets under one immutable candidate snapshot; an explicit evidence object carrying per-condition status; a divergence metric; a calibrated expected-benefit estimator; an overhead meter; a structured audit record (gate reason, fallback reason, both victim sets, later outcome); threshold selection on training/validation traces only; and a configuration that can disable the gate without altering the frozen A0 decision. No change to native `BlockPool`, hash, refcount or free-queue bookkeeping.

### 5.8 Evaluation Plan

| Element | Requirement for a future (authorized) evaluation |
| --- | --- |
| **Baseline** | Actual native LRU: `NativeLRUAdapter` over the same vLLM free-queue snapshot, plus `RetentionAwareLRUAdapter` for the A0 path respecting `(eligibility_tier, native_lru_rank)`. Do **not** substitute the `native_rank`-only internal helpers. |
| **Comparison method** | Paired, same trace / same candidate set / same capacity target / same runtime: (a) native LRU, (b) always-on A2 via `A2NativeBlockAdapter.select_victims()`, (c) gated A2 using only structural diagnostics, (d) gated A2 using validated expected-loss estimates. Thresholds frozen on held-out validation traces; independent scenario/task groups as the unit of inference. |
| **Required evidence** | Complete decision snapshots (candidate set, Tier, `ref_cnt`, content hash, native residency), both victim sets, gate/fallback reasons, subsequent Native hashed eviction, APC hit/miss, and request-level recomputation in `N/E/C/R/W/S` form. Preserve missingness and fail closed. |
| **Main metrics** | Intervention rate; fallback rate and reason distribution; fraction of events with victim-set divergence; estimated vs measured recomputation cost; TTFT (P50/P95), prefill throughput, JCT; policy decision overhead; regressions by workload class. |
| **Correctness checks** | Returned victim set is a legal subset of the eligible candidates; `ref_cnt`-zero constraint; native hash/refcount/APC bookkeeping unchanged; no future information used; identical baseline victim set reproduced when the gate declines. |
| **Falsification conditions** | Frequent intervention without victim-set change; predicted benefit uncorrelated with measured benefit; identity uncertainty forcing near-total fallback; gate overhead erasing any gain; no improvement over always-on A2 on held-out tasks; or a simpler policy matching the gated outcome. |

**[P]** Measurements needed to validate the **complete** idea: per-condition pass rates; the joint distribution of (evidence sufficient, candidates complete, identity verified); divergence frequency and magnitude; calibration of expected incremental benefit against measured `R`/`W`; overhead per decision; and the downstream outcome chain from gate decision → victim set → physical eviction → APC hit → recomputation. Without the full chain, a gate can only be shown to *change decisions*, not to *improve outcomes*.

### 5.9 Expected Benefits

**[P]** Qualitative only: fewer decisions made on unverifiable identity; avoidance of false confidence from elaborate scores; an auditable rule for when to depart from native LRU; a clean attribution of any gain to the gate rather than to the underlying selector. **No numeric performance improvement is claimed or predicted.** *When Fancy Eviction Fails* is explicit counter-evidence against assuming complexity helps.

### 5.10 Failure Criteria and Research Risks

**[P]** Reject or simplify the gate if it frequently intervenes without changing the victim set, if predicted benefit does not correlate with measured benefit, if identity uncertainty is common enough that almost all decisions fall back, or if fallback overhead erases the gain. Risks: the 402/778 `content_unverified` rate may persist and starve the gate; offline proxies may not transfer to Native; candidate completeness may be unverifiable at decision time; thresholds may overfit; the audit path itself may perturb timing. A null result here is a valid research outcome.

### 5.11 Relationship to the Current Phase 3 Scope

**[N]** Idea 1 is **outside** the frozen Phase 3 evaluation campaign. A2's existing fail-closed fallback is part of the current implementation and remains as is; the gated policy is **not** an approved arm, **not** implemented, and **not** validated. Any work on it requires project-level authorization and available time after the existing arms are correctly evaluated.

---

## 6. Idea 2 — Workflow-aware Signals for Block Victim Selection

> In this document "workflow-aware" means signals derived from the **Agent workflow's online runtime lifecycle** (Continuum-style observations such as inter-request gaps, tool context, queue delay, program progress). It does **not** mean AEG/ASG workflow-graph structure as in SAGA/KVFlow, which requires external workflow information this project does not assume (see [`相关工作总结.md`](相关工作总结.md) §2.C–2.D).

### 6.1 Research Question

**[P]** Can Block victim selection benefit from signals that are recorded or consumed before they are collapsed into a final TTL deadline? The question is **not** "should every intermediate variable be added to the score?" but whether a particular signal adds predictive or decision value **beyond the current deadline-only proxy**, under the same candidate set and capacity target.

### 6.2 Motivation

**[I]** Some workflow/runtime signals are recorded in the repository, but **their existence does not mean the runtime Block selector consumes them** (§4.2). Server inter-request gaps, queue delay, ETA and prefill/reload cost are recorded and enter `estimate_ttl()`; `ExternalToolDurationHistory` is recorded **write-only** with no production consumer; the final TTL deadline is the *output* of TTL estimation and only influences A2 indirectly through a deadline-derived `reuse_proxy`. No history signal appears in `EvictionCandidate` / `EvictionContext`.

**[E]** The literature supplies motivation, not transferable results: CacheWise reports that tool-call metadata can guide reuse-aware eviction, but its ~3.5× end-to-end figure is a scheduling+eviction composite and its pure eviction component is ~1.7×–2×; Continuum uses online observations to set a TTL, not a Block-level score; KVFlow relies on an Agent Step Graph. **[N]** None establishes that this project's signals improve its Block selector.

### 6.3 Related Work and Research Context

- CacheWise (arXiv:2606.16824v1) §3 *Coding Agent Workloads*, §5 *CACHEWISE Design* (§5.1 prefix-aware scheduling, §5.2 predictive eviction), §6 *Evaluation*.
- Continuum (arXiv:2511.02230v6) §4.1 *Utility Model*, §4.2 *Setting the TTL Value*, §5.1–5.2 runtime mechanism; the paper's term is "queueing delay".
- KVFlow (arXiv:2507.07400v1) §3 *Design of KVFlow* (ASG, `steps-to-execution`, Figure 3(a)), §3.1 *Workflow-Aware Eviction Policy* (Figure 3(b)), §3.2 *Overlapped KV Prefetching* — a distinct signal family requiring workflow structure; §3.2 prefetch is outside this project's scope.
- Full conditions and non-transferable conclusions: [`References&Notes/论文总结.md`](References&Notes/论文总结.md) §6–§7 and [`References&Notes/对比笔记.md`](References&Notes/对比笔记.md) §6.2. Bibliographic authority: [`References&Notes/参考文献/文献索引.md`](References&Notes/参考文献/文献索引.md).

### 6.4 Existing Project Mechanisms

**[I]** `TTLInput` fields and `estimate_ttl()` (§4.2); `A2NativeReuseState` derives `reuse_weight` only when `lifecycle == TRACKED_FUTURE` and a deadline exists (`a2_native.py:78-85,346-359`); `A0` Block selection uses only `(eligibility_tier, native_lru_rank)` and reads no deadline. `ExternalToolDurationHistory` has no `src/` consumer (verified: `history.py:52-74`, `runtime.py:89,332`; only tests read it).

### 6.5 Current Implementation Status

**[I]** Implemented: signal collection, TTL consumption of four signals, the scalar `ttl_seconds`/`deadline_timestamp`, and A2's deadline-derived reuse proxy.
**[P]** Not implemented: any Block-level consumer of an intermediate signal; a decision-time contract extension; data-availability instrumentation; no-future-leakage and missingness handling; conditional-on-deadline ablation; multi-signal models.
**[E]** Evaluated: TTL/history mechanisms through unit tests and real-runtime validation of the A0 baseline; A2 bounded evaluation and W1-B for the always-on deadline-only A2 path.
**[N]** Independent Native performance evaluation of an intermediate-signal Block selector: none. **See §3 matrix, row Idea 2.**

### 6.6 Proposed Future Design

**[P]** Separate two questions: **(A) when might the prefix be reused?** (conditional reuse/arrival-time estimate from tool type, duration, inter-request history, program progress) and **(B) how costly would eviction be?** (lost reusable prefix, verified Block identity, shared ownership, measured prefill cost). A conceptual expected-loss template (design abstraction only — the project has **no** calibrated $P_c$ or $C_c$):

$$
L(S) = \sum_{c \in \mathcal{C}} P_c(\text{reuse within } H \mid X_c) \left[ C_c(m_c) - C_c(j_c(S)) \right]
$$

with $S$ the physical victim set, $c$ a verifiable prefix chain, $X_c$ the observed signal vector, $m_c$ the currently reusable prefix length, $j_c(S)$ the longest reusable prefix remaining after eviction.

**[P]** Time-to-next-use must condition on elapsed time and non-arrival. With total gap $G$, elapsed $e$, horizon $h$ and conditional CDF $F_X$:

$$
P(G - e \le h \mid G > e, X) = \frac{F_X(e + h) - F_X(e)}{1 - F_X(e)}
$$

This is not generally $F_X(h)$. Traces truncated by task-step limits or collection termination are **right-censored**; treating them as completed observations biases the gap distribution. Where cell counts are small, use a simple empirical survival baseline and report uncertainty rather than a high-capacity model.

**[P]** Required research plan components, each with an explicit deliverable:

1. **Data availability** — a per-signal audit of (i) where the value is recorded, (ii) its provenance class (`NATIVE` / `OBSERVED` / `EXTERNAL` / `APPROXIMATED` / `UNAVAILABLE`), (iii) whether it is causally available **at the eviction decision point**, not merely elsewhere in the runtime, and (iv) its effective sample size after right censoring. Extension of `EvictionCandidate`/`EvictionContext` is part of the method and must be reported as such.
2. **No-future-leakage** — prove the feature could have been computed from information available before the decision; reject any post-hoc or realized-reuse feature.
3. **Missingness** — report missing/unavailable rates per signal per conditioning cell, preserve missingness and fail closed; do not impute with future outcomes.
4. **Incremental-value testing** — compare variants on the same eligible candidate set and capacity target: native LRU; current A2 deadline-only proxy; deadline + one signal at a time; a tool-conditioned time-to-next-request model; a multi-signal expected-loss model; and the gated variant from Idea 1. Test whether each signal adds value **conditional on the deadline**, since the deadline already compresses several of them.
5. **Ablation** — ablate tool type, tool duration, inter-request gap, queue delay, `eta` and prefill cost separately; report victim-set changes, ranking metrics, measured recomputation and end-to-end latency, with held-out tasks and confidence intervals. Do not infer value from score separation alone.
6. **Double-counting safeguard** — TTL already absorbs tool-gap and program-lifecycle information; any correlated pair of features must be tested jointly and reported.

**[P]** Distinguish explicitly: (1) time from tool invocation to tool completion, (2) time from turn completion to next request arrival, (3) remaining time conditional on no arrival. These are different random variables; `ExternalToolDurationHistory` is not the same quantity as `ServerGapHistory`.

### 6.7 Engineering Requirements

**[P]** Extend the decision-time input contract (or an equivalent immutable snapshot) with the selected signals; implement and test a consumer for `ExternalToolDurationHistory` before using it (today it is write-only); add provenance and no-future-leakage assertions; add right-censoring-aware estimators; preserve adapter immutability guarantees; keep native `BlockPool` bookkeeping unchanged; record per-signal missingness and overhead. Any new input must be justified as a decision-time observation, not reconstructed from a later outcome.

### 6.8 Evaluation Plan

| Element | Requirement |
| --- | --- |
| **Baseline** | Native LRU under the actual eligibility plan, plus current A2 deadline-only proxy on the **same** candidates and capacity target. |
| **Comparison method** | Paired variants 1–6 above with all unrelated components fixed; one-signal-at-a-time additions; held-out tasks/workloads; independent scenario draws; no parameter retuning after outcome inspection. |
| **Required evidence** | Decision-time availability proof per signal; content identity and `ref_cnt`; victim sets; Native hashed eviction; APC hit/miss; `N/E/C/R/W/S`; censoring and missingness counts per conditioning cell. |
| **Main metrics** | Victim-set divergence; `R` and `W` (recomputed tokens / prefill work); TTFT P50/P95; JCT/throughput; calibration of predicted loss vs measured loss; per-signal decision overhead; results per workload class. |
| **Correctness checks** | No future information in features; no leakage from TTL outputs reused as independent inputs; `0 ≤ C ≤ E ≤ N`; unchanged native hash/refcount bookkeeping; legal victim sets; right-censored traces not treated as complete. |
| **Falsification conditions** | No signal changes the victim set beyond noise; no incremental value conditional on the deadline; predicted loss uncorrelated with measured recomputation; gains disappear on held-out tasks; missingness/censoring rates make the estimator unusable; or a simple deadline-only rule matches the multi-signal model. |

### 6.9 Expected Benefits

**[P]** Qualitative only: a principled separation of "when might this prefix be reused" from "what does losing it cost"; an auditable account of which signals are actually available at decision time; and a test of whether richer information beats a strong simple baseline. **No numeric performance improvement is claimed or predicted.**

### 6.10 Failure Criteria and Research Risks

**[P]** Reject a signal if it is unavailable at decision time, leaks future information, is entirely absorbed by the deadline, or fails to change outcomes on held-out data. Risks: binding constraint is **availability**, not quality — only the deadline-derived signal reaches A2 today; `ExternalToolDurationHistory` has no consumer to extend from; W1-A/W1-C traces are heavily right-censored (10 tasks, 9 at the 50-step limit; pilot 20 paired tasks), so conditional distributions may be unestimable; contract extension may break immutability; correlated signals may double-count; and on the reviewed H1 archive the deadline itself collapses to recency under COLD_START (§7.2.1).

### 6.11 Relationship to the Current Phase 3 Scope

**[N]** Idea 2 is **outside** the frozen Phase 3 evaluation campaign. The existing TTL/history machinery is part of the A0 baseline and stays frozen; no decision-time contract extension, no new signal consumer, and no intermediate-signal arm is approved. Any work requires project-level authorization and available time.

---

## 7. Idea 3 — Downstream-cost-aware Entry Release Ordering

### 7.1 Research Question

**[P]** Can Entry unpin order be selected from the **downstream physical victim set and resulting recomputation loss**, rather than primarily from Entry deadline and a native-rank-derived secondary key?

### 7.2 Motivation

**[I]** The pressure loop iteratively releases Entries until Tier 1 ∪ Tier 2 eligible Blocks reach `target`, and `_newly_eligible_blocks_after_release()` can compute the Blocks a release would expose (`pressure.py:83,107,285-323`). `_release_sort_key()` is the **frozen A0 order** and already consumes a downstream quantity — the minimum `native_lru_rank` among newly exposed Blocks — so a downstream-aware rule must beat a baseline that is **not** purely deadline-driven.

**[I]** A potential cross-layer mismatch remains: Entry A may expose many low-cost victim Blocks; Entry B may expose few Blocks including a shallow/shared one whose eviction damages several prefixes; a deadline-first ordering may not distinguish them. A simple "cost per newly eligible Block" ratio is not automatically correct, because releases interact with capacity thresholds, shared Blocks, eligibility tiers and the final victim selector.

**[E]** **Runs with a forced first release answer a different question.** `diagnostic_first_release_program_id` bypasses `_release_sort_key()` for the first step; such runs measure one specific release, not an ordering, and must be excluded from ordering comparisons or reported as a separate stratum.

### 7.2.1 Decision-space constraints from the reviewed M4 analysis (#81)

**[E]** A read-only M4 analysis of the Phase 2A H1 archive (123 decisions / 474 candidate records) imposes four constraints on any future evaluation of this idea:

1. **Deadline collapses to recency under COLD_START.** With `prefill_reload_seconds < 1.0` (0.0095–0.1711 on H1), `default_ttl_seconds = max(0, log(prefill_reload_seconds)) = 0.0` (123/123), so `deadline − t == −elapsed` (474/474) and `rank((deadline − t)/sigma) == rank(−elapsed/sigma)` (114/114). Until COLD_START is exited, the deadline signal carries no information beyond recency. Exiting COLD_START changes the A0 baseline and requires separate authorization; this is a shared prerequisite for Ideas 2 and 3.
2. **Stratify by A1 branch.** Gate 2 contained 54/54 `single_step` decisions; on H1, 93/123 are `single_step` (100% agreement between `Sufficient-first + deadline` and `Sufficient-first + A0_key`), and 30/123 enter `per_unit` (78 steps with ≥2 positive candidates). Any comparison must report `single_step` and `per_unit` strata separately.
3. **Capacity geometry.** On H1, `target` has median 32 (max 150); `need = target − |eligible_now|` has median 5 blocks (range 1–88); candidate prefix length has mean 13.1 blocks (median 12), exposing about 2.6× the median deficit (`max N_i / need` median 5.33, max 24) and leaving `N_i − need` Blocks unprotected in Tier 1 on later steps.
4. **Shared-prefix hypotheses are untestable on H1 Level-A.** H1 has 0/123 decisions (0/6220 Blocks) with Blocks shared across candidates (`N_i == block_count` on 474/474). Idea 3/4 shared-ownership effects cannot be evaluated until traces with shared Blocks are available.

**[N]** These are analysis findings, not approval to change the A0 baseline or to run a new campaign. They must be rechecked against the exact archive and commit used by any future study.

### 7.3 Related Work and Research Context

- Continuum (arXiv:2511.02230v6) §4.1–4.2, §5.2 — retention duration, pressure management and recomputation cost. The downstream-aware ordering is an **extension to evaluate**, not a Continuum feature.
- *When Fancy Eviction Fails* (arXiv:2609.28870v2) §4.5, §5.1–5.3, §6, Appendices A/C — limitations of generic replacement scores; supports measuring real miss cost and avoiding unvalidated ratios; **does not** validate Entry-unpin lookahead.
- RLT (arXiv:2601.18999v1) — a richer rule can lose to a simpler one; competitive-ratio results are worst-case and cannot predict average performance.
- Comparative context: [`References&Notes/对比笔记.md`](References&Notes/对比笔记.md) §7.3.

### 7.4 Existing Project Mechanisms

**[I]** **A1** (`src/kvopt/costaware/a1_entry.py`) implements cost-aware **Entry-level** release scoring: `q = sigmoid((deadline − t)/tau)`, `expected_recompute = q·(min(need, N_i) + λ·(N_i − min)⁺)`, `per_unit = expected/N_i`, with full ordering keys `(expected_recompute, deadline, identity)` and `(per_unit, deadline, identity)` (`a1_entry.py:110-169`). Its branches are:

- `single_step` — an Entry whose `N_i ≥ need` can satisfy the target alone;
- `per_unit` — otherwise choose by `expected_recompute / N_i`;
- `pair_lookahead` — when all `N_i = 0`, evaluate pairs via `newly_eligible_after_many` and a combined `q`;
- `deadline_fallback` — earliest deadline when no pair is usable.

**[N]** **A1 does not fully model the actual downstream physical victim set or the resulting recomputation loss.** `ReplayState` recomputes only the eligible set; `expected_recompute` is a weighted Block-unit proxy, and `docs/experiments/phase2g-a1/README.md` and `a1_compare.py` explicitly state that the downstream eviction step is not simulated. A separate offline analysis probe (`scripts/probes/a1_structural_gap.py`) simulates `evicted_blocks`/`realised_loss` but is not part of the A1 implementation.

**[E]** **54/54**: `Sufficient-first + earliest-deadline` reproduced all 54 recorded A1 Gate 2 **forced-release selections**, while A1's own ordering is `(expected_recompute, deadline, identity)` — the score term was not needed on that corpus. The canonical ledger states A1's independent cost-model signal is **unproven**. W1-B's later bounded Native evidence (A1−A0 descriptive sum −3904 tokens across 4 groups, one repeat per arm/group) is a comparability/mechanism smoke: it establishes **no** formal effect, **no** superiority over `Sufficient-first`, and **no** content-level causal attribution (`NOT_ESTABLISHED`). `Sufficient-first + earliest-deadline` is a documented analysis comparator, not an implemented arm in `src/`.

### 7.5 Current Implementation Status

**[I]** Implemented: A1's four scoring branches; frozen A0 `_release_sort_key()`; newly-eligible Block computation; the pressure loop; `diagnostic_first_release_program_id`.
**[P]** Not implemented: downstream victim-set simulation, victim→recomputation-loss mapping, a fixed lookahead unit with identical continuation policy, downstream-aware release ordering, the strong comparator as an implemented arm, and pairwise ordering agreement / rank correlation reporting.
**[E]** Evaluated: A1 offline decision analysis, Phase 2G A1 bounded evaluation, W1-B 12-run smoke — all with the limitations above.
**[N]** Independent Native performance benefit: not established. **See §3 matrix, row Idea 3.**

### 7.6 Proposed Future Design

**[P]** **H3 — Downstream-aware release ordering:** when pressure requires releasing Entries, evaluate candidate releases by simulating their newly eligible Block sets **and** the downstream victim selector, and prefer a release plan that satisfies the capacity target while minimizing expected incremental loss of the resulting physical victim set, subject to valid retention constraints.

**[P]** Six explicit requirements for any future downstream-aware implementation:

1. **A fixed lookahead unit** — either *marginal-step* (default: score only what one hypothetical release changes, at the same loop state for every candidate) or *complete-loop* (simulate the full release loop with an identical continuation policy for every candidate). Mixing units makes the ranking meaningless.
2. **An identical downstream Block selector** for all candidates — the actual A0/A2 runtime adapter, not an internal `native_rank`-only helper.
3. **A consistent candidate set** — same starting eligible set, requested capacity, `target`, Tier 1/Tier 2 state and pressure events for every candidate.
4. **A measurable physical victim set** — the actual selected Block IDs, with content identity and `ref_cnt` evidence, not the set of newly eligible Blocks.
5. **Correct mapping from victim selection to recomputation** — from victim set → surviving reusable prefix → APC hit/miss → `N/E/C/R/W/S`; newly exposed but unselected Blocks must not be counted as immediately evicted.
6. **A strong simple-rule comparator** — `Sufficient-first + earliest-deadline` implemented and reported as a required comparator, not a straw man, because of the 54/54 precedent.

**[P]** Candidate algorithms (unchanged in substance): frozen A0 ordering; `Sufficient-first + earliest-deadline`; lowest incremental expected loss per newly eligible Block (diagnostic only); one-step downstream-aware lookahead under the marginal-step unit; bounded multi-step/beam search under the complete-loop unit if one-step lookahead demonstrates value. A one-step score template:

$$
J(u) = L(S_u) + \lambda \, O(u) + \mu \, R(u)
$$

where $S_u$ is the victim set after hypothetical release $u$, $L$ the expected recomputation loss, $O$ unnecessary exposure of Blocks not selected as immediate victims, and $R$ future risk for exposed Blocks. Weights require explicit justification and sensitivity analysis; future exposure risk is included only if it can be estimated and validated.

### 7.7 Engineering Requirements

**[P]** A simulation hook that can run the real downstream selector on a hypothetical eligible set without mutating runtime state; exact reproduction of the pressure loop and `target`; recording of both newly eligible and physically selected Block sets; prefix-continuity/APC-hit computation; exclusion or separate stratification of `diagnostic_first_release_program_id` runs; deterministic replay of pressure events; planning-overhead measurement; and no change to the frozen A0 ordering itself.

### 7.8 Evaluation Plan

| Element | Requirement |
| --- | --- |
| **Baseline** | Frozen A0 ordering (`_release_sort_key()`) plus the strong `Sufficient-first + earliest-deadline` comparator; the actual downstream Block selector held fixed across all variants. |
| **Comparison method** | Replay the same pressure events under each release order, then apply the identical downstream selector; report the lookahead unit for every result; exclude/stratify forced-first-release runs; paired comparisons over independent pressure events with confidence intervals. |
| **Required evidence** | Per-event eligible set, `target`, newly eligible Blocks, physical victim set, content identity/`ref_cnt`, subsequent Native hashed eviction, APC hit/miss, and `N/E/C/R/W/S`; decision-level ground truth before any outcome claim. |
| **Main metrics** | **Pairwise ordering agreement and rank correlation** (share of events with the same first Entry, same ordered release sequence, Spearman/Kendall over induced orderings) — mandatory; victim-set divergence; number of releases and Blocks exposed; immediate/subsequent recomputation; TTFT/JCT; planner overhead; redundant-release and exposed-but-not-evicted counts. |
| **Correctness checks** | All candidates evaluated at the same loop state and capacity target; identical continuation policy for complete-loop runs; newly eligible ≠ physically evicted; `0 ≤ C ≤ E ≤ N`; forced-first-release counts reported separately; no future knowledge. |
| **Falsification conditions** | Different ordering but identical victim set (nothing that matters changed); identical ordering credited with an outcome difference; no improvement over `Sufficient-first + earliest-deadline`; predicted loss uncorrelated with measured recomputation; overhead exceeding any gain; or results that do not survive held-out replay. |

### 7.9 Expected Benefits

**[P]** Qualitative only: a release order aligned with the physical cost of the victim set it creates; explicit separation of eligibility creation from physical removal; and a measurable answer to whether cross-layer lookahead beats a strong simple rule. **No numeric performance improvement is claimed or predicted.** The A0 baseline already consumes `native_lru_rank`, so headroom may be small.

### 7.10 Failure Criteria and Research Risks

**[P]** Reject or simplify if the ordering collapses onto a simple heuristic, if the victim set does not change, or if outcome gains vanish under paired held-out replay. Risks: 54/54 reproduction shows how quickly richer rules collapse; a single release often cannot satisfy `target`, so an ill-defined lookahead unit invalidates comparisons; the downstream selector may not be simulatable without mutating state; shared Blocks and Tier constraints complicate loss attribution; content identity may be unverifiable (402/778 `content_unverified` in the A2 bounded evaluation).

### 7.11 Relationship to the Current Phase 3 Scope

**[N]** Idea 3 is **outside** the frozen Phase 3 evaluation campaign. A1 is an existing experimental arm whose correct, complete evaluation is part of current work; the downstream-aware ordering is **not** implemented, **not** an approved arm, and **not** validated. The 54/54 finding and W1-B's bounded smoke are evidence boundaries, not support for a new method. Any work requires project-level authorization and available time.

---

## 8. Idea 4 — Partial-tail Entry Unpinning

### 8.1 Research Question

**[P]** When an Entry is selected for release, should the system unprotect the whole Entry, or only a suffix/tail of its Blocks while retaining protection for a shallow prefix? This is a **protection-granularity (L3)** problem. **Partial-tail unpin is not the same as partial physical eviction (L1)**: unpin changes eligibility; eviction removes physical Blocks.

### 8.2 Motivation

**[P]** Whole-Entry release is simple but exposes a large Block set at once. If a long prefix has a shallow portion likely reused by several future requests and a deep suffix with lower expected reuse value, a partial-tail release might preserve the valuable prefix while making enough deeper Blocks reclaimable. This is only beneficial if the runtime can represent protection by Block range/depth and correctly account for shared physical Blocks.

**[N]** **Current retention protection is Entry-level and Boolean.** `RetentionEntrySnapshot.protected: bool` plus a flat `block_ids` tuple (`snapshots.py:152-178`); release is `replace(protected=False)` for the whole Entry (`retention.py:82,98-110`). A `block_ids` list is an **observation** of associated Blocks, not a protection range; `KVCacheManager.free()` releases **all** of a request's Blocks at once in the simulator. **Neither constitutes Partial Tail Unpin.**

### 8.3 Related Work and Research Context

- *When Fancy Eviction Fails* (arXiv:2609.28870v2) §4.5 *Heavy-Tailed Session Footprints*, §5.1 *Quick Demotion*, §5.2 *Compute-awareness*, §5.3 *Block-Level vs Session-Level Eviction* — motivates position-aware/cost-aware granularity, but §5.3 is an **L1 eviction-granularity** discussion, not this project's **L3 protection-release** mechanism.
- KVFlow (arXiv:2507.07400v1) §3 *Design of KVFlow* and §3.1 *Workflow-Aware Eviction Policy* — shared prefix nodes in a tree-structured cache; an eviction-priority (L1) mechanism, not protection granularity.
- vLLM RFC #37003 — token-range retention directives (`RetentionDirective` with `start`, `end`, `priority`, `duration`) as an **engineering precedent only**. It is an open RFC, not a peer-reviewed paper, not an implemented feature, and its current status is **unverified** (see [`References&Notes/参考文献/关于vLLM的参考文档与网址.md`](References&Notes/参考文献/关于vLLM的参考文档与网址.md) §3 and §11.5).
- Full context: [`References&Notes/论文总结.md`](References&Notes/论文总结.md) §8, [`References&Notes/对比笔记.md`](References&Notes/对比笔记.md) §7.4.

### 8.4 Existing Project Mechanisms

**[I]** Whole-Entry Boolean protection; lazy deterministic TTL expiry; pressure release over `(deadline, native_key, identity)`; a reverse index `block → set[RetentionEntryKey]` with `any()`-style shared-owner checks (`retention.py:31-72`, `pressure.py:258-303`); per-evicted-Block association trimming (`retention.py:138-145`); observation-derived block↔prefix mapping whose correctness must not be relied on by vLLM inference (`docs/baseline-freeze.md` §4–§6). `ref_cnt` exists only on runtime candidates; protected Blocks remain native free cached Blocks with normal APC hash metadata.

### 8.5 Current Implementation Status

**[I]** Implemented: whole-Entry protection and release, TTL expiry, pressure loop, shared-owner checks at Entry granularity, simulator request-level allocator.
**[P]** Not implemented: **any** sub-Entry/range protection, partial-tail release, tail-length policy, shared-ownership/range refcount-eligibility accounting, prefix-continuity recomputation, native vLLM integration of partial protection, or concurrency/allocation safety for ranges.
**[E]** Evaluated: whole-Entry A0 baseline in Phase 1B real-runtime validation and W1-B; unit tests for TTL/protection semantics.
**[N]** Independent Native performance evaluation of partial-tail unpin: none. **See §3 matrix, row Idea 4.**

### 8.6 Proposed Future Design

**[P]** **H4 — Prefix-preserving partial unpin:** under pressure, release protection from a selected Entry's tail before unprotecting its full prefix, when the expected cost of preserving the shallow prefix is lower than the cost of exposing it to eviction and when enough tail Blocks can satisfy the capacity target. Test against Whole-Entry release under the same pressure events and downstream Block selector.

**[P]** Candidate granularity policies (unchanged in substance): Whole-Entry unpin (current baseline); fixed tail length or fraction (simple diagnostics); tail length selected to meet the immediate capacity target; cost-aware partial-tail unpin based on verified prefix depth, shared ownership and estimated recomputation cost; and a joint policy with Idea 3. Do **not** begin with an unconstrained learned policy: first establish that the runtime can accurately track which Block ranges are protected, which are shared, and what prefix remains reusable after each possible eviction.

### 8.7 Engineering Requirements

**[P]** Missing requirements, all currently unmet:

1. **Sub-Entry protection representation** — protection by Block range/depth instead of a single Boolean, with deterministic serialization and lazy-expiry semantics.
2. **Shared physical Block ownership** — a Block may be referenced by several logical prefix chains; releasing one Entry's range must not make a Block reclaimable while another owner still protects it. The existing `any()` reverse-index check is Entry-granular and insufficient.
3. **Refcount and eligibility correctness** — `ref_cnt > 0` Blocks must never be evictable; Tier 1/Tier 2 eligibility must be recomputed per range; native `BlockPool`/hash bookkeeping must remain authoritative and unchanged.
4. **Prefix continuity** — recompute the surviving **contiguous** prefix after eviction; retaining arbitrary later Blocks does not preserve prefix-cache hits. Report `E`, `C`, `R`, `W`, `S` after partial release.
5. **Native vLLM integration** — vLLM 0.27.1 has no native pin API; the project's independent protection table must represent ranges without raising `ref_cnt`, moving Blocks to a hidden pool, or duplicating `BlockPool` bookkeeping (`docs/baseline-freeze.md` §6).
6. **Concurrency and allocation safety** — no races between ownership updates, pressure events and allocation; atomic range updates; deadlock avoidance retained; additional metadata and planning overhead measured.
7. **Correctness observability** — distinguish "unprotected", "eligible", "selected as victim", and "physically evicted" in the audit trail.

### 8.8 Evaluation Plan

| Element | Requirement |
| --- | --- |
| **Baseline** | Whole-Entry unpin (current frozen A0 behaviour) with the same Entry choice and the same downstream Block selector; plus fixed-tail simple diagnostics. |
| **Comparison method** | Identical traces, pressure events and capacity targets; vary **only** unpin granularity; report the tail-length rule used; paired comparisons over independent events. |
| **Required evidence** | Protected ranges per Entry, shared-owner map, `ref_cnt`/eligibility per Block, physical victim set, Native hashed eviction, subsequent APC hit prefix length, `N/E/C/R/W/S`. |
| **Main metrics** | Reusable prefix length preserved; immediate and future recomputed tokens/time; physical Blocks freed per release event; Blocks exposed but not evicted; cache hit rate and hit-prefix length; TTFT/prefill throughput/JCT; metadata and planning overhead. |
| **Correctness checks** | Shared ownership (no Block made reclaimable while another owner protects it); prefix continuity; `ref_cnt`-zero constraint; Tier correctness; concurrent pressure events without races; native hash/refcount/APC bookkeeping unchanged; no whole-Entry fallback silently used. |
| **Falsification conditions** | Tail releases never preserve more reusable prefix than Whole-Entry at comparable capacity; correctness checks fail; overhead exceeds any gain; gains vanish on held-out traces; or the runtime cannot represent ranges at all — in which case the idea fails on representation grounds before any performance question. |

### 8.9 Expected Benefits

**[P]** Qualitative only: potentially preserving shallow prefixes shared by several future requests while still satisfying a capacity target; a clearer model of protection granularity; and an explicit test of whether sub-Entry protection is representable in this runtime. **No numeric performance improvement is claimed or predicted.**

### 8.10 Failure Criteria and Research Risks

**[P]** Reject if range protection cannot be represented safely, if shared-ownership/refcount correctness cannot be guaranteed, if prefix continuity is broken, or if outcomes do not improve on held-out traces. Risks: the logical Entry boundary is not the physical Block ownership boundary; a shared Block cannot be made reclaimable by releasing one owner; partial unpin ≠ partial physical eviction; the simulator `KVCacheManager` is not a valid reference; shared-prefix hypotheses are untestable on the reviewed H1 archive (0/6220 Blocks shared across candidates, §7.2.1); the idea may be **unimplementable rather than merely unproven**.

### 8.11 Relationship to the Current Phase 3 Scope

**[N]** Idea 4 is **outside** the frozen Phase 3 evaluation campaign. Protection remains an Entry-level Boolean in the frozen baseline; no range representation, no new arm, and no Native integration is approved. Any work requires project-level authorization and available time.

---

## 9. Cross-idea Relationships

**[P]** The four ideas should be studied independently first and combined only after their individual effects are understood. All four remain potential future research directions; none is an approved combination.

| Dimension | Main decision | Question answered | First controlled comparison (if ever authorized) |
| --- | --- | --- | --- |
| Idea 1: Intervention gate | Whether custom Block policy runs | When should the policy depart from native LRU? | Native LRU vs always-on A2 vs gated A2 |
| Idea 2: Intermediate signals | How to score candidate Blocks | Does information beyond deadline improve expected loss? | Deadline-only vs one-signal-at-a-time vs multi-signal |
| Idea 3: Unpin ordering | Which Entry to unprotect first | Which release makes the best downstream victim set available? | Frozen A0 order vs simple heuristic vs downstream lookahead |
| Idea 4: Unpin granularity | How much of an Entry to unprotect | Can the shallow prefix remain protected while enough tail Blocks become reclaimable? | Whole-Entry vs fixed-tail vs cost-aware partial-tail |

**[P]** Potential interactions: Idea 1 can gate the Block policy produced by Idea 2; Idea 3 can use the Block loss estimator from Idea 2 to evaluate hypothetical releases; Idea 4 changes the eligible set available to Idea 3 and the Block selector. A conceptual joint objective:

$$
(U^*, S^*) = \arg\min_{U, S} J(U, S)
$$

subject to $S$ being a valid subset of Blocks eligible after unpin decision $U$ and the requested capacity being satisfied. This is a **research abstraction**, not a claim that the current code solves the joint problem.

---

## 10. Future Evaluation Planning (shared prerequisites)

**[N]** This section describes **what a future evaluation would need to prove** if a direction is ever authorized. It **creates no campaign, defines no new experimental arm, and modifies no protocol** (see the Protocol note at the top). Expected performance improvements are deliberately absent.

### 10.1 Authorization gate

Before any implementation or evaluation: an explicit project-level decision recorded in [`docs/research-status.md`](../research-status.md), confirmation of available time, a frozen predeclared protocol for that specific study, and a clear statement of which existing arms remain frozen. Unmerged PR proposals are unapproved.

### 10.2 Shared evidence and statistical prerequisites

- Reproduce the **actual** baseline candidate set and decision path (`NativeLRUAdapter` / `RetentionAwareLRUAdapter` over the eligibility plan), never the `native_rank`-only helpers.
- Preserve the evidence tiers: decision snapshot → logical release → physical hashed eviction → APC hit/miss → request-level recomputation. Missing evidence fails closed.
- Report `N/E/C/R/W/S` with `0 ≤ C ≤ E ≤ N`; use independent scenario/task groups as the unit of inference; do not pool turns or runtime repeats; use held-out tasks/workloads, paired comparisons and confidence intervals.
- Include `Sufficient-first + earliest-deadline` as a strong comparator for any Entry-level claim.
- Freeze thresholds on validation traces, never on the test set; no parameter retuning after outcome inspection.

### 10.3 Workload and data-availability boundary

The historical Agent workload is the **W1-C S50/S100 pilot** ([`docs/continuum-w1c-feasibility-pilot.md`](../continuum-w1c-feasibility-pilot.md), **ACCEPTED / CLOSED** on `main`): SWE-bench Verified test split, `Qwen/Qwen2.5-Coder-3B-Instruct`, 32,768-token context limit, 512-token max completion, Mini-SWE-Agent 1.14.4 on one local worker, **20 paired tasks across 12 repositories** under independently run S50/S100 budgets. S50/S100 produced 1,000 / 1,800 successful model calls (plus 3 failed context-limit submissions under S100) and 464 / 943 tool calls; S50 recorded 0 natural completions and 20 step-limit right-censored runs, S100 recorded 1 natural completion, 16 right-censored runs and 3 context-limit failures.

**This pilot is not the formal Phase 3 cohort.** Its 18 full-payload-comparable tasks are excluded from formal effect estimates (engineering regression/evaluator validation only). **G0 has accepted and bound the Cohort Seal: 40 qualified tasks in 20 Workload Groups, two tasks from different repositories per group, at least 10 repositories overall**, selected deterministically from the 80-ID candidate frame (40 Primary + 24 Reserve). Cohort/run bindings and hashes are recorded in the G0 v3 bundle. The 40-run A0 load calibration is complete and reused; the 30-run A0 Noise Calibration is authorized; the 240-run Main Campaign remains locked. No six-arm Main Campaign run has started.

**[P]** Before fitting any model, count usable turn-gap observations after right censoring, report the effective sample size per conditioning cell (per tool type, per program stage) and state whether each cell is large enough; where counts are small, fall back to a simple empirical survival baseline with uncertainty. Local deterministic token IDs are **not** Native submitted-input, APC eligibility, residency or physical-reuse evidence.

### 10.4 Shared metric vocabulary

Victim-set divergence; pairwise ordering agreement / rank correlation (Idea 3); verified and unverified identity/ownership rates; `R`, `W`, `S`; TTFT P50/P95; JCT / session completion time; throughput; cache hit rate and surviving reusable prefix length; Entries released / Blocks exposed / Blocks physically freed; policy decision overhead and metadata; results per workload class and task, not just aggregate averages. Two methods that agree on the ordering cannot be credited with different outcomes; two that disagree on ordering but select the same victim set have not changed the decision that matters.

### 10.5 Staged structure (research agenda only, not a schedule)

1. **Ground truth** — exact signal semantics and decision-time availability; Block identity, prefix depth, shared ownership, physical eviction outcome; correlation of predicted loss with measured recomputation/prefill cost.
2. **Isolated tests** — hold all unrelated components fixed: Idea 1 baseline/always-on/gated; Idea 2 one signal at a time; Idea 3 only release order; Idea 4 only granularity.
3. **Factorial tests** — only after isolated effects are understood: Block signal model × Entry ordering × unpin granularity × fallback mode. Do not combine every feature in the first experiment.
4. **Decision criteria** — continue a direction only if it changes actual decisions in a measurable subset of cases and improves an outcome metric without unacceptable regressions or overhead; simplify or reject if it merely changes internal scores, reproduces a simple baseline, depends on unreliable identity evidence, or fails to improve measured outcomes.

---

## 11. Literature Notes and Exact Claims to Reuse

These are conservative paraphrases with source anchors, not verbatim quotations. Full per-paper reviews, experimental conditions and PPT material are in [`References&Notes/论文总结.md`](References&Notes/论文总结.md); titles/authors/versions/dates are authoritative only in [`References&Notes/参考文献/文献索引.md`](References&Notes/参考文献/文献索引.md). Section numbers refer to the PDF versions held in this repository and may shift in later revisions.

> **Verification status.** Versions consulted: **arXiv:2507.07400v1** (KVFlow, 10 Jul 2025), **arXiv:2511.02230v6** (Continuum, 25 May 2026), **arXiv:2606.16824v1** (CacheWise, 15 Jun 2026), **arXiv:2609.28870v2** (*When Fancy Eviction Fails*, 1 Oct 2026). Author names follow each PDF's first-page byline order. Paper results are **never** this project's results.

### 11.1 CacheWise

Shubham Tiwari, Tapan Chugh, Nash Rickert, Simon Peter, Ratul Mahajan, Haiying Shen, *CacheWise: Understanding Workloads and Optimizing KVCache Management for Efficiently Serving LLM Coding Agents*, arXiv:2606.16824v1, 15 Jun 2026. §3 *Coding Agent Workloads*, §5 *CACHEWISE Design*, §6 *Evaluation*. The abstract describes "prefix-aware scheduling with reuse-aware eviction guided by lightweight predictions from tool call metadata"; §3 reports tool metadata (type, arguments) captures meaningful structure. **Use:** support the premise that tool-aware signals are worth testing; do not claim CacheWise validates Continuum's signal set or a joint Entry/Block optimizer; its ~3.5× is an end-to-end composite, not an eviction-only result. https://arxiv.org/abs/2606.16824

### 11.2 Continuum

Hanchen Li, Runyuan He, Qiuyang Mang, Qizheng Zhang, Huanzhi Mao, Xiaokun Chen, Hangrui Zhou, Alvin Cheung, Joseph Gonzalez, Ion Stoica, *Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live*, arXiv:2511.02230v6, 25 May 2026. §4.1 *Utility Model*, §4.2 *Setting the TTL Value*, §5.1 *Tool Call Handler*, §5.2 *Efficient Pin with TTL in Scheduler* (paper's term: "queueing delay"). **Use:** ground the source of intermediate signals; do not equate a TTL deadline with a calibrated reuse probability or assume Continuum implements a Block selector. https://arxiv.org/abs/2511.02230

### 11.3 KVFlow

Zaifeng Pan, Ajjkumar Patel, Zhengding Hu, Yipeng Shen, Yue Guan, Wan-Lu Li, Lianhui Qin, Yida Wang, Yufei Ding, *KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows*, arXiv:2507.07400v1, 10 Jul 2025. §3 *Design of KVFlow* (ASG, `steps-to-execution`, Figure 3(a)), §3.1 *Workflow-Aware Eviction Policy* (Figure 3(b)), §3.2 *Overlapped KV Prefetching*. The paper describes preserving "shared prefixes in tree-structured caches". **Use:** an alternative signal-family comparator, not a variant of online gap/duration history; §3.2 prefetch is outside this project's scope. https://arxiv.org/abs/2507.07400

### 11.4 When Fancy Eviction Fails

Yiyu Liu, Minlan Yu, Juncheng Yang, *When Fancy Eviction Fails: Rethinking Cache Replacement For LLM Prefix Reuse*, arXiv:2609.28870v2, 1 Oct 2026. Abstract; §3 *Fancy Algorithms Do Not Work Well*; §4.5 *Heavy-Tailed Session Footprints*; §5.1 *Quick Demotion*; §5.2 *Compute-awareness*; §5.3 *Block-Level vs. Session-Level Eviction*; §6 *Discussion*; Appendix A *Capacity Sweeps*, Appendix C *Compute Savings under the Linear Cost Model*. The paper's design principles are "keeping recency as the baseline while incorporating quick demotion to filter one-hit prompts, compute-aware eviction to prioritize expensive misses, and capacity-adaptive eviction granularity". **Use:** justify a strong LRU baseline, conditional intervention, cost-aware measurement and multi-capacity evaluation; do not treat §5.3 as identical to partial-tail unpin; do not generalize "LRU is robust" without its 24 GiB Qwen To-B counterexample. https://arxiv.org/abs/2609.28870

### 11.5 vLLM RFC #37003

vLLM issue/RFC #37003, "[RFC]: Context-Aware KV-Cache Retention API (Prioritized Evictions)", Proposed Change. Token-range retention directives (`RetentionDirective` with `start`, `end`, `priority`, `duration`) are an **engineering precedent** for sub-Entry retention representation. **This is an open RFC, not a peer-reviewed paper, not an implemented feature, and carries no performance evidence.** Its current status, title accuracy and body text are **unverified** (no github.com access); see [`References&Notes/参考文献/关于vLLM的参考文档与网址.md`](References&Notes/参考文献/关于vLLM的参考文档与网址.md) §3. https://github.com/vllm-project/vllm/issues/37003

---

## 12. Unresolved Risks and Open Questions

**[P]** These risks are not removed by better experimental design; a null or negative result is not a failed experiment.

**Risks.**

- **Identity evidence may stay too weak to act on.** The A2 bounded evaluation records 402/778 decisions falling back with `content_unverified` and 82/122 forced-release windows unpairable or identity-incomplete; if that persists, Ideas 1 and 2 spend most decisions in fallback.
- **The baseline is already downstream-aware.** `_release_sort_key()` consumes the native rank of newly exposed Blocks; the 54/54 precedent shows how quickly a richer ordering collapses onto a simple one.
- **Signal availability is the binding constraint for Idea 2.** Only a deadline-derived signal reaches A2; `ExternalToolDurationHistory` has no consumer.
- **Sample size may not support the models.** W1-A: 10 Astropy tasks, 9 right-censored; W1-C pilot: 20 paired tasks, heavily censored, on an unmerged branch. Effective sample sizes per conditioning cell are unknown.
- **Partial-tail unpin may be unimplementable rather than merely unproven.** Protection is an Entry-level Boolean; the simulator has no sub-request granularity; shared ownership and native refcount semantics are unresolved.
- **Attribution may not survive combination.** Nothing in the accepted evidence establishes that isolated effects compose.
- **Authorization and time are not guaranteed.** No work on these ideas may begin without a project-level decision.

**Open questions.**

- Does the Tier 1/Tier 2 split leave enough Tier 2 movement for Entry-ordering changes to alter the victim set at all?
- How much of the deadline's information is already carried by native recency, and does any residual add value conditional on both?
- Can the runtime carry an additional signal to the eviction decision point without breaking the immutability guarantees the adapter contract relies on?
- Is `Sufficient-first + earliest-deadline` implementable as a first-class arm, and does it remain necessary once a downstream-aware rule exists?
- Do the available traces contain enough repeated pressure events at comparable capacity to support paired comparison?
- Which idea, if any, survives isolated testing, and does any interaction reverse an isolated gain?

---

## 13. Recommendation and Authorization Boundary

**[N]** **Current recommendation: do not implement or schedule any of the four ideas.** Preserve them as a research contribution with the status recorded in §3. The project's priority remains the completion of a reliable Phase 3 experimental framework and the correct, complete evaluation of the frozen six-arm campaign **N0/A0/A1/A2/A3/E0** under Protocol v4 (Option F); authorization is defined only by [`docs/research-status.md`](../research-status.md) on `main`.

**[N]** No idea in this document has demonstrated a gain. The accepted project evidence motivates testing the underlying assumptions; it does not establish that an evidence-aware gate, an intermediate-signal Block selector, a downstream-aware Entry ordering, or partial-tail unpin improves performance. Reviews of this work should present the four ideas as **testable hypotheses with explicit engineering prerequisites**, cite prior work with its experimental conditions, and state for each what result would support or reject it.

**[P]** If any idea is ever authorized, the first step is low-cost archive and prerequisite checks (§7.2.1): verify temporal release-budget exposure on existing archives; check gap-sample empirical CDF / TTL quantile ordering once `ttl_seconds > 0` exits COLD_START; run offline reload/JCT checks before changing `RetentionEntrySnapshot` for Idea 4; and keep shared-prefix Entry hypotheses paused until traces with shared Blocks are available. If those checks and a `per_unit`-stratum replay show no independent gain over `Sufficient-first`, record the negative finding rather than proceeding.

**[N]** Neither this document nor any linked document expands the current strategy implementation scope, modifies a frozen protocol or baseline, creates a new campaign or experimental arm, or changes sealed evidence.
