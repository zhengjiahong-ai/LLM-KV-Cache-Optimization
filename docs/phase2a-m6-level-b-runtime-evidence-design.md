# Phase 2A M6 Level-B Runtime Evidence Design

Status: **AUTHORIZED FOR SEAM VALIDATION — FORMAL H1 EXECUTION LOCKED**

This document records the M1-approved Level-B observation contract implemented
by M6. It covers the read-only runtime seam, request-level joins, derived token
semantics, timing semantics, missingness, and S1-S5 validation. It does not
authorize formal H1 outcomes, formal H2 verdicts, B1, or Cost-Aware policy work.

## 1. Raw request observation

The runtime emits at most one `VLLM_NATIVE_REQUEST_OBSERVATION` per request in
the normal `phase2.event.v1` envelope. The envelope preserves the exact
`run_id`, `request_id`, `program_id`, and `native_request_id` identities.

The payload contains only native facts:

| Field | Native source | Observation moment | Availability rule |
| --- | --- | --- | --- |
| `native_prompt_tokens` | Length of `RequestOutput.prompt_token_ids` | Final request output | Unavailable if output omits native prompt IDs |
| `native_cached_prefix_tokens` | `RequestOutput.num_cached_tokens` | Final request output | Unavailable if local APC count is absent |
| `native_apc_block_hashes` | Ordered `Request.block_hashes` | Scheduler observation while request is live | Unavailable if no ordered native chain was captured |
| `native_hash_block_size` | Pinned scheduler block size | Same request observation | Unavailable if provenance is not exact |
| `native_hash_process_id` | EngineCore process identity | Same request observation | Required for same-process comparison |
| `native_hash_function` | Pinned APC hash configuration | Same request observation | Required for compatible comparison |
| `native_queued_timestamp` | `RequestOutput.metrics.queued_ts` | Final request output | Timing-only unavailable if metrics omit it |
| `native_scheduler_admission_timestamp` | `RequestOutput.metrics.scheduled_ts` | Final request output | Timing-only unavailable if metrics omit it |
| `native_first_token_timestamp` | `RequestOutput.metrics.first_token_ts` | Final request output | Timing-only unavailable if metrics omit it |

Prior `VLLM_PREFIX_SNAPSHOT` events retain `ordered_native_hashes`,
`ordered_native_cache_keys`, `hash_num_tokens`, `block_ids`, block size,
process identity, and hash function. `ordered_native_hashes` uses the same
32-byte `Request.block_hashes` representation as the current request;
`ordered_native_cache_keys` additionally preserves the group-qualified cache
keys. The seam verifies each cache key is the corresponding request hash plus
the native four-byte group ID. Logical prefix identity, planned return, or
release state never substitutes for these native facts.

## 2. Collection, identity, and missingness

`kvopt.profiling.runtime_evidence` joins replay, submission, completion, native
observation, and prior prefix snapshots by exact run/request/program identity.
Duplicate native observations and identity mismatches invalidate the artifact.

Token evidence and timing evidence have independent availability. Missing
EngineCore timestamps do not hide otherwise valid native token evidence.
Likewise, complete timing cannot fill missing prompt, cached-token, or hash
provenance. Every unavailable result keeps an explicit reason; values are never
clamped or inferred from logical lifecycle events.

## 3. Derived Level-B token semantics

For one request, let:

```text
N = native_prompt_tokens
C = native_cached_prefix_tokens
B = native_hash_block_size
```

M6 computes the longest common prefix between the current request's ordered APC
hash chain and previously materialized chains from the same run, process, hash
function, and block size. Reuse excludes the final prompt block:

```text
eligible_blocks = min(longest_common_prefix_blocks, floor((N - 1) / B))
E = eligible_blocks * B
W = N - C
R = E - C
```

The required invariants are:

```text
0 <= C <= E <= N
W = N - C
R = E - C
W = R + (N - E)
```

Any violation is data-invalid; no clamp is permitted. Classification is:

```text
E = 0                    -> NO_REUSE_ELIGIBLE_PREFIX
E > 0 and C = 0          -> MISS
0 < C < E                -> PARTIAL_HIT
C = E and E > 0          -> FULL_HIT
```

The fresh suffix `N - E` is excluded from `observed_recomputed_tokens`. This is
the key S5 guard against calling ordinary new-token prefill an eviction loss.

## 4. Timing semantics

Only landmarks from `engine_core_monotonic` are combined for native durations:

```text
native_queue_delay_seconds
  = native_scheduler_admission_timestamp - native_queued_timestamp

native_prefill_to_first_token_seconds
  = native_first_token_timestamp - native_scheduler_admission_timestamp
```

The primary request latency remains the wrapper measurement:

```text
backend_service_e2e_seconds
  = VLLM_REQUEST_COMPLETED.timestamp - VLLM_REQUEST_SUBMITTED.timestamp
```

It uses the wrapper's system-monotonic clock and is not renamed to native E2E.
Cross-domain subtraction is forbidden. Missing landmarks produce timing-only
missingness; reversed landmarks invalidate the artifact.

## 5. Decision loss boundary

The `observed_recomputed_tokens` loss view can use `R` only for a selected
candidate whose later return request has a direct runtime observation. An
unselected candidate is an unobserved counterfactual and remains unavailable.
Therefore request-level evidence may support observed policy outcomes without
pretending that every candidate has native loss evidence.

## 6. Required seam-validation scenarios

Before formal H1 materialization, the seam must pass:

- **S1 cold/no eligible prefix:** `E=0`, `R=0`, class
  `NO_REUSE_ELIGIBLE_PREFIX`.
- **S2 full hit:** `C=E>0`, `R=0`, class `FULL_HIT`.
- **S3 partial hit:** `0<C<E`, `R=E-C`, class `PARTIAL_HIT`.
- **S4 full loss:** `C=0<E`, `R=E`, class `MISS`.
- **S5 fresh suffix:** `N>E` and `W=R+(N-E)`; fresh suffix is excluded from
  recompute loss.

The runtime capability contract is finalized after request completion. Token,
first-token, and scheduler-timing capabilities are reported independently.

## 7. Baseline latency calibration and lock

The companion configuration
`configs/phase2/h1-level-b-collection-design.json` freezes five identical
baseline repetitions and the primary metric `backend_service_e2e_seconds`.
Supporting diagnostics are native queue delay and native prefill-to-first-token.

```text
epsilon_latency = max(abs(repeat_latency - mean_baseline_latency))
```

Scenario/config hashes and deterministic generation settings must match across
the five repeats. Epsilon and raw-run hashes are frozen before sealed H1 outcome
execution. The present status authorizes seam validation only; the formal H1
execution flag remains false.
