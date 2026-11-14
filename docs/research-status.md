# Research Status (M1 canonical status index)

Status: **UNDER REVIEW — Phase 3 Option F execution complete; 270/270 runs reconciled; final M1 adjudication pending**
As-of execution: 2026-11-12, execution code `00a512111f15abddcad329572f6e50ccaaa76775`; [final M6 results](experiments/phase3-option-f-final-results.md); immutable evidence archive SHA-256 `d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`.
Owner: M1. This document indexes decisions and evidence; it does **not** amend sealed artifacts or replace their final reports.

## Research synthesis (R1.3, 2026-11-14; M4 review incorporated)

The revised cross-phase synthesis is available in [Research Results and Contributions](research-consolidation/research-results-and-contributions.md). It incorporates M4's independent review: Phase 4 right-censoring and weak TOOL_GAP proxy results, Phase 2C APC hit distribution, P2 fail-closed exclusions, exact A0 ordering, Phase 3 decision-layer / cell-clustering corrections, and explicit campaign-estimand boundaries. The [R1 evidence ledger](research-consolidation/r1-experiment-evidence-ledger.md) remains the navigation and provenance layer.

**Status boundary:** this synthesis is an M1 working draft, not the final Phase 3 verdict. The 270-run Option F execution and actual-order read-only recovery are complete, but the frozen enqueue-order deviation remains recorded and final M1/M4 adjudication is pending. No new GPU run, Native smoke, algorithm implementation, or Protocol v5 is authorized by this documentation update.

## How to read the evidence

- **Campaign delivered / code merged** does not imply **hypothesis supported** or **formal algorithm benefit demonstrated**.
- `CLOSED` means a stage's accepted scope has concluded, not that every research hypothesis passed.
- `UNDER_REVIEW` means its submission, numbers and gate are **not yet M1 accepted**.
- `AUTHORIZED` means an explicitly bounded operation may start; it does not imply measurements have been collected.
- Unit of inference matters: independent scenario draws or independently sampled tasks/session groups, **not** runtime repeats, turns or request rows.
- No source-generated Agent trace is the author's original paper-run serving trace unless independently established.

## Phase 3 status snapshot (historical M1 reconciliation, 2026-11-10)

Historical snapshot recorded at that review: `f005ecf239c1a982d0a751f430e24fa8ca47e46e`.

**Current repository main as checked 2026-11-14:** `18a0a9198403af735350cbbfd9aae20e7b2b39bd`. The historical hash above is retained as a dated snapshot, not presented as current main. The R1 research branch and PR #108 contain subsequent Phase 3/4 research and synthesis work; these have not all been integrated into main.

