# Phase 2A M6 Formal Profiling Results

Status: CANONICAL FORMAL RESULT / M1 AND M4 HANDOFF

## 1. Decision

The canonical Empirical Gap Gate outcome is:

```text
GAP-PROVISIONAL
```

All five Gate checks pass under the preregistered, trace-derived canonical
loss view `planned_return_weighted_prefill_proxy`. The campaign shows candidate
loss heterogeneity, Continuum baseline headroom, and four decision-time
features that meet the proxy-support thresholds.

This is `PROXY_SUPPORTED`, not `RUNTIME_STABLE`. The canonical label is based
on planned workload timing, and no independent formal rerun has yet replicated
the signal result. It supports continued method design, but not a claim that
the same signals are stable predictors of realized runtime loss.

## 2. Canonical artifacts and provenance

The authoritative evidence is:

- campaign: `artifacts/phase2a-formal-campaign-v4/`;
- V5 raw runs: `artifacts/phase2a-formal-v5-final/`;
- execution summary:
  `artifacts/phase2a-formal-v5-final/formal-execution-dedc3e2e21c1.json`;
- canonical derived bundle: `artifacts/phase2a-formal-v5-derived-v2/`;
- Method Support Pack:
  `artifacts/phase2a-formal-v5-derived-v2/method_support_pack.json`.

The 54 raw runs were collected from clean project commit
`b0ca52fb9a743aa46447feff34be6675c76af290`. The canonical derived bundle was
generated from clean analysis commit
`6023c66e9b8d51491f189e881b45eabe4a823cd9`. Its manifest uses schema
`phase2a.derived.v2` and records planned timing as canonical and observed
timing as non-Gate sensitivity evidence.

Because `artifacts/` is Git-ignored, the complete evidence is packaged for
out-of-band transfer as:

```text
artifacts/phase2a-m6-formal-evidence-6023c66.tar.gz
```

Archive properties:

- size: 656 KiB;
- entries: 447;
- SHA-256:
  `eb38f82643c9f173f745cb7bf6b822e4019932f5dbebf9bfc77860bde12d3770`.

The archive must be transferred separately from the pull request. Its transfer
channel must be agreed with M1 or the project team.

## 3. Campaign validity

The campaign contains 18 scenarios across F1-F6 and seeds `101`, `211`, and
`307`.

| Check | Result |
| --- | ---: |
| Planned / executed runs | 54 / 54 |
| Successful / failed runs | 54 / 0 |
| Runs valid for candidate analysis | 54 / 54 |
| Forced-release decisions | 60 |
| Multi-candidate decisions | 60 (100%) |
| Candidate / decision-outcome rows | 174 / 174 |
| Logical-release rows | 69 |
| Physical-eviction rows | 870 |
| Request-outcome rows | 384 |
| Decision join coverage | 100% |

The execution ran from `2026-10-04T11:55:19Z` to
`2026-10-04T12:16:17Z`. Derived statistics use 2,000 deterministic bootstrap
resamples, bootstrap seed 0, and 95% confidence intervals.

## 4. Canonical loss semantics

For a candidate at a forced-release decision:

```text
planned_time_to_return
= future return request planned arrival offset
  - triggering pressure request planned arrival offset

planned_returned_within_horizon
= planned_time_to_return <= analysis_horizon_seconds

planned_return_weighted_prefill_proxy
= PrefillReload if planned_returned_within_horizon else 0
```

All 174 candidate outcomes have a valid planned pressure anchor. The canonical
view is fully comparable at all 60 decisions and is the only view admitted to
the formal regret, signal, and Gate calculations.

Observed wall-clock timing remains in `decision_outcomes.jsonl`. The separate
`observed_return_weighted_prefill_proxy_sensitivity` view is explicitly marked
`sensitivity_view_not_gate_eligible` and cannot affect the canonical Gate.

## 5. Heterogeneity and baseline headroom

Under `planned_return_weighted_prefill_proxy`:

- 39 of 60 decisions have positive within-decision loss spread (65.0%);
- mean spread is `0.07015` seconds;
- bootstrap 95% CI for mean spread is `[0.05571, 0.08369]`;
- 27 decisions are non-tied;
- Continuum selects a strictly worse release set in 12 of them;
- non-tied misselection rate is `44.44%`;
- mean absolute regret is `0.03625` seconds, with 95% CI
  `[0.02380, 0.04971]`;
