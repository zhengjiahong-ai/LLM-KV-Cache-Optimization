# Phase 5 Scope Amendment — SWE Formal Campaign + BFCL Derived Supplement

**Decision owner:** M1  
**Decision date:** 2026-11-24  
**Status:** M1 research-scope decision accepted; documentation synchronization in progress  
**Supersedes:** The two-primary-strata scope in the Phase 5 v1 design documents, for all future Phase 5 planning and execution.

## 1. M1 decision

Phase 5 will proceed with two data-construction workstreams in parallel, but they have different inferential roles:

1. **SWE-bench Verified — the sole formal workload stratum.** It supports the pre-registered six-system formal campaign and its confirmatory claims, subject to the final single-stratum protocol amendment, qualification, Cohort Seal and execution gates.
2. **BFCL Derived Controlled-Timing — an independent supplementary experiment.** It uses the already accepted derived semantic asset and candidate Group inventory. It does not become a formal stratum and does not contribute Groups, Calibration estimates, sample size, power, multiplicity families or confirmatory claims to the SWE campaign.

The two data packages are to be completed concurrently. There is no separate A-stage for BFCL: its 4+8 partition and supplementary protocol are part of the same data-construction phase.

After both data packages are accepted, the project proceeds to **D — unified system / Native execution gates**, then **E — experiment execution**. GPU execution remains separately gated by M1.

## 2. Data workstreams

### 2.1 SWE-bench Verified — formal dataset

M6 continues the already approved SWE acquisition and qualification workflow. M4 independently reviews Q1–Q9 evidence, source lineage, censoring, outcome blindness, Group independence and Cohort membership.

The latest read-only reconstruction in PR #129 reports 57 processed Sessions from 75 attempts. Under the M1-accepted removal of the arbitrary 16-Turn ceiling (implemented by merged PR #131), 35 Sessions remain candidates under the stated terminal/context/minimum-Turn rules: 2 natural completions and 33 explicitly step-limit right-censored Sessions. The 14 context failures, 3 infrastructure failures and 5 Sessions below 4 Turns remain excluded.

These 35 are **candidate Sessions, not an M4-accepted formal Cohort**. They provide at most 8 four-Program Groups if all distinct Program identities and remaining Q1–Q9 rules pass. The formal design minimum is 12 total Groups per sole stratum (4 Calibration + 8 Formal = 48 distinct qualified Programs). Therefore, at least 13 additional independent, qualified Programs are needed even under the optimistic assumption that all 35 current candidates qualify. The exact shortfall must be recomputed after M4's final qualification and identity audit. Reserve use remains outcome-blind and follows the frozen sampling frame; historical W1-C ledger-only candidates are not automatically promoted.

### 2.2 BFCL — supplementary Derived experiment

BFCL is no longer a formal workload stratum. Do not initiate a new real-time BFCL Native Stratum acquisition pipeline to satisfy the old two-stratum Formal Protocol.

The accepted derived asset remains bounded as `BFCL_DERIVED_CONTROLLED_TIMING`:
- 199 accepted semantic Sessions;
- 40 context-excluded Sessions / 63 Requests;
- 159 derived-eligible Sessions;
- 88 independent source-question Programs;
- 22 candidate Groups, of which 12 satisfy the minimum-Turn applicability check and 10 remain unqualified without deletion or substitution.

M1 has selected the independent 4+8 plan in Issue #132:
- Derived Calibration: G02, G10, G14, G19 (4 Groups / 16 Programs);
- Derived Evaluation: G04, G05, G12, G13, G16, G17, G21, G22 (8 Groups / 32 Programs).

M6 creates child partition manifests and hash bindings without modifying the accepted parent inventory. M4 prepares the separate supplementary protocol and independently reviews the package. These tasks proceed in parallel with SWE dataset completion.

The BFCL Derived experiment uses controlled synthetic Tool Gaps and preserves `SOURCE_TERMINAL_UNKNOWN` / `REPLAY_TRACE_EXHAUSTED` semantics. Its four Calibration Groups are descriptive only; its eight Evaluation Groups are exploratory, not confirmatory. It is not formal BFCL Q1–Q9 PASS, not a Native BFCL Stratum, and not evidence of natural-time workload benefit. Its results must be reported separately.

## 3. Formal campaign design after scope amendment

