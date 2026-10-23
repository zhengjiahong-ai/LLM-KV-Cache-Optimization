# KV Cache Management Optimization for LLM Inference

## Goal

This course project studies **cost-aware KV-cache eviction for LLM serving** on a real vLLM backend.

The broader system context includes retention/protection and scheduling coordination, but the research contribution remains centered on one primary decision:

> **When GPU KV-cache capacity is insufficient, which cached blocks/prefixes should be evicted to minimize future recomputation cost?**

The project therefore uses the following hierarchy:

```text
Primary research core
    Cost-Aware Eviction / Victim Selection

Supporting cache mechanism
    Retention / Protection

System coordination
    Scheduling
```

Retention and scheduling are included where needed to reproduce strong system baselines and to evaluate later coordination extensions. They do not replace eviction as the main research problem.

## Current Status

The current **authoritative Phase 2 research/gate ledger** is [`docs/research-status.md`](docs/research-status.md). Older design and phase-plan files remain useful as historical evidence but must not be read as the current authorization.

```text
Phase 0 / 1A / 1B          CLOSED — real vLLM/APC integration and Continuum-style baseline
Phase 2A H1/H2            CLOSED — H1 DIAGNOSTIC_ONLY; H2 does not unlock B1
Phase 2B / 2C / 2E       CLOSED — fidelity, workload audit and native-baseline evaluation
Phase 2G A1               BOUNDED EVALUATION — independent gain vs sufficient-first unproven
Phase 2G A2               INCONCLUSIVE — no reliable independent block-level value
W0 / W1-A                 CLOSED — source audit and authentic Agent trajectory acquisition
W1-B (PR #73)             UNDER REVIEW — M1 RC1–RC4 pending; reported smoke not accepted
W1-C                      AUTHORIZED BOUNDED PILOT — stratified S50/S100 feasibility only
Formal benefit campaign    NOT AUTHORIZED
```

The W1-A first cohort consists of ten SWE-bench Verified tasks, all from Astropy; nine are right-censored at the 50-step limit. W1-B uses sparse turns and controlled replay pressure, rather than the Continuum paper's original serving arrivals. Do **not** interpret its submitted A1−A0 token delta as a formal improvement estimate.

The real backend is frozen to **vLLM 0.27.1** with GPU Automatic Prefix Caching (APC).

## Research Structure

### Core contribution path

```text
vLLM native APC LRU
        vs.
Cost-Aware Eviction
```

This comparison is the primary algorithmic contribution and must remain independently evaluable with native scheduling fixed.

### Supporting / system-level path

```text
Eviction
  + Retention
  + Scheduling coordination
```

These layers are used for:

- reproducing Continuum-style system behavior;
- testing whether retention further strengthens eviction decisions;
- testing whether scheduling coordination further improves end-to-end performance.

## Current Architecture

```mermaid
flowchart TD
    A[Workload / Session Events] --> B[Request & Session Observation]
    B --> C[Retention State Manager]
    C --> D[Scheduling Policy Adapter]
    D --> E[vLLM Scheduler]
    C --> F[Retention Eligibility Filter]
    F --> G[Eviction Policy Adapter]
    G --> H[vLLM KVCacheManager / BlockPool]
    E --> H
    H --> I[GPU APC KV Cache]
    H --> J[Metrics / Profiling]
```

The **Eviction Policy Adapter is the primary research decision boundary**. Retention and scheduling provide context or coordination around it.

The validated Phase 1A eviction path is:

```text
vLLM cached free blocks
    -> VLLMEvictionBridge
    -> EvictionPolicyAdapter
    -> selected block IDs
    -> native BlockPool allocation / eviction bookkeeping
```

## Baselines

### Baseline 1 — vLLM native system

- vLLM 0.27.1
- GPU APC
- native block-level LRU behavior
- native scheduler

### Baseline 2 — Continuum-style adapted system

Continuum is reproduced as a strong **system-level baseline**, including the retention and scheduling mechanisms required by the frozen Phase 1B scope:

- explicit `program_id/session_id`;
- online tool-gap / reuse history;
- dynamic TTL estimation;
- soft retention protection;
- lazy expiry and deterministic pressure release;
- narrow program-level admission-order scheduling adaptation;
- existing Phase 1A eviction path and native BlockPool cleanup.

This does **not** mean the proposed method becomes scheduler-centric. Continuum's full-system mechanisms are reproduced because they are intrinsic to that baseline.

## Proposed Method

The proposed method starts from **Cost-Aware Eviction / Victim Selection**.

Conceptually:

```text
EvictionLoss = f(
    recomputation_cost,
    reuse_signal,
    memory_footprint,
    cache_pressure
)
```

The exact function is not yet frozen.

After the eviction-only method is validated, optional extensions may add:

```text
Ours-Evict
Ours-Evict+Retention
Ours-Full = Eviction + Retention + Scheduling
```

`Ours-Evict` must remain an independently meaningful method and experiment.

## Key Documents

- [**Current Phase 2 research status**](docs/research-status.md) — authoritative stage/gate ledger, evidence boundaries and PR status.
- [**Phase 2 experiment index**](docs/experiments/README.md) — historical-to-current evidence reading order and algorithm-stage distinctions.

- [`docs/experiment-plan.md`](docs/experiment-plan.md) — research questions and experimental hierarchy.
- [`docs/baseline-freeze.md`](docs/baseline-freeze.md) — frozen Phase 1B Continuum adaptation scope.
- [`docs/continuum-baseline-implementation.md`](docs/continuum-baseline-implementation.md) — current Phase 1B implementation and validation index.
- [`docs/experiments/phase1b-continuum/final-report.md`](docs/experiments/phase1b-continuum/final-report.md) — final Phase 1B real-runtime evidence.
- [`docs/policy-adapter-design.md`](docs/policy-adapter-design.md) — validated Phase 1A block-level eviction adapter.
- [`docs/archive/`](docs/archive/) — superseded spikes and historical implementation records.
- [`docs/team-responsibilities.md`](docs/team-responsibilities.md) — ownership and phase responsibilities.

## Team Responsibilities

Member 1 — Architecture, scheduler/cache interfaces, integration, project management  
Member 2 — Background, related work, motivation  
Member 3 — Baseline system implementation and validation  
Member 4 — **Cost-Aware eviction** design and implementation, then optional coordination extensions  
Member 5 — Dataset, workload and benchmark framework  
Member 6 — Evaluation, visualization, profiling and attribution analysis  
Member 7 — Slides and presentation

## Development Rules

- Do not develop directly on `main`; use task branches and PRs.
- Preserve the common vLLM backend path across policies wherever practical.
- Do not silently change a frozen baseline mechanism.
- Keep eviction-only/component experiments separate from full-system comparisons.
- Do not attribute full-system gains to eviction without component evidence.
- Do not commit model weights, Hugging Face caches, Docker data, or large raw traces.

## Development Status Note

`DummyEvictionPolicy` and the deterministic simulator are **not baselines** and **not the proposed method**. They exist only for deterministic functional/interface testing.
