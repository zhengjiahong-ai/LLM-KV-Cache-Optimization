# Phase 2A M4 — Rule Acceptance Protocol (executable)

Status: **FROZEN by M1 (2026-10-07)**, implemented as code
Owner: M4
Implementation: `src/kvopt/costaware/acceptance.py`
Tests: `tests/test_costaware_acceptance.py`

The protocol was frozen *before* any holdout existed, so the acceptance metric
cannot be re-chosen after a result is seen. This document records the frozen
protocol and states exactly which part of it is enforced by code.

---

## 0. Governing rule

```text
Gate PASS != Rule Accepted
```

The Empirical Gap Gate (`docs/phase2a-empirical-gap-gate.md`) decides whether the
problem is worth attacking. It does **not** decide whether a specific rule wins.
Rule acceptance is governed by this protocol, separately.

---

## 1. The statistical unit: one independent scenario draw

```text
seed repetition  -> runtime noise / reproducibility only, NOT an independent sample
decision position inside one scenario -> NOT an independent sample
statistical unit -> one independent scenario draw
```

**A scenario is one independently designed workload.** Two decisions inside it
share that workload, so they are not two observations.

Aggregation order, which is the whole point:

```text
1. average the seed repeats inside each decision position;
2. average those position means inside each scenario;
3. resample and pair at the scenario level.
```

Only step 3's output counts. Reversing steps 1 and 2 would weight a
position with more seeds more heavily; skipping step 2 would count one workload
twice.

Enforced by `scenario_paired_deltas()`. The decision-position view survives as
`cluster_paired_deltas()`, marked `SCOPE_DECISION_CLUSTER`, **diagnostic only** —
it localises *where* inside a scenario a difference arises, and is never the unit
of the floor or the interval. Every result payload carries its `scope` string so a
diagnostic view can never be presented as the draw-level result.

### 1.1 What this changed on the discovery campaign

| View | Units |
| --- | ---: |
| Raw decision rows | 60 |
| Decision-position clusters (diagnostic) | 20 |
| **Independent scenario draws (the unit)** | **18** |
| Unique decision patterns | 9 |

The correction is not cosmetic: two scenarios contribute two decisions each, so
the cluster view double-counts them. Measured on the canonical campaign the same
comparison reads:

```text
scenario-draw level : 8 improved / 3 worsened / 7 tied   mean +0.016086
decision-position   : 8 improved / 5 worsened / 7 tied   mean +0.014797
```

Same direction, different counts and mean — the draw-level view is the honest one.

---

## 2. Holdout minimum (hard pre-condition)

```text
>= 30 independent scenario draws
covering all 6 formal families (F1..F6)
```

Below the floor the result may only be labelled **`DIAGNOSTIC_ONLY`** — however
favourable its numbers look. `Gate PASS` does not lift this.

Enforced by `holdout_adequacy()`, which accepts **scenario draws only**; passing
the diagnostic cluster view is a type-level impossibility for a caller that uses
the documented entry point. In the verdict, an inadequate holdout is checked
**first** and produces `DIAGNOSTIC_ONLY` rather than `NOT_ACCEPTED`, because "not
enough data" is a different statement from "the rule lost".

---

## 3. Freeze-before-holdout requirement

Before the final holdout materializes, all of the following must be frozen:

