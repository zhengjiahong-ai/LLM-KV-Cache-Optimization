# Phase 2 Research Status (M1 canonical status index)

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

Next decision: M4 may analyze the already transferred bounded evidence and propose one targeted follow-up study. Any algorithm redesign, new data acquisition, or new Native campaign requires separate M1 authorization and a pre-registered comparison. Do not retune the frozen A1/A2 against the just-observed results; no A3/B1 authorization is implied.

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
