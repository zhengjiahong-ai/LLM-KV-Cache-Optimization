"""Algorithm-layer tests for A2 cost-aware block victim selection.

Coverage required by M1, one section per item:

1. cost order agrees with LRU      -> the selection coincides
2. cost order diverges from LRU    -> the selection and modelled loss differ
3. multi-chain shared block        -> marginal cost is charged once per chain
4. multi-block eviction            -> candidates are updated after each pick
5. unknown weight / wrong identity -> native LRU fallback, reason recorded
6. ties, determinism, safe fallback
7. same legal set, same eviction count, zero violations

Plus: a hand-checkable positive case, a negative control, and a multi-block case.
These validate **algorithm correctness**, not native benefit.
"""

from __future__ import annotations

import random

import pytest

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
    MissingReuseWeight,
)
from kvopt.costaware.a2_selector import (
    FALLBACK_CONTENT_UNVERIFIED,
    FALLBACK_REUSE_WEIGHT_MISSING,
    SELECTOR_EXACT,
    SELECTOR_GREEDY,
    SELECTOR_NATIVE_FALLBACK,
    A2BlockSelector,
    A2Config,
    chain_gap,
    chain_loss,
    exact_select,
    greedy_select,
    marginal_cost,
    native_lru_order,
    select_victims,
)

# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _member(chain: str, depth: int) -> Membership:
    return Membership(chain=chain, depth=depth, content_hash=f"{chain}#{depth}")


def _chain_blocks(
    chain: str, length: int, *, rank_of: dict[int, int], base: int = 0
) -> dict[int, LegalBlock]:
    return {
        base + depth: LegalBlock(
            block_id=base + depth,
            native_rank=rank_of[depth],
            memberships=(_member(chain, depth),),
        )
        for depth in range(1, length + 1)
    }


def _geometry(
    blocks: dict[int, LegalBlock],
    *,
    length: dict[str, int],
    q: dict[str, float],
    gaps: dict[int, str] | None = None,
    unknown_weight_chains: tuple[str, ...] = (),
) -> DecisionGeometry:
    return DecisionGeometry(
        blocks=blocks,
        chain_length=length,
        q_by_chain=q,
        gaps=gaps or {},
        unknown_weight_chains=unknown_weight_chains,
    )


def _loss(blocks, geometry: DecisionGeometry) -> float:
    evicted: dict[str, set[int]] = {}
    for block_id in blocks:
        for membership in geometry.blocks[block_id].memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return chain_loss(evicted, geometry)


# --------------------------------------------------------------------------
# 1. cost order agrees with LRU
# --------------------------------------------------------------------------


def test_agrees_with_lru_when_depth_ordered_and_q_uniform() -> None:
    """Deeper colder and one chain: native is already optimal, so sets coincide."""
    blocks = _chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0})
    geometry = _geometry(blocks, length={"a": 4}, q={"a": 0.5})

    native = native_lru_order(geometry)
    selection = select_victims(geometry, 2)

    assert native == (4, 3, 2, 1)  # full order; the selector takes the first `need`
    assert selection.blocks == (4, 3)
    assert selection.cost_known
    assert selection.expected_recompute == pytest.approx(0.5 * 2)


def test_agrees_with_lru_across_chains_when_q_matches_rank() -> None:
    """The cheapest chain also holds the coldest block, so both rules agree."""
    blocks = {
        **_chain_blocks("a", 3, rank_of={1: 5, 2: 4, 3: 3}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 2, 2: 1, 3: 0}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3}, q={"a": 0.9, "b": 0.1})

    native = native_lru_order(geometry)
    selection = select_victims(geometry, 2)

    # chain b is both cheapest (q = 0.1) and coldest (rank 0..2)
    assert native[:2] == (23, 22)
    assert selection.blocks == (23, 22)


# --------------------------------------------------------------------------
# 2. cost order diverges from LRU
# --------------------------------------------------------------------------


