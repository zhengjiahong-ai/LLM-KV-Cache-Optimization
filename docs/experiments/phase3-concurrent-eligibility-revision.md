# Phase 3 Concurrent Eligibility Interpretation

## Status and scope

This is the result-visible, M1-authorized limited interpretation revision for
the Phase 3 independent N/E/C evaluator. It addresses the 40/40 A0 load
calibration conflict in which the second session's first request had `C=112`
while the original lifecycle-completion-only history contract produced `E=0`.
It changes neither N, C, the primary metric, the load grid, nor any policy.
Original Native evidence and the original Fail-Closed evaluation remain
immutable.

## Independent eligibility rule

The original replay-timeline predecessor remains eligible through its unique
prior `VLLM_PREFIX_SNAPSHOT`. In addition, an earlier-enqueued request that has
not crossed the logical lifecycle completion boundary is eligible only when all
of the following are independently demonstrated:

1. its identity precedes the consumer in the frozen Native Enqueue Order;
2. producer and consumer timing landmarks use `engine_core_monotonic`;
3. the producer's first-token timestamp is no later than the consumer's Native
   scheduler-admission timestamp;
4. the producer has one coherent full-prompt Native Hash Snapshot;
5. process identity, hash function, and block size match the consumer; and
6. the two Native hash chains share one or more complete prefix blocks.

The consumer's `native_cached_prefix_tokens` value is not read by this
qualification. Changing C with every other evidence item fixed therefore
cannot change E. After E is independently calculated, the existing
`0 <= C <= E <= N` invariant is still enforced.

The producer Snapshot may be persisted after the consumer observation. In that
case it supplies content identity only; visibility is proven independently by
the same-clock first-token and scheduler-admission landmarks. A missing or
incompatible identity chain fails closed rather than being reconstructed from
C.

## vLLM source-order basis

The frozen runtime is vLLM 0.27.1. Its V1 scheduler publishes computed full
blocks through `KVCacheManager.cache_blocks` during the scheduler update after
a computed step. A subsequent waiting-request schedule performs prefix-cache
lookup against those published full blocks. The recorded first-token landmark
is therefore used only for full-prefill requests: it proves that prompt
computation crossed the full-prefill boundary before the later consumer was
scheduled. This revision does not infer partial-prefill block publication;
partial-prefill eligibility still requires explicit per-block commit evidence.

Source bindings:

- vLLM release `v0.27.1`, commit `6e448d0`;
- `vllm/v1/core/sched/scheduler.py`, scheduler output update and later lookup;
- `vllm/v1/core/kv_cache_manager.py`, `cache_blocks` and `get_computed_blocks`;
- `vllm/v1/core/single_type_kv_cache_manager.py`, full-block cache registration;
- `vllm/v1/metrics/stats.py`, engine-core monotonic queued, scheduled, and
  first-token timestamps.

## Audit output

Each request report contains `concurrent_eligibility_audits`. Every candidate
row binds producer and consumer identities, queued/scheduled/first-token
timestamps, clock domain, Snapshot event index, Hash LCP, eligible complete
tokens, qualification result, and an explicit
`uses_native_cached_tokens_c=false` marker. The 40 conflicting calibration
requests are extracted from those rows into a separate qualification table
before load targets or Headroom are reconsidered.
