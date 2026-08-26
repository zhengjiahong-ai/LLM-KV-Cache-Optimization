# Backend Selection

## Decision

The project will use **vLLM 0.27.1** as the primary real LLM inference backend.

The experimental target is specifically **GPU Automatic Prefix Caching (APC) eviction**, not CPU KV offloading.

The existing deterministic simulator remains useful for interface validation and unit tests, but it must not be used for performance claims.

## Why vLLM

The project needs a backend that is both realistic and modifiable at the KV-cache management layer. vLLM fits this requirement because its V1 architecture exposes explicit KV-cache management components between the scheduler and the cache block pool.

For GPU prefix caching, vLLM maintains cached KV blocks in a block pool and places free cached blocks in an eviction-ordered free-block queue. Allocation consumes blocks from the head of that queue; if a selected block still carries a cached prefix hash, it is evicted before reuse. The current policy is therefore effectively LRU for free cached blocks.

This path directly matches the project question: when GPU KV-cache capacity is under pressure, which reusable cached blocks should be sacrificed?

## Important correction: CPU offload is not the research target

vLLM also has a separate CPU KV offloading subsystem with pluggable cache policies such as LRU/ARC and out-of-tree `CachePolicy` support. That subsystem is useful engineering reference material, but it is **not** the primary experimental target for this project.

Using the CPU-offload policy path as the main implementation would shift the research question toward hierarchical GPU/CPU cache management and KV transfer, which is outside the intended scope.

Therefore:

- GPU APC eviction is the primary research path;
- CPU offload policy code may be consulted for interface ideas;
- formal experiments must not silently substitute CPU-offload eviction for GPU prefix-cache eviction.

## Pinned version

Initial implementation target:

```text
vLLM 0.27.1
```

This is the latest stable PyPI release observed when the backend was frozen for the project (released 2026-08-11).

Formal experiments should use this pinned version unless the team explicitly decides to change it before the experiment freeze.

Before formal runs, record the exact source commit corresponding to the installed release together with:

- Python version;
- PyTorch version;
- CUDA version;
- GPU model;
- model revision.

Do not continuously track vLLM `main` during implementation or evaluation.

## Exact experimental subsystem

Primary target files/components in vLLM V1:

```text
Scheduler
    |
    v
vllm/v1/core/kv_cache_manager.py
    |
    v
KV cache coordinator / per-type managers
    |
    v
vllm/v1/core/block_pool.py
    |
    v
FreeKVCacheBlockQueue
```

### Eviction candidate

The lowest-level eviction candidate is a free `KVCacheBlock` that:

- has `ref_cnt == 0`;
- is present in the free-block queue;
- still has prefix-cache metadata / block hash and is therefore reusable;
- can be physically reassigned when new KV capacity is required.

A request/prefix-level cost model may need to aggregate metadata over multiple such blocks rather than treating every block independently. That mapping is part of the project adapter design.

### Where LRU ordering is maintained

The relevant ordering is maintained by the block pool's `FreeKVCacheBlockQueue`.

The current design places free blocks into an eviction-ordered doubly linked list. Cached free blocks near the queue head are the first blocks consumed and therefore the first cached blocks evicted when capacity is needed.

The existing vLLM prefix-caching documentation explicitly describes eviction as popping the least-recently-used cached block from the queue head.

### Eviction point

The critical allocation path is in `BlockPool.get_new_blocks(...)`.

Conceptually:

```text
request needs new blocks
        |
        v
BlockPool.get_new_blocks(n)
        |
        v
free_block_queue.popleft_n(n)
        |
        v
selected cached block?
        |
       yes
        v
_maybe_evict_cached_block(block)
        |
        v
remove prefix-cache mapping/hash
        |
        v
reuse physical block
```

This means the current victim-selection decision is largely encoded by **queue ordering before `popleft_n()`**, not by a standalone policy object.

## Integration consequence

Unlike the CPU offload subsystem, GPU APC eviction does not currently expose a general out-of-tree eviction-policy interface suitable for this project.

Therefore the likely implementation strategy is a **small, controlled vLLM patch or adapter layer**, not a completely out-of-tree policy plugin.

The project should minimize the patch surface and avoid changing attention kernels or block contents.

Preferred design:

```text
vLLM runtime state
      |
      v
Project eviction-policy adapter
      |
      v
PolicySnapshot / candidate metadata
      |
      +--> LRU baseline
      +--> Continuum-style baseline
      +--> Cost-aware policy
      |
      v
ordered victim block set
      |
      v
vLLM BlockPool eviction/allocation path
```

The same adapter and allocation path must be used for all experimental policies.

## Signals available / signals that may require instrumentation

### Available or derivable near the cache manager