```text
formula
direction
tie-break
fallback
applicability boundary
acceptance metrics (BOTH tiers, see Section 4)
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
| `boundary` | Where the rule does and does not apply |
| `proxy_primary_metric` | Frozen metric for the proxy tier |
| `runtime_primary_metric` | Frozen metric for the runtime tier |
| `frozen_at` / `frozen_commit` | Anchor of the freeze |

Blank fields and unknown metrics are rejected at construction, so an unfrozen
rule cannot be evaluated.

---

## 4. Metric tiers: both are frozen now

A record that named only a proxy metric would force a runtime-metric campaign to
be judged as Level A. Naming the runtime metric *later* — once the data is
visible — is exactly the post-hoc move the protocol exists to prevent. So **both
tiers are frozen together**:

```text
proxy_primary_metric   = planned_return_weighted_prefill_proxy
runtime_primary_metric = observed_recomputed_tokens
```

### 4.1 How the tier is selected

```text
runtime evidence supplied  -> runtime tier is mandatory, metric = frozen runtime metric
otherwise                  -> proxy tier,              metric = frozen proxy metric
```

Selection is driven by **what data exists**, never by which metric looks better.
The caller supplies evidence; the metric comes from the frozen record. Enforced by
`select_metric_tier()`, which additionally rejects an evaluation whose
`loss_view` is not exactly the frozen metric for its tier — so a different view
cannot be slipped in under a tier name.

⚠️ **Consequence:** once a campaign produces runtime recompute observations, the
runtime tier is forced and the rule is judged on `observed_recomputed_tokens`.
There is no path by which a strong proxy result can be reported as Level B, and
none by which a weak runtime result can be reported as Level A.

---

## 5. Levels

### Level A — `PROXY_CANDIDATE`

Proxy tier only. All four conditions must hold:

```text
scenario-draw paired mean loss improvement > 0
scenario-draw 95% CI lower bound > 0
better draws > worse draws
family improvement direction agreement >= 2/3
```

⇒ authorizes the label `PROXY_CANDIDATE` **only**. No runtime claim.

### Level B — `RUNTIME_CANDIDATE`

Runtime tier, judged on the frozen `runtime_primary_metric`, same four conditions:

```text
scenario-draw paired mean recompute reduction > 0
95% scenario-draw CI lower bound > 0
better draws > worse draws
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

## 6. The confidence interval

A **percentile bootstrap over scenario draws**:

```text
resampling unit : one independent scenario draw
iterations      : 10_000
confidence      : 95%
seed            : 20261007   (frozen)
```

The seed is part of the frozen protocol so the interval is reproducible and
cannot be re-drawn until it looks favourable. `AcceptanceCriteria.bootstrap_seed`
is recorded in the verdict payload alongside every interval.

Because the resampling unit is the draw, a 60-row campaign with 18 independent
scenarios yields an interval whose width reflects **18** observations — not 60,
and not the 20 of the diagnostic view.

---

## 7. Latency non-inferiority margin (`epsilon_latency`)

The margin **must not be chosen by hand**. It is calibrated from
baseline-vs-baseline repeated-run jitter:

```text
rule   : max absolute deviation of any baseline repeat from the baseline mean
input  : >= 3 repeated measurements of the baseline (identical configuration)
output : epsilon_latency, frozen before the holdout
```

Rationale: two *identical* baseline runs already differ by this much, so a
challenger inside that band has demonstrated nothing worse than run-to-run noise.
Deriving the margin this way removes the degrees of freedom a hand-picked
"5% / 10%" would leave open.

Enforced by `calibrate_latency_epsilon()` (rejects fewer than 3 repeats and
non-finite values) and applied by `latency_non_inferior()`. The margin is an input
to the check and is **not adjustable** inside it.

⚠️ **This requires calibration data that does not exist yet** — a data request to
M6 (§9). Until it exists, Level B cannot be awarded, and the protocol correctly
returns `NOT_ACCEPTED` for a runtime-tier rule with no latency check.

---

## 8. What the code guarantees

| Guarantee | Enforced by |
| --- | --- |
| A second decision in one scenario is not a second sample | `scenario_paired_deltas` averages positions inside the scenario |
| Seeds never inflate the sample | same, seeds averaged first |
| The floor counts draws, not rows or clusters | `holdout_adequacy` takes `ScenarioPairedDelta` only |
| A diagnostic view is labelled as such | `scope` field on every result and payload |
| The interval is reproducible | frozen `bootstrap_seed`, recorded in the payload |
| The metric cannot be swapped post-hoc | `select_metric_tier` reads it from the record |
| Runtime evidence cannot be judged as Level A | runtime tier is forced when supplied |
| A small holdout cannot yield a candidate label | adequacy checked before any level |
| A rule that loses only in one family is still allowed | 2/3 threshold, tested both ways |
| A rule that loses in half the families is blocked | tested |
| Level B cannot pass without a latency margin | tested |
| Level C cannot be self-declared | requires `ImplementationAttestation` |
| The applied protocol is recorded | `AcceptanceVerdict.as_payload()` → `criteria` |

