# Phase 2A M4 Method-Design Input and Constraints

Status: **M1 REVIEWED — METHOD DESIGN AUTHORIZED / FINAL IMPLEMENTATION NOT YET AUTHORIZED**

Canonical upstream result:

- `docs/phase2a-m6-formal-results.md`
- canonical raw campaign: `artifacts/phase2a-formal-v5-final/`
- canonical derived bundle: `artifacts/phase2a-formal-v5-derived-v2/`
- canonical Gate outcome: `GAP-PROVISIONAL`
- signal evidence level: `PROXY_SUPPORTED`
- runtime replication: not yet established

This document is the formal M1-to-M4 handoff after M6 formal profiling.

## 1. What M6 has established

The formal campaign is sufficient to show a real method-design opportunity under
the canonical planned trace proxy.

Campaign facts:

- 54 / 54 runs succeeded;
- 60 valid multi-candidate forced-release decisions;
- 174 candidate rows;
- 6 scenario families and 3 seeds;
- 100% decision join coverage;
- candidate sets ranged from 2 to 5 entries;
- repeated-pressure and multi-release cases were exercised.

Canonical loss view:

`planned_return_weighted_prefill_proxy`

For each candidate:

`loss = PrefillReload` if the planned workload returns within the configured
analysis horizon, otherwise `loss = 0`.

This is an offline trace-derived proxy.  It is not measured recomputation,
serving latency, or runtime causal loss.

Under this view:

- 39 / 60 decisions have positive within-decision loss spread;
- mean spread = 0.07015 s;
- bootstrap 95% CI = [0.05571, 0.08369];
- 27 decisions are non-tied;
- Continuum/P1B selects a strictly worse release set in 12 / 27;
- non-tied misselection rate = 44.44%;
- mean absolute regret = 0.03625 s;
- mean normalized regret = 0.36882;
- normalized-regret 95% CI = [0.25215, 0.49019].

Therefore M4 may assume:

> decision-time candidates are not interchangeable, and the current forced-release
> ordering leaves measurable proxy headroom.

M4 may **not** assume:

> the same headroom has already been proven in actual recomputed tokens, TTFT,
> E2E latency, or production workloads.

## 2. Decision-time signals supported by M6

Four features satisfy the preregistered proxy-support rule:

| Feature | Overall rho | Family agreement | Seed agreement | Evidence level |
| --- | ---: | ---: | ---: | --- |
| block count | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |
| initially reclaimable block count | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |
| next tool = code | 0.283 | 0.667 | 1.000 | PROXY_SUPPORTED |
| PrefillReload | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |

These are candidate method inputs, not four independent causal factors.

In particular:

- `block_count`, `initially_reclaimable_block_count`, and
  `PrefillReload` form a strongly related size/recompute-cost cluster;
- M4 must test redundancy and degeneracy before combining them;
- `next_tool_type=code` is the only supported signal from a different semantic
  dimension, but remains proxy-supported rather than runtime-stable.

Features that did not pass the support rule include:

- native LRU position;
- elapsed time since TTL decision;
- retention deadline;
- `next_tool_type=search`;
- `next_tool_type=database`;
- eta;
- queue delay;
- waiting-followup.

Do not include unsupported features merely because they are available.

## 3. Interpretation of GAP-PROVISIONAL

`GAP-PROVISIONAL` authorizes **method design**, not an immediate final-policy
implementation.

The distinction is:

```text
M6 evidence
    -> enough to design and evaluate candidate rules offline
    -> not enough to claim runtime-stable predictors
    -> not enough to claim measured recomputation/serving improvement
```

A feature may be called `RUNTIME_STABLE` only after an independent formal
campaign preserves its direction, effect-size threshold, family agreement, and
seed agreement.

## 4. Hard online-information boundary

M4 may use only information available at or before the forced-release decision.

Allowed candidate inputs include approved decision-time facts such as:

- block / token footprint;
- initially reclaimable blocks;
- PrefillReload estimate;
- next tool type;
- retention state and deadline;
- elapsed-since-TTL-decision;
- waiting-followup state;
- eta;
- queue-delay signal;
- native LRU position.

The following are offline-only and forbidden in runtime policy logic:

- planned or observed future return label;
- return time / horizon margin;
- future request arrival;
- post-decision physical eviction;
- future recomputed tokens;
- future latency / TTFT;
- hindsight-best candidate;
- absolute or normalized regret;
- any oracle / future-reused label.

The canonical planned proxy is a **training/evaluation target**, never a runtime
feature.

## 5. Runtime ownership constraints remain frozen

The primary project contribution remains Cost-Aware KV Cache Eviction / Victim
Selection.

Any M4 runtime implementation must preserve Phase 1A ownership:

- project policy selects victim block IDs only;
- native vLLM owns BlockPool mutation;
- native vLLM owns FreeKVCacheBlockQueue links;
- native vLLM owns ref_cnt;
- native vLLM owns hash cleanup;
- native vLLM owns allocation/reuse;
- native scheduler owns request lifecycle/bookkeeping.

Do not move Cost-Aware logic into `src/kvopt/continuum/**`.

Retention eligibility and victim-value ranking remain separate layers.

Native LRU must remain the safe fallback.

## 6. Required corner cases

A valid M4 design must support, not special-case away:

- candidate sets larger than two;
- multiple selected releases in one pressure decision;
- repeated pressure;
- no-return candidates;
- return-order reversal;
- ties;
- evolving prefixes;
- physical block-slot reuse;
- shared / overlapping logical ownership where exposed.

A bare `block_id` must never be treated as permanent content identity.

## 7. What the current evidence does NOT prove about block-level design

