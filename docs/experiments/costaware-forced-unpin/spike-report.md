# Cost-Aware Forced-Unpin Spike Report

Branch: `feature/cost-aware-forced-unpin-spike`
Date: 2026-09-24
Scope: Phase 2 pre-design feasibility spike for request-level cost-aware
victim selection on the frozen Phase 1B Continuum baseline.

This report is based on the repository's actual code, verified before any
implementation, and on a deterministic minimal experiment. It is a
research-direction decision record, not a baseline change.

---

## A. Current code architecture (verified)

```text
orchestrator / workload events
        |
        v
RuntimeCoordinator (src/kvopt/continuum/runtime.py)
    histories: ServerGapHistory / ExternalToolDurationHistory /
               QueueDelayHistory / CompletedProgramEtaHistory
    TurnFinished -> TTLInput -> estimate_ttl (src/kvopt/continuum/ttl.py)
    RetentionManager.upsert(protected=True, block_ids)        [ pin ]
        |
        v   (native vLLM allocation path, monkey-patched)
FreeKVCacheBlockQueue.popleft_n  ->  install_retention_hook.retained_popleft
    (src/kvopt/runtime/vllm/observer.py)
        |
        v
RetentionRuntimeIntegration.apply_pressure
    (src/kvopt/runtime/vllm/retention_integration.py)
        |
        v
RetentionAwareSelectionCoordinator.prepare
    (src/kvopt/continuum/pressure.py)          [ forced-unpin victim selection ]
        |
        v
SelectionPlan validation -> RetentionManager.commit_pressure_releases
    (protected=False)                           [ unpin ]
        |
        v
remove_selected -> queue.remove -> BlockPool._maybe_evict_cached_block
    -> RetentionManager.observe_eviction (reverse-index cleanup)
```

Key facts verified in code, several of which correct assumptions in the
original idea:

1. **Pin/unpin is not `pin_request`/`unpin_request`.** The adapted baseline
   has no vLLM pin API; "pin" is `RetentionManager.upsert(protected=True)`
   and "unpin" is `commit_pressure_releases` / lazy `expire_due`, both
   purely logical flags over free cached blocks.
2. **Memory pressure triggers at `popleft_n`.** Allocation failure does not
   raise; the hook intercepts the free-queue pop, plans releases, and
   removes validated victims through the existing queue/BlockPool path.
3. **TTL expiry is not a free and not an eviction.** `expire_due` /
   `ordinary_expired_entries` only clear the protection flag; blocks stay
   in the free queue as hashed APC-cached blocks until they are physically
   selected by a later allocation (ordinary LRU path).
4. **Forced-unpin is not LRU eviction.** The release decision (which
   protected entry loses protection) is separate from the physical victim
   order (still `(tier, native LRU rank)` in `SelectionPlan`).
5. **A request's blocks** are recorded while alive via `BlocksObserved`
   (from `KVCacheManager.get_block_ids`-equivalent observation); the
   retention entry is keyed `(program_id, prefix_id)` and owns a list of
   `BlockIdentity`. `ref_cnt` is never mutated (soft protection, freeze §6).
6. **The frozen baseline release ranking** (freeze §8) is
   `earliest retention deadline -> native LRU key -> stable identity`
   (`_release_sort_key` in `pressure.py:246`).

## B. Baseline forced-unpin flow (actual call chain)

```text
request turn finishes (non-terminal)
 -> RuntimeCoordinator._handle_turn_finished
    (histories + queue-delay mean + eta + PrefillReload(r))
 -> estimate_ttl: argmax_T [ F(T) * (T_q * eta + R) - T ]   (empirical CDF)
 -> RetentionManager.upsert(protected=True, deadline=finish+TTL)   [ pin ]
 -> ... native allocation calls popleft_n(required_blocks)
 -> retained_popleft -> apply_pressure(mode, blocks, required_blocks, now)
 -> coordinator.prepare(candidates, planning_snapshots, required, now)
      1. ordinary expired entries (deadline <= now, not waiting) -> tier 1
      2. while eligible < target:
           rank protected entries by (deadline, native LRU key, identity)
           release the lowest one                       [ victim selection ]
 -> SelectionPlan (contract-validated) -> commit_pressure_releases [ unpin ]
 -> remove_selected -> native queue removal + _maybe_evict_cached_block
 -> observe_eviction strips stale block edges
```

