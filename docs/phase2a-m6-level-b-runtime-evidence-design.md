# Phase 2A M6 Level-B Runtime Evidence Design

Status: **M6 RECEIVER READY — RUNTIME EMISSION SEAM REQUIRES M1/M5 REVIEW**

This design defines the M6-side collection, join, and derivation boundary for
Level-B evidence. It does not add or modify a vLLM/vLLM-Metal hook.

## 1. Proposed raw event

The runtime seam emits at most one request-scoped event named
`VLLM_NATIVE_REQUEST_OBSERVATION` in the normal `phase2.event.v1` envelope.
It carries a real `request_id`, `program_id`, event index, source, timestamp,
and one native clock domain.

Its payload may contain only direct runtime facts:

| Field | Meaning |
| --- | --- |
| `eligible_prefix_tokens` | Native prefix-token amount eligible for reuse |
| `native_cached_prefix_tokens` | Native cached-prefix amount actually reported |
| `actual_prefill_tokens` | Prefill work actually performed |
| `native_scheduler_admission_timestamp` | Native scheduler admission landmark |
| `native_first_token_timestamp` | Native first-token landmark |

All token counts are non-negative integers. The cached amount cannot exceed
the eligible prefix amount. Actual prefill work cannot be smaller than the
recomputed reusable-prefix work derived from the two native prefix counts.

## 2. M6 collection and join

`kvopt.profiling.runtime_evidence` joins the native observation to replay,
`VLLM_REQUEST_SUBMITTED`, and `VLLM_REQUEST_COMPLETED` by the exact
`(run_id, request_id, program_id)` identity. Duplicate native events or identity
mismatches are data errors.

Every replay request receives one derived row. If the native observation does
not exist, direct fields remain null with explicit missingness statuses. Prefix
identity, planned return, logical release, and a later prefix snapshot are never
used to fill native fields.

## 3. Derived APC semantics

Only direct `eligible_prefix_tokens` and `native_cached_prefix_tokens` determine
the derived APC class:

```text
eligible = 0                         -> NOT_APPLICABLE
eligible > 0 and cached = 0          -> MISS
0 < cached < eligible                -> PARTIAL_HIT
cached = eligible and eligible > 0   -> FULL_HIT
```

Missing either count produces `missing_native_token_count`; it does not produce
a guessed miss or hit.

The Level-B loss is also derived on the M6 side:

```text
recomputed_prefill_tokens
= eligible_prefix_tokens - native_cached_prefix_tokens
```

This value remains unavailable when either direct input is missing. The runtime
does not emit the derived loss or APC label.

## 4. Request-level timing

M6 derives these durations only when both landmarks use the same clock domain:

```text
native_queue_delay = native scheduler admission - backend submission
native_ttft        = native first token - backend submission
native_e2e         = backend completion - backend submission
```

Different clock domains produce `incompatible_clock_domain`. Reversed
landmarks invalidate the artifact. Existing logical `REQUEST_ADMITTED` is not
renamed or substituted for native scheduler admission.

## 5. Formal-statistics boundary

The Level-B primary loss remains direct `recomputed_prefill_tokens`. APC class,
actual prefill work, queue delay, TTFT, and E2E are supporting or serving-impact
fields. Candidate loss and paired-rule statistics may consume this table only
after M1 approves the raw event semantics and the runtime reports the matching
capabilities as `AVAILABLE`.

No H1 holdout outcome should be collected until the receiver contract and the
runtime emission seam pass an end-to-end validation run.

## 6. Baseline latency calibration

The companion design
`configs/phase2/h1-level-b-collection-design.json` preregisters five identical
baseline repetitions. The primary non-inferiority metric is native E2E serving
time; native queue delay and TTFT are supporting diagnostics. All five repeats
must have identical scenario/config hashes and deterministic generation
settings.

The frozen rule already implemented by M4 is:

```text
epsilon_latency = max(abs(repeat_latency - mean_baseline_latency))
```

The resulting value and the hashes of its five raw runs are frozen before any
sealed H1 outcome is executed. A missing native timing landmark, incompatible
clock domain, changed config hash, or fewer than three successful repetitions
invalidates the calibration rather than widening epsilon by hand.
