# Architecture

The project now studies **KV-cache management as a coordinated serving-system problem**, not eviction in isolation.

The research boundary includes:

```text
retention / protection
+
eviction / victim selection
+
scheduling coordination
```

The real inference backend is frozen to **vLLM 0.27.1** with GPU Automatic Prefix Caching (APC).

## System Layers

```text
Workload / Orchestrator
    - request arrivals
    - explicit program/session identity
    - controlled tool-gap events
            |
            v
Request / Session Observation Layer
    - request -> program/session association
    - prefix/block observation
    - completion, reuse, preemption, tool-gap events
            |
            v
Retention State Manager
    - online history
    - dynamic TTL / retention deadline
    - soft protection state
    - program/session <-> prefix <-> block associations
       |                                |
       | scheduler state                | eviction eligibility
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

## vLLM Backend Boundary

Phase 0 validated the native GPU APC path:

```text
KVCacheManager.allocate_slots()
    -> BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

Native vLLM remains authoritative for:

- request status transitions;
- queue mutation and scheduler bookkeeping;
- KV block reference counts;
- free-queue ownership;
- APC hash metadata;
- actual block allocation and metadata cleanup.

Project policies should make decisions through narrow adapters and should not duplicate or bypass these semantics.

## Phase 1A — Eviction Policy Adapter

**Status: CLOSED / VALIDATED**

The existing real-backend adapter lives under:

```text
src/kvopt/runtime/vllm/
```

The validated decision path is:

```text
native free cached blocks
    -> VLLMEvictionBridge snapshot
    -> EvictionCandidate[]
    -> EvictionPolicyAdapter.select_victims()
    -> selected block IDs
    -> native BlockPool eviction bookkeeping
```

The adapter operates at block level. It must remain reusable for:

- native LRU equivalence;
- Continuum retention eligibility + fallback eviction;
- the later Cost-Aware victim-selection component.

The older simulator `EvictionPolicy` interface is a separate logical testing contract and must not be confused with the real vLLM adapter.

## Request / Session Observation Layer

vLLM has `request_id` but no native `program_id/session_id` suitable for multi-turn Continuum-style workflows.

Therefore the project introduces explicit program/session identity from the workload/orchestrator.

The observation layer records runtime associations while native information is still available:

```text
request_id
program_id/session_id
prefix identity
current block IDs
request admission/completion
reuse/resume
preemption
tool-gap start/end
```

The persistent request/session-to-block association is **observation-derived**. APC hashes cannot be used to recover logical ownership after request completion.

This metadata must never become part of vLLM inference correctness.

## Retention State Manager

Retention state is maintained outside native vLLM objects.

Conceptually:

```text
program/session
    -> prefix identity
        -> TTL / retention deadline
        -> protected state
        -> observed block IDs

block ID
    -> associated prefix identities
```

This design is required because:

- ordinary completed `Request` objects disappear;
- APC hashes represent content, not workflow identity;
- block IDs are ephemeral and can be reassigned.

### Soft protection

Protected free cached blocks remain in the native free queue with normal vLLM reference-count and hash semantics.

Protection is implemented as an eligibility rule before victim selection:

```text
native free cached blocks
    -> retention eligibility filter
    -> EvictionPolicyAdapter
```

Do not simulate pinning by changing `ref_cnt` or moving blocks into a second hidden pool.

### Expiry and pressure

TTL expiry is lazy and deterministic.

When memory pressure requires reclamation:

```text
expire overdue entries
    -> use unprotected blocks first
    -> if still insufficient, release protected entries
    -> existing eviction adapter
    -> native BlockPool cleanup
```

The first frozen pressure fallback is:

```text
earliest retention deadline
    -> native LRU rank tie-break
```

This fallback is a project adaptation for bounded-memory progress, not a claimed native Continuum rule.

## SchedulingPolicyAdapter

The broader project includes scheduling/cache coordination.

The first scheduler boundary is intentionally narrow:

```text
read-only scheduler snapshot
    -> SchedulingCandidate[]
    -> SchedulingPolicyAdapter.order(...)
    -> ordered request IDs for the current scheduling step
    -> minimal vLLM hook performs native queue operations
```

The policy may influence waiting/admission order but must not directly mutate:

- `Request` objects;
- waiting/running queue internals;
- request status;
- KV blocks/ref counts;
- scheduler bookkeeping sets.

The first Continuum implementation does **not** require changing running-request preemption order. Any such expansion requires a new project-level freeze.

Native scheduling must remain selectable for component-level experiments and shadow validation.

## Baseline Architecture

### Baseline 1 — vLLM native

```text
native scheduler
+
native APC block-level LRU
```

### Baseline 2 — Continuum-style adapted system

```text
explicit program/session identity
    -> tool-gap / reuse history
    -> dynamic TTL
    -> soft retention protection
    -> program-level admission-order scheduling adaptation
    -> native vLLM APC / BlockPool backend
```

Because vLLM lacks several Continuum-native primitives, this is an explicit system adaptation rather than an exact source-level reproduction.

## Proposed Cost-Aware System

The future proposed method will reuse the same architectural layers and investigate explicit runtime cost when making retention, eviction, and scheduling decisions.

The exact score/function is not frozen.

The key architectural fairness rule is:

> Baselines and the proposed method should share the same native vLLM backend, observation infrastructure, and downstream cache bookkeeping wherever practical; only policy-specific decisions should differ.

## Simulator

The deterministic simulator remains useful for:

- interface tests;
- deterministic policy tests;
- small synthetic edge cases.

It does not execute real GPU KV cache and must not support real serving-performance claims.

## Experiment Boundaries

Two experiment levels must remain distinct.

### Component attribution

Hold native scheduling fixed and isolate cache-management effects.

### Full-system comparison

Allow intrinsic retention/scheduling coordination and compare end-to-end system behavior.

A full-system gain must not automatically be attributed to eviction alone.
