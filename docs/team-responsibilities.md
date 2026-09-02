# Team Responsibilities

This document defines ownership, deliverables, boundaries, dependencies, and acceptance criteria for the seven project members.

The current project scope is **KV Cache Management Optimization for LLM Inference**, covering retention/protection, eviction/victim selection, and scheduling coordination on vLLM 0.27.1.

## Shared rules

1. `main` must remain runnable. All changes go through task branches and pull requests.
2. Frozen decisions in `docs/experiment-plan.md` and `docs/baseline-freeze.md` are authoritative.
3. Do not silently simplify a frozen baseline or expand a scheduler/runtime boundary without updating the freeze.
4. Every technical task must include code or documentation, tests/validation, assumptions/limitations, and a PR.
5. Real serving-performance claims must come from the real vLLM backend, not the deterministic simulator.
6. Component attribution experiments and full-system comparisons must be reported separately.
7. Q&A ownership follows module ownership, but every member should understand how their component fits the end-to-end system.

---

## Member 1 — Architecture, Scheduler/Cache Interfaces, Integration, Project Management

### Primary goal

Own the overall system architecture and keep retention, eviction, scheduling, workloads, metrics, and the real vLLM backend connected through controlled interfaces.

### Main responsibilities

- Maintain the project-level research scope and architecture.
- Own the real vLLM integration boundary.
- Own the common Phase 1A block-level eviction adapter.
- Own the scheduler/cache-management interface and the narrow `SchedulingPolicyAdapter` boundary.
- Freeze baseline adaptation scope and approve later scope changes.
- Preserve common native vLLM allocation, ref-count, hash, and scheduler bookkeeping across policies wherever practical.
- Integrate PRs from Members 3, 4, 5, and 6.
- Resolve cross-module design conflicts and attribution/fairness issues.
- Keep authoritative architecture/backend/status documents synchronized.

### Primary files / directories

- `src/kvopt/runtime/vllm/`
- integration-facing scheduler/cache abstractions
- `configs/`
- `docs/architecture.md`
- `docs/experiment-plan.md`
- `docs/baseline-freeze.md`
- `docs/continuum-vllm-mapping.md`

### Expected deliverables

- Stable real-backend integration path.
- Stable eviction and scheduling policy boundaries.
- Project-level freezes for baseline and proposed-system interfaces.
- End-to-end runnable main branch after each phase.

### Q&A ownership

- Overall architecture and project scope.
- Why retention, eviction, and scheduling are separated/connected as they are.
- vLLM integration decisions.
- Fair-comparison boundaries and system limitations.

---

## Member 2 — Background, Related Work, Motivation

### Primary goal

Provide the literature basis for the project and explain how eviction-oriented, retention-oriented, and workflow/scheduling-aware KV-cache systems differ.

### Main responsibilities

- Study KV cache in LLM inference and serving systems.
- Maintain related-work summaries for eviction, retention, recomputation, preemption, scheduling coordination, and workflow-aware cache management.
- Verify mechanisms and terminology for Continuum and other relevant systems.
- Identify novelty risks and adjacent methods.
- Support Member 1 when distinguishing original-paper behavior from project adaptations.
- Provide slide-ready background/motivation material to Member 7.

### Important boundary

Member 2 provides literature evidence and mechanism interpretation but does **not** freeze implementation scope.

### Q&A ownership

- KV-cache background.
- Existing systems and prior work.
- Why Continuum and native vLLM are used as comparison points.
- Original mechanism vs. adaptation distinctions.

---

## Member 3 — Baseline System Implementation and Validation

### Primary goal

Implement and validate the frozen baselines through the common vLLM backend path.

### Current Phase 1B responsibility

Implement the frozen **Continuum-style retention + program-level scheduling baseline** defined in `docs/baseline-freeze.md`.

The baseline includes:

- explicit external `program_id/session_id`;
- request/session lifecycle observation;
- request/session ↔ prefix/block observation;
- online tool-gap/reuse history;
- dynamic TTL estimation with documented input sources/approximations;
- independent retention state;
- soft protection without changing native `ref_cnt` semantics;
- lazy TTL expiry;
- deterministic pressure release;
- narrow admission-order `SchedulingPolicyAdapter`;
- reuse of the Phase 1A eviction adapter and native BlockPool cleanup path.

### Main responsibilities

- Implement the frozen baseline without silently changing its semantics.
- Add deterministic unit tests for identity, TTL, retention, pressure fallback, mapping cleanup, and scheduler ordering.
- Validate native/shadow/controlled scheduler modes where applicable.
- Run a small real-GPU vLLM 0.27.1 validation after deterministic tests pass.
- Document all approximations and unresolved reproduction gaps.
- Report blockers to Member 1 rather than replacing dynamic TTL with fixed TTL or dropping scheduling silently.

### Primary files / directories

- baseline-specific code under `src/kvopt/`
- real-backend integration only through agreed `runtime/vllm` extension points
- baseline tests under `tests/`
- `docs/continuum-baseline-implementation.md`

### Acceptance criteria

- Dynamic TTL is genuinely history/runtime dependent.
- Multiple request IDs can belong to one explicit program/session.
- Soft protection changes eviction eligibility without corrupting native queue/ref-count/hash bookkeeping.
- Pressure cannot deadlock allocation.
- Controlled scheduler mode changes admission order while native downstream bookkeeping remains correct.
- Real vLLM GPU inference, APC reuse, and eviction still function.
- Existing Phase 1A tests do not regress.

### Q&A ownership

- Baseline algorithm and adaptation details.
- Continuum mechanism → vLLM mapping in the implementation.
- Dynamic TTL inputs and approximations.
- Retention/scheduler edge cases and validation evidence.

---

## Member 4 — Cost-Aware Optimization Design and Implementation

### Primary goal

Own the project's proposed technical contribution: a cost-aware KV-cache management system spanning the subset of retention, eviction, and scheduling decisions justified by evidence.

### Main responsibilities

- Analyze native and Continuum baseline behavior with Members 1, 3, and 6.
- Define the cost model and optimization objective only after baseline/profile evidence is available.
- Implement the proposed method through the same shared runtime boundaries where practical.
- Keep major components configurable for ablation.
- Separate cost-aware retention, eviction, and scheduler contributions where possible.
- Document algorithm inputs, complexity, overhead, assumptions, and failure cases.

### Important boundary

Do not implement Cost-Aware during Phase 1B. The exact cost model and scheduling rule remain unfrozen until the strong baseline is functioning and profiled.

### Q&A ownership

- Proposed method and novelty.
- Cost model and decision logic.
- Complexity, overhead, ablation, and trade-offs.

---

## Member 5 — Dataset, Workload, Benchmark Framework

### Primary goal

Build reproducible workloads that expose both cache-pressure behavior and multi-turn/session retention+scheduling behavior.

### Main responsibilities

- Select public traces/datasets where useful.
- Build controlled synthetic workloads for mechanism validation.
- Support explicit `program_id/session_id`, turn order, tool-gap start/end, arrival timing, and prefix reuse.
- Provide controlled multi-turn/session traces required by Phase 1B.
- Create workload categories such as short/long/mixed requests, low/high pressure, low/high reuse, controlled tool gaps, and bursty arrivals where useful.
- Ensure the same frozen trace/config can be replayed across policies.
- Document preprocessing, seeds, distributions, and whether reuse is natural or synthetic.

### Q&A ownership

- Dataset/trace choice.
- Session/workflow construction.
- Tool-gap and reuse generation.
- Workload fairness and reproducibility.

---

## Member 6 — Evaluation, Visualization, Profiling, and Analysis

### Primary goal

Own formal evaluation and determine both whether the system improves and which component caused the change.

### Main responsibilities

