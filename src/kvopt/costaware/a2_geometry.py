"""A2 block-level geometry with content identity, true depth, and multi-chain ownership.

What this replaces, and why
---------------------------
An earlier version keyed blocks by ``block_id``, read depth from the position of
``block_ids`` in a *candidate entry*, and refused any block owned by more than one
chain. All three were wrong for this question:

1. **native LRU rank is not prefix depth.** Rank is recency; depth is position in
   the request's content. They agreed on the H1 artifacts only because rank happened
   to be depth-ordered there, so nothing about depth could be concluded from it.
2. **A physical block can belong to several chains.** Mapping each block to exactly
   one chain silently drops the joint-design marginal loss
   (PR #50 §3.4.5: ``Delta(b)`` is summed once per chain containing ``b``).
3. Chain membership comes from **ownership**, and depth must come from **content**.

The corrected model
-------------------
Identity is the **content hash**; depth is the block's position in that chain's
ordered hash sequence, both read from ``VLLM_PREFIX_SNAPSHOT``, which carries
``block_ids`` and ``ordered_native_hashes`` aligned by position. A block id may
appear in several snapshots and therefore in several chains, at (possibly
different) depths; all memberships are kept.

Cost, exactly as accepted in PR #50 §3.4:

    Delta(b) = sum over chains c containing b of  q_c * B * max(0, j_c - d_c(b))

and evicting ``b`` moves ``j_c = min(j_c, d_c(b))`` for **every** chain it belongs
to. Chain loss is ``q_c * (m_c - j_c + 1)``, summed over chains with an eviction.

Missing information is reported, never substituted
--------------------------------------------------
If a legal block's depth in some chain cannot be reconstructed, the decision is
marked as having an observation gap and is excluded from the cost comparison. Rank
is never used as a stand-in for depth; a decision that cannot be scored is reported
as unscorable rather than scored approximately.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

#: Chain identity: ``(program_id, prefix_id)``.
ChainKey = str

#: Reasons a decision can be excluded from the cost comparison.
GAP_DEPTH_UNKNOWN = "depth_unknown"
GAP_CONTENT_UNVERIFIED = "content_unverified"
#: Kept for callers that still import the older name.
GAP_CONTENT_UNKNOWN = GAP_CONTENT_UNVERIFIED
GAP_NO_MEMBERSHIP = "no_chain_membership"

#: Blocks that are legal but owned by no candidate chain.
UNOWNED = "<unowned>"


@dataclass(frozen=True, slots=True)
class Membership:
    """One block's place inside one chain."""

    chain: ChainKey
    depth: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class LegalBlock:
    """A legal eviction candidate with every chain it participates in."""

    block_id: int
    native_rank: int
    memberships: tuple[Membership, ...]
    has_block_hash: bool = True

    @property
    def chains(self) -> tuple[ChainKey, ...]:
        return tuple(sorted({m.chain for m in self.memberships}))

    @property
    def is_shared(self) -> bool:
        """True when the block participates in more than one chain."""
        return len({m.chain for m in self.memberships}) > 1

    @property
    def content_hash(self) -> str | None:
        """Content identity, which must be unique when known."""
        hashes = {m.content_hash for m in self.memberships}
        if len(hashes) > 1:
            raise ValueError(
                f"block {self.block_id} maps to conflicting content hashes {hashes}"
            )
        return next(iter(hashes)) if hashes else None

    @property
    def cost_known(self) -> bool:
        """A hashless block costs nothing, so it is always scorable.

        The engine marks such a block ``has_block_hash=False``: it holds no prefix
        content and can be evicted without any recomputation. Treating that as a
        missing observation would misclassify the cheapest blocks in the queue.
        """
        return (not self.has_block_hash) or bool(self.memberships)


