# Phase 2I A3 Native Runtime Integration — Static Preflight

Status: **CPU/Mock implementation and static preflight only**. No GPU Native run
is authorized or reported by this change.

## Frozen integration boundary

The runtime selects A3 only when both conditions are explicit:

- `campaign_kind = phase2i_a3_native_integration`
- `backend_options.phase2g_release_policy = A3`

All other campaign names are rejected. A0, A1 and A2 paths retain their existing
coordinators. A3 uses `A3NativeSelectionCoordinator`, which calls the reviewed
`A3SuffixCostStrategy`; it does not reproduce the formula in the runtime adapter.
The strategy continues to compose frozen A1 and changes only ladder Step 2.

For every live decision the adapter supplies:

- `verification_mode = native_live`;
- the current native hash process ID;
- the persisted decision event ordinal;
- the latest pre-decision `ChainDepthProof`;
- current slot content identities from `A2NativeSnapshotRegistry`.

Missing identity, wrong process, stale/superseded proof, recycled content or an
unscorable candidate causes the entire Step 2 decision to fall back to frozen A1.
Historical replay verification is not reachable from the Native coordinator.

## Evidence joins and pressure counter repair

Each pressure decision receives an immutable `decision_id`. The runtime persists:

1. `FORCED_RELEASE_DECISION` (the existing candidate/release snapshot);
2. `FORCED_RELEASE_DECISION_BINDING` (decision, barrier, stage, pressure request,
   exact forced-release event ordinal and before/after counter);
3. `A3_SUFFIX_RELEASE_DECISION` (formula inputs, predicted victims and fallback);
4. `NATIVE_ENTRY_RELEASE_SELECTION_PLAN` (actual Native selected block IDs);
5. `NATIVE_SELECTION_PLAN_PENDING`, created only after `apply_pressure()` has
   returned the exact Native SelectionPlan, with the decision/barrier/stage/
   request binding and the current per-block content identities;
6. `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED`, joined to that pending plan only
   when block ID, content identity and the full pressure context match uniquely;
7. `PRESSURE_REQUEST_COMPLETED` and `CONTROLLED_REPLAY_PRESSURE_COMPLETED` with
   the exact bound decision IDs for that request/barrier.

The old global `last_selected_block_ids` field is retained only under the name
`legacy_last_selected_block_ids`. It is not used as Phase 2I evidence. Releases
that occur during ordinary request allocation have no pressure-barrier identity,
so they can no longer be misreported as belonging to the next 40/50/55 barrier.
The pending plan remains valid only until the owning pressure context closes.
Unmatched, ambiguous, wrong-content and late ordinary-request evictions remain
`UNATTRIBUTED`; they are never inherited by a previous pressure decision.
Native hash eviction invalidates the content registry before a recycled block ID
can be used by a later A3 proof. A reused ID without a fresh matching snapshot
therefore causes whole-Step-2 fallback rather than stale attribution.

The decision counter is checked locally, not merely for monotonicity:
`after - before` must equal one exactly when the bound forced-release event has
at least one selected release, and otherwise must equal zero. Adjacent pressure
bindings must chain (`next.before == previous.after`). Barrier counts and bound
decision lists must exactly equal the uniquely joined bindings.

Predicted victims, actual SelectionPlan, physical eviction, content identity and
downstream APC/recomputation remain separate evidence levels.

## Static gates

`kvopt.workload.phase2i_a3_preflight.evaluate_a3_native_preflight` independently
checks persisted-style evidence:

- **Gate I** — A3 is explicit and every A3 record is `native_live` with a process
  identity.
- **Gate C** — every non-fallback score has live content verification and exactly
  recomputes `q × prefill × S / m`.
- **Gate D** — a deterministic Mock decision makes A3 choose differently from A1,
  and the intervention joins the exact forced-release event, actual submitted
  entry release and actual SelectionPlan.
- **Gate O** — decision/request/barrier/stage IDs join uniquely, local counter
  deltas and adjacent bindings are exact, barrier counts equal their decision-ID
  lists, and every attributed physical eviction belongs to the same pending
  SelectionPlan with the same block and content identity.

Negative controls cover score tampering, historical-mode injection, missing live
identity, process mismatch, stale/unbound pressure selections, a forced release
whose counter remains `before=2, after=2`, and physical Block 3 reported for a
SelectionPlan that selected Block 99. CPU-hook integration tests also cover
physical eviction after `apply_pressure()` returns, pressure-context closure,
registry invalidation, block-ID reuse without a fresh snapshot and whole-Step-2
fallback on content mismatch.

The CLI evaluator is:

```bash
python -m scripts.spikes.run_phase2i_a3_static_preflight \
  --events <mock-or-static-events.jsonl> \
  --output <static-preflight-report.json>
```

## Targeted CUDA Preflight plan (not executed)

After M1 authorizes GPU work, use a fresh output directory and the reviewed exact
commit. Run the smallest bounded CUDA configuration that creates at least one
legal multi-candidate Step-2 decision. Verify, in order:

1. model/tokenizer/runtime/config SHA and 2048-block pool binding;
2. content-keyed chain proofs precede each A3 decision in the same process;
3. Gate I/C/D/O all pass from persisted Native evidence;
4. A3 selected entry equals the committed release and actual SelectionPlan;
5. late physical evictions join through the bounded pending plan by decision,
   pressure context, block ID and content identity; ordinary later evictions
   remain unattributed;
6. later APC/recomputation is reported only when a later request supplies that
   evidence; otherwise mark it right-censored/unobserved.

Stop fail-closed on configuration drift, all-Step-2 fallback, missing identity,
unrecomputable score, counter/barrier mismatch or broken physical-content join.
Do not change A3/A1/A2, workload, capacity or pressure in response to results.
