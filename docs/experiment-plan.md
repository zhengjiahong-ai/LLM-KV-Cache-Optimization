# Experimental Plan

> **Research positioning (2026-11-10):** This plan describes cost-aware optimization within the project-side Continuum-style KV cache management adaptation on vLLM. The earlier Ours-Evict / Ours-Full roadmap is preserved as historical design context in [Architecture](architecture.md) and [Phase 2 joint design](phase2-cost-aware-joint-design.md); it is not the operative Phase 3 policy definition. For the current formal questions and claim boundaries, use [Research Motivation and Contributions](research-motivation-and-contributions.md), [Research Status](research-status.md), and [Protocol v4](phase3-final-evaluation-protocol-v4.md).

## Current Phase 3 execution overlay (M1 reconciliation, 2026-11-10)

**Canonical status:** [docs/research-status.md](research-status.md). This section is the current operative Phase 3 framing and execution summary. It supersedes earlier eviction-only RQ labels and the 310-run draft plan where they conflict; prior phase verdicts and immutable evidence records remain unchanged.

### Current delivery and authorization

| Item | Status | Evidence / boundary |
| --- | --- | --- |
| Protocol v3 | Historical / superseded | PR #90 remains immutable history |
| Protocol v4 — Option F | **FROZEN** | [Protocol v4](phase3-final-evaluation-protocol-v4.md) |
| Six-arm materializer | **MERGED** | PR #93; CPU/Mock and materialization validation |
| Independent N/E/C evaluator | **MERGED** | PR #94; RC1–RC4 closed |
| G0 v3 | **ACCEPTED by M1 (2026-11-07)** | 40 tasks / 20 Groups / 10 repositories; existing 40-run A0 calibration bound |
| One-shot execution | **AUTHORIZED / NOT STARTED** | [M1 270-run authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md) |
| M6 pre-launch readiness | **NOT YET RECORDED ON MAIN** | Host, runner, GPU allocation, resource reservation, and hash validation must be reported before launch |

### Frozen campaign

- Six arms: **N0 / A0 / A1 / A2 / A3 / E0**.
- Main: **20 Groups × C1/C2 × 6 arms = 240 runs**.
- Noise: **5 frozen Groups × C1/C2 × 3 repeats = 30 runs**.
- Total new-run budget: **270** in one continuous compute window.
- Existing A0 Load Calibration: **40 runs, reused; no rerun**.
- The Workload Group is the statistical unit. C1/C2 are repeated operating conditions within a Group, not independent groups.
- The Main primary paired population is 18 complete Groups; H3-0 uses all 20 Groups / 38 Headroom-qualified cells; H3-R uses 9 RESPONSIVE Groups / 16 cells.

### Fixed conditions and gates

- C1 and C2 are the frozen operating-point names. Their required_blocks are 256 and 1024 respectively; source labels L_LOW / L_HIGH are provenance only and must not be promoted to “low pressure” / “high pressure”.
- Headroom requires rho0 >= 0.05 and R0 >= 512; frozen result: 38/40 cells.
- FLAT / WEAK / RESPONSIVE strata are frozen as 3 / 8 / 9 Groups and are not post-hoc exclusion filters.
- The 30-run Noise stage must produce and persist the exact Protocol v4 pooled estimator and tied threshold.
- Main may start only after the machine-verified transition gate validates all 30 Noise Run IDs, the independent evaluator, all applicable mandatory gates, and all frozen hashes.
- Any missing evidence, undefined required pooled value, mandatory gate failure, or hash mismatch stops the pipeline before Main. No intermediate manual M1 review is required when the automatic gate passes.

### Research interpretation

The campaign separates Entry Release from physical Block Victim Selection. A0−N0 is the registered forced-Entry-Release contrast; A1/A3/E0 change Entry Release selection; A2 changes physical block selection. The Phase 3 Native scheduler is held fixed. TTL inputs/decisions are observable, but no Static-TTL arm is present. Therefore the campaign does not independently estimate Dynamic TTL versus Static TTL or the program-level scheduler's performance effect. See [mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md).