The existing M4 block-level pre-design draft remains useful, but M6 did not
validate all of its assumptions.

M6 supports the general facts that:

- candidate footprint varies;
- recomputation proxy varies;
- baseline ordering has proxy regret;
- some decision-time information is associated with proxy loss.

M6 does **not** establish:

- that prefix-internal block position is predictive;
- that leading-vs-trailing eviction is the dominant mechanism;
- that partial-prefix retention improves actual APC reuse;
- that the real prefill/reload cost curve is sufficiently nonlinear;
- that a request-level score cannot already capture most available headroom;
- that block-level B1 is superior to a simpler entry-level forced-release rule.

Therefore M4 must not treat B1 partial-prefix retention as already approved.

## 8. First M4 task: offline method-design study

Before runtime implementation, M4 should build a small offline evaluator over the
canonical M6 decision-candidate dataset.

The purpose is to answer:

> Can a simple rule using only decision-time information recover meaningful
> canonical proxy headroom without future leakage?

At minimum evaluate these families:

### M0 — executed P1B ordering

The current baseline.

### M1 — cost/size-only rules

Examples for study, not frozen formulas:

- PrefillReload ordering;
- block-count ordering;
- initially-reclaimable-block-count ordering.

These must be tested for redundancy.

### M2 — lifecycle-semantic rule

Use the supported tool-category information, especially
`next_tool_type=code`, without future labels.

### M3 — simple combinations

Only simple, interpretable combinations of the supported feature clusters.

M4 should prefer:

- lexicographic rules;
- normalized additive scores;
- small hand-auditable formulas;

over a complex learned model at this stage.

Do not fit a high-capacity model to 60 controlled decisions.

## 9. Required offline evaluation discipline

The same canonical M6 planned proxy may be used as the offline target.

However, M4 must prevent scenario-family memorization.

Use at least one family-level holdout or leave-one-family-out evaluation.

Report:

- regret versus executed P1B;
- fraction of decisions improved;
- fraction worsened;
- ties;
- behavior by scenario family;
- behavior by candidate-set size;
- behavior under multi-release pressure;
- feature ablations;
- ranking stability across seeds.

Any score/threshold acceptance rule must be frozen before using the final
holdout result.

M4 must explicitly report if the supported signals collapse into the same
ranking.

## 10. Request-level degeneracy must be re-tested, not assumed away

The historical spike found that under a linear recompute-cost model,
`C_recompute / Blocks` can collapse to a constant and make a request-level
cost-aware rule structurally neutral.

The new M6 result shows that size/recompute-related signals correlate with the
canonical proxy, but it does not invalidate the old degeneracy argument.

Therefore every candidate formula must include a degeneracy audit:

- does the score reduce to native/P1B ordering under linear cost?
- are block count and PrefillReload producing identical ranks?
- does dividing by reclaimable blocks cancel the useful cost signal?
- is apparent benefit coming only from the tool-type indicator?

Do not resurrect the previously rejected marginal-block denominator without new
evidence.

## 11. Decisive block-level questions before B1 implementation

If M4 wants to pursue the block-level / partial-prefix path, four questions must
be resolved first.

### Q1. Real cost curve

Measure the real `C(r)` prefill/reload curve over the relevant prefix-length
range on the compliant runtime.

The earlier block-level draft correctly identifies this as decisive: if the
service range is effectively linear, much of the proposed marginal block-cost
structure disappears.

### Q2. Partial APC behavior

Verify that retaining a leading contiguous prefix and evicting trailing blocks
actually yields the assumed partial APC hit / suffix recomputation behavior.

Do not infer this from logical prefix identity alone.

### Q3. Interface availability

B1 requires at least:

- block -> logical owner;
- block position within prefix;
- per-entry recomputation cost;
- reuse/value signal.

These must be exposed through a narrow M1-approved policy interface without
transferring native ownership.

### Q4. Offline benefit beyond simpler entry-level rules

A block-level design is justified only if it can express useful choices that the
simpler supported entry-level features cannot.

If a simple forced-release rule already captures the available proxy headroom,
the extra block-level complexity needs separate evidence.

## 12. Recommended design sequence

```text
Step 1
Reproduce canonical M6 baseline in an M4 offline evaluator

Step 2
Evaluate simple decision-time rules and ablations

Step 3
Run family-held-out validation and degeneracy audit

Step 4
Determine whether entry-level forced-release ranking is sufficient

Step 5
In parallel, measure real C(r) and verify partial APC semantics

Step 6
Only if block-level structure adds evidence-backed value:
freeze the minimal M1 interface extension

Step 7
Write M4 method-design spec v1

Step 8
M1 review

Step 9
Only after review: implement runtime policy
```

## 13. Method-design exit criteria

M4 method design is ready for implementation review when all of the following
are true:

- the proposed rule uses only decision-time information;
- its offline evaluation is reproducible from canonical M6 data;
- family-held-out behavior is reported;
- supported feature redundancy has been audited;
- request-level degeneracy has been audited;
- multi-release and >2-candidate behavior is defined;
- fallback ordering is defined;
- runtime complexity/overhead is bounded;
- required interface extensions are explicit and minimal;
- the proposal does not rely on unavailable runtime capabilities;
- novelty has been checked against the relevant related work;
- limitations remain explicit: evidence is proxy-level until runtime validation.

No implementation should be justified solely by an in-sample proxy-regret
improvement.

## 14. M1 decision

M1 authorizes:

> **M4 method design and offline evaluation.**

M1 does not yet authorize:

> **freezing or merging a final runtime Cost-Aware implementation.**

The next M4 deliverable should be a method-design report/spec that compares
simple evidence-backed alternatives and identifies the minimum runtime interface
needed by the winning design.