## C. Minimal modification points (as implemented)

| Change | File / symbol |
| --- | --- |
| New proposed-method module | `src/kvopt/costaware/forced_unpin.py` — `CostAwareForcedUnpinCoordinator`, `estimate_conditional_return_probability`, `estimate_eviction_loss`, `ForcedUnpinConfig` |
| Injection seam (default unchanged) | `src/kvopt/runtime/vllm/retention_integration.py` — `RetentionRuntimeIntegration.__init__(selection_coordinator=None)` and `apply_pressure` uses `self._selection_coordinator` |
| Unit tests | `tests/test_costaware_forced_unpin.py` (14 tests) |
| Experiment harness | `experiments/costaware_forced_unpin/run_experiments.py` + `results/summary.json` |

Only the release ranking is overridden; TTL, histories, retention state,
tier assignment, `SelectionPlan` contracts, and native bookkeeping are
inherited from the frozen baseline. The frozen default path is
byte-identical when no coordinator is injected (all 616 pre-existing
tests pass unchanged).

## D. Minimal prototype design

Per-candidate score, computed only from the frozen `TTLInput` snapshot
already attached to every `RetentionEntrySnapshot`:

```text
P_return(r)   = P(gap ends <= deadline | still running)
                = (F(deadline) - F(elapsed)) / (1 - F(elapsed))
                from the same history tier the TTL estimator selected
                (tool-specific / global; 1.0 for cold start)
C_recompute   = ttl_input.prefill_reload_seconds          (OBSERVED input)
C_queue       = ttl_input.queue_delay_t_seconds           (OBSERVED input)
Memory(r)     = len(entry.block_ids)

Score(r) = P_return(r) * (C_recompute(r) + lambda * C_queue(r)) / Memory(r)
```

Release order: ascending score, deterministic tie-break by
`(deadline, stable identity)`. Entries with no observed blocks score
`+inf` (released last). Coordinator reuses the parent `prepare()` loop and
only overrides `_release_sort_key`.

## E. Experiment results

Deterministic discrete-event harness driving the real components
(`RuntimeCoordinator` + `RetentionManager` + `RetentionRuntimeIntegration`,
CONTROLLED mode), no vLLM process. Metrics are functional counters and
recompute-cost proxies from the canonical PrefillReload profile
(`PrefillReload(256) = 0.0887 s`, linear), not measured GPU latency.
Lognormal tool-gap tools (fast ~1 s, search ~4 s, slow ~20 s, heavy
~5 s sigma 1.2 for a protection window at 32k-64k-token prefixes);
4-turn agent programs; 6 warm-up samples per tool.

| Scenario | Policy | unpins | hit rate | recompute s | misses |
| --- | --- | --- | --- | --- | --- |
| uniform_medium (2k tok) | baseline / ours-l0 / ours-l1 | 0 / 0 / 0 | 0.847 | 7.81 | 11 |
| mixed_length (1k-32k tok) | baseline / ours | 13 / 13 | 0.667 | 83.07 | 24 |
| fast_slow_tools (4k tok) | baseline / ours | 0 / 0 | 0.958 | 4.26 | 3 |
| anticorrelated (32k fast / 2k slow) | baseline / ours | 19 / 19 | 0.750 | 75.98 | 18 |
| high_pressure | baseline / ours | 0 / 0 | 0.597 | 20.59 | 29 |
| heavy_tail_aged (32k/64k, sigma 1.2) | baseline / ours | 40 / 40 | 0.667 | 295.34 | 28 |
| affine_prefill_overhead | baseline / ours | 20 / 20 | 0.631 | 117.72 | 31 |

