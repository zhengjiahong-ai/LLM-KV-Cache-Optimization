# Phase 5 Formal Campaign Engineering Acceptance Status

**Status:** CPU/Mock integration substantially complete; external and GPU gates remain

**GPU Calibration/Formal execution:** not started and not authorized

## 1. Integrated path

The engineering branch now provides one coherent path:

`Protocol validation → Trace qualification → Workload Seal → N-session Replay → Six-system plan → isolated execution contract → raw evidence → independent metrics → Calibration binding → Formal analysis → deterministic archive`

The exact systems are Native, Continuum Official, Continuum Adapted, A1
Original, A3 Suffix and DVA-ER v1. Every paired cell shares one Workload Seal,
Arrival realization and expected enqueue identity. Each system Run requires a
fresh process, fresh EngineCore, empty cache, no preheat and no automatic
retry.

## 2. CPU/Mock gates

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Protocol/schema/hash loader | PASS | structural and identity validation only |
| Generic Trace contract and Workload Seal | PASS | no Formal Cohort selected |
| N-session Replay and frozen arrival | PASS | CPU event/state contract |
| Async Native Adapter lifecycle | PASS | CPU/Mock; pinned API source audit exists |
| Six-system matrix and routing | PASS | CPU/Mock execution contract |
| DVA-ER v1 correctness | PASS | merged 28-test CPU gate |
| DVA Candidate adapter | PASS | real `DVAERStrategy`, decision-time evidence only |
| Candidate/SelectionPlan/physical join | PASS | identity consistency only |
| Independent N/E/C and serving metrics | PASS | raw-evidence contract |
| Group-level analysis | PASS | paired permutation, t, bootstrap and Holm |
| Campaign manifests and archive | PASS | deterministic archive round trip |
| P5E Part A Mock pipeline | PASS | explicitly not GPU Conformance |

## 3. Real Native gates

No new Phase 5 Formal Native gate has passed in this engineering work. Earlier
Phase 3 evidence and the pinned vLLM source/API audit are not substitutes for
the Phase 5 six-system Native Conformance gate.

DVA-ER is recorded as:

- CPU correctness: `PASS`;
- candidate status: `PROVISIONAL_NOT_FROZEN`;
- Native Conformance: `NOT_RUN`.

The CPU orchestrator may exercise the provisional adapter interface, but its
Formal-system readiness remains `BLOCKED` until M1/M4 freeze the candidate and
the live Native compatibility gate passes.

## 4. Open protocol and environment gates

| Gate | Current state | Required action |
| --- | --- | --- |
| U1 DVA formal freeze | CPU gate passed; protocol still provisional | M1/M4 protocol-state update |
| U2 Adapted scheduler scope | unresolved | M1/M6 audit and system-label decision |
| U3 Continuum Official compatibility | not run | pinned environment evidence |
| U4 BFCL acquisition | not authorized | M1 authorization and frozen fixture |
| U5 Arrival rate/seed | provisional | M1/M4 freeze |
| U6 GPU budget | requested, not authorized | M1 authorization |
| U7 censored-session population | unresolved | M1/M4 freeze |
| P5E Part A | changed-HEAD Seal and GPU run absent | authorized GPU window |
| Stop/Abort Part B | `NOT_READY` | independent Native abort confirmation |

## 5. Remaining engineering limitation

The Calibration module validates the exact 144-run matrix and implements the
M4-frozen common mixed model after removing the two Stratum fixed effects.
The method-of-moments backend uses `df_between=6`, `df_within=16`, and
`df_total=22`; per-Stratum `df=3/8` is retained only for descriptive and
conservative upper-bound calculations. It produces an 8x8 `df=6` covariance
with PSD projection, seeded 10,000-resample parametric-bootstrap variance
upper bounds, and iterative noncentral-t sizing with `df=n-1`. The incompatible
`pooled_df=7` and z approximations are explicitly prohibited. Calibration
remains unexecuted and does not authorize Formal execution.

Source-specific SWE-bench/mini-SWE-agent and BFCL acquisition remains blocked
by data availability and authorization. Generic normalization, qualification
and sealing are implemented; no incomplete public artifact is labelled a
fully replayable Agent Trace.

## 6. GPU-only acceptance sequence

Once the external decisions and GPU resource are available, the continuous
sequence is:

1. environment and exact code/contract hash preflight;
2. regenerated P5E Seal and bounded Part A Native Conformance;
3. authorized Trace acquisition and Q1--Q9 qualification;
4. six-system Calibration;
5. exact sample-size calculation and final Formal freeze;
6. six-system Formal Campaign;
7. independent evaluation and deterministic archive validation.

Mock PASS, Candidate Exposure, predicted victim divergence and physical victim
matching do not establish Cost-Aware system benefit.
