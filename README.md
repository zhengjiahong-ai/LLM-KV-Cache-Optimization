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

The authoritative **M1 project and authorization ledger** is
[`docs/research-status.md`](docs/research-status.md). Phase 3 execution history
and the current data-readiness decision are indexed in
[`docs/experiments/README.md`](docs/experiments/README.md).

```text
Phase 0 / 1A / 1B             CLOSED — real vLLM/APC integration and baseline
Phase 2A–2I                   CLOSED / bounded findings preserved; see ledger
Phase 3 Protocol v3           PR #90 MERGED — FROZEN by M1 (reviewed HEAD 3a8c388)
Phase 3 Workload Feasibility  PR #92 MERGED — feasibility established, not a final dataset
Phase 3 Stage 1               PR #93 MERGED — six-arm materializer, E0/N0 CPU/Mock
Phase 3 Stage 2               PR #94 MERGED — independent N/E/C evaluator (RC1–RC4)
Final dataset                 NEXT — M6 selects/acquires 40 tasks + 24 reserves from 80 candidates
Final evaluation              CONDITIONALLY AUTHORIZED — after cohort seal and frozen gates
```

Current data boundary:
- W1-C froze 100 candidate task IDs; 20 were acquired for the S50/S100 pilot.
- 18 pilot tasks are full-payload comparable, but all historical pilot tasks are
  excluded from the formal Phase 3 cohort.
- The remaining 80 IDs are candidates, not acquired Agent traces. They span
  ten repositories in the current frozen frame.
- The frozen minimum for the final cohort is **at least 10 repositories**,
  with 20 groups and two tasks from different repositories per group.
- M6's next deliverable is an evidence-backed data-readiness report. No Native
  calibration or GPU campaign has started.

The Phase 3 comparison remains six arms: N0/A0/A1/A2/A3/E0. The planned
evaluation remains 40 A0 load-calibration runs + 30 A0 noise-calibration runs
+ 240 main-campaign runs = 310 runs. The estimate in M6 PR #92 is 3–5 RTX
4090D GPU-hours with a 6-hour planning ceiling; M6 must reconfirm against the
actual qualified cohort before formal execution.

The real backend is frozen to **vLLM 0.27.1** with GPU Automatic Prefix
Caching (APC).
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

The **final independently validated Ours-Evict contribution and scoring claim** are not frozen. This conceptual sketch is not an assertion that no Cost-Aware code exists: A1 (entry-level forced release) and A2 (block-level victim selection) have already been implemented and evaluated in bounded studies, with their independent algorithmic value still under investigation. See [current status](docs/research-status.md) and the [experiment index](docs/experiments/README.md).

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
