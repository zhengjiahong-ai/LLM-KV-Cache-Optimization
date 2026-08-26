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

### Baseline 1 — vLLM-style LRU

LRU is retained as a production-oriented baseline because current LLM serving systems still use recency-based eviction in KV-cache/prefix-cache management.

This baseline answers:

> How much is gained by using signals beyond recency?

The baseline should use deterministic tie-breaking and run through the same cache-manager/runtime path as the proposed method.

### Baseline 2 — Continuum-style TTL / retention policy

A recent strong baseline inspired by Continuum will represent retention-aware KV-cache management.

The exact implementation scope is not yet frozen. Before implementation, the team must document:

- which Continuum decision mechanism is reproduced;
- what runtime assumptions differ from the original system;
- which components are omitted;
- why the resulting baseline remains a fair and meaningful comparison.

The baseline should not silently collapse into ordinary LRU.

### Optional baseline — KVFlow-style reuse-aware policy

KVFlow-style workflow/future-reuse-aware eviction may be added only if time and runtime support permit.

It is **not required** for the minimum project scope because a faithful implementation may require workflow structure or future-execution information that is not available in ordinary serving traces.

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

TBD.

The repository currently contains a deterministic logical simulator for interface validation only. It must not be used as evidence for real LLM inference performance.

The final backend should satisfy the following requirements:

- support real LLM inference on available GPU hardware;
- expose or permit modification of KV-cache management decisions;
- allow LRU, strong baseline, and proposed policy to use the same execution path;
- expose enough measurements for latency, throughput, cache behavior, and policy overhead;
- remain feasible to build and reproduce within course-project time constraints.

A vLLM-based implementation is a leading candidate, but the backend is not frozen yet.

---

## Models

TBD.

Model selection should consider:

- available GPU memory;
- ability to create meaningful KV-cache pressure;
- runtime/backend compatibility;
- reproducibility;
- experiment duration.

The final comparison must use the same model and model configuration for all policies.

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
vLLM-style LRU
vs.
Continuum-style recent strong baseline
vs.
Proposed dynamic cost-aware policy
```

All methods must use:

- the same model;
- the same request trace;
- the same cache/memory budget;
- the same runtime/backend version;
- the same hardware;
- the same relevant batching/scheduling settings;
- the same random seed where randomness exists.

Only policy-specific settings may differ.

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

TBD.

Record at minimum:

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
- a full reproduction of every component in Continuum or KVFlow;
- training or fine-tuning an LLM.

The research contribution should remain focused on **KV-cache eviction / retention decisions during LLM serving**.

---

## Current Status and Freeze Points

### Frozen now

- Overall topic: KV Cache Management Optimization for LLM Inference
- Research focus: Cost-Aware KV Cache Eviction for LLM Serving
- Weak/production baseline family: vLLM-style LRU
- Recent strong baseline target: Continuum-style retention policy
- Core evaluation questions: RQ1, RQ2, RQ3 above

### Not frozen yet

- exact real inference backend / version;
- exact Continuum reproduction scope;
- exact proposed scoring function;
- model(s);
- dataset(s);
- final workload matrix;
- hardware;
- final hyperparameters.

These items should remain TBD until the relevant owner provides evidence for the choice.
