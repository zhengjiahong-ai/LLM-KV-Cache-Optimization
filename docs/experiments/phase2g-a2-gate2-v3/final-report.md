# Phase 2G A2 Native Gate 2 v3 — Final Result

## Scope

This report records the M1-authorized A0/A2 Native Gate 2 v3 campaign. The
campaign compares frozen A0 Entry Release + Native LRU Block Selection against
the same Entry Release decisions with frozen A2 Cost-Aware Block Selection.
The independent statistical unit is the scenario draw.

## Execution and completeness

- Execution tooling: `7a7803718e64e64e4e16a099dc4496024981f8b3`
- Offline evaluator: `main@2b4681901ff76eb5ca8190ba7b4cf40d5c23a4d9`
- Scenarios: 36/36, with F1–F6 each contributing 6/6
- Planned Native runs: 144
- Successful Native runs: 144
- Valid runs after fail-closed ingestion: 144
- Comparable repeat-level A0/A2 pairs: 72/72
- Complete scenario estimates: 36/36
- Request completeness: 72/72 pairs `COMPLETE`
- Frozen token-metric consistency: 72/72 pairs `EXACT`

The frozen campaign completeness threshold is satisfied.

## Frozen metric result

The primary metric is
`aggregate_recomputed_tokens = sum(eligible_prefix_tokens - cached_prefix_tokens)`.
The paired effect is `A2 - A0`, so negative values favor A2.

- Better / worse / tied scenarios: 0 / 0 / 36
- Mean paired delta: 0 tokens
- Median paired delta: 0 tokens
- Exploratory bootstrap: 10,000 replicates, seed `20261019`
- 95% bootstrap interval: `[0, 0]`
- Every family has 6 tied scenarios and a mean delta of 0

These statistics apply only to the predefined parameter grid and are not an
estimate for an arbitrary production workload distribution.

## Mechanism result

All 72 repeat-level pairs are classified as `NOT_REALIZED`:

- Scenarios with proved A0/A2 selection divergence: 0
- Scenarios with proved physical-eviction divergence: 0
- Native physical eviction events reported by the strict A2 evaluator: 3,400
- Unmapped physical eviction events: 2,032

The A2 evidence stream contains incomplete content identity for at least one
decision in every pair, and no pair establishes a different victim set. The
zero token delta therefore must not be interpreted as evidence that A2 and LRU
are mechanistically equivalent. It means that this frozen experiment did not
realize a provable A2-vs-A0 selection intervention. Per-eviction causal
attribution to recomputation is not established.

## Final candidate conclusion

The campaign is complete and its request-level metric is valid, but the A2
mechanism was not realized under the frozen grid. Consequently:

- No Native recomputation benefit was observed.
- No Native recomputation regression was observed.
- The experiment does not support an A2 benefit claim.
- The limiting condition is absence of proved selection divergence, compounded
  by incomplete strict content-identity mapping for physical evidence.
- No A3 or B1 authorization follows from this result.

## Provenance and exclusions

The earlier campaign was preserved separately as
`ABORTED_PROFILE_RANGE_INCOMPATIBILITY`; none of its 92 successful attempts or
its failed attempt was mixed into this result. The 512-token bridge control and
the A0/A2 profile-repair smokes are non-formal compatibility evidence and are
not statistical samples. An A1-only review tool was briefly invoked during
diagnosis; its output is excluded because it does not understand the A2 arm.

The complete raw evidence, campaign inputs, authorization, Profile repair
records, evaluator output, and relevant source bindings are delivered through
the external archive identified in `evidence-manifest.json`.
