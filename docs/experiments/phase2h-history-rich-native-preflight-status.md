# Phase 2H History-Rich Native Replay — Preflight Status

## Scope

This record covers the execution infrastructure and CPU/static preflight
authorized after the PR #85 freeze. It is not a Native GPU Smoke result and it
does not authorize the six frozen GPU runs.

## Frozen execution inputs

- Scenarios: `hr01-balanced-gap`, `hr02-short-gap-long-context`
- Arms: A0, A1, A2; one run per arm and scenario
- Requests: 180 exact-token requests per scenario (60 per session)
- Pressure barriers: after rounds 40, 50, and 55
- KV capacity: 2,048 blocks of 16 tokens
- Fixed pressure: 12,256 tokens for HR01; 6,064 tokens for HR02
- Stop controls: 1,800 seconds per run; 14,400 seconds total GPU wall time

## Static preflight result

The static preflight generated from the frozen W1-C S100 sidecars reports
`PASS_STATIC_PREFLIGHT`.

- Both scenarios contain exactly 180 requests and 363 logical boundaries.
- Each scenario contains 117 observed within-session gaps before the first
  pressure boundary, meeting the frozen empirical-TTL history threshold.
- Every individual request fits within the 2,048-block capacity.
- The first fixed pressure input produces the preregistered nominal shortage:
  32 blocks for HR01 and 128 blocks for HR02, before accounting for earlier
  physical evictions.
- Later logical joint demand can exceed capacity by design. This is repeated
  capacity competition, not evidence that all three prefixes remain resident.
- Timeline and pressure token inputs are deterministic and share identical
  SHA-256 identities across A0/A1/A2.

Generated artifact:

`artifacts/phase2h-history-rich-native-preflight-v1/static-preflight.json`

SHA-256:

`51ef3df0130b6710ac82499cebf15e33d08f99e9ba2433656de6464e31547608`

## Implemented observation contract

- Every TTL input persists global/tool history sample counts, complete sample
  arrays, source provenance, threshold, ETA, queue delay, and reload estimate.
- Every TTL result persists mode, reason, consumed TTL, and derived deadline.
- A1 selection traces persist actual decision-time `need` together with every
  candidate's q, newly eligible blocks, deadline, and score inputs.
- The Gate H evaluator independently recomputes TTL and deadline from persisted
  inputs.
- Gate D treats A1 scoring as actual evidence only on A1. A0/A2 expose candidate
  opportunity but are explicitly labelled `SHADOW_DIAGNOSTIC_NOT_EXECUTED`.
- Fixed pressure token IDs are validated against stage size and model vocabulary;
  runtime policy outcomes cannot alter the pressure input.

## Outstanding Native preflight

The following remain `NOT_RUN_GPU_EXECUTION_NOT_AUTHORIZED` and must be measured
on the target CUDA runtime before M1 execution authorization:

- longest-request execution and actual 2,048-block pool binding;
- three-session Native inflight/barrier behavior;
- all three fixed pressure stages and forced-release exposure;
- empirical TTL decisions consuming the recorded history;
- stable identity joins across eviction, re-request, APC, recomputation, and
  right-censored content;
- per-run Gate H and Gate D reports, runtime, and stop-control telemetry.

No GPU Smoke was started while producing this record.
