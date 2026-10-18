"""Tests for the A2 block-level mechanism study.

The recorded corpora show no divergence at all, so these tests carry the weight:
they establish that the comparison machinery is correct, that it can register a
difference when one exists, and that it reports a failure rather than smoothing it
over.
"""

from __future__ import annotations

import math

import pytest

from kvopt.costaware.a2_mechanism import (
    UNOWNED,
    BlockFact,
    cost_aware_selection,
    expected_loss,
    loss_of_selection,
    native_selection,
)
from kvopt.costaware.a2_scenarios import (
    all_scenarios,
    evaluate,
    scenario_equal_q_degenerate,
    scenario_q_reorders_chains,
    scenario_q_wrong,
    scenario_single_chain,
)


def _block(
    block_id: int, chain: str, depth: int, chain_length: int, rank: int
) -> BlockFact:
    return BlockFact(
        block_id=block_id,
        chain=chain,
        depth=depth,
        chain_length=chain_length,
        native_rank=rank,
    )


# --- geometry --------------------------------------------------------------


def test_native_selection_is_rank_order() -> None:
    facts = {
        1: _block(1, "a", 4, 4, 0),
        2: _block(2, "a", 3, 4, 1),
        3: _block(3, "b", 4, 4, 2),
    }
    assert native_selection([1, 2, 3], facts, 2) == (1, 2)


def test_within_a_chain_native_order_equals_depth_descending() -> None:
    """The observed invariant: deeper blocks are colder.

    This is what makes a depth decision impossible inside one chain, so it is worth
    asserting directly rather than inferring it.
    """
    facts = {
        depth: _block(depth, "a", depth, 5, 5 - depth) for depth in range(1, 6)
    }
    assert native_selection(sorted(facts), facts, 5) == (5, 4, 3, 2, 1)


def test_unowned_blocks_cost_nothing() -> None:
    facts = {1: _block(1, UNOWNED, 0, 0, 0)}
    assert loss_of_selection([1], facts, {"a": 0.9}) == 0.0


# --- marginal cost ---------------------------------------------------------


def test_greedy_prefers_the_cheaper_chain_when_q_differs() -> None:
    scenario = scenario_q_reorders_chains()
    chosen, loss = cost_aware_selection(
        scenario.legal, scenario.facts, scenario.need, scenario.q_by_chain
    )
    assert all(scenario.facts[b].chain == "B" for b in chosen)
    assert loss == pytest.approx(0.2)


def test_greedy_respects_depth_order_inside_a_chain() -> None:
    """Taking a shallow block before a deeper one must never be cheaper."""
    facts = {
        depth: _block(depth, "a", depth, 4, 4 - depth) for depth in range(1, 5)
    }
    chosen, _ = cost_aware_selection(sorted(facts), facts, 2, {"a": 0.5})
    assert chosen == (4, 3)


def test_equal_q_makes_concentration_and_dispersion_equivalent() -> None:
    """The token metric is linear, so at equal q both shapes cost the same."""
    facts = {
        **_block_set("a", base=10, length=4, first_rank=0),
        **_block_set("b", base=20, length=4, first_rank=4),
    }
    q = {"a": 0.5, "b": 0.5}
    concentrated = {10 + 4: 4, 10 + 3: 3}  # a@4, a@3
    dispersed = {10 + 4: 4, 20 + 4: 4}
    assert loss_of_selection(tuple(concentrated), facts, q) == pytest.approx(
        loss_of_selection(tuple(dispersed), facts, q)
    )


def _block_set(chain: str, *, base: int, length: int, first_rank: int) -> dict[int, BlockFact]:
    return {
        **{
            base + depth: _block(
                base + depth, chain, depth, length, first_rank + (length - depth)
            )
            for depth in range(1, length + 1)
        }
    }


def test_expected_loss_uses_the_shallowest_evicted_depth() -> None:
    facts = _block_set("a", base=10, length=4, first_rank=0)
    # Evicting depth 3 covers depths 4 and 3, so j = 3 and two tokens-blocks remain.
    assert expected_loss({"a": [4, 3]}, facts, {"a": 1.0}) == pytest.approx(2.0)
    # Adding a deeper block changes nothing.
    assert expected_loss({"a": [4, 3]}, facts, {"a": 1.0}) == expected_loss(
        {"a": [4]}, facts, {"a": 1.0}
    ) + 1.0


# --- scenarios -------------------------------------------------------------


def test_positive_scenario_shows_a_real_difference() -> None:
    row = evaluate(scenario_q_reorders_chains())
    assert row["set_differs"] is True
    assert row["cost_aware_expected_loss"] < row["native_expected_loss"]
    assert row["native_expected_loss"] == pytest.approx(1.8)
    assert row["cost_aware_expected_loss"] == pytest.approx(0.2)


def test_degenerate_scenario_reports_no_difference() -> None:
    row = evaluate(scenario_equal_q_degenerate())
    assert row["cost_aware_expected_loss"] == pytest.approx(row["native_expected_loss"])


def test_failure_scenario_is_worse_in_realised_terms() -> None:
    row = evaluate(scenario_q_wrong())
    # The estimate still looks favourable ...
    assert row["cost_aware_expected_loss"] < row["native_expected_loss"]
    # ... but the realised loss flips, because the proxy ranked the chains wrongly.
    assert row["realised_cost_aware_loss"] > row["realised_native_loss"]


def test_single_chain_scenario_has_no_freedom() -> None:
    row = evaluate(scenario_single_chain())
    assert row["set_differs"] is False
    assert row["cost_aware_expected_loss"] == pytest.approx(row["native_expected_loss"])


@pytest.mark.parametrize("scenario", all_scenarios(), ids=lambda s: s.name)
def test_scenario_selections_are_legal_and_sized(scenario) -> None:
    row = evaluate(scenario)
    legal = set(scenario.legal)
    assert set(row["native_blocks"]) <= legal
    assert set(row["cost_aware_blocks"]) <= legal
    assert len(row["native_blocks"]) == min(scenario.need, len(legal))
    assert len(row["cost_aware_blocks"]) == min(scenario.need, len(legal))
    assert len(set(row["cost_aware_blocks"])) == len(row["cost_aware_blocks"])


@pytest.mark.parametrize("scenario", all_scenarios(), ids=lambda s: s.name)
def test_cost_aware_scenario_loss_matches_the_shared_scorer(scenario) -> None:
    row = evaluate(scenario)
    recomputed = loss_of_selection(
        row["cost_aware_blocks"], scenario.facts, scenario.q_by_chain
    )
    assert row["cost_aware_expected_loss"] == pytest.approx(recomputed)


def test_all_chain_weights_are_proper_probabilities() -> None:
    """A q outside (0, 1) would mean the proxy is being used as something else."""
    for scenario in all_scenarios():
        for chain, q in scenario.q_by_chain.items():
            assert 0.0 < q < 1.0, f"{scenario.name}:{chain}={q}"
            assert not math.isnan(q)