## Project Theme and Research Objective

**Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM**

The project builds upon a project-side Continuum-style adaptation for program-aware, multi-turn KV cache management on vLLM 0.27.1. Its research objective is to determine whether cost-aware decisions can improve cache management under memory pressure.

The motivating system manages program/session lifecycle, tool-gap and reuse history, dynamic TTL, soft retention, pressure-driven release, and program-level scheduling. The optimization study focuses on two distinct decisions:

1. **Entry Release:** which retained logical entry should yield when protected cache must be released.
2. **Physical Block Victim Selection:** which eligible KV blocks should be removed by Native vLLM.

The project does not claim exact source-level reproduction of the original Continuum system. The Phase 1B adaptation is an engineering baseline; the later cost-aware work, especially Phase 2G and Phase 3, investigates local optimization choices within that baseline.

See [Research Motivation and Contributions](research-motivation-and-contributions.md) for the canonical project narrative and [Research Status](research-status.md) for the current phase and evidence boundaries.

## Research Questions

The formal Phase 3 questions are defined by frozen Protocol v4 and must not be changed by this narrative document.

### RQ1 — Continuum-style forced Entry Release

Under the shared pressure path, Native LRU/APC and Native scheduler, what is the incremental effect of the frozen project-side Continuum-style forced Entry Release path versus the no-forced-release control (A0−N0)?

### RQ2 — Cost-Aware Entry Release

Do the registered Cost-Aware Entry Release policies (A1/A3) improve the recomputation outcome relative to the adapted baseline A0?

### RQ3 — Cost-Aware physical Block Victim Selection

Does changing only the physical victim selector (A2), while retaining A0 Entry Release, improve the recomputation outcome relative to A0?

### RQ4 — Cost-model discriminability

Does the suffix-cost-aware decision path (A3) produce the required robustly discriminable decisions beyond the deadline-only Step 2 comparator (E0), under the exact G3-CM definition?

### RQ5 — Workload heterogeneity

How do the registered effects vary across the frozen FLAT / WEAK / RESPONSIVE strata and fixed C1/C2 operating points?

Dynamic TTL and program-level scheduling remain important Continuum-style baseline mechanisms, but the current Phase 3 design does not independently estimate Dynamic-TTL-versus-Static-TTL or scheduler-performance effects.

## System foundation and execution baselines

### Native vLLM execution path

The underlying execution backend is vLLM 0.27.1 GPU Automatic Prefix Caching (APC), using Native scheduling and Native physical LRU block-victim selection unless a registered arm explicitly changes the victim selector.

The Native path remains responsible for allocation, reference counts, APC hash metadata, physical block reuse, free-queue state, and cleanup.

### Project-side Continuum-style cache-management adaptation

**Status: Phase 1B IMPLEMENTED AND REAL-RUNTIME VALIDATED.**

This adaptation is the system foundation for the current optimization study. Its validated scope includes:

- explicit program/session identity across native request IDs;
- tool-gap and server inter-request-gap history;
- dynamic TTL estimation and PrefillReload inputs;
- soft retention protection and lazy expiry;
- deterministic pressure-driven logical Entry Release;
- a narrow program-level admission-order scheduling adapter;
- preservation of Native vLLM APC / BlockPool ownership.

It is a documented project-side adaptation, not a byte-for-byte or source-level reproduction of the original Continuum system. The Phase 1B scheduler adapter is engineering/integration evidence; its performance effect is not estimated by Phase 3.

### Phase 3 baseline and control roles

- **N0:** no forced Entry Release, with the same pressure request/barrier/replay path, Native LRU/APC, and Native scheduler.
- **A0:** frozen project-side Continuum-style Entry Release with Native LRU physical block selection. This is the adapted Entry Release baseline, not a full public-Continuum system arm.

## Phase 3 registered policy arms

