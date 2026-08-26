# Architecture

The repository separates stable interfaces from candidate policies and runtime backends.

## Phase status

**Phase 0 — Backend & Architecture Validation: COMPLETE**

The deterministic simulator remains the unit-test and interface-validation environment. The primary real inference backend is now pinned to **vLLM 0.27.1**, and the GPU Automatic Prefix Caching (APC) eviction path has been validated under real GPU inference and controlled cache pressure.

The next project phase is **Phase 1 — Baseline Reproduction**.

## Scheduler

The local simulator scheduler selects which request executes. Its deterministic FIFO implementation owns request status, but has no cache-capacity or eviction logic.

For the real backend, the project uses vLLM's existing scheduler and does not replace it as part of the current research scope.

## KVCacheManager

The local `KVCacheManager` manages the lifecycle of logical, fixed-size KV-cache blocks. It maps request IDs to block IDs and calls an `EvictionPolicy` only when capacity is insufficient. It does not allocate GPU tensors.

The real backend must not be confused with this simulator abstraction. In vLLM, GPU APC capacity and cached-block reuse are ultimately handled through the V1 cache manager and `BlockPool` path.

## EvictionPolicy

Simulator policies receive an immutable `CacheState` snapshot and return victim request IDs. This remains useful for deterministic policy tests.

For real vLLM integration, the validated lowest-level victim-selection point is block-oriented:

```text
BlockPool.get_new_blocks()
→ FreeKVCacheBlockQueue.popleft_n()
→ BlockPool._maybe_evict_cached_block()
```

The real policy adapter should therefore rank/select free cached blocks immediately around the current `popleft_n()` victim-selection step while leaving vLLM's physical allocation and cached-metadata removal logic common to all policies.

Preferred real-backend structure:

```text
vLLM runtime state
      ↓
EvictionPolicyAdapter
      ├─ vanilla vLLM LRU
      ├─ Continuum-style baseline
      └─ cost-aware policy
      ↓
ordered victim blocks
      ↓
existing BlockPool allocation / eviction path
```

The adapter interface should remain minimal until baseline reproduction establishes which additional request/prefix metadata is actually required.

## Workload

`Workload` produces requests in the local simulator. Dataset traces and synthetic generators can use the same interface.

For real-backend experiments, workload generation will issue requests to the pinned vLLM backend. The smoke test has already demonstrated repeated-prefix APC hits and a controlled cache-pressure workload; formal workload construction belongs to the later evaluation phase.

## Metrics

`MetricsCollector` records allocation, free, eviction, access, completion, and occupancy events in the simulator.

For vLLM, native metrics should be used wherever possible. Phase 0 directly validated APC reuse using `/metrics`, including local prefix-cache hit tokens. Additional policy-specific observability should be implemented in Python control-plane code rather than CUDA kernels.

## Simulator

The simulator wires workload, scheduler, cache manager, policy, and metrics together. It is used for architecture validation and deterministic functional testing only; it does not predict real LLM latency and must not be used for serving-performance claims.

Scheduler policy and cache eviction policy are independent concerns.

## Real backend validation

The pinned vLLM backend has passed the following checks:

- real CUDA GPU inference;
- Automatic Prefix Caching initialization;
- direct APC cache-hit verification through vLLM metrics;
- controlled GPU KV-cache pressure without intentional OOM;
- runtime observation of a cached free block selected by `popleft_n()` and passed to `_maybe_evict_cached_block()`;
- confirmation of block-level LRU semantics in `FreeKVCacheBlockQueue`;
- confirmation that no CUDA/kernel modification is required for the planned policy work.

Detailed evidence is recorded in `docs/vllm-smoke-test.md`.

## Scope boundary

Architecture/backend work should not expand into:

- custom attention kernels;
- model training or fine-tuning;
- multi-GPU/distributed KV-cache transfer;
- CPU KV offloading as the main research mechanism;
- replacing the vLLM scheduler;
- claiming that Phase 0 constitutes reproduction of the strong baseline.

Phase 0 establishes the experimental substrate. Baseline reproduction and the proposed optimization are separate later phases.
