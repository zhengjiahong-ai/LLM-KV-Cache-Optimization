"""Phase 2G A2: cost-aware block victim selection.

Scope
-----
A2 changes **only** which legal block is evicted. Entry release, the legal candidate
set and the number of blocks evicted are all fixed by Continuum, exactly as in A0.
This module is a pure decision function: it receives the legal set plus the
decision-time cost facts and returns a victim set. It never mutates native state.

Objective
---------
Minimise expected aggregate recomputed tokens. For a victim set ``S``:

    L(S) = sum over chains c with at least one eviction of  q_c * B * (m_c - j_c(S) + 1)

where ``j_c(S) = min{ d_c(b) : b in S, b in chain c }`` and ``m_c`` is the chain
length in blocks. Only the *shallowest* evicted depth per chain matters, because an
APC prefix either resolves or it does not: once depth ``j`` is gone, every deeper
block of that chain is worthless and evicting more of them adds nothing.

Per-block marginal cost follows from that, and is what the incremental algorithm
uses:

    Delta(b | S) = sum over chains c containing b of  q_c * B * max(0, j_c(S) - d_c(b))

Evicting ``b`` then updates ``j_c := min(j_c, d_c(b))`` for **every** chain ``b``
belongs to. A shared block is therefore charged to each chain that would have to
recompute it, and no chain is charged twice for the same eviction.

Why greedy is not simply valid, and what is done about it
---------------------------------------------------------
``Delta`` is not submodular in general, so greedy can miss the optimum. Two concrete
reasons, both handled explicitly rather than assumed away:

1. **Chain saturation.** After the first eviction from a chain, every deeper block of
   that chain has ``Delta = 0``. A greedy walk therefore drains one chain per pass and
   is *correct* on a single chain, but across chains the choice of which chain to
   drain first is the real decision, and a cheap first pick can block a cheaper set.
2. **Shared blocks.** A block's cost depends on which chains are already drained, so
   the ordering of picks changes the total.

The algorithm therefore runs two selectors and keeps the better one:

- **incremental greedy** — exact marginal recomputation after every pick,
  ``O(k * n * r)`` for ``k`` evictions, ``n`` legal blocks and ``r`` memberships per
  block. Optimal on a single chain and on fully independent chains;
- **exact search** — branch and bound over victim sets, used when the legal set is
  small enough (``C(n, k)`` bounded by a configurable budget). This closes the gap
  greedy can leave when shared blocks couple the chains.

If the budget is exceeded the exact search is skipped and the greedy result is
returned, with the reason recorded. The result therefore carries which selector
produced it, and never silently claims optimality.

Fallback
--------
If any legal block's content identity, depth or chain reuse weight is unavailable, the
cost model cannot be evaluated without inventing information. In that case the
selector returns native LRU order restricted to the legal set, and records why.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .a2_geometry import (
    ChainKey,
    DecisionGeometry,
    LegalBlock,
    MissingReuseWeight,
)

#: Which selector produced the result.
SELECTOR_GREEDY = "incremental_greedy"
SELECTOR_EXACT = "exact_branch_and_bound"
SELECTOR_NATIVE_FALLBACK = "native_lru_fallback"

#: Why a fallback happened. Empty when the cost model was fully evaluable.
FALLBACK_CONTENT_UNVERIFIED = "content_unverified"
FALLBACK_REUSE_WEIGHT_MISSING = "reuse_weight_missing"
FALLBACK_NO_LEGAL_BLOCKS = "no_legal_blocks"


@dataclass(frozen=True, slots=True)
class VictimSelection:
    """One victim set plus everything needed to audit how it was produced."""

    blocks: tuple[int, ...]
    selector: str
    expected_recompute: float | None
    #: ``True`` when the cost model was fully evaluable for this decision.
    cost_known: bool
    fallbacks: tuple[str, ...] = ()
    #: Set when an exact search was skipped because the budget was exceeded.
    search_truncated: bool = False
    #: Per-step diagnostics: the marginal cost of each greedy pick.
    step_costs: tuple[float, ...] = ()

    @property
    def is_fallback(self) -> bool:
        return self.selector == SELECTOR_NATIVE_FALLBACK


# --------------------------------------------------------------------------
# cost model
# --------------------------------------------------------------------------


def chain_gap(
    evicted: Mapping[ChainKey, set[int]], chain: ChainKey, chain_length: int
) -> int:
    """Shallowest evicted depth, or ``m + 1`` when the chain is intact."""
    depths = evicted.get(chain)
    return min(depths) if depths else chain_length + 1


def chain_loss(
    evicted: Mapping[ChainKey, set[int]],
    geometry: DecisionGeometry,
) -> float:
    """``sum_c q_c * (m_c - j_c + 1)`` over chains with at least one eviction.

    Raises :class:`MissingReuseWeight` rather than treating an unpriced chain as free.
    """
    total = 0.0
    for chain, depths in evicted.items():
        if not depths:
            continue
        if chain not in geometry.q_by_chain:
            raise MissingReuseWeight(chain)
        j = min(depths)
        length = geometry.chain_length.get(chain, max(depths))
        total += geometry.q_by_chain[chain] * (length - j + 1)
    return total


def marginal_cost(
    block: LegalBlock,
    evicted: Mapping[ChainKey, set[int]],
    geometry: DecisionGeometry,
) -> float:
    """``Delta(b | S)``, summed once per chain the block belongs to.

    A hashless block has no memberships and therefore costs nothing, which is correct:
    it holds no prefix content, so evicting it forces no recomputation.
    """
    total = 0.0
    for membership in block.memberships:
        if membership.chain not in geometry.q_by_chain:
            raise MissingReuseWeight(membership.chain)
        length = geometry.chain_length.get(membership.chain, membership.depth)
        j = chain_gap(evicted, membership.chain, length)
        total += geometry.q_by_chain[membership.chain] * max(0, j - membership.depth)
    return total


def _apply(
    block: LegalBlock, evicted: dict[ChainKey, set[int]]
) -> None:
    """Record an eviction: every chain containing the block moves its gap inward."""
    for membership in block.memberships:
        evicted.setdefault(membership.chain, set()).add(membership.depth)


# --------------------------------------------------------------------------
# selectors
# --------------------------------------------------------------------------


def native_lru_order(geometry: DecisionGeometry) -> tuple[int, ...]:
    """Native LRU order over the legal set: smallest recorded rank first."""
    ordered = sorted(
        geometry.blocks.values(), key=lambda block: (block.native_rank, block.block_id)
    )
    return tuple(block.block_id for block in ordered)


def _tie_break(geometry: DecisionGeometry, block_id: int) -> tuple[float, int]:
    """Deterministic, cost-independent ordering for equal marginal costs.

    Rank first because it is the frozen engine order, then block id so the result
    never depends on dict iteration order.
    """
    return (geometry.blocks[block_id].native_rank, block_id)


def greedy_select(
    geometry: DecisionGeometry, need: int
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Incremental greedy: recompute every marginal cost after each pick.

    Complexity ``O(k * n * r)`` for ``k = min(need, n)`` picks, ``n`` legal blocks and
    ``r`` memberships per block. Exact on a single chain: the first pick sets the gap
    and every deeper block then has marginal cost zero, so the walk drains that chain
    deepest-first before touching anything else.
    """
    remaining = dict(geometry.blocks)
    evicted: dict[ChainKey, set[int]] = {}
    chosen: list[int] = []
    step_costs: list[float] = []

    for _ in range(min(need, len(remaining))):
        best_id: int | None = None
        best_key: tuple[float, float, int] | None = None
        for block_id, block in remaining.items():
            cost = marginal_cost(block, evicted, geometry)
            rank, tie = _tie_break(geometry, block_id)
            key = (cost, rank, tie)
            if best_key is None or key < best_key:
                best_key, best_id = key, block_id
        if best_id is None:
            break
        chosen.append(best_id)
        step_costs.append(best_key[0] if best_key is not None else math.inf)
        _apply(remaining.pop(best_id), evicted)

    return tuple(chosen), tuple(step_costs)


