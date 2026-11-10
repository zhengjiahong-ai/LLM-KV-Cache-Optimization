# Phase 3 Mechanism Coverage and Claim Boundaries

**Status:** M1 reporting reference for the frozen Phase 3 Option F campaign.  
**As of:** 2026-11-10  
**Authority:** Protocol v4, G0 v3, and the one-shot 270-run authorization.

This document explains what the completed Phase 1B baseline work established, what the current 270-run Phase 3 campaign measures, and which claims remain outside its design. It is an interpretation guide; it does not amend the frozen protocol, estimands, cohort, manifests, or execution authorization.

## 1. Research hierarchy

The project has three related but distinct layers:

1. **Cost-aware KV eviction / victim selection** — the central research objective.
2. **Retention / protection** — supporting cache mechanism, including the project-side Continuum-style Entry Release path.
3. **Program-level scheduling** — system coordination required by the Continuum-style baseline.

Entry Release and physical Block Victim Selection are separate decisions. Releasing a protected entry changes which blocks become eligible; it does not itself perform Native block eviction.

## 2. What Phase 1B established

Phase 1B implemented and real-runtime validated a project-side Continuum-style baseline adapted to vLLM 0.27.1. Its validated scope includes:

- explicit Program / Session identity and lifecycle events;
- tool-gap and server inter-request-gap history;
- dynamic TTL estimation and PrefillReload inputs;
- soft retention protection and lazy expiry;
- deterministic pressure-driven Entry Release;
- a narrow program-level admission-order scheduling adapter;
- the existing Native APC / BlockPool allocation and eviction path.

The scheduler adapter was exercised at the controlled Native Request boundary in the Phase 1B real-runtime validation. This is engineering/integration evidence for the adaptation. It is not a formal estimate of scheduling-performance benefit, nor a claim of byte-for-byte reproduction of the public Continuum system.

See Baseline Freeze, Continuum Baseline Implementation, and the Phase 1B final report.

## 3. What the Phase 3 six-arm campaign changes

The 240-run Main Campaign compares six policies on the same frozen workload, conditions, request order, replay timeline, model/runtime identity, and pressure inputs.

| Arm | Entry Release | Physical Block Victim | Role |
| --- | --- | --- | --- |
| N0 | No-op; no forced Entry Release | Native LRU | No-forced-release control |
| A0 | Frozen project-side Continuum-style Entry Release | Native LRU | Internal Continuum-style Entry Release baseline |
| A1 | Cost-Aware Entry Release | Native LRU | Entry-level cost-aware policy |
| A2 | Same frozen A0 Entry Release | Cost-Aware block selector | Block-level victim-selection policy |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Suffix-cost entry policy |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator |

A2 is not an A1+A2 combined policy. A1/A3/E0 modify the Entry Release choice; A2 modifies the physical block-victim choice. All Phase 3 arms retain the **Native vLLM scheduler**.

## 4. What the registered contrasts can establish

### 4.1 Forced Entry Release: A0 versus N0

Protocol v4 registers:

- **H3-0:** A0 − N0 over every Headroom-qualified cell: 20 Groups / 38 cells.
- **H3-R:** A0 − N0 over the RESPONSIVE subset: 9 Groups / 16 cells.

N0 preserves the pressure request, boundary, replay timeline, pressure barrier, Native LRU/APC path, and Native scheduler, but performs no forced Entry Release. A0 uses the frozen project-side Continuum-style Entry Release with Native LRU block selection.

These contrasts estimate the incremental effect of the frozen forced-Entry-Release path under the shared Native scheduler and Native LRU/APC path. They do **not** compare a complete Continuum system against untouched Vanilla vLLM, and they do not isolate every individual internal subcomponent of Retention.

### 4.2 Entry Release and physical victim selection

- **A1 − A0:** incremental effect of replacing A0's Entry Release choice with the frozen Cost-Aware Entry Release, while retaining Native LRU block selection.
- **A2 − A0:** incremental effect of replacing Native LRU physical victim selection with the Cost-Aware block selector, while retaining the same A0 Entry Release.
- **A3 − A0:** effect of the suffix-cost-aware Entry Release policy relative to A0; interpretation must preserve the registered A3 branch/fallback composition.
- **E0 − A0:** deadline-only Step 2 comparator within the registered A1-style branch ladder.
- **A3 versus E0:** the registered cost-model discriminability comparison. A3/E0 differences must be counted only under the exact Protocol v4 G3-CM definition; an insufficient number of robust discriminable decisions yields NOT_EVALUABLE, not a claim of equivalence.

The primary metric remains aggregate recomputed tokens, Σ(E-C). N, E, and C are independently established. Logical Entry Release, Native physical eviction, later APC status, and recomputed tokens remain separate evidence tiers.

