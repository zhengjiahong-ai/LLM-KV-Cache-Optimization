# Phase 5 Concurrent Dataset Construction

**Decision owner:** M1  
**Research design / independent qualification:** M4  
**Acquisition / engineering:** M6  
**Scope amendment:** [2026-11-24 M1 decision](phase5-scope-amendment-2026-11-24.md)  
**Status:** TWO DATA WORKSTREAMS AUTHORIZED IN PARALLEL  
**GPU execution:** NOT AUTHORIZED

## 1. M1 decision and work structure

The previous Phase 5 design treated SWE-bench and BFCL Web Search as two primary formal strata. M1 has superseded that scope.

The current work package constructs two datasets concurrently, with different research roles:

- **SWE-bench Verified — sole formal dataset.** Complete the real Agent Trace acquisition, exact Token Materialization, Q1–Q9 qualification, outcome-blind independent Program grouping, disjoint Calibration/Formal cohorts and Workload Seal.
- **BFCL Derived Controlled-Timing — supplementary dataset.** Complete the already accepted derived 4+8 Group partition and independent supplementary protocol. No new real-time BFCL formal-stratum acquisition is required.

There is no separate A-stage. These are parallel workstreams within one data-construction phase. After both packages are accepted, proceed to D (unified system/protocol/Native gates), then E (experiment execution).

## 2. SWE-bench — sole formal stratum

Use the accepted SWE-bench Verified task revision and pinned mini-SWE-agent acquisition path. Reuse existing collection infrastructure; do not reopen source selection absent a concrete provenance problem.

The latest read-only reconstruction (PR #129) identified:
- 75 acquisition attempts;
- 57 unique processed Sessions;
- 35 candidate Sessions after applying minimum-Turn, context, terminal and evidence rules: 2 natural completions + 33 explicitly step-limit right-censored Sessions;
- 14 context failures, 3 infrastructure failures and 5 below-minimum Sessions remain excluded.

These 35 are not yet M4-accepted qualified Programs. Preserve explicit right-censor status; do not relabel censored sessions as natural completion. The accepted removal of the arbitrary 16-Turn ceiling (PR #131) remains in force: minimum 4 Turns, exact token evidence, Prompt ≤32,640 tokens, Prompt + frozen generation budget ≤32,768 tokens, and all other Q1–Q9 constraints remain binding.

Formal design:
- 4 distinct Programs per Group;
- 4 disjoint Calibration Groups (16 Programs), 3 repeats per system;
- Formal N selected by the accepted single-stratum Calibration method, minimum 8 / target 12 / maximum 16 Groups, 2 repeats per system;
- at least 48 independent qualified Programs for the minimum 4 Calibration + 8 Formal Groups;
- Calibration and Formal Groups must be disjoint;
- Workload Group is the independent statistical unit.

If all 35 current candidates qualify, they provide at most 8 Groups and at least 13 additional independent qualified Programs are still needed to reach the 48-Program minimum. M4 must recompute the gap after final identity and Q1–Q9 review. Historical W1-C ledger-only records are not automatically promoted. Reserve promotion remains outcome-blind.

M6 continues acquisition, raw evidence preservation, normalization, Token Materialization and Q1–Q9. M4 independently reviews provenance, censoring, semantic completeness, Program independence, outcome blindness and disjoint Cohorts.

## 3. BFCL — supplementary Derived Controlled-Timing dataset

Do not acquire a new BFCL real-time formal stratum to satisfy the superseded two-stratum design.

Accepted parent asset and candidate inventory:
- 199 accepted semantic Sessions;
- 40 context-excluded Sessions / 63 Requests;
- 159 derived-eligible Sessions;
- 88 independent source-question Programs;
- 22 candidate Groups, 12 minimum-Turn-applicable and 10 unqualified without replacement.

M1-frozen partition (Issue #132):
- Derived Calibration: G02, G10, G14, G19 (4 Groups / 16 Programs);
- Derived Evaluation: G04, G05, G12, G13, G16, G17, G21, G22 (8 Groups / 32 Programs).

M6 creates child partition manifests, per-Program paired-mode links, lineage/hash bindings and disjointness validators. Do not mutate the accepted parent inventory. Paired SNIPPET/NO_SNIPPET alternatives stay attached to their source Program and do not count as independent Programs.

M4 prepares a short, standalone supplementary protocol and performs independent review. Four Calibration Groups are descriptive only; eight Evaluation Groups are exploratory, not confirmatory. The study remains labelled `BFCL_DERIVED_CONTROLLED_TIMING`, preserves synthetic Tool Gap and `SOURCE_TERMINAL_UNKNOWN` / `REPLAY_TRACE_EXHAUSTED` semantics, and cannot establish natural-time workload benefit or replace SWE formal evidence.

## 4. Ownership and coordination

**M6**
1. Continue SWE formal dataset acquisition and qualification pipeline.
2. In parallel, finish the BFCL Derived 4+8 child partition package.
3. Preserve raw evidence, failures, exclusions, provenance and hashes.
4. Submit both workstream artifacts with separate manifests and status reports.

**M4**
1. Independently qualify SWE Q1–Q9 and construct disjoint Calibration/Formal Groups.
2. Independently review SWE Program identity, censoring, provenance, outcome blindness and Workload Seal.
3. Prepare the BFCL Derived supplementary protocol and independently review its partition.
4. Submit separate qualification reports; do not merge the inferential populations.

**M1**
M1 accepts the two packages separately. Once both are accepted, the project moves to D. No step-by-step approval is required for routine, reversible acquisition and packaging work already authorized.

## 5. Required deliverables

### SWE formal package
- source and acquisition-attempt inventory;
- immutable raw traces and SHA-256;
- normalized traces and adapter identity;
- exact Token Materialization and model/tokenizer/template hashes;
- Q1–Q9 per-Session evidence and exclusions;
- independent Program and Group manifests;
- disjoint Calibration/Formal manifests;
- censoring/missingness/yield report;
- Workload Seal, Arrival Plan and provenance manifest;
- independent M4 qualification report.

### BFCL supplementary package
- Calibration and Evaluation child manifests;
- Program/Session/Mode identities and paired alternative ledger;
- parent manifest, Seal, lineage and context-exclusion hash bindings;
- disjointness/exact-count validator;
- supplementary protocol, run-matrix proposal and statistical/claim boundaries;
- independent M4 review and SHA-256 manifest.

## 6. Non-authorizations

This work package does not authorize:
- Phase 5E Part A/B Native GPU Conformance;
- SWE Calibration or Formal execution;
- BFCL Derived GPU execution;
- a formal BFCL Native Stratum;
- use of BFCL Derived Groups in SWE Formal or Calibration;
- any 72–112 GPU-hour reservation or execution.

The old two-stratum Formal Protocol/JSON and its 144-run Calibration plan are superseded for current execution but remain immutable history until a coordinated protocol/engineering amendment is accepted.
