# Phase 2A Empirical Gap Gate

Status: FROZEN v0 FOR PILOT

The gate decides whether M6's FORMAL profiling and analysis provide enough evidence to justify asking M4 to implement a Cost-Aware forced-release policy. It does not decide the final score formula.

The 30-run P0-P3 foundation suite is NOT an eligible standalone gate input. It may validate instrumentation, joins, and metric code, but GAP-PASS requires the broader M6 formal profiling dataset defined in docs/phase2a-m6-formal-profiling-plan.md.

## 1. Gate inputs

Use only M6 datasets derived from the FORMAL Phase 2A profiling campaign under the profiling data contract. Foundation-test artifacts may be included only as validation/sanity evidence, not as the sole statistical basis.

A valid decision has:
- candidate_count >= 2
- complete decision-time candidate snapshot
- selected logical release(s)
- traceable post-decision lifecycle

Physical/recompute/timing fields may be capability-gated, but missingness must be explicit.

## 2. Data-integrity gate — REQUIRED

PASS when:
- >= 95% of otherwise-valid forced-release decisions join from decision to selected logical release and post-decision lifecycle
- physical eviction evidence is either joinable or explicitly marked unavailable, never silently inferred
- no derived row loses run_id / decision_event_index provenance

Failure means fix instrumentation/dataset construction, not no research gap.

## 3. Event-volume gate — REQUIRED

Minimum formal-dataset target:
- at least 30 valid multi-candidate forced-release decisions
- across at least 3 scenario families
- with at least 3 seeds represented

This is a minimum diagnostic volume, not final paper sample size.

If the pilot cannot produce this volume, outcome is INSUFFICIENT-EVENTS.

## 4. Heterogeneity gate — REQUIRED

For each valid decision, construct candidate-level realized-loss views from all available layers.

PASS when at least one nontrivial realized-loss view shows both:
- positive within-decision spread in >= 25% of valid decisions
- bootstrap 95% CI for mean within-decision spread is strictly above zero

Preferred loss views, in order of directness:
1. actual recompute work
2. serving impact
3. physical eviction cost
4. logical release / PrefillReload proxy

Proxy-only evidence can establish HETEROGENEITY-PROVISIONAL but not the strongest final claim.

## 5. Baseline-headroom gate — REQUIRED

For each decision and usable realized-loss view:
- hindsight best candidate is the candidate with minimum realized loss under that view
- compare Continuum selected logical release with hindsight choice
- preserve ties explicitly

PASS when, for at least one realized-loss view:
1. Continuum selects a strictly worse candidate than hindsight in >= 10% of valid non-tied decisions
2. mean normalized regret is positive with bootstrap 95% CI lower bound > 0

Recommended normalized regret:
(selected_loss - best_loss) / max(abs(selected_loss), epsilon)

M6 must also report unnormalized loss difference.

The oracle is offline analysis only and must not enter runtime policy input.

## 6. Decision-time signal gate — SUPPORTING

Before implementing a new policy, verify observed headroom is not purely future-unpredictable.

Using only decision-time fields, check whether at least one candidate feature or simple pre-registered combination has a stable association with realized loss across scenario families/seeds.

Candidate inputs include:
- prefix/block footprint
- PrefillReload
- next_tool_type
- elapsed_since_ttl_decision
- retention deadline
- waiting_followup
- eta
- queue delay
- native LRU position

This does not require a complex model. A simple stratification, rank correlation, or tiny held-out regression is sufficient for diagnosis.

If hindsight headroom exists but no decision-time signal is observable, label:
HEADROOM-BUT-NO-ONLINE-SIGNAL

## 7. Overall outcomes

GAP-PASS:
all required gates pass and at least one usable decision-time signal is supported. M4 may begin method design.

GAP-PROVISIONAL:
data integrity/event volume pass, but headroom relies only on logical/physical proxies because recompute/serving outcomes are unavailable. Improve only the missing observation seam needed to resolve the gap.

NO-MEASURABLE-GAP:
data integrity and event volume pass, but candidate heterogeneity or baseline headroom fails. Do not implement Cost-Aware from the current hypothesis.

HEADROOM-BUT-NO-ONLINE-SIGNAL:
offline hindsight headroom is real, but no stable decision-time predictor is available. Revisit the method hypothesis.

INSUFFICIENT-EVENTS / DATA-INVALID:
not research conclusions.

## 8. What this gate protects against

The gate prevents:
- implementing a generic reuse x recompute score before showing a real gap
- treating logical release as identical to physical eviction
- using future information online
- claiming improvement when candidates have similar realized cost
- overfitting a policy to a tiny smoke workload
