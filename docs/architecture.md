# Architecture

The project studies KV-cache management on **vLLM 0.27.1 GPU APC**, with a clear hierarchy of concerns.

> **Current research/evaluation interpretation:** This architecture records the validated Phase 1A block adapter and the original proposed system hierarchy. The later Phase 2G evaluation explicitly separates **Entry forced-release** from **physical Block victim selection**; the original `Ours-Evict` schematic below is a research goal, **not** a claim that its independent benefit has been established. Read [canonical status](research-status.md), [experiment index](experiments/README.md), and [frozen Phase 1B baseline](baseline-freeze.md) for their different authority levels.

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

## Two decision layers in current Phase 2 evaluation

The Phase 1A `EvictionPolicyAdapter` remains the **validated physical block-victim boundary**. Phase 2G additionally evaluates a logically separate **entry forced-release** choice in the Continuum retention/pressure layer. Releasing a protected entry changes eligibility; it does **not** itself evict a KV block.

| Evaluated arm | Entry-release selection | Physical block-victim selection | Attribution boundary |
| --- | --- | --- | --- |
| A0 | Frozen Continuum-style project adaptation | Native LRU | Baseline |
| A1 | Cost-Aware Entry selector | Same Native LRU as A0 | Entry release / exposed candidate pool |
| A2 | Same frozen A0 entry release | Cost-Aware Block selector | Physical victim choice |

A2 does **not** combine A1 and A2. Do not compare their recomputation results as if they changed the same choice layer. A1 may change which blocks become eligible; A2 may change which eligible block is selected. The actual evidence chain is: **logical release → selected candidate/victim → Native hashed eviction → later APC prefix status → recomputed tokens**, and each arrow requires runtime evidence. A controlled comparison cannot attribute a token delta to a specific victim from co-occurrence alone.

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
