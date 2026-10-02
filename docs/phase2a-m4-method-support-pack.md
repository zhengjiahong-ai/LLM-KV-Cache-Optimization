# Phase 2A Method Support Pack — Required Deliverable for M4

Status: REQUIRED OUTPUT

## 1. Purpose

This is the artifact M4 consumes before designing the Cost-Aware forced-release method.

It must summarize evidence, not prescribe the final formula.

## 2. Executive findings

Provide concise answers to:
1. How often does multi-candidate forced release occur in the formal campaign?
2. How large is candidate heterogeneity?
3. How often is Continuum hindsight-suboptimal?
4. How large is the realized regret when it is suboptimal?
5. Which decision-time signals are consistently associated with realized loss?
6. Which signals are unavailable, unstable, or future-only?

## 3. Baseline prevalence section

Required tables/plots:
- forced-release frequency;
- candidate-count distribution;
- pressure-severity distribution;
- releases-per-decision distribution;
- repeated-pressure / repeated-release rate.

## 4. Candidate heterogeneity section

For each decision-time feature, report:
- overall distribution;
- within-decision spread;
- variation by workload family;
- missingness / availability.

Features include:
- block/token footprint;
- PrefillReload;
- retention deadline;
- elapsed-since-TTL-decision;
- next tool type;
- waiting-followup state;
- eta;
- queue delay;
- native LRU rank / position.

## 5. Outcome heterogeneity section

Keep separate views for:
- logical release cost;
- physical eviction cost;
- recomputation cost;
- serving impact.

Explicitly show where these views disagree.

## 6. Baseline headroom section

Required:
- hindsight best candidate definition for each loss view;
- tie rate;
- Continuum misselection rate;
- absolute regret distribution;
- normalized regret distribution;
- high-regret exemplars with raw event references;
- breakdown by scenario family, candidate count, and pressure severity.

## 7. Signal usefulness section

Using only decision-time information, report:
- simple correlations / rank associations;
- stratified loss differences;
- simple one/two-feature diagnostic baselines;
- held-out checks across seeds/families;
- signals that reverse or disappear out of family.

This section should identify promising inputs for M4, not train the final policy.

## 8. Method constraints for M4

End with a concrete constraint list:
- online features safe to use;
- online features available but weak/unstable;
- future-only labels that must never be used online;
- observation capabilities still missing;
- candidate-set / shared-block corner cases;
- expected runtime overhead budget if known;
- loss view(s) best supported by evidence;
- unresolved questions requiring another profiling pass.

## 9. Raw traceability

Every headline finding should be traceable to:
- run IDs;
- decision_event_index values;
- derived-table rows;
- source event indexes.

## 10. Decision boundary

M4 begins method design only after M1 reviews this pack against the Empirical Gap Gate.

A Method Support Pack can validly conclude:
- GAP-PASS;
- GAP-PROVISIONAL;
- NO-MEASURABLE-GAP;
- HEADROOM-BUT-NO-ONLINE-SIGNAL;
- DATA-INVALID / INSUFFICIENT-EVENTS.

Only GAP-PASS should trigger normal method implementation.