- Define metrics for serving, cache retention/eviction, scheduling, and policy overhead.
- Run reproducible baseline and proposed-system experiments.
- Maintain separate protocols for:
  - component attribution with native scheduling fixed;
  - full-system comparison with intrinsic scheduling/cache coordination.
- Profile recomputation, prefix hits, evictions, protected KV volume, waiting time, scheduling decisions, and policy overhead.
- Generate plots/tables from stored raw results.
- Report regressions and failure cases.

### Target metrics

- throughput;
- TTFT;
- TPOT;
- end-to-end request latency;
- session/program completion time;
- queueing/waiting time;
- APC hit/reuse rate;
- eviction count and evicted blocks/tokens;
- recomputed tokens / preemption/reload events where applicable;
- protected KV volume / retention lifetime;
- scheduling-decision and cache-policy overhead;
- GPU memory/utilization where meaningful.

### Q&A ownership

- Experimental setup and fairness.
- Metric definitions.
- Component attribution vs. full-system claims.
- Profiling and bottleneck interpretation.

---

## Member 7 — Slides and Main Presentation

### Primary goal

Turn the technical work into one coherent presentation and serve as primary presenter.

### Main responsibilities

- Own the final slide deck and talk structure.
- Keep terminology consistent with authoritative project documents.
- Present the system as KV-cache management rather than eviction-only.
- Clearly separate native baseline, Continuum-style adapted system, and the proposed Cost-Aware system.
- Distinguish component attribution experiments from full-system comparisons.
- Collect verified figures/results from Members 1-6.
- Lead rehearsal and route detailed Q&A to module owners.

---

## Cross-member collaboration map

```text
Member 2: related work / mechanism evidence
             |
             v
Member 1: architecture / freezes / integration
     |              |               |
     v              v               v
Member 3         Member 4         Member 5
Continuum        Cost-Aware       workload/session traces
baseline         method
     \              |               /
      \             |              /
       +----------> Member 6
              evaluation / profiling
                     |
                     v
                 Member 7
              slides / presentation
```

---

## Current Development Phases

### Phase 0 — Backend & Architecture Validation

**Status: CLOSED**

- vLLM 0.27.1 real GPU backend validated.
- APC prefix hit and real cache pressure validated.
- native block-level eviction path established.

### Phase 1A — Common Eviction Policy Adapter

**Status: CLOSED**

- block-level `EvictionPolicyAdapter` validated against native LRU ordering;
- real controlled eviction and native metadata cleanup validated.

### Phase 1B — Continuum Baseline

**Status: IMPLEMENTATION SCOPE FROZEN; IMPLEMENTATION NEXT**

- feasibility mapping complete;
- retention+scheduling adaptation scope frozen;
- Member 3 implements and validates the baseline;
- Member 5 can prepare controlled multi-turn/session traces in parallel;
- Member 6 can prepare required metrics in parallel.

Exit condition:

- Continuum-style adapted baseline runs on real vLLM 0.27.1;
- dynamic TTL, retention, pressure behavior, and scheduler ordering are validated;
- limitations/approximations are documented.

### Phase 2 — Baseline Profiling and Cost-Aware Design Freeze

- Member 6 profiles native and Continuum baselines.
- Member 4 finalizes the Cost-Aware method using observed evidence.
- Member 1 freezes any required runtime/interface extensions.

### Phase 3 — Cost-Aware Implementation and Formal Evaluation

- implement Ours and required ablations;
- freeze datasets/workloads/configs;
- execute component and full-system comparisons;
- produce final figures/tables and limitations.

### Phase 4 — Presentation

- Members 1-6 provide verified slide-ready material;
- Member 7 assembles and rehearses the final presentation;
- each member owns Q&A for their subsystem.

---

## Definition of Done

A technical task is complete only when it includes:

1. implementation or finalized decision document;
2. deterministic tests or reproducible validation commands;
3. relevant configuration/workload metadata;
4. assumptions, approximations, and limitations;
5. a PR explaining integration impact;
6. real-backend validation when the task makes serving-system claims.
