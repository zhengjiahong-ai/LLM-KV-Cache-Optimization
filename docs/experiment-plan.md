# Experimental Plan

## Project Theme

**Cost-Aware KV Cache Management for LLM Serving**

The project studies how KV-cache retention, eviction, and scheduling coordination can reduce unnecessary recomputation and improve LLM serving performance under constrained GPU memory.

The project no longer treats eviction-time victim selection as the entire research boundary. Instead, victim selection is one validated cache-management subproblem inside a broader system design that may also control retention/protection state and cache-aware scheduling decisions.

---

## Research Questions

### RQ1 — Cache-management policy benefit

Can cost-aware KV-cache management improve serving performance over the native vLLM APC behavior?

Primary comparison:

- vLLM 0.27.1 native APC + native scheduling;
- proposed cost-aware cache-management design.

### RQ2 — Comparison with a recent strong system baseline

How does the proposed design compare with a recent retention-and-scheduling-aware KV-cache management system?

Primary comparison target:

- Continuum-style retention + scheduling behavior;
- proposed cost-aware cache management.

The comparison must clearly separate full-system performance from component-level attribution.

### RQ3 — Where do the gains come from?

How much benefit comes from each layer of the proposed design?

Planned ablation structure:

```text
Ours-Evict
    = cost-aware victim selection only

Ours-Retention
    = retention + eviction, native scheduler fixed

Ours-Full
    = retention + eviction + cache-aware scheduling
```

The exact mechanisms and names may change after profiling, but the final evaluation must include enough ablation to distinguish cache-policy gains from scheduler gains.

### RQ4 — Workload sensitivity

Under which workload conditions does broader cost-aware KV-cache management help the most?

Candidate dimensions include:

- short vs. long requests;
- mixed request lengths;
- low vs. high cache pressure;
- low vs. high prefix reuse;
- short vs. long inter-turn/tool gaps;
- steady vs. bursty arrivals;
- single-turn vs. multi-turn/agent-like request structures where feasible.

---

## Baselines

### Baseline 1 — vLLM 0.27.1 native APC + native scheduler

**Status: FROZEN**

Backend:

```text
vLLM 0.27.1
```

Subsystem:

```text
GPU Automatic Prefix Caching (APC)
```

Validated native eviction path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

Phase 1A additionally validated a block-level policy adapter against native LRU ordering in real GPU inference. This adapter remains the execution substrate for cache-policy experiments, but it is not the full research boundary.

### Baseline 2 — Continuum-style retention + scheduling

**Status: STRONG BASELINE TARGET; FULL ADAPTATION SCOPE TO BE FROZEN**

Continuum is relevant because it treats KV-cache retention and scheduling as coupled system decisions for multi-turn/agent workloads.

The project should not reduce Continuum to a retention-only baseline and then describe it as a full reproduction. Before Member 3 implements it, `docs/baseline-freeze.md` must freeze:

- dynamic TTL / retention logic;
- pin/unpin or equivalent protection semantics;
- memory-pressure behavior;
- scheduling behavior required to represent the baseline;
- request/session-to-vLLM-cache mapping;
- which original components cannot be reproduced faithfully;
- which results are full-system comparisons and which are component-level comparisons.

If an implementation omits major Continuum scheduling behavior, it must be labeled `Continuum-style retention` rather than `Continuum reproduction`.

### Optional component baselines

ARC, RLT, SAGA/WA-LRU, or other reuse-aware eviction policies may still be used as component-level references if they materially improve attribution. They are not currently required as full-system baselines.

---

## Proposed Method

### Cost-Aware KV Cache Management

The proposed design may operate at three coordinated layers:

#### Layer 1 — Eviction / victim selection

When memory must be reclaimed, rank candidate cached blocks or prefixes according to estimated eviction loss rather than recency alone.

Conceptually:

```text
EvictionLoss = f(
    recomputation_cost,
    reuse_signal,
    memory_footprint,
    cache_pressure
)
```

#### Layer 2 — Retention / protection

High-value reusable KV state may receive temporary protection or a dynamically chosen retention horizon when the expected cost of losing it is high.

Potential signals include:

- observed reuse history;
- predicted/estimated idle gap;
- cached token or block volume;
- recomputation cost;
- current memory pressure.

The exact retention rule is not frozen.

#### Layer 3 — Cache-aware scheduling coordination

The scheduler may use cache state or recomputation cost when deciding which request/session to resume or prioritize, when doing so can avoid expensive KV loss or recomputation.

The exact scheduler modification is not frozen and should be kept minimal enough for attribution and implementation feasibility.

### Required distinction from related systems

The proposed method must not be merely:

- renamed LRU;
- fixed TTL;
- manual tuning of Continuum;
- a scheduler-only heuristic with no cache-management contribution;
- an offline policy assuming unavailable future information.

The intended contribution is a **cost-aware coordination framework** in which retention, eviction, and possibly scheduling decisions are driven by explicit runtime estimates of the consequences of losing KV state.

---

## Architecture

The project now treats the system as two interacting decision layers:

```text
Request arrivals / active sessions
        |
        v
Scheduling Coordination Layer
        |
        v
KV Cache Management Layer
  - retention / protection
  - eviction / victim selection
        |
        v
vLLM BlockPool / GPU APC
```

Phase 1A already validated the lower eviction boundary:

```text
vLLM free cached blocks
    -> VLLMEvictionBridge
    -> EvictionPolicyAdapter
    -> selected block IDs
    -> native BlockPool eviction bookkeeping
```

This remains valid and should be reused rather than replaced.

A scheduler/retention interface should be added above it only after the required runtime state and ownership are understood. The project should avoid a large vLLM scheduler rewrite unless evidence shows it is necessary.

