# Phase 2G A2 — Cost-Aware Block Victim Selection (algorithm and interface)

> **Historical scope: A2 algorithm and interface freeze.** “Native integration not started” below was true for the original algorithm-stage handoff; subsequent A2 Native Gate 1/Gate 2, fidelity repair and bounded-value experiments exist. See the [experiment index](../README.md), [A2 bounded evaluation](../phase2g-a2-bounded-value-evaluation.md) and [A2 research judgment](../phase2g-a2-research-judgment.md). Current A2 effectiveness remains inconclusive. Do not read this algorithm-layer test report as a physical benefit result.


Status: **algorithm + algorithm-layer tests complete; native integration not started.**
Entry release, legal candidate set and eviction count are all fixed by Continuum;
A2 changes **only** which legal block is evicted. No native state is touched.

Supersedes nothing: this is the implementation of the marginal-loss idea accepted in
`docs/phase2-cost-aware-joint-design.md` §3.4, made complete and executable.

---

## 1. Objective

Minimise a **proxy-weighted loss** over victim sets. TTFT and queue delay are auxiliary
observations and never enter the decision. The selector does **not** minimise expected
recomputed tokens: $q_c$ is uncalibrated, so no expected-token quantity is defined by
this objective. The actual token benefit of these choices is what A2 Gate 2 measures.

For a victim set $S$:

$$
L(S)=\sum_{c\,:\,S\cap c\neq\varnothing} q_c\cdot\bigl(m_c-j_c(S)+1\bigr),
\qquad
j_c(S)=\min\{\,d_c(b): b\in S,\ b\in c\,\}
$$

| symbol | meaning | unit |
|---|---|---|
| $c$ | a prefix chain, identified by `(program_id, prefix_id)` | — |
| $m_c$ | chain length | blocks |
| $d_c(b)$ | 1-based depth of block $b$ within chain $c$ | blocks |
| $j_c(S)$ | shallowest evicted depth on chain $c$ | blocks |
| $q_c$ | decision-time reuse proxy for chain $c$ | dimensionless, $(0,1]$ |

**Why only the shallowest depth matters.** This is APC semantics, not an
approximation. A prefix either resolves or it does not: once depth $j$ is gone, every
deeper block of that chain is unreachable, so evicting more of them adds no
recomputation. $m_c-j_c+1$ is exactly the number of blocks that would have to be
recomputed if the chain returns.

**Units.** The reported loss is in **weighted block units**: the suffix length is
counted in blocks and the per-token block size $B$ is a constant factor common to every
candidate set, so it is factored out rather than carried. Multiplying the value by $B$
would give a *proxy-weighted block-count*, still not an expected token count, because
$q_c$ is not a probability. The stored field is therefore named
`proxy_weighted_loss`, and `None` (never a number) when the cost model is not
evaluable.

### 1.1 Reuse weight $q_c$

$$q_c=\sigma\!\left(\frac{\text{deadline}_c-t}{\tau}\right),\qquad \sigma(x)=\frac{1}{1+e^{-x}}$$

- `deadline_c` is Continuum's dynamic retention deadline, already computed at decision
  time; $t$ is the decision timestamp; $\tau$ is a time scale.
- $q_c>0.5$ means the TTL has not passed; $q_c<0.5$ means it has passed but the entry
  has not been released yet — the normal state for an entry the pressure loop is about
  to sacrifice.
- **$q_c$ is a ranking proxy, not a calibrated probability and not an expected reuse
  count.** Only its ordering is justified from first principles.
- It is monotone in the deadline, so when $N$ and the bracket are equal across
  candidates the ordering degenerates exactly to deadline-first.

**$\tau$ is frozen, and its magnitude is load-bearing.** Because $L$ sums $q_c$
across chains, two candidates in different chains compete on $q_a s_a$ versus
$q_b s_b$, so the *ratio* of two $q$ values decides, not only their order. Changing
$\tau$ rescales every $q$ non-uniformly (each chain sits at a different deadline
distance from $t$), so a $\tau$ change preserves the deadline ordering and can still
change the selected victim set. A concrete case, with chain $a$'s deadline strictly
earlier than chain $b$'s for every $\tau$ used:

| $\tau$ | $q_a$ | $q_b$ | suffix $s_a$ | suffix $s_b$ | victim |
|---|---|---|---|---|---|
| 30 s | $q_a\approx 2\times10^{-9}$ | 0.269 | 2 | 1 | $a$ |
| 600 s | 0.269 | 0.487 | 2 | 1 | $b$ |

At $\tau=30$ s chain $a$ looks almost free and is taken; at $\tau=600$ s both weights
converge toward $0.5$ and the suffix lengths dominate, so the single-block chain $b$ is
taken instead. Pinned by
`test_tau_changes_the_victim_set_while_the_deadline_order_is_fixed`.

Consequences, stated rather than glossed:

- $\tau$ is **frozen per campaign** and passed in explicitly, never defaulted at the
  call site. Any reported result must state the $\tau$ it used.
- The policy is a **heuristic** whose weighting is a modelling choice. Nothing here
  establishes token savings; that is A2 Gate 2's measurement.

### 1.2 Content identity and depth

- **Identity is the content hash**, never `block_id`. A `block_id` is a recyclable
  physical slot: the same id can name different content at different times.
- **Depth is the block's 1-based position in its chain's ordered hash sequence.** It
  is *not* `native_lru_rank`; rank is recency.
- Provenance rule: depth is only usable when the chain's snapshot and the candidate
  are shown to be the same content, via
  `phase2d_shared_retention._mapping_for_candidate`'s protocol (latest prior snapshot,
  ordered `block_ids` equality, complete payload, no intervening same-process
  eviction). Anything else is an observation gap, not a guess.

---

## 2. Marginal cost and multi-block updates

$$ \Delta(b\mid S)=\sum_{c\ni b} q_c\cdot\max\bigl(0,\;j_c(S)-d_c(b)\bigr) $$

Evicting $b$ then updates, for **every** chain containing $b$:

$$ j_c \;\leftarrow\; \min\bigl(j_c,\;d_c(b)\bigr) $$

### 2.1 Why shared blocks are summed, not collapsed

A shared block belongs to several chains. If it is evicted, **each** of those chains
loses its prefix and each would recompute. Those are separate recomputations, so the
cost is a sum over memberships. Collapsing to one chain understates the loss; summing
never counts the same eviction twice, because each chain is charged at most once for
the shallowest depth it lost.

Worked check (test `test_shared_block_marginal_is_charged_once_per_chain`):
block at depth 3 of chain a (m=4, q=0.9) and depth 5 of chain b (m=6, q=0.1)

$$ \Delta = 0.9\cdot(5-3) + 0.1\cdot(7-5) = 1.8 + 0.2 = 2.0 $$

---

## 3. Victim selection

### 3.1 Legal candidate set

The legal set is $E(R)$ after Continuum's frozen entry release. A2 **cannot** add to
it: it receives the set and returns a subset. Nothing in A2 can release an entry, so
the protection mechanism is unbypassable by construction.

### 3.2 Pseudocode

```text
select(geometry, need):
    if legal is empty or need <= 0:              return ()
    if any block has unproved content,
       or any priced chain lacks a weight:       return native_lru(legal, need)
                                                 + record fallback reasons

    greedy = incremental_greedy(geometry, need)
    best   = greedy
    if exhaustive search enabled and C(|legal|, need) <= budget:
        candidate = enumerate_every_victim_set(geometry, need)
        if candidate.loss < greedy.loss: best = candidate   # greedy wins ties

    return best
```

Incremental greedy:

```text
remaining = legal ; evicted = {}
for step in 1..min(need, |legal|):
    for each b in remaining: cost[b] = Δ(b | evicted)      # recomputed每步
    pick argmin (cost, native_rank, block_id)               # deterministic
    append pick ; update evicted with every membership of the pick
```

### 3.3 Why two selectors

$\Delta$ exhibits diminishing returns in $S$, but greedy minimisation under a
cardinality constraint is still not optimal in general. Two coupling effects are real:

- a first pick that opens a chain makes that chain's remaining blocks free, so the
  *order* in which chains are opened decides the total;
- a shared block's cost depends on which chains are already open.

**Measured**: over 3,684 random geometries (1–3 chains, lengths 2–4, with and without
a shared block, $k\le 3$), incremental greedy was suboptimal in **25** cases, worst gap
0.70 loss units. The exhaustive search therefore earns its place rather than being
defensive padding. These gaps are in the same proxy-weighted block units as $L$, not
tokens.

