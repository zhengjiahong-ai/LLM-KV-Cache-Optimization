# Team Responsibilities

This document defines ownership and phase responsibilities for the seven project members.

## Project hierarchy

The overall topic is KV Cache Management Optimization, but the research contribution has a clear priority:

```text
Primary research core
    Cost-Aware Eviction / Victim Selection

Supporting mechanism
    Retention / Protection

System coordination
    Scheduling
```

Retention and scheduling remain in scope because they are required by the Continuum system baseline and may later be evaluated as extensions. They must not displace eviction as the primary proposed algorithm.

## Shared rules

1. `main` must remain runnable; all changes go through task branches and PRs.
2. `docs/experiment-plan.md` and `docs/baseline-freeze.md` are authoritative for frozen decisions.
3. Do not silently simplify a frozen baseline or expand scheduler/runtime scope.
4. Real performance claims must use the real vLLM backend, not the deterministic simulator.
5. Primary eviction experiments and full-system experiments must be reported separately.
6. Full-system gains must not be attributed to eviction without component evidence.

---

## Member 1 — Architecture, Scheduler/Cache Interfaces, Integration, Project Management

### Primary goal

Own the end-to-end architecture while keeping the **eviction decision boundary central** and integrating supporting retention/scheduling mechanisms without conflating their effects.

### Responsibilities

- Own vLLM 0.27.1 backend integration.
- Maintain the validated Phase 1A `EvictionPolicyAdapter` as the primary policy execution boundary.
- Own scheduler/retention integration interfaces required by strong baselines and later extensions.
- Freeze baseline scope and approve any scope changes.
- Preserve native vLLM allocation/ref-count/hash/scheduler bookkeeping wherever practical.
- Maintain authoritative architecture, status, and fairness documents.
- Integrate Member 3/4/5/6 PRs.

### Q&A ownership

- Overall architecture and project scope.
- Why eviction is the research core.
- Why retention/scheduling are included but treated as supporting/system layers.
- vLLM integration and fairness boundaries.

---

## Member 2 — Background, Related Work, Motivation

### Primary goal

Provide the literature basis for eviction-oriented, retention-oriented, and workflow/scheduling-aware KV-cache systems while keeping the project's novelty claim grounded in eviction/victim selection.

### Responsibilities

- Study and summarize eviction methods such as LRU/Leaf-LRU, ARC, RLT and related work.
- Study retention/workflow systems such as Continuum and SAGA.
- Verify Continuum mechanisms and terminology.
- Identify novelty risks for Cost-Aware eviction.
- Distinguish original-paper behavior from project adaptation.
- Provide slide-ready background and motivation.

### Boundary

Member 2 provides evidence and interpretation but does not freeze implementation scope.

---

## Member 3 — Baseline System Implementation and Validation

### Primary goal

Implement and validate frozen baselines. The current Phase 1B task is the Continuum-style adapted system baseline.

### Current Phase 1B baseline

Implement:

- explicit `program_id/session_id`;
- request/session lifecycle observation;
- request/session ↔ prefix/block observation;
- online tool-gap/reuse history;
- dynamic TTL estimation with documented approximations;
- independent soft retention state;
- lazy TTL expiry;
- deterministic pressure release;
- narrow admission-order `SchedulingPolicyAdapter`;
- reuse of the Phase 1A eviction adapter and native BlockPool cleanup.

### Important research boundary

Continuum includes retention+scheduling because those mechanisms are intrinsic to the **baseline**. M3 must not reinterpret this as a signal that the proposed method should become scheduler-centric.

### Acceptance criteria

- Dynamic TTL is history/runtime dependent.
- Session continuity works across multiple request IDs.
- Soft protection preserves native vLLM queue/ref-count/hash semantics.
- Pressure cannot deadlock allocation.
- Controlled scheduling can alter admission order without corrupting native bookkeeping.
- Real GPU vLLM inference/APC/eviction still work.
- Phase 1A tests do not regress.

---

## Member 4 — Cost-Aware Eviction Design and Implementation

### Primary goal

Own the project's **main technical contribution: Cost-Aware KV-cache eviction / victim selection**.

### Mandatory first deliverable — Ours-Evict

