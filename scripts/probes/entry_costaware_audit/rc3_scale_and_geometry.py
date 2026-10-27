"""RC-B: the geometry counterfactual on the complete legal set.

The earlier version reported "66/66 deepest-first, 0/66 counterfactual difference".
Three things were wrong with it:

1. it rebuilt the geometry from ``block_memberships`` only, so every legal block with
   no membership -- the hashless blocks, which are over half of the free queue -- was
   dropped, and ``need``/rank were read off the reduced set;
2. it called ``select_victims``, which is budget-bound, and reported the result as if
   it were exhaustive;
3. it treated "rank is deepest-first within every chain" as a sufficient condition for
   cost-aware selection to coincide with LRU. That is false, and
   ``counterexample()`` reproduces the repository's own
   ``test_diverges_from_lru_when_a_cheap_chain_is_not_the_coldest`` to show it.

This version keeps every legal id (``rebuild_geometry``), uses the recorded rank order,
and separates the three outcomes instead of collapsing them:

  greedy            -- ``greedy_select``, the rule the engine actually falls back to
  exact_enumerated  -- full enumeration, only when C(|legal|, need) is under the cap
  certified_zero    -- no enumeration needed: the rank set's loss is 0, and loss is
                       non-negative, so the rank set is optimal
  over_cap          -- neither enumerable nor certifiable: exact optimality unknown

A ``greedy != exact`` gap can only be reported for ``exact_enumerated`` decisions. The
script never calls a non-enumerated result exact.
"""

from __future__ import annotations

import math
import statistics
import sys
from collections import Counter

sys.path.insert(0, "src")

from rebuild_geometry import Rebuild, iter_decisions, rebuild

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from kvopt.costaware.a2_selector import (
    chain_loss,
    exhaustive_select,
    greedy_select,
    native_lru_order,
)

ANALYSIS_CAP = 300_000


def loss_of(geometry: DecisionGeometry, blocks: tuple[int, ...]) -> float:
    evicted: dict = {}
    for block_id in blocks:
        for member in geometry.blocks[block_id].memberships:
            evicted.setdefault(member.chain, set()).add(member.depth)
    return chain_loss(evicted, geometry)


def exact_set(rb: Rebuild) -> tuple[tuple[int, ...] | None, int]:
    legal = len(rb.geometry.blocks)
    k = min(rb.need, legal)
    if k <= 0:
        return (), 1
    combinations = math.comb(legal, k)
    if combinations > ANALYSIS_CAP:
        return None, combinations
    found = exhaustive_select(rb.geometry, rb.need, budget=combinations)
    return (None if found is None else tuple(found[0])), combinations


def chain_is_deepest_first(geometry: DecisionGeometry) -> bool:
    """Within every chain, is the recorded rank order the depth-descending order?"""
    per_chain: dict[str, list[tuple[int, int]]] = {}
    for block in geometry.blocks.values():
        for member in block.memberships:
            per_chain.setdefault(member.chain, []).append((member.depth, block.native_rank))
    for pairs in per_chain.values():
        pairs.sort()
        ranks = [rank for _, rank in pairs]
        if any(ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1)):
            return False
    return True


def _chain(chain: str, length: int, base: int, first_rank: int) -> dict[int, LegalBlock]:
    blocks = {}
    for depth in range(1, length + 1):
        block_id = base + depth
        blocks[block_id] = LegalBlock(
            block_id=block_id,
            native_rank=first_rank + (length - depth),
            memberships=(Membership(chain=chain, depth=depth, content_hash=f"{chain}{depth}"),),
        )
    return blocks


def chain_is_deepest_first_for(geometry: DecisionGeometry, chain: str) -> bool:
    pairs = sorted(
        (member.depth, block.native_rank)
        for block in geometry.blocks.values()
        for member in block.memberships
        if member.chain == chain
    )
    ranks = [rank for _, rank in pairs]
    return all(ranks[i] >= ranks[i + 1] for i in range(len(ranks) - 1))


def counterexample() -> None:
    """Deepest-first in both chains, yet the victim sets differ."""
    blocks = {
        **_chain("a", 3, base=10, first_rank=0),
        **_chain("b", 3, base=20, first_rank=10),
    }
    geometry = DecisionGeometry(
        blocks=blocks, chain_length={"a": 3, "b": 3}, q_by_chain={"a": 0.9, "b": 0.1}
    )
    native = native_lru_order(geometry)[:1]
    greedy, _ = greedy_select(geometry, 1)
    exact, _ = exhaustive_select(geometry, 1, budget=100)
    print("== counterexample: deepest-first does not imply no divergence ==")
    print("  chain a: ranks 0..2, q=0.9   chain b: ranks 10..12, q=0.1   need=1")
    print(f"  deepest-first within a      {chain_is_deepest_first_for(geometry, 'a')}")
    print(f"  deepest-first within b      {chain_is_deepest_first_for(geometry, 'b')}")
    print(f"  rank-LRU victim             {native}")
    print(f"  greedy victim               {greedy}")
    print(f"  exact victim                {None if exact is None else exact[0]}")
    print("  -> 'deepest-first is sufficient' is false; the cheaper chain is not the")
    print("     coldest one, and selection follows the cost, not the rank")
    print()


