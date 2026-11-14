# Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM

## Project Positioning

This project investigates how to improve **Continuum-style, program-aware KV cache management** adapted to vLLM 0.27.1, with a focus on cost-aware decisions under GPU memory pressure.

The project is not a generic KV-cache eviction framework developed independently of a system baseline. It first builds and validates a project-side Continuum-style management baseline, then studies whether cost-aware policies can improve two distinct decisions within that management path:

1. **Entry Release:** when retained cache entries must yield to memory pressure, which logical entry should be released first?
2. **Physical Block Victim Selection:** after entries become eligible, which physical KV blocks should Native vLLM actually evict?

The system foundation includes program/session identity, tool-gap and reuse history, dynamic TTL estimation, soft retention protection, pressure-driven release, and a narrow program-level scheduling adaptation. These mechanisms are adapted to vLLM interfaces; the project does not claim a byte-for-byte or source-level reproduction of the original Continuum system.

**Working research title:** *Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM.*

See [Research Motivation and Contributions](docs/research-motivation-and-contributions.md) for the canonical motivation, research questions, contribution boundaries, and terminology.

## Current Status (as of 2026-11-14)

**Repository:** [zhengjiahong-ai/LLM-KV-Cache-Optimization](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization)  
**Main HEAD after PR #104 merge:** `c3a53bfc45bd36d4026876658d21d3b4bf845e23`

- Phase 0 / 1A / 1B: **CLOSED**. The common vLLM/APC adapter and the project’s Continuum-style baseline have been integrated and real-runtime validated.
- Phase 2A–2I: historical research and bounded evaluations are closed; their positive, negative, and inconclusive findings remain scoped to their original evidence.
- Phase 3 Protocol v4 — Option F: **FROZEN**. Protocol v3 remains historical.
- G0 v3: **ACCEPTED by M1 on 2026-11-07**. The sealed cohort contains 40 qualified tasks, 20 Workload Groups, and 10 repositories. The existing 40-run A0 Load Calibration is reused.
- One-shot execution: **COMPLETE** — 30/30 Noise + 240/240 Main runs; all 270 run identities reconciled.
- Phase 3 final M1 decision: **ACCEPTED for bounded paired-effect interpretation**, with frozen replay-order conformance failure, historical authorization gap, and transition-ledger gap retained as recorded deviations. This is not a claim that every frozen execution gate passed.
- Mainline promotion: PR #104 is merged. PR #109 carries the subsequent Phase 3/4 evidence package and M4-reviewed R1.3 synthesis for final mainline review.
- Research boundary: tested Cost-Aware arms did not demonstrate incremental recomputation benefit over A0 in this cohort; this does not establish universal algorithm equivalence or impossibility.

The 270 new runs are exactly:

| Stage | Runs | Scope |
| --- | ---: | --- |
| A0 Noise Calibration | 30 | 5 frozen Groups × C1/C2 × 3 repeats |
| Main Campaign | 240 | 20 Groups × C1/C2 × 6 arms |
| **Total new runs** | **270** | One continuous compute window |

The earlier 40-run A0 Load Calibration is existing evidence bound into G0. It is **not** part of the 270 new runs and must not be rerun.

The formal backend is vLLM 0.27.1 with GPU Automatic Prefix Caching (APC). The six arms are N0/A0/A1/A2/A3/E0. The statistical unit is the Workload Group, not a cell, request, turn, or runtime repeat. See the [canonical M1 status ledger](docs/research-status.md) and [Phase 3 Protocol v4](docs/phase3-final-evaluation-protocol-v4.md).

## Research Structure

~~~text
Research target
    Continuum-style, program-aware multi-turn KV cache management on vLLM

System foundation
    Project-side Continuum-style adaptation
    - Program / Session lifecycle and reuse history
    - Dynamic TTL and soft retention protection
    - Pressure-driven Entry Release
    - Narrow program-level scheduling adaptation

