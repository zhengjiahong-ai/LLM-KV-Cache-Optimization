# vLLM 0.27.1 Backend Smoke Test

## Status

**Phase 0 — Backend & Architecture Validation: PASS**

This document records the real-backend validation completed before baseline reproduction begins.

The goal of this phase was not to reproduce the target research baseline or implement the proposed cost-aware policy. It was to verify that the selected serving backend exposes a real, observable GPU APC eviction path that can support later policy integration.

## Environment

- Backend: `vllm/vllm-openai:v0.27.1`
- Model: `Qwen/Qwen2.5-0.5B-Instruct`
- GPU: NVIDIA GeForce RTX 4060 Laptop GPU, 8 GiB VRAM
- Runtime: Docker Desktop with WSL2 backend
- vLLM workaround required under this WSL2 setup: `VLLM_USE_V2_MODEL_RUNNER=0`
- Hugging Face cache: named Docker volume `kvopt-hf-cache`

The workaround is environment-specific and does not change the GPU APC eviction policy.

## Basic GPU inference

**PASS**

The pinned vLLM image successfully initialized CUDA-enabled PyTorch and executed real GPU inference with the selected Qwen model after disabling the V2 model runner under WSL2.

No CPU fallback was used.

## Automatic Prefix Caching

**PASS**

A repeated-prefix workload was served through a temporary local vLLM OpenAI server with APC enabled.

The shared prefix length was approximately 336 tokens. The second request reused the prefix cache.

The vLLM `/metrics` endpoint provided direct evidence:

```text
vllm:prefix_cache_queries_total = 672
vllm:prefix_cache_hits_total = 320
vllm:prompt_tokens_by_source{source="local_cache_hit"} = 320
```

Therefore the APC result is based on backend metrics rather than latency inference.

## Cache pressure

**PASS**

Configuration used for the eviction smoke test:

```text
gpu_memory_utilization = 0.30
GPU KV cache           = 0.32 GiB
GPU KV cache size      = 28,368 tokens
block size             = 16 tokens
GPU KV blocks          ≈ 1,773
```

Workload:

```text
P1, P2, P3, P1, P4 ... P120
```

Each request used a distinct approximately 336-token prefix and `max_tokens=1`.

This produced cache pressure without intentionally triggering OOM.

## Observed GPU APC eviction path

**PASS**

The pinned vLLM 0.27.1 source and runtime trace agree on the following path:

```text
BlockPool.get_new_blocks()
→ FreeKVCacheBlockQueue.popleft_n()
→ BlockPool._maybe_evict_cached_block()
```

A free cached block can have `ref_cnt == 0`, remain in the free-block queue, and still retain prefix-cache metadata until the physical block is selected for reuse.

The victim-selection decision is therefore effectively encoded by the order of `FreeKVCacheBlockQueue` before `popleft_n()`.

## Runtime eviction evidence

**PASS**

Temporary container-only instrumentation captured cached blocks being selected and then evicted:

```text
[KVOPT] {"event":"SELECT","block_id":462,"ref_cnt":0,"has_block_hash":true,"requested_block_count":21,"free_queue_length":1751}
[KVOPT] {"event":"EVICT_CACHED","block_id":462,"ref_cnt":0,"has_block_hash":true}

[KVOPT] {"event":"SELECT","block_id":461,"ref_cnt":0,"has_block_hash":true,"requested_block_count":21,"free_queue_length":1751}
[KVOPT] {"event":"EVICT_CACHED","block_id":461,"ref_cnt":0,"has_block_hash":true}
```

This establishes the complete runtime chain:

```text
cached free block
→ selected by popleft_n()
→ _maybe_evict_cached_block()
→ cached metadata removal
```

In the pinned source, `_maybe_evict_cached_block()` invokes `_remove_cached_block_hashes(block)` and returns success only after the cached hash mapping is removed.

## LRU semantics

### Block-level LRU

**PASS**

`FreeKVCacheBlockQueue` maintains its head as the least-recently-used free block. Blocks released with a prefix hash are appended to the tail. When APC reuses a cached free block, `touch()` removes it from the free queue; after later release it re-enters according to its newer access position.

This establishes block-level LRU semantics for vanilla vLLM APC eviction.

### Request-level P1/P2/P3 mapping

**NOT ESTABLISHED**

The temporary runtime trace did not preserve a request-ID-to-block-ID mapping. Therefore this phase does not claim experimental proof that a specific request prefix such as P2 is evicted before P1 after `P1, P2, P3, P1`.

That mapping can be added later if needed for baseline diagnostics, but it is not required to validate the architecture integration point.

## Instrumentation properties

- Instrumentation type: temporary container-only Python patch
- Repository source modified: **NO**
- vLLM policy behavior changed: **NO**
- Queue order changed: **NO**
- `ref_cnt` changed: **NO**
- Block hash changed: **NO**
- Scheduler changed: **NO**
- CUDA kernel modified: **NO**

The instrumentation only emitted `SELECT` and `EVICT_CACHED` events.

## Validated integration point

The preferred project integration point is immediately around the current victim-selection step in `BlockPool.get_new_blocks()`:

```text
vLLM runtime state
        ↓
collect free cached candidates
        ↓
project eviction-policy adapter
        ↓
ordered victim block IDs
        ↓
existing BlockPool allocation / metadata-removal path
```

A minimal interface can initially remain block-oriented:

```python
class EvictionPolicyAdapter(Protocol):
    def rank_candidates(
        self,
        candidates: list[EvictionCandidate],
        context: EvictionContext,
    ) -> list[int]:
        ...
```

The adapter must not duplicate vLLM's physical block allocation or cached-metadata removal logic. All compared policies should use the same underlying `BlockPool` path.

## Phase boundary

This smoke test completes **Phase 0 — Backend & Architecture Validation**.

It does **not** constitute baseline reproduction.

The next phase is:

**Phase 1 — Baseline Reproduction**

The expected handoff is:

1. preserve vanilla vLLM LRU as the production baseline;
2. expose the common policy adapter through the validated block-selection path;
3. reproduce the agreed Continuum-style strong baseline through the same path;
4. only after baseline validation, integrate the proposed cost-aware policy.

## Conclusion

- Real GPU inference: **PASS**
- APC initialization: **PASS**
- APC cache hit: **PASS**
- Controlled cache pressure: **PASS**
- Cached-block eviction observation: **PASS**
- Block-level LRU semantics: **PASS**
- Kernel modification required: **NO**
- Backend integration point validated: **YES**

**Architecture/backend integration is ready for baseline-policy implementation.**
