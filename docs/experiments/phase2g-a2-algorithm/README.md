# Phase 2G A2 — Cost-Aware Block Victim Selection (algorithm and interface)

Status: **algorithm + algorithm-layer tests complete; native integration not started.**
Entry release, legal candidate set and eviction count are all fixed by Continuum;
A2 changes **only** which legal block is evicted. No native state is touched.

Supersedes nothing: this is the implementation of the marginal-loss idea accepted in
`docs/phase2-cost-aware-joint-design.md` §3.4, made complete and executable.

---

## 1. Objective

Minimise **expected aggregate recomputed tokens**. TTFT and queue delay are auxiliary
observations and never enter the decision.

For a victim set $S$:

$$
L(S)=\sum_{c\,:\,S\cap c\neq\varnothing} q_c\cdot B\cdot\bigl(m_c-j_c(S)+1\bigr),
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
| $B$ | block token size | tokens/block |

**Why only the shallowest depth matters.** This is APC semantics, not an
approximation. A prefix either resolves or it does not: once depth $j$ is gone, every
deeper block of that chain is unreachable, so evicting more of them adds no
recomputation. $m_c-j_c+1$ is exactly the number of blocks that must be recomputed if
the chain returns.

**Units.** $B$ is a positive constant (`block_size`), so it scales every candidate
cost identically and cancels in all comparisons. The selector therefore works in
"chain-block" units and the reported loss is in those units, convertible to tokens by
multiplying by $B$.

### 1.1 Reuse weight $q_c$

$$q_c=\sigma\!\left(\frac{\text{deadline}_c-t}{\tau}\right),\qquad \sigma(x)=\frac{1}{1+e^{-x}}$$

- `deadline_c` is Continuum's dynamic retention deadline, already computed at decision
  time; $t$ is the decision timestamp; $\tau$ is a time scale (default 30 s).
- $q_c>0.5$ means the TTL has not passed; $q_c<0.5$ means it has passed but the entry
  has not been released yet — the normal state for an entry the pressure loop is about
  to sacrifice.
- **$q_c$ is a ranking proxy, not a calibrated probability.** Its magnitude is only
  meaningful through comparison within one decision.
- It is monotone in the deadline, so when $N$ and the bracket are equal across
  candidates the ordering degenerates exactly to deadline-first.

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

$$ \Delta(b\mid S)=\sum_{c\ni b} q_c\cdot B\cdot\max\bigl(0,\;j_c(S)-d_c(b)\bigr) $$

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
    if exact search enabled and C(|legal|, need) <= budget:
        exact = exhaustive(geometry, need)
        if exact.loss < greedy.loss: best = exact      # greedy wins ties

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
0.70 loss units. The exact search therefore earns its place rather than being
defensive padding.

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
| exact search | $O\binom{n}{k}\cdot(n+k)$ | only run when $\binom{n}{k}\le$ `exact_search_budget` (default 20,000) |
| fallback | $O(n\log n)$ | native rank sort |

The exact search is skipped, and `search_truncated` is set, whenever the combination
count exceeds the budget. On the recorded corpus 57 of 87 scorable decisions exceeded
it, which is why the greedy result is the practical answer there and the exact search
is a correctness oracle plus a small-decision improvement.

### 3.5 Ties

Total order `(marginal_cost, native_rank, block_id)`. Rank is included because it is
the frozen engine order, and block id last so the result never depends on dict
iteration order. Verified by `test_ties_break_on_rank_then_block_id` and
`test_selection_is_independent_of_dict_insertion_order`.

### 3.6 Fallback

If **any** of these holds, A2 returns native LRU order over the legal set and records
the reason:

| reason | trigger |
|---|---|
| `content_unverified` | a hash-carrying legal block has no proved chain membership |
| `reuse_weight_missing` | a chain carrying priced content has no decision-time weight |

Fallback reports `expected_recompute: None` — a loss is never invented. Hashless blocks
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

---

## 5. Failure modes

| failure | effect | mitigation |
|---|---|---|
| `q_c` mis-ranks the chains | A2 drains the wrong chain; loss rises | $q$ monotone in TTL only; divergence measured per decision, not assumed |
| slot reuse | stale content attached to a slot | content proof required; unproved ⇒ fallback |
| depth from rank | systematically wrong costs | depth never read from rank; enforced by contract |
| shared ownership collapsed | loss understated | all memberships summed |
| greedy suboptimality | up to 0.70 loss units in the random search | exact search where affordable; selector recorded |
| exact search over budget | greedy result only | `search_truncated` flag set, never claimed optimal |
| missing weight treated as free | spurious benefit | raises `MissingReuseWeight`; decision unscorable |

---

## 6. Algorithm-layer verification

`tests/test_costaware_a2_selector.py` (30 tests) and
`tests/test_costaware_a2_contract.py` (24 tests) cover the seven areas required:

| required coverage | tests |
|---|---|
| 1. cost order agrees with LRU | `test_agrees_with_lru_when_depth_ordered_and_q_uniform`, `..._across_chains_when_q_matches_rank` |
| 2. cost diverges from LRU, with modelled loss | `test_diverges_from_lru_when_a_cheap_chain_is_not_the_coldest` |
| 3. multi-chain shared marginal | `test_shared_block_marginal_is_charged_once_per_chain`, `test_evicting_a_shared_block_moves_the_gap_in_every_chain`, `test_shared_block_is_not_double_counted_after_its_chain_is_drained` |
| 4. multi-block updates | `test_multi_block_greedy_drains_one_chain_before_touching_the_next`, `test_marginal_costs_are_recomputed_after_every_pick` |
| 5. unknown weight / wrong identity / slot reuse / stale snapshot | `test_unknown_reuse_weight_falls_back_to_native_lru`, `test_unverified_content_falls_back_and_records_the_reason`, `test_marginal_cost_raises_on_unknown_weight_rather_than_returning_zero`, plus the identity-proof regressions in `tests/test_costaware_a2_evidence.py` |
| 6. ties, determinism, safe fallback | `test_ties_break_on_rank_then_block_id`, `test_selection_is_deterministic_across_repeated_calls`, `test_selection_is_independent_of_dict_insertion_order` |
| 7. same legal set / same count / zero violations | `test_victims_are_always_a_subset_of_the_legal_set`, `test_selection_never_exceeds_the_requested_count` |

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
- no A3 joint optimisation, no B1 active release;
- no global combinatorial optimisation: greedy plus a bounded exact search, with the
  bounds and the measured greedy gap stated rather than glossed.

## 8. Reproduce

```bash
python -m pytest tests/test_costaware_a2_selector.py tests/test_costaware_a2_contract.py -q
```
