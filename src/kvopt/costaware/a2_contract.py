"""Frozen decision-time contract between A2 and the native engine (for M6).

Purpose
-------
This module is the interface A2 needs at eviction time, expressed as data the engine
can populate. It is deliberately separate from the existing
``runtime.vllm.EvictionCandidate`` / ``EvictionContext`` types, which A2 extends
rather than replaces: nothing here changes Native BlockPool ownership, ref-counting,
hash cleanup, the free-block queue, or request lifecycle.

Two facts drive the whole contract
----------------------------------
1. **``block_id`` is a recyclable physical slot.** It proves nothing about content.
   A slot that held prefix content at time ``t0`` may hold different content later, so
   any content claim must carry an explicit validity window and an invalidation rule.
2. **``native_lru_rank`` is recency, not prefix depth.** Depth is a position in the
   request's content, so it must come from the hash chain, not from the queue order.

Field classification
--------------------
``ALREADY_AVAILABLE``     readable today from the engine or from Continuum state
``DERIVED_IN_ENGINE``     computable inside the engine from state it already owns
``NEEDS_EXPOSURE``        must be added by M6 for A2 to run at all
``EVALUATION_ONLY``       post-decision truth; must never reach an online decision
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .a2_geometry import ChainKey, DecisionGeometry, LegalBlock, Membership

#: Field-provenance labels.
ALREADY_AVAILABLE = "already_available"
DERIVED_IN_ENGINE = "derived_in_engine"
NEEDS_EXPOSURE = "needs_exposure"
EVALUATION_ONLY = "evaluation_only"


@dataclass(frozen=True, slots=True)
class FieldContract:
    """One field A2 consumes, with where it comes from and how long it is valid."""

    name: str
    provenance: str
    description: str
    #: How long the value stays true once produced.
    validity: str = ""
    #: What makes a previously valid value unusable.
    invalidated_by: str = ""


#: The complete set of fields A2 reads. Reviewed as the frozen contract.
FIELD_CONTRACT: tuple[FieldContract, ...] = (
    FieldContract(
        "block_id",
        ALREADY_AVAILABLE,
        "Physical slot identifier of a free-queue block.",
        validity="valid only while the slot is not reallocated",
        invalidated_by=(
            "slot reuse: the id names a location, not content, so it must always be "
            "paired with a content hash before it can be used"
        ),
    ),
    FieldContract(
        "has_block_hash",
        ALREADY_AVAILABLE,
        "False when the block carries no prefix content. Such a block is free to "
        "evict: zero recomputation, no chain membership needed.",
    ),
    FieldContract(
        "native_lru_rank",
        ALREADY_AVAILABLE,
        "Position in the native free queue. Used ONLY as a recency tie-break and as "
        "the native comparator. Never interpreted as prefix depth.",
    ),
    FieldContract(
        "required_blocks",
        ALREADY_AVAILABLE,
        "Frozen pressure target: how many blocks this decision must free.",
    ),
    FieldContract(
        "decision_timestamp",
        ALREADY_AVAILABLE,
        "Clock reading at the decision, used to evaluate the reuse proxy.",
    ),
    FieldContract(
        "content_hash",
        NEEDS_EXPOSURE,
        "Content identity of the block's hash chain entry, same value the engine uses "
        "for APC lookup.",
        validity="until the slot is reallocated or the hash entry is evicted",
        invalidated_by=(
            "a hashed-cache eviction of that slot by the same hash process, or a later "
            "snapshot showing different content"
        ),
    ),
    FieldContract(
        "prefix_depth",
        DERIVED_IN_ENGINE,
        "1-based position of the block within its own chain's hash sequence. "
        "Derivable in-engine from the block's position in the request prefix; must NOT "
        "be inferred from native_lru_rank.",
        validity="as long as the request's prefix chain is unchanged",
        invalidated_by="prefix truncation or request completion",
    ),
    FieldContract(
        "chain_id",
        DERIVED_IN_ENGINE,
        "Identity of a prefix chain containing the block, e.g. (program_id, "
        "prefix_id). A block may belong to several chains, and every membership must "
        "be reported: collapsing to one chain understates the loss.",
    ),
    FieldContract(
        "chain_length",
        DERIVED_IN_ENGINE,
        "Number of blocks in that chain, i.e. m_c. Needed for the suffix length.",
    ),
    FieldContract(
        "reuse_weight",
        NEEDS_EXPOSURE,
        "q_c in (0, 1], the decision-time reuse proxy for a chain. Derived from "
        "Continuum retention state (TTL deadline, program history), not from any "
        "future outcome. A chain with content but no weight makes the decision "
        "unscorable rather than free.",
        validity="must be recomputed at each decision from current retention state",
        invalidated_by="retention entry release, expiry, or program completion",
    ),
    FieldContract(
        "observed_recomputed_tokens",
        EVALUATION_ONLY,
        "Post-decision measurement. Used only to evaluate a campaign; never an input.",
    ),
    FieldContract(
        "returned_after_decision",
        EVALUATION_ONLY,
        "Post-decision truth about whether a chain returned. Evaluation only.",
    ),
)


@dataclass(frozen=True, slots=True)
class BlockDecisionInput:
    """One legal block as the engine must present it to A2."""

    block_id: int
    native_rank: int
    has_block_hash: bool = True
    #: Required when ``has_block_hash`` is True; omitted when False.
    memberships: tuple[Membership, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """The complete decision-time input for one eviction decision."""

    required_blocks: int
    timestamp: float
    blocks: tuple[BlockDecisionInput, ...]
    chain_length: dict[ChainKey, int] = field(default_factory=dict)
    reuse_weight: dict[ChainKey, float] = field(default_factory=dict)

    def to_geometry(self) -> DecisionGeometry:
        """Build the cost model's input, marking anything unproved as a gap.

        A hash-carrying block with no membership cannot be priced, so it becomes a
        gap and the selector will fall back to native LRU rather than guess.
        """
        blocks: dict[int, LegalBlock] = {}
        gaps: dict[int, str] = {}
        unknown_weight_chains: set[ChainKey] = set()

        for item in self.blocks:
            blocks[item.block_id] = LegalBlock(
                block_id=item.block_id,
                native_rank=item.native_rank,
                memberships=item.memberships,
                has_block_hash=item.has_block_hash,
            )
            if item.has_block_hash and not item.memberships:
                gaps[item.block_id] = "content_unverified"
            for membership in item.memberships:
                if membership.chain not in self.reuse_weight:
                    unknown_weight_chains.add(membership.chain)

        return DecisionGeometry(
            blocks=blocks,
            chain_length=dict(self.chain_length),
            q_by_chain={
                chain: weight for chain, weight in self.reuse_weight.items()
            },
            gaps=gaps,
            unknown_weight_chains=tuple(sorted(unknown_weight_chains)),
        )


def validate_request(request: DecisionRequest) -> tuple[str, ...]:
    """Return contract violations as plain strings; empty means the request is valid.

    Deliberately non-throwing so the engine can log and fall back instead of crashing
    the scheduler on a malformed input.
    """
    problems: list[str] = []
    if request.required_blocks < 0:
        problems.append("required_blocks must be non-negative")
    if not request.blocks:
        problems.append("no legal blocks supplied")

    seen: set[int] = set()
    for item in request.blocks:
        if item.block_id in seen:
            problems.append(f"duplicate block id {item.block_id}")
        seen.add(item.block_id)
        if item.native_rank < 0:
            problems.append(f"negative native rank for block {item.block_id}")
        if not item.has_block_hash and item.memberships:
            problems.append(
                f"block {item.block_id} is hashless but claims chain memberships"
            )
        for membership in item.memberships:
            if membership.depth < 1:
                problems.append(
                    f"block {item.block_id} has depth {membership.depth} < 1"
                )
            if membership.chain not in request.chain_length:
                problems.append(
                    f"block {item.block_id} references chain "
                    f"{membership.chain!r} with unknown length"
                )
            elif membership.depth > request.chain_length[membership.chain]:
                problems.append(
                    f"block {item.block_id} depth {membership.depth} exceeds chain "
                    f"{membership.chain!r} length "
                    f"{request.chain_length[membership.chain]}"
                )
    for chain, weight in request.reuse_weight.items():
        if not 0.0 < weight <= 1.0:
            problems.append(f"reuse weight for {chain!r} outside (0, 1]: {weight}")
    return tuple(problems)


def fields_needing_exposure() -> tuple[FieldContract, ...]:
    """The fields M6 must add, i.e. what is missing today."""
    return tuple(
        field for field in FIELD_CONTRACT if field.provenance == NEEDS_EXPOSURE
    )


def evaluation_only_fields() -> tuple[FieldContract, ...]:
    """Fields that must never reach an online decision."""
    return tuple(
        field for field in FIELD_CONTRACT if field.provenance == EVALUATION_ONLY
    )


def fields_by_provenance(provenance: str) -> tuple[FieldContract, ...]:
    return tuple(
        field for field in FIELD_CONTRACT if field.provenance == provenance
    )


def assert_no_evaluation_fields(names: Sequence[str]) -> None:
    """Guard used by tests and by any adapter: forbid post-decision inputs."""
    forbidden = {field.name for field in evaluation_only_fields()}
    leaked = forbidden.intersection(names)
    if leaked:
        raise ValueError(
            f"post-decision fields must not be decision inputs: {sorted(leaked)}"
        )