def test_diverges_from_lru_when_a_cheap_chain_is_not_the_coldest() -> None:
    """Hand-checkable positive case.

    Chain a holds the coldest blocks (rank 0..2) but has q = 0.9. Chain b is warmer
    (rank 10..12) and has q = 0.1. Need one block.

    Native takes a@3 (rank 0)          -> loss 0.9 * 1 = 0.9
    Cost-aware takes b@3 (cost 0.1)    -> loss 0.1 * 1 = 0.1
    """
    blocks = {
        **_chain_blocks("a", 3, rank_of={1: 2, 2: 1, 3: 0}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 12, 2: 11, 3: 10}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3}, q={"a": 0.9, "b": 0.1})

    native = native_lru_order(geometry)
    selection = select_victims(geometry, 1)

    assert native[0] == 13  # a@3, the coldest
    assert selection.blocks == (23,)  # b@3, the cheapest to lose
    assert selection.expected_recompute == pytest.approx(0.1)
    assert selection.expected_recompute < _loss(native[:1], geometry)


def test_negative_control_equal_q_leaves_no_advantage() -> None:
    """With equal q the two rules cost the same, so no benefit may be claimed."""
    blocks = {
        **_chain_blocks("a", 3, rank_of={1: 2, 2: 1, 3: 0}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 12, 2: 11, 3: 10}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3}, q={"a": 0.5, "b": 0.5})

    native = native_lru_order(geometry)
    selection = select_victims(geometry, 1)

    assert selection.expected_recompute == pytest.approx(_loss(native[:1], geometry))


# --------------------------------------------------------------------------
# 3. multi-chain shared blocks
# --------------------------------------------------------------------------


def test_shared_block_marginal_is_charged_once_per_chain() -> None:
    """PR #50 §3.4.5: a shared block is summed over the chains it belongs to."""
    shared = LegalBlock(
        block_id=1,
        native_rank=0,
        memberships=(
            Membership("a", 3, "shared#3"),
            Membership("b", 5, "shared#5b"),
        ),
    )
    geometry = _geometry(shared_block_geometry(shared), length={"a": 4, "b": 6},
                         q={"a": 0.9, "b": 0.1})
    # No evictions yet: j_a = 5, j_b = 7
    #   a: 0.9 * (5 - 3) = 1.8 ; b: 0.1 * (7 - 5) = 0.2  => 2.0
    assert marginal_cost(shared, {}, geometry) == pytest.approx(2.0)


def shared_block_geometry(shared: LegalBlock) -> dict[int, LegalBlock]:
    return {shared.block_id: shared}


def test_evicting_a_shared_block_moves_the_gap_in_every_chain() -> None:
    shared = LegalBlock(
        block_id=1,
        native_rank=0,
        memberships=(
            Membership("a", 3, "shared#3a"),
            Membership("b", 2, "shared#2b"),
        ),
    )
    geometry = _geometry({1: shared}, length={"a": 4, "b": 4}, q={"a": 1.0, "b": 1.0})

    evicted: dict[str, set[int]] = {}
    for membership in shared.memberships:
        evicted.setdefault(membership.chain, set()).add(membership.depth)

    assert chain_gap(evicted, "a", 4) == 3
    assert chain_gap(evicted, "b", 4) == 2
    # a: 4-3+1 = 2 ; b: 4-2+1 = 3
    assert chain_loss(evicted, geometry) == pytest.approx(5.0)


def test_shared_block_is_not_double_counted_after_its_chain_is_drained() -> None:
    """A chain already drained at a shallower depth contributes nothing more."""
    shared = LegalBlock(
        block_id=1, native_rank=0, memberships=(_member("a", 3), _member("b", 3))
    )
    deeper_a = LegalBlock(block_id=2, native_rank=1, memberships=(_member("a", 1),))
    geometry = _geometry(
        {1: shared, 2: deeper_a}, length={"a": 4, "b": 4}, q={"a": 1.0, "b": 1.0}
    )
    evicted = {"a": {1}}
    # a is already open at depth 1, so the shared block only costs its b share.
    # b: j = 5 -> 5 - 3 = 2
    assert marginal_cost(shared, evicted, geometry) == pytest.approx(2.0)