def exact_select(
    geometry: DecisionGeometry, need: int, *, budget: int
) -> tuple[tuple[int, ...], float] | None:
    """Exhaustive search over victim sets, or ``None`` when over budget.

    Only viable for small decisions; the caller passes ``budget`` as the maximum
    number of combinations to enumerate. Ties break on the sorted victim tuple so the
    result is deterministic.
    """
    legal = sorted(geometry.blocks)
    k = min(need, len(legal))
    if k == 0:
        return (), 0.0
    combinations = math.comb(len(legal), k)
    if combinations > budget:
        return None

    best: tuple[float, tuple[int, ...]] | None = None
    for combo in itertools.combinations(legal, k):
        evicted: dict[ChainKey, set[int]] = {}
        for block_id in combo:
            _apply(geometry.blocks[block_id], evicted)
        loss = chain_loss(evicted, geometry)
        key = (loss, combo)
        if best is None or key < best:
            best = key
    assert best is not None
    return best[1], best[0]


# --------------------------------------------------------------------------
# the decision function
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class A2Config:
    """Knobs that affect the search, not the objective."""

    #: Maximum victim-set combinations the exact search may enumerate.
    exact_search_budget: int = 20_000
    #: Set ``False`` to skip the exact search and keep greedy only.
    enable_exact_search: bool = True