| Arm | Logical Entry Release | Physical Block Victim Selection | Research role |
| --- | --- | --- | --- |
| N0 | No-op; no forced Entry Release | Native LRU | Control for the forced-release path |
| A0 | Frozen project-side Continuum-style Entry Release | Native LRU | Adapted Entry Release baseline |
| A1 | Cost-Aware Entry Release | Native LRU | Cost-aware change at the Entry Release layer |
| A2 | Same frozen A0 Entry Release | Cost-Aware block selector | Cost-aware change at the physical victim layer |
| A3 | Suffix-cost-aware Entry Release | Native LRU | Alternative cost-aware Entry Release candidate |
| E0 | A1 branch ladder with deadline-only Step 2 | Native LRU | Strong deadline-only comparator |

A2 is **not** an A1+A2 combined policy. A1/A3/E0 change the logical Entry Release decision; A2 changes physical victim selection while retaining the A0 Entry Release path.

## Decision layers and attribution

The system-level decision chain is:

~~~text
program/session lifecycle and retention state
    -> memory pressure
    -> logical Entry Release
    -> newly eligible Native KV blocks
    -> physical Block Victim Selection
    -> Native hashed eviction / BlockPool cleanup
    -> later APC prefix availability
    -> recomputed prompt tokens
~~~

Entry Release changes eligibility; it does not itself evict a physical block. A selected victim is not, by itself, proof of a later APC miss. A later miss is not, by itself, proof of additional recomputation. Each transition requires its own evidence.

The current policy candidates are the six frozen Phase 3 arms. The earlier Ours-Evict / Ours-Evict+Retention / Ours-Full labels are retained only as historical conceptual roadmap terminology; they are not aliases for A1, A2, or any combined Phase 3 treatment. See [Research Motivation and Contributions](research-motivation-and-contributions.md).

## Backend and adapter boundary

Backend:

~~~text
vLLM 0.27.1
GPU Automatic Prefix Caching (APC)
~~~

Validated Native GPU APC path:

~~~text
BlockPool.get_new_blocks()
    -> FreeKVCacheBlockQueue.popleft_n()
    -> BlockPool._maybe_evict_cached_block()
~~~

The Phase 1A VLLMEvictionBridge / EvictionPolicyAdapter is the physical block-victim selection boundary. It is varied by A2; it is not the logical Entry Release boundary. Native BlockPool cleanup and ownership remain unchanged.

## Formal Phase 3 execution design

The frozen campaign is governed by [Protocol v4](phase3-final-evaluation-protocol-v4.md) and the [one-shot M1 authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md).

| Component | Runs | Current status |
| --- | ---: | --- |
| Existing A0 Load Calibration | 40 | Completed earlier, bound into G0, reused without rerun |
| A0 Noise Calibration | 30 | Authorized as Stage A; not yet reported as executed |
| Six-arm Main Campaign | 240 | Conditionally pre-authorized after the automatic Noise transition gate |
| **New execution budget** | **270** | One continuous compute window |

The Main Campaign is 20 Workload Groups × C1/C2 × six arms. Noise uses five frozen Groups × C1/C2 × three repeats. The Workload Group is the independent statistical unit; cells, turns, and repeats must not be counted as independent groups.

## Frozen workload and operating-point interpretation

- G0 v3 binds 40 tasks / 20 Workload Groups / 10 repositories.
- C1 and C2 are frozen operating-point names with 256 and 1024 required blocks respectively. Do not relabel them as low/high pressure.
- Headroom qualification is frozen at 38/40 cells.
- FLAT / WEAK / RESPONSIVE are frozen at 3 / 8 / 9 Groups.
- The primary paired arm-minus-A0 population is 18 complete Groups.
- H3-0 uses all 20 Groups / 38 Headroom-qualified cells; H3-R uses 9 RESPONSIVE Groups / 16 cells.

Use the exact Protocol v4 population, weighting, bootstrap, missingness, and gate definitions. Do not substitute exploratory workload categories from historical plans or post-hoc labels for the frozen Group/condition populations above.

