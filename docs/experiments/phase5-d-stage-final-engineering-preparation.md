# Phase 5 D-Stage Final CPU Engineering Preparation

**Status:** CPU/interface preparation complete; Native/GPU conformance not run

**Date:** 2026-11-25

**Frozen workload:** PR #138 SWE membership, Groups and Arrival unchanged

The final contract cleanup binds the production DVA-ER provider to the exact
EngineCore object supplied at installation and requires every controller timer
to carry a non-empty chain identity whose Program/Session identity matches the
candidate. M1/M2 divergence is computed only against an explicit A0 comparator;
distinct observed entries or victim sequences remain descriptive heterogeneity,
not algorithmic divergence. M3 separately reports physical-vs-predicted and,
when observable, selected-physical-vs-A0 comparisons.
The formal physical-evidence producer now requires the independently executed
`CONTINUUM_ADAPTED` outcome for the same frozen Pressure Boundary and emits the
A0 selected, predicted and physical comparator fields consumed by M1/M2/M3.

## 1. SWE-only execution contract

All formal execution layers now use the sole formal Stratum `SWE_BENCH`:

- Calibration: 4 Groups × 6 Systems × 3 Repeats = 72 runs;
- Formal: integer N in 8..16, 6 Systems × 2 Repeats = 12N runs;
- reference points N=8/12/16 give 96/144/192 formal runs;
- minimum complete campaign: 168 runs;
- BFCL Derived remains a separate descriptive/exploratory supplement.

The calibration model uses `df_between=3`, `df_within=8`, `df_total=11` and
`df_covariance=3`. The 8×8 contrast covariance is explicitly rank-bounded by
3; direct full-rank inversion is prohibited. Sample sizing searches every
integer N from 8 through 16 using the frozen noncentral-t method. If N>8 is
required, the current materialized data capacity is insufficient and the
runner returns to M1 rather than reusing data or reducing power.

The GPU projection is implemented as:

```text
(1+reserve) × Σ_s [12*Tcal_s + 2N*Tformal_s
  + (12+2N)*(startup_s+restart_s+archive_s+evaluator_s)] / 3600
```

The obsolete two-Stratum 72–112 hour envelope is not reused.

## 2. DVA-ER production runtime preparation

The Phase 5E same-core installer now requires the live integration to build a
`DVAERNativeDecisionProvider` from the exact EngineCore, Scheduler,
KVCacheManager and BlockPool objects before the controlled hook is installed.
The provider remains fail-closed for missing BlockPool/free-queue, refcount,
protection, owner, Program/Session/follow-up identity or controller-armed timer
evidence, and for future/stale/cross-core observations.

This is a real production installation path, but its runtime result remains:

```text
NATIVE_RUNTIME_CONFORMANCE = NOT_RUN
```

Only a future authorized GPU run can confirm the pinned vLLM object shapes,
live values and complete event emission.

## 3. M0–M5 observation framework

The archive now carries a separate `mechanism_observations_m0_m5` stream:

- M0: Decision Space;
- M1: Selection Divergence;
- M2: Predicted Victim Divergence;
- M3: Actual Physical Eviction;
- M4: Downstream Recompute observation;
- M5: paired Group-level System Effect.

These levels are observations, not gates. Single-candidate decisions, equal
scores/selections/victim sets, and zero downstream differences remain valid
research results. Missing evidence is `NOT_OBSERVABLE`, never silently zero.
The following boundaries remain fixed:

```text
eviction_causal_attribution = NOT_ESTABLISHED
downstream_recompute_attribution = NOT_ESTABLISHED
algorithmic_benefit_claim = NOT_ESTABLISHED
```

H=60s remains the uncalibrated design prior. H=30s/120s are same-snapshot
offline sensitivity values only; they add no GPU arm and cannot be selected
after outcomes.

## 4. Frozen SWE workload analysis

The analyzer was run against both private processed roots for all frozen 48
Programs. Private output SHA-256:

`b91b346f0ca20794631a62da3c9e719dc31681bd2039697a882747d6a3d2e2f1`

Key trace-level observations:

- 4,611 requests; 48 Sessions; Turn P50=100, mean=96.06;
- Prompt tokens P50=9,818, max=32,093;
- adjacent exact LCP P50=9,708 tokens;
- adjacent normalized prefix reuse P50=98.31%;
- exclusive suffix/context growth P50=176 tokens;
- actual tool execution P50=0.278s (2,860 observations);
- adjacent request interval P50=0.282s (4,563 observations);
- cross-Program first-request block LCP=112 tokens for all 1,128 pairs;
- 71 within-Group Program pairs overlap under frozen Poisson arrivals.

Tool execution duration and adjacent request interval are reported separately.
The latter can include controller and other overhead. These trace statistics
do not establish Native residency, legal candidate exposure, eviction,
recomputation or benefit. Frozen membership, Grouping and Arrival were not
changed.

Right-censor sensitivity is `NOT_ESTIMABLE`: only two Natural Terminal
Programs exist and cannot form a four-Program Group. Primary analysis uses
only valid observed requests and never imputes future Turns.

## 5. BFCL Derived boundary

The accepted 4 descriptive Calibration Groups and 8 exploratory Evaluation
Groups retain `BFCL_DERIVED_CONTROLLED_TIMING`, synthetic one-second gaps,
`SOURCE_TERMINAL_UNKNOWN` and `REPLAY_TRACE_EXHAUSTED`. They are not pooled
with SWE and do not count toward SWE N.

## 6. Verification and remaining GPU-only risks

CPU tests cover SWE-only matrices, integer-N sizing, covariance rank,
resource projection, archive evidence, M0–M5 semantics, and same-core provider
installation. The only full-suite failure while changes are uncommitted is the
pre-existing Phase 2E test that intentionally rejects a dirty worktree.

Remaining runtime-only questions are:

1. pinned vLLM live BlockPool/free-queue shapes and values;
2. controller timer and identity coverage at real decision boundaries;
3. real Native concurrency, allocation watermark and pressure execution;
4. physical victim/content evidence and downstream APC N/E/C observations;
5. per-system timing measurements needed to freeze the GPU budget;
6. Native Conformance, Calibration and Formal execution outcomes.

No GPU execution, Calibration or Formal Campaign is authorized by this report.
