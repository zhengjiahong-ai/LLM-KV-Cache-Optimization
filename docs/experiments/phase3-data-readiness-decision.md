# Phase 3 Data Readiness and Execution Decision (M1)

Date: 2026-11-03  
Current main: `27249ab93953f531544ec8e226fc891adda60457`  
Frozen Protocol v3 HEAD: `3a8c3882ad248715b2f5ea90e34baa3875ea0226`  
Repository: [zhengjiahong-ai/LLM-KV-Cache-Optimization](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization)

## 1. M1 decision

M1 confirms that Phase 3 Final Evaluation Protocol v3 is **FROZEN**. PR #90
was merged on 2026-11-03 as `27249ab93953f531544ec8e226fc891adda60457`.
The protocol content is the reviewed M4 HEAD
`3a8c3882ad248715b2f5ea90e34baa3875ea0226`.

The protocol design is closed. No further changes to the six arms, hypotheses,
metrics, statistical unit, load definitions, thresholds, stop conditions or
310-run budget are authorized through ordinary implementation work. Any
proposed protocol change requires a separate M1 decision.

M1 now authorizes M6 to select, acquire and qualify the formal Phase 3 dataset
from the existing frozen W1-C candidate frame. Once the cohort and its
SHA-256-bound run manifest satisfy the frozen protocol requirements, M6 is
authorized to proceed with the formal evaluation sequence: A0 Load Calibration,
A0 Noise Calibration, then the six-arm Main Campaign after the applicable
protocol gates pass. This is a conditional execution authorization, not
permission to bypass G0–G4, G3-CM or any fail-closed condition.

## 2. Recent PR history

