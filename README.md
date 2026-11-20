# Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM

## Project Positioning

This project investigates how to improve **Continuum-style, program-aware KV cache management** adapted to vLLM 0.27.1, with a focus on cost-aware decisions under GPU memory pressure.

The project is not a generic KV-cache eviction framework developed independently of a system baseline. It first builds and validates a project-side Continuum-style management baseline, then studies whether cost-aware policies can improve two distinct decisions within that management path:

1. **Entry Release:** when retained cache entries must yield to memory pressure, which logical entry should be released first?
2. **Physical Block Victim Selection:** after entries become eligible, which physical KV blocks should Native vLLM actually evict?

The system foundation includes program/session identity, tool-gap and reuse history, dynamic TTL estimation, soft retention protection, pressure-driven release, and a narrow program-level scheduling adaptation. These mechanisms are adapted to vLLM interfaces; the project does not claim a byte-for-byte or source-level reproduction of the original Continuum system.

**Working research title:** *Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM.*

See [Research Motivation and Contributions](docs/research-motivation-and-contributions.md) for the canonical motivation, research questions, contribution boundaries, and terminology.

## Current Status (as of 2026-11-20)

**Repository:** [zhengjiahong-ai/LLM-KV-Cache-Optimization](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization)  
**Main HEAD before this documentation update:** `4a8ff8e3f9c3829be4fd542f8a19132f1837d753` (PR #124 merged).

- Phase 0 / 1A / 1B: **CLOSED**. The project-side Continuum-style baseline is integrated and real-runtime validated.
- Phase 2: **HISTORICAL / CLOSED**. Findings remain scoped to their original evidence.
- Phase 3: **M1 ACCEPTED FOR BOUNDED PAIRED-EFFECT INTERPRETATION**. The 270/270 campaign is reconciled; frozen replay-order and historical process deviations remain recorded.
- Phase 4: **RESEARCH / DIAGNOSIS COMPLETE**. Its analyses inform later work but are not confirmatory evidence for Phase 5.
- Phase 5: **CURRENT** — M1 accepts the six-system trace-driven design; PR #124 engineering integration is merged; dataset acquisition and qualification are next.

### Phase 5 at a glance

| Area | Current state |
| --- | --- |
| Formal design | M1 accepts M4's six-system design; protocol JSON remains `DESIGN_FROZEN_CANDIDATE` |
| Engineering | PR #124 merged; CPU/Mock campaign path integrated |
| DVA-ER v1 | 28 focused CPU correctness tests passed; formal candidate selection/freeze gate remains open |
| SWE-bench traces | New Phase 5 acquisition not completed |
| BFCL Web Search traces | New acquisition and frozen fixtures not completed |
| Qualified Cohort | Not selected; no Phase 5 Workload Seal |
| Native GPU Conformance | Not passed; Phase 5E Part A remains a GPU gate |
| GPU Calibration / Formal | Not started and not authorized |

The approved next work package is [Phase 5 Dataset Acquisition & Construction](docs/experiments/phase5-dataset-acquisition-and-construction.md). It covers SWE-bench Verified coding-agent traces and BFCL v4 Web Search traces with frozen tool fixtures. PR #125 was merged on 2026-11-19; the documentation pause is lifted and the approved dataset-construction work package may proceed.

**Important distinction:** PR #124 establishes CPU/Mock contracts and production-shaped runner wiring. It does not establish live EngineCore/BlockPool behavior, Native concurrency, GPU conformance, trace availability, cohort qualification or algorithmic benefit. Dataset-construction approval does not authorize GPU Calibration or Formal execution.

See the [canonical M1 status ledger](docs/research-status.md), [Phase 5 Formal Protocol](docs/experiments/phase5-formal-protocol.md), and [Phase 5 dataset construction decision](docs/experiments/phase5-dataset-acquisition-and-construction.md).

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
