# Phase 2G A2 Gate 2 — bounded Native evaluation preparation

## Status and scope

This package prepares, but does not authorize or execute, the Phase 2G A2 Native
Gate 2 campaign.

- Preparation authorization: granted by M1 after A2 Gate 1.
- Formal Native execution: **not authorized**.
- Planned size: 36 scenario draws × 2 policies × 2 runtime repeats = 144 runs.
- Independent statistical unit: scenario draw.
- Runtime repeats are measurement-noise repeats, not independent samples.
- Frozen A2 implementation under test:
  `15a65e36604af5679987bb91d224fd20ce560e8a`.

No H1/H2 artifact, A0 Entry Release behavior, Native ownership mechanism, A2
formula, A3 method, or B1 behavior is changed by this preparation.

## Compared policies

Both arms use the same frozen Continuum A0 Entry Release, legal Block candidate
set, required release count, workload, request order, model, tokenizer, cache
capacity, and runtime parameters.

- **A0:** A0 Entry Release + Native LRU Block Selection.
- **A2:** A0 Entry Release + frozen A2 Cost-Aware Block Selection.

The only experimental arm difference is `phase2g_block_policy`. The materializer
computes one input-contract SHA-256 for each scenario and requires all four
policy/repeat configs to share it.

## Scenario design

The campaign is a predefined balanced parameter grid, not a claim of sampling
from a production distribution. It contains six draws in each family:

| Family | Controlled focus |
|---|---|
| F1 | Prefix depth and unequal private-tail recomputation cost |
| F2 | Shared multi-chain marginal Block cost |
| F3 | Reuse-weight and return-gap heterogeneity |
| F4 | Multi-turn context growth and repeated cache competition |
| F5 | No-sharing and LRU-aligned negative controls |
| F6 | Proxy-weight misspecification and adverse return behavior |

Across draws, the grid varies Entry count, prefix size, pressure shortage,
pressure count, return gap, sharing topology, and context growth. The content
seed is scenario-scoped and remains identical across both policies and both
runtime repeats.

## Frozen metrics and aggregation

For each eligible request:

```text
N = native prompt tokens
E = eligible prefix tokens
C = native cached prefix tokens

actual_prefill_tokens = N - C
recomputed_tokens     = E - C
new_suffix_tokens     = N - E
```

The primary metric is:

```text
aggregate_recomputed_tokens = Σ(E - C)
Δ = A2 - A0
```

Negative Δ is improvement; positive Δ is regression. The evaluator also reports
`Σ(N-C)` and `Σ(N-E)` and checks their arithmetic relationship. Requests may not
be silently removed to make the arms comparable.

The two repeats are first aggregated within each scenario. Overall and family
summaries then use scenario draws. The exploratory 95% bootstrap confidence
interval uses 10,000 resamples and seed `20261019`.

## Evidence layers

The evaluator keeps three claims separate:

1. **Selection:** A2 and Native LRU victim sets differ by decision-time content
   identity. A difference in reusable `block_id` alone is insufficient.
2. **Physical mechanism:** paired arms show different Native physical eviction
   signatures. Missing content/hash-process evidence remains not observable.
3. **Request outcome:** paired request-level Native evidence yields a difference
   in the frozen recomputation metric.

Physical event correlation is not interpreted as per-Block causal attribution
to later recomputation. A2 proxy-weighted loss is not reported as actual expected
recomputation.

Physical evidence is observable only when every relevant eviction has a current
decision-time content identity, occurs after the applicable pressure/Block
decision, uses the same Native Hash process and cache key, and records
`hash_removed_after=true`. Process mismatch, Slot reuse, a decision-preceding
event, or even one partially unmapped eviction makes that run's physical layer
not observable.

Each A2 decision must select only legal candidates, select exactly
`required_blocks` unique victims, carry complete legal/selected/LRU identity
evidence, and contain no unhandled adapter or frozen-contract problem. Fallbacks
remain visible and do not count as realization of the A2 mechanism.

## Failure and missingness rules

- All planned runs and attempts must be retained.
- A technical retry must use an identical frozen config and preserve the failed
  attempt.
- A missing or invalid arm makes that repeat not comparable.
- A scenario requires both comparable repeats for a numeric scenario estimate.
- Missing request evidence, duplicate/unpaired request identities, absent content
  identity, and missing physical evidence fail closed at their respective layer.
- Mechanism not realized is distinct from no benefit and from invalid evidence.
- A formal overall result requires all 36 scenarios, with all six families fully
  represented. If fewer than 36 scenario estimates are complete, the formal
  campaign verdict is `INCONCLUSIVE`. Statistics over the remaining complete
  scenarios are explicitly descriptive only.
- Bootstrap results describe this predefined parameter grid only; they are not
  estimates for an arbitrary production workload distribution.

## Preparation workflow

Materialize the still-locked campaign:

```bash
python -m kvopt.workload.phase2g_a2_gate2_materialize \
  --distribution configs/phase2/phase2g-a2-native-gate2-distribution-v1.json \
  --output-dir artifacts/phase2g-a2-native-gate2-campaign-v1
```

Validate its structure and pairing without inspecting outcomes:

```bash
python -m kvopt.workload.phase2g_a2_gate2_validate \
  --manifest artifacts/phase2g-a2-native-gate2-campaign-v1/manifest.json \
  --output artifacts/phase2g-a2-native-gate2-campaign-v1/validation-report.json
```

The generated manifest remains locked with both authorization fields set to
`false`. It must be bound to the committed experiment-tooling SHA and submitted
to M1. A separate reviewed authorization step is required before any Native Gate
2 runner may execute these configs.

## Evaluator activation boundary

`kvopt.profiling.phase2g_a2_gate2` refuses to analyze an execution-locked
manifest. After a future explicit M1 authorization, the evaluator additionally
requires a separate `phase2g.a2_gate2_authorization.v1` record binding the exact
reviewed manifest SHA, all run/config hashes, all scenario/trace hashes, tested
A2 implementation SHA and full experiment-tooling SHA. Each actual run must then
match its frozen config, trace and tooling revision. Changing an authorization
Boolean alone cannot unlock evaluation.