@dataclass(frozen=True, slots=True)
class A2BlockSelector:
    """Cost-aware block victim selection, with safe fallback to native LRU.

    The decision function is pure: given the same geometry, ``need`` and config it
    always returns the same victim set.
    """

    config: A2Config = field(default_factory=A2Config)

    def select(self, geometry: DecisionGeometry, need: int) -> VictimSelection:
        """Choose ``min(need, |legal|)`` victims.

        Order of operations:

        1. if there is nothing to choose, return empty;
        2. if the cost model is not fully evaluable, return native LRU order over the
           legal set and record why;
        3. run incremental greedy;
        4. if configured and over budget, keep greedy; otherwise run the exact search
           and keep whichever set has the lower modelled loss (greedy wins ties, so the
           cheaper-to-audit answer is preferred).
        """
        legal = geometry.blocks
        if not legal or need <= 0:
            return VictimSelection(
                blocks=(),
                selector=SELECTOR_GREEDY,
                expected_recompute=0.0,
                cost_known=True,
            )

        fallbacks = self._fallbacks(geometry)
        if fallbacks:
            ordered = native_lru_order(geometry)
            return VictimSelection(
                blocks=ordered[: min(need, len(ordered))],
                selector=SELECTOR_NATIVE_FALLBACK,
                expected_recompute=None,
                cost_known=False,
                fallbacks=fallbacks,
            )

        greedy_blocks, step_costs = greedy_select(geometry, need)
        greedy_loss = self._loss(greedy_blocks, geometry)
        best_blocks, best_loss = greedy_blocks, greedy_loss
        selector = SELECTOR_GREEDY
        truncated = False

        if self.config.enable_exact_search:
            exact = exact_select(
                geometry, need, budget=self.config.exact_search_budget
            )
            if exact is None:
                truncated = True
            else:
                exact_blocks, exact_loss = exact
                # Greedy wins ties: equal loss means the cheaper-to-audit answer.
                if exact_loss < best_loss - 1e-12:
                    best_blocks, best_loss = exact_blocks, exact_loss
                    selector = SELECTOR_EXACT

        return VictimSelection(
            blocks=best_blocks,
            selector=selector,
            expected_recompute=best_loss,
            cost_known=True,
            search_truncated=truncated,
            step_costs=step_costs if selector == SELECTOR_GREEDY else (),
        )

    # -- helpers ---------------------------------------------------------

    def _fallbacks(self, geometry: DecisionGeometry) -> tuple[str, ...]:
        reasons: list[str] = []
        if geometry.gaps:
            reasons.append(FALLBACK_CONTENT_UNVERIFIED)
        if geometry.unknown_weight_chains:
            reasons.append(FALLBACK_REUSE_WEIGHT_MISSING)
        for block in geometry.blocks.values():
            if not block.has_block_hash:
                continue
            for membership in block.memberships:
                if membership.chain not in geometry.q_by_chain:
                    if FALLBACK_REUSE_WEIGHT_MISSING not in reasons:
                        reasons.append(FALLBACK_REUSE_WEIGHT_MISSING)
                    break
        return tuple(reasons)

    @staticmethod
    def _loss(blocks: Sequence[int], geometry: DecisionGeometry) -> float:
        evicted: dict[ChainKey, set[int]] = {}
        for block_id in blocks:
            _apply(geometry.blocks[block_id], evicted)
        return chain_loss(evicted, geometry)


def select_victims(
    geometry: DecisionGeometry,
    need: int,
    *,
    config: A2Config | None = None,
) -> VictimSelection:
    """Convenience entry point mirroring ``EvictionPolicyAdapter.select_victims``."""
    return A2BlockSelector(config or A2Config()).select(geometry, need)
