# Architecture

The project studies KV-cache management on **vLLM 0.27.1 GPU APC**, with a clear hierarchy of concerns.

> **Current research/evaluation interpretation (2026-11-10):** The project keeps cost-aware KV eviction as its research core, while the frozen Phase 3 campaign distinguishes Entry Release from physical Block Victim Selection. The six-arm Option F mapping and claim boundaries are current; the original `Ours-Evict` schematic below remains a research hierarchy, not a claim that an independent final method has already been validated. Read [canonical status](research-status.md), [experiment index](experiments/README.md), and [frozen Phase 1B baseline](baseline-freeze.md) for their different authority levels.

## Research hierarchy

```text
Primary research core
    Eviction / Victim Selection

Supporting cache mechanism
    Retention / Protection

System coordination
    Scheduling
```

The broader architecture includes all three because strong baselines such as Continuum couple retention with scheduling. However, the proposed research contribution remains centered on improving **which cached KV blocks/prefixes are evicted under memory pressure**.

## System Layers

```text
Workload / Orchestrator
    - request arrivals
    - optional program/session identity
    - controlled tool-gap events
            |
            v
Request / Session Observation Layer
            |
            v
Retention State Manager
       |                                |
       | scheduler context              | eviction eligibility
       v                                v
SchedulingPolicyAdapter          EvictionPolicyAdapter
       |                                |
       +---------------+----------------+
                       v
                 vLLM Scheduler
                       |
                 KVCacheManager
                       |
                    BlockPool
                       |
                 GPU APC KV Cache
```

## Phase 3 decision layers and six-arm mapping

The Phase 1A EvictionPolicyAdapter remains the **physical block-victim boundary**. The Continuum-style pressure path also makes a separate **Entry Release** decision: releasing a protected entry changes eligibility; it does **not** itself evict a KV block.

| Arm | Entry-release selection | Physical block-victim selection | Attribution boundary |
| --- | --- | --- | --- |
| N0 | No-op; no forced Entry Release | Native LRU | Control for the forced-release path; pressure request/barrier/timeline remain active |
| A0 | Frozen project-side Continuum-style Entry Release | Native LRU | Baseline Entry Release policy; not a complete public Continuum reproduction |
| A1 | Cost-Aware Entry Release | Native LRU | Entry-level selection and resulting eligible candidate pool |
| A2 | Same frozen A0 Entry Release | Cost-Aware Block selector | Physical victim choice only |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Suffix-cost Entry decision path |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator |

A2 does **not** combine A1 and A2. A1/A3/E0 change which entries are released; A2 changes which legal Native block is selected. The evidence chain remains: **logical release → selected candidate/victim → Native hashed eviction → later APC prefix status → recomputed tokens**. Each transition requires its own evidence; co-occurrence alone is not physical causal attribution.

All Phase 3 arms use the **Native vLLM scheduler**. The campaign does not include a program-level scheduler treatment. The narrow Continuum scheduler adapter was implemented and real-runtime validated in Phase 1B, but its performance effect is outside the current 270-run estimands.

The registered A0−N0 H3-0 contrast uses every Headroom-qualified cell (20 Groups / 38 cells); H3-R is a separate RESPONSIVE-only contrast (9 Groups / 16 cells). This is a forced-Entry-Release comparison under shared Native scheduling and Native LRU/APC, not a complete Continuum-versus-Vanilla-vLLM system comparison.

Dynamic TTL inputs and decisions are instrumented for mechanism inspection. There is no Static-TTL arm, so Phase 3 cannot independently estimate Dynamic TTL's advantage over Static TTL. See [mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

### Phase 1A physical block adapter



Phase 1A validated the real backend victim-selection path:

```text
native free cached blocks
    -> VLLMEvictionBridge snapshot
    -> EvictionCandidate[]
    -> EvictionPolicyAdapter.select_victims()
    -> selected block IDs
    -> native BlockPool eviction bookkeeping
```

This is the **physical victim-selection boundary** validated by Phase 1A; entry-release selection is a separate upstream Phase 2G research choice (see the preceding section).

It must support at minimum:

- native block-level LRU equivalence;
- Continuum retention-aware eligibility/fallback behavior;
- future Cost-Aware victim selection.

The project must preserve native vLLM ownership of:

- block reference counts;
- free-queue links;
- APC hashes;
- actual allocation;
- metadata cleanup.

## Retention layer

Retention is a supporting mechanism around eviction.

It may determine whether a cached prefix/block should currently be protected from ordinary victim selection, but it does not replace the eviction policy itself.

For the Continuum baseline, retention state is maintained independently of native vLLM block semantics:

```text
program/session
    -> prefix identity
        -> TTL / deadline
        -> protected state
        -> observed blocks
```

Protected blocks remain native free cached blocks and are filtered before ordinary victim selection.

## Scheduling layer

Scheduling coordination is included because Continuum's defining system behavior requires program-level scheduling adaptation and because later full-system experiments may study coordination benefits.

The frozen first boundary is narrow:

```text
read-only scheduler snapshot
    -> SchedulingCandidate[]
    -> SchedulingPolicyAdapter.order(...)
    -> ordered waiting request IDs
    -> native vLLM scheduling bookkeeping
```

The first implementation does not modify running-request preemption order.

Scheduling is therefore a **system coordination layer**, not the primary algorithmic contribution.

## Baseline architecture

### Native vLLM

```text
native scheduler
+
native APC block-level LRU
```

### Continuum-style adapted system

```text
explicit program/session identity
    -> tool-gap history
    -> dynamic TTL
    -> soft retention
    -> program-level admission-order scheduling
    -> native APC / BlockPool backend
```

Continuum is intentionally reproduced as a system-level baseline even though the proposed research core is eviction.

## Proposed architecture

**Original conceptual roadmap, not a completed method/acceptance record.** The staged `Ours-Evict` / `Ours-Full` names below represent the original research hierarchy. Actual evaluated Phase 2G A0/A1/A2 policies have the two-level definitions above; the strong Sufficient-first comparator and formal Native benefit evaluation are not yet complete. See [current research status](research-status.md).

The proposed method should be developed in stages:

```text
Ours-Evict
    = Cost-Aware victim selection
    + native scheduler
    + no proposed retention/scheduling extension required

Ours-Evict+Retention
    = Ours-Evict
    + proposed retention support

Ours-Full
    = Ours-Evict+Retention
    + proposed scheduling coordination
```

`Ours-Evict` is mandatory as an independently evaluable method. Retention and scheduling extensions must not become prerequisites for demonstrating the core contribution.

## Experiment boundaries

### Primary algorithm experiment

Hold scheduling fixed and compare victim selection:

```text
vLLM native LRU
vs.
Cost-Aware Eviction
```

### Supporting component experiments

Evaluate whether retention further improves the eviction-centered method.

### Full-system experiment

Compare intrinsic system combinations such as:

```text
vLLM native
vs.
Continuum-style adapted system
vs.
Ours-Full
```

A full-system gain must not be attributed to eviction alone without the eviction-only/component results.

## Simulator

The deterministic simulator remains useful for interface/unit tests only. Real serving-performance claims must come from the validated vLLM backend.
