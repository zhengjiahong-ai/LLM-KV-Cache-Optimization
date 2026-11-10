# Architecture

> **Project objective:** Cost-aware optimization of a project-side Continuum-style, program-aware KV cache management adaptation on vLLM 0.27.1. Continuum-style lifecycle/retention is the system foundation; cost-aware Entry Release and physical Block Victim Selection are the current optimization targets. This is not a claim of exact reproduction of the original Continuum system. See [Research Motivation and Contributions](research-motivation-and-contributions.md).

The project studies KV-cache management on **vLLM 0.27.1 GPU APC**, with a clear hierarchy of concerns.

> **Current research/evaluation interpretation (2026-11-10):** The project studies cost-aware optimization within a project-side Continuum-style, program-aware cache-management adaptation. The Phase 3 campaign evaluates local changes to logical Entry Release and physical Block Victim Selection; it does not evaluate a monolithic Ours-Evict system or a full-system Continuum-versus-Vanilla comparison. Earlier Ours-Evict / Ours-Full diagrams below are historical conceptual roadmap only. The current six-arm mapping and claim boundaries are defined above and in [canonical status](research-status.md), [experiment index](experiments/README.md), and [Protocol v4](phase3-final-evaluation-protocol-v4.md).

## Research hierarchy

~~~text
System foundation
    Project-side Continuum-style program-aware cache management
    - Program / Session lifecycle and reuse history
    - Dynamic TTL and soft retention protection
    - Pressure-driven Entry Release
    - Narrow program-level scheduling adaptation

Current optimization targets
    1. Cost-Aware Entry Release
    2. Cost-Aware Physical Block Victim Selection

Native execution substrate
    vLLM 0.27.1 GPU APC / KVCacheManager / BlockPool
~~~

Retention and scheduling are intrinsic to the Continuum-style system foundation. The formal Phase 3 campaign changes only registered cache decision policies; it holds the Native scheduler fixed.

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
- the registered A2 Cost-Aware physical block-victim selector.

The project must preserve native vLLM ownership of:

- block reference counts;
- free-queue links;
- APC hashes;
- actual allocation;
- metadata cleanup.

## Retention layer

Retention is part of the Continuum-style system foundation. It determines whether a cached logical entry or observed prefix should remain protected during its retention window, and when pressure may release that protection. It is distinct from physical Block Victim Selection: releasing protection changes eligibility but does not itself remove a physical KV block.

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

The narrow program-level admission-order adapter is part of the Phase 1B Continuum-style system adaptation and was real-runtime validated at its controlled Native request boundary. Phase 3 does not install or vary this adapter: every Phase 3 arm uses the Native vLLM scheduler. Its performance contribution is therefore not estimated by the current campaign.

The frozen first boundary is narrow:

```text
read-only scheduler snapshot
    -> SchedulingCandidate[]
    -> SchedulingPolicyAdapter.order(...)
    -> ordered waiting request IDs
    -> native vLLM scheduling bookkeeping
```

The first implementation does not modify running-request preemption order.

Scheduling is therefore a validated system-integration mechanism, not a Phase 3 treatment or a demonstrated performance advantage.

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

The project-side Continuum-style adaptation is the system foundation for the current cost-aware optimization study. It is not an exact reproduction of the original system and is not compared as a complete system against untouched Vanilla vLLM in Phase 3.

## Proposed architecture

**Historical conceptual roadmap only.** The staged `Ours-Evict` / `Ours-Full` names below predate the current Phase 3 Option F design. They are not current arm names, and the old statement that a formal Native benefit campaign is still pending is superseded by the accepted Protocol v4 and the current 270-run authorization. The operative Phase 3 mapping is N0/A0/A1/A2/A3/E0 above; the campaign is authorized but not yet started. See [current research status](research-status.md).

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

The current formal campaign is component-level within the adapted Continuum-style system:

- A0−N0: incremental effect of the frozen forced Entry Release path under shared Native LRU/APC and Native scheduling;
- A1−A0 and A3−A0: registered Entry Release policy changes;
- A2−A0: physical block-victim selector change while retaining A0 Entry Release;
- A3 versus E0: registered suffix-cost versus deadline-only discriminability comparison.

The campaign does not estimate a full-system Continuum-versus-Vanilla effect, Dynamic-TTL-versus-Static-TTL effect, or program-level scheduler-performance effect. A full-system follow-up would require a separate protocol and M1 authorization.

## Simulator

The deterministic simulator remains useful for interface/unit tests only. Real serving-performance claims must come from the validated vLLM backend.
