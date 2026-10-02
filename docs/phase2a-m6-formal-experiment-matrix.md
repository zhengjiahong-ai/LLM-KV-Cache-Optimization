# Phase 2A M6 Formal Experiment Matrix

Status: EXECUTION SPECIFICATION

## 1. Purpose

This matrix defines the minimum coverage M6 must achieve in formal profiling before handing evidence to M4.
It is deliberately broader than the P0-P3 foundation suite.

The matrix is not a fixed paper benchmark yet. M6 may refine exact concrete values after bring-up, but may not silently remove an axis.

## 2. Campaign structure

Formal profiling is organized into six experiment families.

### F1 — Prevalence and candidate-set structure

Goal: measure how often the target forced-release problem appears and what decision sets look like.

Required variation:
- candidate count: 2, medium (>2), higher-contention;
- homogeneous and heterogeneous prefix sizes;
- shallow and deeper pressure shortages;
- at least one repeated-pressure trace.

Required outputs:
- forced-release events per run / per request;
- candidate-count distribution;
- required-blocks / shortage distribution;
- number of logical releases per pressure decision;
- repeated-release frequency for the same logical object.

### F2 — Cost heterogeneity

Goal: characterize within-decision variation in recomputation-related cost.

Required variation:
- homogeneous prefix sizes;
- mixed 128/256/512-token materialized prefixes where supported;
- at least one decision with a large within-set size spread;
- multiple candidate-set sizes.

Required outputs:
- candidate block/token footprint distribution;
- PrefillReload distribution;
- within-decision cost spread;
- relation between logical size, physical eviction, and eventual recomputation.

### F3 — Reuse / return heterogeneity

Goal: characterize future reuse behavior independently from prefix size.

Required variation:
- early return;
- late return;
- no return within at least one predeclared horizon;
- repeated multi-turn returns;
- interleaved follow-ups across multiple programs.

Required outputs:
- return probability by horizon;
- time-to-return distribution;
- repeated-return counts;
- candidate-level realized reuse labels derived offline.

### F4 — Pressure severity and repeated contention

Goal: understand whether the optimization problem changes under deeper shortages.

Required variation:
- shortage requiring only a small marginal release;
- shortage requiring multiple logical releases or many newly eligible blocks;
- repeated pressure stages before all programs complete.

Required outputs:
- logical releases per event;
- newly eligible blocks per release;
- actual physical evictions;
- divergence between logical release volume and physical eviction volume.

### F5 — Queue / timing / concurrency state

Goal: test whether queue and lifecycle state provide useful online signals.

Required variation:
- low and higher waiting population;
- staggered and overlapping arrivals;
- different tool-gap patterns;
- different queue-delay states;
- at least two return-order patterns under the same prefix-size assignment.

Required outputs:
- planned versus observed arrival timing;
- queue-delay inputs at decision time;
- association between timing/lifecycle signals and realized loss;
- serving timing outcomes where the backend exposes valid landmarks.

### F6 — Cache-structure and identity robustness

Goal: make sure analysis is valid under native cache behavior, not only clean synthetic ownership.

Where supported, include:
- physical block-slot reuse;
- overlapping/shared ownership;
- evolving prefixes across turns;
- repeated eviction of the same physical block ID holding different content over time.

Required outputs:
- ambiguity rate if joining only by block_id;
- content/owner attribution coverage where available;
- explicit unavailable coverage where attribution is not safe.

## 3. Cross-product policy

M6 does not need a full Cartesian product of all dimensions.

Instead, every axis above must appear in multiple contexts, and each major conclusion must be supported by more than one workload family.

Minimum expectations:
- >= 3 candidate-set scales represented;
- >= 3 pressure severities represented;
- >= 3 reuse-lifecycle patterns represented;
- homogeneous and heterogeneous cost cases;
- multiple seeds / repetitions for every formal scenario family;
- enough valid multi-candidate decisions to satisfy the Empirical Gap Gate with margin, not exactly at the minimum.

## 4. Repetition and validity

M6 chooses repetitions based on runtime cost and variance, but must:
- predeclare the repetition count for each family;
- record invalid/failed runs rather than replacing them silently;
- separate infrastructure failure from scenario-invalidity;
- preserve all provenance needed to reproduce a run.

A decision is valid for candidate-level analysis only if:
- candidate_count >= 2;
- the decision snapshot is complete;
- selected release(s) are traceable;
- post-decision lifecycle is traceable;
- required capability missingness is explicit.

## 5. Foundation suite relationship

The P0-P3 30-run suite is a prerequisite sanity layer.

It may be reused for:
- schema tests;
- join tests;
- metric unit tests;
- timing plumbing validation;
- examples in debugging.

It is not the formal experiment matrix and should not dominate aggregate statistics.

## 6. M6 implementation freedom

M6 may choose:
- exact larger candidate counts;
- exact repeated-pressure schedules;
- exact horizon values;
- exact scenario-generator structure;
- exact storage format for derived tables;
- plotting implementation.

M6 may not change without review:
- raw event semantics;
- online-vs-future information boundary;
- canonical decision/candidate join keys;
- meaning of logical release versus physical eviction;
- requirement that formal evidence, not foundation tests, drives M4 design.
