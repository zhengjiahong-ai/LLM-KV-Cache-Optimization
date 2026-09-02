# Architecture

The project studies KV-cache management on **vLLM 0.27.1 GPU APC**, with a clear hierarchy of concerns.

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

## Primary decision boundary — EvictionPolicyAdapter

Phase 1A validated the real backend victim-selection path:

```text
native free cached blocks
    -> VLLMEvictionBridge snapshot
    -> EvictionCandidate[]
    -> EvictionPolicyAdapter.select_victims()
    -> selected block IDs
    -> native BlockPool eviction bookkeeping
```

This is the **main experimental decision boundary** for the proposed algorithm.

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
