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
not crossed the logical lifecycle completion boundary is eligible through a
Same-batch Shared Predecessor or Earlier-forward Shared Predecessor path only
when all of the following are independently demonstrated:

1. its identity precedes the consumer in the frozen Native Enqueue Order;
2. producer and consumer timing landmarks use `engine_core_monotonic`;
3. the producer is scheduled in the same or an earlier Scheduler iteration;
4. the producer has a first-token observation proving that it entered a model
   forward, without using that timestamp as a cache-publication boundary;
5. producer and consumer each have one coherent Native Hash Snapshot;
6. process identity, hash function, block size, and Hash LCP agree; and
7. the Snapshot prefix Block IDs are complete and physically identical.

The consumer's `native_cached_prefix_tokens` value is not read by this
qualification. Changing C with every other evidence item fixed therefore
cannot change E. After E is independently calculated, the existing
`0 <= C <= E <= N` invariant is still enforced.

The Snapshots may be persisted after the consumer observation. They supply
content and physical identity, not publication time. A missing, partial, or
incompatible identity chain or physical Block mapping fails closed rather than
being reconstructed from C.

Physical Producer and Consumer Snapshot evidence is required only when a
concurrent candidate could increase the independently established E. The two
Native Observation Hash Chains are sufficient to prove that a dominated
candidate cannot change E; they are not sufficient to qualify it. If a valid
frozen historical predecessor already supplies an equal or longer Hash LCP,
the concurrent candidate is recorded as
`NOT_QUALIFIED_DOMINATED_BY_EXISTING_HISTORY` and cannot change E. This keeps
the protocol compatible with terminal right-censoring, where a final request
may intentionally lack a post-request Snapshot as either Producer or Consumer,
without treating missing evidence as positive evidence or consulting C.

## vLLM source-order basis

The frozen runtime is vLLM 0.27.1. `Scheduler.schedule()` calculates one
`scheduled_timestamp` per iteration. During its ordered request loop,
`allocate_slots()` registers full-block metadata before a later request calls
`get_computed_blocks()`. This proves metadata visibility but not, by itself, KV
content readiness.

Content readiness is established separately. The attention layer invokes
`unified_kv_cache_update`, whose FlashAttention implementation performs
`reshape_and_cache_flash` using the physical Slot Mapping. It passes the
returned dummy dependency to `unified_attention_with_output`; the source
explicitly states that this preserves KV-update-before-attention ordering under
`torch.compile`. Attention then reads `key_cache` and `value_cache` through the
consumer Block Table. This establishes the write-before-read dependency for a
same-batch shared physical block.

For adjacent Scheduler iterations, the frozen execution binds
`VLLM_ENABLE_V1_MULTIPROCESSING=0`. `UniProcExecutor.collective_rpc` calls the
worker synchronously even when `non_block=True`, then returns a completed or
async-output Future. Successive model submissions therefore retain worker and
CUDA stream order. The Earlier-forward path additionally requires the same
physical Block-ID proof as the Same-batch path.

This revision does not infer eligibility from metadata registration alone and
does not infer arbitrary partial-block publication. Only complete Hash Chain
blocks with complete physical Block evidence are eligible.

Source bindings:

- vLLM release `v0.27.1`;
- `vllm/v1/core/sched/scheduler.py`, one timestamp per Scheduler iteration and
  ordered lookup/allocation;
- `vllm/v1/core/kv_cache_manager.py`, early full-block metadata registration;
- `vllm/model_executor/layers/attention/attention.py`, explicit KV-update dummy
  dependency passed to unified attention;
- `vllm/v1/attention/backends/flash_attn.py`, physical Slot Mapping write and
  Block Table cache read;
- `vllm/v1/executor/uniproc_executor.py`, synchronous worker invocation; and
- `vllm/v1/metrics/stats.py`, first-SCHEDULED timestamp persistence.

## Audit output

Each request report contains `concurrent_eligibility_audits`. Every candidate
row binds producer and consumer identities, queued/scheduled/first-token
timestamps, Scheduler relation, clock domain, Snapshot event index, Hash LCP,
physical prefix Block IDs, eligible complete tokens, qualification result, and
an explicit
`uses_native_cached_tokens_c=false` marker. The 40 conflicting calibration
requests are extracted from those rows into a separate qualification table
before load targets or Headroom are reconsidered.

The read-only audit found 36 Same-batch and four Earlier-forward conflicts.
All 40 had matching process/hash/block-size identity, Hash LCP covering the
observed prefix, and identical physical prefix Block IDs. These observations
do not overwrite either the original Native evidence or the original
Fail-Closed evaluation.
