# Experimental Plan

## Project Theme

**Cost-Aware KV Cache Eviction for LLM Serving**

The primary research question is:

> When GPU KV-cache capacity is insufficient, which cached blocks/prefixes should be evicted so that future recomputation cost is minimized without introducing excessive policy overhead or unfair queueing effects?

The project keeps retention and scheduling in scope as supporting/system-level mechanisms, but they do not replace eviction/victim selection as the research core.

## Research hierarchy

```text
Primary contribution
    Cost-Aware Eviction / Victim Selection

Supporting extension
    Retention / Protection

System extension
    Scheduling Coordination
```

---

## Research Questions

### RQ1 — Core eviction question

Can Cost-Aware victim selection outperform native recency-based vLLM APC LRU under identical scheduling and cache budgets?

Primary comparison:

```text
vLLM native APC LRU
vs.
Ours-Evict
```

This is the project's main algorithmic comparison.

### RQ2 — Why and when does Cost-Aware eviction help?

Under which workload conditions does Cost-Aware eviction reduce expensive recomputation most effectively?

Candidate dimensions:

- short vs. long requests;
- mixed request lengths;
- low vs. high cache pressure;
- low vs. high prefix reuse;
- heterogeneous recomputation cost;
- steady vs. bursty arrivals where useful.

Analysis should connect:

```text
victim-selection change
    -> fewer costly evictions
    -> fewer recomputed/prefill tokens
    -> latency / throughput impact
```

### RQ3 — Does retention further improve the eviction-centered method?

After `Ours-Evict` is validated independently, evaluate whether a retention/protection mechanism provides additional benefit.

Comparison structure:

```text
Ours-Evict
vs.
Ours-Evict+Retention
```

Retention is an extension, not a prerequisite for the core method.

### RQ4 — Does scheduling coordination further improve full-system performance?

Evaluate the incremental effect of scheduling coordination only after the eviction and retention components are separately measurable.

Comparison structure:

```text
Ours-Evict+Retention
vs.
Ours-Full
```

Full-system comparisons may additionally include Continuum.

---

## Baselines

### Baseline 1 — vLLM 0.27.1 native APC + native scheduler

**Status: FROZEN**

Validated native GPU APC path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

This is the primary weak/native baseline for RQ1.

### Baseline 2 — Continuum-style adapted system

**Status: PHASE 1B SCOPE FROZEN**

Continuum is the strong system-level baseline and includes the mechanisms frozen in `docs/baseline-freeze.md`:

- explicit program/session identity;
- tool-gap/reuse history;
- dynamic TTL;
- soft retention protection;
- lazy expiry / pressure release;
- narrow program-level admission-order scheduling adaptation;
- native vLLM BlockPool bookkeeping.

Continuum is reproduced as a full-system comparison point because retention+scheduling are intrinsic to that baseline. This does not change the project's own research core from eviction to scheduling.

### Optional component baselines

ARC, RLT, SAGA/WA-LRU, or another eviction/reuse-aware method may be used if they improve attribution and are feasible within project time.

---

## Proposed Method

### Ours-Evict — mandatory core method

The proposed core method ranks eviction candidates according to estimated eviction loss.

Conceptually:

```text
EvictionLoss = f(
    recomputation_cost,
    reuse_signal,
    memory_footprint,
    cache_pressure
)
```

Possible runtime signals include:

- cached token/block count;
- estimated prefill/recomputation cost;
- recent reuse history;
- cache pressure;
- memory released by eviction;
- request/prefix age when justified.

The exact score is not yet frozen.

The method must not be merely:

- renamed LRU;
- fixed TTL;
- manual tuning of Continuum;
- offline future knowledge;
- scheduler-only prioritization.

`Ours-Evict` must run with native scheduling and be independently evaluable.

### Ours-Evict+Retention — optional/secondary extension

May add retention/protection if evidence shows that proactive preservation complements victim selection.

### Ours-Full — system extension

May add scheduling coordination after the eviction and retention effects are separately measurable.

---

## Architecture and Backend

Backend:

```text
vLLM 0.27.1
GPU Automatic Prefix Caching (APC)
```

