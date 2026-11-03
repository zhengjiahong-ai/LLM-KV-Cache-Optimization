# Phase 3 Data Readiness Decision (M1)

Date: 2026-11-03  
Canonical code baseline: `main` @ `8d51897fb90d310e322d347c6e4fb23cf7512b87`  
Repository: [zhengjiahong-ai/LLM-KV-Cache-Optimization](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization)

## 1. Purpose

This record reconciles the actual Phase 3 delivery history and sets the next
M1-approved action. It supersedes the earlier ten-repository minimum and the
proposal to make Cohort Seal a separate engineering stage. It does not alter
the six-arm algorithm definitions, N/E/C semantics, primary metric, statistical
unit or 310-run plan.

## 2. Recent PR history

| PR | Delivery | Merge state | M1 interpretation |
| --- | --- | --- | --- |
| [#90](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/90) | M4 Final Evaluation Protocol v3 | **OPEN / DESIGN_ONLY**, HEAD `3a8c3882ad248715b2f5ea90e34baa3875ea0226` | M4 completed two revision rounds (9 items in v2 and 7 in v3). No M1 final approval or merge. The branch is based on stale main and must be synchronized and reconciled before formal freeze. |
| [#92](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/92) | M6 Workload & Execution Feasibility Report | **MERGED** as `67e5e29b93d547040500f1205c5a2aeb8f469d6e` | Confirms execution feasibility and proposes 40 Primary + 24 Reserve from the remaining W1-C frame. It is not evidence that the new cohort has been acquired. |
| [#93](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/93) | Stage 1: six-arm Materializer, E0 and N0 integration | **MERGED** as `d0db0c7ae25eff8ad063c8f06c94b0b7271bd531` | Stage 1 complete. Cell materialization and CPU/Mock checks are implemented; this does not acquire tasks or construct the final cohort. |
| [#94](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/94) | Stage 2: independent N/E/C Evaluator | **MERGED** as `8d51897fb90d310e322d347c6e4fb23cf7512b87` | Stage 2 complete. RC1–RC4 are closed, including timeline-aware history predecessors and duplicate-Snapshot rejection. |

### Stage 1 closeout

PR #93 materializes a supplied frozen cell into six arms (N0/A0/A1/A2/A3/E0),
preserves shared Trace/Explicit Token IDs/pressure/replay inputs, binds a common
input SHA, and keeps `execution_authorized=false`. E0 and N0 CPU/Mock
integration is complete. It is a cell expander, not a task-acquisition or
cohort-selection tool.

### Stage 2 closeout

PR #94 implements independent request-level N/E/C evaluation. `N` is derived
from Native prompt tokens, `C` from Native APC cached tokens, and `E` from
frozen history plus Native content identity. E never uses C as fallback.
RC1–RC4 cover Native Observation scope, fixed six-arm contract, hash-chain
integrity, and timeline-aware history completeness. The evaluator requires
Frozen Request Order = Native Enqueue Order and an explicit per-request
History Predecessor relation derived from the frozen Replay Timeline.

M6 reported 26 Stage 1/2 targeted tests and a full CPU regression of 1736
passed, 8 skipped, 1 deselected, plus Ruff and diff checks. M1 added the final
post-observation duplicate-Snapshot regression before merge. The repository
does not expose a CI workflow result for that final M1 patch; the PR history
and merged source are the authoritative implementation record.

## 3. Actual W1-C data inventory

The committed W1-C stratified sample has 100 candidate task IDs:

- 20 were acquired for the S50/S100 pilot across 12 repositories;
- 18 of those 20 are full-payload comparable;
- the 18 historical comparable tasks are excluded from the formal Phase 3
  effect-estimation cohort;
- the remaining 80 task IDs are unacquired candidates, not Agent traces.

The 80 remaining candidate IDs currently span ten repositories:

| Repository | Candidate IDs |
| --- | ---: |
| django/django | 40 |
| sympy/sympy | 12 |
| sphinx-doc/sphinx | 7 |
| matplotlib/matplotlib | 6 |
| scikit-learn/scikit-learn | 5 |
| pytest-dev/pytest | 3 |
| pydata/xarray | 3 |
| astropy/astropy | 2 |
| psf/requests | 1 |
| pylint-dev/pylint | 1 |
| **Total** | **80** |

These counts establish candidate-frame coverage only. They do not establish
Full Payload, Profile or Native Replay readiness for any unacquired task.

No final 40-task Phase 3 trace cohort or materialized 64-ID Primary/Reserve
manifest is present in current `main`. PR #92 contains the feasibility report
and sampling proposal; PR #93 contains the six-arm cell materializer; neither
delivers the final 40 new traces.

## 4. M1 cohort ruling

The formal target remains:

- 40 **new qualified Agent tasks**;
- 20 independent Workload Groups;
- two tasks per group, from different repositories;
- at least **8 distinct repositories** overall.

The minimum of 8 repositories supersedes the earlier 10-repository minimum
written in PR #92 and the still-open PR #90 draft. Do not lower the threshold
below 8. If the existing frame cannot yield 40 qualified tasks across at least
8 repositories, M6 must report the actual qualified count, repository count,
failed qualification reasons and blockers for M1 review.

The 18 historical full-payload-comparable pilot tasks must not be reused in
formal effect estimates. The existing 80 unacquired W1-C candidate IDs remain
the acquisition frame; candidate-pool expansion requires a new M1 decision.

The 40 Primary + 24 Reserve plan from PR #92 remains the working plan within
that frame. Reserve promotion must follow pre-registered, pre-Native
qualification rules and must never depend on policy outcomes.

## 5. Next action: M6 Final Evaluation Data Readiness Confirmation

M6 is authorized to confirm and acquire/validate the Agent traces needed for
the final cohort within the existing 80-candidate W1-C frame. The deliverable
must distinguish candidates from acquired traces and report, per task:

1. task ID, upstream repository and pinned source revision;
2. acquisition state and qualification outcome;
3. Full Payload completeness, including conversation/tool observations and
   failure or right-censoring information;
4. Explicit Token IDs and source/sidecar integrity;
5. Prefill Profile availability and provenance;
6. Native Replay feasibility under the frozen vLLM/model/tokenizer/runtime
   constraints;
7. request order, Session pairing and Replay Timeline availability;
8. prompt/request length and context-limit compatibility;
9. source, trace, sidecar, profile and relevant configuration hashes.

The report must provide the proposed 40-task Primary set, 24 pre-registered
Reserve candidates, 20 legal cross-repository groups, per-repository counts,
and a clear READY / READY WITH LIMITATIONS / NOT READY conclusion. If the
minimum of 8 repositories or 40 qualified tasks is not met, stop and report;
do not silently substitute, lower the threshold or expand the frame.

## 6. No separate Stage 3 Cohort Seal engineering milestone

Stage 1 and Stage 2 are complete. M1 does not require another standalone
Cohort Seal implementation stage before the final evaluation.

The final accepted data/run manifest must nevertheless freeze and SHA-256 bind
the task membership and pairing, Frozen Request Order, Native Enqueue Order,
Replay Timeline, Session pairing, and per-request History Predecessors. These
fields are required by the merged Stage 2 evaluator and are part of final
pre-run data/run preparation, not a separate engineering phase.

## 7. Final Evaluation remains unchanged

The six arms remain N0/A0/A1/A2/A3/E0. The planned 310 runs remain:

| Set | Runs |
| --- | ---: |
| A0 Load Calibration | 40 |
| A0 Noise Calibration | 30 |
| Main Campaign: 20 groups × 2 loads × 6 arms | 240 |
| **Total** | **310** |

The main campaign's statistical unit remains the Workload Group: 20 groups per
load, analyzed separately by load rather than pooled into n=40. PR #92's
3–5 RTX 4090D GPU-hour estimate and 6-hour ceiling are planning values; M6 must
reconfirm them against the qualified cohort.

A public Continuum system-level comparison is not silently added to the
six-arm matrix. If later considered, it requires a separate protocol.

## 8. Authorization

Authorized now:

- M6 data-readiness audit;
- Agent-trace acquisition and qualification within the existing 80-candidate
  W1-C frame;
- task/group proposal and preparation of the final data/run manifest.

Not authorized yet:

- A0 Load Calibration;
- A0 Noise Calibration;
- GPU Smoke;
- 240-run Main Campaign.

After M1 accepts the M6 data-readiness report and M4 synchronizes/reconciles
Protocol v3 PR #90 with this decision, proceed directly to Final Evaluation.
No additional standalone Stage 3 engineering milestone is required.