Minimal counterexample (`test_greedy_is_suboptimal_on_the_counterexample`):

```text
chain a: m=4, q=0.4        chain b: m=3, q=0.2        shared s at a@3 and b@3
need = 2

greedy : a@4 (Δ=0.4) → b@2 (Δ=0.4)   loss = 0.4 + 0.4 = 0.8
optimal: b@1 (Δ=0.6) → b@2 (Δ=0)     loss = 0.2 * 3   = 0.6
```

Greedy spent a pick on a chain it did not need to open; the optimum drains one chain.

### 3.4 Complexity

| selector | time | notes |
|---|---|---|
| incremental greedy | $O(k\cdot n\cdot r)$ | $k=\min(\text{need},n)$ picks, $n$ legal blocks, $r$ memberships per block |
| exhaustive search | $O\binom{n}{k}\cdot(n+k)$ | only run when $\binom{n}{k}\le$ `exact_search_budget` (default 20,000) |
| fallback | $O(n\log n)$ | native rank sort |

The second selector is **bounded exhaustive enumeration**, not branch and bound: it
has no bounding function and no pruning, and it is exact only because it enumerates
every set, and only while the combination count fits the budget. The recorded
selector name is `bounded_exhaustive_search` accordingly.

The exhaustive search is skipped, and `search_truncated` is set, whenever the
combination count exceeds the budget. On the recorded corpus 57 of 87 scorable
decisions exceeded it, which is why the greedy result is the practical answer there and
the exhaustive search is a correctness oracle plus a small-decision improvement.

### 3.5 Ties

Greedy uses the total order `(marginal_cost, native_rank, block_id)`. Rank is included
because it is the frozen engine order, and block id last so the result never depends on
dict iteration order. Verified by `test_ties_break_on_rank_then_block_id` and
`test_selection_is_independent_of_dict_insertion_order`.

The exhaustive search compares victim **sets**, so its tie-break is set-level: among
equal-loss sets, the smallest sorted vector of the members' `(native_rank, block_id)`
pairs wins. Comparing sorted slot ids instead would let an arbitrary low id beat the
frozen engine order. Verified by
`test_exhaustive_ties_prefer_engine_order_over_the_lowest_block_id` and
`test_exhaustive_set_level_ties_prefer_the_engine_order`.

### 3.6 Fallback

If **any** of these holds, A2 returns native LRU order over the legal set and records
the reason:

| reason | trigger |
|---|---|
| `content_unverified` | a hash-carrying legal block has no proved chain membership, or its memberships disagree on the content hash |
| `reuse_weight_missing` | a chain carrying priced content has no decision-time weight |
| `contract_invalid` | the whole request failed `validate_request`; victims are the distinct legal ids in native order |

Fallback reports `proxy_weighted_loss: None` — a loss is never invented. Hashless blocks
are **not** a fallback trigger: they carry no prefix content, so their cost is zero by
construction rather than unknown.

---

## 4. Interface contract (for M6)

Expressed as data the engine populates; see `src/kvopt/costaware/a2_contract.py` and
`FIELD_CONTRACT` for the authoritative table.

### 4.1 Already available

| field | use |
|---|---|
| `block_id` | slot identity only — never content |
| `has_block_hash` | `False` ⇒ zero-cost block |
| `native_lru_rank` | recency tie-break and the native comparator only |
| `required_blocks` | the eviction count |
| decision timestamp | evaluates $q_c$ |

### 4.2 Derivable inside the engine

| field | note |
|---|---|
| `prefix_depth` | position in the request's prefix; **not** from `native_lru_rank` |
| `chain_id` | `(program_id, prefix_id)`; all memberships must be reported |
| `chain_length` | $m_c$ |

### 4.3 Needs exposure — the minimal ask

| field | why | validity | invalidated by |
|---|---|---|---|
| `content_hash` | identity; `block_id` cannot substitute | until slot reallocation or hash eviction | same-process hashed-cache eviction, or a later snapshot showing different content |
| `reuse_weight` | $q_c$; a chain with content but no weight makes the decision unscorable rather than free | recomputed per decision from current retention state | retention entry release, expiry, program completion |