- mean normalized regret is `0.36882`, with 95% CI
  `[0.25215, 0.49019]`.

These are offline proxy comparisons. They show method headroom but do not
constitute direct recomputation or serving-impact evidence.

## 6. Planned versus observed sensitivity

The planned and observed strict-horizon labels are comparable for all 174
candidate outcomes. Ten labels flip, for a boundary flip rate of `5.75%`.

Observed horizon margins are:

- minimum: `-4.00558` seconds;
- median: `-1.00059` seconds;
- maximum: `5.99929` seconds.

This confirms that runtime jitter changes a non-zero fraction of strict
observed-horizon labels. The observed view is retained for sensitivity
diagnosis only and is not an alternative canonical result.

## 7. Decision-time signal analysis

Support requires absolute overall Spearman rho of at least `0.2`, at least
three evaluable family and seed groups, and direction agreement of at least
`2/3`. Four features meet those thresholds against the canonical planned
proxy:

| Feature | Overall rho | Family agreement | Seed agreement | Level |
| --- | ---: | ---: | ---: | --- |
| block count | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |
| initially reclaimable block count | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |
| next tool = code | 0.283 | 0.667 | 1.000 | PROXY_SUPPORTED |
| PrefillReload | 0.205 | 0.833 | 1.000 | PROXY_SUPPORTED |

Native LRU position, elapsed time, retention deadline, search/database tool
indicators, `eta`, queue delay, and waiting-follow-up do not meet the support
rule. The evaluation records `runtime_replicated=false`; an independent formal
rerun must preserve direction, effect-size threshold, family agreement, and
seed agreement before any feature can be upgraded to `RUNTIME_STABLE`.

## 8. Empirical Gap Gate

| Gate | Status | Evidence |
| --- | --- | --- |
| Data integrity | PASS | join coverage 1.000; V5 capability contract complete |
| Event volume | PASS | 60 decisions, 6 families, 3 seeds |
| Loss heterogeneity | PASS | canonical planned proxy passes spread thresholds |
| Baseline headroom | PASS | canonical planned proxy passes regret thresholds |
| Decision-time signal | PASS | four proxy-supported decision-time features |

The overall result is `GAP-PROVISIONAL`. It permits the next method-design
step using the canonical planned proxy, subject to the explicit
`PROXY_SUPPORTED` limitation. It does not authorize presenting proxy support
as realized runtime stability.

## 9. Handoff constraints

### M4

- Treat the four supported signals as candidate inputs for method design, not
  as independently replicated runtime predictors.
- Keep planned/observed return labels, hindsight choices, regret, and horizon
  margins offline-only.
- Preserve support for multiple releases, repeated pressure, block-slot reuse,
  shared ownership, no-return candidates, return-order reversal, and ties.

### Future runtime replication

An independent formal campaign may upgrade a proxy-supported signal to
`RUNTIME_STABLE` only if direction, effect size, family agreement, and seed
agreement all remain above the preregistered thresholds. No additional raw
rerun is required merely to validate the planned-proxy re-derivation reported
here.

### Remaining limitations

- unselected-victim counterfactual outcomes require controlled replay;
- serving-impact loss is not constructed;
- direct recomputed-token evidence remains unavailable;
- physical eviction remains incomplete candidate-level block-slot evidence;
- native APC hit/miss and hardware counters are unavailable;
- the workload matrix is controlled and diagnostic, not a production
  benchmark.

## 10. Superseded and diagnostic evidence

The following evidence remains preserved but is not canonical:

- V4 final derived results, including
  `HEADROOM-BUT-NO-ONLINE-SIGNAL`, are diagnostic only;
- `artifacts/phase2a-formal-v5-derived/` uses the observed-horizon proxy and
  its `GAP-PROVISIONAL` result is superseded;
- interrupted, same-process, context-check, and validation-only campaigns are
  debugging evidence and must not be pooled with the canonical result.

The V5 raw directory must remain byte-unchanged. The canonical conclusion must
be regenerated from `phase2a-formal-v5-final` into a fresh derived directory
using analysis commit `6023c66` or an explicitly reviewed successor.
