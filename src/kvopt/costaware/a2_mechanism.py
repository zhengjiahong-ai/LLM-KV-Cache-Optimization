"""A2 mechanism study: is there independent decision space at the block layer?

Scope
-----
This is a singly-owned, rank-correlated H1 diagnostic. Shared blocks require
multi-chain ownership and are explicitly unsupported; position is not verified
native prefix depth.

A2 keeps Continuum's entry release unchanged and replaces only *which legal block*
the eviction path takes. This module answers that question offline on recorded
decisions; it does not implement a native policy and does not run experiments.

The rule it evaluates is the one accepted for the joint design (PR #50 §3.4):

    Delta(b) = q_c * B_b * max(0, j_c - d_c(b))

where ``j_c`` is the shallowest already-evicted depth on chain ``c`` and ``d_c(b)``
is the block's depth. Greedily taking the minimum ``Delta`` is compared against
native LRU order.

Why the comparison is necessarily *between* chains
--------------------------------------------------
Depth and chain membership are reconstructed from each candidate's ``block_ids``
order. On the recorded decisions that order is strictly inverse-monotone in
``native_lru_rank`` (294/294 entries, verified by
``scripts/probes/a2_block_geometry.py``). So within a chain, native LRU already
evicts deepest-first and there is no depth decision to make. Any difference
between the two rules must come from *which chain* is drained first, i.e. from
``q_c`` rather than from block geometry.

That is a real but narrow decision space, and this module reports exactly how
large it is instead of assuming it is large.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .replay import CandidateKey, DecisionSnapshot

#: Blocks with no recorded owner carry no recomputation cost.
UNOWNED = "<unowned>"


@dataclass(frozen=True, slots=True)
class BlockFact:
    """Everything the block layer needs about one legal block."""

    block_id: int
    chain: str
    depth: int
    chain_length: int
    native_rank: int


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    """One rule's victim set on one decision."""

    rule: str
    blocks: tuple[int, ...]
    expected_recompute: float
    chains_touched: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionDivergence:
    """Native LRU versus cost-aware on the same legal candidate set."""

    run_id: str
    decision_event_index: int
    target: int
    legal_count: int
    order_differs: bool
    set_differs: bool
    native: SelectionOutcome
    cost_aware: SelectionOutcome
    chain_count: int
    branch: str


def reconstruct_blocks(
    snapshot: DecisionSnapshot,
    rows: Mapping[CandidateKey, object],
) -> dict[int, BlockFact]:
    """Build a *single-owner diagnostic proxy*, not native prefix provenance.

    ``block_ids`` position is an assumed depth proxy correlated with LRU rank in
    the inspected H1 artifacts; rank monotonicity does not establish true
    prefix depth. A shared physical block may participate in several chains;
    this one-chain diagnostic MUST reject such cases rather than silently
    overwrite an owner and undercount the joint-design marginal loss.
    """
    facts: dict[int, BlockFact] = {}
    for key, row in rows.items():
        block_ids = getattr(row, "block_ids", ())
        for depth, block_id in enumerate(block_ids, start=1):
            if block_id not in snapshot.ranking_by_block:
                # Not currently in the free queue, so not a legal candidate.
                continue
            chain = f"{key[0]}:{key[1]}"
            if block_id in facts and facts[block_id].chain != chain:
                raise ValueError(
                    "MULTI_CHAIN_BLOCK_UNSUPPORTED: physical block "
                    f"{block_id} belongs to both {facts[block_id].chain} and {chain}; "
                    "requires content-chain ownership and a multi-chain loss function"
                )
            facts[block_id] = BlockFact(
                block_id=block_id,
                chain=f"{key[0]}:{key[1]}",
                depth=depth,
                chain_length=len(block_ids),
                native_rank=snapshot.ranking_by_block[block_id],
            )
    return facts


def chain_lengths(rows: Mapping[CandidateKey, object]) -> dict[str, int]:
    return {
        f"{key[0]}:{key[1]}": len(getattr(row, "block_ids", ())) for key, row in rows.items()
    }


def native_selection(
    legal: Sequence[int], facts: Mapping[int, BlockFact], need: int
) -> tuple[int, ...]:
    """Native LRU: take the blocks with the smallest ``native_lru_rank``."""
    ordered = sorted(legal, key=lambda block_id: facts[block_id].native_rank)
    return tuple(ordered[:need])


def _gap(evicted: Mapping[str, list[int]], chain: str, chain_length: int) -> int:
    depths = evicted.get(chain)
    return min(depths) if depths else chain_length + 1


