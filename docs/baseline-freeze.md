# Baseline Freeze Decision Record

## Purpose

This document freezes the project-level baseline scope and the minimum faithful-enough Continuum adaptation for vLLM 0.27.1.

It is based on the completed feasibility spike in `docs/continuum-vllm-mapping.md`.

---

## Baseline 1 — vLLM 0.27.1 native APC + native scheduling

**Status: FROZEN**

Backend:

```text
vLLM 0.27.1
```

Cache subsystem:

```text
GPU Automatic Prefix Caching (APC)
```

Validated eviction path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

Phase 1A also validated that the project block-level `EvictionPolicyAdapter` can reproduce native LRU victim order in real GPU inference while preserving native downstream bookkeeping.

---

## Baseline 2 — Continuum-style retention + program-level scheduling

**Status: PHASE 1B IMPLEMENTATION SCOPE FROZEN**

The project will implement a **Continuum-style system baseline adapted to vLLM 0.27.1**.

It must not be described as an exact source-level reproduction because vLLM lacks Continuum-native program/session identity, pin APIs, tool-gap state, and program-level scheduler primitives.

The baseline must preserve the defining combination:

```text
program/session lifecycle
    -> tool-gap / reuse history
    -> dynamic TTL estimation
    -> soft KV retention/protection
    -> expiry / pressure release
    -> program-level scheduling adaptation
```

A retention-only implementation is insufficient for the primary full-system Continuum baseline.

---

## Frozen Phase 1B Scope

### 1. Program / session identity

Continuum requires a stable identity across multiple requests/turns.

vLLM `Request.request_id` is not sufficient because ordinary completed requests are deleted and later turns arrive as new requests.

Therefore Phase 1B requires an **explicit project/orchestrator-provided `program_id` or `session_id`**.

Rules:

- do not infer session identity from APC hashes;
- do not treat `request_id` as a program ID;
- session/program identity must be supplied by the workload/orchestrator and propagated into the project observation layer;
- first-version experiments may use controlled multi-turn traces where this identity is explicit.

### 2. Tool-gap / reuse history

The baseline must maintain online history needed for Continuum-style TTL decisions.

Minimum state:

- `program_id/session_id`;
- tool/gap type where available;
- gap start and end timestamps;
- observed reuse/resume event;
- program/turn order;
- associated prefix identity.

vLLM does not natively provide tool events. These are an **external workload/orchestrator input**, not a reconstructed vLLM signal.

### 3. Dynamic TTL

The primary baseline must use a **dynamic TTL estimator** based on the Continuum mechanism and available runtime/history signals.

A single fixed TTL is not an acceptable substitute.

Because several Continuum estimator inputs are not natively available in vLLM, the implementation must classify every input as:

```text
NATIVE
OBSERVED
EXTERNAL
APPROXIMATED
UNAVAILABLE
```

Any approximation must be documented before formal evaluation. Missing inputs must not be silently replaced with arbitrary constants and still called faithful reproduction.

### 4. Retention representation

Retention must use a project-owned **independent runtime state table** rather than changing vLLM block reference-count semantics.

Frozen logical representation:

```text
program/session
    -> prefix identity
        -> retention deadline / protection state
        -> observed block IDs

block ID
    -> associated prefix identities
```

Retention is keyed by both logical session/program state and content-derived prefix identity.

Reasons:

- `Request` objects disappear after ordinary completion;
- APC hashes identify content, not logical workflow ownership;
- block IDs are ephemeral and can be reassigned.

### 5. Request/session ↔ block observation

Phase 1B must add an observation layer that records block ownership/association **while the request is still alive**, before completion destroys native logical ownership.

Relevant native information includes:

- `KVCacheManager.get_blocks(request_id)`;
- `get_block_ids(request_id)`;
- scheduler allocation/output block IDs;
- request block hashes / prefix identities.

The persistent mapping is explicitly **observation-derived**, not a native vLLM guarantee.

Correctness of vLLM inference must never depend on this metadata table.

On real block eviction, stale block associations must be removed from the reverse index.

### 6. Soft protection / pin-unpin adaptation

vLLM 0.27.1 has no native Continuum-style pin API.

The frozen adaptation is:

```text
native free queue remains unchanged
+
project retention table marks cached prefixes/blocks protected
+
protected entries are filtered from ordinary eviction candidates
```

Do not:

- artificially increment `ref_cnt` to simulate pinning;
- remove protected free blocks into a separate hidden pool;
- duplicate `BlockPool` allocation bookkeeping.

Protected blocks remain native free cached blocks and retain normal APC hash metadata.

### 7. TTL expiry

Expiry is **lazy and deterministic**.

Check deadlines:

- at/near each scheduler step;
- immediately before pressure-driven allocation/reclamation.

Use a monotonic clock and make tests injectable with a deterministic `now`.

No background timer thread is required in Phase 1B.

### 8. Memory-pressure release

Protection is soft, never absolute.

When unprotected free cached blocks cannot satisfy the required allocation:

1. expire all deadlines already reached;
2. use unprotected candidates first;
3. if still insufficient, release protected entries until allocation can proceed;
4. then delegate actual victim removal through the existing Phase 1A eviction path and native `BlockPool` cleanup.

**Release-order semantics must be deterministic but are an adaptation, not a claimed native Continuum rule.**

For Phase 1B validation, freeze the fallback release order as:

```text
earliest retention deadline first
    -> native LRU rank as tie-breaker
```

If later paper evidence supports a different exact pressure-selection rule that can be reproduced, update this document before formal experiments.

### 9. Scheduling adaptation