# --------------------------------------------------------------------------
# 4. multi-block eviction and candidate updates
# --------------------------------------------------------------------------


def test_multi_block_greedy_drains_one_chain_before_touching_the_next() -> None:
    """Hand-checkable multi-block case.

    chain a: length 3, q = 0.1. chain b: length 3, q = 0.9.
    Need 2 blocks. Draining a costs 0.1 for the first pick and 0.1 for the second
    (each shallower step re-opens the suffix by one), total 0.2.
    Touching both chains would cost 0.1 + 0.9 = 1.0.
    """
    blocks = {
        **_chain_blocks("a", 3, rank_of={1: 5, 2: 6, 3: 7}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 0, 2: 1, 3: 2}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3}, q={"a": 0.1, "b": 0.9})

    selection = select_victims(geometry, 2)

    assert set(selection.blocks) == {13, 12}  # both from chain a
    assert selection.expected_recompute == pytest.approx(0.2)


def test_marginal_costs_are_recomputed_after_every_pick() -> None:
    """The second pick's cost must reflect the first pick's gap update."""
    blocks = _chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0})
    geometry = _geometry(blocks, length={"a": 4}, q={"a": 1.0})

    chosen, step_costs = greedy_select(geometry, 3)
    assert chosen == (4, 3, 2)
    # 1 for the first (opens the suffix), then 1 for each shallower step
    assert step_costs == pytest.approx((1.0, 1.0, 1.0))

    # A stale-cost implementation would have given 1, 2, 3.
    evicted: dict[str, set[int]] = {}
    first = marginal_cost(geometry.blocks[4], evicted, geometry)
    for membership in geometry.blocks[4].memberships:
        evicted.setdefault(membership.chain, set()).add(membership.depth)
    second = marginal_cost(geometry.blocks[3], evicted, geometry)
    assert first == 1.0 and second == 1.0


def test_need_larger_than_legal_set_is_capped() -> None:
    blocks = _chain_blocks("a", 2, rank_of={1: 1, 2: 0})
    geometry = _geometry(blocks, length={"a": 2}, q={"a": 0.5})
    selection = select_victims(geometry, 99)
    assert len(selection.blocks) == 2
    assert set(selection.blocks) == set(blocks)


# --------------------------------------------------------------------------
# 5. unknown weight, wrong identity, slot reuse, stale snapshot
# --------------------------------------------------------------------------


def test_unknown_reuse_weight_falls_back_to_native_lru() -> None:
    blocks = _chain_blocks("a", 3, rank_of={1: 2, 2: 1, 3: 0})
    geometry = _geometry(
        blocks, length={"a": 3}, q={}, unknown_weight_chains=("a",)
    )

    selection = select_victims(geometry, 2)

    assert selection.selector == SELECTOR_NATIVE_FALLBACK
    assert selection.is_fallback
    assert selection.blocks == native_lru_order(geometry)[:2]
    assert FALLBACK_REUSE_WEIGHT_MISSING in selection.fallbacks
    # No loss may be reported for a fallback.
    assert selection.expected_recompute is None
    assert not selection.cost_known


def test_unverified_content_falls_back_and_records_the_reason() -> None:
    blocks = _chain_blocks("a", 3, rank_of={1: 2, 2: 1, 3: 0})
    geometry = _geometry(
        blocks, length={"a": 3}, q={"a": 0.5}, gaps={99: "content_unverified"}
    )

    selection = select_victims(geometry, 2)

    assert selection.selector == SELECTOR_NATIVE_FALLBACK
    assert FALLBACK_CONTENT_UNVERIFIED in selection.fallbacks


def test_marginal_cost_raises_on_unknown_weight_rather_than_returning_zero() -> None:
    blocks = _chain_blocks("a", 2, rank_of={1: 1, 2: 0})
    geometry = _geometry(blocks, length={"a": 2}, q={})
    with pytest.raises(MissingReuseWeight):
        marginal_cost(geometry.blocks[2], {}, geometry)


