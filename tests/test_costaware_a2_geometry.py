"""Tests for A2 block geometry: content identity, true depth, multi-chain cost.

These tests exist because the earlier A2 study got three things wrong, and each
wrong assumption is now pinned by a test:

1. depth is **content position**, not native rank;
2. a physical block may belong to **several chains**, and its marginal cost is the
   sum over those chains;
3. a hashless block has **zero** cost, so it is not an observation gap even though
   it belongs to no chain.
"""

from __future__ import annotations

import math

import pytest

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
    chain_loss,
    cost_aware_selection,
    evaluate,
    marginal_delta,
    native_selection,
    q_order_agrees,
    reuse_proxy,
    selection_outcome,
)


def _member(chain: str, depth: int, content: str | None = None) -> Membership:
    return Membership(chain=chain, depth=depth, content_hash=content or f"{chain}#{depth}")


def _geometry(
    blocks: list[LegalBlock],
    *,
    length: dict[str, int],
    q: dict[str, float],
    gaps: dict[int, str] | None = None,
) -> DecisionGeometry:
    return DecisionGeometry(
        blocks={block.block_id: block for block in blocks},
        chain_length=length,
        q_by_chain=q,
        gaps=gaps or {},
    )


def _chain(
    chain: str,
    *,
    length: int,
    base: int,
    depths: range | list[int],
    rank_of: dict[int, int],
) -> list[LegalBlock]:
    return [
        LegalBlock(
            block_id=base + depth,
            native_rank=rank_of[depth],
            memberships=(_member(chain, depth),),
        )
        for depth in depths
    ]


# --- depth comes from content, not rank ------------------------------------


def test_depth_is_not_derived_from_rank() -> None:
    """Two blocks in one chain may have any rank order; depth stays positional."""
    block_deep = LegalBlock(
        block_id=1, native_rank=0, memberships=(_member("a", 4),)
    )
    block_shallow = LegalBlock(
        block_id=2, native_rank=5, memberships=(_member("a", 1),)
    )
    assert block_deep.memberships[0].depth == 4
    assert block_shallow.memberships[0].depth == 1
    # Rank says block 1 is colder; depth says it is deeper. Both are recorded
    # independently, which is exactly the distinction the earlier study lost.
    assert block_deep.native_rank < block_shallow.native_rank


def test_conflicting_content_hashes_for_one_block_are_rejected() -> None:
    block = LegalBlock(
        block_id=7,
        native_rank=0,
        memberships=(_member("a", 1, "h1"), _member("b", 2, "h2")),
    )
    with pytest.raises(ValueError, match="conflicting content hashes"):
        _ = block.content_hash


# --- multi-chain ownership -------------------------------------------------


def test_shared_block_cost_is_summed_over_its_chains() -> None:
    """PR #50 §3.4.5: counted once per chain containing the block."""
    shared = LegalBlock(
        block_id=1,
        native_rank=0,
        memberships=(_member("a", 3), _member("b", 5)),
    )
    length = {"a": 4, "b": 6}
    q = {"a": 0.9, "b": 0.1}

    # a: j = 5 -> 0.9 * (5 - 3) = 1.8 ; b: j = 7 -> 0.1 * (7 - 5) = 0.2
    assert marginal_delta(shared, {}, length, q) == pytest.approx(2.0)


def test_shared_ownership_is_not_collapsed_to_one_chain() -> None:
    shared = LegalBlock(
        block_id=1, native_rank=0, memberships=(_member("a", 3), _member("b", 5))
    )
    assert shared.is_shared
    assert shared.chains == ("a", "b")

    single = LegalBlock(block_id=2, native_rank=1, memberships=(_member("a", 3),))
    assert not single.is_shared


def test_evicting_a_shared_block_moves_the_gap_in_every_chain() -> None:
    shared = LegalBlock(
        block_id=1, native_rank=0, memberships=(_member("a", 3), _member("b", 2))
    )
    geometry = _geometry([shared], length={"a": 4, "b": 4}, q={"a": 1.0, "b": 1.0})
    outcome = selection_outcome("rule", [1], geometry)

    # j_a = 3 -> 2 blocks remain ; j_b = 2 -> 3 blocks remain
    assert outcome.expected_recompute == pytest.approx(2.0 + 3.0)
    assert outcome.chains_touched == ("a", "b")


def test_shared_block_can_be_more_expensive_than_a_private_one() -> None:
    geometry = _geometry(
        [
            LegalBlock(block_id=1, native_rank=0, memberships=(_member("a", 3), _member("b", 5))),
            LegalBlock(block_id=2, native_rank=1, memberships=(_member("a", 3),)),
        ],
        length={"a": 4, "b": 6},
        q={"a": 0.9, "b": 0.1},
    )
    deltas = {
        block_id: marginal_delta(block, {}, geometry.chain_length, geometry.q_by_chain)
        for block_id, block in geometry.blocks.items()
    }
    assert deltas[1] == pytest.approx(2.0)
    assert deltas[2] == pytest.approx(1.8)
    # The cheaper private block is taken first.
    assert cost_aware_selection(geometry, 1) == (2,)


# --- depth inversion is where a depth rule can win -------------------------


def _inverted_chain(q: float = 1.0) -> DecisionGeometry:
    """Depth 1..4 with shallower blocks colder, so native takes the shallowest."""
    blocks = _chain(
        "a", length=4, base=10, depths=[1, 2, 3, 4], rank_of={1: 0, 2: 1, 3: 2, 4: 3}
    )
    return _geometry(blocks, length={"a": 4}, q={"a": q})