Cost-aware optimization under memory pressure
    A. Entry Release policy
       A0 baseline / A1 Cost-Aware / A3 suffix-cost-aware / E0 deadline-only comparator
    B. Physical Block Victim Selection
       Native LRU baseline / A2 Cost-Aware selector

Native execution substrate
    vLLM 0.27.1 GPU APC / KVCacheManager / BlockPool
~~~

The project therefore studies cost-aware optimization **inside a Continuum-style cache-management design**. Retention, Entry Release, physical block selection, and scheduling are related but distinct mechanisms; results must be attributed only to the decision layer actually varied.

## Current Architecture

~~~mermaid
flowchart TD
    A[Workload / Program / Session Events] --> B[Lifecycle and Reuse-History Observation]
    B --> C[Continuum-Style State: Dynamic TTL and Retention]
    C --> D[Pressure-Driven Entry Release]
    D --> E[Eligible Native KV Blocks]
    E --> F[Physical Victim Selection: Native LRU or A2]
    F --> G[vLLM KVCacheManager / BlockPool]
    G --> H[GPU Automatic Prefix Caching]
    G --> I[Native Evidence and Recompute Metrics]
    C -. Phase 1B scheduling adaptation .-> J[Native Scheduler Boundary]
    J -. Phase 3 uses Native scheduler in every arm .-> G
~~~

The common native execution path remains authoritative for allocation, reference counts, APC hashes, physical block reuse, and cleanup. Entry Release changes eligibility; it does not itself perform physical block eviction.

## Baselines

### Baseline 1 — Native vLLM

- vLLM 0.27.1;
- GPU Automatic Prefix Caching;
- Native block-level LRU victim selection;
- Native scheduler.

This is the underlying execution baseline and the unchanged physical-victim policy in most Phase 3 arms.

### Baseline 2 — Project-side Continuum-style adaptation

Phase 1B implemented and real-runtime validated a Continuum-style adaptation to vLLM 0.27.1. Its validated scope includes:

- explicit program/session identity across native request IDs;
- tool-gap and server inter-request-gap history;
- dynamic TTL estimation and PrefillReload inputs;
- soft retention protection and lazy expiry;
- deterministic pressure-driven Entry Release;
- a narrow program-level admission-order scheduling adapter;
- native APC and BlockPool allocation/eviction ownership.

This is a **project-side adaptation**, not an exact reproduction of the original paper's source code, serving traces, or complete system. The implementation and validation boundary is documented in [Continuum Baseline Implementation](docs/continuum-baseline-implementation.md) and the [Phase 1B final report](docs/experiments/phase1b-continuum/final-report.md).

The frozen Phase 3 A0 arm uses the project-side Continuum-style Entry Release path with Native LRU physical block selection. It should not be described as a full-system Continuum-versus-Vanilla-vLLM comparison.

## Phase 3 evaluation boundary

The formal Phase 3 campaign evaluates **local cost-aware policy changes within the project-side Continuum-style cache-management path**. It is not a full-system comparison of the original Continuum system against untouched vLLM.

- **A0 − N0:** incremental effect of the frozen forced Entry Release path versus no forced Entry Release, with pressure requests, replay barriers, Native LRU/APC, and the Native scheduler held in common.
- **A1 − A0 and A3 − A0:** changes to the Entry Release decision.
- **A2 − A0:** changes only physical block-victim selection, retaining the A0 Entry Release path.
- **A3 versus E0:** registered cost-model discriminability comparison against the deadline-only Step 2 comparator.

All Phase 3 arms use the Native vLLM scheduler. The Phase 1B program-level scheduler adaptation was separately implemented and real-runtime validated, but its performance effect is not estimated by this campaign.

TTL inputs and decisions are available for mechanism inspection. There is no Static-TTL arm, so Phase 3 does not estimate Dynamic TTL versus Static TTL. No optimization benefit is claimed before the formal run evidence and independent evaluation are accepted.

## Cost-Aware Optimization Candidates

The current research does not assume that a particular cost-aware policy is already superior. It evaluates several candidates at two decision layers:

