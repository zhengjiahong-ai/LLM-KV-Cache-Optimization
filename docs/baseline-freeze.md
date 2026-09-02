# Baseline Freeze Decision Record

## Purpose

This document records project-level decisions about baseline selection and adaptation scope.

The project studies **KV Cache Management Optimization** broadly enough to include:

- retention / protection;
- eviction / victim selection;
- scheduling coordination when it directly interacts with cache lifetime and recomputation.

Phase 1A validated a real block-level eviction-policy integration path, but that implementation boundary is a subsystem boundary, not the final research boundary.

---

## Baseline 1 — vLLM 0.27.1 native APC + native scheduler

**Status: FROZEN**

Backend:

```text
vLLM 0.27.1
```

Validated APC eviction path:

```text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
```

Phase 1A also validated that the project adapter can reproduce native block-level LRU ordering under real GPU inference while preserving native downstream eviction bookkeeping.

This baseline represents the unmodified production serving behavior against which broader system improvements are measured.

---

## Baseline 2 — Continuum-style retention + scheduling system

**Status: STRONG BASELINE TARGET; EXACT vLLM ADAPTATION SCOPE NOT YET FROZEN**

The previous decision to freeze a retention-only Continuum baseline is **withdrawn**.

Reason:

```text
Continuum's defining system behavior spans
retention / pin-unpin
+
scheduling coordination
```

Reducing it to a retention-only mechanism is still useful for component ablation, but it should not serve as the project's only representation of Continuum in the broader system comparison.

### What must be mapped before implementation

Member 1 must freeze the following after paper/runtime mapping:

1. **Retention state**
   - how dynamic TTL is represented;
   - how pin/unpin or equivalent protection maps to vLLM APC state;
   - what runtime events update retention metadata.

2. **Memory-pressure behavior**
   - what happens when retained/protected KV prevents required allocation;
   - which behavior comes from Continuum and which is a project adaptation.

3. **Scheduling behavior**
   - what scheduling priority/order rule is essential to represent Continuum's cache-aware scheduling contribution;
   - what minimal vLLM scheduler hook is required;
   - whether batching/admission semantics need to change.

4. **Granularity / identity mapping**
   - session/request/prefix identity;
   - mapping from that logical object to vLLM cached blocks;
   - handling of multi-turn idle gaps and resumed requests.

5. **Excluded original-system components**
   - any distributed, multi-GPU, workflow-framework, or unavailable mechanism that cannot be reproduced faithfully;
   - explicit wording for those omissions.

---

## Two Evaluation Levels

The project must separate component attribution from full-system comparison.

### Level A — Controlled component comparison

Hold the native scheduler fixed and compare cache-management components:

```text
vLLM native LRU
vs.
Continuum-style retention-only adaptation
vs.
Ours-Evict / Ours-Retention
```

Purpose:

> determine whether gains come from eviction/retention logic itself.

A retention-only Continuum adaptation is valid here, but must be labeled accordingly and must not be called full Continuum reproduction.

### Level B — Full-system comparison

Allow method-intrinsic cache/scheduler coordination:

```text
vLLM native system
vs.
Continuum-style/full adapted system
vs.
Ours-Full
```

Purpose:

> compare end-to-end serving-system performance when each approach uses its intended cache-management and scheduling coordination.

A full-system result cannot by itself attribute gains specifically to eviction or scheduling; that attribution must come from Level A and ablation experiments.

---

## Phase 1A Reuse

The existing real-vLLM adapter remains authoritative for block-level eviction execution:

```text
vLLM cached free blocks
    -> snapshot / candidate metadata
    -> EvictionPolicyAdapter
    -> selected blocks
    -> native BlockPool bookkeeping
```

This work is retained unchanged.

New retention/scheduler work should be layered above or beside this boundary rather than replacing it.

Important unresolved issue:

> General request/session-to-block mapping has not yet been established.

That mapping is now a required architecture task for retention and scheduling experiments.

---

## Proposed-System Scope

The proposed research direction is broadened from eviction-only to **cost-aware KV-cache management**.

Potential coordinated decisions are:

```text
Retention:
How long should reusable KV remain protected?

Eviction:
If memory must be reclaimed, which KV should be sacrificed?

Scheduling:
Which request/session should run or resume when cache state and recomputation cost matter?
```

The intended unifying principle is explicit runtime cost/value estimation rather than recency alone.

The exact proposed formulas and scheduler rules are **not frozen**.

---

## Required Ablations

The final system should, if technically feasible, expose at least these configurations:

```text
Ours-Evict
    -> cost-aware victim selection only

Ours-Retention
    -> cost-aware retention + eviction
    -> native scheduler

Ours-Full
    -> cost-aware retention + eviction + scheduling coordination
```

Equivalent naming is acceptable, but the experiment must allow Member 6 to separate:

- victim-selection contribution;
- retention contribution;
- scheduling contribution;
- policy overhead.

---

## Fairness Rules

### Controlled comparisons

Keep constant:

- vLLM version;
- model/revision;
- hardware;
- request trace;
- cache-memory budget;
- scheduler/batching configuration;
- generation parameters;
- metric definitions;
- random seeds where applicable.

### Full-system comparisons

Scheduling and retention behavior may differ when intrinsic to each method.

Keep constant wherever possible:

- backend/runtime version;
- model;
- hardware;
- workload;
- total GPU-memory/cache budget;
- generation settings;
- measurement methodology.

Every policy-specific scheduler or retention difference must be documented.

Full-system superiority must not be presented as proof that one eviction rule alone is superior.

---

## Implementation Ownership

### Member 1

Owns:

- overall runtime architecture;
- cache-policy adapter;
- scheduler/cache-management integration boundary;
- final Continuum adaptation freeze;
- fairness rules and integration.

### Member 2

Provides:

- evidence for Continuum retention and scheduling mechanisms;
- related-work comparison;
- identification of omitted or approximated mechanisms;
- novelty-risk checking.

### Member 3

Implements the baseline only after the revised full-system adaptation scope is frozen.

Member 3 should **not begin from the withdrawn retention-only freeze** as though it were final.

### Member 4

Implements the proposed cost-aware mechanism after interfaces are frozen.

### Member 5

Provides workloads capable of exposing both cache-pressure behavior and multi-turn/session scheduling effects.

### Member 6

Runs component and full-system experiments separately and performs ablation/attribution analysis.

---

## Current Decision State

```text
Overall research scope
    -> KV CACHE MANAGEMENT
    -> RETENTION + EVICTION + SCHEDULING COORDINATION

vLLM native APC + native scheduler
    -> FROZEN BASELINE

Phase 1A block-level eviction adapter
    -> COMPLETE
    -> RETAINED AS CACHE SUBSYSTEM INFRASTRUCTURE

Continuum
    -> STRONG SYSTEM BASELINE TARGET
    -> RETENTION-ONLY FREEZE WITHDRAWN
    -> FULL vLLM ADAPTATION SCOPE NOT YET FROZEN

Cost-Aware
    -> BROADER SYSTEM DIRECTION FROZEN
    -> EXACT RETENTION / EVICTION / SCHEDULING RULES NOT FROZEN
```

---

## Next Architecture Task

Before Member 3 starts Phase 1B implementation, Member 1 must perform a **Continuum-to-vLLM system mapping** covering:

```text
paper mechanism
    -> retention state
    -> request/session identity
    -> block association
    -> scheduler decision point
    -> memory-pressure path
    -> observable metrics
```

The output should freeze the smallest faithful-enough Continuum-style system that can run on vLLM 0.27.1 while preserving the distinction between controlled component experiments and full-system comparison.
