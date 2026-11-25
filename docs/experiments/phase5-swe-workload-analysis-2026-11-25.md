# Phase 5 SWE Workload Structure — Metadata Analysis and Trace-Analysis Plan

**Status:** private trace-level analysis complete; no Cohort/Arrival change
**Cohort:** PR #138 frozen 48 Programs / 12 Groups
**Purpose:** understand the frozen SWE workload before execution; no Cohort, Group or Arrival re-selection

---

## 1. What can be concluded now

The frozen Group manifest supports the following structural facts:

- 48 Programs / 12 four-Program Groups;
- 10 repositories;
- every Group has at least 3 repositories and at most 2 Programs from one repository;
- provenance: 35 existing Phase 5 Programs + 13 fresh reacquisition Programs;
- terminal classes: 2 Natural Terminal + 46 Right-Censored.

The private normalized traces and exact token materializations were analyzed
in place. The private output is:

```text
SWE_TRACE_WORKLOAD_ANALYSIS = TRACE_ANALYSIS_COMPLETE
private analysis SHA-256 = b91b346f0ca20794631a62da3c9e719dc31681bd2039697a882747d6a3d2e2f1
```

No private trace or token payload is added to Git by this report.

### Frozen 48-Program trace summary

| Measure | Count | P50 | Mean | Max |
|---|---:|---:|---:|---:|
| Turns / Session | 48 | 100 | 96.06 | 100 |
| Prompt tokens | 4,611 | 9,818 | 10,607.36 | 32,093 |
| Adjacent exact LCP tokens | 4,563 | 9,708 | 10,518.97 | 31,875 |
| Adjacent block-aligned LCP tokens | 4,563 | 9,696 | 10,511.21 | 31,872 |
| Normalized adjacent prefix reuse | 4,563 | 0.9831 | 0.9751 | 0.9941 |
| Context growth tokens | 4,563 | 176 | 183.66 | 1,170 |
| Exclusive suffix proxy tokens | 4,563 | 176 | 183.66 | 1,170 |
| Adjacent request interval seconds | 4,563 | 0.2819 | 0.2790 | 8.2347 |
| Actual tool execution seconds | 2,860 | 0.2781 | 0.4209 | 8.2207 |
| Session duration seconds | 48 | 340.19 | 377.70 | 804.10 |

Across all 1,128 cross-Program first-request pairs, exact LCP P50 is 124
tokens and block-aligned LCP is 112 tokens. Under the frozen Poisson arrivals,
71 within-Group Program pairs have overlapping logical lifetimes. These are
trace-level opportunity measures only, not Native residency, Candidate
Exposure, eviction, recomputation or benefit evidence.

---

## 2. Frozen Group structure

| Group | Role | Programs | Repositories | Max per repo | Natural | Right-censored |
|---|---|---|---:|---:|---:|---:|
| SWE_G01 | Calibration | 4 | 3 | 2 | 0 | 4 |
| SWE_G02 | Calibration | 4 | 4 | 1 | 0 | 4 |
| SWE_G03 | Calibration | 4 | 3 | 2 | 1 | 3 |
| SWE_G04 | Calibration | 4 | 3 | 2 | 0 | 4 |
| SWE_G05 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G06 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G07 | Formal candidate | 4 | 3 | 2 | 1 | 3 |
| SWE_G08 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G09 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G10 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G11 | Formal candidate | 4 | 3 | 2 | 0 | 4 |
| SWE_G12 | Formal candidate | 4 | 3 | 2 | 0 | 4 |

Repository totals:

| Repository | Programs |
|---|---:|
| django | 23 |
| sympy | 9 |
| matplotlib | 4 |
| pydata | 3 |
| psf | 2 |
| pytest-dev | 2 |
| scikit-learn | 2 |
| pylint-dev | 1 |
| sphinx-doc | 1 |
| mwaskom | 1 |

### Interpretation

- All groups meet the frozen diversity rule.
- Django is structurally dominant (23/48). This is a workload-composition limitation that must be reported, not corrected by changing frozen membership.
- Only G03 and G07 contain a Natural Terminal program; no Group contains four Natural Terminal programs. This is the structural reason the right-censoring sensitivity is **NOT_ESTIMABLE**.
- Calibration G01/G02/G04 are all right-censored; G03 has one natural program. This affects interpretation, not the frozen membership.

---

## 3. Trace-level analysis plan

The analyzer is:

`scripts/spikes/phase5_dataset/analyze_swe_workload.py`

Example:

```bash
PYTHONPATH=src python scripts/spikes/phase5_dataset/analyze_swe_workload.py \
  --group-manifest docs/experiments/phase5-swe-cohort-data/swe-group-manifest.json \
  --arrival-manifest docs/experiments/phase5-swe-cohort-data/swe-frozen-poisson-arrival-manifest.json \
  --processed-root /path/to/private/phase5-swe-acquisition-processed-v5 \
  --processed-root /path/to/private/phase5-swe-historical-reacquisition-processed-v1 \
  --output /path/to/private/evidence/swe-workload-analysis.json
```

It computes:

1. **Turn and length**
   Per Session: Turn count, prompt token count, first/last growth, maximum and distribution.

2. **Prefix reuse**
   Consecutive exact token LCP and 16-token block-aligned LCP; normalized reuse ratio.

3. **Cross-Program structure**
   First-request LCP across all Program pairs, block-aligned LCP, positive-sharing pairs.

4. **Observed Tool Gap**
   `next_turn.submitted_at_seconds - current_turn.completed_at_seconds` in the same clock domain; missing/invalid intervals are reported, not zero-filled.

5. **Group context/suffix**
   Group-level distributions of prompt length, consecutive LCP, and observable exclusive suffix proxies.

6. **Arrival overlap**
   For each frozen Group, apply the stored Poisson start offsets and observed Session durations; count logical overlap intervals. This is a potential-contention description only.

7. **Public comparison**
   The analyzer records the PR #135/#136 reference values as external context, not as Phase 5 measurements.

The analyzer does not re-select Programs, Groups, Sessions or arrivals.

---

## 4. Public reference values for later comparison

From PR #135/#136:

```text
Public OpenHands initial input P50: 6,959 tokens
Public OpenHands final input P50:   50,606 tokens
Adjacent exact LCP P50:             30,940 tokens
Adjacent prefix reuse P50:          98.5%
Cross-issue first-request LCP P50:  5,816 tokens
Same-issue retry first-request LCP P50: 6,962 tokens
```

These are **public OpenHands/Qwen3 projections**, not Phase 5 SWE or Native measurements. The comparison will only ask whether the frozen Phase 5 workload has qualitatively similar long-context and prefix-sharing structure; differences will be reported, not “corrected”.

---

## 5. Why this analysis matters

It will help interpret:

- whether the SWE traces provide enough long-context and prefix-reuse opportunity for the retention hypothesis;
- whether Tool Gaps are long enough to make continuation protection plausible;
- whether Group members have different context/suffix profiles;
- whether frozen arrival overlap creates potential cache contention;
- whether the 2/46 natural/right-censored split is likely to dominate system-level results.

It will **not** establish:

- Native cache residency;
- legal candidate exposure;
- physical victim sets;
- actual downstream recompute;
- algorithm benefit.

Those remain M0–M5/Phase 5 runtime questions.

---

## 6. Result boundary

The analysis is complete for the frozen 48 Programs. It does not change the
frozen Cohort, Groups or Arrival. The high within-Session prefix reuse and
logical overlap support the workload's relevance to cache-retention research,
but only the future Native run can establish legal candidate exposure,
physical eviction and downstream recomputation.