| PR | Delivery | Merge state | M1 interpretation |
| --- | --- | --- | --- |
| [#90](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/90) | M4 Final Evaluation Protocol v3 | **MERGED / FROZEN** as `27249ab` | M4 completed two protocol-revision rounds. M1 froze reviewed HEAD `3a8c3882ad248715b2f5ea90e34baa3875ea0226` by merging PR #90 on 2026-11-03. |
| [#92](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/92) | M6 Workload & Execution Feasibility Report | **MERGED** as `67e5e29b93d547040500f1205c5a2aeb8f469d6e` | Establishes execution feasibility and the 40 Primary + 24 Reserve plan from the remaining W1-C frame. It does not mean the formal traces have been acquired. |
| [#93](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/93) | Stage 1: six-arm Materializer, E0 and N0 integration | **MERGED** as `d0db0c7ae25eff8ad063c8f06c94b0b7271bd531` | Stage 1 complete. Cell materialization and CPU/Mock checks are implemented; this does not acquire tasks or select the final cohort. |
| [#94](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/94) | Stage 2: independent N/E/C Evaluator | **MERGED** as `8d51897fb90d310e322d347c6e4fb23cf7512b87` | Stage 2 complete. RC1–RC4 are closed, including timeline-aware history predecessors and duplicate-Snapshot rejection. |

## 3. Actual W1-C data inventory

The committed W1-C stratified sample contains 100 candidate task IDs:

- 20 tasks were acquired for the S50/S100 pilot across 12 repositories;
- 18 of those 20 are full-payload comparable;
- all 18 historical full-payload-comparable pilot tasks are excluded from the
  formal Phase 3 effect-estimation cohort;
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
| **Total** | **80 across 10 repositories** |

These counts establish candidate-frame coverage only. They do not establish
Full Payload, Profile or Native Replay readiness for any unacquired task.

No final 40-task Phase 3 trace cohort or materialized 64-ID Primary/Reserve
manifest is present in current `main`. PR #92 contains the feasibility report
and sampling proposal; PR #93 contains the six-arm cell materializer; neither
delivers the final 40 new traces.

## 4. Frozen formal cohort requirements

The formal cohort must satisfy the frozen Protocol v3 / M6 feasibility design:

- 40 **new qualified Agent tasks**;
- 20 independent Workload Groups;
- two tasks per group, from different repositories;
- at least **10 distinct repositories** overall;
- 40 Primary candidates plus 24 pre-registered Reserve candidates, selected
  deterministically from the existing 80 unacquired W1-C candidate IDs.

The ten-repository minimum is part of frozen Protocol v3 and M6 PR #92. It is
not relaxed by this M1 decision. If the existing candidate frame cannot yield
40 qualified tasks, 20 legal groups and at least ten repositories, M6 must
report the actual qualified count, repository coverage, failed qualification
reasons and blockers. Do not lower thresholds or expand the candidate frame.

The 18 historical full-payload-comparable pilot tasks must not be reused in
formal effect estimates. Reserve promotion must follow pre-registered,
pre-Native qualification rules and must never depend on policy outcomes.

## 5. Next action: M6 selects and qualifies the formal dataset

M6 is authorized to perform the following work within the existing frozen
80-candidate W1-C frame:

1. Materialize the deterministic 64-ID Primary/Reserve list (40 Primary +
   24 Reserve), excluding all 20 previously acquired pilot task IDs.
2. Select and acquire the 40 formal Agent traces using the pre-registered
   qualification and reserve-substitution rules.
3. Validate each task's Full Payload, tool observations, failure/right-censoring
   evidence, Explicit Token IDs, sidecars, Prefill Profile and Native Replay
   feasibility under the frozen model/runtime/context constraints.
4. Construct 20 legal cross-repository Workload Groups and report per-repository
   counts, task/request counts, prompt-length/LCP distributions, source gaps,
   failure classes and right-censoring.
5. Produce the formal dataset manifest and run-input manifest with SHA-256
   bindings for task IDs, repository/source revisions, trace and sidecar hashes,
   profile hashes, Primary/Reserve roles, group pairing, request subsets,
   Frozen Request Order, Native Enqueue Order, Replay Timeline, Session pairing,
   and per-request History Predecessors.

The final data package must distinguish candidate IDs from acquired traces and
include a READY / READY WITH LIMITATIONS / NOT READY conclusion. A cohort that
does not meet all frozen requirements is not eligible for the formal campaign;
stop and return the evidence to M1 rather than silently substituting or
relaxing constraints.

## 6. Cohort seal and Stage 3 boundary

Stage 1 and Stage 2 are complete. M1 does not require a separate standalone
code-engineering stage called "Stage 3 Cohort Seal". However, the **cohort seal
itself is mandatory**: M6 must produce the deterministic 64-ID Primary/Reserve
record and the final qualified 40-task / 20-group dataset/run manifest described
above, SHA-256 bind it, and ensure it satisfies the Stage 2 evaluator's history
predecessor contract. This is a data-selection and pre-run freeze deliverable,
not permission to skip the seal.

## 7. Formal evaluation sequence and authorization

The six arms remain N0/A0/A1/A2/A3/E0. The 310-run plan is unchanged:

| Set | Runs | Order |
| --- | ---: | --- |
| A0 Load Calibration | 40 | First; calibrate the two load targets and derive the pre-run Headroom inputs |
| A0 Noise Calibration | 30 | Before the Main Campaign; estimate the noise floor and define the pre-registered tied threshold |
| Main Campaign | 240 | 20 groups × 2 loads × 6 arms; execute only after the applicable frozen protocol gates pass |
| **Total** | **310** | — |

The main campaign's statistical unit remains the Workload Group: 20 groups per
load, analyzed separately by load rather than pooled into n=40. PR #92's
3–5 RTX 4090D GPU-hour estimate and 6-hour ceiling are planning values; M6 must
reconfirm them against the qualified cohort.

A public Continuum system-level comparison is not silently added to the
six-arm matrix. If later considered, it requires a separate protocol.

### Authorization

**Authorized now**

- deterministic selection of 40 Primary + 24 Reserve IDs from the existing
  frozen 80-candidate frame;
- Agent-trace acquisition and qualification within that frame;
- construction and SHA-256 sealing of the final dataset/run manifest;
- after the cohort is complete and frozen, the 40-run A0 Load Calibration and
  30-run A0 Noise Calibration;
- after the applicable frozen protocol gates pass, the 240-run Main Campaign.

**Not authorized**

- expansion or replacement of the frozen 80-candidate frame;
- changing the 10-repository minimum, group structure, six arms, metrics,
  thresholds, load definitions or 310-run budget;
- post-outcome workload/algorithm retuning or reserve substitution based on
  Native policy outcomes;
- adding a public Continuum arm to the frozen six-arm campaign.

Any qualification shortfall, missingness pattern that violates the protocol,
G0–G4/G3-CM failure, or proposed deviation must stop at the relevant gate and
return to M1. No further protocol-design review is needed for a compliant
execution of the frozen plan.