The six-system comparison remains unchanged:
Native vLLM, Continuum Official, Continuum Adapted (A0), A1 Original, A3 Suffix and DVA-ER v1, subject to each system's existing conformance/freeze gate.

Only the formal workload scope changes: **SWE-bench is the sole formal stratum**. Calibration and Formal Groups are built only from the independently qualified SWE cohort and remain disjoint.

The existing per-stratum design rules remain:
- 4 Calibration Groups, 3 repeats per system;
- Formal N selected by the pre-registered calibration method, with 8 minimum, 12 target, 16 maximum Groups;
- 2 repeats per system per Formal Group;
- four distinct Programs per Group;
- Workload Group is the independent statistical unit.

### Single-stratum run counts

For six systems:
- Calibration: `6 × 4 × 3 = 72` runs.
- Formal: `6 × N × 2 = 12N` runs:
  - N=8: 96 runs;
  - N=12: 144 runs;
  - N=16: 192 runs.
- Total including Calibration: 168 / 216 / 264 runs at minimum / target / maximum.

These are design counts, not execution authorization. The BFCL Derived run matrix and resource budget are separate and must be specified in its supplementary protocol before any M1 execution decision.

## 4. D — unified system and Native execution gates

After M1 accepts both data packages, complete the remaining system gates as one coordinated D work package:

- DVA-ER v1 formal candidate selection and freeze;
- Continuum Adapted (A0) Scheduler Conformance and final label;
- Continuum Official compatibility/environment audit;
- final Arrival parameters and Seed freeze;
- single-formal-stratum protocol/schema/validator/runner/calibration/campaign-plan adaptation;
- regenerated formal execution manifests and code/config identity;
- Phase 5E Part A Native/GPU Conformance on the authorized clean main;
- final system readiness and resource projection.

Phase 5E Part B Abort Conformance remains separate and is not a prerequisite for Part A unless a concrete dependency is demonstrated. No GPU step is authorized merely by this scope amendment.

## 5. E — execution sequence

After D gates pass and M1 separately authorizes execution:

1. Run the single-stratum SWE Calibration (72 runs).
2. Independently evaluate Calibration, select Formal N under the frozen method, and freeze the SWE Formal plan.
3. Run the SWE six-system Formal Campaign (96–192 runs depending on N).
4. Run the BFCL Derived Calibration and Evaluation only under its own accepted protocol and separate authorization/budget. It may run in the same broad execution period, but its Groups and analysis never mix with SWE Formal.
5. Independently evaluate, archive and report each study with its own estimand and claim boundary.

## 6. Required protocol/engineering reconciliation

The existing Phase 5 v1 prose, machine-readable JSON, schemas, validators, campaign planner and Calibration backend were built for two formal strata. This M1 scope amendment does not silently rewrite their hash-bound identities.

Before D is declared complete, M4/M6 must submit a coordinated protocol-amendment PR that:
- defines the sole formal stratum as SWE-bench;
- removes BFCL from formal-stratum enumerations and formal Cohort/sample-size calculations;
- changes the formal Calibration matrix from 144 to 72 runs;
- changes Formal run planning to 96/144/192 for N=8/12/16;
- updates the fixed-effect/variance model and all df/covariance/bootstrap/noncentral-t inputs for one stratum, rather than merely changing displayed run counts;
- updates protocol JSON, schemas, validators, calibration/campaign code, manifests, documentation and tests consistently;
- preserves the separate BFCL Derived protocol and all accepted BFCL derived artifacts;
- leaves historical two-stratum design records and sealed artifacts immutable, clearly marked superseded for current execution.

No one may execute the old two-stratum JSON or old 144-run Calibration plan as though it implements this amendment.

## 7. Current authorization boundary

Authorized now:
- concurrent SWE formal-dataset completion and BFCL Derived supplementary-package completion;
- routine acquisition, normalization, Token Materialization, qualification, deterministic partitioning, documentation and independent review already covered by the respective M1 decisions.

Not authorized:
- Phase 5E Native/GPU Conformance;
- SWE Calibration or Formal Campaign;
- BFCL Derived GPU execution;
- any formal BFCL Native Stratum;
- any use of BFCL Derived Groups in SWE Calibration/Formal;
- any claim of algorithmic benefit before the relevant independent evaluation is completed.

**Current sequence:** concurrent data construction → D unified system/protocol/Native gates → E independently authorized experiments.
