# Research Motivation and Design Proposal: Four Optimization Directions for Continuum-Informed KV-Cache Management

**Project:** LLM-KV-Cache-Optimization  
**Purpose:** Research motivation and design proposal; not an implementation-status report  
**Scope:** Block-level intervention and victim selection; Entry-level unpin ordering and granularity  
**Status:** Proposed hypotheses. None of the proposed gains should be treated as established until evaluated.

---

## 1. Executive Summary

This proposal organizes the next research questions into four independent but composable optimization ideas:

1. **Block-level Idea 1 — Intervention and fallback:** When should a custom Block eviction policy intervene, and when should the system retain the native LRU decision?
2. **Block-level Idea 2 — Continuum intermediate signals:** Should Block victim selection use signals available inside Continuum—such as tool type, tool duration, inter-request gaps, queue delay, program progress, and prefill/reload cost—instead of relying primarily on a final TTL deadline?
3. **Entry-level Idea 3 — Unpin ordering:** Can the Entry release ordering (`_release_sort_key`) be improved by accounting for the downstream Blocks that become eligible and the actual victims that a Block selector would choose?
4. **Entry-level Idea 4 — Unpin granularity:** Should protection be released for an entire Entry, or can a partial-tail unpin preserve valuable shallow prefixes while exposing only a subset of deeper Blocks?

The central working hypothesis is that cache retention and physical eviction are coupled decisions. Entry unpin determines which Blocks become eligible; Block eviction determines which eligible Blocks are actually removed. Optimizing either stage in isolation can miss opportunities available to a coordinated decision. This is a research hypothesis, not yet a demonstrated project result.

The proposal deliberately reuses useful ideas from prior work. It does not claim novelty merely because it uses tool metadata, workflow information, cost-aware eviction, or fine-grained cache management. The practical objective is to test which ideas transfer to this repository, what incremental value they add over its actual baseline, and under what conditions they should be used.

## 2. Project Reality and Current Implementation

### 2.1 Relevant current code paths

The following repository files are the primary implementation references:

