# vLLM Eviction Policy Adapter Design

## Status

**Phase 1A — Common Policy Adapter: PASS.**

This design applies to the pinned real backend, vLLM 0.27.1 with GPU Automatic Prefix Caching (APC). Phase 0 established the native cached-block victim path as:

```text
BlockPool.get_new_blocks()
  -> FreeKVCacheBlockQueue.popleft_n()
  -> BlockPool._maybe_evict_cached_block()
```

Phase 1A introduced and validated one common victim-selection boundary so native LRU, the strong baseline, and the proposed method can share the same runtime path.

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

Policies make decisions only. They must not mutate vLLM block metadata, reference counts, or hash mappings directly. The integration hook may remove adapter-selected blocks from the native free queue in controlled mode, but downstream cached-block eviction and metadata cleanup remain owned by the original vLLM `BlockPool` path.

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

## Native LRU equivalence

`NativeLRUAdapter` sorts by `lru_rank`, where rank 0 is the current head of the native free queue. Therefore its expected victim sequence is identical to the order that native `popleft_n()` would select from the same snapshot.

The integration validation sequence has completed:

1. **Unit equivalence — PASS.** Adapter preserves an input free-queue order.
2. **Shadow mode — PASS.** In a real vLLM run, adapter victims were computed from the same queue snapshot while native vLLM remained authoritative.
3. **Controlled mode — PASS.** Adapter-selected victims drove the real free-queue selection while downstream eviction semantics remained native vLLM behavior.

### Real-backend validation record

Pinned validation environment:

- vLLM: `0.27.1`
- model: `Qwen/Qwen2.5-0.5B-Instruct`
- GPU APC enabled
- `gpu_memory_utilization=0.30`
- GPU KV cache capacity observed: `28,368 tokens`
- WSL2 workaround: `VLLM_USE_V2_MODEL_RUNNER=0`

Observed results:

- cache pressure: PASS;
- requests: 85;
- `POLICY_SHADOW` events: 85;
- shadow mismatches: 0;
- `POLICY_CONTROLLED` events: 85;
- real GPU inference under adapter control: PASS;
- real cached-block eviction observations: 2,741;
- cached metadata removal after `_maybe_evict_cached_block()`: confirmed;
- repository tests after integration: 11 passed.

The controlled path is therefore:

```text
free cached blocks
  -> adapter snapshot / NativeLRUAdapter selection
  -> selected blocks removed from native free queue
  -> BlockPool allocation path
  -> _maybe_evict_cached_block()
  -> native cached metadata removal
```

This establishes **block-level native LRU equivalence** for the validated workload. Request-level P1/P2/P3-to-block mapping remains **NOT ESTABLISHED** and must not be claimed.

## Integration mechanism

`src/kvopt/runtime/vllm/observer.py` provides an opt-in hook intended for the pinned disposable vLLM container environment.

Supported modes:

- `KVOPT_POLICY_MODE=shadow` — computes and logs adapter selection but delegates actual selection to native `popleft_n()`;
- `KVOPT_POLICY_MODE=controlled` — uses the adapter-selected block order while retaining native downstream eviction and metadata cleanup.

The validation did not modify the installed vLLM package or CUDA kernels. Container startup used a temporary `/tmp/sitecustomize.py` to install the repository hook.

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
- [x] real vLLM shadow-mode victim sequence matches native LRU.
- [x] adapter-controlled LRU completes real GPU inference through the native downstream eviction machinery.

**Phase 1A is closed. The next implementation phase is strong-baseline reproduction after the Continuum adaptation scope is frozen.**
