# Experimental Plan

## Project Theme

**Cost-Aware KV Cache Eviction for LLM Serving**

The project studies the following decision problem:

> When GPU KV-cache capacity is insufficient, which cached request/prefix should be evicted so that future recomputation or reload cost is reduced without unnecessarily increasing queueing delay or policy overhead?

The project focuses on **online eviction decisions under cache pressure**, rather than redesigning the entire LLM inference runtime.

---

## Research Questions

### RQ1 — Cost-aware eviction vs. recency-based eviction

Can a dynamic cost-aware eviction policy improve LLM serving performance over a recency-based KV-cache eviction policy such as LRU?

Primary comparison:

- vLLM-style LRU eviction
- proposed cost-aware eviction policy

### RQ2 — Cost-aware eviction vs. a recent strong baseline

How does the proposed online cost-aware eviction policy compare with a recent retention-based KV-cache management approach?

Primary comparison:

- Continuum-style TTL / retention baseline
- proposed cost-aware eviction policy

The implementation should reproduce the relevant decision logic as faithfully as practical for the selected runtime and clearly document any simplifications.

### RQ3 — Workload sensitivity

Under which workload conditions does cost-aware eviction help the most?

Candidate workload dimensions include:

- short-request dominated vs. long-request dominated;
- mixed request lengths;
- low vs. high cache pressure;
- low vs. high prefix reuse;
- steady vs. bursty arrivals, if supported by the final benchmark setup.

The final workload matrix should remain small enough to run reproducibly within course-project resource limits.

---

## Baselines

### Baseline 1 — vLLM 0.27.1 native APC LRU

Baseline 1 is the native GPU Automatic Prefix Caching (APC) eviction behavior in **vLLM 0.27.1**.

The Phase 0 backend validation confirmed the real allocation/eviction path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

The free-block queue maintains cached free blocks in block-level LRU order. A cached free block selected from the queue head can be physically reassigned, after which `_maybe_evict_cached_block()` removes its cached hash metadata.

This baseline answers:

> How much is gained by using signals beyond recency?

Important terminology boundary:

- **vLLM APC LRU** is the project's production/weak baseline and refers to vLLM's block-level free-cache ordering;
- **SGLang Leaf-LRU** is a different implementation over a radix/prefix-tree cache and should not be treated as the same concrete policy implementation, even though both belong to the recency-based eviction family.

All experimental policies must use the same vLLM backend and the same underlying allocation/bookkeeping path wherever practical.

### Baseline 2 — Continuum-style TTL / retention policy

Continuum remains the current recent strong-baseline target.

**The exact reproduction scope is not yet frozen.** Literature notes may identify candidate components such as TTL calculation, pin/unpin behavior, scheduling priority, and pressure handling, but those notes are not the implementation specification.

Before Member 3 implements this baseline, Member 1 must freeze the adaptation scope in `docs/baseline-freeze.md` after considering both:

- the mechanism described by the Continuum paper;
- what can be represented faithfully on the pinned vLLM 0.27.1 GPU APC path.

The freeze must document:

- which Continuum decision mechanism is reproduced;
- which candidate components are included or excluded;
- what runtime assumptions differ from the original system;
- what unit of retention/eviction is used in the vLLM adaptation;
- how the adapted policy interacts with the common policy/runtime path;
- why the resulting baseline remains a fair and meaningful comparison.

The baseline must not silently collapse into ordinary LRU, and the adaptation must not be described as a faithful full-system reproduction if major Continuum system components are omitted.

### Optional baseline — reuse/workflow-aware policy

Additional policies such as ARC, RLT, SAGA/WA-LRU, or another reuse/workflow-aware method may be added only if time and runtime support permit.

They are **not required** for the minimum project scope. Their primary role at this stage is related-work and mechanism comparison unless explicitly promoted through a later project freeze.

---

## Proposed Method

### Dynamic Cost-Aware Eviction

When cache capacity is insufficient and one or more cached entries must be removed, the proposed policy will rank eviction candidates according to an online estimate of eviction loss.

The conceptual decision function is:

```text
EvictionCost(request) = f(
    recomputation_cost,
    reuse_signal,
    memory_footprint,
    waiting_or_admission_impact
)
```

The exact scoring function is **not yet frozen** and must be finalized after the baseline implementation and profiling phase.

Candidate signals include:

- cached token count;
- occupied KV blocks;
- estimated prefill/recomputation cost;
- recent reuse history or another online reuse signal;
- request age / waiting time;
- current cache pressure;
- expected memory released by eviction.

The method should select the lowest-loss victim set that frees enough capacity.

