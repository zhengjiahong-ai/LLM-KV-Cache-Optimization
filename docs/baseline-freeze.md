# Baseline Freeze Decision Record

## Purpose

This document is the project-level decision record for baseline selection and adaptation scope.

It separates three responsibilities:

- literature evidence and mechanism summaries;
- project-level baseline selection and runtime adaptation decisions;
- baseline implementation.

Related-work notes may recommend mechanisms, but they do not by themselves freeze the implementation scope.

---

## Baseline Set

### Baseline 1 — vLLM 0.27.1 native APC LRU

**Status: FROZEN**

Backend:

```text
vLLM 0.27.1
```

Subsystem:

```text
GPU Automatic Prefix Caching (APC)
```

Validated eviction path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

The baseline is the native block-level recency ordering represented by vLLM's free-block queue.

Important terminology:

- this is **vLLM APC block-level LRU**;
- it is not the same concrete implementation as SGLang's radix-cache Leaf-LRU;
- related work may compare both as recency-based policies, but implementation claims must keep them separate.

No additional baseline-specific victim-ranking logic should be added to this policy.

---

### Baseline 2 — Continuum-style dynamic TTL retention core

**Status: FROZEN FOR IMPLEMENTATION**

The project will reproduce the **retention core** of Continuum rather than the complete Continuum scheduling system.

The defining mechanism to preserve is:

```text
observed multi-turn / tool-call gap statistics
    -> dynamic TTL estimate using Continuum's cost-benefit logic
    -> retain (pin/protect) reusable KV state until TTL expires
    -> unpin/release when TTL expires or cache pressure requires reclamation
```

This baseline is therefore a **Continuum-style dynamic TTL retention baseline**, not ordinary LRU with an arbitrary fixed TTL.

### Included mechanisms

The following components are frozen as required:

1. **Dynamic TTL calculation**
   - TTL must be computed from online/historical reuse-gap information using the paper's retention cost-benefit principle.
   - A single manually chosen fixed TTL is not an acceptable substitute.

2. **Retention eligibility / pin-unpin state**
   - Cached state within its active TTL is treated as protected from ordinary LRU eviction.
   - TTL expiry makes the state eligible for normal eviction again.

3. **Pressure-triggered release**
   - Protected entries must not cause allocation failure or deadlock.
   - When required capacity cannot be satisfied from unprotected candidates, the implementation may release protected entries deterministically according to the frozen pressure rule below.

4. **Online state update**
   - Reuse-gap statistics used by TTL calculation must be updated from observed workload events available at runtime.

### Excluded mechanisms

The following Continuum system components are explicitly **out of scope for the primary baseline**:

- program-level FCFS scheduling;
- TTL-aware scheduling priority changes;
- changes to vLLM batching or admission order;
- Continuum's full agent/workflow scheduler;
- distributed/multi-GPU mechanisms not required for the retention decision.

Reason: the project studies KV-cache retention/eviction policy. Changing the scheduler at the same time would introduce a second source of performance differences and make RQ2 harder to interpret. All primary policies therefore keep the same vLLM scheduler and differ only in cache-policy behavior.

The report must describe this implementation as a **Continuum-style retention-core adaptation**, not a full-system reproduction of Continuum.

---

## Continuum-to-vLLM Mapping

### Original decision level

Continuum reasons about reusable KV state across multi-turn / tool-call gaps and assigns a dynamic time-to-live to decide how long that state should remain retained.

### vLLM target level

The validated backend manages reusable APC state at the cached-block level through the free-block queue and `BlockPool` bookkeeping.

The project adaptation therefore separates:

```text
retention metadata / eligibility
        -> candidate filtering
        -> common block-level victim selection
        -> native vLLM downstream eviction bookkeeping
```

The existing `EvictionPolicyAdapter` remains the common block-level victim-selection interface. Continuum-specific TTL state should be implemented as a separate retention layer or candidate-eligibility filter rather than expanding the adapter into a scheduler interface.

### Granularity rule

