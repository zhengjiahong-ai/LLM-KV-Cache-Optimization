# Phase 2G A2 Native Gate 2 v3 — Root Cause Audit

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

The frozen campaign completeness threshold is satisfied. M1 records this as an
execution-completeness result, not as an A2 effectiveness verdict.

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

## Mechanism result after fail-closed correction

The original evaluator classified all 72 repeat pairs as `NOT_REALIZED` even
though `selection_diverged` was `None`. That aggregation collapsed
unobservable evidence into a proved false value. The corrected evaluator gives:

- Repeat pairs classified `SELECTION_NOT_OBSERVABLE`: 72/72
- Scenario-level selection divergence: `None` for 36/36
- Repeat pairs with proved equal selection: 0
- Repeat pairs with proved selection divergence: 0
- Native physical eviction events reported by the strict A2 evaluator: 3,400
- Unmapped physical eviction events: 2,032

The zero token delta is therefore descriptive only. It cannot establish that A2
and LRU are equivalent, nor can the physical-event stream establish per-block
causality for recomputation.

## Decision-level root cause

The read-only audit covers all 778 persisted A2 block decisions:

- 428 used explicit `native_lru_fallback`, all for `content_unverified`.
- 350 used `incremental_greedy`, but every selected victim set equalled the
  recorded Native-LRU reference set.
- All 778 decisions selected the same set as their Native-LRU reference.
- 54 decisions immediately followed a `FORCED_RELEASE_DECISION`; the other 724
  were native-allocation decisions outside that pressure-release association.
- For all 54 associated decisions, the A0 decision-time victim set equalled the
  A2 Native-LRU reference set.
- All 778 Native-LRU reference sets were the required-length prefix of the
  recorded legal-candidate order. All 54 A0 pressure windows had complete
  decision-time victim sets; the windows contained 994 observable hashed
  physical evictions.
- No decision reported a shared block (`shared_block_count = 0`).
- Only 54 decisions contained any identified hashed block; 2,032 physical
  eviction records remained unmapped by the strict evaluator.
- Identity states across legal candidates were 5,882 `HASHED_PROVEN`, 27,066
  `HASHED_UNVERIFIED`, and 730 `HASHLESS_NO_CONTENT`.
- No contract or adapter problems were recorded.

The 54 pressure-associated legal queues contained 648 Tier-0, 618 Tier-1 and
2,130 blocks without a resolved Continuum tier. A0 Tier-aware ordering and the
A2 Native-LRU reference agreed for every associated decision, so the observed
fallback comparator is internally consistent; this does not repair the missing
content identity needed to prove a cost-aware intervention.

Thus the frozen runs exercised the adapter and request measurement path but did
not establish a distinguishable A2 intervention. The dominant causes are
content-unverified fallback and a zero-difference greedy result; shared-block
marginal-cost behavior was not exercised by the observed candidate sets.

The two arms nevertheless provide identical descriptive request distributions:
each has 360 eligible requests, 278 full hits, 44 partial hits and 38 misses;
each sums to 9,568 recomputed tokens, 16,008 actual prefill tokens and 6,440 new
suffix tokens.

## Final candidate conclusion

The campaign execution is complete and its request-level measurements are
descriptively valid, but A2 mechanism activation is not established.
Consequently:

- No Native recomputation benefit was observed.
- No Native recomputation regression was observed.
- A2 effectiveness is `INCONCLUSIVE`; this is not a final negative result.
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

The machine-readable root-cause summary and 778-row decision table are generated
from the unchanged raw evidence. The complete handoff is identified in
`evidence-manifest.json`.
