"""Controlled block-geometry scenarios for the A2 mechanism study.

These are hand-built and small on purpose. On the recorded corpora the two rules
never diverge (see ``docs/experiments/phase2g-a2/README.md``), so a controlled
construction is the only way to show *what would have to be true* for the block
layer to have independent value, and what a realistic failure looks like.

Each scenario fixes the legal candidate set, the chain geometry, and the reuse
proxy, then reports both rules scored by the same expected-loss function.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .a2_mechanism import (
    BlockFact,
    cost_aware_selection,
    loss_of_selection,
    native_selection,
)


@dataclass(frozen=True, slots=True)
class BlockScenario:
    """One legal candidate set plus the chain geometry and reuse weights."""

    name: str
    purpose: str
    expectation: str
    facts: dict[int, BlockFact]
    q_by_chain: Mapping[str, float]
    need: int
    notes: str = ""
    #: Evaluation-only ground truth: which chains actually return.
    returns_after_decision: Mapping[str, bool] = field(default_factory=dict)

    @property
    def legal(self) -> list[int]:
        return sorted(self.facts)


def _facts(
    chain: str,
    chain_length: int,
    *,
    first_rank: int,
    depths: Sequence[int],
) -> dict[int, BlockFact]:
    """Blocks of one chain, with rank inversely monotone in depth as observed."""
    rows: dict[int, BlockFact] = {}
    for index, depth in enumerate(depths):
        block_id = {"A": 100, "B": 200, "C": 300}.get(chain, 900) + depth
        rows[block_id] = BlockFact(
            block_id=block_id,
            chain=chain,
            depth=depth,
            chain_length=chain_length,
            # deeper blocks are colder: depth m -> rank first_rank
            native_rank=first_rank + (max(depths) - depth),
        )
    return rows


def scenario_q_reorders_chains() -> BlockScenario:
    """Positive case: the cheap-to-lose chain is NOT the coldest chain.

    Chain A has the coldest blocks, so native LRU drains A. Chain B is far less
    likely to return, so the marginal-cost rule drains B instead. Both satisfy the
    target; only the expected loss differs.
    """
    facts = {
        **_facts("A", 4, first_rank=0, depths=(1, 2, 3, 4)),
        **_facts("B", 4, first_rank=4, depths=(1, 2, 3, 4)),
    }
    return BlockScenario(
        name="q_reorders_chains",
        purpose="cost-aware prefers the cheap chain while native follows recency",
        expectation="native drains A (loss 1.8), cost-aware drains B (loss 0.2)",
        facts=facts,
        q_by_chain={"A": 0.9, "B": 0.1},
        need=2,
        notes=(
            "Native takes A's two coldest blocks A@4, A@3 -> j_A = 3 -> 0.9 * 2 = 1.8. "
            "Cost-aware takes B@4 (delta 0.1) then B@3 (delta 0.2) -> j_B = 3 -> "
            "0.1 * 2 = 0.2. Same target, nine times lower expected recomputation."
        ),
        returns_after_decision={"A": True, "B": False},
    )


def scenario_equal_q_degenerate() -> BlockScenario:
    """Degenerate case: equal q removes the only signal that distinguishes chains.

    With identical chains and equal q, both rules satisfy the target at the same
    expected loss. The sets may still differ in order, which is exactly why order
    difference must not be reported as a benefit.
    """
    facts = {
        **_facts("A", 4, first_rank=0, depths=(1, 2, 3, 4)),
        **_facts("B", 4, first_rank=4, depths=(1, 2, 3, 4)),
    }
    return BlockScenario(
        name="equal_q_degenerate",
        purpose="no reuse asymmetry means no block-level decision space",
        expectation="both rules reach the same expected loss",
        facts=facts,
        q_by_chain={"A": 0.5, "B": 0.5},
        need=2,
        notes=(
            "Either chain costs 0.5 * 2 = 1.0. This is the token-metric linearity "
            "result: at equal q, concentrating and dispersing cost the same."
        ),
    )


def scenario_q_wrong() -> BlockScenario:
    """Failure case: the proxy ranks the chains the wrong way round.

    Cost-aware sacrifices B because the proxy says B is unlikely to return. If B is
    in fact the chain that returns, the rule has just bought a recomputation that
    native LRU would have avoided.
    """
    facts = {
        **_facts("A", 4, first_rank=0, depths=(1, 2, 3, 4)),
        **_facts("B", 4, first_rank=4, depths=(1, 2, 3, 4)),
    }
    return BlockScenario(
        name="q_wrong",
        purpose="a mis-estimated q can make the marginal-cost rule worse than native",
        expectation="cost-aware still picks B, but ground truth says B returns",
        facts=facts,
        q_by_chain={"A": 0.9, "B": 0.1},
        need=2,
        notes=(
            "Identical geometry to the positive case, so the *choice* is the same; "
            "only the ground truth differs. That is the point: the rule cannot "
            "distinguish a correct q from a lucky one, so q reliability has to be "
            "measured, not assumed."
        ),
        returns_after_decision={"A": False, "B": True},
    )


def scenario_single_chain() -> BlockScenario:
    """No freedom at all: one chain must supply everything.

    With a single chain, the depth order is forced and native LRU already evicts
    deepest-first, so there is nothing for a block-layer rule to decide. Reporting
    "no divergence" here is vacuous rather than reassuring, which is why it is
    included: on a single-chain decision the study proves nothing either way.
    """
    facts = _facts("A", 6, first_rank=0, depths=(1, 2, 3, 4, 5, 6))
    return BlockScenario(
        name="single_chain_no_freedom",
        purpose="legal geometry can leave no freedom at all",
        expectation="both rules take the same four deepest blocks of A",
        facts=facts,
        q_by_chain={"A": 0.9},
        need=4,
        notes=(
            "Only A is legal, so both rules take A@6..A@3 and the expected loss is "
            "0.9 * 4 = 3.6 for both. Not every 'no divergence' is evidence about "
            "the rule."
        ),
    )


def all_scenarios() -> tuple[BlockScenario, ...]:
    return (
        scenario_q_reorders_chains(),
        scenario_equal_q_degenerate(),
        scenario_q_wrong(),
        scenario_single_chain(),
    )


def evaluate(scenario: BlockScenario) -> dict[str, object]:
    """Score both rules on one scenario with the shared expected-loss function."""
    legal = scenario.legal
    native = native_selection(legal, scenario.facts, scenario.need)
    aware, _ = cost_aware_selection(legal, scenario.facts, scenario.need, scenario.q_by_chain)
    native_loss = loss_of_selection(native, scenario.facts, scenario.q_by_chain)
    aware_loss = loss_of_selection(aware, scenario.facts, scenario.q_by_chain)

    realised_native: float | None = None
    realised_aware: float | None = None
    if scenario.returns_after_decision:
        realised_native = _realised(native, scenario)
        realised_aware = _realised(aware, scenario)

    return {
        "scenario": scenario.name,
        "purpose": scenario.purpose,
        "expectation": scenario.expectation,
        "need": scenario.need,
        "native_blocks": native,
        "cost_aware_blocks": aware,
        "order_differs": native != aware,
        "set_differs": set(native) != set(aware),
        "native_expected_loss": native_loss,
        "cost_aware_expected_loss": aware_loss,
        "realised_native_loss": realised_native,
        "realised_cost_aware_loss": realised_aware,
        "notes": scenario.notes,
    }


def _realised(selection: Sequence[int], scenario: BlockScenario) -> float:
    """Loss counting only chains that actually return (evaluation-side only)."""
    q_truth = {
        chain: (1.0 if returns else 0.0)
        for chain, returns in scenario.returns_after_decision.items()
    }
    return loss_of_selection(selection, scenario.facts, q_truth)
