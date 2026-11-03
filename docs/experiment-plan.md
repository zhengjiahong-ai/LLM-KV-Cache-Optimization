# Experimental Plan

## Current Phase 3 execution overlay (2026-11-03)

**Canonical status:** [`docs/research-status.md`](research-status.md). This overlay records the current M1-approved Phase 3 direction. Historical research questions and Phase 2 verdicts below remain historical and are not retroactively changed.

### Phase 3 delivery status

| Item | Status | Evidence |
| --- | --- | --- |
| M4 Final Evaluation Protocol v3 | OPEN / DESIGN_ONLY | [PR #90](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/90); requires M1 final freeze and synchronization with current main |
| M6 workload/execution feasibility | MERGED | [PR #92](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/92) |
| Six-arm Materializer, E0/N0 | MERGED — Stage 1 complete | [PR #93](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/93) |
| Independent N/E/C Evaluator | MERGED — Stage 2 complete | [PR #94](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/94) |
| Final data readiness | NEXT — M6 | [M1 data-readiness decision](experiments/phase3-data-readiness-decision.md) |
| Final Evaluation | NOT STARTED / NOT AUTHORIZED | 310-run plan remains unchanged |

### Final cohort requirement

- 40 **new qualified Agent tasks** arranged into 20 independent Workload Groups.
- Two tasks per group, from different repositories.
- Minimum repository coverage: **8 repositories**. This supersedes the earlier ten-repository target in PR #92 and PR #90.
- Existing W1-C's 20 acquired pilot tasks (18 full-payload comparable) are engineering/regression data only and are excluded from the formal cohort.
- M6 must confirm the real Full Payload, Explicit Token IDs, sidecars, Prefill Profile and Native Replay readiness of each selected task. The remaining 80 W1-C IDs are candidates, not acquired traces.
- If fewer than 40 qualified tasks or fewer than 8 repositories are available, report the actual shortfall; do not lower the threshold or expand the frozen candidate frame without M1 approval.

### Final experiment plan

The six arms remain N0/A0/A1/A2/A3/E0. The planned scale remains:

| Set | Runs |
| --- | ---: |
| A0 Load Calibration | 40 |
| A0 Noise Calibration | 30 |
| Main Campaign (20 groups × 2 loads × 6 arms) | 240 |
| **Total** | **310** |

The PR #92 estimate is 3–5 RTX 4090D GPU-hours with a 6-hour ceiling; M6 must reconfirm the estimate against the actual qualified cohort.

M6 is authorized to confirm and acquire/validate Agent traces within the existing 80-candidate W1-C frame. Native calibration, GPU Smoke and Main Campaign remain unauthorized until M1 accepts the data-readiness report and freezes the final protocol/run manifest.

No separate Stage 3 Cohort Seal engineering milestone is required. The final run manifest must still SHA-256 bind task membership, group pairing, Frozen Request Order, Native Enqueue Order, Replay Timeline, Session pairing and per-request History Predecessors before formal execution.

---

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

**Status: IMPLEMENTED AND REAL-RUNTIME VALIDATED**

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

Owns shared reproducible workload/benchmark substrate and runner interface support. M6 owns current W0/W1 source-specific Agent acquisition, replay materialization and evidence.

### Member 6

Owns evaluation and must separate eviction attribution from retention/scheduling/full-system effects. In current W0/W1 stages, also owns Agent trajectory collection, frozen sample design, source provenance, Native replay and statistical/missingness reporting.

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
- Phase 1B implementation and real-runtime validation: COMPLETE

### Not frozen

- exact Cost-Aware eviction score;
- exact proposed retention extension;
- exact proposed scheduling extension;
- formal model/dataset/workload matrix;
- final hyperparameters.

For current authorization and outcome status after these initial freeze notes, consult **[`research-status.md`](research-status.md)**; this section records the original foundational freeze and must not be read as the latest execution authorization.

Before the exact `Ours-Evict` score is frozen:

1. Member 5 prepares reproducible cache-pressure/reuse workloads;
2. Member 6 profiles the frozen baselines and identifies costly eviction behavior;
3. Member 2 refreshes the novelty boundary against current related work;
4. Member 4 finalizes the Cost-Aware objective and score from the observed bottleneck;
5. Member 1 keeps the runtime/policy interface and fairness boundary stable.

The method must still start from `Ours-Evict`, not from a monolithic retention+scheduling system.