## 5. Dynamic TTL: observable, but not independently randomized

The Phase 3 lifecycle path emits TTL history-input and TTL-decision observations when the history-evidence mode is enabled. The recorded fields include history mode, sample counts, provenance, selected TTL, decision timestamp, and retention deadline.

This allows post-run descriptive/mechanism analysis of:

- whether a decision used cold-start, global, or tool-specific history;
- which observed inputs and provenance supported the TTL decision;
- the selected TTL and resulting deadline;
- how Entry Release and pressure events relate temporally to those deadlines.

However, the six-arm design contains **no Static-TTL arm**. Therefore:

- TTL decisions can be audited and described;
- the campaign can inspect whether the dynamic estimator was actually operating in empirical-history or cold-start mode;
- the campaign cannot estimate a causal Dynamic-TTL-versus-Static-TTL performance effect;
- an A0−N0 result must not be described as the isolated benefit of Dynamic TTL.

Any claim about empirical TTL activation must be supported by the actual per-run TTL_HISTORY_INPUT_OBSERVED and TTL_DECISION_OBSERVED events, including their sample counts and history-mode values. Do not infer empirical activation from the fact that the estimator exists in code.

## 6. Program-level scheduling: implemented, but not a Phase 3 treatment

The Phase 1B scheduler adapter implements a narrow ordering policy for waiting Native requests, using immutable scheduling candidates and returning ordered request identities to the Native scheduling hook. Its real-runtime validation establishes that the adapter can operate at the intended boundary.

The Phase 3 six-arm runner does not install or vary this scheduler policy. All arms use the Native vLLM scheduler, so scheduler behavior is controlled rather than experimentally manipulated.

Consequently, the current campaign:

- does not estimate program-level FCFS versus Native scheduler performance;
- does not estimate the scheduling contribution to end-to-end latency or throughput;
- cannot attribute A0−N0 or any Cost-Aware arm effect to scheduler prioritization.

The scheduler mechanism may be discussed as a completed Phase 1B implementation/validation result, but not as a mechanism whose performance advantage was demonstrated by the 270-run campaign.

## 7. Exact campaign budget and statistical populations

| Component | Runs / population | Interpretation |
| --- | --- | --- |
| Existing A0 Load Calibration | 40 existing runs | Bound into G0 and reused; no rerun |
| Noise Calibration | 30 new runs | 5 frozen Groups × C1/C2 × 3 repeats |
| Main Campaign | 240 new runs | 20 Groups × C1/C2 × 6 arms |
| **New execution budget** | **270 runs** | One continuous compute window |

The Workload Group is the statistical unit. C1 and C2 are repeated conditions within a Group, not independent groups.

- Primary arm-minus-A0 paired population: 18 complete Groups.
- H3-0: 20 Groups / 38 Headroom-qualified cells.
- H3-R: 9 RESPONSIVE Groups / 16 cells.
- Noise estimator: 10 sampled Group-condition cells, each with 3 repeats; repeats are used to estimate within-cell run noise, not to increase the independent Group count.

Use the exact Protocol v4 populations, weights, bootstrap unit, and missingness rules. Do not substitute cells, turns, or repeats as independent samples.

## 8. Claim language for the final report

| Evidence observed | Safe wording | Wording to avoid |
| --- | --- | --- |
| Phase 1B scheduler integration passes | “The project implemented and real-runtime validated a narrow program-level admission-order adapter.” | “The scheduler is proven to improve serving performance.” |
| TTL decision events are present | “The campaign records and audits dynamic-TTL inputs, history mode, selected TTL, and deadlines.” | “Dynamic TTL outperforms Static TTL.” |
| A0 differs from N0 | “The frozen forced-Entry-Release path has an incremental effect relative to the no-forced-release control under shared Native scheduling.” | “The complete Continuum system beats Vanilla vLLM.” |
| A1/A2/A3/E0 differ from A0 | “The corresponding registered Entry Release or block-victim policy changes the measured outcome under the frozen Phase 3 design.” | “All Cost-Aware mechanisms are independently beneficial.” |
| A3/E0 robust discriminability is below the registered threshold | “The cost-model hypothesis is NOT_EVALUABLE under the frozen discriminability requirement.” | “The cost model is equivalent to the deadline heuristic.” |

All final claims remain conditional on valid Native evidence, independent N/E/C evaluation, applicable protocol gates, and M1's final evidence review.

## 9. Immutable references

- Protocol v4 — Option F.
- G0 v3 review bundle.
- One-shot 270-run authorization.
- Option F engineering status.
- Phase 1B baseline freeze.
- Phase 1B implementation index.
- Phase 1B final report.