**All request-level outcome metrics are identical between the baseline
ranking and the cost-aware ranking in every scenario**, including the
heavy-tail regime with 40 forced unpins and the affine-prefill regime
designed to break the per-block cost uniformity. Forced-unpin victim
*sequences* differ only by permutation (unit tests confirm the rankings do
diverge on constructed states); the victim *sets* and all aggregate
outcomes coincide.

Planning overhead (`prepare()`, 60 entries / 400 queue blocks / 5 forced
releases / best of 20 reps):

```text
baseline coordinator : 0.2278 s
cost-aware coordinator: 0.0044 s   (~51x faster)
```

The baseline ranking's tie-break (`_newly_eligible_blocks_after_release`)
rescans the whole queue per candidate per release iteration
(O(releases x candidates x queue)); the score is O(samples) per candidate.
The cost-aware override is therefore cheaper, not more expensive. A
giant-context variant of the heavy-tail scenario (131k-196k tokens, 20k
free-queue blocks) was attempted and abandoned after more than ten
minutes of wall clock dominated by baseline planning alone — the
quadratic queue rescan is itself a scalability finding.

## F. Findings and failure scenarios

1. **Linear PrefillReload makes the request-level score structurally
   flat.** With (near-)linear prefill, `C_recompute/Blocks` is the same
   constant for every prefix, so the score collapses to `P_return`
   ordering. This is not a harness artifact: the project's own canonical
   Metal profile is linear.
2. **`P_return` is monotone in remaining deadline** within one tool
   distribution, and the frozen baseline already releases the smallest
   remaining deadline first. The cost-aware ranking is a monotone
   re-parameterization of the baseline ordering in same-tool regimes.
3. **The TTL layer is itself the cost-aware filter.** `argmax_T
   [F(T)(T_q*eta+R) - T]` gives TTL ~ 0 unless `R` is comparable to the
   tool-gap scale; cheap-to-recompute prefixes are never protected, so
   they never reach the release decision. The release decision only sees
   entries with large `R`, whose per-block loss has converged.
4. **`C_queue` is a global mean, not per-request.** `TTLInput.
   queue_delay_t_seconds` is `QueueDelayHistory.mean_seconds()`, identical
   for every candidate in one decision. The `lambda * C_queue` term cannot
   differentiate victims; it only shifts TTL globally through feedback.
5. **Forced unpin only exists in the large-context regime.** In all
   small/medium-prefix scenarios (2k-4k tokens with ~4 s gaps) TTL ~ 0 and
   all misses flow through ordinary expiry + LRU, identical by
   construction for any release ranking.
6. **Empty-entry release waste (real, fixed).** The baseline ranking can
   spend its first release on an entry whose blocks were already
   physically evicted (earliest deadline, no blocks); the score sends
   block-less entries to `+inf` and releases productive entries first
   (unit-tested).
7. **Shared-prefix analysis (why sharing does not rescue request-level).**
   With a shared system-prompt region, releasing an entry only frees its
   private blocks (co-owned shared blocks stay protected), and the
   returning request re-hits the shared region. Marginal loss is again
   proportional to marginal blocks; per-block loss stays uniform. The
   refined request-level objective
   `Score = P * C / marginal_blocks` (computable from
   `_newly_eligible_blocks_after_release`) is the correct form but still
   degenerate under linear cost. It is documented here as the fix to apply
   IF a request-level policy is ever revisited.

Failure scenarios for the idea as formulated: any workload where (a)
prefixes are homogeneous or linear-cost, (b) tools are homogeneous, or
(c) contexts are small relative to gap scale — which covers all eight
tested regimes, including the adversarial ones designed to favor the
score (anticorrelated size/gap, affine prefill overhead, heavy-tail aged).