def test_inverted_depth_gives_a_real_victim_set_difference() -> None:
    geometry = _inverted_chain()
    native = native_selection(geometry, 2)
    aware = cost_aware_selection(geometry, 2)

    assert native == (11, 12)  # shallowest first
    assert aware == (14, 13)  # deepest first
    assert set(native) != set(aware)

    native_loss = selection_outcome("n", native, geometry).expected_recompute
    aware_loss = selection_outcome("a", aware, geometry).expected_recompute
    assert native_loss == pytest.approx(4.0)
    assert aware_loss == pytest.approx(2.0)
    assert aware_loss < native_loss


def test_depth_ordered_chain_leaves_nothing_to_decide() -> None:
    """Deeper colder: native already evicts deepest-first, so the sets coincide."""
    blocks = _chain(
        "a", length=4, base=10, depths=[1, 2, 3, 4], rank_of={1: 3, 2: 2, 3: 1, 4: 0}
    )
    geometry = _geometry(blocks, length={"a": 4}, q={"a": 1.0})
    assert native_selection(geometry, 2) == (14, 13)
    assert cost_aware_selection(geometry, 2) == (14, 13)


def test_no_freedom_when_the_whole_legal_set_is_required() -> None:
    geometry = _inverted_chain()
    # The order differs, but the set cannot: every legal block must go.
    assert set(native_selection(geometry, 4)) == set(cost_aware_selection(geometry, 4))
    row = evaluate(run_id="r", decision_event_index=0, geometry=geometry, need=4)
    assert row.order_differs
    assert not row.victim_set_differs


# --- hashless blocks -------------------------------------------------------


def test_hashless_block_costs_nothing_and_is_not_a_gap() -> None:
    block = LegalBlock(
        block_id=1, native_rank=0, memberships=(), has_block_hash=False
    )
    assert block.cost_known
    assert marginal_delta(block, {}, {}, {}) == 0.0

    geometry = _geometry([block], length={}, q={})
    assert geometry.scorable
    assert geometry.gaps == {}


def test_hashed_block_without_membership_is_a_gap() -> None:
    block = LegalBlock(block_id=1, native_rank=0, memberships=(), has_block_hash=True)
    assert not block.cost_known


# --- scoring ---------------------------------------------------------------


def test_chain_loss_uses_the_shallowest_evicted_depth() -> None:
    length = {"a": 4}
    q = {"a": 1.0}
    assert chain_loss({"a": {4}}, length, q) == pytest.approx(1.0)
    assert chain_loss({"a": {4, 3}}, length, q) == pytest.approx(2.0)
    # Adding a deeper block on top changes nothing.
    assert chain_loss({"a": {4, 3}}, length, q) == chain_loss({"a": {3}}, length, q)


def test_loss_ignores_chains_without_evictions() -> None:
    assert chain_loss({"a": set(), "b": {2}}, {"a": 4, "b": 4}, {"a": 1.0, "b": 1.0}) == (
        pytest.approx(3.0)
    )


def test_q_order_agreement_reports_none_when_not_comparable() -> None:
    single = _geometry(
        _chain("a", length=4, base=10, depths=[1, 2, 3], rank_of={1: 0, 2: 1, 3: 2}),
        length={"a": 4},
        q={"a": 1.0},
    )
    assert q_order_agrees(single) is None

    no_hashed = _geometry(
        [LegalBlock(block_id=1, native_rank=0, memberships=(), has_block_hash=False)],
        length={},
        q={},
    )
    assert q_order_agrees(no_hashed) is None


def test_q_order_agreement_detects_divergence() -> None:
    """Cheapest chain is 'b' while the coldest hashed block lives in 'a'."""
    blocks = [
        LegalBlock(block_id=1, native_rank=0, memberships=(_member("a", 3),)),
        LegalBlock(block_id=2, native_rank=1, memberships=(_member("b", 3),)),
    ]
    geometry = _geometry(blocks, length={"a": 4, "b": 4}, q={"a": 0.9, "b": 0.1})
    assert q_order_agrees(geometry) is False

    geometry.q_by_chain["a"] = 0.1
    assert q_order_agrees(geometry) is True


def test_reuse_proxy_matches_the_a1_formula() -> None:
    assert reuse_proxy(100.0, 100.0, 30.0) == pytest.approx(0.5)
    assert reuse_proxy(130.0, 100.0, 30.0) > 0.5
    assert reuse_proxy(70.0, 100.0, 30.0) < 0.5
    assert not math.isnan(reuse_proxy(0.0, 1000.0, 30.0))


# --- evaluate --------------------------------------------------------------


def test_evaluate_keeps_gaps_visible() -> None:
    geometry = _geometry(
        _chain("a", length=4, base=10, depths=[1, 2, 3], rank_of={1: 0, 2: 1, 3: 2}),
        length={"a": 4},
        q={"a": 1.0},
        gaps={99: "no_chain_membership"},
    )
    row = evaluate(run_id="r", decision_event_index=1, geometry=geometry, need=2)
    assert not row.scorable
    assert row.gaps == {99: "no_chain_membership"}


def test_evaluate_reports_order_and_set_separately() -> None:
    geometry = _inverted_chain()
    row = evaluate(run_id="r", decision_event_index=2, geometry=geometry, need=2)
    assert row.order_differs
    assert row.victim_set_differs

    whole = evaluate(run_id="r", decision_event_index=3, geometry=geometry, need=4)
    assert not whole.victim_set_differs


def test_selection_outcome_counts_shared_blocks_taken() -> None:
    geometry = _geometry(
        [
            LegalBlock(block_id=1, native_rank=0, memberships=(_member("a", 2), _member("b", 2))),
            LegalBlock(block_id=2, native_rank=1, memberships=(_member("a", 1),)),
        ],
        length={"a": 3, "b": 3},
        q={"a": 0.5, "b": 0.5},
    )
    outcome = selection_outcome("rule", [1], geometry)
    assert outcome.shared_blocks_taken == 1
