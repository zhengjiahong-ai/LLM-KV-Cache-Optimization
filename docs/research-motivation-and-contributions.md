# Research Motivation and Contributions

**Project title:** Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM  
**中文定位：** 面向 vLLM 的 Continuum 风格 KV Cache 管理成本感知优化  
**Status:** Canonical project-positioning document, 2026-11-10  
**Authority:** This document explains the research narrative. Frozen implementation semantics remain in [Baseline Freeze](baseline-freeze.md); current experimental status and claims remain in [Research Status](research-status.md); Phase 3 estimands and gates remain in [Protocol v4](phase3-final-evaluation-protocol-v4.md).

## 1. One-sentence project definition

This project builds a project-side adaptation of Continuum-style, program-aware multi-turn KV cache management on vLLM 0.27.1, then investigates whether cost-aware policies can improve the cache-release and physical-victim decisions made under GPU memory pressure.

The project is therefore **not** a generic KV-cache eviction framework developed independently of a system baseline, and it is **not** a claim of exact source-level reproduction of the original Continuum system.

## 2. Why Continuum-style cache management is the system foundation

In multi-turn conversations and tool-using Agent workloads, a request may pause while a tool runs and later resume with a related prefix. KV blocks can therefore remain valuable even when they are not accessed continuously. A cache manager that only observes the recency of the last native request may not fully represent the lifecycle of a multi-turn program or session.

Continuum provides the motivating system design: manage cache state with program/workflow context, use inter-request/tool-gap history to estimate retention time, protect useful prefixes during that window, release protection when it expires or memory pressure requires reclamation, and coordinate program-level request scheduling.

vLLM 0.27.1 does not natively expose all of the program/session identity, tool-gap, pinning, and program-level scheduling primitives required by that design. Phase 1B therefore implemented a **project-side Continuum-style adaptation** using external lifecycle observations and independent retention state while preserving Native vLLM ownership of allocation, reference counts, APC hashes, physical block reuse, and cleanup.

The accepted adaptation includes:

- explicit program/session identity across multiple native request IDs;
- tool-gap and server inter-request-gap history;
- dynamic TTL estimation with documented input provenance and adaptations;
- soft retention protection and lazy expiry;
- deterministic pressure-driven Entry Release;
- a narrow program-level admission-order scheduling adapter;
- Native APC / BlockPool allocation and eviction semantics.

Phase 1B passed its real-runtime integration validation on its qualified Metal profile. This is evidence that the adaptation and its controlled integration boundaries work on the validated profile. It is **not** proof of exact paper-system reproduction, original-paper workload reproduction, or a measured serving-performance advantage.

See [Baseline Freeze](baseline-freeze.md), [Continuum Baseline Implementation](continuum-baseline-implementation.md), and the [Phase 1B final report](experiments/phase1b-continuum/final-report.md).

## 3. The optimization question inside the Continuum-style system

The Continuum-style baseline supplies program-aware retention context, but cache pressure still requires a sequence of distinct decisions. The project separates two of them.

### 3.1 Entry Release — which retained entry should yield?

Retention protection is soft, not absolute. When ordinary unprotected blocks are insufficient to satisfy an allocation, the system may need to release protection for one or more retained logical entries. This makes their associated blocks eligible for the Native eviction path.

The research question is not merely whether an entry has expired. It is whether the system can choose which entry to release by considering the amount of memory recovered and the future recomputation/reuse loss that may result.

Phase 3 candidates at this layer are:

- **A0:** frozen project-side Continuum-style Entry Release baseline;
- **A1:** Cost-Aware Entry Release;
- **A3:** suffix-cost-aware Entry Release;
- **E0:** the A1-style branch ladder with deadline-only Step 2, serving as a strong comparator.

**N0** is the no-forced-Entry-Release control. It retains the pressure request and replay path but does not perform the forced-release action.

### 3.2 Physical Block Victim Selection — which eligible blocks should Native vLLM evict?

After logical release changes eligibility, a separate decision determines which physical KV blocks are removed. The project preserves Native vLLM ownership of BlockPool, free-queue, hash cleanup, reference counts, allocation, and actual eviction bookkeeping.

The physical-victim research question is whether a cost-aware selector can choose a better legal victim set than Native LRU, while holding the upstream A0 Entry Release path constant.

Phase 3 **A2** changes this physical block-victim decision while retaining A0 Entry Release. A2 is not a combined A1+A2 policy.

### 3.3 Why the two decisions must remain separate

The evidence chain is:

~~~text
retention state / pressure
    -> logical Entry Release
    -> newly eligible Native blocks
    -> physical victim selection
    -> Native hashed eviction / BlockPool cleanup
    -> later APC prefix availability
    -> recomputed prompt tokens
~~~

A logical release is not itself a physical eviction. A selected victim is not, by itself, proof of a later APC miss. A cache-state change is not, by itself, proof of increased recomputation. Each transition requires its own evidence.

This decomposition is central to the project's research design: it allows the Entry Release policy and the physical block-victim policy to be changed and evaluated separately.

## 4. Current research questions

The current formal questions are defined by Phase 3 Protocol v4. In plain language:

1. **Does the Continuum-style forced Entry Release path matter?** Compare A0 with N0 under the same pressure path, Native LRU/APC, and Native scheduler (registered H3-0 and H3-R).
2. **Can cost-aware Entry Release improve on the adapted baseline?** Compare A1 and A3 with A0 under the frozen protocol.
3. **Can cost-aware physical victim selection improve on Native LRU?** Compare A2 with A0 while keeping the A0 Entry Release path unchanged.
4. **Does the suffix-cost model add decision information beyond a deadline-only rule?** Compare A3 with E0 using the registered G3-CM discriminability definition.
5. **How do effects vary across the pre-registered workload strata and fixed C1/C2 operating points?** Report only the frozen group-level populations and analyses.

