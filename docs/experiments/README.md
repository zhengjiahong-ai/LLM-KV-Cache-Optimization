# Phase 2 Experiment and Decision Index

This is a **navigation index**, not a replacement for primary evidence, historical final reports, or M1 approvals. For live stage authorizations, read [the canonical status ledger](../research-status.md). Historical reports retain their original scope and outcomes; later results do not retroactively rewrite them.

## Reading order

| Topic | Recommended record | Reading boundary |
| --- | --- | --- |
| Overall status and current authorization | [Research status](../research-status.md) | PR #73/W1-B ACCEPTED and merged at `fc9626da`; W1-C remains bounded pilot only |
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
| W1-C expanded Agent workload | [Current authorization](../research-status.md) | Sampling design plus S50/S100 feasibility pilot; full ~100-task acquisition **not authorized** |
| Bounded Native Cost-Aware evaluation | [Final execution report](../continuum-native-cost-aware-bounded-results.md) | 54/54 runs complete; A1 0/1/8 and A2 0/3/6 better/worse/tied across nine groups; pending M1 result review |

## Interpret the three algorithm layers correctly

- **A0**: Continuum-style frozen **entry release** plus Native LRU **block victim**.
- **A1**: Cost-Aware **entry release** with A0's Native LRU block selection.
- **A2**: A0 entry release with Cost-Aware **block victim selection**.

These are not three implementations of the same choice layer; A2 is not a joint A1+A2 policy. Sufficient-first plus earliest-deadline is a needed strong comparator before claiming the standalone value of A1's scoring model.

## Evidence/claim guardrails

Native input identity, logical retention release, Native hashed block eviction, APC eligibility, residency, and recomputed tokens are separate evidence tiers. When Native Level-B evidence is complete, `N` = prompt tokens, `E` = eligible reusable prefix, `C` = cached prefix, `R = E - C`, `W = N - C`, `S = N - E`.

Do not pool turns or repeated runtime runs as independent sample draws. Do not cite early offline reports as though they prove physical benefit. Do not claim a production or original Continuum serving distribution from synthetic arrivals or sparse-turn replay.

## Preservation

This index links to historical experiments; it **does not** migrate or rewrite sealed raw evidence, SHA manifests, frozen statistical verdicts, or archived negative results. Review the [canonical status ledger](../research-status.md) before updating any “current” status elsewhere.