Design and implement an independently evaluable eviction method:

```text
vLLM free cached blocks
    -> Cost-Aware ranking
    -> victim block set
    -> native BlockPool cleanup
```

The method should reason about explicit eviction loss/cost using signals such as:

- recomputation/prefill cost;
- reuse signal;
- memory footprint;
- cache pressure;
- other justified online state.

### Required boundary

`Ours-Evict` must work with **native scheduling fixed** and must be able to stand alone as the primary contribution.

Do not start by building a monolithic retention+scheduling system.

### Later extensions

Only after `Ours-Evict` is implemented and evaluated may M4 add:

```text
Ours-Evict+Retention
Ours-Full = Ours-Evict + Retention + Scheduling
```

These extensions must be ablated separately.

### Acceptance criteria

- More than renamed/tuned LRU.
- No unavailable future knowledge.
- Runs through the shared Phase 1A eviction boundary.
- Decision overhead is measurable.
- Major score components are configurable for ablation.
- Eviction-only benefits can be measured independently of retention/scheduling.

---

## Member 5 — Dataset, Workload, Benchmark Framework

### Primary goal

Build reproducible workloads for both the **core eviction experiments** and the system-level Continuum/full-system experiments.

### Responsibilities

For eviction-focused experiments, support:

- short/long/mixed request lengths;
- heterogeneous recomputation cost;
- low/high cache pressure;
- low/high prefix reuse;
- controlled arrival patterns.

For Continuum/system experiments, additionally support:

- explicit `program_id/session_id`;
- turn order;
- tool-gap start/end;
- controlled multi-turn reuse.

The same frozen trace/config must be replayable across compared policies.

---

## Member 6 — Evaluation, Visualization, Profiling, and Analysis

### Primary goal

Determine both whether the proposed method improves performance and **which component caused the improvement**.

### Mandatory evaluation hierarchy

#### A. Primary eviction attribution

```text
Native LRU
vs.
Ours-Evict
```

Native scheduling must remain fixed.

#### B. Retention extension

```text
Ours-Evict
vs.
Ours-Evict+Retention
```

#### C. Full-system comparison

```text
vLLM native
vs.
Continuum-style adapted system
vs.
Ours-Full
```

### Core metrics

- eviction count and evicted blocks/tokens;
- recomputed tokens / prefill work;
- APC hit/reuse rate;
- victim-selection overhead;
- throughput;
- TTFT;
- TPOT;
- end-to-end latency.

For system extensions, additionally measure retention and scheduling metrics such as protected KV volume, waiting time, admission order and session completion time.

---

## Member 7 — Slides and Main Presentation

### Primary goal

Present one coherent story with the correct research hierarchy.

### Required narrative

The presentation should make this distinction explicit:

```text
Problem:
    expensive wrong KV eviction under pressure

Core method:
    Cost-Aware Eviction / Victim Selection

Strong baseline:
    Continuum-style retention + scheduling system

Extensions:
    retention and scheduling coordination around the core eviction method
```

Do not present the proposed contribution as a generic scheduling system unless later experimental evidence and a formal scope change justify that claim.

---

## Current Development Phases

### Phase 0 — Backend & architecture validation

**CLOSED**

### Phase 1A — Common block-level eviction adapter

**CLOSED**

### Phase 1B — Continuum baseline

- feasibility mapping: **CLOSED**
- implementation scope: **FROZEN**
- implementation/validation: **NEXT**

### Phase 2 — Cost-Aware eviction

Member 4 implements `Ours-Evict` through the validated common eviction boundary.

Exit condition:

> Cost-Aware victim selection can be compared against native LRU with native scheduling fixed.

### Phase 3 — Optional retention/scheduling extensions

Only after the eviction core is validated.

### Phase 4 — Formal evaluation and presentation

Member 6 freezes/runs the experiment matrix; Member 7 integrates verified results into the final presentation.

---

## Definition of done

A technical task requires:

1. implementation or authoritative documentation;
2. tests/validation;
3. assumptions and limitations;
4. reproducible configuration where relevant;
5. a PR explaining the change;
6. no silent drift from the frozen research hierarchy or baseline scope.
