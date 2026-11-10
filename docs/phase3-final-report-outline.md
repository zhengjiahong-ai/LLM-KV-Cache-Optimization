# Cost-Aware Optimization of Continuum-Style KV Cache Management on vLLM

## Phase 3 Final Research Report — Outline and Evidence Checklist

**Status:** Reporting scaffold only; no Phase 3 Noise or Main results are pre-filled.  
**As of:** 2026-11-10  
**Frozen design:** Protocol v4 — Option F  
**Execution authority:** M1 one-shot 270-run authorization

This outline organizes the report around the project’s actual research target: a project-side Continuum-style multi-turn KV cache management adaptation on vLLM, and cost-aware optimization at its Entry Release and physical Block Victim Selection layers. It is a reporting scaffold, not a new protocol; it must not change estimands, populations, gates, or run plans.

## 1. Executive summary

- Why program-aware, Continuum-style KV cache management is the chosen system foundation.
- Why cache pressure creates two separate cost-sensitive decisions: logical Entry Release and physical Block Victim Selection.
- The exact local policy changes evaluated in Phase 3.
- Backend, workload, cohort, and six-arm design.
- Primary results and uncertainty.
- Registered H3-0/H3-R findings.
- Cost-model evaluability result (including NOT_EVALUABLE if required).
- Main limitations and the strongest defensible conclusion.

Do not write outcome claims until the Native campaign, independent evaluators, and M1 evidence review are complete.

## 2. Background and related work

- KV cache reuse and Automatic Prefix Caching in vLLM.
- Cost of recomputation and the eviction/victim-selection problem.
- Continuum's program-aware multi-turn retention, TTL, pressure handling, and scheduling ideas.
- The project's vLLM adaptation boundary and the distinction between reproducing system mechanisms and optimizing selected decisions.
- Distinction between eviction, retention/protection, and scheduling.
- Related cost-aware and adaptive cache policies.
- Precise project adaptation boundary: Continuum-style implementation, not byte-for-byte reproduction.

## 3. Research questions and hypotheses

Organize the report around the frozen Phase 3 questions within the Continuum-style adapted cache-management system:

1. What is the incremental effect of the project-side forced Entry Release path (A0−N0)?
2. Do Cost-Aware Entry Release variants improve over A0 (A1/A3)?
3. Does Cost-Aware physical Block Victim Selection improve over A0 (A2)?
4. Does the suffix-cost model make robust, empirically discriminable decisions beyond the deadline-only comparator (A3 versus E0)?
5. How do effects vary across the pre-registered FLAT / WEAK / RESPONSIVE strata and fixed C1/C2 operating conditions?

Keep Dynamic TTL and program-level scheduling as supporting mechanism context, not as hypotheses whose causal effects are estimated by the current six-arm design.

## 4. System design and implementation

- Native vLLM 0.27.1 APC / BlockPool ownership boundary.
- Phase 1A eviction adapter.
- Phase 1B Continuum-style lifecycle, dynamic TTL, retention, pressure release, and scheduler adaptation.
- Phase 3 Entry Release versus physical Block Victim Selection boundaries.
- Six-arm policy mapping.
- Native scheduler fixed across Phase 3 arms.
- Independent N/E/C evidence construction and evaluation.

## 5. Experimental methodology

### 5.1 Cohort and workload

- 40 qualified tasks / 20 Workload Groups / 10 repositories.
- Cohort Seal identity and SHA-256.
- Source/task/trace provenance and replay timeline.
- Frozen request order, Native enqueue order, session pairing, and history predecessors.
- Historical W1-C pilot exclusion.

### 5.2 Operating points and cache configuration

- vLLM version and exact runtime identity.
- GPU / hardware / driver / software environment.
- 2048-block KV pool and 16-token block size.
- C1 = 256 required blocks; C2 = 1024 required blocks.
- Do not relabel C1/C2 as low/high pressure.
- Headroom definition and frozen qualified populations.
- FLAT / WEAK / RESPONSIVE classification.

### 5.3 Six arms and comparison logic

- N0, A0, A1, A2, A3, E0.
- Entry Release versus physical Block Victim Selection.
- H3-0 and H3-R.
- A3/E0 G3-CM discriminability.
- Explicitly identify what remains fixed, especially Native scheduling.

### 5.4 Run budget and execution

- Existing 40-run A0 Load Calibration: reused, not rerun.
- 30 A0 Noise Calibration runs.
- 240 Main Campaign runs.
- 270 new runs in one continuous compute window.
- Automatic Noise evaluation and transition gate.
- Execution host, runner, GPU allocation, timestamps, failures/retries, and exact authorization/hash bindings.