### Required distinction from baselines

The proposed method must not be merely:

- a renamed LRU policy;
- a fixed TTL;
- manual parameter tuning of Continuum;
- an offline policy that assumes unavailable future knowledge.

Its intended distinction is:

> make an online victim-selection decision at eviction time using explicit cost signals, instead of relying only on recency or a fixed retention horizon.

### Ablation requirement

The final implementation should make major score components configurable so that Member 6 can evaluate which signals actually contribute to performance.

Example ablations may include:

- recomputation cost only;
- recomputation cost + memory footprint;
- reuse signal only;
- full cost model.

These are examples, not frozen experiment settings.

---

## Runtime / Backend

### Frozen backend

The real inference backend is frozen to:

```text
vLLM 0.27.1
```

Primary research target:

```text
GPU Automatic Prefix Caching (APC) eviction
```

This project does **not** use the CPU KV-offload cache-policy subsystem as its primary experimental path.

### Phase 0 validation status

Phase 0 — Backend & Architecture Validation is complete.

Validated on the available single-GPU environment:

- real GPU inference: PASS;
- APC initialization and real prefix-cache hit: PASS;
- controlled GPU KV-cache pressure: PASS;
- real cached-block selection and eviction: PASS;
- block-level LRU semantics: PASS;
- kernel changes required: NO.

A cache-pressure smoke configuration used `gpu_memory_utilization=0.30`, yielding approximately `0.32 GiB` of GPU KV cache and `28,368` cache tokens. Under repeated distinct-prefix requests, real cached blocks were observed flowing through:

```text
cached free block
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
    -> cached hash metadata removal
```

The temporary instrumentation used for this validation changed observability only and did not change policy behavior.

Detailed evidence is recorded in `docs/vllm-smoke-test.md` and backend architecture decisions in `docs/backend-selection.md`.

### Common policy integration requirement

The project should introduce the smallest practical policy adapter around the real victim-selection boundary while preserving common vLLM allocation and cache bookkeeping.

Conceptually:

```text
vLLM runtime state
      -> project policy adapter
      -> candidate metadata/context
      -> {native LRU, Continuum-style baseline, Cost-Aware}
      -> ordered victim block set
      -> common BlockPool allocation/eviction bookkeeping
```

Member 3 and Member 4 must not implement baselines and the proposed method through unrelated backend paths, because that would make performance comparisons difficult to interpret.

The deterministic repository simulator remains useful for interface/unit testing only and must not be used for real serving-performance claims.

---

## Models

Current Phase 0 smoke model:

```text
Qwen/Qwen2.5-0.5B-Instruct
```

This model is validated as feasible for backend smoke tests on the available GPU, but the **formal experiment model selection remains to be frozen**. The final comparison must use the same model and model configuration for all policies.

---

## Dataset

TBD.

Member 5 should select dataset(s) or request traces that can support meaningful KV-cache reuse and cache-pressure experiments.

Dataset selection must document:

- public source;
- license / availability if relevant;
- preprocessing procedure;
- sampling rules;
- random seed;
- prompt-length distribution;
- requested/generated output-length handling;
- whether prefix reuse is naturally present or synthetically constructed.

Synthetic workloads may be used for controlled analysis, but they must be clearly separated from real-data experiments.

---

## Workloads

The final benchmark should include a compact set of controlled workloads rather than a large number of arbitrary scenarios.

Candidate categories:

### W1 — Short-request workload

Primarily short prompts / contexts.

Purpose: test whether sophisticated eviction offers little benefit when recomputation costs are small.

### W2 — Long-request workload

Primarily long prompts / contexts.

Purpose: amplify differences in recomputation cost.

### W3 — Mixed-length workload

Mix short and long requests.

Purpose: test whether cost-aware victim selection can distinguish expensive from cheap evictions.

### W4 — High cache-pressure workload

Configure concurrency / memory budget so that eviction is frequent.

Purpose: expose policy differences.

### W5 — Reuse-sensitive workload

Requests contain repeated/reusable prefixes when supported by the selected runtime.

Purpose: test the reuse component of the policy.

Not every candidate workload must remain in the final experiment matrix. The final set should be frozen before formal evaluation.

---

## Metrics

### Serving performance

- Throughput
- TTFT (Time To First Token)
- TPOT (Time Per Output Token)
- End-to-end request latency / completion time

### KV-cache behavior

- KV-cache utilization
- Cache hit / reuse rate, where meaningful
- Eviction count
- Evicted blocks / tokens
- Recomputed tokens or equivalent recomputation volume
- Preemption/reload events, where applicable

### Optimization overhead

