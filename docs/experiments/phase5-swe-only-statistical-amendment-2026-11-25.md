# Phase 5 SWE-only Statistical Amendment and Mechanism Analysis

**Status:** M1 accepted the research direction on PR #139; contract values are normative for M6 D-stage implementation, subject to final integrated M1 acceptance.  
**Decision authority:** M1  
**Scope:** SWE-bench Verified sole formal stratum; BFCL Derived remains an independent supplementary experiment.  
**Preserved:** PR #138 Cohort membership, Group construction, Arrival realization; `E−C` primary metric; Workload Group independent unit.  
**Not authorized:** GPU, Calibration, Formal Campaign, or algorithm-benefit claims.

---

# 1. Normative single-stratum design

## 1.1 Run design

| Partition | Groups | Systems | Repeats | Runs |
|---|---:|---:|---:|---:|
| Calibration | 4 | 6 | 3 | **72** |
| Formal N=8 | 8 | 6 | 2 | **96** |
| Formal N=12 | 12 | 6 | 2 | **144** |
| Formal N=16 | 16 | 6 | 2 | **192** |

Combined totals:

```text
168 / 216 / 264 runs
```

The existing two-stratum values (144 calibration; 192/288/384 formal) are obsolete for the current SWE-only design.

## 1.2 Variance model

For one formal stratum and repeated Group-level paired differences:

```text
d_{g,r} = μ + b_g + ε_{g,r}
b_g ~ (0, σ_between²)
ε_{g,r} ~ (0, σ_repeat²)
```

No stratum fixed effect. No cross-stratum pooling.

## 1.3 Degrees of freedom

With 4 Calibration Groups and 3 repeats:

```text
df_between = 4 − 1 = 3
df_within  = 4 × (3 − 1) = 8
df_total   = 11
df_covariance = 3
```

Estimators:

```text
SS_between = Σ_g (mean_r d_{g,r} − overall_mean)²
SS_within  = Σ_g Σ_r (d_{g,r} − mean_r d_{g,·})²

σ_repeat²_hat = SS_within / 8
σ_between²_hat = max(0, SS_between/3 − σ_repeat²_hat/3)
σ_d² = σ_between²_hat + σ_repeat²_hat/2
```

The existing `df_between=6`, `df_within=16`, `df_total=22`, `df_covariance=6` are invalid for the SWE-only design.

## 1.4 Covariance and rank limit

The six candidate contrasts plus two system-context contrasts still form an 8×8 contrast covariance.

With only 4 Calibration Groups, the centered Group-difference vectors have dimension at most 3:

```text
rank(Σ_contrast) ≤ 3
```

Therefore:

- the 8×8 covariance cannot be treated as full-rank;
- do not invert it;
- use PSD projection and a pseudoinverse or simulation/interval propagation;
- `df_covariance=3`;
- candidate sizing uses the maximum candidate-contrast variance upper bound;
- report the rank limitation explicitly.

This is a structural limitation of 4 Calibration Groups, not a bug.

## 1.5 Power, MDE and multiplicity

Preserved:

```text
E−C primary metric
MDE = max(512 tokens, 5% × calibration Native Group mean)
α per candidate test = 0.05 / 6
power = 0.80
six candidate contrasts in one Holm family
two system-context contrasts in a separate family
noncentral-t, no z approximation
formal N = 8 / 12 / 16, minimum 8
```

Single stratum removes the per-stratum duplication of families and the two-stratum common model.

## 1.6 Resource formula

Replace `24` calibration runs/system with `12`:

```text
GPU_hours =
  (1 + failure_reserve_fraction)
  × Σ_s (
      12 × Tcal_s
    + 4N × Tformal_s
    + (12 + 4N) × (startup_s + restart_s + archive_s + evaluator_s)
    ) / 3600
```

At the 600s hard ceiling, the pure run-time range is approximately:

```text
168 runs × 600s = 28.0 h
264 runs × 600s = 44.0 h
```

The old 72–112 GPU-hour envelope was sized for the 336–528 run two-stratum campaign. M1 must set a new envelope after M6 measures startup/restart/archive/evaluator overhead; do not reuse the old reservation unchanged.

## 1.7 Current materialization limit

Current 48 Programs produce exactly:

```text
4 Calibration Groups + 8 Formal Candidate Groups
```

Thus:

```text
formal N = 8 is materializable
formal N > 8 is not materializable without additional outcome-blind data
```

If Calibration selects N>8:

```text
STOP_AND_RETURN_TO_M1
```

Do not reuse Calibration Groups, create pseudo-replicates, or lower power.

---

# 2. Right-censoring

## 2.1 Primary analysis

Keep all qualified Sessions with valid observed Turns, including right-censored Sessions. Do not impute future Turns. Do not upgrade a right-censored Session to natural completion.