## 6. Evidence integrity and evaluator methodology

- G0 freeze and immutable manifests.
- Native Run-ID reconciliation.
- N/E/C definitions and independent derivation.
- Cross-arm N/E invariance and E independence from C.
- Physical APC/hash evidence and its attribution level.
- Missingness, right-censoring, and fail-closed handling.
- Noise estimator, pooled threshold, and tied classification.
- Gate outcomes: G1, G2, G3-CM, G4, plus diagnostic-only G4-M.

## 7. Results

Populate only from the sealed run archive and accepted evaluators.

### 7.1 Execution and integrity

- 30/30 Noise Run-ID reconciliation (or exact stop state).
- 240/240 Main Run-ID reconciliation (or exact stop state).
- Runtime failures, retries, incomplete evidence, and archive hashes.
- Native fidelity and evaluator gate results.

### 7.2 Noise calibration

- Pooled sigma_run.
- sigma_delta.
- Tied threshold.
- Per-stratum diagnostics and ratio status (diagnostic only).
- Persisted threshold record and SHA-256.

### 7.3 Primary arm effects

For each non-A0 arm, report arm−A0 under Protocol v4:
- Group-level estimates and intervals.
- C1 and C2 descriptive estimates.
- 18-Group paired primary.
- FLAT / WEAK / RESPONSIVE heterogeneity outputs.
- Missingness and exact analysis populations.

### 7.4 H3-0 and H3-R

- A0−N0 over 20 Groups / 38 Headroom-qualified cells.
- A0−N0 over 9 RESPONSIVE Groups / 16 cells.
- Group-level uncertainty and effect interpretation.
- Explicit limitation: forced-Entry-Release contrast, not full Continuum-versus-Vanilla comparison.

### 7.5 Entry and block decision evidence

- A1/A3/E0 Entry Release decisions and branch composition.
- A2 physical block-victim decisions.
- S2A/S2B/S2C composition and G2.
- A3/E0 robust discriminability and G3-CM.
- Native physical eviction, APC status, and recomputation evidence tiers.

## 8. Mechanism analysis

- TTL history inputs, history mode, selected TTL, and deadlines.
- Retention protection, expiry, forced Entry Release, and pressure events.
- Entry selection versus physical victim selection.
- Native scheduler behavior as a controlled invariant, not a treatment effect.
- Which mechanisms have causal contrasts, which have only event-level observability, and which were validated only in Phase 1B.

## 9. Discussion

- What the experiment establishes.
- What remains inconclusive or NOT_EVALUABLE.
- Why a null or tied result is not automatically equivalence.
- Workload and operating-point limitations.
- Difference between the project adaptation and the original Continuum paper.
- Why Phase 3 supports component-level claims about selected cache decisions, not a full-system Continuum-versus-Vanilla comparison.
- Implications for cost-aware eviction design.

## 10. Threats to validity and limitations

- Cohort selection and repository coverage.
- Controlled replay versus original serving arrival processes.
- Model/runtime/hardware specificity.
- Fixed Native scheduler.
- No Static-TTL ablation.
- Statistical power and group-level sample size.
- Physical causal attribution limits.
- Right-censoring and missing evidence.

## 11. Conclusion and future work

- Concise answers to the registered research questions.
- Supported contribution claims only.
- Future independent scheduler and Static-TTL ablations, if pursued, require separate protocols and authorization.
- The proposed Phase 4/5 follow-on sequence is documented separately in [Post-Phase-3 Experimental Roadmap](post-phase3-experimental-roadmap.md); it is not part of the Phase 3 result set or report claims.
- Avoid implying those unmeasured effects are established by Phase 3.

## 12. Reproducibility package

- Repository commit and implementation HEAD.
- Protocol v4 and M1 authorization records.
- Cohort Seal and G0 hashes.
- Noise/Main plans and input manifests.
- Native evidence archive and SHA-256 manifest.
- Evaluator versions and outputs.
- Environment lock, runner configuration, and execution ledger.
- Analysis scripts, tables, plots, and report-generation provenance.

## Required interpretation rules

- The Workload Group is the statistical unit; never count cells, turns, or repeats as independent groups.
- C1/C2 are fixed operating points, not automatically low/high pressure.
- N, E, and C remain independently derived; never compute E from C.
- A0−N0 is not a full Continuum-versus-Vanilla system contrast.
- TTL event observability is not a Dynamic-TTL-versus-Static-TTL causal estimate.
- Phase 3 does not estimate the program-level scheduler's performance contribution.
- An insufficient G3-CM robust discriminability count is NOT_EVALUABLE, not equivalence.
- No campaign result is final until M1 reviews the complete immutable evidence.
