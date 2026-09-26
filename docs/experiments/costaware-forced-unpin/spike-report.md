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
| Unit tests | `tests/test_costaware_forced_unpin.py` (16 tests) |
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
ranking and the cost-aware ranking in every linear-profile scenario**,
including the heavy-tail regime with 40 forced unpins and the
affine-prefill regime with a small (0.5 s) overhead. Forced-unpin victim
*sequences* differ only by permutation (unit tests confirm the rankings do
diverge on constructed states); the victim *sets* and all aggregate
outcomes coincide. E.2 shows this neutrality is specific to the linear
profile shape.

### E.2 Prefill-profile matrix (escape route b: non-linear cost)

The linear profile makes `C_recompute / Blocks` constant, so the score
cannot differentiate. To close that escape route the four forced-unpin
scenarios were replayed under three non-linear PrefillReload shapes,
normalized so the 32k-token cost equals the canonical linear value:
`affine-5s` (`C(r) = 5 s + spt*r`, fixed launch overhead), `power-0.5`
(`C(r) = spt*r*(r/32k)^-0.5`, small prefixes expensive per block) and
`power-1.5` (large prefixes expensive per block).

| Cell | baseline unpin / recompute s / misses | ours unpin / recompute s / misses | delta |
| --- | --- | --- | --- |
| mixed_length @ linear | 13 / 83.07 / 24 | 13 / 83.07 / 24 | 0 (control) |
| mixed_length @ affine-5s | 24 / 139.62 / 15 | **17 / 130.03 / 15** | **-6.9%** |
| mixed_length @ power-0.5 | 19 / 150.39 / 29 | **18 / 144.37 / 26** | **-4.0%** |
| mixed_length @ power-1.5 | 7 / 24.60 / 10 | 7 / 24.60 / 10 | 0 |
| anticorrelated @ linear | 19 / 75.98 / 18 | 19 / 75.98 / 18 | 0 (control) |
| anticorrelated @ affine-5s | 17 / 155.33 / 18 | **16 / 138.20 / 15** | **-11.0%** |
| anticorrelated @ power-0.5 | 15 / 82.84 / 15 | 15 / 82.84 / 15 | 0 |
| anticorrelated @ power-1.5 | 17 / 58.74 / 17 | 17 / 58.74 / 17 | 0 |
| heavy_tail_aged @ linear | 40 / 295.34 / 28 | 40 / 295.34 / 28 | 0 (control) |
| heavy_tail_aged @ affine-5s | 45 / 413.98 / 26 | 45 / 413.98 / 26 | 0 |
| heavy_tail_aged @ power-0.5 | 40 / 296.30 / 28 | **38 / 262.23 / 25** | **-11.5%** |
| heavy_tail_aged @ power-1.5 | 41 / 295.30 / 28 | 41 / 295.30 / 28 | 0 |
| high_pressure @ linear | 0 / 20.59 / 29 | 0 / 20.59 / 29 | 0 (control) |
| high_pressure @ affine-5s | 26 / 239.81 / 42 | 26 / 239.81 / 42 | 0 |
| high_pressure @ power-0.5 | 22 / 116.41 / 41 | 21 / 116.41 / 41 | 0 |
| high_pressure @ power-1.5 | 0 / 2.31 / 13 | 0 / 2.31 / 13 | 0 |

**Escape route (b) is real and measured**: under non-linear cost with a
heterogeneous protected pool, the cost-aware ranking reduces total
recomputation by 4-11.5% and reduces misses by up to 3 per scenario, with
**zero regressions in any cell**. The linear control cells reproduce the
main-run numbers bit-for-bit, confirming the matrix wiring. The mechanism
in the winning cells is textbook per-block greedy: the score sacrifices
large prefixes with low loss per block (freeing the target in fewer
releases: 24 -> 17 unpins in `mixed_length@affine-5s`) and keeps small
prefixes whose fixed launch overhead makes each cached block expensive to
lose.

The null cells are explained by the TTL filter, not by the score: under
`power-1.5` small prefixes have `R` far below the tool-gap scale, so their
TTL collapses to ~0 and they never enter the protected pool, leaving a
single size class whose per-block loss is uniform again. **Divergence
requires both (i) non-uniform per-block loss and (ii) at least two
different cost classes admitted into the protected pool.**

`lambda = 1` is identical to `lambda = 0` in every cell, confirming that
the queue-delay term cannot differentiate candidates (it is a global mean,
see F.3).

### E.3 Planning overhead

`prepare()` on a synthetic pressured state (60 entries / 400 queue blocks
/ 5 forced releases / best of 20 reps):

```text
baseline coordinator   : 0.1307 s
cost-aware (total)     : 0.0036 s   (~37x faster)
cost-aware (marginal)  : 0.1206 s   (rejected ablation, F.6)
```

