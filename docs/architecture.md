# Architecture

The repository separates the stable interfaces from candidate policies and future runtime backends.

## Scheduler

The scheduler selects which request executes. Its deterministic FIFO implementation owns request status, but has no cache-capacity or eviction logic.

## KVCacheManager

`KVCacheManager` manages the lifecycle of logical, fixed-size KV-cache blocks. It maps request IDs to block IDs and calls an `EvictionPolicy` only when capacity is insufficient. It does not allocate GPU tensors.

## EvictionPolicy

Policies receive an immutable `CacheState` snapshot and return victim request IDs. This lets baseline and optimized policies evolve without accessing manager internals.

## Workload

`Workload` produces requests. Dataset traces and synthetic generators can use the same interface.

## Metrics

`MetricsCollector` records allocation, free, eviction, access, completion, and occupancy events. It is a small extension point for formal evaluation and profiling.

## Simulator

The simulator wires workload, scheduler, cache manager, policy, and metrics together. It is currently used for architecture validation and deterministic functional testing only; it does not predict real LLM latency.

Scheduler policy and cache eviction policy are independent concerns.