---

## Runtime / Backend

### Frozen backend

```text
vLLM 0.27.1
```

Primary cache subsystem:

```text
GPU Automatic Prefix Caching (APC)
```

CPU KV offloading is not the primary mechanism.

### Phase 0 — Backend & Architecture Validation

**COMPLETE**

Validated:

- real GPU inference;
- APC initialization;
- real prefix-cache hit;
- controlled GPU KV-cache pressure;
- real cached-block eviction;
- native block-level LRU semantics.

### Phase 1A — Common Eviction Policy Adapter

**COMPLETE**

Validated in real vLLM 0.27.1:

- 85 shadow-policy events;
- 0 native/adapter mismatches;
- 85 adapter-controlled events;
- real GPU inference under adapter control;
- 2,741 observed cached-block evictions;
- native downstream metadata cleanup retained;
- request-level P1/P2/P3-to-block mapping remains not established.

Phase 1A is a validated infrastructure component, not a reason to restrict the whole project to eviction-only research.

---

## Models

Current validated smoke model:

```text
Qwen/Qwen2.5-0.5B-Instruct
```

Formal experiment model selection remains to be frozen. All compared policies must use the same model/configuration within each controlled experiment.

---

## Dataset / Workload Requirements

Member 5 should support both cache-pressure experiments and, if the broader design is retained, multi-turn/session-style workloads that expose retention and scheduling behavior.

The final workload set should include a compact subset of:

- short-request workload;
- long-request workload;
- mixed-length workload;
- high cache-pressure workload;
- repeated-prefix workload;
- multi-turn/session workload with controlled idle gaps;
- bursty arrival workload where scheduling effects are observable.

Synthetic workloads may be used for controlled mechanism analysis, but must be clearly distinguished from real-data or trace-driven evaluation.

---

## Metrics

### Serving performance

- throughput;
- TTFT;
- TPOT;
- end-to-end request latency;
- job/session completion time for multi-turn workloads.

### KV-cache behavior

- cache utilization;
- hit/reuse rate;
- eviction count;
- evicted blocks/tokens;
- recomputed tokens or equivalent recomputation volume;
- retention lifetime / protected KV volume;
- preemption/reload events where applicable.

### Scheduling behavior

If scheduling is modified, record at minimum:

- queueing/waiting time;
- resume order / scheduling decisions;
- preemption count;
- starvation/fairness indicators where relevant.

### Overhead

- eviction-policy decision latency;
- retention-policy overhead;
- scheduling-decision overhead;
- additional CPU and metadata memory overhead.

---

## Experimental Comparison Structure

The evaluation should contain two complementary levels.

### A. Controlled component comparison

Hold the scheduler fixed where possible:

```text
Native LRU
vs.
Ours-Evict
vs.
Ours-Retention
```

Purpose: attribute gains to cache-management components.

### B. Full-system comparison

Allow each system's intrinsic scheduling/cache coordination:

```text
vLLM native system
vs.
Continuum-style/full adapted baseline
vs.
Ours-Full
```

Purpose: answer the broader system-performance question.

The report must not mix conclusions from A and B. A component-level result supports mechanism attribution; a full-system result supports end-to-end system comparison.

---

## Fairness Principles

For controlled comparisons, keep constant wherever applicable:

- model and revision;
- vLLM version;
- hardware;
- workload/trace;
- cache budget;
- batching configuration;
- random seeds;
- metric definitions.

For full-system comparisons, policy-specific scheduling/retention behavior may differ when intrinsic to the method, but these differences must be documented and analyzed through ablation.

---

## Scope Boundaries

The project may modify:

- KV-cache retention/protection decisions;
- eviction/victim-selection logic;
- request/session scheduling priority where needed for cache-aware coordination.

The minimum project still does **not** require:

- multi-GPU inference;
- custom CUDA kernels;
- attention-kernel redesign;
- speculative decoding;
- distributed KV transfer;
- CPU KV offloading as the primary mechanism;
- model training/fine-tuning.

The project should remain a single-GPU serving-system study rather than expanding into distributed serving.

---

## Ownership

### Member 1

Owns:

- backend/runtime architecture;
- cache-policy adapter;
- scheduler/cache-management interface boundary;
- baseline scope freeze;
- integration and cross-policy fairness rules.

### Member 2

Owns:

- background and related work;
- mechanism summaries;
- evidence for baseline relevance;
- novelty-risk identification.

### Member 3

Owns:

- baseline implementation after the baseline scope is frozen;
- reporting concrete reproduction blockers.

### Member 4

Owns:

- proposed cost-aware mechanism implementation, including cache-policy components and any scheduler component assigned after architecture freeze.

### Member 5

Owns:

- datasets/traces/workloads/benchmark harness.

### Member 6

Owns:

- formal experiments, metrics, profiling, ablation, and attribution analysis.

---

## Current Status

### Frozen

- Overall topic: KV Cache Management Optimization for LLM Inference
- Broader research scope: retention + eviction + scheduling coordination
- Backend: vLLM 0.27.1
- Cache subsystem: GPU APC
- Native baseline: vLLM APC + native scheduler
- Phase 0: COMPLETE
- Phase 1A common eviction adapter: COMPLETE
- Continuum: strong system-baseline target

### Not frozen

- exact Continuum full-system adaptation scope;
- scheduler interface / minimal modification point;
- retention-state representation;
- proposed cost model;
- proposed scheduling rule;
- formal models/datasets/workloads;
- final experiment matrix and hyperparameters.

The next architecture task is to map Continuum's retention and scheduling mechanisms onto vLLM 0.27.1 and identify the minimum scheduler/retention hooks required for a faithful-enough strong baseline and for the proposed system.