The baseline ranking's tie-break (`_newly_eligible_blocks_after_release`)
rescans the whole queue per candidate per release iteration
(O(releases x candidates x queue)); the total-block score is O(samples)
per candidate. The cost-aware override is therefore cheaper, not more
expensive, while the marginal ablation inherits the baseline's quadratic
rescan. A giant-context variant of the heavy-tail scenario (131k-196k
tokens, 20k free-queue blocks) was attempted and abandoned after more
than ten minutes of wall clock dominated by baseline planning alone —
the quadratic queue rescan is itself a scalability finding for the
frozen baseline, not for the proposed method.

## F. Findings and failure scenarios

1. **Linear PrefillReload makes the request-level score structurally
   flat.** With (near-)linear prefill, `C_recompute/Blocks` is the same
   constant for every prefix, so the score collapses to `P_return`
   ordering, which is monotone in the remaining deadline the baseline
   already ranks on. This is not a harness artifact: the project's own
   canonical Metal profile is a single point interpolated linearly. The
   profile matrix (E.2) confirms this is the *only* condition under which
   the ranking is provably neutral.
2. **The TTL layer is itself the cost-aware filter.** `argmax_T
   [F(T)(T_q*eta+R) - T]` gives TTL ~ 0 unless `R` is comparable to the
   tool-gap scale; cheap-to-recompute prefixes are never protected, so
   they never reach the release decision. The release decision only sees
   entries with large `R`. This filter also *homogenizes* the protected
   pool: under `power-1.5` only the largest size class survives the
   filter, and the score has nothing left to differentiate (E.2 null
   cells).
3. **`C_queue` is a global mean, not per-request.** `TTLInput.
   queue_delay_t_seconds` is `QueueDelayHistory.mean_seconds()`, identical
   for every candidate in one decision. The `lambda * C_queue` term cannot
   differentiate victims; it only shifts TTL globally through feedback.
   Confirmed empirically: `lambda=1` equals `lambda=0` in all 16 matrix
   cells.
4. **Forced unpin only exists in the large-context regime.** In all
   small/medium-prefix scenarios (2k-4k tokens with ~4 s gaps) TTL ~ 0 and
   all misses flow through ordinary expiry + LRU, identical by
   construction for any release ranking.
5. **Empty-entry release waste (real, fixed).** The baseline ranking can
   spend its first release on an entry whose blocks were already
   physically evicted (earliest deadline, no blocks); the score sends
   block-less entries to `+inf` and releases productive entries first
   (unit-tested).
6. **The marginal-block denominator is the wrong refinement (rejected).**
   `Score = P * C / newly_eligible_blocks` was implemented as a config
   ablation for co-protected (shared) entries and **rejected by analysis
   and unit test**: for a B/C co-owned block pair the iterative release
   loop already sequences the two cheap co-owner releases (combined loss
   ~0.2 s), while the marginal form refuses to release a co-protected
   entry at all and falls back to the expensive single-owner entry
   (~1.0 s loss). The total-block form handles co-protection correctly by
   construction; the marginal form also costs as much planning time as the
   baseline (0.1206 s vs 0.1307 s, E.3) because it rescans the queue per
   candidate. The correct marginal *numerator* (loss proportional to the
   evicted suffix) needs positional block information that only exists at
   block level.
7. **What actually differentiates (the win condition).** Non-uniform
   per-block loss *and* a heterogeneous protected pool. Measured wins of
   4-11.5% recomputation reduction in E.2 come from profiles with a fixed
   launch overhead (small prefixes expensive per block) or sub-linear
   scaling, combined with the TTL filter admitting at least two cost
   classes.

Failure scenarios for the idea as formulated: any workload where (a)
prefixes are homogeneous or linear-cost, (b) tools are homogeneous, or
(c) contexts are small relative to gap scale. On the canonical linear
profile the request-level ranking is exactly neutral (E.1); under
non-linear cost it wins measurably (E.2) with no observed regression.

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

### G.1 Literature evidence for the cost curve and the design (2026-09-26)

Verified against arXiv (search engines blocked; abs/HTML pages fetched
directly):

- **InferCept** (arXiv:2402.01869, UCSB/UCSD) is the origin of this whole
  line: it reports that recomputation of already-computed contexts is
  **37-40% of total model forwarding time** in augmented-LLM workloads,
  and its preserve/discard/swap decision is driven by `T_fwd(C)` — an
  explicitly measured "scheduled tokens -> iteration time" mapping. It
  establishes both the cost-curve measurement methodology and the payoff
  ceiling for getting victim selection right.