Phase 0 backend validation: **COMPLETE**.

Phase 1A common block-level eviction adapter: **COMPLETE**.

Validated project decision path:

```text
vLLM free cached blocks
    -> VLLMEvictionBridge
    -> EvictionCandidate[]
    -> EvictionPolicyAdapter
    -> selected block IDs
    -> native BlockPool cleanup
```

This adapter is the primary execution boundary for RQ1/RQ2.

Retention and scheduler adapters are auxiliary layers around this core path.

---

## Experimental Structure

### A. Primary eviction experiments

Hold fixed:

- native scheduler;
- model;
- request trace;
- cache budget;
- batching/runtime settings;
- hardware;
- random seed where applicable.

Compare:

```text
Native LRU
vs.
Ours-Evict
```

This experiment answers the main research question.

### B. Retention extension experiments

Compare:

```text
Ours-Evict
vs.
Ours-Evict+Retention
```

Purpose: quantify additional benefit from retention.

### C. Full-system experiments

Compare:

```text
vLLM native
vs.
Continuum-style adapted system
vs.
Ours-Full
```

Purpose: evaluate end-to-end system performance.

Do not use C alone to claim superiority of the eviction algorithm.

---

## Workloads

The final matrix should remain compact and reproducible.

Recommended categories:

- short-request workload;
- long-request workload;
- mixed-length workload;
- high cache-pressure workload;
- reuse-sensitive workload;
- controlled multi-turn/session workload for Continuum/system experiments.

Multi-turn/session traces are required for the strong system baseline, but the primary eviction experiments should also include scheduler-independent controlled workloads.

---

## Metrics

### Core eviction metrics

- eviction count;
- evicted blocks/tokens;
- recomputed tokens or equivalent recomputation volume;
- cache hit/reuse rate;
- victim-selection decision latency;
- additional policy metadata/CPU overhead.

### Serving metrics

- throughput;
- TTFT;
- TPOT;
- end-to-end latency.

### Supporting system metrics

For retention/scheduling extensions:

- protected KV volume / retention lifetime;
- queueing/waiting time;
- program/session completion time;
- scheduling decisions / admission order;
- preemption/reload events where relevant.

---

## Fairness Rules

For primary eviction comparisons, scheduler behavior must remain identical.

For full-system comparisons, policy-specific retention/scheduling may differ only when intrinsic to the compared system and must be documented.

All formal comparisons should keep constant where applicable:

- model and revision;
- vLLM version;
- hardware;
- request trace;
- cache/memory budget;
- batching settings;
- generation parameters;
- metric definitions;
- seeds.

---

## Ownership

### Member 1

Owns backend/runtime architecture, adapter boundaries, baseline freeze, integration, and fairness rules.

### Member 2

Owns background/related work and verifies original mechanism vs. adaptation claims.

### Member 3

Owns implementation and validation of native/Continuum baselines according to `docs/baseline-freeze.md`.

### Member 4

Owns the **Cost-Aware eviction algorithm first**. Retention/scheduling extensions come only after `Ours-Evict` is independently implemented and validated.

### Member 5

Owns reproducible workloads/traces, including both eviction-focused traces and multi-turn/session traces.

### Member 6

Owns evaluation and must separate eviction attribution from retention/scheduling/full-system effects.

---

## Current Freeze State

### Frozen

- Overall topic: KV Cache Management Optimization for LLM Inference
- **Primary research core: Cost-Aware KV Cache Eviction / Victim Selection**
- Supporting scope: retention + scheduling coordination
- Backend: vLLM 0.27.1 GPU APC
- Native baseline: vLLM APC LRU + native scheduler
- Strong system baseline: Continuum-style adapted system
- Phase 0: CLOSED
- Phase 1A: CLOSED
- Phase 1B Continuum adaptation scope: FROZEN

### Not frozen

- exact Cost-Aware eviction score;
- exact proposed retention extension;
- exact proposed scheduling extension;
- formal model/dataset/workload matrix;
- final hyperparameters.

The next immediate implementation task remains Phase 1B Continuum baseline implementation. After that, Member 4 should start from `Ours-Evict`, not from a monolithic full-system method.