That is **two fields**. Nothing about BlockPool ownership, ref-counting, hash cleanup,
`FreeKVCacheBlockQueue` or request lifecycle changes.

### 4.4 Evaluation-only, never an input

`observed_recomputed_tokens`, `returned_after_decision`. Enforced structurally: the
decision type has no such field, and `assert_no_evaluation_fields` rejects them.

### 4.5 Content-identity guard at the contract boundary

A physical slot holds one content, so the request must say so consistently or the
decision must not be scored. `validate_request` therefore rejects, as plain strings
the caller can log:

| violation | rejection reason |
|---|---|
| a hash-carrying membership with an **empty** (or whitespace-only) `content_hash` | claims an identity it does not have |
| one block whose memberships report **different** `content_hash` values | impossible for one slot ⇒ the input is wrong, not merely ambiguous |
| one `(chain, depth)` claimed with incompatible hashes by different blocks | a chain position cannot hold two contents |

The failure path is explicit and is part of the frozen contract,
`a2_contract.decide()`: validate first, and if anything fails, **log the reasons and
return native LRU order over the distinct legal block ids, restricted to
`required_blocks`**, marked `contract_invalid`, with `proxy_weighted_loss = None`. A
malformed request therefore never enters cost scoring and cannot change a decision.

The fallback must survive the very defects it is invoked for, so it does not simply
sort and slice `request.blocks`:

- **victim ids are deduplicated.** A request with ids `(1, 1, 2)` and
  `required_blocks = 2` would otherwise return `(1, 1)` — naming one physical block
twice, so the engine would evict a block it has already freed and the returned count
would overstate the pressure relieved;
- **the duplicate policy is deterministic**: each id is represented by its smallest
  `(native_rank, block_id)` key, so a duplicate can neither displace the colder record
  nor make the result depend on record order;
- **the count is truncated at the number of distinct ids.** If fewer distinct
  candidates exist than `required_blocks`, the short answer is returned rather than
  padded with a repeat. Reporting a short count is honest; a duplicate is not.

The rejection reasons are still returned in `DecisionOutcome.problems`, so the repair
never hides the diagnosis.

The guard is doubly enforced. `DecisionRequest.to_geometry()` marks a block with a
defective identity as a `content_unverified` gap, so even a caller that skips
`validate_request` gets the selector's native-LRU fallback rather than a scored
malformed block. `LegalBlock.content_hash` (which raises on conflicting hashes) is
therefore load-bearing rather than decorative.

This is a targeted contract guard, not a new identity architecture: it adds no state,
changes no existing identity proof, and reuses the fallback already specified above.

---

## 5. Failure modes

| failure | effect | mitigation |
|---|---|---|
| `q_c` mis-ranks the chains | A2 drains the wrong chain; loss rises | $q$ monotone in TTL only; divergence measured per decision, not assumed |
| $\tau$ rescaled between campaigns | different victims at identical deadline order | $\tau$ frozen and reported; sensitivity pinned by a test |
| slot reuse | stale content attached to a slot | content proof required; unproved ⇒ fallback |
| inconsistent content hashes in the request | malformed block scored as a verified shared block | `validate_request` rejects; `to_geometry` marks a gap; `decide` falls back |
| duplicate block ids in the request | fallback victim list naming one block twice, overstating freed blocks | `decide` deduplicates before truncating; count capped at distinct ids |
| depth from rank | systematically wrong costs | depth never read from rank; enforced by contract |
| shared ownership collapsed | loss understated | all memberships summed |
| greedy suboptimality | up to 0.70 loss units in the random search | exhaustive search where affordable; selector recorded |
| exhaustive search over budget | greedy result only | `search_truncated` flag set, never claimed optimal |
| missing weight treated as free | spurious benefit | raises `MissingReuseWeight`; decision unscorable |

---

## 6. Algorithm-layer verification

`tests/test_costaware_a2_selector.py` (34 tests) and
`tests/test_costaware_a2_contract.py` (41 tests) cover the seven areas required:

| required coverage | tests |
|---|---|
| 1. cost order agrees with LRU | `test_agrees_with_lru_when_depth_ordered_and_q_uniform`, `..._across_chains_when_q_matches_rank` |
| 2. cost diverges from LRU, with modelled loss | `test_diverges_from_lru_when_a_cheap_chain_is_not_the_coldest` |
| 3. multi-chain shared marginal | `test_shared_block_marginal_is_charged_once_per_chain`, `test_evicting_a_shared_block_moves_the_gap_in_every_chain`, `test_shared_block_is_not_double_counted_after_its_chain_is_drained` |
| 4. multi-block updates | `test_multi_block_greedy_drains_one_chain_before_touching_the_next`, `test_marginal_costs_are_recomputed_after_every_pick` |
| 5. unknown weight / wrong identity / slot reuse / stale snapshot | `test_unknown_reuse_weight_falls_back_to_native_lru`, `test_unverified_content_falls_back_and_records_the_reason`, `test_marginal_cost_raises_on_unknown_weight_rather_than_returning_zero`, plus the identity-proof regressions in `tests/test_costaware_a2_evidence.py` |
| 6. ties, determinism, safe fallback | `test_ties_break_on_rank_then_block_id`, `test_selection_is_deterministic_across_repeated_calls`, `test_selection_is_independent_of_dict_insertion_order`, `test_exhaustive_ties_prefer_engine_order_over_the_lowest_block_id`, `test_exhaustive_set_level_ties_prefer_the_engine_order` |
| 7. same legal set / same count / zero violations | `test_victims_are_always_a_subset_of_the_legal_set`, `test_selection_never_exceeds_the_requested_count` |

Two further areas were added in this revision because the objective and the input
contract are themselves claims that need pinning:

| added coverage | tests |
|---|---|
| the score is proxy-weighted block units, not tokens | `test_loss_is_in_weighted_block_units_with_no_token_factor` |
| $\tau$'s scale is load-bearing | `test_tau_changes_the_victim_set_while_the_deadline_order_is_fixed` |
| content identity fails closed at the boundary | `test_empty_content_hash_is_reported`, `test_whitespace_only_content_hash_is_reported`, `test_one_block_with_two_content_hashes_is_reported`, `test_chain_slot_claimed_with_incompatible_hashes_is_reported`, `test_consistent_shared_identity_is_accepted`, `test_invalid_identity_never_enters_cost_scoring`, `test_conflicting_identity_becomes_a_gap_even_without_validation`, `test_decide_scores_a_valid_request` |
| the fail-closed fallback names distinct blocks | `test_intake_detects_the_duplicate_before_the_fallback_runs`, `test_fail_closed_victims_are_never_duplicated`, `test_fail_closed_fallback_returns_every_distinct_candidate_it_has`, `test_fail_closed_deduplication_is_deterministic_under_record_order`, `test_fail_closed_duplicate_keeps_the_coldest_record` |

### 6.1 The three named cases

**Positive (hand-checkable).** Chain a coldest (rank 0..2) but $q_a=0.9$; chain b
warmer (rank 10..12) but $q_b=0.1$; need = 1.

```text
native     : a@3  → loss 0.9 * 1 = 0.9
cost-aware : b@3  → loss 0.1 * 1 = 0.1
```

**Negative control.** Same geometry with $q_a=q_b=0.5$: both rules cost the same, so
no advantage may be claimed. This is the guard against reporting a benefit that comes
from the tie-break rather than from cost.

**Multi-block.** Chain a (m=3, $q$=0.1) and chain b (m=3, $q$=0.9), need = 2.
A2 takes both blocks from a, loss 0.2; touching both chains would cost 1.0.

**What these validate: algorithm correctness only.** No native eviction happens, so
none of them is evidence of runtime benefit. That requires M6's Gate 1.

---

## 7. What is deliberately not done

- no native policy, no adapter wiring, no vLLM change — that is M6's step;
- no claim that A2 improves recomputation on any real workload;
- **no claim that the selector minimises expected recomputed tokens.** $q_c$ is not
  calibrated, so no expected-token objective is defined here; the objective is the
  proxy-weighted loss above, and its token benefit is an A2 Gate 2 measurement;
- no calibration of $q_c$ and no new predictor — the accepted "no new predictor"
  approach is unchanged;
- no A3 joint optimisation, no B1 active release;
- no global combinatorial optimisation: greedy plus a bounded exhaustive search, with
  the budget and the measured greedy gap stated rather than glossed.

## 8. Reproduce

```bash
python -m pytest tests/test_costaware_a2_selector.py tests/test_costaware_a2_contract.py -q
```