The verdict payload embeds the criteria it applied and the `sign_convention`,
so a report cannot quote a result without also quoting the protocol and the sign
meaning.

---

## 9. Out of scope / open

| Item | Status |
| --- | --- |
| `epsilon_latency` calibration data (baseline repeats) | **Requested from M6** — does not exist yet |
| Direct recompute observation (runtime tier metric) | **Blocked on the observation seam** M1 approved |
| Holdout with ≥ 30 draws over 6 families | **Blocked on H1's independent workload draw** |
| CLI wiring of the protocol | Deferred — lands with the H1-R1 registration |

### Why the current campaign cannot produce a candidate label

```text
independent scenario draws : 18      (floor is 30)
families present           : 6/6     ✓
```

⇒ any verdict computed on this data is `DIAGNOSTIC_ONLY`. The campaign is
classified as **DISCOVERY / CHARACTERIZATION DATA** and must never serve as the
final holdout for a rule discovered on it.

---

## 10. Worked examples (canonical campaign)

Both use the frozen defaults (`bootstrap_iterations=10000`, `bootstrap_seed=20261007`)
and the scenario-draw unit.

### 10.1 `H1_R1_reverse_deadline`

```text
tier          : proxy   (metric planned_return_weighted_prefill_proxy)
level         : DIAGNOSTIC_ONLY
units         : 18       (improved/worsened/tied = 8 / 3 / 7)
mean_delta    : +0.016086      CI [-0.022461, +0.055409]
family        : 5/6 agreeing, rate 0.833
diagnostic    : 20 decision-position clusters, 8 / 5 / 7
failures      : holdout_adequate, scenario_ci_lower_bound_positive
```

The interval spans zero at 18 draws, so even the best-looking hypothesis on the
discovery data is not distinguishable from noise. The diagnostic row is shown
alongside precisely so the two units are not confused.

### 10.2 `M2_non_code_first`

```text
level         : DIAGNOSTIC_ONLY
failures      : holdout_adequate, scenario_ci_lower_bound_positive,
                family_direction_agreement
```

### 10.3 `M1_marginal_cost_per_reclaimable`

```text
level         : DIAGNOSTIC_ONLY
failures      : holdout_adequate, scenario_mean_improvement_positive,
                scenario_ci_lower_bound_positive, better_draws_outnumber_worse,
                family_direction_agreement
```

⚠️ In all three cases the label is `DIAGNOSTIC_ONLY` rather than
`NOT_ACCEPTED`, because the 30-draw floor is not met. That distinction is
deliberate: "not enough data to judge" is a different statement from "the rule
lost", and the protocol must not silently upgrade the first into the second.

---

## 11. Traceability

| Statement | Source |
| --- | --- |
| Unit = independent scenario draw; seeds and positions are not samples | M1 ruling, 2026-10-07 |
| Aggregation order: seeds → positions → scenario | M1 ruling |
| Decision-position view retained as diagnostic only | M1 ruling |
| ≥ 30 scenario draws over all 6 families, else diagnostic | M1 ruling |
| **Both** tier metrics frozen before the holdout | M1 ruling |
| Tier chosen from available evidence, not by the caller | M1 ruling |
| Freeze formula/direction/tie-break/fallback/boundary/metrics | M1 ruling |
| Level A four conditions | M1 ruling |
| Level B metric + latency non-inferiority | M1 ruling |
| `epsilon_latency` from baseline-vs-baseline jitter, not hand-picked | M1 ruling |
| Level C = B + interface/novelty/overhead reviews | M1 ruling |
| `Gate PASS != Rule Accepted` | M1 ruling |
| Gate is not a rule selector | M1 ruling |
| 18 draws / 20 clusters on the discovery campaign | `H1 evidence request` §1.1, `offline_eval.scenario_clusters` |