def test_chain_loss_raises_on_unknown_weight() -> None:
    blocks = _chain_blocks("a", 2, rank_of={1: 1, 2: 0})
    geometry = _geometry(blocks, length={"a": 2}, q={})
    with pytest.raises(MissingReuseWeight):
        chain_loss({"a": {2}}, geometry)


def test_fallback_still_returns_the_requested_count() -> None:
    blocks = _chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0})
    geometry = _geometry(
        blocks, length={"a": 4}, q={}, unknown_weight_chains=("a",)
    )
    selection = select_victims(geometry, 3)
    assert len(selection.blocks) == 3


# --------------------------------------------------------------------------
# 6. ties, determinism, safe fallback
# --------------------------------------------------------------------------


def test_ties_break_on_rank_then_block_id() -> None:
    """Equal marginal costs must resolve deterministically."""
    blocks = {
        1: LegalBlock(1, 5, (_member("a", 3),)),
        2: LegalBlock(2, 2, (_member("b", 3),)),
        3: LegalBlock(3, 2, (_member("c", 3),)),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3, "c": 3},
                         q={"a": 0.5, "b": 0.5, "c": 0.5})
    selection = select_victims(geometry, 1)
    # rank 2 ties; block id 2 wins over 3
    assert selection.blocks == (2,)


def test_selection_is_deterministic_across_repeated_calls() -> None:
    blocks = {
        **_chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0}, base=10),
        **_chain_blocks("b", 4, rank_of={1: 7, 2: 6, 3: 5, 4: 4}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 4, "b": 4}, q={"a": 0.3, "b": 0.7})
    selector = A2BlockSelector()
    first = selector.select(geometry, 2)
    for _ in range(5):
        assert selector.select(geometry, 2) == first


def test_selection_is_independent_of_dict_insertion_order() -> None:
    base = {
        **_chain_blocks("a", 3, rank_of={1: 2, 2: 1, 3: 0}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 5, 2: 4, 3: 3}, base=20),
    }
    geometry_a = _geometry(base, length={"a": 3, "b": 3}, q={"a": 0.2, "b": 0.8})

    shuffled_items = list(base.items())
    random.Random(7).shuffle(shuffled_items)
    geometry_b = _geometry(
        dict(shuffled_items), length={"a": 3, "b": 3}, q={"a": 0.2, "b": 0.8}
    )

    assert select_victims(geometry_a, 2).blocks == select_victims(geometry_b, 2).blocks


def test_empty_legal_set_returns_empty_and_is_not_a_fallback() -> None:
    geometry = _geometry({}, length={}, q={})
    selection = select_victims(geometry, 3)
    assert selection.blocks == ()
    assert not selection.is_fallback
    assert selection.expected_recompute == 0.0


def test_zero_need_returns_empty() -> None:
    blocks = _chain_blocks("a", 2, rank_of={1: 1, 2: 0})
    geometry = _geometry(blocks, length={"a": 2}, q={"a": 0.5})
    assert select_victims(geometry, 0).blocks == ()


# --------------------------------------------------------------------------
# 7. same legal set, same count, zero violations
# --------------------------------------------------------------------------


@pytest.mark.parametrize("need", [1, 2, 3])
def test_victims_are_always_a_subset_of_the_legal_set(need: int) -> None:
    blocks = {
        **_chain_blocks("a", 3, rank_of={1: 4, 2: 5, 3: 6}, base=10),
        **_chain_blocks("b", 3, rank_of={1: 0, 2: 1, 3: 2}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 3, "b": 3}, q={"a": 0.1, "b": 0.9})
    selection = select_victims(geometry, need)

    assert set(selection.blocks) <= set(geometry.blocks)
    assert len(selection.blocks) == need
    assert len(set(selection.blocks)) == len(selection.blocks)


def test_selection_never_exceeds_the_requested_count() -> None:
    blocks = {
        **_chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0}, base=10),
    }
    geometry = _geometry(blocks, length={"a": 4}, q={"a": 0.5})
    for need in range(1, 6):
        selection = select_victims(geometry, need)
        assert len(selection.blocks) == min(need, 4)


