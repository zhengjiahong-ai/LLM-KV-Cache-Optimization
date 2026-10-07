# Phase 2A M4 — Rule Acceptance Protocol (executable)

Status: **FROZEN by M1 (2026-10-07, ruling item 4)**, implemented as code
Owner: M4
Implementation: `src/kvopt/costaware/acceptance.py`
Tests: `tests/test_costaware_acceptance.py`

This document records the frozen protocol and states exactly which part of it is
now enforced by code. The protocol was frozen *before* any holdout existed, so
that the acceptance metric cannot be re-chosen after a result is seen.

---

## 0. Governing rule

```text
Gate PASS != Rule Accepted
```

The Empirical Gap Gate (`docs/phase2a-empirical-gap-gate.md`) decides whether the
problem is worth attacking. It does **not** decide whether a specific rule wins.
Rule acceptance is governed by this protocol, separately.

---

## 1. The statistical unit

```text
seed repetition  -> runtime noise / reproducibility only, NOT an independent sample
statistical unit -> independent workload/scenario decision cluster
```

A cluster is `(scenario group, decision position)`, where the scenario group is
the `run_id` with its `-seed-NNN` suffix removed. Seeds inside a cluster are
**averaged first**, then the cluster is paired. This is what keeps the paired
counts summing to the cluster count instead of inflating with duplicate seeds.

Enforced by `cluster_paired_deltas()`; seeds cannot inflate the sample.

---

## 2. Holdout minimum (hard pre-condition)

```text
>= 30 independent decision clusters
covering all 6 formal families (F1..F6)
```

Below the floor, the result may only be labelled **`DIAGNOSTIC_ONLY`** — however
favourable its numbers look. `Gate PASS` does not lift this.

Enforced by `holdout_adequacy()`. In the verdict, an inadequate holdout is
checked **first** and produces `DIAGNOSTIC_ONLY` rather than `NOT_ACCEPTED`,
because "not enough data" is a different statement from "the rule lost".

---

## 3. Freeze-before-holdout requirement

Before the final holdout materializes, all five must be frozen:

```text
formula
direction
tie-break
fallback
acceptance metrics
```

Enforced by `RulePreregistration`, a required, validated record:

| Field | Meaning |
| --- | --- |
| `rule_id` | Identity of the rule under test |
| `family` | M0–M3 / H1 lineage |
| `formula` | The exact ordering, in words |
| `direction` | Ascending / descending per component |
| `tie_break` | Complete tie-break rule |
| `fallback` | Ordering used when a field is unavailable |
| `primary_metric` | Which metric decides the level (§4) |
| `frozen_at` | Date of the freeze |
| `frozen_commit` | Commit the freeze is anchored to |

Blank fields and an unknown `primary_metric` are rejected at construction, so an
unfrozen rule cannot be evaluated. `evaluate_acceptance()` takes the primary
metric **from the preregistration**, never from the caller — that is the
mechanism that stops a metric swap after a result is known.

---

## 4. Levels

### Level A — `PROXY_CANDIDATE`

Applies when only a proxy outcome is available. All four conditions must hold:

```text
cluster-level paired mean loss improvement > 0
cluster-level 95% CI lower bound > 0
better decisions > worse decisions
family improvement direction agreement >= 2/3
```

⇒ authorizes the label `PROXY_CANDIDATE` **only**. It does not authorize any
runtime claim.

### Level B — `RUNTIME_CANDIDATE`

Applies when direct recompute observation is available. The primary metric
becomes `actual recomputed_prefill_tokens`, with the same four conditions:

```text
cluster-level paired mean recompute reduction > 0
95% cluster-level CI lower bound > 0
better > worse
family direction agreement >= 2/3
```

plus:

```text
TTFT / serving latency must show no material regression
```

⇒ authorizes the label `RUNTIME_CANDIDATE`.

### Level C — `IMPLEMENTATION_ELIGIBLE`

```text
RUNTIME_CANDIDATE
+ interface review
+ novelty review
+ bounded runtime overhead
```

The three reviews are **human attestations** (`ImplementationAttestation`), never
inferred from data. Only after Level C does M4 return to M1 to request
authorization for a real runtime implementation.

---

## 5. The confidence interval

A **percentile bootstrap over clusters**, not over rows:

```text
resampling unit : cluster
iterations      : 10_000
confidence      : 95%
seed            : 20261007   (frozen)
```

The seed is part of the frozen protocol so the interval is reproducible and
cannot be re-drawn until it looks favourable. `AcceptanceCriteria.bootstrap_seed`
is recorded in the verdict payload alongside every interval.

Because the resampling unit is the cluster, a 60-row campaign with 20 clusters
yields an interval whose width reflects **20** observations, not 60.

---

## 6. Latency non-inferiority margin (`epsilon_latency`)

The margin **must not be chosen by hand**. It is calibrated from
baseline-vs-baseline repeated-run jitter:

```text
rule   : max absolute deviation of any baseline repeat from the baseline mean
input  : >= 3 repeated measurements of the baseline (identical configuration)
output : epsilon_latency, frozen before the holdout
```

Rationale: two *identical* baseline runs already differ by this much, so a
challenger inside that band has demonstrated nothing worse than run-to-run noise.
Deriving the margin this way removes the degrees of freedom that a hand-picked
"5% / 10%" would leave open.

