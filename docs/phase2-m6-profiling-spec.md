# Phase 2A Member 6 Spec — Formal Profiling, Experiment Tests, and Method Support

Status: **ACTIVE TASK SPEC**

This document is the authoritative Member 6 specification for Phase 2A.

It supersedes the earlier narrower interpretation in which Member 6 mainly
recorded and analyzed a small forced-release audit.  The current assignment is
broader: Member 6 owns the formal experiment/test/analysis layer that produces
the evidence Member 4 needs before designing the Cost-Aware method.

Authoritative companion documents:

- `docs/phase2a-foundation-test-suite.md`
- `docs/phase2a-m6-formal-profiling-plan.md`
- `docs/phase2a-m6-formal-experiment-matrix.md`
- `docs/phase2a-m6-formal-test-plan.md`
- `docs/phase2a-profiling-data-contract.md`
- `docs/phase2a-empirical-gap-gate.md`
- `docs/phase2a-m4-method-support-pack.md`

## 1. Stage goal

Member 6 must provide evidence for the next Member 4 design step.

The central questions are:

1. How often does multi-candidate forced release occur?
2. How different are candidates at decision time?
3. How different are their realized outcomes?
4. Where does Continuum/P1B forced release make hindsight-suboptimal choices?
5. How large is the resulting headroom/regret?
6. Is that headroom predictable using information available online at decision time?

This phase evaluates a research gap.  It does **not** assume that a Cost-Aware
method is valid.

Member 4 should not design the final optimization from intuition or from the
foundation micro-tests alone.  The required input is the Member 6 **Method
Support Pack**.

## 2. Foundation tests are not the formal experiment

The existing P0-P3 suite is classified as:

> **Phase 2A Foundation Tests**

It validates:

- scenario materialization;
- low-cost real-runtime execution;
- multi-candidate forced release;
- prefix-size plumbing;
- planned/observed timing plumbing;
- decision/logical-release/physical-eviction/future-lifecycle joins;
- basic analysis/test fixtures.

The current 30 foundation runs are useful for bring-up and regression testing.

They are **not** sufficient by themselves to:

- characterize real problem prevalence;
- establish final candidate-set distributions;
- establish statistical headroom;
- pass the Empirical Gap Gate;
- justify a Cost-Aware design;
- support paper-level performance claims.

## 3. Member 6 ownership

Member 6 owns the formal Phase 2A experiment layer.

### 3.1 Experiment and workload work

Member 6 owns:

- formal experiment design;
- formal scenario/workload design for Phase 2A;
- writing scenario generators / experiment configurations;
- writing experiment tests;
- selecting formal repetitions/seeds;
- executing formal profiling campaigns;
- documenting invalid/failed runs.

Member 6 may reuse Member 5 substrate and the foundation backend/configs, but
must not treat the provided P0-P3 suite as the complete experiment.

### 3.2 Data and analysis work

Member 6 owns:

- raw artifact ingestion;
- derived-dataset construction;
- join logic;
- outcome attribution;
- capability/missingness handling;
- paper-reference replay;
- offline oracle/proxy analysis;
- regret/headroom analysis;
- statistical summaries;
- visualization;
- negative/null-result preservation;
- method-support interpretation for Member 4.

### 3.3 Test work

Member 6 owns tests for:

- scenario construction;
- runtime evidence integrity;
- dataset construction;
- metric correctness;
- no-future-leakage;
- capability missingness;
- analysis regressions.

## 4. Member 6 does not own

Member 6 does **not** own:

- changing the live Continuum/P1B forced-release decision rule;
- implementing the Cost-Aware policy;
- silently redefining runtime event semantics;
- adding future outcome information to online policy inputs;
- changing generic Member 5 substrate behavior unless a real substrate defect is found;
- bypassing Member 1 review for a new low-level observation seam.

If a formal experiment requires a missing raw runtime fact, Member 6 should
identify the required fact and ask Member 1 for a narrow observation/interface
decision rather than patching baseline logic.

## 5. Source-of-truth separation

Phase 2A must keep four evidence layers distinct.

### A. Decision-time facts

Facts legally available at forced-release decision time.

Source:

`FORCED_RELEASE_DECISION` plus explicitly approved runtime/workload
observations.

Examples:

- candidate `(program_id, prefix_id)`;
- retention deadline;
- waiting-followup state;
- protected block IDs;
- initially reclaimable block IDs;
- next tool type;
- elapsed time since TTL decision;
- PrefillReload estimate;
- eta;
- queue-delay signal;
- native LRU/free-queue position;
- actual P1B selected release effect.

### B. Logical release facts

Facts describing which logical protection was removed.

Examples:

- selected logical entry;
- release order;
- newly eligible blocks.

Logical release is not equivalent to immediate physical eviction.

### C. Physical runtime facts

Facts describing actual native cache behavior.

Examples:

- physical block eviction;
- block-slot reuse;
- native hash/content identity where safely available;
- known logical owner attribution where safely available.

A bare `block_id` is not a persistent content identity.

### D. Future outcome facts

Facts known only after the decision.

Examples:

- later follow-up arrival;
- later reuse;
- APC hit/miss where available;
- recomputed/prefill tokens where available;
- future return time/distance;
- TTFT/latency where valid raw landmarks exist.

Class D must never be used as an online policy feature.

## 6. Canonical identities and ordering

Every persisted record belongs to one run and carries append-only
`event_index`.

Canonical keys:

- run: `run_id`;
- decision: `(run_id, decision_event_index)`;
- candidate/logical object: `(program_id, prefix_id)`;
- request: `(run_id, request_id)`.

Recommended candidate-row key:

`(run_id, decision_event_index, program_id, prefix_id)`

Use `event_index` for within-run causal ordering.

Compare timestamps only when the relevant `clock_domain` values are known to
be compatible.

## 7. Formal experiment coverage

Formal profiling must go beyond two-candidate micro-cases.

Member 6 must cover the dimensions in the formal experiment matrix.

### F1. Prevalence / candidate-set structure

Measure:

- forced-release frequency;
- candidate-set size distribution;
- required-block/shortage distribution;
- releases per decision;
- repeated releases / repeated pressure.

Include at least:

- two-candidate cases;
- more-than-two-candidate cases;
- a higher-contention case.

### F2. Cost heterogeneity

Cover:

- homogeneous prefix sizes;
- heterogeneous materialized prefix sizes;
- larger within-decision cost spreads;
- more than one candidate-set size.

Measure:

- reusable-token/block footprint;
- PrefillReload;
- within-decision cost spread;
- divergence among logical size, physical eviction, and eventual recomputation.

### F3. Reuse / return heterogeneity

Cover:

- early return;
- late return;
- no return within predeclared horizon;
- repeated multi-turn return;
- interleaved follow-ups.

Measure:

- return probability by horizon;
- time to return;
- repeated-return behavior.

### F4. Pressure severity / repeated contention

Cover:

- shallow shortage;
- deeper shortage;
- cases requiring multiple logical releases or substantial newly eligible capacity;
- repeated pressure stages.

Measure:

- logical release volume;
- newly eligible blocks;
- actual physical eviction;
- logical-vs-physical divergence.

### F5. Queue / timing / concurrency

Cover variation in:

- arrival overlap;
- waiting population;
- tool-gap pattern;
- queue-delay state;
- return order under fixed prefix-size assignment.

Preserve planned timing and observed timing separately.

### F6. Cache structure / identity robustness

Where supported, include:

- physical block-slot reuse;
- shared/overlapping ownership;
- evolving prefixes;
- repeated eviction of the same physical block ID while holding different content.

## 8. M6 formal tests

Member 6 must implement the following test classes.

### 8.1 Scenario-construction tests

Verify:

- requested candidate count is actually materialized;
- requested prefix sizes equal observed reusable-token counts;
- intended pressure shortage is achieved;
- pressure occurs after intended protected candidates exist;
- planned timing/order is deterministic;
- seeds do not silently change scenario semantics;
- repeated-pressure traces really contain repeated pressure stages.

### 8.2 Runtime-evidence tests

Verify:

- provenance is complete;
- `event_index` is valid and monotonic;
- every forced-release decision has complete candidates;
- selected releases belong to the candidate set;
- newly eligible blocks obey recorded snapshot semantics;
- future joins respect event ordering;
- incompatible clock domains are not compared;
- block-slot reuse cannot create a false content join.

### 8.3 Dataset-construction tests

Use synthetic/compact fixtures for:

- one decision / two candidates;
- one decision / more than two candidates;
- multiple decisions in one run;
- multiple selected releases;
- repeated release of one logical object;
- block ID reuse with different content;
- no-return cases;
- tie cases;
- missing optional capabilities.

Tests must prevent many-to-many join duplication.

### 8.4 Metric tests

Test hand-computable examples for:

- candidate count;
- within-decision spread;
- logical release volume;
- physical eviction before return;
- return horizon labels;
- time to return;
- recompute loss where available;
- hindsight best candidate;
- tie handling;
- absolute regret;
- normalized regret;
- aggregation by family/seed;
- bootstrap/statistical-summary plumbing.

### 8.5 No-future-leakage tests

Maintain an explicit allowlist of online candidate features.

Reject future-only information as online features, including:

- future request arrival;
- return/no-return label;
- post-decision physical eviction;
- recomputed tokens observed after decision;
- future TTFT/latency;
- hindsight best candidate;
- regret.

## 9. Data artifacts

Raw artifacts remain authoritative:

- `run.json`;
- `trace.json`;
- `replay.jsonl`;
- `events.jsonl`;
- explicit capability availability/missingness.

Member 6 derived datasets should include at least:

- `runs`;
- `decisions`;
- `decision_candidates`;
- `logical_releases`;
- `physical_evictions`;
- `request_outcomes`;
- `decision_outcomes`.

Every derived row must retain source event-index references.

## 10. Program first-arrival convention

The forced-release snapshot intentionally does not contain
`program_arrival_time`.

For paper-reference replay, Phase 2A operationalizes program arrival as:

> the observed server arrival timestamp of the program's first request

This is a project execution convention, not a verbatim Continuum paper
definition.

Do not substitute:

- planned arrival offset;
- request-ID ordering;
- trace-file order;
- current request arrival;
- TTL decision timestamp.

If observed first arrival cannot be established reliably, the corresponding
paper-reference replay is blocked and must be reported.

## 11. Paper-Continuum replay

The paper-level forced-release reference is operationalized as:

- when protected release is required;
- repeatedly select the candidate whose program has the latest observed
  first-request arrival time;
- release until the observed `required_blocks` target can be satisfied.

This is an offline Phase 2A replay adaptation because it does not reproduce the
full scheduler counterfactual.

Record at least:

- `paper_selected`;
- `paper_release_order`.

Do not call the live P1B adaptation "original Continuum".

## 12. P1B adaptation reference

The actual P1B forced release is:

- earliest retention deadline;
- native-LRU key;
- stable entry identity.

Preserve this actual executed reference independently from the paper replay.

## 13. Counterfactual limitation

One runtime execution directly observes the consequence of the release(s) that
actually occurred.

It does not directly observe the latency that would have occurred if a
different candidate had been released.

Therefore:

- actual selected-victim outcome may be directly observed;
- unselected-victim counterfactual outcome is not directly measured in that run.

Offline regret may use:

1. a clearly labeled trace-derived/proxy loss; or
2. controlled alternate-policy replay.

Do not label proxy counterfactual latency as measured latency.

High-value/high-regret cases should later be validated with controlled replay
before causal performance claims are made.

## 14. Multiple loss views

Do not choose one loss definition too early.

Formal analysis should preserve separate views:

### LogicalReleaseCost

Loss associated with removing protection from the logical entry.

### PhysicalEvictionCost

Actual cache content displaced by native eviction.

### RecomputeCost

Work actually redone when a future request returns.

### ServingImpact

Observed request/service effect such as valid TTFT/E2E measurements.

The Method Support Pack should explicitly show where these views agree or
diverge.

## 15. Oracle / regret analysis

The oracle exists only to estimate headroom.

It is offline analysis and must never feed future information into the online
policy.

For each usable loss view, preserve ties and compute:

- actual P1B selected loss;
- paper-reference selected loss where available;
- hindsight minimum loss;
- absolute regret;
- normalized regret.

For multi-release decisions, evaluate the release set rather than only the
first victim.

## 16. Required analyses

The formal Phase 2A report must include at least:

### A. Baseline prevalence

- forced-release frequency;
- candidate-count distribution;
- pressure severity;
- releases per decision;
- repeated pressure/release.

### B. Candidate heterogeneity

For decision-time features:

- overall distributions;
- within-decision spreads;
- breakdown by workload family;
- missingness/availability.

### C. Outcome heterogeneity

Keep separate:

- logical release;
- physical eviction;
- recomputation;
- serving impact.

### D. Baseline headroom

Report:

- tie rate;
- misselection rate;
- absolute regret distribution;
- normalized regret distribution;
- high-regret cases;
- breakdown by family/candidate count/pressure severity.

### E. Decision-time signal usefulness

Using only online-available facts, evaluate:

- stratified comparisons;
- rank correlations;
- simple one/two-feature diagnostics;
- held-out checks across seeds/families;
- signals that fail to generalize.

This section diagnoses what Member 4 may plausibly use.  It is not the final
policy model.

## 17. Method Support Pack for Member 4

Member 6's main stage deliverable is the **Method Support Pack**.

It must contain:

1. baseline prevalence;
2. candidate heterogeneity;
3. outcome heterogeneity;
4. baseline headroom/regret;
5. decision-time signal usefulness;
6. method constraints.

The method-constraints section must tell Member 4:

- which features are truly available online;
- which features vary enough to matter;
- which features show stable association with realized loss;
- which features are weak/unstable;
- which information is future-only and forbidden online;
- which observation capabilities remain unavailable;
- which corner cases must be handled;
- which loss view(s) are best supported by the evidence;
- which questions remain unresolved.

## 18. Reproducibility

Every derived table/figure must be traceable to:

- run ID;
- decision event index;
- Git SHA;
- trace/scenario;
- seed;
- runtime/model/hardware config;
- raw decision evidence;
- raw outcome evidence;
- analysis script/version.

Analysis must regenerate outputs from raw artifacts without manual data edits.

Raw artifacts must not be overwritten.

## 19. Empirical Gap Gate

The Empirical Gap Gate applies to the **formal M6 profiling dataset**, not the
P0-P3 foundation suite.

The foundation suite may validate instrumentation and metric code but cannot by
itself produce `GAP-PASS`.

Possible stage conclusions:

- `GAP-PASS`;
- `GAP-PROVISIONAL`;
- `NO-MEASURABLE-GAP`;
- `HEADROOM-BUT-NO-ONLINE-SIGNAL`;
- `INSUFFICIENT-EVENTS`;
- `DATA-INVALID`.

Only `GAP-PASS` should normally trigger Member 4 Cost-Aware method
implementation.

## 20. Delivery requirements

A complete Member 6 Phase 2A delivery contains:

### Code/tests

- formal scenario/workload generator or equivalent configs;
- scenario-construction tests;
- runtime-evidence tests;
- dataset-construction tests;
- metric tests;
- no-future-leakage tests;
- analysis pipeline.

### Data

- formal raw artifacts;
- run-validity table;
- derived datasets;
- capability/missingness summary.

### Analysis

- prevalence summary;
- heterogeneity summary;
- regret/headroom analysis;
- signal-usefulness analysis;
- negative/null findings;
- selected raw exemplars.

### Handoff

- Method Support Pack for Member 4;
- explicit Empirical Gap Gate outcome.

## 21. Closure criteria

Member 6 Phase 2A work is **implementation/analysis complete** when:

- [ ] foundation suite is treated only as a sanity layer;
- [ ] formal experiment matrix covers all required axes;
- [ ] M6-authored formal tests exist and pass;
- [ ] all formal runs preserve provenance;
- [ ] raw-to-derived joins are reproducible;
- [ ] decision-time and future-outcome columns are separated;
- [ ] proxy versus direct measurement is explicit;
- [ ] block-slot reuse cannot silently corrupt attribution;
- [ ] paper reference and P1B adaptation remain distinct;
- [ ] oracle/regret analysis contains no online future leakage;
- [ ] formal dataset satisfies or explicitly fails the Empirical Gap Gate;
- [ ] Method Support Pack is delivered to Member 4;
- [ ] negative/insufficient evidence is reported rather than hidden.

Formal repository closure still requires normal integration/review validation.

## 22. Escalation to Member 1

Stop and request an interface decision if:

- a required raw fact cannot be observed reliably;
- candidate identity cannot be joined across decision and outcome records;
- physical eviction attribution is ambiguous enough to affect conclusions;
- recomputation evidence ambiguity can change the regret result;
- shared ownership semantics are unclear;
- analysis would require changing the live baseline decision path;
- a proposed feature would use future information;
- formal experiment validity depends on redefining runtime event semantics.