- **KVFlow** (arXiv:2507.07400, UCSD+AWS) is the current SOTA for agentic
  prefix caching. Its eviction priority is **pure future-reuse distance**
  ("steps-to-execution") with **no cost term**: agents closer to their
  next activation are retained longer, shared nodes take the most
  conservative child priority, and dynamic suffixes are evicted first.
  It beats SGLang's LRU radix cache by 1.83x-2.19x, which proves the
  reuse-distance dimension alone is worth more than anything measured in
  this spike. Its Figure 2(b) is a directly citable measured
  prefill-latency-vs-context-length curve (Llama-3.1-8B, batch size 1),
  alongside the PCIe-swap-vs-recompute comparison. **The request-level
  score proposed here is complementary to KVFlow**: it adds the loss
  dimension KVFlow omits, and KVFlow adds the reuse-distance dimension
  the frozen TTL only approximates.
- **KVCache Cache in the Wild** (arXiv:2506.02634, USENIX ATC'25) is the
  "Workload-Aware Eviction" characterization: reuse probability and reuse
  time are diverse overall but **predictable per request category**, the
  cache size needed for an ideal hit ratio is moderate, and the
  workload-aware eviction policy helps most **under limited cache
  capacity** — consistent with the high-pressure observations in E.1 and
  the empirical basis for `P_return`.
- **Sarathi-Serve** (arXiv:2403.02310) establishes that prefill saturates
  GPU compute and that its cost is well structured by chunk size; the
  fixed-overhead tail of the cost curve follows from the same
  measurement tradition.

**Cost-curve expectation for the qualified platform.** Prefill cost
decomposes as `2*N*P` (linear) + `2*N^2*d*L` (attention) + fixed
overhead, so per-token cost is elevated at both ends and flattest in the
middle. For Qwen2.5-0.5B (`P ~ 0.5B`, `d = 896`, `L = 24`) the attention
term catches the linear term at `N* ~ 23k` tokens, giving an estimated
per-block loss ratio of roughly 1.1x at 4k, 1.3x at 8k, 1.6x at 16k and
2.3x at 32k relative to 2k tokens — a FLOPs lower bound, since attention
kernels typically achieve lower efficiency than the linear GEMMs and bend
the curve earlier. The canonical profile point (`PrefillReload(256) =
0.0887 s`) sits in the flat region and therefore **hides this curvature**
by linear extrapolation. Consequence for the decision: on this platform
the non-uniformity — and hence the request-level win — is expected to
concentrate in **long-context pools (>8k tokens)**, while mid-range pools
stay neutral. The power-1.5 matrix cell (E.2) probed exactly this
long-tail regime and was null only because the TTL filter collapsed the
protected pool to a single size class there; a real smooth curve keeps
several size classes protected, so the win condition is more achievable
than that cell suggests. Measuring the real `C(r)` curve on Metal/H100
remains the single decisive experiment.

## H. Final verdict

**Go for the request-level method under a stated condition; block-level
remains the primary contribution.**

- **Insertability and cost (proven).** Contract-clean injection with the
  frozen default path byte-identical (16 unit tests, 616 regression tests
  green), and the total-block score plans ~37x faster than the frozen
  baseline ranking (E.3).
- **Effectiveness (now measured, conditionally).** On the canonical linear
  PrefillReload profile the ranking is provably neutral (E.1, F.1). Under
  non-linear prefill cost with a heterogeneous protected pool it is
  **measurably better: 4-11.5% less recomputation and up to 3 fewer misses
  per scenario, with zero regressions in 16 matrix cells** (E.2). The win
  condition is precise and testable: non-uniform per-block loss plus at
  least two cost classes admitted by the TTL filter (F.7).
- **Conditions before claiming it for the paper.** (i) The qualified
  runtime must produce a non-linear PrefillReload profile (measure the
  real `C(r)` curve on Metal/H100 instead of interpolating the single
  256-token point linearly); G.1 predicts the curvature concentrates
  above ~8k tokens on Qwen2.5-0.5B (attention crossover ~23k), so the
  experiment must cover long-context pools. If the real profile is linear
  in the served size range, the method is neutral there and should be
  reported as such. (ii) `lambda * C_queue` needs a per-request queue
  signal (F.3) before the queue term can contribute; it is currently a
  global mean. (iii) The marginal-block refinement is rejected (F.6); do
  not ship it.
- **Recommended next step (Go):** block-level victim selection remains
  the primary contribution path (G), because partial-prefix retention is
  the only way to obtain the positional (leading-vs-suffix) loss
  structure that request-level granularity provably cannot express
  (F.6). The request-level coordinator stays in the tree as the
  fallback tier and as the policy that already runs when the real
  profile turns out non-linear.
- The real-runtime validation boundary still applies: this spike ran on
  the deterministic functional harness (Windows host, no vLLM process);
  any quantitative claim for the paper requires the qualified Metal/H100
  profile, as recorded in `docs/continuum-baseline-implementation.md`.