@dataclass(frozen=True, slots=True)
class DecisionGeometry:
    """Everything the block layer can see for one decision."""

    blocks: Mapping[int, LegalBlock]
    chain_length: Mapping[ChainKey, int]
    q_by_chain: Mapping[ChainKey, float]
    gaps: Mapping[int, str] = field(default_factory=dict)
    #: Chains whose content is proved but whose reuse weight could not be obtained.
    unknown_weight_chains: tuple[ChainKey, ...] = ()

    @property
    def scorable(self) -> bool:
        """A decision is scorable only when nothing about its cost is unknown.

        Two independent failures disqualify it, and neither may be silently treated
        as zero:

        - a hash-carrying block whose content identity could not be proved;
        - a proved chain with no decision-time reuse weight, because a real chain
          with content but unknown ``q`` is not a zero-cost chain.

        Hashless blocks are exempt: they carry no prefix content, so their cost is
        zero by construction rather than unknown.
        """
        if self.gaps or self.unknown_weight_chains:
            return False
        # Any chain that carries priced content must have a weight.
        for block in self.blocks.values():
            if block.has_block_hash and block.memberships:
                for membership in block.memberships:
                    if membership.chain not in self.q_by_chain:
                        return False
        return True

    @property
    def shared_block_count(self) -> int:
        return sum(1 for block in self.blocks.values() if block.is_shared)

    @property
    def multi_chain_decision(self) -> bool:
        return len({m.chain for b in self.blocks.values() for m in b.memberships}) > 1


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    """One rule's victim set on one decision."""

    rule: str
    blocks: tuple[int, ...]
    expected_recompute: float
    chains_touched: tuple[ChainKey, ...]
    shared_blocks_taken: int


@dataclass(frozen=True, slots=True)
class DecisionDivergence:
    """Native LRU versus cost-aware on the same legal candidate set."""

    run_id: str
    decision_event_index: int
    need: int
    legal_count: int
    shared_block_count: int
    chain_count: int
    order_differs: bool
    victim_set_differs: bool
    #: ``None`` when the loss cannot be computed, so the selection stays a diagnostic.
    native: SelectionOutcome | None
    cost_aware: SelectionOutcome | None
    q_order_agrees_with_rank: bool | None
    #: Every block's content and every chain's weight were known.
    scorable: bool
    #: ``scorable`` **and** both losses were computed: only these may be counted.
    verified: bool = False
    gaps: Mapping[int, str] = field(default_factory=dict)
    native_blocks: tuple[int, ...] = ()
    cost_aware_blocks: tuple[int, ...] = ()
    unknown_weight_chains: tuple[ChainKey, ...] = ()


# --------------------------------------------------------------------------
# cost model
# --------------------------------------------------------------------------


class MissingReuseWeight(ValueError):
    """A chain carrying priced content has no decision-time reuse weight.

    Raised instead of defaulting to zero, because a real chain with content but
    unknown ``q`` is not a free chain. Callers must record the decision as
    unscorable rather than silently scoring it as cheap.
    """

    def __init__(self, chain: ChainKey) -> None:
        super().__init__(f"no decision-time reuse weight for chain {chain!r}")
        self.chain = chain


def _jam(evicted: Mapping[ChainKey, set[int]], chain: ChainKey, length: int) -> int:
    depths = evicted.get(chain)
    return min(depths) if depths else length + 1


def marginal_delta(
    block: LegalBlock,
    evicted: Mapping[ChainKey, set[int]],
    chain_length: Mapping[ChainKey, int],
    q_by_chain: Mapping[ChainKey, float],
) -> float:
    """``sum_c q_c * max(0, j_c - d_c(b))``, once per chain containing the block.

    Raises :class:`MissingReuseWeight` when a chain containing the block has no
    weight, rather than treating that chain as free.
    """
    total = 0.0
    for membership in block.memberships:
        if membership.chain not in q_by_chain:
            raise MissingReuseWeight(membership.chain)
        length = chain_length.get(membership.chain, membership.depth)
        j = _jam(evicted, membership.chain, length)
        total += q_by_chain[membership.chain] * max(0, j - membership.depth)
    return total


