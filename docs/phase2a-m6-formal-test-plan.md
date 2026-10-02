# Phase 2A M6 Formal Test Plan

Status: REQUIRED M6 IMPLEMENTATION

## 1. Purpose

M6 must write tests for the formal experiment and analysis stack, not only run existing tests.

This plan defines what must be tested. M6 owns the implementation.

## 2. Scenario-construction tests

Required assertions:
- requested number of programs/candidates is actually materialized;
- requested per-program prefix size equals observed reusable-token count;
- block budget creates the intended shortage depth;
- pressure stage occurs after intended protected candidates exist;
- scenario seeds do not change semantic dimensions unless explicitly intended;
- planned arrivals are deterministic;
- repeated-pressure scenarios actually contain repeated stages.

Negative cases:
- insufficient candidate count;
- malformed prefix-size assignment;
- impossible block budget;
- terminal turn before required follow-up;
- pressure stage before candidate materialization.

## 3. Runtime evidence tests

Required assertions:
- run provenance is complete;
- event_index is unique and monotonic within a run;
- every FORCED_RELEASE_DECISION has complete candidates and selected releases;
- selected logical releases belong to the candidate set;
- newly eligible blocks are subsets of candidate-owned blocks under the recorded snapshot semantics;
- future joins use event_index ordering;
- timestamps are only compared within compatible clock domains;
- physical block ID reuse does not create a false content join.

## 4. Dataset-construction tests

M6 should create small synthetic artifact fixtures covering:
- one decision / two candidates;
- one decision / >2 candidates;
- multiple decisions in one run;
- repeated release of the same logical object;
- block ID reused with different content;
- selected candidate never returns;
- unselected candidate returns first;
- missing optional capability;
- multiple selected releases;
- tie in realized loss.

Required derived-table checks:
- one decision row per decision;
- one candidate row per candidate per decision;
- source event indexes retained;
- no candidate duplicated by a many-to-many join;
- no future event attached to a candidate before the decision;
- analysis horizon applied consistently.

## 5. Metric correctness tests

Test exact hand-computed examples for:
- candidate_count;
- within-decision feature spread;
- logical blocks released;
- physical blocks evicted before return;
- return/no-return within horizon;
- time to return;
- recompute loss when available;
- hindsight best candidate;
- tie handling;
- absolute regret;
- normalized regret;
- aggregation by family and seed;
- bootstrap confidence interval plumbing.

## 6. No-future-leakage tests

Maintain an explicit allowlist of online candidate features.

Every feature used in signal analysis or passed to an M4 method prototype must originate at or before decision_event_index.

Tests must reject as online features:
- future request arrival;
- future return/no-return label;
- post-decision physical eviction;
- recomputed tokens observed after the decision;
- future latency / TTFT;
- hindsight best candidate;
- regret.

## 7. Capability-missingness tests

For each optional capability, test:
- AVAILABLE with valid value;
- UNAVAILABLE with reason;
- ERROR / malformed value;
- mixed availability across runs.

Analysis must not silently coerce unavailable values to zero.

## 8. Regression tests from foundation artifacts

At least one known foundation run should be converted into a stable regression fixture or compact synthetic equivalent.

Use it to verify that later analysis refactors preserve:
- decision/candidate joins;
- logical-vs-physical distinction;
- future lifecycle joins;
- block-slot reuse handling.

## 9. Acceptance

M6 formal profiling is test-ready when:
- scenario tests pass;
- dataset join tests pass;
- metric tests pass;
- no-future-leakage tests pass;
- capability missingness is explicit;
- the formal campaign can fail loudly on invalid evidence instead of producing a plausible-looking table.