def cost_aware_selection(
    legal: Sequence[int],
    facts: Mapping[int, BlockFact],
    need: int,
    q_by_chain: Mapping[str, float],
) -> tuple[tuple[int, ...], float]:
    """Greedy minimum marginal expected recomputation.

    Returns the chosen blocks and the resulting expected loss, so the two rules
    can be compared on a common scale rather than only by set difference.
    """
    remaining = list(legal)
    evicted: dict[str, list[int]] = {}
    chosen: list[int] = []
    for _ in range(min(need, len(remaining))):
        best_block = None
        best_key: tuple[float, str, int] | None = None
        for block_id in remaining:
            fact = facts[block_id]
            if fact.chain == UNOWNED:
                delta = 0.0
            else:
                j = _gap(evicted, fact.chain, fact.chain_length)
                delta = q_by_chain.get(fact.chain, 0.0) * max(0, j - fact.depth)
            key = (delta, fact.chain, block_id)
            if best_key is None or key < best_key:
                best_key, best_block = key, block_id
        if best_block is None:
            break
        chosen.append(best_block)
        remaining.remove(best_block)
        fact = facts[best_block]
        if fact.chain != UNOWNED:
            evicted.setdefault(fact.chain, []).append(fact.depth)
    return tuple(chosen), expected_loss(evicted, facts, q_by_chain)


def expected_loss(
    evicted: Mapping[str, list[int]],
    facts: Mapping[int, BlockFact],
    q_by_chain: Mapping[str, float],
) -> float:
    """``sum_c q_c * (m_c - j_c + 1)`` over chains with at least one eviction."""
    total = 0.0
    lengths: dict[str, int] = {}
    for fact in facts.values():
        lengths[fact.chain] = fact.chain_length
    for chain, depths in evicted.items():
        if chain == UNOWNED or not depths:
            continue
        j = min(depths)
        total += q_by_chain.get(chain, 0.0) * (lengths.get(chain, 0) - j + 1)
    return total


def loss_of_selection(
    selection: Sequence[int],
    facts: Mapping[int, BlockFact],
    q_by_chain: Mapping[str, float],
) -> float:
    """Expected loss of an arbitrary victim set, so both rules are measured alike."""
    evicted: dict[str, list[int]] = {}
    for block_id in selection:
        fact = facts[block_id]
        if fact.chain == UNOWNED:
            continue
        evicted.setdefault(fact.chain, []).append(fact.depth)
    return expected_loss(evicted, facts, q_by_chain)


def reuse_proxy_by_chain(
    snapshot: DecisionSnapshot,
    rows: Mapping[CandidateKey, object],
    *,
    tau_seconds: float = 30.0,
) -> dict[str, float]:
    """``q_c`` for each chain, from the same TTL proxy A1 uses."""
    proxies: dict[str, float] = {}
    for key, row in rows.items():
        deadline = float(row.retention_deadline_timestamp)
        proxies[f"{key[0]}:{key[1]}"] = 1.0 / (
            1.0 + math.exp(-(deadline - snapshot.timestamp) / tau_seconds)
        )
    return proxies


def analyse_decision(
    snapshot: DecisionSnapshot,
    rows: Mapping[CandidateKey, object],
    *,
    tau_seconds: float = 30.0,
) -> DecisionDivergence | None:
    """Run A0's release, then compare native LRU with cost-aware on ``E(R)``.

    Returns ``None`` when the decision offers no legal block at all, which simply
    means the block layer has nothing to decide.
    """
    from .replay import ExecutedP1BStrategy, ReplayState, replay_decision

    result = replay_decision(snapshot, ExecutedP1BStrategy(), rows)  # type: ignore[arg-type]
    state = ReplayState(snapshot)
    for key in result.released:
        state.release(key)
    eligible = state.eligible_block_ids()
    if not eligible:
        return None

    facts = reconstruct_blocks(snapshot, rows)
    for block_id in eligible:
        if block_id not in facts:
            facts[block_id] = BlockFact(
                block_id=block_id,
                chain=UNOWNED,
                depth=0,
                chain_length=0,
                native_rank=snapshot.ranking_by_block.get(block_id, 0),
            )

    legal = sorted(eligible)
    need = min(snapshot.target, len(legal))
    q_by_chain = reuse_proxy_by_chain(snapshot, rows, tau_seconds=tau_seconds)

    native_blocks = native_selection(legal, facts, need)
    cost_blocks, greedy_loss = cost_aware_selection(legal, facts, need, q_by_chain)

    # Both arms are scored by the same function, so the comparison cannot favour
    # whichever rule produced its own number.
    native_loss = loss_of_selection(native_blocks, facts, q_by_chain)
    cost_loss = loss_of_selection(cost_blocks, facts, q_by_chain)
    if abs(cost_loss - greedy_loss) > 1e-9:
        raise AssertionError(
            "greedy loss disagrees with the shared scorer: "
            f"{greedy_loss} != {cost_loss}"
        )

    chains = {facts[b].chain for b in legal if facts[b].chain != UNOWNED}
    return DecisionDivergence(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        target=need,
        legal_count=len(legal),
        order_differs=native_blocks != cost_blocks,
        set_differs=set(native_blocks) != set(cost_blocks),
        native=SelectionOutcome(
            rule="native_lru",
            blocks=native_blocks,
            expected_recompute=native_loss,
            chains_touched=tuple(sorted({facts[b].chain for b in native_blocks})),
        ),
        cost_aware=SelectionOutcome(
            rule="cost_aware_marginal",
            blocks=cost_blocks,
            expected_recompute=cost_loss,
            chains_touched=tuple(sorted({facts[b].chain for b in cost_blocks})),
        ),
        chain_count=len(chains),
        branch="unowned_first" if UNOWNED in {facts[b].chain for b in legal} else "owned_only",
    )