- [`src/kvopt/costaware/a2_native.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/costaware/a2_native.py): constructs A2 snapshots and the current cost-aware Block selection inputs. Its `A2NativeBlockAdapter.select_victims()` is the **runtime** entry point: it implements the `EvictionPolicyAdapter` contract over live vLLM candidates and falls back to native LRU when content identity or reuse weights cannot be verified.
- [`src/kvopt/costaware/a2_geometry.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/costaware/a2_geometry.py): contains the deadline-derived `reuse_proxy()` and related geometric/cost calculations. The proxy is a ranking signal, not a calibrated probability of future reuse.
- [`src/kvopt/costaware/a2_selector.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/costaware/a2_selector.py): contains the **offline** Block-level selection logic (`A2BlockSelector.select()`) and comparison paths. It reasons over a `DecisionGeometry` reconstructed from recorded candidates, which is a different input from the live candidate list the runtime adapter receives.
- [`src/kvopt/runtime/vllm/adapter.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/runtime/vllm/adapter.py): defines the `EvictionPolicyAdapter` contract, plus `NativeLRUAdapter` (pure free-queue LRU ordered by `lru_rank`) and `RetentionAwareLRUAdapter` (the actual A0 path, which selects from the validated eligibility plan's `virtual_eligible_order`).
- [`src/kvopt/runtime/vllm/bridge.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/runtime/vllm/bridge.py): `VLLMEvictionBridge` snapshots a vLLM free queue into `EvictionCandidate`s in native LRU order and validates the returned victim set against the candidate set.
- [`src/kvopt/runtime/vllm/retention_integration.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/runtime/vllm/retention_integration.py): `RetentionRuntimeIntegration.apply_pressure()` is the runtime entry that couples pressure release with Block selection and feeds observed evictions back into the snapshot registry.
- [`src/kvopt/continuum/selection.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/selection.py): defines `EligibilityTier` (`TIER_1` for eligibility that exists before any pressure release, `TIER_2` for eligibility created by a pressure release) and `selection_key = (eligibility_tier, native_lru_rank)`.
- [`src/kvopt/continuum/ttl.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/ttl.py): `estimate_ttl()` and `TTLInput`, where the intermediate signals listed in §4.2 are consumed and collapsed into `ttl_seconds`.
- [`src/kvopt/kv_cache/manager.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/kv_cache/manager.py): the in-repository logical block allocator used by the simulator. It has no refcount or shared-ownership semantics, and `free()` releases every block of a request at once. It is not a model of vLLM's refcounted prefix caching.
- [`src/kvopt/continuum/pressure.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/pressure.py): contains pressure-release planning, `_release_sort_key()`, newly eligible Block calculation, and the iterative Entry release path.
- [`src/kvopt/continuum/snapshots.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/snapshots.py): represents retention snapshots and TTL decisions used by downstream code.
- [`src/kvopt/continuum/history.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/history.py): stores historical signals such as inter-request gaps and external tool durations.
- [`src/kvopt/continuum/runtime.py`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/src/kvopt/continuum/runtime.py): coordinates runtime histories, including in-progress tool-gap state and completed tool observations.
- [`docs/experiments/phase2g-a2-research-judgment.md`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/experiments/phase2g-a2-research-judgment.md): current A2 research judgment and conditions for further evaluation.
- [`docs/experiments/phase2g-a2-bounded-value-evaluation.md`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/experiments/phase2g-a2-bounded-value-evaluation.md): bounded A2 evidence, including limitations in content verification and baseline comparability.
- [`docs/experiments/phase2g-a1/README.md`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/experiments/phase2g-a1/README.md): A1 evidence and comparison with simpler release heuristics.
- [`docs/phase2a-m4-method-design-report.md`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/phase2a-m4-method-design-report.md): earlier Entry-release method comparisons.

**Two entry points, two baselines.** The offline `A2BlockSelector.select()` in `a2_selector.py` and the runtime `A2NativeBlockAdapter.select_victims()` in `a2_native.py` are distinct paths over different inputs. Results from one do not transfer automatically to the other. Every Idea 1 baseline comparison must be grounded in the runtime path: `NativeLRUAdapter` for pure free-queue LRU, and `RetentionAwareLRUAdapter` for the actual A0 decision. The real path restricts candidates to those the eligibility plan marks eligible and orders them by `(eligibility_tier, native_lru_rank)`. The internal helpers `native_selection()` in `a2_geometry.py` and `native_lru_order()` in `a2_selector.py` sort by `native_rank` alone and omit the tier constraint, so they are internal references rather than the A0 baseline.

These files should be rechecked at the exact commit used for each experiment. Paths and behavior may change as the branch evolves.

### 2.2 What the current architecture does—and does not—mean

The current design separates two operations:

- **Entry unpin/unprotect:** changes protection state and makes some Blocks eligible for reclamation.
- **Physical Block eviction:** chooses which eligible Blocks are actually removed.

These operations are related but not interchangeable. Unpinning an Entry does not itself prove that every newly eligible Block will be evicted immediately. Conversely, a Block's eventual eviction can affect one or more logical prefixes, especially when physical Blocks are shared.

The current pressure-release path orders Entries using `_release_sort_key()` and recomputes newly eligible Blocks after a candidate release. The current ordering is deadline-first, with a native-rank-derived secondary key and deterministic identity ordering. The code documents `_release_sort_key()` as **the frozen A0 ordering**, not an ad-hoc heuristic: it is a reference rule for deciding which Entry to release, and it is not a direct minimization of the downstream eviction loss.

At Block level, A2 derives a reuse ranking proxy from the TTL deadline. Continuum snapshots retain TTL-related inputs, but the current A2 score path compresses the deadline into a scalar ranking signal. The presence of a signal elsewhere in the repository does not mean the Block selector currently uses it directly.

### 2.3 Existing evidence and its interpretation

The repository's Phase 2G reports should be used as motivation, not as proof that a proposed replacement will work.

- A2's bounded evaluation reports incomplete content verification in a substantial share of recorded decisions (the report records 402/778 decisions as `content_unverified`, about 51.7%). This limits how confidently policy choices can be attributed to actual physical-prefix loss.
- The A2 report also warns that the selector's internal Native-LRU reference is not always identical to the actual A0 choice, because the real path can include eligibility/tier constraints. Concretely, `native_selection()` sorts by `native_rank` alone, while the A0 path orders by `(eligibility_tier, native_lru_rank)` and only over Blocks the eligibility plan marks eligible. Therefore, a valid comparison must reproduce the actual baseline candidate set and decision path, not merely call an internal LRU ordering helper.
- The A1 report records that `Sufficient-first + earliest-deadline` reproduced all 54/54 recorded A1 Gate 2 release choices. This is evidence that the more complicated A1 ordering needs to demonstrate value beyond a simple heuristic.
- The Phase 2A M4 report found that some proposed size-based heuristics were behaviorally identical to a simpler baseline, while a simple cost-per-released-Block ratio could be worse. A new score should therefore be justified by decision-level and outcome-level evidence, not by complexity alone.

**Interpretation:** Existing evidence supports testing the assumptions behind the current design. It does not establish that A2, tool-aware scoring, joint optimization, or partial-tail unpin will improve performance.

---

## 3. Idea 1 — Block-Level Intervention Gate and Native-LRU Fallback

### 3.1 Research question

Under what conditions should a custom cost-aware Block selector replace the native LRU victim set, and when should it fall back to the actual native decision?

This is a policy-selection problem rather than merely a scoring problem. A custom policy can be useful only if it has enough trustworthy information to predict a better outcome. If the candidate set or Block identity is incomplete, a more elaborate score may create false confidence.

### 3.2 Proposed hypothesis

**H1 — Evidence-aware conditional intervention:** A custom Block selector should intervene only when (a) the candidate set and relevant Block/prefix identity are sufficiently verified, (b) it proposes a materially different victim set from the actual baseline, and (c) offline evaluation predicts a benefit that exceeds a predeclared threshold. Otherwise, preserve the actual native LRU path.

This is a proposed decision rule, not an established optimal gate.

The existing A2 report's D/Q-style structural diagnostics can remain useful as *candidate-scenario detectors*. They should not, by themselves, be treated as sufficient evidence to intervene. For example, a large difference in reuse-proxy values does not guarantee a different victim set, and a different victim set does not guarantee lower recomputation cost.

### 3.3 Algorithm sketch

1. Construct the exact eligible candidate set that the real baseline sees — the same vLLM free-queue snapshot passed through `VLLMEvictionBridge.build_candidates()`, restricted to the Blocks the runtime eligibility plan actually marks eligible.
2. Compute the actual baseline victim set for the same capacity target using `NativeLRUAdapter` and `RetentionAwareLRUAdapter`, not an internal `native_rank`-only ordering helper.
3. Check whether content identity, ownership, prefix depth, and cost evidence are adequate.
4. Compute the proposed custom victim set and the expected loss difference.
5. Use the custom set only if the evidence and expected-gain conditions pass; otherwise use the actual baseline decision.
6. Record the gate reason, selected set, fallback reason, and later outcome.

A production gate should not rely on an offline proxy alone until the proxy has been validated against real recomputation and latency outcomes.

### 3.4 Evaluation

Compare at least:

- **Actual native LRU baseline** — `NativeLRUAdapter` over the same vLLM free-queue snapshot, plus `RetentionAwareLRUAdapter` for the A0 path that respects the eligibility plan's `(eligibility_tier, native_lru_rank)` ordering. Do not substitute the internal `native_rank`-only helpers; they omit the tier constraint and are therefore not the A0 decision.
- Always-on current A2, entered through the runtime `A2NativeBlockAdapter.select_victims()` rather than the offline `A2BlockSelector.select()`.
- Gated A2 using only structural diagnostics.
- Gated A2 using validated expected-loss estimates.

Report: intervention rate; fallback rate and reason; percentage of events where the victim set changes; estimated and measured recomputation cost; TTFT/prefill latency; end-to-end agent completion time; and regressions by workload class.

The gate should be evaluated on held-out tasks/workloads. Thresholds must be selected on training/validation traces, not tuned on the test set.

### 3.5 Failure criteria

Reject or simplify the gate if it frequently intervenes without changing the victim set, if the predicted benefit does not correlate with measured benefit, if identity uncertainty is common enough to make the custom policy unusable, or if fallback overhead erases the gain.

### 3.6 Source grounding

- **Repository:** `docs/experiments/phase2g-a2-research-judgment.md`, especially its discussion of D/Q-style structural conditions and the need to distinguish proxy differences from actual value.
- **Repository:** `docs/experiments/phase2g-a2-bounded-value-evaluation.md`, for `content_unverified` and the difference between an internal Native-LRU reference and the actual A0 path.
- **Paper:** Liu, Yu, and Yang, *When Fancy Eviction Fails: Rethinking Cache Replacement For LLM Prefix Reuse*, arXiv:2609.28870v2, abstract and the paper's evaluation/discussion sections. The authors report that sophisticated policies often provide limited gains over LRU, while quick demotion to filter one-hit prompts, compute-aware eviction to prioritize expensive misses, and capacity-adaptive eviction granularity can help under particular structural conditions (§5.1, §5.2, §5.3). Use this as support for retaining a strong LRU baseline and evaluating conditional use—not as proof that this project's proposed gate will work.  
  https://arxiv.org/abs/2609.28870

---

## 4. Idea 2 — Use Continuum Intermediate Signals for Block Victim Selection

### 4.1 Research question

Can Block victim selection benefit from Continuum signals that are available before they are collapsed into a final TTL deadline?

The question is not “should every intermediate variable be added to the score?” The correct question is whether particular signals add predictive or decision value beyond the current deadline-only proxy, under the same candidate set and capacity target.

### 4.2 Relevant signals in the repository

The current repository contains or tracks the following types of information:

| Signal                                     | Repository source / meaning                                  | Reaches the Block selector today?                            | Potential use                                                | Caveat                                                       |
| :----------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| `next_tool_type`                           | TTL input / next tool context; consumed by `_select_history()` in `ttl.py` | No — selects the history mode inside `estimate_ttl()`; only `ttl_seconds` survives | Condition future reuse estimates on tool category            | A tool category may be a weak proxy; validate by category and workload |
| Global inter-request gap samples           | `ServerGapHistory.global_samples()`                          | No — compressed into `ttl_seconds`                           | Estimate request-arrival timing after a completed turn       | This is not the same as tool execution duration              |
| Tool-conditioned inter-request gap samples | `ServerGapHistory.samples_for_tool()`                        | No — compressed into `ttl_seconds`                           | Estimate timing conditional on tool category                 | Requires enough samples and careful handling of censored traces |
| External tool duration history             | `ExternalToolDurationHistory` / runtime coordinator          | **No — write-only; no read path under `src/`**               | Estimate external-tool waiting time                          | Recorded in `runtime.py` but never read; requires implementing a consumer first. Do not treat it as identical to request gap |
| Queue delay                                | `QueueDelayHistory` → `queue_delay_t_seconds`                | No — enters the `ttl.py` benefit term                        | Model delay cost or the chance that cache space is needed soon | Queue delay is not itself a reuse probability                |
| Program progress / `eta`                   | `CompletedProgramEtaHistory.eta()`                           | No — enters the `ttl.py` benefit term                        | Distinguish programs at different lifecycle stages           | Validate calibration and data availability                   |
| Prefill/reload cost                        | `prefill_reload_seconds` provider                            | No — enters the `ttl.py` benefit term                        | Estimate cost of losing a prefix                             | Should be checked against measured prefill/recomputation cost |
| Final TTL deadline                         | `TTLDecision.deadline_timestamp`                             | **Yes — the only one**                                       | Existing deadline-only ranking signal                        | A deadline-derived sigmoid is a ranking proxy, not a calibrated probability |

**Only the final TTL deadline reaches the Block selector.** The runtime decision-time contract is `EvictionCandidate` (`block_id`, `ref_cnt`, `has_block_hash`, `lru_rank`, `content_hash`) plus `EvictionContext` (`required_blocks`, `free_blocks`, `total_blocks`, `timestamp`). None of the first seven signals above appear in either structure. They are consumed inside `estimate_ttl()` and survive only as the scalar `ttl_seconds`, hence as `deadline_timestamp` at the Entry level. The presence of a signal in the runtime therefore does not make it available to Block victim selection.

Consequently, Idea 2 is not primarily a scoring change. Using any intermediate signal at Block level requires (a) extending `EvictionCandidate`/`EvictionContext` or an equivalent decision-time input, (b) tracing the signal's causal availability at the moment the native allocator requests victims — not merely its existence somewhere in the runtime — and (c) an ablation showing the signal adds value *conditional on the deadline*, since the deadline already carries compressed information from several of them.

`ExternalToolDurationHistory` needs a separate warning. It is recorded in `runtime.py`, but no code path under `src/` reads `global_samples()` or `samples_for_tool()`; only a test asserts the recorded samples, so it is write-only for serving today. Any experiment that uses it must first implement and test a consumer, and must state the observation semantics it assumes.

Before implementation, verify each signal's exact semantics and availability at the eviction decision point. In particular, distinguish (1) time from tool invocation to tool completion, (2) time from turn completion to next request arrival, and (3) remaining time conditional on a request not having arrived yet. These are different random variables.

### 4.3 Proposed modeling decomposition

Separate two questions:

**A. When might the prefix be reused?**

Estimate a conditional reuse or arrival-time quantity using signals such as tool type, observed tool duration, inter-request history, and program progress.

**B. How costly would eviction be?**

Estimate the lost reusable prefix and the recomputation/prefill cost using prefix depth, verified Block identity, shared ownership, and measured prefill cost.

A simple conceptual expected-loss form is:

$$
L(S) = \sum_{c \in \mathcal{C}} P_c(\text{reuse within } H \mid X_c) \left[ C_c(m_c) - C_c(j_c(S)) \right]
$$

where $S$ is the physical victim set; $c$ is a verifiable prefix chain; $X_c$ is the observed signal vector; $m_c$ is the currently reusable prefix length; $j_c(S)$ is the longest reusable prefix remaining after the eviction; and $C_c(\cdot)$ is the measured or calibrated prefill/recomputation cost. This is a design template, not a claim that the project already has a calibrated $P_c$ or $C_c$.

A key safeguard: do not double-count the same information. TTL may already incorporate some of the tool-gap and program-lifecycle signals. An ablation should compare deadline-only scoring against intermediate-signal models and test whether the intermediate signals add value *conditional on the deadline*.

### 4.4 Time-to-next-use and censored observations

If the target is the remaining time until the next request, the model must account for elapsed time and the fact that no request has arrived yet. Let $G$ be the total gap, $e$ the elapsed time, $h$ a future horizon, and $F_X$ the conditional CDF given features $X$. Under an appropriate continuous-distribution model:

$$
P(G - e \le h \mid G > e, X) = \frac{F_X(e + h) - F_X(e)}{1 - F_X(e)}
$$

This is not generally equal to $F_X(h)$. Traces cut off by task-step limits or collection termination are right-censored; treating them as completed observations can bias the estimated gap distribution. If sample counts are small, use a simple empirical survival baseline and report uncertainty rather than introducing a high-capacity model.

### 4.5 Experimental design

Use the same actual eligible set and the same capacity target for all variants:

1. Native LRU.
2. Current A2 deadline-only proxy.
3. Deadline plus one intermediate signal at a time.
4. Tool-conditioned time-to-next-request model.
5. Multi-signal model with calibrated or empirically validated expected loss.
6. The gated variant from Idea 1.

Variants 3–5 require extending the decision-time input described in §4.2. Any such extension is part of the method and must be reported as such, together with evidence that the added signal is causally available at the decision point rather than merely recorded elsewhere in the runtime.

Ablate tool type, tool duration, inter-request gap, queue delay, `eta`, and prefill cost separately. Report whether each signal changes the victim set, improves ranking metrics, reduces measured recomputation, and improves end-to-end latency. Use held-out tasks and confidence intervals; do not infer value from score separation alone.

### 4.6 Source grounding

- **Repository:** `src/kvopt/costaware/a2_native.py` and `src/kvopt/costaware/a2_geometry.py` for the current deadline-derived proxy; `src/kvopt/continuum/ttl.py` for where the intermediate signals are consumed and collapsed; `src/kvopt/continuum/history.py`, `snapshots.py`, and `runtime.py` for the source and lifecycle of intermediate signals; `src/kvopt/runtime/vllm/types.py` and `bridge.py` for the decision-time contract that currently carries none of them.
- **Paper:** Tiwari et al., *CacheWise: Understanding Workloads and Optimizing KVCache Management for Efficiently Serving LLM Coding Agents*, arXiv:2606.16824v1. The abstract describes reuse-aware eviction guided by lightweight predictions from tool-call metadata. Consult §3 (*Coding Agent Workloads*), §5 (*CACHEWISE Design*), and §6 (*Evaluation*) to identify what signals were used and how their contribution was measured. CacheWise demonstrates that tool metadata can be useful; it does not establish that every Continuum signal will improve this project's A2 policy.  
  https://arxiv.org/abs/2606.16824
- **Paper:** *Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live*, arXiv:2511.02230v6. Consult §4.1 (*Utility Model*) and §4.2 (*Setting the TTL Value*) for the role of tool call durations, queueing delay, program continuity, and prefill/loading cost, and §5.1–§5.2 for the runtime mechanism. These are useful design inputs; they should not be assumed to be calibrated Block-level reuse probabilities.  
  https://arxiv.org/abs/2511.02230
- **Paper:** Pan et al., *KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows*, arXiv:2507.07400v1. §3.1 (*Agent Step Graph and Steps-to-Execution*) introduces the Agent Step Graph and `steps-to-execution`; §3.2 (*Workflow-Aware Eviction Priority Assignment*) turns them into eviction priorities, including shared prefixes in tree-structured caches. This is a useful alternative signal family to compare with Continuum's online runtime signals.  
  https://arxiv.org/abs/2507.07400

---

## 5. Idea 3 — Improve Entry Unpin Ordering (`_release_sort_key`)

### 5.1 Research question

Can Entry unpin order be selected based on the downstream Block victim set and expected loss, rather than primarily on Entry deadline and a native-rank-derived secondary key?

### 5.2 Why the current frozen A0 ordering may leave value on the table

The current pressure-release flow iteratively releases Entries until enough Blocks become eligible (`pressure.py`, the loop that runs while the union of Tier 1 and Tier 2 eligible Blocks is below the capacity target). For each candidate Entry, it can determine which additional Blocks would become eligible via `_newly_eligible_blocks_after_release()`. However, the Entry ordering does not directly minimize the physical Block loss produced by the downstream selector.

This creates a potential cross-layer mismatch:

- Entry A may expose many Blocks, but those Blocks may be low-cost victims.
- Entry B may expose fewer Blocks, but include a shallow/shared Block whose eviction would damage several prefixes.
- A deadline-first ordering may not distinguish these cases.
- A simple “cost per newly eligible Block” ratio is not automatically correct, because release decisions interact with capacity thresholds, overlapping/shared Blocks, eligibility tiers, and the final victim selector.

`_release_sort_key()` is documented in code as **the frozen A0 ordering**, not an ad-hoc heuristic. It returns a three-part key: the Entry deadline, then the minimum `native_lru_rank` among the Blocks that release would newly expose, then a deterministic Entry sort key. Two consequences matter for this Idea. First, the A0 baseline already consumes a downstream quantity — the native rank of the Blocks a release would expose — so a downstream-aware ordering has to beat a baseline that is not purely deadline-driven. Second, A1's scoring rule was itself reproduced on 54/54 recorded Gate 2 release choices by a score-free `Sufficient-first + earliest-deadline` rule, so agreement with the baseline must be measured before any outcome difference is interpreted.

**Runs with a forced first release answer a different question.** `RetentionAwareSelectionCoordinator.prepare()` accepts `diagnostic_first_release_program_id`. When it is set, the first pressure release is forced to that program and `_release_sort_key()` is bypassed for that step. Such runs measure the effect of one specific release, not the effect of an ordering. They must be excluded from ordering comparisons, or reported as a separate stratum, and their count must be stated in every Idea 3 result.

### 5.3 Proposed hypothesis

**H3 — Downstream-aware release ordering:** When the pressure manager must release one or more Entries, evaluate candidate releases by simulating their newly eligible Block sets and the downstream victim selector. Prefer a release plan that satisfies the capacity target while minimizing the expected incremental loss of the resulting physical victim set, subject to valid retention constraints.

**Defining the lookahead unit.** The frozen loop releases Entries until the union of Tier 1 and Tier 2 eligible Blocks reaches `target = min(required_blocks, queue_len)`, so a single candidate release frequently does not satisfy the requested capacity on its own. The lookahead must therefore fix one of two clearly separated evaluation units and apply it to every candidate:

- **Marginal-step evaluation (default).** Score only what the single hypothetical release changes: the Blocks it newly exposes, and the victims the downstream selector takes from the eligible set after that release. This measures the first-order effect of choosing this Entry next. Because every candidate is scored at the same point in the same loop state, the comparison is like-for-like.
- **Complete-loop evaluation.** Continue the simulation through the full release loop, applying the frozen A0 ordering to the remaining Entries until the capacity target is met, then score the final victim set. This captures the knock-on effect of an early release, but it is only a valid comparison of release choices if the continuation policy is identical for every candidate; otherwise the result compares continuation rules rather than first releases.

Under either unit, all candidates must be evaluated under equivalent conditions: the same starting eligible set, the same requested capacity and `target`, and the same downstream Block selector. Mixing a marginal score for one candidate with a complete-loop score for another makes the resulting ranking meaningless. Runs whose first release is forced by `diagnostic_first_release_program_id` fall outside this comparison (§5.2).

This need not require exhaustive joint optimization initially. A practical first version can use one-step lookahead or beam search over candidate Entry releases, followed by the existing Block selector.

### 5.4 Candidate algorithms

Compare the following:

1. The frozen A0 ordering (`_release_sort_key()`).
2. `Sufficient-first + earliest-deadline` baseline. This rule reproduced all 54/54 recorded A1 Gate 2 release choices, while A1's own ordering is `(expected_recompute, deadline, identity)` — so the reproduction means the score term was not needed on that corpus. Treat it as a required strong comparator, not a straw man.
3. Lowest incremental expected loss per newly eligible Block (as a diagnostic baseline, not assumed optimal).
4. One-step downstream-aware lookahead, scored under the marginal-step unit defined in §5.3: from the same loop state, simulate releasing each candidate Entry, run the actual Block selector on the resulting eligible set, and score only the change in the victim set.
5. Bounded multi-step lookahead or beam search, scored under the complete-loop unit defined in §5.3 with an identical continuation policy for every candidate, if one-step lookahead demonstrates value and overhead is acceptable.

For each candidate release $u$, a one-step score can be written as:

$$
J(u) = L(S_u) + \lambda \, O(u) + \mu \, R(u)
$$

where $S_u$ is the victim set returned by the downstream selector after hypothetical release $u$, $L(S_u)$ is expected recomputation loss, $O(u)$ is unnecessary exposure of Blocks that are newly unprotected but not selected as immediate victims, and $R(u)$ is a risk term for future eviction of those exposed Blocks. The weights $\lambda$ and $\mu$ require explicit justification and sensitivity analysis; do not tune them only to one trace.

The model must not count all newly eligible Blocks as immediately evicted. It should distinguish actual victims from newly exposed-but-retained Blocks. Future exposure risk should be included only if it can be estimated and validated.

### 5.5 Evaluation

Use identical pressure events, eligible sets, requested capacity, `target`, and downstream selector for every candidate, and state which lookahead unit from §5.3 was used. Measure:

- Number of Entry releases and Blocks exposed per pressure event.
- The lookahead evaluation unit (marginal step or complete loop) and, for complete-loop runs, the continuation policy applied to non-candidate Entries. Report this for every result.
- Whether any candidate release failed to satisfy the requested capacity on its own, and how many subsequent releases the loop then required.
- **Pairwise ordering agreement and rank correlation** between every candidate method and the frozen A0 ordering, and between candidate methods: the share of pressure events where two methods select the same Entry, the share where they produce the same ordered release sequence, and Spearman/Kendall rank correlation over the induced Entry orderings.
- Count of pressure events whose first release was forced by `diagnostic_first_release_program_id`, reported separately from unconstrained ordering decisions.
- Actual physical victim set and its divergence from the real baseline.
- Immediate and subsequent prefix recomputation.
- Measured prefill/reload time and end-to-end completion time.
- Planner runtime and memory overhead.
- Frequency of redundant releases or exposed Blocks that were not needed for the capacity target.

The agreement metrics are not optional. A method that produces a different ordering but the same victim set has changed nothing that matters, and a method that produces the same ordering cannot explain an outcome difference. Both cases must be separable from a genuine ranking change before any outcome delta is interpreted; this is the same failure mode that made the 54/54 `Sufficient-first` reproduction necessary to report.

A useful diagnostic is to replay the same pressure event under each release order and then apply the same downstream selector. This isolates the effect of unpin ordering from changes in Block scoring.

### 5.6 Source grounding

- **Repository:** `src/kvopt/continuum/pressure.py`, especially `_release_sort_key()` (documented in code as the frozen A0 order), `_newly_eligible_blocks_after_release()`, the loop that accumulates newly eligible Blocks, and the `diagnostic_first_release_program_id` override that can force the first release.
- **Repository:** `docs/phase2a-m4-method-design-report.md`, for prior Entry-release heuristic comparisons and evidence that some seemingly more sophisticated rules were equivalent to a baseline or worse.
- **Repository:** `docs/experiments/phase2g-a1/README.md`, for the 54/54 reproduction by `Sufficient-first + earliest-deadline`; use this as a required strong baseline.
- **Paper:** *Continuum*, the retention/pressure-management and cost-model sections, for the underlying relationship between retention duration, pressure release, and recomputation cost. The proposed downstream-aware ordering is an extension to evaluate, not something that should be attributed to Continuum as an existing feature.  
  https://arxiv.org/abs/2511.02230
- **Paper:** *When Fancy Eviction Fails*, §4.5 (*Heavy-Tailed Session Footprints*), §5.1 (*Quick Demotion*), §5.2 (*Compute-awareness*), §5.3 (*Block-Level vs. Session-Level Eviction*), §6 (*Discussion*), and Appendices A and C (*Capacity Sweeps*; *Compute Savings under the Linear Cost Model*), on the limitations of generic replacement scores. This supports measuring real miss cost and avoiding unvalidated ratios; it does not directly validate this project's Entry-unpin lookahead.  
  https://arxiv.org/abs/2609.28870

---

## 6. Idea 4 — Unpin Granularity: Whole-Entry vs. Partial-Tail Unpin

### 6.1 Research question

When an Entry is selected for release, should the system unprotect the whole Entry, or only a suffix/tail of its Blocks while retaining protection for a shallow prefix?

This is a protection-granularity problem. **Partial-tail unpin is not the same as partial physical eviction.** Unpin changes eligibility; eviction removes physical Blocks.

### 6.2 Motivation

Whole-Entry release is simple, but may expose a large set of Blocks at once. If a long prefix has a shallow portion likely to be reused by multiple future requests and a deep suffix with lower expected reuse value or lower loss on eviction, a partial-tail release may preserve the more valuable prefix while making enough deeper Blocks reclaimable.

However, this is only beneficial if the runtime can represent protection by Block range/depth and correctly account for shared physical Blocks. A shared Block may be referenced by several logical prefix chains; releasing protection for one Entry must not incorrectly make the Block reclaimable while another owner still protects it.

### 6.3 Proposed hypothesis

**H4 — Prefix-preserving partial unpin:** Under pressure, release protection from a selected Entry's tail before unprotecting its full prefix, when the expected cost of preserving the shallow prefix is lower than the cost of exposing it to eviction and when enough tail Blocks can satisfy the capacity target.

This hypothesis should be tested against Whole-Entry release under the same pressure events and downstream Block selector.

### 6.4 Candidate granularity policies

1. Whole-Entry unpin (current baseline).
2. Fixed tail length or fixed tail fraction (simple diagnostic baselines).
3. Tail length selected to meet the immediate Block-capacity target.
4. Cost-aware partial-tail unpin based on verified prefix depth, shared ownership, and estimated recomputation cost.
5. A joint policy combining partial-tail unpin with the downstream-aware Entry/Block decision from Idea 3.

Do not begin with an unconstrained learned policy. First establish that the runtime can accurately track which Block ranges are protected, which are shared, and what prefix remains reusable after each possible eviction.

### 6.5 Engineering and correctness requirements

- Represent protection at a Block range/depth level. Today `RetentionEntrySnapshot` carries a single `protected` Boolean plus a `block_ids` tuple, so protection cannot be released for part of an Entry.
- Preserve reference/ownership accounting for shared Blocks.
- Distinguish “unprotected,” “eligible,” “selected as victim,” and “physically evicted.”
- Recompute the surviving contiguous prefix after eviction; do not assume that retaining arbitrary later Blocks preserves prefix-cache hits.
- Handle concurrent requests and pressure events without races between ownership updates and eviction.
- Verify that partial unpin does not violate vLLM's ownership/refcount rules. `ref_cnt` lives on the runtime candidate layer — `EvictionCandidate` in `src/kvopt/runtime/vllm/types.py`, populated from the vLLM block snapshot by `VLLMEvictionBridge`. The in-repository `KVCacheManager` does **not** implement refcount-based ownership and frees all of a request's blocks at once, so it must not be used as the reference for shared-Block semantics.
- Record the additional metadata and runtime overhead.

### 6.6 Evaluation

Compare whole-entry and partial-tail policies on identical traces and capacity targets. Report:

- Reusable prefix length preserved.
- Immediate and future recomputation tokens/time.
- Physical blocks freed per release event.
- Number of entries/blocks exposed but not evicted.
- Cache hit rate and prefix length of subsequent hits.
- TTFT, prefill throughput, end-to-end agent completion time.
- Correctness checks for shared ownership, prefix continuity, and concurrent pressure events.
- Metadata and planning overhead.

### 6.7 Source grounding

- **Repository:** `src/kvopt/continuum/snapshots.py` and `src/kvopt/continuum/pressure.py`, for current Entry-level protection and whole-entry release behavior.
- **Paper:** *When Fancy Eviction Fails*, §4.5 (*Heavy-Tailed Session Footprints*), §5.1 (*Quick Demotion*), §5.2 (*Compute-awareness*), and §5.3 (*Block-Level vs. Session-Level Eviction*). These results motivate exploring position-aware, cost-aware partial release/eviction, but the paper's block-level versus session-level eviction discussion must not be mislabeled as this project's partial-tail *unpin* mechanism.  
  https://arxiv.org/abs/2609.28870
- **Paper:** *KVFlow*, §3.1 (*Agent Step Graph and Steps-to-Execution*) and §3.2 (*Workflow-Aware Eviction Priority Assignment*), for the treatment of shared prefix nodes and dynamic suffixes in an Agent Step Graph. It motivates ownership-aware prefix-level decisions but does not itself prove partial-tail unpin is effective.  
  https://arxiv.org/abs/2507.07400
- **Engineering reference:** vLLM RFC #37003, Proposed Change, which discusses token-range retention directives. This is an architectural reference for range-based retention, not peer-reviewed evidence of performance gains.  
  https://github.com/vllm-project/vllm/issues/37003

---

## 7. How the Four Ideas Relate

The four ideas should be studied independently first and combined only after their individual effects are understood.

| Dimension                    | Main decision                     | Question answered                                            | First controlled comparison                                 |
| :--------------------------- | :-------------------------------- | :----------------------------------------------------------- | :---------------------------------------------------------- |
| Idea 1: Intervention gate    | Whether custom Block policy runs  | When should the policy depart from native LRU?               | Native LRU vs always-on A2 vs gated A2                      |
| Idea 2: Intermediate signals | How to score candidate Blocks     | Does information beyond deadline improve expected loss?      | Deadline-only vs one-signal-at-a-time vs multi-signal       |
| Idea 3: Unpin ordering       | Which Entry to unprotect first    | Which release makes the best downstream victim set available? | Frozen A0 order vs simple heuristic vs downstream lookahead |
| Idea 4: Unpin granularity    | How much of an Entry to unprotect | Can the shallow prefix remain protected while enough tail Blocks become reclaimable? | Whole-Entry vs fixed-tail vs cost-aware partial-tail        |

Potential interactions:

- Idea 1 can gate the Block policy produced by Idea 2.
- Idea 3 can use the Block loss estimator from Idea 2 to evaluate hypothetical Entry releases.
- Idea 4 changes the set of eligible Blocks available to Idea 3 and the Block selector.
- A full joint optimizer could select both an Entry/range to unpin and a physical victim set, but should be attempted only after simpler factored variants demonstrate measurable value.

A conceptual joint objective is:

$$
(U^*, S^*) = \arg\min_{U, S} J(U, S)
$$

subject to $S$ being a valid subset of Blocks eligible after unpin decision $U$, and the requested capacity being satisfied. $J$ should include expected recomputation/prefill cost and, only where measurable, the future risk caused by exposing but not evicting Blocks. This formulation is a research abstraction, not a claim that the current code already solves the joint problem.

---

## 8. Experimental Plan

### Phase A — Validate signals and ground truth

The available Agent workload is the frozen W1-C pilot recorded in [`docs/continuum-w1c-feasibility-pilot.md`](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/blob/main/docs/continuum-w1c-feasibility-pilot.md): SWE-bench Verified (test split), `Qwen/Qwen2.5-Coder-3B-Instruct`, a 32,768-token model context limit with a 512-token maximum completion, Mini-SWE-Agent 1.14.4 on a single local worker, and **20 paired tasks** across 12 repositories executed under two independently run step budgets, S50 and S100. Those two budgets produced 1,000 and 1,800 successful model calls (plus 3 failed context-limit submissions under S100) and 464 and 943 tool calls respectively. In lifecycle terms, S50 recorded 0 natural completions and 20 step-limit right-censored runs; S100 recorded 1 natural completion (`psf__requests-2931`), 16 step-limit right-censored runs, and 3 context-limit failures (`astropy__astropy-8872`, `django__django-13569`, `sympy__sympy-21596`). The broader ~100-task acquisition is not authorized, so every sufficiency statement below must be made against these counts rather than against a hypothetical larger corpus.

1. Confirm the exact semantics of each history signal and when it is available, and separate the signals that reach the Block selector (only the TTL deadline) from those compressed into `ttl_seconds` (§4.2).
2. **Assess whether the available sample supports the proposed models; do not assume that it does.** Count the usable turn-gap observations after accounting for right-censored traces — tasks stopped by the S50/S100 step budget (20/20 under S50, 16/20 under S100), tasks that reach the 32,768-token context limit (3/20 under S100), and runs terminated by collection cutoff. Report the effective sample size per conditioning cell (per tool type, per program lifecycle stage) *before* fitting anything, and state explicitly whether each cell is large enough to estimate a conditional request-gap distribution. Where cell counts are small, fall back to a simple empirical survival baseline and report uncertainty rather than introducing a higher-capacity model.
3. Verify Block identity, prefix depth, shared ownership, and the actual physical eviction outcome.
4. Ensure the Native-LRU comparison uses the actual baseline candidate set and eligibility path — `NativeLRUAdapter` and `RetentionAwareLRUAdapter` over the validated eligibility plan — not the internal `native_rank`-only helpers.
5. Measure whether predicted loss correlates with actual recomputation/prefill cost.

### Phase B — Isolated tests

Run each idea with all unrelated policy components fixed:

- **Idea 1:** compare baseline, always-on custom policy, and gated policy.
- **Idea 2:** hold the candidate set and release policy fixed; add one signal at a time.
- **Idea 3:** hold the downstream Block selector fixed; vary only Entry release order, excluding or separately reporting runs whose first release was forced by `diagnostic_first_release_program_id`.
- **Idea 4:** hold the Entry choice and downstream selector fixed; vary only unpin granularity.

### Phase C — Factorial combination tests

After isolated tests, run a small factorial comparison to estimate interactions:

- Current vs new Block signal model.
- Current vs downstream-aware Entry ordering.
- Whole-Entry vs partial-tail unpin.
- Native-LRU fallback vs always-on custom selection.

Do not combine every proposed feature in the first experiment; otherwise, a positive or negative outcome cannot be attributed to a particular idea.

### Phase D — Metrics and statistical discipline

Report at least:

- Actual victim-set differences from the baseline.
- Pairwise ordering agreement and rank correlation between candidate release orderings and the frozen A0 order (Idea 3), so identical decisions are distinguishable from genuinely different rankings.
- Count of runs whose first release was forced by `diagnostic_first_release_program_id`, reported separately from unconstrained ordering decisions.
- Verified and unverified identity/ownership rates.
- Immediate and subsequent recomputation tokens and time.
- Prefill/reload latency, TTFT, throughput, and end-to-end agent completion time.
- Cache hit rate and surviving reusable prefix length.
- Number of Entries released, Blocks exposed, and Blocks physically freed.
- Planner CPU/runtime overhead and additional metadata.
- Results per workload class and task, not just aggregate averages.

Use multiple independent tasks/workloads, held-out evaluation traces, confidence intervals, and paired comparisons where the trace and pressure events can be replayed deterministically. A small number of single-run cases can validate plumbing but cannot establish robust performance gains. Two methods that agree on the ordering cannot be credited with different outcomes, and two methods that disagree on the ordering but select the same victim set have not changed the decision that matters; both situations must be reported rather than averaged away.

### Phase E — Decision criteria

Continue a direction if it changes actual decisions in a measurable subset of cases and improves an outcome metric without unacceptable regressions or overhead. Simplify or reject it if it merely changes internal scores, reproduces a simple baseline, depends on unreliable identity evidence, or fails to improve measured outcomes.

---

## 9. Literature Notes and Exact Claims to Reuse

The following are the relevant claims and where they should be checked in the original sources. When citing them in a paper or report, verify the exact wording and page/section against the version being cited; the notes below are paraphrases, not verbatim quotations.

> **Verification status.** Authors, titles, arXiv identifiers, and section numbers below were checked against the PDFs held in this repository at `docs/Background-RelatedWork-Motivation/References&Notes/参考文献/`. The versions consulted are **arXiv:2507.07400v1** (KVFlow, 10 Jul 2025), **arXiv:2511.02230v6** (Continuum, 25 May 2026), **arXiv:2606.16824v1** (CacheWise, 15 Jun 2026), and **arXiv:2609.28870v2** (*When Fancy Eviction Fails*, 1 Oct 2026). Author names are listed in each paper's byline order as printed on its first page. Section numbers refer to those versions and may shift in later revisions. The *claims* each paper is used to support remain conservative paraphrases, not verbatim quotations.

### 9.1 CacheWise

**Source:** Shubham Tiwari, Tapan Chugh, Nash Rickert, Simon Peter, Ratul Mahajan (University of Washington), and Haiying Shen (University of Virginia), *CacheWise: Understanding Workloads and Optimizing KVCache Management for Efficiently Serving LLM Coding Agents*, arXiv:2606.16824v1, 15 Jun 2026.  
**Where to consult:** §3 *Coding Agent Workloads* for the workload characterization; §5 *CACHEWISE Design* for the reuse-prediction method and the reuse-aware eviction it drives; §6 *Evaluation* for the ablations.  
**Useful point:** Coding-agent workloads alternate model calls with external tool calls, and the abstract states that CACHEWISE "combines prefix-aware scheduling with reuse-aware eviction guided by lightweight predictions from tool call metadata." §3 further reports that tool metadata such as tool type and arguments captures meaningful structure in execution behavior.  
**Use in this project:** Support Idea 2's premise that tool-aware signals are worth testing. Do not claim that CacheWise validates Continuum's specific signal set or the proposed joint Entry/Block optimizer.  
**Link:** https://arxiv.org/abs/2606.16824

### 9.2 Continuum

**Source:** Hanchen Li, Runyuan He, Qiuyang Mang (UC Berkeley), Qizheng Zhang (Stanford University), Huanzhi Mao (UC Berkeley), Xiaokun Chen (Tensormesh), Hangrui Zhou (Tsinghua University), Alvin Cheung, Joseph Gonzalez, Ion Stoica (UC Berkeley), *Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live*, arXiv:2511.02230v6, 25 May 2026. Names are listed in byline order.  
**Where to consult:** §4.1 *Utility Model* for the cost model; §4.2 *Setting the TTL Value* for how TTL is derived from tool call durations, prefill/loading costs, and measurements of program continuity; §5.1 *Tool Call Handler* and §5.2 *Efficient Pin with TTL in Scheduler* for the runtime mechanism. The paper's term is "queueing delay."  
**Useful point:** Multi-turn Agent cache management can use TTL and lifecycle information while considering queueing and prefill/reload costs.  
**Use in this project:** Ground the existing source of intermediate signals and motivate testing them at Block level. Do not equate a TTL deadline with a calibrated reuse probability or assume Continuum already implements the proposed Block selector.  
**Link:** https://arxiv.org/abs/2511.02230

### 9.3 KVFlow

**Source:** Zaifeng Pan, Ajkumar Patel, Zhengding Hu (UC San Diego), Yipeng Shen (AWS), Yue Guan (UC San Diego), Wan-Lu Li (AWS), Lianhui Qin (UC San Diego), Yida Wang (AWS), Yufei Ding (UC San Diego), *KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows*, arXiv:2507.07400v1, 10 Jul 2025. Names are listed in byline order.  
**Where to consult:** §3.1 *Agent Step Graph and Steps-to-Execution* for the graph representation, the `steps-to-execution` value, and shared-prefix handling in tree-structured caches; §3.2 *Workflow-Aware Eviction Priority Assignment* for how those values become eviction priorities.  
**Useful point:** Workflow proximity to future activation can guide fine-grained KV-node eviction, including shared prefix structures. The paper describes preserving "shared prefixes in tree-structured caches" and retaining shared nodes while any agent still needs them.  
**Use in this project:** A useful comparator to online Continuum signals. Consider workflow-distance information as an additional baseline or signal, rather than assuming it is equivalent to tool-duration/inter-request-gap history.  
**Link:** https://arxiv.org/abs/2507.07400

### 9.4 When Fancy Eviction Fails

**Source:** Yiyu Liu, Minlan Yu, and Juncheng Yang (Harvard University), *When Fancy Eviction Fails: Rethinking Cache Replacement For LLM Prefix Reuse*, arXiv:2609.28870v2, 1 Oct 2026.  
**Where to consult:** Abstract; §3 *Fancy Algorithms Do Not Work Well* for the LRU baseline result; §4.5 *Heavy-Tailed Session Footprints*; §5.1 *Quick Demotion*; §5.2 *Compute-awareness*; §5.3 *Block-Level vs. Session-Level Eviction*; §6 *Discussion*; Appendix A *Capacity Sweeps* and Appendix C *Compute Savings under the Linear Cost Model*. The paper's design principles are, in its own words, "keeping recency as the baseline while incorporating quick demotion to filter one-hit prompts, compute-aware eviction to prioritize expensive misses, and capacity-adaptive eviction granularity."  
**Useful point:** Across the paper's studied production traces and policies, sophisticated policies often provide limited gains over LRU, while quick demotion, compute-aware eviction, and capacity-adaptive eviction granularity can help in specific conditions.  
**Use in this project:** Justify a strong LRU baseline, careful conditional intervention, cost-aware outcome measurement, and testing partial granularity. Do not treat the paper's block-level versus session-level eviction discussion as identical to partial-tail unpin.  
**Link:** https://arxiv.org/abs/2609.28870

### 9.5 vLLM RFC #37003

**Source:** vLLM issue/RFC #37003, "[RFC]: Context-Aware KV-Cache Retention API (Prioritized Evictions)," Proposed Change.  
**Useful point:** Token-range retention directives (`RetentionDirective` with `start`, `end`, `priority`, and `duration`) are an engineering precedent for representing retention at finer than whole-entry granularity.  
**Use in this project:** Inform the API/data-model discussion for Idea 4. This is an RFC/engineering proposal, not peer-reviewed evidence of performance gains, and nothing in it should be cited as a measured result. **Verification note:** In offline/restricted environments where `github.com` cannot be queried directly, the title and description are cross-referenced against the repository's reference notes at `docs/Background-RelatedWork-Motivation/References&Notes/参考文献/关于vLLM的参考文档与网址.md`; confirm the live issue status before citing it externally.  
**Link:** https://github.com/vllm-project/vllm/issues/37003

---

## 10. Unresolved Risks and Open Questions

These risks are not removed by better experimental design. They are stated here so that a null or negative result is not mistaken for a failed experiment.

**Risks.**

- **Identity evidence may stay too weak to act on.** The A2 bounded evaluation records 402 of 778 decisions falling back with `content_unverified`, and 82 of 122 forced-release windows remained unpairable or identity-incomplete. If that rate persists on the W1-C workload, Ideas 1 and 2 will spend most of their decisions in fallback and no scoring improvement will be observable.
- **The baseline is already downstream-aware.** `_release_sort_key()` consumes the native rank of the Blocks a release would expose. Idea 3's headroom is therefore smaller than a deadline-only baseline would imply, and the A1 precedent — a score-free rule reproducing 54/54 recorded choices — shows how quickly an apparently richer ordering collapses onto a simple one.
- **Signal availability, not signal quality, is the binding constraint on Idea 2.** Only the TTL deadline reaches the Block selector today. Until the decision-time contract is extended, Idea 2 cannot be tested at all, and `ExternalToolDurationHistory` has no consumer to extend from.
- **Sample size may not support the models.** The W1-C pilot is 20 paired tasks. Whether it yields enough uncensored turn-gap observations per tool type and program stage to estimate a conditional gap distribution is an open question that Phase A must settle before any model is fit.
- **Partial-tail unpin may be unimplementable rather than merely unproven.** Protection is an Entry-level Boolean, and the in-repository `KVCacheManager` has no sub-request granularity. Idea 4 may fail on representation and ownership grounds before any performance question arises.
- **Attribution may not survive combination.** Each idea is testable in isolation, but the factorial stage assumes the isolated effects compose. Nothing in the current evidence establishes that they do.

**Open questions.**

- Does the Tier 1/Tier 2 split leave enough Tier 2 movement for Entry-ordering changes to alter the victim set at all?
- How much of the deadline's information is already carried by native recency, and does any residual add value conditional on both?
- Can the runtime carry an additional signal to the eviction decision point without breaking the immutability guarantees the adapter contract relies on?
- Do the W1-C traces contain enough repeated pressure events at comparable capacity to support paired comparison, or are events too heterogeneous to pool?
- Which idea, if any, survives the factorial stage, and does any interaction reverse an isolated gain?

## 11. Final Recommendation

The strongest immediate research plan is:

1. Establish reliable decision-level ground truth and the actual Native-LRU baseline.
2. Test whether Continuum intermediate signals add predictive value beyond the current deadline proxy (Idea 2).
3. Test conditional intervention using the signal/loss model validated in Phase A (Idea 1).
4. With the Block selector fixed, test whether downstream-aware Entry release ordering improves the physical victim set (Idea 3).
5. Separately test whether partial-tail unpin preserves more reusable prefix at comparable capacity (Idea 4).
6. Only then evaluate combinations, so each gain or regression can be attributed.

The four ideas are technically distinct and all are reasonable research directions. No idea in this proposal has demonstrated a gain: the project evidence motivates testing them and does not establish that any of them improves performance. The deliverable should therefore present them as testable optimization hypotheses, directly cite the relevant prior work, and define what result would support or reject each one.
