# W1-C-derived formal Native Cost-Aware campaign protocol

## Status and scope

This is the candidate protocol submitted for M1 freeze. It does not authorize
Native execution and contains no policy outcomes. It joins the accepted W1-C
cross-repository workload evidence to the accepted W1-B Native replay path.

The study compares the frozen A0, A1 and A2 implementations. It does not change
their objectives, weights, candidate semantics, Native ownership, BlockPool,
hash cleanup or scheduler behavior. A3 and B1 remain closed.

## Cohort and missingness

The cohort is all and only the 18 W1-C task pairs with full payload evidence.
They cover 11 repositories. `astropy__astropy-8872` and
`sympy__sympy-21596` remain lifecycle evidence but are excluded because their
oversized tool results cannot be inverted to the original full payload. The
cohort must not be described as 12-repository Native content evidence.

The S100 execution is the frozen source condition. Only successful observed
model submissions can become replay requests. A rejected context-limit attempt
remains source missingness and is never converted into a successful Native
request. For each session, six integer-quantile checkpoints including its first
and last successful calls are selected before policy outcomes exist. Their
token arrays and digests are immutable replay inputs; prompt content is not
rewritten.

The 18 tasks are used exactly once in nine disjoint two-session groups. Pairing
uses pre-outcome prompt geometry: mostly cross-repository low/high pairs plus
one within-repository near-matched negative control. The workload group, not a
request, turn, pressure cell or runtime repeat, is the independent unit.

## Controlled replay schedule

Within each session, selected requests retain their observed order. Valid
observed completion-to-next-submit gaps are replay inputs; the 250 ms
cross-session stagger, two-request concurrency limit, cache capacity and
pressure are controlled experimental conditions rather than observed W1-C
arrival behavior.

Every group has two predeclared pressure regimes. `moderate` is the smallest
shortage that requires a legal release; `deep` targets multiple legal
candidates. Both require a later return observation. Exact block counts and
cache capacity must be fixed by a static audit before authorization and must be
identical across arms and repeats. Automatic tuning after outcomes is forbidden.

The 9 groups × 2 pressure regimes × 3 Native arms × 2 runtime repeats produce
108 planned runs. Runtime order is balanced by group and repeat. Repeats estimate
runtime noise and are aggregated before any cross-group statistic.

## Policies and simple comparators

- A0: frozen Continuum entry release plus Native/Tier-aware LRU block choice.
- A1: frozen Cost-Aware entry release plus the A0 block path.
- A2: A0 entry release plus frozen Cost-Aware block selection.

Sufficient-first + earliest deadline and Sufficient-first + minimum overshoot
are evaluated offline on the same complete A1 decision snapshot. They are not
extra Native arms and may not be evaluated when candidate, `need`, marginal
release or deadline evidence is incomplete. This preserves a common decision
state and avoids attributing unrelated runtime noise to the simple rules.

## Evidence and fail-closed rules

Decision evidence records candidate count, `need`, legal blocks, each entry's
marginal newly eligible blocks, deadline, q, q span, selected set and fallback.
A1/simple-rule divergence requires a complete common snapshot. A2/A0 divergence
requires actual A0 Tier-aware selection and verified content identity; physical
block IDs are never compared across processes.

Physical evidence requires a common Native hash process, pre-eviction content
key, ordered post-decision eviction, `hash_removed_after=true`, and a later APC
observation. Without the full chain the result is temporal association or not
observable, not block-level causality.

For every request, `N` is Native prompt tokens, `E` the eligible prefix, and
`C` the observed Native cached prefix. The frozen accounting is:

- `R = E - C`: recomputed eligible tokens (primary);
- `W = N - C`: actual prefill tokens;
- `S = N - E`: new suffix tokens.

Missing or duplicate request identity, incomplete decision state, unmapped
physical eviction, cross-arm token/config drift and unsupported PrefillReload
queries all fail closed. Failed and unrealized runs remain in the campaign.

## Statistical analysis and interpretation

Requests aggregate to runs, two repeats aggregate within a pressure cell, the
two pressure cells aggregate within each of nine workload groups, and only then
are paired arm differences summarized. The protocol freezes 10,000 bootstrap
resamples with seed `20261115` and a 95% interval. Because the nine groups form
a designed grid rather than a probability sample, inference is limited to this
grid and is not a production-population estimate.

The campaign-level verdict requires complete three-arm estimates in both
pressure regimes for all nine groups. Otherwise it is `INCONCLUSIVE`; complete
cases may still be reported descriptively. Decision, physical and token-effect
claims are reported separately.

The final analysis must answer whether q spans remain small, whether A1 differs
from both simple rules, whether A2 differs from actual A0 LRU with complete
identity, and whether confirmed selection changes propagate to physical
eviction and recomputation. Token improvement alone does not validate the cost
model, and selection convergence alone does not invalidate it.

## Gates still pending before execution

M1 protocol freeze, numeric cache/pressure binding, measured PrefillReload
coverage through the largest selected nonterminal prefix, cross-arm config and
token-digest validation, and immutable runner/evaluator code hashes are all
pending. In particular, the accepted W1-B profile ends at 5,120 tokens whereas
this candidate deliberately preserves substantially longer W1-C contexts.
Execution must remain locked until a measured, fail-closed profile coverage
contract is approved; extrapolation is prohibited.
