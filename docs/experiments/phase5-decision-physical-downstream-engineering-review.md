# Phase 5 Decision, Physical Outcome, and Downstream Evidence Review

**Status:** CPU contract repair complete; Native runtime conformance not run  
**Scope:** Phase 5 engineering evidence only; PR #138 cohort and arrival freeze unchanged

## Executive conclusion

The repository previously had a correct CPU DVA-ER policy and an offline
physical-evidence join, but it did not have a production provider that could
construct DVA-ER inputs from one live EngineCore. The formal archive also did
not require the physical-decision join or downstream observations.

This change closes the CPU/interface and archive-contract gaps. It does not
claim that pinned vLLM has supplied the evidence on GPU. DVA-ER Native runtime
conformance remains `NOT_RUN`; the production provider remains
`NOT_INSTALLED` until the live retention integration exposes it.

## 1. Runtime data sources and call chain

The existing Phase 5E path installs one controlled retention hook on the
verified EngineCore and records selection/physical events through
`Phase5ERuntimeEventSource`. It also captures terminal BlockTable hashes before
`Scheduler._free_request` performs Native cleanup. This path supports A3
retention evidence, but it did not construct the DVA-ER decision snapshot.

`DVAERNativeDecisionProvider` now defines the required production boundary:

1. a complete live BlockPool snapshot, including all blocks, exact
   FreeKVCacheBlockQueue order, refcount, owners, and protected owners;
2. a live legal-candidate/Program/Prefix identity snapshot;
3. controller-armed follow-up timers from the same EngineCore clock domain;
4. observation, timer-armed, and decision timestamps with fail-closed ordering;
5. immutable hashes for pool, queue, refcount, and protection state.

It rejects cross-EngineCore state, incomplete owner/protection identities,
future observations, non-controller timers, and incomplete timer coverage.
It never reconstructs these fields from future trace turns or reuse outcomes.

The remaining Native integration change is explicit: the live runtime
integration must expose `dva_er_native_decision_provider` and populate its
three readers at the forced decision boundary. Until then,
`production_provider_status()` returns `NOT_INSTALLED`, and CPU fixtures cannot
be interpreted as Native PASS.

## 2. DVA-ER decision evidence

Every candidate decision now preserves the predicted Native victim sequence
for every scored Entry, not only the selected Entry. Validation requires exact
coverage of the score set, finite scores, unique non-negative block identities,
and equality between the selected Entry's sequence and the selected victim
sequence.

The adapter continues to use only decision-time DVA-ER inputs. Missing input,
invalid refcount/protection, stale timers, or future information fails closed.

## 3. Decision to physical outcome

The independent join now binds:

- stable Decision ID and Pressure Boundary ID;
- complete per-Entry loss and predicted victim sequences;
- selected Entry and Native SelectionPlan;
- matched, unmatched, and hashless physical victims;
- Block ID to content identity mappings.

Wrong Decision/Boundary identities, missing content identity, duplicate block
IDs, or a SelectionPlan that differs from the selected prediction fails closed.

Formal run manifests and the campaign archive now require two additional
immutable evidence streams: `decision_physical_events` and
`downstream_observations`. The archive can no longer pass while silently
omitting these files.

## 4. Downstream observation boundary

The new independent downstream evaluator links evicted content identities to
later request prefix identities and records Native prompt tokens (N), reusable
prefix tokens (E), Native cached tokens (C), and observed `E-C`. It enforces
`0 <= C <= E <= N`, unique request identities, and complete prefix-content
identity.

This is an observational association only. Every row and aggregate retains:

`eviction_causal_attribution = NOT_ESTABLISHED`

`downstream_recompute_attribution = NOT_ESTABLISHED`

Later access to the same content does not prove that a particular eviction
caused the miss or recomputation. A causal claim requires a separately frozen
counterfactual design and is not introduced here.

## 5. Tests and evidence schemas

CPU tests cover:

- complete live pool/refcount/protection/owner/timer snapshot construction;
- cross-EngineCore evidence, missing owner identity, and future timer rejection;
- all-candidate predicted victim sequences;
- Decision/Pressure/SelectionPlan/Physical Outcome identity binding;
- content identity coverage;
- downstream N/E/C and recomputation observation;
- missing physical or downstream evidence;
- archive rejection when required evidence streams are absent.

These are CPU contract tests. They do not replace a real Native/GPU run.

## 6. Gate impact and remaining work

| Area | CPU/interface status | Native status | Gate effect |
|---|---|---|---|
| DVA-ER input Provider | Implemented, fail closed | `NOT_INSTALLED` / `NOT_RUN` | D gate remains open |
| Complete candidate victim predictions | PASS | Not observed | Required before D acceptance |
| Decision to physical join | PASS | Not observed | Required archive stream |
| Downstream N/E/C association | PASS | Not observed | Attribution remains `NOT_ESTABLISHED` |
| Formal archive binding | PASS | No campaign executed | E execution remains unauthorized |

Before Native conformance, the same EngineCore integration must install the
DVA provider, emit complete candidate evaluations, SelectionPlans, physical
content identities, and later prefix observations, then run the independent
evaluator over the archived raw evidence. Any unobservable field must fail
closed rather than be replaced with Mock data.

## 7. Protocol and metrics assessment

No change to the frozen cohort, Group construction, arrival realization,
systems, primary metric, or statistical design is required by this repair.
The evidence contract and archive schema are strengthened. If M1/M4 later want
to turn observational downstream association into a causal estimand, that
would require a Protocol/Metrics amendment; this implementation deliberately
does not do so.
