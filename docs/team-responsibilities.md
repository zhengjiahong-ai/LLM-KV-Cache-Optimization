# Team Responsibilities

> **Current project positioning (2026-11-10):** The project optimizes a project-side Continuum-style program-aware KV cache management adaptation on vLLM. Phase 1B establishes the baseline; the current research evaluates cost-aware Entry Release and physical Block Victim Selection. Exact reproduction of the original Continuum system is not claimed. See [Research Motivation and Contributions](research-motivation-and-contributions.md) and [Research Status](research-status.md).

This document defines ownership and phase responsibilities for the seven project members. For the **current** phase and its authorized scope, read [`research-status.md`](research-status.md); the baseline responsibilities below remain historical/general guidance where newer M1 authorizations assign narrower operational ownership.

## Project hierarchy

~~~text
System foundation
    Continuum-style program-aware multi-turn KV cache management

Current optimization targets
    Cost-Aware Entry Release
    Cost-Aware Physical Block Victim Selection

Supporting system mechanism
    Program-level scheduling adaptation
~~~

The project does not treat Continuum retention and scheduling as unrelated add-ons: they form part of the adapted system baseline. The optimization contribution is evaluated at the specific cache decision layers varied by the frozen protocol.

## Current Phase 3 ownership and execution authority

This overlay is authoritative for the current Option F campaign and takes precedence over the historical role descriptions below.

- **M1:** research architecture, phase grants, canonical status, Protocol v4 freeze, fairness/claim boundaries, integration, and final evidence adjudication.
- **M4:** frozen Protocol v4 semantics and post-campaign effect/statistical analysis. No routine protocol redesign is authorized.
- **M6:** pre-launch readiness, one-shot 270-run execution, automatic Noise-to-Main transition, Native evidence, independent evaluator outputs, execution statistics, and immutable evidence archive.
- **M5:** shared workload/runner substrate only if a concrete interface gap remains.
- **M2/M3:** background/source-mechanism review and frozen baseline support.
- **M7:** final report and presentation preparation after the evidence and claims are accepted.

**Current gate:** G0 v3 was accepted by M1 on 2026-11-07. The one-shot 270-run pipeline is AUTHORIZED / NOT STARTED. M6 must still record the execution host, runner, GPU allocation, full resource reservation, and frozen-hash checks. The 240-run Main stage is conditional on the machine-verified Noise transition gate; no intermediate manual M1 review is required if that gate passes.

## Historical initial role descriptions

The Member 1–7 descriptions and the original Ours-Evict / Ours-Full implementation roadmap below document the project's earlier division of labor. They are retained for provenance and are **not the active execution assignments** where they conflict with the current Phase 3 overlay above. In particular, the old mandatory Ours-Evict deliverable is not the current Phase 3 arm definition.

## Shared rules

1. `main` must remain runnable; all changes go through task branches and PRs.
2. `docs/research-status.md` is the canonical live status; Protocol v4 and the M1 authorization govern the current campaign; `docs/baseline-freeze.md` governs immutable Phase 1B semantics.
3. Do not silently simplify a frozen baseline or change the cohort, manifests, arms, estimands, gates, or run plan.
4. Real performance claims require valid Native vLLM evidence and independent evaluation, not simulator output alone.
5. Keep logical Entry Release, physical Block Victim Selection, Native physical eviction, later APC status, and recomputed-token outcomes as separate evidence levels.
6. Do not attribute Dynamic TTL or scheduler performance effects to Phase 3; neither has a corresponding randomized treatment.

---

## Member 1 — Architecture, Scheduler/Cache Interfaces, Integration, Project Management

### Primary goal

Own the end-to-end architecture of the project-side Continuum-style cache-management adaptation and preserve clean boundaries between lifecycle/retention, logical Entry Release, physical block-victim selection, and Native vLLM ownership.

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
- Why cost-aware Entry Release and physical Block Victim Selection are studied within a Continuum-style system foundation.
- Why Phase 3 fixes Native scheduling and separates logical release from physical eviction.
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

Implement and validate frozen baselines. The Continuum-style Phase 1B baseline implementation and real-runtime validation are complete; Member 3 now keeps the baseline frozen for fair comparison and only fixes validation-backed defects.

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
- implementation: **COMPLETE**
- real-runtime validation: **COMPLETE**
- final integration to `main`: **COMPLETE**
- Phase 1B status: **CLOSED**

### Phase 2 — Bottleneck identification and Cost-Aware eviction

Work begins in parallel:

- Member 5 builds reproducible controlled workloads and benchmark entry points;
- Member 6 profiles the frozen baselines and reports the eviction/recomputation bottleneck;
- Member 2 refreshes the novelty boundary relevant to Cost-Aware eviction;
- Member 4 studies available online signals, then freezes and implements `Ours-Evict` based on the observed problem;
- Member 1 maintains the common runtime/policy interface and integration boundary.

Exit condition:

> Cost-Aware victim selection can be compared against native LRU with native scheduling fixed, and the method is motivated by measured baseline behavior rather than an assumed bottleneck.

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