Likely available or derivable without kernel changes:

- block ID;
- block hash / cached status;
- block reference count;
- number of free blocks;
- request-to-block mappings;
- cached token/block counts;
- request prompt length and generation progress at scheduler level;
- waiting/running request state at scheduler level;
- cache hit / computed-block information.

### Requires project-side metadata or instrumentation

The proposed policy may need to maintain or derive:

- last-access timestamp / logical recency;
- prefix reuse history;
- mapping from cached blocks back to owning/relevant request or prefix metadata;
- estimated recomputation cost;
- waiting-queue impact;
- policy-decision latency.

These should be implemented in Python control-plane code where possible. Do not modify CUDA kernels solely to collect them.

## Relation to current vLLM development

The relevance of this target is reinforced by current vLLM development: a 2026 RFC proposes waiting-queue-informed LRU for prefix-cache eviction because ordinary APC LRU can evict a cached prefix that a near-future waiting request is about to reuse, forcing recomputation.

This validates that GPU prefix-cache victim selection is still an active problem rather than a solved historical detail.

The project should treat that RFC as related work / motivation, not as the proposed method itself.

## Initial integration strategy

### Stage A — Keep the current simulator

Use the local simulator for:

- `EvictionPolicy` semantics;
- victim-set correctness;
- deterministic tie-breaking;
- cost-score tests;
- unit tests.

### Stage B — Establish vanilla vLLM 0.27.1 baseline

Before modifying policy behavior:

1. install/build the pinned release;
2. run a small supported model with APC enabled;
3. construct a repeated-prefix workload;
4. confirm observable prefix-cache hits;
5. create cache pressure sufficient to trigger cached-block eviction;
6. record the unmodified LRU behavior.

### Stage C — Instrument the GPU APC path

Add the smallest necessary instrumentation to expose:

- candidate blocks;
- eviction order;
- cache hit/miss statistics;
- evicted blocks/tokens;
- recomputation proxy or directly measured recomputed tokens where practical;
- policy execution overhead.

Instrumentation must not change the baseline decision logic.

### Stage D — Add the common policy adapter

Refactor only enough of the queue/victim-selection path so that multiple policies can select the victims while the underlying block allocation and cache bookkeeping stay common.

### Stage E — Reproduce baselines

Implement:

- vanilla vLLM LRU;
- the agreed Continuum-style strong baseline / adaptation.

Any difference from the original Continuum setting must be documented explicitly.

### Stage F — Proposed method

Integrate the dynamic cost-aware victim-selection policy through the same adapter and evaluation path.

## Why not use the local simulator as the final backend

The repository simulator models logical cache blocks only. It does not model real GPU execution, attention kernels, prefill cost, decode cost, batching overhead, or GPU-memory behavior accurately enough for serving-performance conclusions.

It is only for architecture validation and deterministic functional testing.

## Why not choose mini-vLLM as the main experimental backend

Educational mini-vLLM implementations are useful for understanding PagedAttention and block allocation, but commonly omit mature prefix caching, preemption, scheduling, metrics, and serving benchmark infrastructure.

They may be used for learning or debugging concepts, not as the primary final backend.

## Why not choose SGLang as the primary backend

SGLang is a strong current serving system with sophisticated prefix caching, but its cache management is tightly connected to radix-tree/session semantics. That would introduce a second major design dimension beyond the project's intended victim-selection problem.

vLLM offers a cleaner fit for isolating GPU APC eviction while keeping the rest of serving unchanged.

## Scope boundary

Backend integration should not require:

- custom CUDA kernels;
- attention-kernel modification;
- multi-GPU/tensor parallelism;
- distributed KV-cache transfer;
- CPU KV offloading as the main mechanism;
- model training or fine-tuning.

If a proposed design requires invasive changes outside scheduler/cache-manager/block-pool control-plane code, reduce the policy scope rather than expanding into a full runtime rewrite.

## Owner

Primary owner: **Member 1**

Collaborators:

- Member 3 — vanilla LRU and strong-baseline integration;
- Member 4 — optimized policy integration;
- Member 5 — repeated-prefix/cache-pressure workload construction;
- Member 6 — metrics, profiling, and formal evaluation.

## Next checkpoint

Member 1 should now produce and validate a minimal vLLM-0.27.1 smoke experiment that answers:

1. Can APC hits be reproduced on the available hardware?
2. Can GPU cache pressure be forced reliably without OOM?
3. Can actual eviction events/order be observed with lightweight instrumentation?
4. Can the queue/victim-selection point be patched without touching kernels?
5. Which small model gives enough KV pressure while keeping experiments fast?

Only after this smoke experiment should Members 3 and 4 begin modifying the real vLLM eviction policy.