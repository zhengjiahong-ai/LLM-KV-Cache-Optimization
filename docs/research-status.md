# Research Status (M1 canonical status index)

Status: **ACTIVE — Phase 3 Protocol v4 / Option F frozen; G0 accepted; one-shot 270-run pipeline authorized; execution not yet started**  
As-of reconciliation: 2026-11-10, `main` @ `f005ecf239c1a982d0a751f430e24fa8ca47e46e`; [PR #99](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/99) merged; operative [M1 one-shot authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md).  
Owner: M1. This document indexes decisions and evidence; it does **not** amend sealed artifacts or replace their final reports.

## How to read the evidence

- **Campaign delivered / code merged** does not imply **hypothesis supported** or **formal algorithm benefit demonstrated**.
- `CLOSED` means a stage's accepted scope has concluded, not that every research hypothesis passed.
- `UNDER_REVIEW` means its submission, numbers and gate are **not yet M1 accepted**.
- `AUTHORIZED` means an explicitly bounded operation may start; it does not imply measurements have been collected.
- Unit of inference matters: independent scenario draws or independently sampled tasks/session groups, **not** runtime repeats, turns or request rows.
- No source-generated Agent trace is the author's original paper-run serving trace unless independently established.

## Current Phase 3 status (M1 reconciliation, 2026-11-10)

Current main: `f005ecf239c1a982d0a751f430e24fa8ca47e46e`.

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

### Execution state — do not infer readiness from authorization

As of main HEAD `f005ecf`, the repository contains the authorization but no execution ledger proving that the 270-run campaign has started or that a GPU allocation is reserved. M6 must record the pre-launch host, runner, GPU allocation, resource reservation, and frozen-hash verification before launch. Until such evidence is committed, the correct status is **AUTHORIZED / NOT STARTED**.

The current six-arm campaign is N0/A0/A1/A2/A3/E0. Its new-run budget is **270**, not 310: the 40-run A0 Load Calibration already exists and is reused. The Main grid is 20 Groups × C1/C2 × 6 arms = 240; the Noise stage is 5 Groups × C1/C2 × 3 repeats = 30.

See [Option F engineering status](experiments/phase3-option-f-engineering-status.md), the [operative one-shot authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md), and [mechanism coverage / claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

## Research objective and decision layers

The project studies **cost-aware KV-cache eviction / victim selection on real vLLM 0.27.1 with GPU APC**. The longer-term research hierarchy remains:

1. **Core research:** cost-aware KV eviction and victim selection.
2. **Supporting cache mechanism:** retention / protection, including the Continuum-style Entry Release path.
3. **System coordination:** scheduling.

The Phase 3 campaign evaluates two distinct decision layers. Entry Release changes which cached entries become eligible; physical Block Victim Selection chooses among eligible Native blocks. They must not be collapsed into one generic “eviction algorithm” when attributing effects.

| Arm | Entry forced-release policy | Physical block-victim policy | Interpretation |
| --- | --- | --- | --- |
| N0 | No-op; no forced Entry Release | Native LRU | No-forced-release control; pressure requests, barriers, timeline, APC and Native scheduler remain active |
| A0 | Frozen project-side Continuum-style Entry Release | Native LRU | Continuum-style Entry Release baseline; not a complete public-paper reproduction |
| A1 | Frozen Cost-Aware Entry Release | Native LRU | Changes the Entry Release decision relative to A0 |
| A2 | Same frozen A0 Entry Release | Cost-Aware block selector | Changes only physical victim selection relative to A0 |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Tests the suffix-cost Entry decision path |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator for the cost-aware Step 2 |

A2 is **not** an A1+A2 combined policy. A1/A3/E0 operate at the Entry Release layer; A2 operates at the physical block-victim layer. The primary metric is aggregate recomputed tokens, `Σ(E-C)`, with independently derived `N`, `E`, and `C`. E must never be completed from C.

The registered H3-0 contrast is **A0 − N0** over every Headroom-qualified cell (20 Groups / 38 cells); H3-R is a separate RESPONSIVE-only contrast (9 Groups / 16 cells). This measures the incremental effect of the frozen forced-Entry-Release path against the no-forced-release control under the shared Native scheduler and Native LRU/APC path. It is **not** a full Continuum-versus-Vanilla-vLLM system comparison.

Dynamic TTL inputs and decisions are observable through the lifecycle evidence, but there is no Static-TTL arm; therefore Phase 3 cannot independently estimate Dynamic TTL's advantage over Static TTL. Likewise, the Phase 3 arms all use Native scheduling; the program-level scheduler's performance effect is not estimated by this campaign. Phase 1B separately implemented and real-runtime validated the narrow program-level admission-order adaptation. See [mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

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
| Phase 3 Option F — PR #99 / Protocol v4 | **ACTIVE — G0 ACCEPTED; 270-RUN PIPELINE AUTHORIZED / NOT STARTED** | G0 v3 binds 40 tasks / 20 Groups / 10 repositories and the existing 40-run A0 calibration. The one-shot pipeline is 30 Noise + conditional 240 Main. No result or readiness claim until M6 commits execution evidence. |

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