If a retained logical prefix spans multiple cached blocks, all blocks associated with the retained prefix/request state should share the same retention eligibility for that TTL interval wherever the mapping is available.

If reliable request/session-to-block mapping is unavailable for a workload, the implementation must not invent one silently. The affected experiment must either:

- use a controlled workload that provides the required association explicitly; or
- document a block-level approximation and report it as such.

The current Phase 1A validation established block-level LRU equivalence but did **not** establish general request-level P1/P2/P3-to-block mapping.

---

## Frozen Memory-Pressure Rule

Continuum-style protection is soft, not absolute.

Victim selection under pressure uses this order:

```text
1. expired / unprotected cached blocks
2. if still insufficient: protected blocks with the earliest TTL expiry
3. native LRU order as deterministic tie-breaker
```

This rule guarantees progress while preserving the intended retention behavior as long as capacity permits.

Any later change to this rule must update this decision record before formal evaluation.

---

## Fair-Comparison Constraints

For the primary LRU vs. Continuum-style vs. Cost-Aware comparison, keep constant:

- vLLM `0.27.1`;
- GPU APC backend;
- model and model revision;
- hardware;
- request trace / workload;
- cache-memory budget;
- batching and scheduler configuration;
- generation parameters;
- metric definitions;
- common downstream `BlockPool` allocation/eviction bookkeeping.

The primary Continuum-style baseline must **not** receive a scheduler-priority advantage unavailable to LRU and Cost-Aware.

Any optional experiment that later adds Continuum's scheduling component must be reported separately as a system-level extension, not mixed into the primary policy comparison.

---

## Minimum Reproduction Validation

Member 3 must complete all items below before the baseline is considered reproduced sufficiently for this course project:

1. **Mechanism test**
   - show that different observed reuse-gap histories can produce different TTL values;
   - show that unexpired entries are protected and expired entries become evictable.

2. **Pressure test**
   - create cache pressure;
   - show that unprotected entries are selected before protected ones;
   - when protected release is necessary, confirm earliest-expiry-first with native LRU tie-breaking.

3. **Real-backend test**
   - run on real vLLM `0.27.1` GPU inference;
   - reuse the common adapter / native downstream eviction path validated in Phase 1A;
   - confirm successful inference and real cached-block metadata removal.

4. **Trend-level reproduction**
   - use a multi-turn or controlled reuse-gap workload where retention matters;
   - verify at least the qualitative trend that dynamic retention can preserve reusable KV state across useful gaps compared with pure recency eviction under pressure.

The project does not require reproducing every numerical result from the original Continuum paper because the runtime, model, hardware, and workload differ.

---

## Implementation Ownership

### Member 1

Owns:

- this frozen adaptation scope;
- common vLLM policy boundary;
- fairness constraints;
- approval of any scope change caused by implementation blockers.

### Member 2

Provides:

- paper-mechanism evidence;
- clarification of Continuum's original TTL and scheduling behavior;
- wording support for related work and limitations.

### Member 3

Implements the frozen Continuum-style retention-core baseline on `feature/baseline`.

Member 3 must not silently add scheduling changes or replace dynamic TTL with a fixed heuristic. If the paper's exact TTL inputs cannot be reconstructed from available runtime information, the approximation and its rationale must be documented before formal experiments.

### Member 6

Checks that the comparison uses the frozen common scheduler/backend settings and that retention-specific metrics are collected consistently.

---

## Current Decision State

```text
vLLM native APC LRU
    -> FROZEN
    -> REAL ADAPTER EQUIVALENCE VALIDATED

Continuum-style dynamic TTL retention core
    -> FROZEN FOR IMPLEMENTATION
    -> DYNAMIC TTL + RETENTION ELIGIBILITY + PRESSURE RELEASE INCLUDED
    -> SCHEDULER PRIORITY EXCLUDED FROM PRIMARY BASELINE

Cost-Aware policy
    -> RESEARCH DIRECTION FROZEN
    -> SCORING FUNCTION NOT FROZEN
```

The next phase is **Phase 1B — Continuum-style Baseline Reproduction**, owned by Member 3 using the validated common vLLM policy path.