Enforced by `calibrate_latency_epsilon()` (rejects fewer than 3 repeats and
non-finite values) and applied by `latency_non_inferior()`. The margin is an
input to the check and is **not adjustable** inside it.

⚠️ **This requires calibration data that does not exist yet** — it is a data
request to M6 (§8). Until it exists, Level B cannot be awarded, and the protocol
correctly returns `NOT_ACCEPTED` for a runtime-metric rule with no latency check.

---

## 7. What the code guarantees

| Guarantee | Enforced by |
| --- | --- |
| Seeds never inflate the sample | `cluster_paired_deltas` averages inside a cluster |
| Paired counts sum to the cluster count | same |
| The interval is reproducible | frozen `bootstrap_seed`, recorded in the payload |
| The metric cannot be swapped post-hoc | `primary_metric` comes from the preregistration |
| A small holdout cannot yield a candidate label | adequacy checked before any level |
| A rule that loses only in one family is still allowed | 2/3 threshold, tested both ways |
| A rule that loses in half the families is blocked | tested |
| Level B cannot pass without a latency margin | tested |
| Level C cannot be self-declared | requires `ImplementationAttestation` |
| The applied protocol is recorded | `AcceptanceVerdict.as_payload()` → `criteria` |

The verdict payload embeds the criteria it applied, so a report or a PR cannot
quote a result without also quoting the protocol that produced it.

---

## 8. Out of scope / open

| Item | Status |
| --- | --- |
| `epsilon_latency` calibration data (baseline repeats) | **Requested from M6** — does not exist yet |
| Direct recompute observation (Level B primary metric) | **Blocked on the observation seam** M1 approved |
| Holdout with ≥ 30 clusters over 6 families | **Blocked on H1's independent workload draw** |
| CLI wiring of the protocol | Deferred — lands with the H1-R1 registration (ruling item 5/2) |

### Why the current campaign cannot produce a candidate label

Measured on the canonical campaign:

```text
clusters                : 20      (floor is 30)
families present        : 6/6     ✓
```

⇒ any verdict computed on this data is `DIAGNOSTIC_ONLY`. The campaign is now
classified as **DISCOVERY / CHARACTERIZATION DATA** and must never serve as the
final holdout for a rule discovered on it.

---

## 9. Worked example (canonical campaign)

Both examples use the frozen defaults (`bootstrap_iterations=10000`,
`bootstrap_seed=20261007`). They are useful demonstrations that the protocol
reproduces, mechanically, conclusions the report previously had to argue in prose.

### 9.1 `M2_non_code_first` — looks positive, fails three checks

```text
level        : DIAGNOSTIC_ONLY
accepted     : False
clusters     : 20   (improved/worsened/tied = 1 / 0 / 19)
mean_delta   : +0.004437   CI [+0.000000, +0.013310]
family       : 1/6 agreeing, rate 0.167   (minimum 0.667)
failures     : holdout_adequate,
               cluster_ci_lower_bound_positive,
               family_direction_agreement
```

The CI lower bound lands exactly on `0.000000`, so the improvement is not
distinguishable from noise at this sample size — and the family-agreement check
independently catches the family-memorization the report §5.3 flagged
qualitatively.

### 9.2 `M1_marginal_cost_per_reclaimable` — fails every check

```text
level        : DIAGNOSTIC_ONLY
accepted     : False
clusters     : 20   (improved/worsened/tied = 6 / 6 / 8)
mean_delta   : -0.002308  CI [-0.039328, +0.035570]
family       : 3/6 agreeing, rate 0.500   (minimum 0.667)
failures     : holdout_adequate,
               cluster_mean_improvement_positive,
               cluster_ci_lower_bound_positive,
               better_decisions_outnumber_worse,
               family_direction_agreement
```

Equal better/worse counts, a negative mean, an interval spanning zero, and only
half the families agreeing — the same verdict the report reached by pairing
analysis, now reached by the frozen protocol without re-deriving it.

⚠️ In **both** cases the label is `DIAGNOSTIC_ONLY` rather than `NOT_ACCEPTED`,
because the holdout floor of 30 clusters is not met. That distinction is
deliberate: "not enough data to judge" is a different statement from "the rule
lost", and the protocol must not silently upgrade the first into the second.

---

## 10. Traceability

| Statement | Source |
| --- | --- |
| Cluster is the statistical unit; seeds are noise only | M1 ruling, item 4 |
| ≥ 30 clusters over all 6 families, else diagnostic | M1 ruling, item 4 |
| Freeze formula/direction/tie-break/fallback/metrics pre-holdout | M1 ruling, item 4 |
| Level A four conditions | M1 ruling, item 4 |
| Level B primary metric + latency non-inferiority | M1 ruling, item 4 |
| `epsilon_latency` from baseline-vs-baseline jitter, not hand-picked | M1 ruling, item 4 |
| Level C = B + interface/novelty/overhead reviews | M1 ruling, item 4 |
| `Gate PASS != Rule Accepted` | M1 ruling, item 4 opening |
| Gate is not a rule selector | M1 ruling, item 3 |
| Cluster definition | `offline_eval.scenario_group`, report §5.2.1 |
