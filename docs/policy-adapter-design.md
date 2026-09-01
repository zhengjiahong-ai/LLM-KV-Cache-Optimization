# vLLM Eviction Policy Adapter Design

## Status

**Phase 1A — Common Policy Adapter: interface scaffold implemented; real vLLM hook pending.**

This design applies to the pinned real backend, vLLM 0.27.1 with GPU Automatic Prefix Caching (APC). Phase 0 established the native cached-block victim path as:

```text
BlockPool.get_new_blocks()
  -> FreeKVCacheBlockQueue.popleft_n()
  -> BlockPool._maybe_evict_cached_block()
```

The goal of Phase 1A is to introduce one common victim-selection boundary so native LRU, the strong baseline, and the proposed method can share the same runtime path.

## Architectural boundary

```text
vLLM free cached blocks
        |
        v
VLLMEvictionBridge
  snapshot runtime state
        |
        v
EvictionPolicyAdapter
        |
        +-- NativeLRUAdapter
        +-- future Continuum-related policy component(s)
        +-- future Cost-Aware policy
        |
        v
validated ordered block IDs
        |
        v
existing vLLM allocation / eviction machinery
```

Policies make decisions only. They must not mutate vLLM block metadata, queue pointers, reference counts, or hash mappings directly.

## Runtime-neutral data

`EvictionCandidate` currently exposes only fields supported by the validated backend path:

- `block_id`
- `ref_cnt`
- `has_block_hash`
- `lru_rank`

`EvictionContext` currently exposes:

- `required_blocks`
- `free_blocks`
- `total_blocks`
- `timestamp`

The following are intentionally **not frozen** yet:

- request/session identity mapping;
- reuse probability;
- recomputation cost estimate;
- TTL / pin state;
- policy score;
- queueing/admission metadata.

These fields may be added only when their collection semantics and ownership are defined.

## Policy contract

`EvictionPolicyAdapter.select_victims(...)` returns unique candidate block IDs in eviction order. The policy cannot modify the vLLM runtime directly.

The bridge validates that returned IDs belong to the candidate snapshot, contain no duplicates, and provide enough blocks for the current decision when enough candidates exist.

## Native LRU equivalence target

`NativeLRUAdapter` sorts by `lru_rank`, where rank 0 is the current head of the native free queue. Therefore its expected victim sequence is identical to the order that native `popleft_n()` would select from the same snapshot.

The required integration validation sequence is:

1. **Unit equivalence** — adapter preserves an input free-queue order.
2. **Shadow mode** — in a real vLLM run, compute adapter victims from the same queue snapshot while native vLLM remains authoritative; compare both victim sequences.
3. **Controlled mode** — allow the adapter-selected victim order to drive the real allocation path without changing downstream eviction semantics.

Only after steps 2 and 3 pass should the adapter be treated as the common experimental runtime path.

## Continuum boundary

Continuum is not assumed to be a pure block-ranking policy. Its final vLLM adaptation may require retention eligibility (for example pin/unpin or equivalent protection state) before victim selection.

Do not expand `EvictionPolicyAdapter` into a combined scheduler/retention interface before the Continuum adaptation scope is frozen. If needed, retention eligibility should be modeled as a separate layer that filters candidates before the common victim-selection step.

## Simulator boundary

The existing `kvopt.kv_cache.policy.EvictionPolicy` is a request-level logical-simulator contract and returns request IDs. It remains separate from this real-backend block-level adapter.

Do not silently replace one with the other. The simulator is for interface validation only and is not evidence for real vLLM serving performance.

## Phase 1A completion criteria

- [x] `EvictionCandidate` / `EvictionContext` defined.
- [x] `EvictionPolicyAdapter` defined.
- [x] `VLLMEvictionBridge` defined.
- [x] `NativeLRUAdapter` implemented.
- [x] unit tests for order preservation and bridge validation added.
- [ ] real vLLM shadow-mode victim sequence matches native LRU.
- [ ] adapter-controlled LRU completes real GPU inference through the native downstream eviction machinery.
