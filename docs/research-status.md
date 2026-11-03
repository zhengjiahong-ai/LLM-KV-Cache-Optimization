# Research Status (M1 canonical status index)

Status: **ACTIVE — W1-C and Bounded Native Cost-Aware evaluation ACCEPTED / CLOSED; next method decision pending**  
As-of decision: M1 review 2026-10-27, [PR #82](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/82), evaluated HEAD `673da7f0631085942abbb932559af243b7c03dbf`.  
Owner: M1. This document indexes decisions and evidence; it does **not** amend sealed artifacts or replace their final reports.

## How to read the evidence

- **Campaign delivered / code merged** does not imply **hypothesis supported** or **formal algorithm benefit demonstrated**.
- `CLOSED` means a stage's accepted scope has concluded, not that every research hypothesis passed.
- `UNDER_REVIEW` means its submission, numbers and gate are **not yet M1 accepted**.
- `AUTHORIZED` means an explicitly bounded operation may start; it does not imply measurements have been collected.
- Unit of inference matters: independent scenario draws or independently sampled tasks/session groups, **not** runtime repeats, turns or request rows.
- No source-generated Agent trace is the author's original paper-run serving trace unless independently established.

## Current Phase 3 status (M1 reconciliation, 2026-11-03)

Current main: `8d51897fb90d310e322d347c6e4fb23cf7512b87`.

| PR | Delivered scope | Current state | Boundary |
| --- | --- | --- | --- |
| [#90](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/90) | M4 Final Evaluation Protocol v3 | **OPEN / DESIGN_ONLY** | M4 completed two protocol-revision rounds; no M1 final approval or merge. Its branch is based on an old main and must be synchronized before formal freeze. |
| [#92](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/92) | M6 Workload & Execution Feasibility Report | **MERGED** as `67e5e29` | Establishes execution feasibility and a proposed cohort/budget; it does not mean 40 new traces have been acquired. |
| [#93](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/93) | Stage 1 six-arm Materializer, E0 and N0 integration | **MERGED** as `d0db0c7` | CPU/Mock engineering only. Materializes a supplied cell; it does not acquire tasks or construct the final cohort. |
| [#94](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/94) | Stage 2 independent N/E/C Evaluator | **MERGED** as `8d51897` | RC1–RC4 closed, including timeline-aware history predecessors and duplicate-Snapshot rejection. No calibration or GPU campaign. |

### Data inventory and what is still missing

The frozen W1-C sample contains 100 task candidates. Twenty were acquired for the S50/S100 pilot across 12 repositories; 18 are full-payload comparable. Those historical pilot tasks are restricted to engineering regression and evaluator validation and are not eligible for the formal Phase 3 cohort.

The remaining 80 IDs are **unacquired candidates**, not complete Agent traces. The current frozen frame distributes them across ten repositories:

| Repository | Remaining candidates |
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

No final 40-task Phase 3 trace cohort or materialized 64-ID Primary/Reserve manifest is present in the current main tree. PR #92 records the proposed 40 Primary + 24 Reserve sampling plan; PR #93 is a six-arm cell materializer, not a cohort builder.

### Current M1 data decision

The formal target remains **40 new qualified tasks arranged into 20 independent Workload Groups**, with two tasks from different repositories in every group. The minimum repository coverage is now **8 repositories**, not 10. This M1 ruling supersedes the earlier 10-repository minimum in the PR #92 feasibility report and the still-open PR #90 protocol draft. If fewer than 8 repositories or fewer than 40 qualified tasks can be obtained from the existing frozen candidate frame, M6 must report the actual result and blockers; the threshold must not be silently lowered and the candidate frame must not be expanded without M1 approval.

The 18 historical full-payload-comparable pilot tasks remain excluded from formal effect estimates. The existing 80-candidate W1-C frame is the acquisition boundary. The PR #92 plan of 40 Primary candidates and 24 pre-registered Reserve candidates remains the planning baseline unless M1 explicitly changes it.

### Next action and authorization

M6's next deliverable is **Final Evaluation Data Readiness Confirmation** against the existing 80-candidate frame. The report must distinguish candidate IDs from acquired traces and give, per task, repository, acquisition/qualification state, Full Payload completeness, Explicit Token ID and sidecar availability, Prefill Profile availability, Native Replay feasibility, request/session order, token/context limits, and source/model/tokenizer provenance. It must propose 20 legal cross-repository groups, report repository coverage, and identify any gaps or right-censoring.

M6 is authorized to perform this data confirmation and the Agent-trace acquisition/validation needed to establish the proposed cohort **within the existing frozen 80-candidate frame**. This does not authorize Native Load Calibration, Noise Calibration, GPU Smoke, or the Main Campaign.

The separate Stage 3 Cohort Seal engineering milestone is not required. The final task membership, group pairing, request order, Native enqueue order, Replay Timeline, Session pairing and per-request History Predecessors must still be frozen in the final data/run manifest and SHA-256 bound before formal cells execute. This is a pre-run data freeze using the merged Stage 1/2 substrate, not another standalone engineering phase.

After M1 accepts M6's data-readiness report and M4 reconciles Protocol v3 with this decision, proceed directly to the Final Evaluation. The planned matrix remains six arms (N0/A0/A1/A2/A3/E0), 20 groups × 2 loads × 6 arms = 240 main runs, plus 40 A0 load-calibration and 30 A0 noise-calibration runs (310 total). PR #92's 3–5 GPU-hour estimate and 6-hour ceiling are planning estimates and must be reconfirmed against the actual qualified cohort.


## Research objective and decision layers

The project studies **cost-aware KV-cache eviction / victim selection on real vLLM 0.27.1 with GPU APC**. Retention and scheduling are supporting/baseline mechanisms, not a replacement for the eviction research question.

Current experimental arms must be distinguished by decision layer:

| Arm | Entry forced release | Physical block victim selection |
| --- | --- | --- |
| A0 | Frozen Continuum-style deterministic baseline | Native LRU under existing eligibility |
| A1 | Cost-aware entry-level selection | Same block-level baseline as A0 |
| A2 | A0 entry-level release | Cost-aware block-level selector |

`A2` is **not** an A1+A2 combined policy. A1-versus-A0 differences cannot by themselves establish the independent value of A1's q/λ/pair-lookahead signals. **Sufficient-first + earliest-deadline** remains a required strong comparator for any future formal claim.

## Phase status ledger

| Phase / evidence | Status | What is supported / what is not |
| --- | --- | --- |
| Phase 0 / 1A | CLOSED | Backend/adapter validation; native BlockPool retains refcounts, hashes, free-queue and eviction bookkeeping |
| Phase 1B | CLOSED | Continuum-style baseline integrated and real-runtime validated; project adaptation is not asserted byte-for-byte equivalent to the paper |
| Phase 2A H1 | CLOSED — `DIAGNOSTIC_ONLY` | 29 independent paired-evaluable draws, below threshold 30; no rule promotion; Phase 2C later identified content-topology fidelity limitations |
| Phase 2A H2 | CLOSED | M1/M2/M3 measurements passed their gates; M4 failed; aggregate did not unlock B1 |
| Phase 2B / 2C | CLOSED | Native evidence/fidelity repair and a workload audit; historical H1 artifacts remain sealed |
| Phase 2E | CLOSED | Frozen Native LRU/Continuum measured comparability campaign; outcome is workload/measurement evidence, not cost-aware benefit |
| Phase 2G A1 | BOUNDED EVALUATION COMPLETED | Native evidence of some beneficial entry-release differences; prior Gate 2 decision analysis found 54/54 A1 selections reproduced by simple sufficient-first heuristic; independent cost-model signal unproven |
| Phase 2G A2 | INCONCLUSIVE | Bounded evaluation found 0 better / 3 worse / 33 tied in 36 draws; attribution and decision exposure limitations; neither proof of universal equivalence nor formal benefit |
| Phase 2 W0 — PR #71 | CLOSED / `CONDITIONAL_GO` | Public Continuum/SWE-bench source and converter path audited; paper-run per-request trajectories absent |
| Phase 2 W1-A — PR #72 | CLOSED / `CONDITIONAL_GO` | 10 frozen SWE-bench Verified Agent tasks acquired; reported 453 model / 271 tool calls; 1 submitted, 9 right-censored at step limit; local tokenization and wrapper timing have explicit provenance |
| Phase 2 W1-B — PR #73 | **ACCEPTED / CLOSED — `BOUNDED_SMOKE_ONLY`** | M1 approved HEAD `4b902da` and merged as `fc9626da` (2026-10-23). M6 reports 4 groups × A0/A1/A2 = 12 successful runs; A1−A0 recompute delta −3904 tokens and A2−A0 zero. Limited descriptive/native comparability evidence; no formal effect or content-level causal attribution |
| Phase 2 W1-C | **ACCEPTED / CLOSED** | Cross-repository stratified sampling and the 20-task S50/S100 feasibility pilot completed; 18 full-payload-comparable task pairs fed the later bounded Native evaluation |
| Bounded Native Cost-Aware evaluation — PR #82 | **M1 ACCEPTED / CLOSED (2026-10-27)** | RTX 4090D campaign reports 54/54 successful Native runs over nine frozen groups; A1: 0 better / 1 worse / 8 tied, A2: 0 better / 3 worse / 6 tied. No observed A1/A2 recomputation-token benefit in this predefined grid. Exploratory single-repeat evidence; content-level causal attribution `NOT_ESTABLISHED`. External evidence archive handed to M4; no independent archive rehash in this M1 review. |

### W1-B closeout — M1 acceptance and evidence boundaries

[PR #73](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/73) was **M1 APPROVED** at HEAD `4b902da69c9da5c4e7f99d6c4be3040d3d017f9b` and **merged** into `main` as `fc9626da74e6f9b139f021d9b9b6c6a036857e39` on 2026-10-23. Review RC1–RC4 were closed within the **bounded Native comparability/mechanism smoke** scope:

- RC1: replay semantics reconciled to absolute planned-arrival offsets with a per-session completion barrier; zero enforced minimum post-completion gap. No original Agent timing-reproduction claim or raw-run rewrite.
- RC2: frozen-source and policy-independent cross-arm input/config binding; missing source/native digest bindings fail closed.
- RC3: forced-release exposure, subsequent Native hashed eviction and downstream request-observation availability gate the bounded mechanism status. Report explicitly labels **temporal association only**, with content-level causal attribution **NOT_ESTABLISHED**.
- RC4: trailing Native hash-chain exception narrowly scoped to supported W1-B exact-token/one-token conditions, with negative controls.

Reported bounded observations: **12/12 successful runs**, four selected groups with A0/A1/A2 and **one repeat per arm/group**. Per-group A1−A0 recomputed-token deltas: **−1056, 0, −1616, −1232** (descriptive sum **−3904**); A2−A0 is **zero in every group**, with no observed A2-vs-Native-LRU victim-set divergence. The submitted v2 evidence archive/report and 1536-test run were reported by M6; this M1 review did **not** independently rehash the external archive or rerun the raw 12 Native executions. Accepting W1-B does **not** establish a population benefit, superiority to Sufficient-first, individual physical-eviction causality, or reproduction of the Continuum paper's original serving workload.

**Historical next gates (as of W1-B acceptance, 2026-10-23):** W1-C acquisition and subsequent decision-discriminability work were pending at that time. W1-C and the later 54-run bounded evaluation are now completed and accepted as recorded above; no broader campaign has been authorized.

### Real Agent workload limitations

W0's first ten sampled tasks all came from Astropy and are not a cross-project representative cohort. W1-A captured real model/tool interactions but 9/10 trajectories were right-censored by the author's configured 50-step limit. W1-B replays selected sparse turns with controlled concurrency/pressure; it does **not** replay the original W1-A cross-session serving arrival process. Local deterministic token IDs, native submitted input, native APC hash identity and physical KV residency remain distinct evidence tiers.

W1-C completed the bounded 20-task S50/S100 feasibility pilot; 18 full-payload-comparable tasks entered the accepted 54-run Native evaluation. The replay remains controlled and sparse, not a reconstruction of the original serving arrival distribution. A broader ~100-task acquisition or a new algorithm campaign requires a separate M1 decision.

## Measurement and interpretation rules

For requests with complete native hash/APC evidence, let `N` = native prompt tokens, `E` = reusable eligible native-prefix tokens, `C` = native cached-prefix tokens. Enforce `0 ≤ C ≤ E ≤ N` and report separately:

- `R = E - C`: eligible-prefix recomputation;
- `W = N - C`: actual prefill work;
- `S = N - E`: genuinely new suffix; `W = R + S`.

Logical release, physical hashed eviction, subsequent APC hit/miss and request-level recomputation are different claims requiring different observations. If any required evidence is missing, preserve the missingness and fail closed. A short smoke is not an independently powered statistical campaign.

## Authority, ownership and next steps

- **M1**: phase grants, canonical status, architecture/fairness boundary, integration and final experimental verdicts.
- **M4**: holds the externally archived PR #82 evidence for follow-up A1/A2 decision-opportunity analysis, theory, strong-comparator interpretation, and next-method recommendation; not default workload acquisition owner.
- **M6**: current W0/W1 Agent-source acquisition, conversion, replay, native measurement and evidence statistics.
- **M5**: shared workload/runner substrate when a concrete interface gap requires work; not the owner of M6's W1 data acquisition.
- **M2/M3**: background/source-mechanism review and frozen baseline support, respectively.

Next decision: M6 completes the authorized Final Evaluation Data Readiness Confirmation within the existing W1-C candidate frame. M1 reviews the qualified 40-task / 20-group cohort and repository coverage (minimum 8). M4 synchronizes and reconciles Protocol v3 PR #90. Once both are accepted, proceed directly to the 310-run Final Evaluation; no separate Stage 3 Cohort Seal engineering phase is required. Native calibration and the formal GPU campaign remain unauthorized until that M1 go/no-go.

## Provenance and reading order

Read this file for **current state**, then use the [experiment navigation index](experiments/README.md) and sealed/final records for exact results:

- [Project README](../README.md) and [experimental framing](experiment-plan.md)
- [Phase 2A H1/H2 closeout](phase2a-h1-h2-closeout-verdict-record.md)
- [Phase 2E measured campaign](phase2e-m6-measured-campaign-report.md)
- [A1 evidence](experiments/phase2g-a1/README.md), [A2 bounded evaluation](experiments/phase2g-a2-bounded-value-evaluation.md), [A2 research judgment](experiments/phase2g-a2-research-judgment.md)
- [W0 source audit](continuum-workload-source-audit.md) and [conversion feasibility](continuum-workload-conversion-feasibility.md)
- [W0 PR #71](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/71), [W1-A PR #72](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/72), [W1-B PR #73 merged and accepted](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/73)
- [Bounded Native Cost-Aware evaluation results](continuum-native-cost-aware-bounded-results.md)

Historical plans, negative results, old approvals and sealed hashes are **not modified by this index**. When phase status changes, update this ledger in a new reviewable commit and link the M1-approved verdict.