| Arm | Entry Release | Physical Block Victim | Purpose |
| --- | --- | --- | --- |
| N0 | No forced Entry Release | Native LRU | Control |
| A0 | Frozen Continuum-style Entry Release | Native LRU | Adapted baseline |
| A1 | Cost-Aware Entry Release | Native LRU | Entry-level cost-aware candidate |
| A2 | Same A0 Entry Release | Cost-Aware selector | Physical block-level candidate |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Entry-level suffix-cost candidate |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator |

A2 is not a combined A1+A2 policy. Entry Release and physical victim selection are separate decisions. The exact definitions, metrics, estimands, and gates are frozen in [Phase 3 Protocol v4](docs/phase3-final-evaluation-protocol-v4.md).

The four potential follow-on directions (not part of Phase 3 and not authorized for implementation) are preserved in [Potential Future Research Directions](docs/future-research-directions.md): evidence-aware Block intervention, workflow-aware Block signals, downstream-cost-aware Entry Release, and partial-tail Entry unpinning.

## Key Documents

- [**Post-Phase-3 experimental roadmap**](docs/post-phase3-experimental-roadmap.md) — proposed Phase 4 algorithm development and Phase 5 four-system evaluation under representative Agent workloads; planning only, not an execution authorization.
- [**M1 canonical research status**](docs/research-status.md) — current phase, accepted decisions, execution authorization, and claim boundaries.
- [**Experiment and decision index**](docs/experiments/README.md) — navigation across historical evidence and current Phase 3 records.
- [**Phase 3 Final Evaluation Protocol v4 — Option F**](docs/phase3-final-evaluation-protocol-v4.md) — frozen estimands, operating points, populations, noise estimator, and gates.
- [**One-shot 270-run authorization**](docs/experiments/phase3-option-f-270-run-pipeline-authorization.md) — operative M1 execution authorization and automatic transition contract.
- [**Option F engineering status**](docs/experiments/phase3-option-f-engineering-status.md) — G0 acceptance, engineering validation, and execution status.
- [**Mechanism coverage and claim boundaries**](docs/experiments/phase3-mechanism-coverage-and-claim-boundaries.md) — what Phase 1B validated and what Phase 3 can/cannot establish.
- [**Final report outline**](docs/phase3-final-report-outline.md) — planned structure for the eventual research report.
- [**Experimental plan**](docs/experiment-plan.md) — research questions and experiment hierarchy.
- [**Baseline freeze**](docs/baseline-freeze.md) — immutable Phase 1B Continuum-style semantics.
- [**Continuum baseline implementation**](docs/continuum-baseline-implementation.md) — implementation and real-runtime validation index.
- [**Phase 1B final report**](docs/experiments/phase1b-continuum/final-report.md) — accepted baseline evidence.
- [**Policy adapter design**](docs/policy-adapter-design.md) — validated physical block-level eviction boundary.
- [**Team responsibilities**](docs/team-responsibilities.md) — project ownership.
- [**Archive**](docs/archive/) — superseded spikes and historical implementation records.

## Team Responsibilities

Member 1 — Research architecture, Continuum-style baseline integration, phase gates and final evidence adjudication  
Member 2 — Continuum / related-work mechanism review and research motivation  
Member 3 — Continuum-style baseline implementation and regression support  
Member 4 — Cost-Aware Entry Release and physical block-victim policy design and analysis  
Member 5 — Shared workload, benchmark and runner infrastructure  
Member 6 — Formal workload execution, independent evaluation and evidence analysis  
Member 7 — Research narrative, slides and presentation

## Development Rules

- Do not develop directly on `main`; use task branches and PRs.
- Preserve the common vLLM backend path across policies wherever practical.
- Do not silently change a frozen baseline mechanism.
- Keep eviction-only/component experiments separate from full-system comparisons.
- Do not attribute full-system gains to eviction without component evidence.
- Do not commit model weights, Hugging Face caches, Docker data, or large raw traces.

## Development Status Note

`DummyEvictionPolicy` and the deterministic simulator are **not baselines** and **not the proposed method**. They exist only for deterministic functional/interface testing.