def main() -> int:
    total = 0
    state_ok = rank_ok = 0
    weights: list[float] = []
    greedy_vs_rank = 0
    exact_checked = exact_vs_rank = exact_vs_greedy = 0
    certified = over_cap = 0
    engine_greedy = engine_other = engine_truncated = 0
    deepest_first = deepest_then_diverge = 0
    legal_sizes: list[int] = []
    states: Counter[str] = Counter()
    rows: list[tuple] = []

    for run, payload in iter_decisions():
        rb = rebuild(run, payload)
        total += 1
        state_ok += int(rb.state_ok)
        rank_ok += int(rb.rank_order_ok)
        weights.extend(float(w) for w in (payload.get("decision_reuse_weights") or {}).values())
        engine_truncated += int(rb.recorded_truncated)
        if not rb.geometry.scorable or rb.need <= 0:
            continue

        legal_sizes.append(rb.legal_count)
        native = tuple(native_lru_order(rb.geometry)[: rb.need])
        native_loss = loss_of(rb.geometry, native)
        greedy_blocks, _ = greedy_select(rb.geometry, rb.need)
        exact_blocks, _combinations = exact_set(rb)

        if exact_blocks is not None:
            state = "exact_enumerated"
            exact_checked += 1
            if set(exact_blocks) != set(native):
                exact_vs_rank += 1
            if set(exact_blocks) != set(greedy_blocks):
                exact_vs_greedy += 1
        elif abs(native_loss) <= 1e-12:
            state = "certified_zero_loss"
            certified += 1
        else:
            state = "over_cap"
            over_cap += 1
        states[state] += 1

        if set(greedy_blocks) != set(native):
            greedy_vs_rank += 1

        df = chain_is_deepest_first(rb.geometry)
        deepest_first += int(df)
        if df and set(greedy_blocks) != set(native):
            deepest_then_diverge += 1

        if set(rb.selected) == set(greedy_blocks):
            engine_greedy += 1
        else:
            engine_other += 1
            rows.append((run, rb.need, rb.legal_count, sorted(rb.selected)[:6], sorted(native)[:6]))

    print(f"decisions with an A2 block audit: {total}")
    print()
    print("== rebuild fidelity ==")
    print(f"  identity-state counts reproduced exactly   {state_ok} / {total}")
    print(f"  native_lru_victims == legal prefix         {rank_ok} / {total}")
    if legal_sizes:
        legal_sizes.sort()
        print(
            f"  legal candidates compared                  {len(legal_sizes)} decisions, "
            f"median {legal_sizes[len(legal_sizes) // 2]}, max {legal_sizes[-1]}"
        )
    print()
    print("== exact optimality of the rank set ==")
    for key in sorted(states):
        print(f"  {key:24s} {states[key]:4d}")
    print("  certified_zero: loss is non-negative, the rank set attains 0, so it is")
    print("  optimal; no enumeration is needed and none is claimed.")
    print()
    print("== selection comparison on the complete legal set ==")
    print(f"  greedy set differs from rank-LRU           {greedy_vs_rank}")
    print(f"  exact-enumerated decisions                 {exact_checked}")
    print(f"  exact set differs from rank-LRU            {exact_vs_rank}")
    print(f"  exact set differs from greedy              {exact_vs_greedy}")
    print(f"  exact optimality undetermined (over cap)   {over_cap}")
    print(f"  engine reported search_truncated           {engine_truncated}")
    print()
    print("== what the engine actually returned ==")
    print(f"  recorded selection == greedy               {engine_greedy}")
    print(f"  recorded selection != greedy               {engine_other}")
    for row in rows[:5]:
        print("   ", row)
    print()
    print("== within-chain rank geometry (descriptive, not a criterion) ==")
    print(f"  deepest-first in every chain               {deepest_first}")
    print(f"  ... and greedy still differs from rank     {deepest_then_diverge}")
    print()
    if weights:
        ordered = sorted(weights)
        print("== decision_reuse_weights distribution ==")
        print(f"  n        {len(ordered)}")
        print(f"  min      {ordered[0]:.3e}")
        print(f"  median   {statistics.median(ordered):.3e}")
        print(f"  max      {ordered[-1]:.3e}")
        print(f"  > 0.01   {sum(1 for w in ordered if w > 0.01)} / {len(ordered)}")
        print(f"  > 0.1    {sum(1 for w in ordered if w > 0.1)} / {len(ordered)}")
        print()
    counterexample()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
