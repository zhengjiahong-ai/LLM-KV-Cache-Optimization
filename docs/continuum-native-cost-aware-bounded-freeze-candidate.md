# Bounded Native Cost-Aware evaluation freeze candidate

Status: **PENDING M1 FINAL FREEZE**

This candidate supersedes the unexecuted 3B/108-run protocol. It does not
change or reinterpret any earlier Metal, H800, W1-A, W1-B, or W1-C evidence.

## Frozen design candidate

- Model: `Qwen/Qwen2.5-Coder-1.5B-Instruct` at
  `d18ecad881a290f0c792f1c2b5dbee1820d4a424`.
- Tokenizer: the same repository and revision, subject to an empirical exact-ID
  compatibility gate against every frozen W1-C replay request.
- Runtime: vLLM 0.27.1 CUDA, a qualified 24GB-or-larger GPU,
  `max_model_len=32768`, chunked prefill with a 2,048-token budget, and eager
  execution.
- Cohort: all 18 previously frozen W1-C tasks in all nine disjoint groups.
- Cells: nine groups by two pressure regimes by A0/A1/A2 by one runtime run,
  for 54 planned Native runs.
- Statistical unit: one two-task workload group. The single runtime execution
  does not establish run-to-run stability, and all results are exploratory.

## Controlled sparse replay time

The selected W1-C checkpoint timestamps are retained as a monotonic Continuum
lifecycle clock, but they are not converted into wall-clock sleeps. The
implementation is `kvopt.continuum.ControlledSparseReplayClock`, which reuses
the existing `Clock`/`FakeClock` abstraction and records every explicit time
advance.

Logical time drives Continuum lifecycle, TTL, Deadline, q, retention expiry,
and pressure decisions. Native vLLM execution continues to use its real
monotonic clock. Each time advance records `logical_timestamp`,
`native_monotonic_timestamp`, the source boundary, and actual wall elapsed
time. The two domains cannot be subtracted or ordered without an explicit
conversion. Logical time cannot advance while any Native request is inflight,
and all three arms must bind the identical logical event-sequence SHA-256.

This is **Controlled Sparse Replay with Logical Lifecycle Time**. It does not
reconstruct the omitted Agent turns or claim to reproduce their production
cache state and service timing. A runner that cannot preserve the frozen
ordering, two-request concurrency bound, and zero-inflight time-advance rule
must fail closed rather than fall back to zero-gap or mixed-clock replay.

The exact machine, driver, PyTorch build, KV capacity, pressure shortage, code
SHA, configuration SHA, and trace SHA remain pre-execution bindings. A change
to any bound value invalidates authorization rather than silently rematerializing
the campaign.

## Sparse PrefillReload profile

The proposed grid is 1,024, 4,096, 8,192, 12,288, 16,384, 24,576, and 32,256
tokens. Each point uses two warmup and eight measured MISS/HIT pairs. The grid
was selected before any 1.5B profile outcome and covers the frozen query range
of 1,248–32,144 tokens without extrapolation.

The canonical point estimate is the median of eight measured deltas. Raw
deltas, IQR, and a 10,000-resample bootstrap interval with seed 20261121 must be
reported. Piecewise-linear interpolation is allowed only inside the measured
range. Adjacent secant slopes are reported without post-outcome grid changes.
An A1 decision whose ordering changes under the pointwise uncertainty envelope
is `INCONCLUSIVE_COST_ORDERING`; uncertainty is never silently clamped away.

## Pre-execution gates

Execution remains locked until all of the following are bound and pass:

1. Every frozen explicit token ID is accepted unchanged by the 1.5B model and
   tokenizer; submitted digests must equal the W1-C frozen digests.
2. The 32,154-token maximum request completes without truncation or
   retokenization.
3. Static and real-runtime capacity checks demonstrate the two-session,
   pressure, and return geometry on the selected 24GB GPU.
4. Native content identity, APC, physical eviction, and request-level
   recomputation evidence remain available and fail closed when incomplete.
5. A0/A1/A2 share request content, order, capacity, pressure, and runtime
   configuration; only the authorized policy layer differs.
6. All seven Profile points complete under the identical model/backend freeze,
   and ranking-sensitivity analysis is implemented before policy outcomes.
7. The materialized 54 configs and traces, runner, evaluator, model, Profile,
   and runtime environment receive immutable SHA bindings.
8. M1 changes the campaign state from `PENDING_FINAL_FREEZE` to explicitly
   authorized.

## Budget and stop rule

At CNY 2 per GPU-hour, the candidate estimates 8–20 GPU-hours (CNY 16–40) and
sets a recommended cap of CNY 60. The run stops before exceeding the approved
cap or after a systematic fidelity/capacity failure. Failed attempts and
missing evidence are retained; workloads are not replaced based on policy
outcomes.

The machine-readable protocol and Profile plan are
`configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json` and
`configs/phase2/continuum-native-cost-aware-bounded-prefill-profile-v1.json`.