## G. Request-level -> block-level follow-up design

The evidence above redirects the cost-aware effort to block granularity,
where per-block loss is genuinely non-uniform because APC reuse requires
the prefix to be cached **contiguously from position 0**:

```text
request-level signals (TTL input, histories)
    -> block-level value: positional prefix value
       value(block i) ~ P_return(prefix) * (cost of the suffix it anchors)
    -> vLLM BlockPool eviction interface
       (existing Phase 1A EvictionPolicyAdapter boundary)
    -> LRU replacement only as the fallback tier
```

Concrete opportunities, all compatible with the current architecture
(verified against code, no Radix Tree assumption — vLLM 0.27.1 APC uses
per-request `block_hashes` + free-queue LRU):

1. **Partial-prefix retention.** Evict only suffix blocks of a protected
   prefix; the returning follow-up keeps a partial APC hit (leading run)
   and re-prefills only the evicted suffix. Loss becomes proportional to
   evicted blocks * position, which is exactly the non-uniform
   loss/block structure the request-level score lacks. The
   `EligibilityTier`/`BlockEligibilitySnapshot` contracts already model
   per-block eligibility, so this is an adapter-level change.
2. **Reuse probability + prefix offset** (Workload-Aware-Eviction style):
   map each entry's `P_return` and its `TTLInput` reuse history onto its
   block list; leading blocks inherit the full reuse probability, suffix
   blocks the discounted one. Inputs already exist per entry; the block
   mapping uses the observed `block_ids` order.
3. **Execution distance / future reuse** (KVFlow style): the pending
   server-gap state (`_pending_server_gaps`) already records
   `previous_finish_timestamp` and tool type; an estimated return time per
   program is one interpolation away. This orders blocks by expected
   reuse distance instead of LRU recency.
4. **Shared blocks / ref_cnt**: `_entries_by_block` already tracks
   multi-owner blocks; a block-level policy must treat co-owned blocks as
   the cheap victims' opposite (high aggregate loss). Never mutate
   `ref_cnt` (freeze §6) — ownership weighting stays in the policy.
5. **Priority-aware BlockPool interface (RFC #37003 style)**: the
   `EvictionPolicyAdapter` + `VLLMEvictionBridge` pair is already a
   priority-selection interface in front of `popleft_n`; a block-level
   cost policy plugs in exactly where `NativeLRUAdapter` sits today,
   with retention eligibility (`RetentionAwareLRUAdapter`) unchanged.

Not recommended: rewriting `BlockPool` allocation bookkeeping (freeze §6),
or porting the request-level TTL objective to blocks (it optimizes
protection windows, not victim value).

## H. Final verdict

**Conditional Go — with a redirect.**

- The request-level cost-aware forced-unpin as formulated is **insertable
  (proven: contract-clean, 14 unit tests, 616 regression tests green) and
  cheap (36x faster planning), but empirically equivalent to the frozen
  deadline heuristic** in every tested regime, for structural reasons
  (F.1-F.4) that are properties of the frozen information set, not of the
  implementation.
- Conditions to satisfy before any further request-level work:
  per-entry token counts and shared/private decomposition in the
  retention snapshot, and a per-request queue signal. All three require
  baseline-surface changes and are not justified by current evidence.
- **Recommended next step (Go):** move directly to the block-level
  objective in G (partial-prefix retention + positional reuse value) on
  the existing `EvictionPolicyAdapter` boundary, which is where
  `Ours-Evict` (the project's primary contribution) is supposed to live
  anyway. The spike's harness, `CostAwareForcedUnpinCoordinator`, and
  injection seam are reusable as the request-level fallback tier of that
  design.
- The real-runtime validation boundary still applies: this spike ran on
  the deterministic functional harness (Windows host, no vLLM process);
  any quantitative claim for the paper requires the qualified Metal/H100
  profile, as recorded in `docs/continuum-baseline-implementation.md`.