The primary outcome is aggregate recomputed tokens, Σ(E−C), derived from independently established N, E, and C. The Workload Group is the statistical unit.

## 5. What Phase 3 does not test

The 270-run campaign is a **controlled component-level evaluation within the project-side Continuum-style cache-management adaptation**. It does not evaluate every mechanism in the Continuum-style system.

- **Dynamic TTL versus Static TTL:** TTL inputs, history modes, selected values, and deadlines can be inspected, but there is no Static-TTL arm. The campaign cannot estimate the causal performance advantage of dynamic TTL over static TTL.
- **Program-level scheduler performance:** the narrow scheduler adapter was implemented and real-runtime validated in Phase 1B. Every Phase 3 arm uses the Native scheduler, so the campaign does not estimate the scheduler's performance contribution.
- **Full-system Continuum versus Vanilla vLLM:** A0−N0 isolates the incremental forced-Entry-Release path under shared Native scheduling and Native LRU/APC. It is not a comparison of the complete Continuum-style adaptation against untouched Vanilla vLLM.
- **Original-paper reproduction:** the project uses a documented adaptation and controlled workload. It does not claim source-level or original-serving-trace reproduction.

These boundaries are deliberate. They prevent the report from attributing an observed effect to TTL, scheduling, or the complete system when the formal design varies a narrower decision.

## 6. Contribution statement: what is complete and what remains a hypothesis

### Completed engineering and research infrastructure

1. **Continuum-style vLLM adaptation:** implemented program/session lifecycle observation, history-aware TTL inputs, soft retention, pressure release, and a narrow scheduler adapter while preserving Native vLLM cache ownership.
2. **Real-runtime integration validation:** verified the Phase 1B adaptation and its controlled boundaries on the qualified vLLM 0.27.1 Metal profile.
3. **Decision-layer decomposition:** separated logical Entry Release from physical Block Victim Selection and preserved the Native eviction path as the common execution substrate.
4. **Evaluation infrastructure:** established frozen six-arm materialization, independent N/E/C evaluation, G0 cohort sealing, and a fail-closed Protocol v4 campaign design.

### Research hypotheses still requiring formal evidence

- whether A0 forced Entry Release reduces recomputation relative to N0;
- whether A1 or A3 improves on A0;
- whether A2 improves on A0;
- whether A3 has sufficient robust discriminability beyond E0;
- how any effects vary across the frozen workload population.

No cost-aware policy is described as superior until the 270-run evidence, independent evaluation, applicable gates, and M1 final review support that claim.

## 7. Potential future research directions

The following ideas are retained as a **research reserve**, separate from the formal Phase 3 hypotheses and current campaign:

- **Evidence-aware Block intervention:** a benefit-aware policy gate over the actual Native-LRU baseline, beyond the existing input/contract fallback.
- **Workflow-aware Block signals:** determine whether online lifecycle signals add value to Block selection beyond the final TTL-derived deadline.
- **Downstream-cost-aware Entry Release:** choose Entry release order by simulating the actual downstream victim set and its recomputation consequences.
- **Partial-tail Entry unpinning:** investigate sub-Entry protection granularity while preserving prefix continuity and shared-owner correctness.

All four remain proposals with unresolved implementation, data, and evaluation requirements. None is a completed contribution or proven improvement; none is included in Phase 3 or authorized for implementation. The [Potential Future Research Directions](future-research-directions.md) document is the detailed source for their status, prerequisites, and falsification criteria.

## 7. Current formal campaign at a glance

| Component | Runs | Status / interpretation |
| --- | ---: | --- |
| Existing A0 Load Calibration | 40 | Completed earlier and bound into G0; reused, not rerun |
| A0 Noise Calibration | 30 | Authorized; part of the one-shot execution pipeline |
| Six-arm Main Campaign | 240 | Pre-authorized conditionally on the machine-verified Noise transition gate |
| **New runs** | **270** | One continuous compute window |

The Main Campaign uses 20 Workload Groups × C1/C2 × six arms (N0/A0/A1/A2/A3/E0). The Noise stage uses five frozen Groups × C1/C2 × three repeats. See the [M1 status ledger](research-status.md), [Protocol v4](phase3-final-evaluation-protocol-v4.md), and [one-shot authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md) for operative details.

## 8. Recommended terminology

| Prefer | Avoid / qualify |
| --- | --- |
| project-side Continuum-style adaptation | exact reproduction of Continuum |
| Continuum-style cache-management baseline | full original Continuum system, unless specifically qualified |
| cost-aware optimization within the adapted system | generic KV-cache optimization with no system context |
| logical Entry Release | physical eviction, when only protection was released |
| physical Block Victim Selection | Entry Release, when actual block selection changed |
| Phase 1B real-runtime integration validation | complete reproduction / proven performance gain |
| Phase 3 component-level effect | full-system Continuum superiority |
| TTL decision observability | Dynamic TTL causal benefit |
| Phase 1B scheduler integration | Phase 3 scheduler performance result |

## 9. Source-of-truth documents

- [M1 Research Status](research-status.md)
- [Phase 3 Protocol v4](phase3-final-evaluation-protocol-v4.md)
- [Phase 3 mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md)
- [Baseline Freeze](baseline-freeze.md)
- [Continuum Baseline Implementation](continuum-baseline-implementation.md)
- [Phase 1B final report](experiments/phase1b-continuum/final-report.md)
- [Phase 3 final report outline](phase3-final-report-outline.md)
