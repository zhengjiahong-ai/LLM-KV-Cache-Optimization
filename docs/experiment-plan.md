# Experimental Plan

## Current Phase 3 execution overlay (M1 reconciliation, 2026-11-10)

**Canonical status:** [docs/research-status.md](research-status.md). This overlay records the current frozen Option F campaign and M1 execution authorization. It does not rewrite historical research questions or prior phase verdicts.

### Current delivery and authorization

| Item | Status | Evidence / boundary |
| --- | --- | --- |
| Protocol v3 | Historical / superseded | PR #90 remains immutable history |
| Protocol v4 — Option F | **FROZEN** | [Protocol v4](phase3-final-evaluation-protocol-v4.md) |
| Six-arm materializer | **MERGED** | PR #93; CPU/Mock and materialization validation |
| Independent N/E/C evaluator | **MERGED** | PR #94; RC1–RC4 closed |
| G0 v3 | **ACCEPTED by M1 (2026-11-07)** | 40 tasks / 20 Groups / 10 repositories; existing 40-run A0 calibration bound |
| One-shot execution | **AUTHORIZED / NOT STARTED** | [M1 270-run authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md) |
| M6 pre-launch readiness | **NOT YET RECORDED ON MAIN** | Host, runner, GPU allocation, resource reservation, and hash validation must be reported before launch |

### Frozen campaign

- Six arms: **N0 / A0 / A1 / A2 / A3 / E0**.
- Main: **20 Groups × C1/C2 × 6 arms = 240 runs**.
- Noise: **5 frozen Groups × C1/C2 × 3 repeats = 30 runs**.
- Total new-run budget: **270** in one continuous compute window.
- Existing A0 Load Calibration: **40 runs, reused; no rerun**.
- The Workload Group is the statistical unit. C1/C2 are repeated operating conditions within a Group, not independent groups.
- The Main primary paired population is 18 complete Groups; H3-0 uses all 20 Groups / 38 Headroom-qualified cells; H3-R uses 9 RESPONSIVE Groups / 16 cells.

### Fixed conditions and gates

- C1 and C2 are the frozen operating-point names. Their required_blocks are 256 and 1024 respectively; source labels L_LOW / L_HIGH are provenance only and must not be promoted to “low pressure” / “high pressure”.
- Headroom requires rho0 >= 0.05 and R0 >= 512; frozen result: 38/40 cells.
- FLAT / WEAK / RESPONSIVE strata are frozen as 3 / 8 / 9 Groups and are not post-hoc exclusion filters.
- The 30-run Noise stage must produce and persist the exact Protocol v4 pooled estimator and tied threshold.
- Main may start only after the machine-verified transition gate validates all 30 Noise Run IDs, the independent evaluator, all applicable mandatory gates, and all frozen hashes.
- Any missing evidence, undefined required pooled value, mandatory gate failure, or hash mismatch stops the pipeline before Main. No intermediate manual M1 review is required when the automatic gate passes.

### Research interpretation

The campaign separates Entry Release from physical Block Victim Selection. A0−N0 is the registered forced-Entry-Release contrast; A1/A3/E0 change Entry Release selection; A2 changes physical block selection. The Phase 3 Native scheduler is held fixed. TTL inputs/decisions are observable, but no Static-TTL arm is present. Therefore the campaign does not independently estimate Dynamic TTL versus Static TTL or the program-level scheduler's performance effect. See [mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

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