def chain_loss(
    evicted: Mapping[ChainKey, set[int]],
    chain_length: Mapping[ChainKey, int],
    q_by_chain: Mapping[ChainKey, float],
) -> float:
    """``sum_c q_c * (m_c - j_c + 1)`` over chains with at least one eviction.

    Raises :class:`MissingReuseWeight` for an evicted chain with no weight.
    """
    total = 0.0
    for chain, depths in evicted.items():
        if not depths:
            continue
        if chain not in q_by_chain:
            raise MissingReuseWeight(chain)
        j = min(depths)
        length = chain_length.get(chain, max(depths))
        total += q_by_chain[chain] * (length - j + 1)
    return total


def native_selection(geometry: DecisionGeometry, need: int) -> tuple[int, ...]:
    """Native LRU order: smallest recorded ``native_lru_rank`` first."""
    ordered = sorted(geometry.blocks.values(), key=lambda block: block.native_rank)
    return tuple(block.block_id for block in ordered[:need])


def cost_aware_selection(geometry: DecisionGeometry, need: int) -> tuple[int, ...]:
    """Greedy minimum marginal expected recomputation."""
    remaining = dict(geometry.blocks)
    evicted: dict[ChainKey, set[int]] = {}
    chosen: list[int] = []
    for _ in range(min(need, len(remaining))):
        best_id: int | None = None
        best_key: tuple[float, int] | None = None
        for block_id, block in remaining.items():
            delta = marginal_delta(block, evicted, geometry.chain_length, geometry.q_by_chain)
            key = (delta, block_id)
            if best_key is None or key < best_key:
                best_key, best_id = key, block_id
        if best_id is None:
            break
        chosen.append(best_id)
        block = remaining.pop(best_id)
        for membership in block.memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return tuple(chosen)


def cost_aware_selection_diagnostic(
    geometry: DecisionGeometry, need: int
) -> tuple[int, ...]:
    """Greedy ordering that tolerates unknown weights, for diagnostics only.

    Unknown weights are treated as zero **for ordering** so a choice can still be
    displayed. The result must never be scored or counted as a verified comparison,
    which is why it has a separate name rather than a ``strict=False`` flag: the
    distinction is about what the number is allowed to be used for.
    """
    remaining = dict(geometry.blocks)
    evicted: dict[ChainKey, set[int]] = {}
    chosen: list[int] = []
    for _ in range(min(need, len(remaining))):
        best_id: int | None = None
        best_key: tuple[float, int] | None = None
        for block_id, block in remaining.items():
            delta = 0.0
            for membership in block.memberships:
                weight = geometry.q_by_chain.get(membership.chain, 0.0)
                length = geometry.chain_length.get(membership.chain, membership.depth)
                j = _jam(evicted, membership.chain, length)
                delta += weight * max(0, j - membership.depth)
            key = (delta, block_id)
            if best_key is None or key < best_key:
                best_key, best_id = key, block_id
        if best_id is None:
            break
        chosen.append(best_id)
        block = remaining.pop(best_id)
        for membership in block.memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return tuple(chosen)


def selection_outcome(
    rule: str,
    blocks: Sequence[int],
    geometry: DecisionGeometry,
) -> SelectionOutcome:
    """Score a victim set with the shared loss function."""
    evicted: dict[ChainKey, set[int]] = {}
    shared = 0
    for block_id in blocks:
        block = geometry.blocks[block_id]
        if block.is_shared:
            shared += 1
        for membership in block.memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return SelectionOutcome(
        rule=rule,
        blocks=tuple(blocks),
        expected_recompute=chain_loss(evicted, geometry.chain_length, geometry.q_by_chain),
        chains_touched=tuple(sorted(evicted)),
        shared_blocks_taken=shared,
    )


