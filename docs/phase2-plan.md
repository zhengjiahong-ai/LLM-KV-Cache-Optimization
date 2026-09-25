# Phase 2A — Forced-Release Profiling Plan

## Goal

Phase 2A validates a candidate research hypothesis before freezing the proposed method:

> Continuum already models whether an Agent KV cache should remain retained, but when memory pressure forces protected state to be released early, victim selection may still leave measurable decision headroom. Phase 2A determines whether that headroom is real and whether online system signals can explain it.

This is a **hypothesis-validation phase**, not the final Cost-Aware method.

## Baseline semantics

Three decision references are distinguished explicitly.

### A. Continuum paper forced-release heuristic

The paper-level Continuum forced-release rule is treated as a separate experimental reference:

```text
memory contention / scheduling blocked
    -> repeatedly unpin protected requests
    -> choose victim by latest program arrival time
    -> stop when the first request can be scheduled
```

This rule must not be conflated with the Phase 1B project adaptation.

### B. Phase 1B project adaptation

The validated Phase 1B implementation intentionally uses a deterministic project adaptation:

```text
ordinary expiry
    -> ordinary/unprotected eligible blocks
    -> if still insufficient, release protected entries by
         earliest retention deadline
         -> entry native-LRU key
         -> stable entry identity
```

This remains the frozen Phase 1B baseline behavior unless a later experiment explicitly selects another forced-release policy.

### C. Offline oracle

Phase 2A may use an offline oracle that sees future outcomes only to estimate headroom/regret.

The oracle is **not** an online policy and must never be used as the proposed method.

## Profiling contract

The runtime exposes immutable decision-time observations through:

```text
kvopt.profiling.forced_release
```

The contract records all protected logical candidates present when forced release is required, together with the actual Phase 1B selected release effects.

Decision-time facts and future outcome labels are kept separate.

The observation layer must not:

- change release ordering;
- change block victim selection;
- modify retention state;
- modify native vLLM state;
- introduce a Cost-Aware score.

## Current decision-time fields

The first profiling contract exposes only facts already available at the decision boundary:

- `(program_id, prefix_id)`;
- retention deadline;
- waiting-followup state;
- protected block IDs;
- blocks that would become immediately reclaimable if the entry were released;
- next tool type when known;
- elapsed time since the TTL decision;
- profiled PrefillReload value;
- eta;
- queue-delay signal;
- actual Phase 1B pressure-release effects.

Fields are not added merely because they may be useful later. Additional runtime enrichment requires an explicit interface decision.

## Phase 2A experiment references

The first audit should compare:

```text
1. Continuum paper forced-release heuristic
2. Phase 1B deterministic adaptation
3. Offline oracle upper bound
```

No new Ours heuristic is required for the first audit.

## Questions Phase 2A must answer

1. Can forced release be triggered reproducibly?
2. Are candidate release losses meaningfully heterogeneous?
3. Does either online baseline show non-trivial regret against the oracle?
4. Does forced-release regret lead to measurable cache miss/recomputation or next-turn latency impact?
5. Which decision-time signals explain the observed regret?
6. Is logical value better modeled at the protected entry/prefix level or directly at the block level?
7. Does current related work already subsume the exact decision problem?

## Exit gate

Do not freeze or implement the final Cost-Aware forced-release policy until both conditions hold:

```text
Novelty gate:
    the exact decision problem is not already subsumed by nearby work

Empirical gap gate:
    forced-release decisions show measurable, reproducible headroom
```

If either gate fails, Phase 2 should revisit the research direction rather than forcing an algorithm onto a weak gap.

## Ownership

- Member 1: profiling/interface boundary, integration, fairness rules.
- Member 2: novelty audit and paper-mechanism verification.
- Member 5: reproducible forced-pressure workload.
- Member 6: profiling, regret analysis, causal outcome analysis.
- Member 4: online-signal feasibility now; final method only after the Phase 2A gates pass.
- Member 3: Phase 1B baseline remains frozen except for validated defects.
