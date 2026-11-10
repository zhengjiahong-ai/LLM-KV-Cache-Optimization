# Experiment and Decision Index

This is a **navigation index**, not a replacement for primary evidence, historical final reports, or M1 approvals. For live stage authorizations, read [the canonical status ledger](../research-status.md). Historical reports retain their original scope and outcomes; later results do not retroactively rewrite them.

## Reading order

| Topic | Recommended record | Reading boundary |
| --- | --- | --- |
| Overall status and current authorization | [Research status](../research-status.md) | Protocol v4 / Option F frozen; G0 accepted; one-shot 270-run pipeline authorized but not started; Main is conditional on the automatic Noise gate |
| Phase 2A H1/H2 original verdicts | [H1/H2 closeout](../phase2a-h1-h2-closeout-verdict-record.md) | H1 `DIAGNOSTIC_ONLY`; H2 not all-pass, B1 locked |
| Phase 2B/2C fidelity lessons | [Phase 2B fidelity repair](../phase2b-m6-experimental-fidelity-repair-spec.md), [Phase 2C audit](../phase2c-m6-workload-reuse-audit.md) | Separate replay fidelity from real Native content sharing and context growth |
| Phase 2E baseline measurements | [Measured campaign](../phase2e-m6-measured-campaign-report.md) | Native LRU vs Continuum baseline on predefined synthetic grid, **not** A1 benefit |
| A1 initial algorithm/offline selection | [A1 original report](phase2g-a1/README.md) | Historical offline-only scope; its “no Native validation” and “next steps” date from that stage |
| A1 Native Gate 2 evidence/metric qualification | [Gate 2 review](phase2g-gate2-review/README.md), [canonical status](../research-status.md) | Reported 12 BETTER / 1 WORSE / 22 TIED / 1 INCONCLUSIVE; corrected-metric and simple-rule discrimination caveats apply |
| A2 original algorithm definition | [A2 algorithm/interface](phase2g-a2-algorithm/README.md) | Historical algorithm-layer-only scope; native integration occurred *later* |
| A2 Gate 2 v3 | [Gate 2 v3 final report](phase2g-a2-gate2-v3/final-report.md) | Complete run execution but 72/72 selection pairs `NOT_OBSERVABLE`; zero token difference does not prove equal decisions |
| A2 bounded Native value and later corrections | [Bounded evaluation](phase2g-a2-bounded-value-evaluation.md), [research judgment](phase2g-a2-research-judgment.md) | 0 BETTER / 3 WORSE / 33 TIED; limited content-level divergence and causal attribution |
| W0 source audit | [Continuum workload source audit](../continuum-workload-source-audit.md) | Original paper's complete trajectories are **not** public in audited repo |
| W1-A real Agent acquisition | [PR #72](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/72), [status](../research-status.md) | 10 acquired tasks, mostly right-censored; local tokenizer/wrapper provenance is not Native APC evidence |
| W1-B Native bounded smoke | [PR #73](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/73) | **ACCEPTED / CLOSED** (M1 approved, merged 2026-10-23 as `fc9626da`); 12-run bounded comparability/mechanism smoke only; deltas remain descriptive, not formal performance effects or content-level causal attribution |
| W1-C expanded Agent workload | [Research status](../research-status.md) | Bounded S50/S100 pilot completed and accepted; 18 comparable tasks used for the subsequent Native evaluation; full ~100-task acquisition not authorized |
| Bounded Native Cost-Aware evaluation | [Final execution report](../continuum-native-cost-aware-bounded-results.md), [PR #82](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/82) | **M1 ACCEPTED / CLOSED (2026-10-27)**; 54/54 runs reported successful; A1 0/1/8 and A2 0/3/6 better/worse/tied across nine groups; no observed improvement; external archive handed to M4 |

## Phase 3 Final Evaluation

| Topic | Primary record | Current reading boundary |
| --- | --- | --- |
| M1 canonical status | [Research status](../research-status.md) | Current as of 2026-11-10; main @ f005ecf; G0 accepted; 270-run pipeline authorized / not started |
| Frozen final protocol | [Protocol v4 — Option F](../phase3-final-evaluation-protocol-v4.md) | Current protocol; fixed operating points, estimands, populations, Noise estimator, and gates are frozen. Protocol v3 is historical. |
| G0 review bundle | [G0 v3 README](phase3-option-f-g0-v3/README.md) | Accepted by M1 on 2026-11-07; 40 tasks / 20 Groups / 10 repositories; 40-run A0 calibration evidence reused. The bundle's execution_authorized=false is its original freeze state, not the later M1 authorization. |
| Option F engineering | [Engineering status](phase3-option-f-engineering-status.md), [PR #99](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/99) | Merged; G0 v3 accepted; existing A0 calibration reused; no new GPU run performed by the engineering PR. |
| Operative execution authorization | [One-shot 270-run authorization](phase3-option-f-270-run-pipeline-authorization.md) | 30 A0 Noise runs, then 240 Main runs only after machine-verified transition gate; one compute window; no intermediate manual M1 review. |
| Earlier continuous-execution decision | [Intermediate authorization record](phase3-option-f-continuous-execution-authorization.md) | Retained as decision history; the one-shot 270-run amendment is the operative execution contract. |
| Mechanism coverage | [Phase 3 mechanism coverage and claim boundaries](phase3-mechanism-coverage-and-claim-boundaries.md) | Separates TTL observability, forced-release effect, physical victim selection, and scheduler validation; prevents full-Continuum or scheduler-effect overclaims. |
| Final reporting structure | [Phase 3 final report outline](../phase3-final-report-outline.md) | Pre-registered report structure and evidence checklist; contains no campaign results. |
| Current execution state | [Research status](../research-status.md) | No committed pre-launch host/runner/GPU reservation or 270-run start record at current main HEAD. Do not infer readiness from authorization. |

The accepted G0 cohort contains 40 qualified tasks in 20 Workload Groups across 10 repositories. The existing 40-run A0 Load Calibration is reused and must not be rerun. The new execution budget is **270 runs**: 30 A0 Noise Calibration + 240 six-arm Main Campaign. Main is conditionally pre-authorized and may start only after the frozen Noise evaluator and every applicable mandatory transition condition pass.

## Phase 3 arm mapping

- **N0**: no-op forced Entry Release; pressure requests, barriers, replay timeline, Native LRU/APC and Native scheduler remain active.
- **A0**: frozen project-side Continuum-style Entry Release + Native LRU.
- **A1**: Cost-Aware Entry Release + Native LRU.
- **A2**: A0 Entry Release + Cost-Aware physical block-victim selector.
- **A3**: suffix-cost-aware Entry Release + Native LRU.
- **E0**: A1 branch ladder with deadline-only Step 2 + Native LRU.

A1/A3/E0 are Entry Release policies; A2 changes physical block selection. A2 is not an A1+A2 combination. The registered A0−N0 H3-0/H3-R contrasts test the forced-release path against the no-forced-release control, not a complete Continuum-versus-Vanilla-vLLM system comparison.

The frozen M6 feasibility report and G0 require **at least ten repositories**. The accepted G0 cohort meets the 40-task / 20-Group / 10-repository requirement. The historical 18 W1-C pilot tasks remain excluded from formal Phase 3 effect estimates.

## Interpret the three algorithm layers correctly

- **A0**: frozen project-side Continuum-style **Entry Release** plus Native LRU **block victim**.
- **A1**: Cost-Aware **Entry Release** with A0's Native LRU block selection.
- **A2**: A0 Entry Release with Cost-Aware **physical block-victim selection**.
- **A3**: suffix-cost-aware Entry Release with Native LRU block selection.
- **E0**: A1 branch ladder with deadline-only Step 2 and Native LRU block selection.
- **N0**: no-op forced Entry Release control; the pressure path remains active.

These are not three implementations of the same choice layer; A2 is not a joint A1+A2 policy. Sufficient-first plus earliest-deadline is a needed strong comparator before claiming the standalone value of A1's scoring model.

## Evidence/claim guardrails

Native input identity, logical retention release, Native hashed block eviction, APC eligibility, residency, and recomputed tokens are separate evidence tiers. When Native Level-B evidence is complete, `N` = prompt tokens, `E` = eligible reusable prefix, `C` = cached prefix, `R = E - C`, `W = N - C`, `S = N - E`.

Do not pool turns or repeated runtime runs as independent sample draws. Do not cite early offline reports as though they prove physical benefit. Do not claim a production or original Continuum serving distribution from synthetic arrivals or sparse-turn replay. Phase 3 records TTL inputs/decisions but has no Static-TTL arm; it therefore does not estimate Dynamic TTL versus Static TTL. All Phase 3 arms use the Native scheduler; the program-level scheduler's performance effect is not estimated. The Phase 1B scheduler implementation/validation is separate evidence.

## Preservation

This index links to historical experiments; it **does not** migrate or rewrite sealed raw evidence, SHA manifests, frozen statistical verdicts, or archived negative results. Review the [canonical status ledger](../research-status.md) before updating any “current” status elsewhere.