def q_order_agrees(geometry: DecisionGeometry) -> bool | None:
    """Does the cheapest-``q`` chain coincide with the chain native drains first?

    "Native drains first" means the chain holding the **coldest hash-carrying
    block**, because a hashless block belongs to no chain and cannot identify one.
    Returns ``None`` when the comparison is meaningless: fewer than two chains with
    a usable ``q``, or no hash-carrying block with a known membership.
    """
    chain_q: dict[ChainKey, float] = {}
    for block in geometry.blocks.values():
        for membership in block.memberships:
            if membership.chain not in geometry.q_by_chain:
                # An unknown weight would compare as the cheapest chain; that would
                # turn a missing signal into a spurious divergence.
                return None
            chain_q[membership.chain] = geometry.q_by_chain[membership.chain]
    if len(chain_q) < 2:
        return None

    hashed = [
        block
        for block in geometry.blocks.values()
        if block.has_block_hash and block.memberships
    ]
    if not hashed:
        return None

    cheapest = min(chain_q, key=lambda chain: (chain_q[chain], chain))
    coldest_block = min(hashed, key=lambda b: (b.native_rank, b.block_id))
    # A shared block has several chains; the one it would be charged to first is
    # the cheapest of them, which is also the choice a greedy cost rule would make.
    coldest_chain = min(
        (m.chain for m in coldest_block.memberships),
        key=lambda chain: (chain_q[chain], chain),
    )
    return cheapest == coldest_chain


def evaluate(
    *,
    run_id: str,
    decision_event_index: int,
    geometry: DecisionGeometry,
    need: int,
) -> DecisionDivergence:
    """Compare the two rules on one decision, keeping gaps and unknowns visible.

    Selection is always computed, because both rules can be run as soon as the legal
    set is known. Cost is computed only when nothing about it is unknown;
    otherwise the selections are retained as diagnostics and no loss comparison is
    reported, so an unscorable decision can never contribute a verified delta.
    """
    native_blocks = native_selection(geometry, need)
    chains = {m.chain for block in geometry.blocks.values() for m in block.memberships}
    # The choice itself is always a fact, so it is computed diagnostically first and
    # never allowed to raise: only the loss is withheld when costs are unknown.
    diagnostic_blocks = cost_aware_selection_diagnostic(geometry, need)
    order_differs = native_blocks != diagnostic_blocks

    # A loss is only meaningful when nothing about the cost is unknown. Computing it
    # on a degraded geometry would produce a number that looks like a measurement
    # while silently treating unknown chains as free, so it is not attempted.
    if not geometry.scorable:
        aware_blocks = diagnostic_blocks
        native_outcome = None
        aware_outcome = None
        costs_computable = False
    else:
        try:
            aware_blocks = cost_aware_selection(geometry, need)
            native_outcome = selection_outcome("native_lru", native_blocks, geometry)
            aware_outcome = selection_outcome("cost_aware_marginal", aware_blocks, geometry)
            costs_computable = True
        except MissingReuseWeight:
            aware_blocks = diagnostic_blocks
            native_outcome = None
            aware_outcome = None
            costs_computable = False

    verified = bool(geometry.scorable and costs_computable)
    return DecisionDivergence(
        run_id=run_id,
        decision_event_index=decision_event_index,
        need=need,
        legal_count=len(geometry.blocks),
        shared_block_count=geometry.shared_block_count,
        chain_count=len(chains),
        order_differs=order_differs,
        victim_set_differs=set(native_blocks) != set(aware_blocks),
        native=native_outcome,
        cost_aware=aware_outcome,
        q_order_agrees_with_rank=q_order_agrees(geometry),
        scorable=geometry.scorable,
        verified=verified,
        gaps=dict(geometry.gaps),
        native_blocks=native_blocks,
        cost_aware_blocks=aware_blocks,
        unknown_weight_chains=geometry.unknown_weight_chains,
    )


def reuse_proxy(deadline: float, timestamp: float, tau_seconds: float) -> float:
    """``sigmoid((deadline - t) / tau)``, the same proxy A1 uses."""
    return 1.0 / (1.0 + math.exp(-(deadline - timestamp) / tau_seconds))