## 2.2 Sensitivity analysis

Current data:

```text
Natural Terminal = 2
Right-Censored = 46
```

A sensitivity analysis excluding right-censored Sessions leaves only 2 Programs. A Group requires 4 independent Programs. Therefore:

```text
SWE_RIGHT_CENSORING_SENSITIVITY = NOT_ESTIMABLE
reason = NO_COMPLETE_FOUR_PROGRAM_GROUP_AFTER_EXCLUSION
```

Report:

- the proportion and causes of right-censoring;
- the 2 natural-terminal Program descriptions;
- the primary analysis with censored Sessions;
- the explicit non-estimability of the group-level sensitivity.

Do not create a “sensitivity Group” from fewer than four Programs.

---

# 3. M0–M5 mechanism analysis

M0–M5 are an **observation and interpretation framework**, not a sequence of pre-execution gates. A null at one level is a result, not a reason to stop the campaign.

## 3.1 Levels

| Level | Observation | Unit | Claim boundary |
|---|---|---|---|
| **M0** | legal candidates, fully scored candidates, multi-candidate decisions | decision | Is there decision space? |
| **M1** | score distribution, rank inversion, selection divergence | decision, within same snapshot | Did the algorithm make a different choice? |
| **M2** | predicted victim sequence / predicted victim-set divergence | decision | Did the choice imply different physical targets? |
| **M3** | matched/unmatched actual physical victims | decision + Native evidence | Did Native actually evict different blocks? |
| **M4** | observed downstream reuse/recompute | decision + later requests | Did the different victims change later reuse? |
| **M5** | Group-level E−C and serving metrics | Workload Group | Did a system-level effect occur? |

M2–M4 are **observational and associational** unless a comparable intervention isolates the effect. A predicted/actual victim match proves prediction consistency, not downstream causal attribution.

## 3.2 Reporting rule

For every experiment, report the level reached:

```text
M0_DECISION_SPACE = PASS / FAIL / NOT_OBSERVABLE
M1_SELECTION_DIVERGENCE = ...
M2_PREDICTED_VICTIM_DIVERGENCE = ...
M3_ACTUAL_PHYSICAL_EVICTION = ...
M4_DOWNSTREAM_RECOMPUTE = ...
M5_SYSTEM_EFFECT = ...
```

A null at M1–M4 does not invalidate the system-level M5 experiment. It explains why an observed M5 difference may be absent.

## 3.3 Required denominators

- `legal_candidate_count`
- `fully_scored_candidate_count`
- `multi_candidate_decision_count`
- `selection_divergence_count`
- `predicted_victim_divergence_count`
- `physical_victim_match_count` / `unmatched_count`
- `downstream_reuse_observed_count`
- `evidence_coverage`

All are descriptive by decision and aggregated by Group/System. Do not treat decisions as independent statistical replicates.

## 3.4 Metrics Contract boundary

No new composite “mechanism score”. Preserve:

```text
physical_causal_attribution = NOT_ESTABLISHED
downstream_recompute_attribution = NOT_ESTABLISHED
```

until M3/M4 evidence is complete. The system-level paired experiment and the decision-level mechanism analysis keep separate claim boundaries.

---

# 4. DVA-ER research boundary

## 4.1 H parameter

```text
H_60s = DESIGN_PRIOR_NOT_CALIBRATED
```

Basis: Phase 4 60s proxy and engineering prior; not a calibrated Native waiting-time estimate.

Use:

```text
primary report: H=60s
sensitivity: H=30s, H=120s
no post-outcome H selection
no separate GPU arm for H sensitivity
```

Sensitivity reports changes in ranks, selection, predicted victim set, and observed physical/downstream outcomes at the same decision snapshots.

## 4.2 Pre-run requirements

DVA-ER may enter the formal experiment when the following are confirmed:

- implementation correctness;
- real, legal decision inputs;
- no future information leakage;
- Native victim simulation matches the Native mechanism;
- required data are actually collectable;
- cross-system comparability.

It is **not** required to prove predictive validity before the experiment. Predictive validity, decision divergence, physical divergence and downstream benefit are research questions.

## 4.3 Information added over A1/A3

DVA-ER adds:

- predicted Native LRU victim sequence after candidate release;
- active follow-up chain / pending tool-gap risk over those victims;
- A0 order only as a tie-break.

It does not add source-observed future requests or actual Native execution.

## 4.4 Decision-difference conditions

A different DVA-ER selection can change the physical victim set only when:

1. at least two legal candidates exist;
2. their predicted victim prefixes differ;
3. follow-up risk coverage differs;
4. the selection changes;
5. Native executes the predicted difference.

If no difference is observed, classify:

```text
NO_MULTI_CANDIDATE
SAME_PREDICTED_VICTIM_SET
SAME_RISK_MASK
SAME_SELECTION
SAME_PHYSICAL_VICTIM
SAME_DOWNSTREAM_REUSE
NO_OBSERVED_FOLLOWUP
INSUFFICIENT_EVIDENCE
```

Do not collapse these into “DVA-ER ineffective”.

---

# 5. BFCL Derived supplement

BFCL Derived remains separate:

```text
4 Calibration Groups = descriptive only
8 Evaluation Groups = exploratory only
```

It does not contribute to SWE Calibration, sample size, power, multiplicity, or confirmatory claims.

Permitted questions:

- instrumentation and evidence-contract feasibility;
- controlled-timing decision-space and mechanism observations;
- exploratory E−C/decision differences under a fixed synthetic schedule;
- sensitivity to decision thresholds and candidate geometry.

Not permitted:

- natural Tool Gap distribution claims;
- natural terminal/completion claims;
- BFCL Native stratum claims;
- pooled SWE+BFCL estimates;
- GPU/Native benefit claims.

Limits to report:

```text
SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED
SOURCE_TERMINAL_UNKNOWN
REPLAY_TRACE_EXHAUSTED
40 context-excluded Sessions
10 minimum-Turn-unqualified Groups
```

---

# 6. SWE workload analysis

The requested trace-level analysis needs the private normalized traces and token materializations. The current public repository contains Group/identity metadata but not the private Session content.

A reusable analyzer is provided at:

`scripts/spikes/phase5_dataset/analyze_swe_workload.py`

It consumes the private processed evidence root and the frozen Group manifest and reports:

- Turn count, prompt length, growth;
- consecutive exact token LCP and 16-token block-aligned LCP;
- cross-Program first-request LCP and exclusive suffix;
- observed tool-gap distribution;
- Group-level context/suffix distributions;
- Frozen-Poisson lifecycle overlap and potential cache contention;
- comparison with the public Nebius summaries.

The analyzer does not re-select the Cohort or alter the frozen Groups/Arrival. Until the private root is mounted, the report field is:

```text
SWE_TRACE_WORKLOAD_ANALYSIS = PENDING_PRIVATE_EVIDENCE_ROOT
```

Metadata-level structural results already available from the frozen Group manifest:

- 48 Programs, 12 Groups, 10 repositories;
- every Group has at least 3 repositories and at most 2 Programs from one repository;
- 2 Natural Terminal and 46 Right-Censored Programs;
- Calibration: SWE_G01–G04; Formal candidate: SWE_G05–G12.

These metadata results do not substitute for trace-level context/reuse/tool-gap analysis.

---

# 7. Required M6 implementation changes

## 7.1 Protocol / calibration

- `strata = 1` / SWE-only formal contract;
- calibration 4 Groups, 72 runs;
- formal 96/144/192 at N=8/12/16;
- variance model without stratum fixed effect;
- `df_between=3`, `df_within=8`, `df_total=11`, `df_covariance=3`;
- covariance rank warning and PSD/pseudoinverse handling;
- resource formula `12` calibration runs/system;
- run-count validators, schema constants, archive/freeze code, campaign planner, tests;
- old two-stratum values are rejected, not silently ignored.

## 7.2 Metrics / Evaluator

- keep `E−C` primary and Group unit;
- add M0–M5 fields/reporting as observational layers;
- require denominators/evidence coverage;
- no new composite causal score;
- keep `physical_causal_attribution` and `downstream_recompute_attribution` not established;
- report `SWE_RIGHT_CENSORING_SENSITIVITY = NOT_ESTIMABLE`.

## 7.3 DVA-ER

- mark H=60s design prior;
- 30/120 sensitivity at same snapshots;
- no pre-run predictive-validity gate;
- pre-run requirements limited to correctness, legal inputs, no future leakage, Native mechanism match, collectability, comparability;
- no separate H GPU arm.

## 7.4 BFCL

- separate protocol/reporting contract;
- 4 descriptive, 8 exploratory;
- no formal N/power/multiplicity;
- no pooling with SWE.

## 7.5 Workload analyzer

- run on private processed root;
- output JSON + Markdown;
- no re-selection, no Group/Arrival change;
- public Nebius comparison only as external reference.

---

# 8. Preserved decisions

```text
SWE = sole formal stratum
BFCL Derived = independent supplement
PR #138 Group/Arrival = unchanged
E−C primary = unchanged
Workload Group independent unit = unchanged
Right-censored primary inclusion = unchanged
Formal N=8 currently; N>8 requires M1 data decision
```

No GPU, Calibration, Formal Campaign or algorithm-benefit claim is authorized by this document.