## Metrics and evidence

The primary outcome is aggregate recomputed tokens, Σ(E−C), with N, E, and C independently derived. Enforce 0 ≤ C ≤ E ≤ N.

- R = E−C: eligible-prefix recomputation;
- W = N−C: actual prefill work;
- S = N−E: genuinely new suffix;
- W = R+S.

Report the exact registered arm contrasts and group-level uncertainty. TTFT, throughput, TPOT, cache-hit measures, victim-decision overhead, and mechanism counts are supporting outcomes where available; they do not replace the registered primary outcome.

Logical Entry Release, physical hashed eviction, subsequent APC status, and request-level recomputation are separate evidence tiers. Missing evidence must remain missing and fail closed where the protocol requires it.

## Fairness and claim boundaries

All six Phase 3 arms use the Native vLLM scheduler. The model/runtime identity, frozen request inputs, cache configuration, replay timeline, pressure conditions, and other registered controls must remain bound to the frozen manifests.

The campaign can estimate the registered local policy contrasts within the project-side Continuum-style adaptation. It does **not** estimate:

- a complete original Continuum-versus-Vanilla-vLLM system effect;
- Dynamic TTL versus Static TTL (there is no Static-TTL arm);
- the program-level scheduler's performance contribution (all arms use Native scheduling);
- exact source-level or original-paper workload reproduction.

Do not claim that any cost-aware candidate is superior before the 270-run evidence, independent evaluation, applicable gates, and M1 final review are complete.

## Ownership and current authority

- **M1:** research architecture, phase grants, canonical status, protocol freeze, fairness/claim boundaries, integration, and final evidence adjudication.
- **M4:** frozen Protocol v4 semantics and post-campaign effect/statistical analysis; no routine protocol redesign is authorized.
- **M6:** pre-launch readiness, one-shot 270-run execution, automatic Noise-to-Main transition, Native evidence, independent evaluator outputs, execution statistics, and immutable evidence archive.
- **M5:** shared workload/runner substrate only when a concrete interface gap remains.
- **M2/M3:** background/source-mechanism review and frozen baseline support.
- **M7:** report and presentation preparation after results and claims have been accepted.

## Current freeze state (2026-11-10)

### Frozen / accepted

- Project positioning: cost-aware optimization within a project-side Continuum-style KV cache-management adaptation.
- Backend: vLLM 0.27.1 GPU APC.
- Phase 1B Continuum-style adaptation: scope frozen, implemented, and real-runtime validated.
- Phase 3 Protocol v4 — Option F: FROZEN.
- Six-arm materializer and independent N/E/C evaluator: merged.
- G0 v3: accepted by M1 on 2026-11-07.
- Existing 40-run A0 Load Calibration: reused, not rerun.
- New-run plan: 30 Noise + conditionally 240 Main, one continuous compute window.

### Execution state

**270-run pipeline: AUTHORIZED / NOT STARTED.** M6 pre-launch readiness must still record the host, runner, GPU allocation, full resource reservation, and frozen-hash validation. The 240-run Main stage may start only after the machine-verified Noise transition gate passes. Authorization is not evidence that the compute window is ready or that any run has started.



## Historical plan archive

The complete pre-2026-11-10 experimental plan, including the original Ours-Evict/Ours-Full roadmap, earlier RQ1–RQ4 formulations, and the 310-run draft budget, is preserved verbatim in [the historical plan archive](archive/experiment-plan-pre-phase3-reframing-2026-11-10.md). Those statements document earlier planning and are not current Phase 3 authorization or arm definitions.

## Historical roadmap note

Earlier project plans used Ours-Evict, Ours-Evict+Retention, and Ours-Full as conceptual stages. Those names are preserved in historical design documents, but they are not the current Phase 3 arm names and must not be used to imply that Phase 3 evaluates a monolithic Ours-Evict system. The current registered policy map is N0/A0/A1/A2/A3/E0.
