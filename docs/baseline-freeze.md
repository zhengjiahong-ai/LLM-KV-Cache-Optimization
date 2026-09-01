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

### Baseline 2 — Continuum-style TTL / retention

**Status: TARGET SELECTED; IMPLEMENTATION SCOPE NOT YET FROZEN**

Continuum is retained as the current strong recent baseline because it represents a distinct retention-oriented approach to preserving reusable KV state across multi-turn/agent gaps.

The following are currently **candidate reproduction components**, not frozen requirements:

- TTL calculation;
- pin/unpin or equivalent retention eligibility;
- pressure-triggered release of protected entries;
- scheduling-priority interactions when required by the selected mechanism.

Before implementation starts, the project must answer the questions below.

### Freeze Question 1 — What is the minimum mechanism that still represents Continuum?

Identify the smallest subset of Continuum's decision logic that preserves the paper's defining retention behavior.

The adaptation must not reduce to:

```text
ordinary LRU + arbitrary fixed TTL
```

### Freeze Question 2 — What maps cleanly to vLLM 0.27.1 GPU APC?

For each candidate component, document:

- original Continuum object/granularity;
- available vLLM runtime object/granularity;
- required mapping or approximation;
- whether the approximation changes the meaning of the decision.

Particular attention is required for the mismatch between request/session-level retention and vLLM APC's block-level cached-prefix management.

### Freeze Question 3 — Does scheduling belong inside the baseline?

Continuum couples retention with scheduling behavior. The project must decide whether a faithful-enough baseline requires reproducing scheduling priority or whether a retention-only adaptation remains meaningful.

If scheduling is included, the comparison protocol must state explicitly that this baseline changes more than victim ordering.

If scheduling is excluded, the report must explain why the retained mechanism is still representative and must avoid describing the result as full-system Continuum reproduction.

### Freeze Question 4 — How is memory pressure handled?

The baseline must define what happens when retained/pinned entries would prevent required allocation.

The selected rule must:

- avoid deadlock or allocation failure caused solely by policy protection;
- be deterministic where practical;
- be documented as original behavior or project adaptation.

### Freeze Question 5 — What constitutes a fair comparison?

At minimum, the comparison should keep constant wherever applicable:

- model and model revision;
- vLLM version;
- hardware;
- request trace;
- cache/memory budget;
- batching parameters;
- measurement definitions.

Policy-specific behavior may differ only when it is intrinsic to the baseline and is documented.

---

## Common Runtime Requirement

Baseline 1, Baseline 2, and the proposed Cost-Aware policy should share the same underlying vLLM allocation and cache-bookkeeping path wherever practical.

Desired architecture:

```text
vLLM runtime state
      -> project policy adapter
      -> policy-specific decision
          |- native LRU
          |- Continuum-style retention baseline
          `- Cost-Aware
      -> common BlockPool allocation/eviction bookkeeping
```

The project must avoid implementing each policy through unrelated backend paths unless a baseline intrinsically requires a documented exception.

---

## Ownership

### Member 1

Owns the final project-level freeze of:

- baseline set;
- Continuum adaptation scope;
- common backend/policy boundary;
- fairness constraints across policies.

### Member 2

Provides:

- literature evidence;
- mechanism summaries;
- candidate baseline components;
- warnings about related/competing methods.

Member 2 does not unilaterally freeze implementation scope.

### Member 3

Implements the frozen baseline and reports concrete feasibility problems.

Member 3 should not silently change the frozen mechanism to make implementation easier. If a blocker is found, update this decision record before changing scope.

### Member 6

Checks that the frozen baseline can be evaluated under a meaningful and documented comparison protocol.

---

## Current Decision State

```text
vLLM native APC LRU
    -> FROZEN

Continuum-style strong baseline
    -> TARGET FROZEN
    -> EXACT ADAPTATION SCOPE NOT FROZEN

Cost-Aware policy
    -> RESEARCH DIRECTION FROZEN
    -> SCORING FUNCTION NOT FROZEN
```

The next update to this document should happen only after Continuum's paper mechanism has been mapped explicitly onto the validated vLLM 0.27.1 APC architecture.