| Record / PR | Delivered scope | Current state | Boundary |
| --- | --- | --- | --- |
| [PR #90](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/90) | Protocol v3 | **MERGED / FROZEN — HISTORICAL** | Superseded for the final Option F campaign by Protocol v4. Preserve v3 as immutable design history. |
| [PR #92](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/92) | Workload and execution feasibility | **MERGED** | Feasibility and sampling frame; not itself proof of formal run execution. |
| [PR #93](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/93) | Six-arm Materializer, N0/E0 integration | **MERGED — STAGE 1 COMPLETE** | CPU/Mock and materialization validation; not GPU campaign evidence. |
| [PR #94](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/94) | Independent N/E/C Evaluator | **MERGED — STAGE 2 COMPLETE** | RC1–RC4 closed; E is independently derived from Native evidence, not completed from C. |
| Issue #98 / Option F | Final fixed-pressure design adaptation | **ACCEPTED by M1** | Protocol v4 is a separate frozen document; it does not amend v3 in place. |
| [PR #99](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/99) | Final Option F engineering adaptation and G0 v3 | **MERGED** as `a7fe138354720412b393ac584e8d1d6ed8cd4709` | Accepted implementation HEAD `6f77f7178d366a259e14285469f9419e05afaa5f`; G0 v3 accepted by M1 on 2026-11-07. |
| [Protocol v4](phase3-final-evaluation-protocol-v4.md) | Option F estimands, fixed operating points, noise estimator, gates | **FROZEN** | Do not change estimands, populations, thresholds, run grid, or gate meanings during execution. |
| [G0 v3 bundle](experiments/phase3-option-f-g0-v3/README.md) | Cohort Seal, 40-run A0 calibration evidence, plans, inputs, hashes | **ACCEPTED by M1** | The bundle's `execution_authorized=false` records its original freeze state. The separate M1 addendum is the execution authority. |
| [One-shot 270-run authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md) | 30 Noise + conditional 240 Main in one compute window | **AUTHORIZED** | Main starts only after the machine-verified Noise transition gate passes; no intermediate manual M1 review. |

### Frozen cohort and calibration evidence

The accepted G0 v3 bundle binds:

- **40 qualified tasks**, arranged into **20 Workload Groups**;
- **10 repositories** represented in the sealed cohort;
- the Cohort Seal SHA-256 and the matching 20 Group IDs;
- the existing **40-run A0 Load Calibration**, its 40 reports, Native evidence, execution summary, and analysis archive;
- the fixed C1/C2 conditions, six-arm Main Plan, 30-run Noise Plan, input manifests, Protocol v4, and M1 authorization bindings.

The existing A0 Load Calibration is reused. It is not a new stage in the 270-run budget and must not be rerun. The 18 historical W1-C comparable pilot tasks remain excluded from formal Phase 3 effect estimates.

### Current execution authorization

M1's 2026-11-09 amendment authorizes one continuous compute window:

| Stage | Runs | Authorization |
| --- | ---: | --- |
| A0 Noise Calibration | 30 | Authorized immediately under the frozen Noise Plan and input manifest |
| Main Campaign | 240 | Pre-authorized conditionally; starts only if the machine-verified transition gate passes |
| **Total new runs** | **270** | One-shot pipeline; no intermediate manual M1 approval |

The controller must reconcile all 30 Noise Run IDs, run the independent Protocol v4 Noise Evaluator, persist the pooled `sigma_run`, `sigma_delta`, and tied threshold, evaluate all applicable mandatory gates, and verify every frozen hash binding before dispatching Main. Any missing/invalid evidence, undefined required pooled value, mandatory gate failure, or hash mismatch stops the pipeline before Main.

The original G0 v3 manifest intentionally remains immutable with `execution_authorized=false`. The separate M1 one-shot amendment is the operative execution authority; do not rewrite the G0 manifest to make it appear that authorization existed at freeze time.

### Execution state

M6 reports the one-shot pipeline **COMPLETE**: 30/30 Noise and 240/240 Main runs, automatic transition `MAIN_AUTHORIZED_BY_PIPELINE`, and all 270 result identities reconciled. Noise passed with `sigma_run = sigma_delta = tied threshold = 0`. Main found A1/A2/A3/E0 tied with A0 on aggregate recomputed tokens, while N0 recomputed more than A0. These are submitted results pending final M1/M4 evidence adjudication, not yet an M1-accepted final verdict.

The current six-arm campaign is N0/A0/A1/A2/A3/E0. Its new-run budget is **270**, not 310: the 40-run A0 Load Calibration already exists and is reused. The Main grid is 20 Groups × C1/C2 × 6 arms = 240; the Noise stage is 5 Groups × C1/C2 × 3 repeats = 30.

See [Option F engineering status](experiments/phase3-option-f-engineering-status.md), the [operative one-shot authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md), and [mechanism coverage / claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

## Research objective and decision layers

### Project objective

The project investigates **cost-aware optimization of a Continuum-style, program-aware KV cache management adaptation on vLLM 0.27.1**. The Continuum-style adaptation is the system foundation; cost-aware policy design is the optimization direction.

The project is organized around four related but non-interchangeable layers:

1. **Program-aware cache lifecycle:** program/session identity, tool-gap and reuse history, dynamic TTL, and retention protection.
2. **Entry Release under pressure:** deciding which logically retained cache entry should be released so its blocks become eligible.
3. **Physical Block Victim Selection:** choosing which eligible Native KV blocks are actually evicted by the vLLM cache path.
4. **Program-level scheduling:** a narrow Continuum-style admission-order adaptation, implemented and real-runtime validated in Phase 1B.

Entry Release is not physical eviction. Releasing a protected entry changes eligibility; Native vLLM still performs physical block eviction and owns BlockPool bookkeeping.

### Current Phase 3 policy map

| Arm | Entry Release policy | Physical block-victim policy | Role in the Continuum-style optimization study |
| --- | --- | --- | --- |
| N0 | No forced Entry Release | Native LRU | Control for the incremental forced-release path |
| A0 | Frozen project-side Continuum-style Entry Release | Native LRU | Adapted Entry Release baseline |
| A1 | Cost-Aware Entry Release | Native LRU | Cost-aware change at the Entry Release layer |
| A2 | Same frozen A0 Entry Release | Cost-Aware block selector | Cost-aware change at the physical victim layer |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Alternative cost-aware Entry Release candidate |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator for A3 |

A2 is not an A1+A2 combined policy. A1/A3/E0 change Entry Release; A2 changes physical block selection. The main outcome remains aggregate recomputed tokens, Σ(E−C), with N, E, and C independently derived.

### What the formal campaign can establish

- **A0 − N0 (H3-0 / H3-R):** the incremental effect of the frozen forced Entry Release path against no forced Entry Release, under shared Native LRU/APC and Native scheduling.
- **A1 − A0 / A3 − A0:** the incremental effect of the registered Entry Release policy variants.
- **A2 − A0:** the incremental effect of cost-aware physical block-victim selection while retaining A0 Entry Release.
- **A3 versus E0:** whether the suffix-cost model produces the registered level of robustly discriminable decisions beyond the deadline-only comparator.

These are component-level contrasts within the project-side Continuum-style cache-management adaptation. They are **not** a full-system comparison of the original Continuum paper against untouched Vanilla vLLM.

### Mechanisms present but not causally evaluated in Phase 3

- **Dynamic TTL:** its history inputs, selected values, and deadlines can be inspected through lifecycle evidence. There is no Static-TTL arm, so the campaign does not estimate Dynamic TTL versus Static TTL.
- **Program-level scheduling:** the narrow adapter was implemented and real-runtime validated in Phase 1B. All Phase 3 arms use the Native scheduler, so this campaign does not estimate the scheduler's performance contribution.

The Phase 1B baseline adaptation is not an exact source-level reproduction of Continuum. The current Phase 3 claims must remain limited to the frozen protocol, evaluated decision layers, workload, and evidence. See [Research Motivation and Contributions](research-motivation-and-contributions.md) for the canonical project narrative.

## Potential future research directions — research reserve only

M1 has accepted M2's four proposals for preservation as potential future research directions:

1. **Evidence-aware Block intervention** — decide when a validated cost-aware selector should replace the actual Native-LRU victim set.
2. **Workflow-aware Block signals** — test whether online lifecycle signals add value beyond the TTL-derived deadline proxy.
3. **Downstream-cost-aware Entry Release** — evaluate release order through the actual downstream physical victim set and recomputation loss.
4. **Partial-tail Entry unpinning** — investigate range-level protection while preserving shallow reusable prefixes.

These directions are **not part of Phase 3 Protocol v4**, do not create experimental arms, and do not authorize implementation, new data acquisition, smoke tests, or GPU runs. Current priority remains the already-authorized one-shot 270-run pipeline and its independent analysis. Any follow-on work requires a separate M1 decision, available time, and a study-specific frozen protocol. See [Potential Future Research Directions](future-research-directions.md) for the consolidated research agenda.

## Post-Phase-3 staged experimental roadmap — planning only

M1 has recorded a proposed three-stage research sequence in [Post-Phase-3 Experimental Roadmap](post-phase3-experimental-roadmap.md): (1) complete and adjudicate the frozen Phase 3 controlled component campaign; (2) use accepted results for Phase 4 diagnosis and algorithm development; and (3) conduct a separate Phase 5 full-system comparison on an independent, more representative Agent workload cohort.

The proposed Phase 5 comparison has four primary systems: Native vLLM, the authors' Continuum Official Public Implementation, the project's A0-derived full-system Continuum-style adaptation, and the Phase 4 frozen Cost-Aware candidate. The roadmap explicitly distinguishes Phase 3 A0 from an A0-derived full-system configuration with the project scheduler enabled, and it preserves the official repository's stated limitation that its public code does not include the paper's estimator.

**This is a planning decision only.** It does not change Phase 3 Protocol v4, G0, the 270-run authorization, or the current execution priority. Phase 4/5 implementation, new data acquisition, GPU runs, and final system definitions each require separate M1 approval and a study-specific frozen protocol.

## Phase status ledger

| Phase / evidence | Status | What is supported / what is not |
| --- | --- | --- |
| Phase 0 / 1A | CLOSED | Backend/adapter validation; native BlockPool retains refcounts, hashes, free-queue and eviction bookkeeping |
| Phase 1B | CLOSED | Continuum-style baseline integrated and real-runtime validated; project adaptation is not asserted byte-for-byte equivalent to the paper |
| Phase 2A H1 | CLOSED — `DIAGNOSTIC_ONLY` | 29 independent paired-evaluable draws, below threshold 30; no rule promotion; Phase 2C later identified content-topology fidelity limitations |
| Phase 2A H2 | CLOSED | M1/M2/M3 measurements passed their gates; M4 failed; aggregate did not unlock B1 |
| Phase 2B / 2C | CLOSED | Native evidence/fidelity repair and workload audit; among 495 eligible turn prefixes, 288 full hits / 48 partial hits / 159 misses; 408 first eligible predecessors are no-prior-eligible-prefix, not misses. Different-program first hash chains matched 0/771 in the audited H1 workload; this is workload-specific, not universal |
| Phase 2E | CLOSED | Frozen Native LRU/Continuum measured comparability campaign; outcome is workload/measurement evidence, not cost-aware benefit |
| Phase 2G A1 | BOUNDED EVALUATION COMPLETED; token verdict remains PROVISIONAL | W1-B's four-group smoke had descriptive A1−A0 reductions only; PR #82's separate nine-group bounded evaluation found 0 better / 1 worse / 8 tied (mean +412.44 tokens), Phase 2H's sole A1 divergence increased recomputation by 6,320 tokens, and Phase 3 showed no A1/A0 difference with sparse two-candidate exposure. No independent A1 benefit is demonstrated; historical Gate 2 token values remain provisional pending corrected same-archive evaluation |
| Phase 2G A2 | INCONCLUSIVE | Bounded evaluation found 0 better / 3 worse / 33 tied in 36 draws; attribution and decision exposure limitations; neither proof of universal equivalence nor formal benefit |
| Phase 2 W0 — PR #71 | CLOSED / `CONDITIONAL_GO` | Public Continuum/SWE-bench source and converter path audited; paper-run per-request trajectories absent |
| Phase 2 W1-A — PR #72 | CLOSED / `CONDITIONAL_GO` | 10 frozen SWE-bench Verified Agent tasks acquired; reported 453 model / 271 tool calls; 1 submitted, 9 right-censored at step limit; local tokenization and wrapper timing have explicit provenance |
| Phase 2 W1-B — PR #73 | **ACCEPTED / CLOSED — `BOUNDED_SMOKE_ONLY`** | M1 approved HEAD `4b902da` and merged as `fc9626da` (2026-10-23). M6 reports 4 groups × A0/A1/A2 = 12 successful runs; A1−A0 recompute delta −3904 tokens and A2−A0 zero. Limited descriptive/native comparability evidence; no formal effect or content-level causal attribution |
| Phase 2 W1-C | **ACCEPTED / CLOSED** | Cross-repository stratified sampling and the 20-task S50/S100 feasibility pilot completed; 18 full-payload-comparable task pairs fed the later bounded Native evaluation |
| Bounded Native Cost-Aware evaluation — PR #82 | **M1 ACCEPTED / CLOSED (2026-10-27)** | RTX 4090D campaign reports 54/54 successful Native runs over nine frozen groups; A1: 0 better / 1 worse / 8 tied, A2: 0 better / 3 worse / 6 tied. No observed A1/A2 recomputation-token benefit in this predefined grid. Exploratory single-repeat evidence; content-level causal attribution `NOT_ESTABLISHED`. External evidence archive handed to M4; no independent archive rehash in this M1 review. |
| Phase 3 Option F — PR #99 / Protocol v4 | **UNDER REVIEW — 270/270 COMPLETE** | Noise 30/30 and Main 240/240 completed. Frozen enqueue order failed in 32/40 cells, but all six arms shared the same actual order in every cell; a read-only actual-order audit independently recovered unchanged E for 5,760/5,760 request-arm observations and exactly reproduced the fixed-population effects. A0 outperformed N0 on recomputation; A1/A2/A3/E0 showed zero incremental effect versus A0. The replay-conformance deviation remains recorded; final M1/M4 adjudication is pending. |

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

- **M1**: phase grants, canonical status, protocol freeze, architecture/fairness boundary, documentation authority, and final experimental verdicts.
- **M4**: frozen Protocol v4 semantics and post-campaign effect/statistical analysis. No routine protocol redesign is authorized.
- **M6**: pre-launch compute-window preparation, 270-run execution, automatic Noise-to-Main transition, Native evidence, independent evaluator outputs, execution statistics, and immutable evidence archive.
- **M5**: shared workload/runner substrate only if a concrete interface gap remains.
- **M2/M3**: background/source-mechanism review and frozen baseline support.

**Immediate next action:** M6 records the pre-launch execution host, runner, GPU allocation, 270-run resource reservation, and all frozen-hash checks. It then executes the already-authorized one-shot pipeline exactly as specified. No additional smoke, load-calibration rerun, cohort replacement, parameter tuning, or protocol change is authorized. The automatic transition gate controls whether the 240-run Main stage may start. After collection, M4 performs the registered analysis and M1 reviews the complete evidence before any final research claim.

The authorization does not establish that the compute window is ready, that any GPU run has started, or that the Main stage is unconditionally authorized.

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
