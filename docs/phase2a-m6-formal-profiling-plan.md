# Phase 2A M6 Formal Profiling and Method-Support Plan

Status: TASK DEFINITION

## 1. Role of M6 in this stage

M6 is not only a data runner.

M6 owns:
- formal experiment test design and implementation;
- workload / scenario test writing for Phase 2A;
- profiling and data collection;
- derived-dataset construction;
- data-quality tests;
- statistical analysis;
- visualization;
- interpretation of baseline behavior;
- the evidence package used by M4 to design the optimization.

M4 owns optimization method design and implementation.

Therefore the Phase 2A output is not '30 foundation runs'. The required output is a Method Support Pack showing what problem exists, how large it is, which decision-time signals explain it, and which cases a new policy must handle.

## 2. Foundation tests versus formal profiling

Foundation tests already provided:
- deterministic micro-scenarios;
- small P0-P3 suite;
- low-cost real-runtime validation;
- schema/join/timing sanity.

Formal M6 profiling must go beyond these tests in three directions:
1. broader decision structure;
2. broader workload / pressure conditions;
3. systematic outcome analysis.

M6 may reuse the foundation backend and configs, but should write additional tests and scenario generators rather than treating the frozen P0-P3 suite as the experiment itself.

## 3. Questions the formal profiling must answer for M4

### Q1. How common is the target problem?
Measure:
- forced-release event frequency;
- candidate-set size distribution;
- number of logical releases per pressure event;
- pressure depth / required blocks;
- repeated pressure on the same program/prefix.

M4 needs to know whether the optimization target is frequent enough to matter.

### Q2. How heterogeneous are candidates at decision time?
Measure within-decision distributions of:
- reusable-token / block footprint;
- PrefillReload;
- retention deadline;
- elapsed time since TTL decision;
- waiting-followup state;
- next-tool type;
- eta;
- queue delay;
- native LRU rank / free-queue position.

M4 needs to know which online signals actually vary enough to be useful.

### Q3. How heterogeneous are realized outcomes?
For every candidate, derive as available:
- return / no return within horizons;
- time to return;
- logical blocks released;
- physical blocks evicted before return;
- recomputed/prefill tokens;
- request-level serving impact.

Do not collapse logical release, physical eviction, recomputation, and serving impact into one metric prematurely.

### Q4. Where does Continuum make costly forced-release choices?
Construct decision-level comparisons between:
- Continuum-selected candidate(s);
- hindsight lower-cost candidate(s);
- ties.

Report:
- misselection frequency;
- absolute regret;
- normalized regret;
- regret distribution by scenario/workload family;
- examples of large-regret decisions.

This is offline analysis only.

### Q5. Is the hindsight gap predictable online?
Using only decision-time fields, analyze whether realized loss has stable association with observable features.

At minimum M6 should evaluate simple, interpretable diagnostics:
- stratified comparisons;
- rank correlations;
- simple one/two-feature baselines;
- held-out sanity checks across seeds/workload families.

The goal is not to build the final policy. The goal is to tell M4 whether an online Cost-Aware rule is plausible and which signals deserve attention.

## 4. Formal profiling dimensions

M6 should write tests/scenario generators that cover more than two-candidate micro-cases.

### Candidate-set scale
- 2 candidates;
- >2 candidates;
- a higher-contention case where several logical releases may be required.

The exact larger sizes should be chosen by M6 based on runtime cost and stable execution, not hard-coded here as a paper claim.

### Prefix / recomputation heterogeneity
- homogeneous sizes;
- mixed sizes;
- larger within-decision cost spread;
- real materialized prefix sizes.

### Reuse lifecycle
- early return;
- late return;
- no return within analysis horizon;
- repeated multi-turn return;
- multiple programs with interleaved follow-ups.

### Pressure severity
- shallow shortage;
- deeper shortage where multiple protected blocks/entries must become eligible;
- repeated pressure stages.

### Workload concurrency / queue state
Include different:
- arrival overlap;
- waiting population;
- queue-delay state;
- tool-gap patterns.

Planned and observed timing must both be retained.

### Shared/cache-structure cases
Where supported:
- shared physical blocks / overlapping ownership;
- block-slot reuse after eviction;
- repeated logical release of evolving prefixes.

These matter because block_id alone is not a persistent content identity.

## 5. M6 must write experiment tests

### A. Scenario-construction tests
Verify:
- requested candidate count is actually materialized;
- requested prefix sizes equal observed reusable-token counts;
- pressure severity matches intended shortage;
- planned order/timing is deterministic;
- seeds do not silently change scenario semantics.

### B. Runtime evidence tests
Verify:
- every formal run has complete provenance;
- every forced-release decision has a complete candidate snapshot;
- selected logical releases belong to the candidate set;
- physical eviction joins never rely on block_id after ambiguous reuse;
- timing comparisons never cross incompatible clock domains.

### C. Dataset-construction tests
Use small synthetic artifacts to test:
- decision/candidate joins;
- post-decision horizon handling;
- no-return labeling;
- physical-eviction counting;
- tie handling;
- repeated block-slot reuse;
- missing capability handling.

### D. Metric tests
Test exact calculations for:
- within-decision spread;
- return horizons;
- logical/physical/recompute loss views;
- hindsight best candidate;
- regret and normalized regret;
- bootstrap/statistical summaries.

### E. No-future-leakage tests
Fields used as candidate online features must be provably available at or before the decision event.
Future lifecycle, physical eviction after the decision, recomputation, and serving outcomes may only be targets/offline labels.

## 6. Required M6 derived datasets

At minimum:
- runs
- decisions
- decision_candidates
- logical_releases
- physical_evictions
- request_outcomes
- decision_outcomes

Recommended canonical candidate row:
(run_id, decision_event_index, program_id, prefix_id)

Each derived row retains source event-index references.

## 7. Method Support Pack for M4

M6's main Phase 2A deliverable to M4 should contain:

### A. Baseline prevalence
- forced-release frequency;
- candidate-set size distribution;
- pressure severity distribution.

### B. Candidate heterogeneity
- distributions of decision-time features;
- within-decision feature spreads.

### C. Outcome heterogeneity
- logical release;
- physical eviction;
- recomputation;
- serving impact;
- divergence among these views.

### D. Baseline headroom
- Continuum misselection frequency;
- regret distribution;
- high-regret examples;
- breakdown by workload / pressure family.

### E. Signal usefulness
- relationship between decision-time signals and realized loss;
- stable versus unstable signals;
- signals that only work in one synthetic family.

### F. Method constraints
A short list for M4:
- which information is actually available online;
- which information is predictive enough to consider;
- which corner cases must be handled;
- which metrics should not be optimized directly;
- where current evidence is insufficient.

M4 should design the Cost-Aware method from this evidence, not from the foundation micro-scenarios alone.

## 8. Empirical Gap Gate

The existing empirical-gap criteria apply to the formal M6 profiling dataset, not to the 30-run foundation suite.
The foundation suite may be used to debug the pipeline and validate metric implementations, but it cannot by itself produce GAP-PASS.

## 9. M1 / M5 / M4 boundary

M1:
- approves observation semantics and narrow backend seams;
- reviews M6 experiment protocol and evidence validity;
- integrates changes.

M5:
- generic substrate remains closed unless a real substrate defect is found.

M6:
- owns formal tests, experiments, data, analysis, and method-support evidence.

M4:
- consumes the Method Support Pack;
- formulates and implements optimization after evidence supports it.