- Policy decision latency
- CPU overhead of victim selection
- Additional metadata / memory overhead

### System metrics

Where supported by the final backend:

- GPU memory usage
- GPU utilization

Every reported metric must have a clear definition and collection method before formal runs begin.

---

## Experimental Comparisons

At minimum, formal experiments should compare:

```text
vLLM 0.27.1 native APC LRU
vs.
Continuum-style recent strong baseline (scope frozen separately)
vs.
Proposed dynamic cost-aware policy
```

All methods must use:

- the same model;
- the same request trace;
- the same cache/memory budget;
- the same vLLM/backend version;
- the same hardware;
- the same relevant batching/scheduling settings unless a baseline intrinsically requires a documented policy-specific scheduling mechanism;
- the same random seed where randomness exists.

Only policy-specific settings may differ, and those differences must be documented.

---

## Analysis Plan

The project should answer not only whether the proposed method is faster, but also **why**.

For each major result, Member 6 should try to connect performance changes to cache behavior, for example:

```text
fewer costly evictions
    -> fewer recomputed tokens
    -> lower prefill/recovery work
    -> lower latency and/or higher throughput
```

The evaluation must also include cases where the proposed method provides limited benefit or regresses.

Candidate expected limitation:

> When requests have similar cache sizes and recomputation costs, cost-aware ranking may converge toward simpler policies while still paying additional decision overhead.

This is a hypothesis to test, not a conclusion.

---

## Hardware

Current validated development environment includes a single NVIDIA GeForce RTX 4060 Laptop GPU with 8 GiB-class VRAM under Docker Desktop / WSL2 GPU passthrough.

Formal experiment hardware details must still be frozen and recorded exactly before final runs, including:

- GPU model and VRAM;
- CPU model if policy overhead is material;
- host memory;
- CUDA version;
- framework/runtime version;
- operating system / container image where relevant.

---

## Reproducibility

Formal runs must use:

- fixed random seed;
- frozen request traces;
- same model and model revision;
- same memory/cache budget;
- same runtime version;
- frozen experiment configuration;
- repeated runs where runtime variance is non-negligible;
- raw result files stored before plotting;
- plots generated from scripts rather than manually edited data.

Large datasets, model weights, and profiling traces should not be committed to Git. Store only scripts, manifests, configuration, and lightweight reproducibility metadata.

---

## Scope Boundaries

The minimum project scope does **not** require:

- multi-GPU inference;
- custom CUDA kernels;
- redesigning attention kernels;
- speculative decoding;
- distributed KV-cache transfer;
- CPU KV offloading as the primary mechanism;
- a full reproduction of every component in Continuum or another related system;
- training or fine-tuning an LLM.

The research contribution should remain focused on **GPU APC KV-cache eviction / retention decisions during LLM serving**.

---

## Ownership and Freeze Process

### Member 1 — architecture / backend / project-level freeze

Member 1 owns:

- authoritative backend/runtime facts;
- the common policy-integration boundary;
- final baseline-set approval;
- the Continuum adaptation/reproduction-scope freeze;
- cross-policy runtime fairness constraints.

### Member 2 — literature evidence

Member 2 owns:

- background and related-work research;
- mechanism summaries;
- evidence for why candidate baselines are relevant;
- identifying adjacent/competing approaches and novelty risks.

Member 2's notes may recommend candidate reproduction components, but they do not freeze implementation scope.

### Member 3 — baseline implementation

Member 3 owns implementation and validation of the baselines after the scope is frozen.

If the frozen scope proves infeasible on vLLM 0.27.1, Member 3 should report the concrete blocker; Member 1 then updates the freeze rather than allowing silent implementation drift.

---

## Current Status and Freeze Points

### Frozen now

- Overall topic: KV Cache Management Optimization for LLM Inference
- Research focus: Cost-Aware KV Cache Eviction for LLM Serving
- Real backend: vLLM 0.27.1
- Primary subsystem: GPU Automatic Prefix Caching eviction
- Native production/weak baseline: vLLM 0.27.1 APC block-level LRU
- Recent strong baseline target: Continuum-style retention policy
- Phase 0 backend/architecture validation: COMPLETE
- Core evaluation questions: RQ1, RQ2, RQ3 above

### Not frozen yet

- exact Continuum reproduction/adaptation scope;
- exact common policy-adapter API;
- exact proposed scoring function;
- formal experiment model(s);
- dataset(s);
- final workload matrix;
- formal-run hardware/configuration;
- final hyperparameters.

These items should remain explicitly unfrozen until the relevant owner provides evidence and the project records the decision.
