# Backend Selection

## Decision

The project will use **vLLM** as the primary real LLM inference backend.

The existing deterministic simulator remains useful for interface validation and unit tests, but it must not be used for performance claims.

## Why vLLM

The project needs a backend that is both realistic and modifiable at the KV-cache management layer. vLLM fits this requirement well because its current architecture exposes explicit KV-cache management components between the scheduler and cache allocation logic, including `KVCacheManager`, coordinator layers, and per-cache-group managers.

Current vLLM prefix caching also still uses LRU-style eviction, making it a natural production baseline for this project.

In addition, current vLLM KV offloading infrastructure supports custom cache policies through a `CachePolicy` interface and allows out-of-tree policy implementations. This is important because it creates a path for experimenting with eviction logic without immediately forking large portions of vLLM or changing CUDA kernels.

## Why not use the local simulator as the final backend

The repository simulator models logical cache blocks only. It does not model real GPU execution, attention kernels, prefill cost, decode cost, batching overhead, or GPU memory behavior accurately enough for serving-performance conclusions.

It will therefore be used only for:

- interface validation;
- deterministic unit tests;
- early policy correctness tests;
- small synthetic logic tests.

## Why not choose mini-vLLM as the main experimental backend

Educational mini-vLLM implementations are useful for understanding PagedAttention and block allocation, but typical teaching implementations omit production features such as prefix caching, preemption, or mature serving/benchmark infrastructure.

They may still be used as a reference when understanding internals, but not as the primary backend for the final evaluation.

## Why not choose SGLang as the primary backend

SGLang is also a strong and current serving framework with sophisticated RadixCache and session-aware cache management. However, its cache architecture is more tightly coupled to radix-tree/session semantics.

For this project, vLLM is preferred because:

- the existing project architecture already mirrors scheduler -> KV cache manager -> policy separation;
- LRU provides a clean production baseline;
- vLLM exposes explicit KV-cache management components;
- custom policy insertion is easier to isolate from unrelated serving features;
- the project is focused on victim selection / eviction cost rather than designing a new prefix-tree structure.

SGLang can still be discussed as related work or used as an optional comparison if time permits.

## Initial integration strategy

The integration should be incremental.

### Stage A — Keep the current simulator

Continue using the local simulator to validate:

- `EvictionPolicy` semantics;
- victim-set correctness;
- deterministic tie-breaking;
- score computation;
- unit tests.

### Stage B — Reproduce vLLM LRU behavior

Study the selected vLLM version and identify the exact cache structure and eviction path used by prefix caching / the relevant KV-cache subsystem.

The team should first reproduce or expose the existing LRU behavior before implementing the proposed method.

### Stage C — Add an adapter layer

Avoid coupling project policy code directly to arbitrary vLLM private state.

Introduce an adapter that converts the relevant vLLM cache/runtime information into project-level policy inputs such as:

- cached token count;
- occupied block count;
- last access / recency information;
- request waiting information where available;
- cache pressure;
- estimated recomputation cost.

The adapter should then map selected victims back to the corresponding vLLM cache entries/blocks.

### Stage D — Strong baseline

Implement the selected Continuum-style retention baseline in the same evaluation path.

Any simplification relative to the original work must be documented explicitly.

### Stage E — Proposed cost-aware policy

Implement the proposed online cost-aware victim selection using the same runtime path and benchmark harness.

## Version policy

Do **not** track vLLM `main` continuously during formal experiments.

Before implementation begins, freeze one tested vLLM release or commit and record:

- vLLM version / commit SHA;
- Python version;
- PyTorch version;
- CUDA version;
- GPU model;
- model revision used for experiments.

Once the formal evaluation phase starts, runtime upgrades should require an explicit decision because they can change cache behavior and invalidate earlier results.

## Scope boundary

The backend integration should not require:

- custom CUDA kernels;
- modifications to attention kernels;
- tensor-parallel or multi-GPU support;
- distributed KV-cache transfer;
- model training or fine-tuning.

If the desired eviction policy cannot be integrated without invasive kernel/runtime changes, the project scope should be reduced rather than expanding into a full vLLM fork.

## Owner

Primary owner: **Member 1**

Collaborators:

- Member 3 for LRU / baseline integration;
- Member 4 for optimized policy integration;
- Member 5 for benchmark inputs;
- Member 6 for metrics and profiling.

## Next technical checkpoint

Before writing the real backend adapter, Member 1 should produce a short implementation note that answers:

1. Which exact vLLM release/commit will be pinned?
2. Which vLLM cache subsystem is the experimental target: GPU prefix-cache eviction, CPU offload cache policy, or another explicitly identified path?
3. What object represents an eviction candidate?
4. Where is LRU ordering maintained?
5. What information is available at eviction time?
6. Can the proposed policy be inserted out-of-tree, or is a small vLLM patch required?
7. Which metrics can be collected without changing kernel code?

No optimization implementation should begin until these questions are answered.