# --------------------------------------------------------------------------
# greedy versus exact: the second selector earns its place
# --------------------------------------------------------------------------


def _counterexample() -> DecisionGeometry:
    """Minimal case where incremental greedy is suboptimal.

    chain a: length 4, q = 0.4   (a@3 is shared)
    chain b: length 3, q = 0.2   (b@3 is shared)
    shared block s at a@3 and b@3.  need = 2.

    Greedy takes a@4 (0.4) then b@2 (0.4) -> loss 0.4 + 0.4 = 0.8
    Optimal takes b@1 then b@2           -> loss 0.2 * 3 = 0.6
    """
    blocks: dict[int, LegalBlock] = {
        1: LegalBlock(1, 101, (_member("a", 1),)),
        2: LegalBlock(2, 102, (_member("a", 2),)),
        3: LegalBlock(3, 104, (_member("a", 4),)),
        4: LegalBlock(4, 201, (_member("b", 1),)),
        5: LegalBlock(5, 202, (_member("b", 2),)),
        6: LegalBlock(
            6,
            300,
            (
                Membership("a", 3, "shared#3"),
                Membership("b", 3, "shared#3"),
            ),
        ),
    }
    return _geometry(blocks, length={"a": 4, "b": 3}, q={"a": 0.4, "b": 0.2})


def test_greedy_is_suboptimal_on_the_counterexample() -> None:
    geometry = _counterexample()
    greedy, _ = greedy_select(geometry, 2)
    exact = exact_select(geometry, 2, budget=10**9)

    assert exact is not None
    assert _loss(greedy, geometry) == pytest.approx(0.8)
    assert exact[1] == pytest.approx(0.6)
    assert exact[1] < _loss(greedy, geometry) - 1e-12


def test_exact_search_wins_on_the_counterexample() -> None:
    geometry = _counterexample()
    selection = select_victims(geometry, 2)

    assert selection.selector == SELECTOR_EXACT
    assert selection.expected_recompute == pytest.approx(0.6)


def test_disabling_exact_search_falls_back_to_greedy() -> None:
    geometry = _counterexample()
    selector = A2BlockSelector(A2Config(enable_exact_search=False))
    selection = selector.select(geometry, 2)

    assert selection.selector == SELECTOR_GREEDY
    assert selection.expected_recompute == pytest.approx(0.8)


def test_exact_search_is_skipped_when_over_budget() -> None:
    blocks = {
        **_chain_blocks("a", 4, rank_of={1: 3, 2: 2, 3: 1, 4: 0}, base=10),
        **_chain_blocks("b", 4, rank_of={1: 7, 2: 6, 3: 5, 4: 4}, base=20),
    }
    geometry = _geometry(blocks, length={"a": 4, "b": 4}, q={"a": 0.3, "b": 0.7})
    selector = A2BlockSelector(A2Config(exact_search_budget=1))
    selection = selector.select(geometry, 2)

    assert selection.selector == SELECTOR_GREEDY
    assert selection.search_truncated


def test_exact_and_greedy_agree_when_there_is_no_coupling() -> None:
    """On independent single chains greedy is already optimal."""
    blocks = _chain_blocks("a", 5, rank_of={d: 5 - d for d in range(1, 6)})
    geometry = _geometry(blocks, length={"a": 5}, q={"a": 0.5})

    greedy, _ = greedy_select(geometry, 3)
    exact = exact_select(geometry, 3, budget=10**9)
    assert exact is not None
    assert _loss(greedy, geometry) == pytest.approx(exact[1])


def test_cost_model_is_pure() -> None:
    """Selection must not mutate the geometry it was given."""
    geometry = _counterexample()
    before_blocks = dict(geometry.blocks)
    before_q = dict(geometry.q_by_chain)
    select_victims(geometry, 2)
    assert dict(geometry.blocks) == before_blocks
    assert dict(geometry.q_by_chain) == before_q