Program-level scheduling is included in the primary Continuum system baseline.

The first scheduler adapter must be deliberately narrow.

Frozen contract:

```text
read-only scheduler snapshot
    -> SchedulingCandidate[]
    -> SchedulingPolicyAdapter.order(...)
    -> ordered request IDs for the current scheduling step
    -> minimal vLLM hook performs native queue operations
```

The policy must not directly mutate:

- `Request` objects;
- waiting/running queues;
- request status;
- KV blocks;
- ref counts;
- scheduler bookkeeping sets.

Primary hook scope:

- waiting/admission order in `Scheduler.schedule()` / `_select_waiting_queue_for_scheduling()`.

Preemption-order modification is **not required in the first implementation** unless Member 3 demonstrates that Continuum's required program-level behavior cannot be represented without it. If added, it requires a scope update before formal experiments.

Native scheduling must remain available as a baseline/shadow mode.

### 10. Scheduler candidate state

The scheduling snapshot should expose only required immutable state, including where available:

- `request_id`;
- external `program_id/session_id`;
- request status;
- arrival time / waiting age;
- native priority;
- program/turn order;
- cached token/block estimate;
- retention deadline / protection state;
- recomputation estimate when required by the reproduced mechanism.

Do not prematurely add Cost-Aware-only features to the Continuum baseline interface.

---

## Explicit First-Version Exclusions

Phase 1B does not require:

- CUDA/kernel changes;
- model-code changes;
- multi-GPU or distributed KV transfer;
- CPU KV offloading;
- connector-backed KV cache semantics;
- asynchronous/deferred-free configurations that invalidate the simple completion→free observation assumption;
- a general production agent orchestrator;
- arbitrary real-world tool execution.

First validation should use controlled multi-turn/session traces with explicit program IDs and tool-gap events.

---

## Common Architecture

```text
orchestrator / workload lifecycle events
            |
            v
Request / Session Observation Layer
            |
            v
Retention State Manager
(history, dynamic TTL, protection, prefix<->block map)
        |                         |
        | eligibility             | scheduler snapshot
        v                         v
existing EvictionPolicyAdapter   SchedulingPolicyAdapter
        |                         |
        +------------+------------+
                     v
              native vLLM Scheduler
                     |
              KVCacheManager
                     |
                 BlockPool
```

The Phase 1A eviction adapter and native downstream BlockPool bookkeeping remain authoritative and must not be rewritten for Continuum.

---

## Validation Required Before Phase 1B Is Closed

Member 3 must show all of the following.

### Identity / lifecycle

- two or more requests can be linked to one explicit program/session;
- tool-gap start/end events update the correct program history;
- new request IDs do not destroy logical program continuity.

### TTL

- different observed histories produce different TTL values;
- estimator inputs are logged with their source classification;
- approximations are explicit.

### Retention

- unexpired protected prefixes remain reusable under moderate pressure;
- expiry makes them ordinarily reclaimable;
- stale block mappings are cleaned after real eviction.

### Pressure

- protection cannot deadlock allocation;
- unprotected candidates are used first;
- protected fallback release follows the frozen deterministic adaptation rule.

### Scheduling

- shadow mode can reproduce native admission ordering when native policy is selected;
- controlled mode can alter admission order through ordered request IDs while native downstream scheduler bookkeeping remains correct;
- program-level ordering can be demonstrated on a controlled multi-turn trace.

### Real backend

- run on real vLLM 0.27.1 GPU inference;
- APC reuse remains functional;
- real eviction still flows through native BlockPool cleanup;
- existing Phase 1A tests continue to pass.

---

## Comparison Semantics

Two types of experiment must remain separate.

### Component attribution

Use the same native scheduler when comparing cache mechanisms such as:

```text
native LRU
vs.
retention/eviction components
vs.
Ours-Evict / Ours-Retention
```

### Full-system comparison

Allow intrinsic scheduling/cache coordination:

```text
vLLM native
vs.
Continuum-style adapted system
vs.
Ours-Full
```

A full-system result must not be used alone to claim that one eviction rule is superior; ablation/component experiments must support attribution.

---

## Ownership

### Member 1

Owns:

- this Phase 1B scope;
- runtime interface boundaries;
- approval of any new approximation or scheduler/preemption expansion;
- fairness rules.

### Member 2

Supports:

- paper-mechanism verification;
- exact Continuum terminology;
- identifying whether an implementation detail is original or adaptation.

### Member 3

Implements Phase 1B according to this freeze.

Member 3 must not silently:

- replace dynamic TTL with fixed TTL;
- remove program/session identity;
- omit scheduling and still call the result the primary full-system baseline;
- mutate native BlockPool/ref-count/hash semantics to simplify pinning;
- add preemption/scheduler behavior outside the frozen scope.

### Member 6

Checks component/full-system experiment separation and collects retention/scheduling metrics needed for attribution.

---

## Current Decision State

```text
vLLM native APC + native scheduler
    -> FROZEN

Phase 1A block-level eviction adapter
    -> CLOSED / VALIDATED

Continuum-style vLLM system baseline
    -> PHASE 1B SCOPE FROZEN
    -> explicit program/session identity
    -> dynamic TTL with documented approximations
    -> soft retention protection
    -> lazy expiry + deterministic pressure release
    -> narrow program-level admission-order scheduler adapter
    -> native BlockPool bookkeeping preserved

Cost-Aware system
    -> BROAD RESEARCH DIRECTION FROZEN
    -> exact retention / eviction / scheduler algorithms NOT YET FROZEN
```

The next implementation phase is **Phase 1B — Continuum Baseline Implementation and Validation**.