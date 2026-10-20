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

from .a2_geometry import (
    GAP_CONTENT_UNVERIFIED,
    ChainKey,
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from .a2_selector import (
    FALLBACK_CONTRACT_INVALID,
    SELECTOR_NATIVE_FALLBACK,
    A2BlockSelector,
    A2Config,
    VictimSelection,
)

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
        "for APC lookup. Must be non-empty for every hash-carrying membership, and all "
        "memberships of one physical block must report the same value: a block cannot "
        "be two different contents at once. A block whose memberships disagree is "
        "malformed input, not a verified shared block.",
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
        invalidated_by=(
            "followup admission, program completion, or a later retention fact; "
            "logical release alone does not erase the decision-time future-demand fact"
        ),
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
        gap and the selector will fall back to native LRU rather than guess. A block
        whose memberships carry conflicting content identities is treated the same
        way: physical identity failed closed, so it must never be scored even if the
        caller skipped :func:`validate_request`.
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
            if item.has_block_hash and (not item.memberships or _identity_problems(item)):
                gaps[item.block_id] = GAP_CONTENT_UNVERIFIED
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


def _identity_problems(item: BlockDecisionInput) -> tuple[str, ...]:
    """Content-identity defects of one block, as plain strings.

    Two failure modes, both of which would otherwise let a malformed block be treated
    as a verified shared block and scored:

    - a hash-carrying membership with an empty content hash claims an identity it does
      not have;
    - memberships of the same physical block disagree on the content hash, which is
      impossible for one slot and means the input is wrong, not merely ambiguous.
    """
    if not item.has_block_hash:
        return ()
    problems: list[str] = []
    hashes: set[str] = set()
    for membership in item.memberships:
        digest = (membership.content_hash or "").strip()
        if not digest:
            problems.append(
                f"block {item.block_id} membership in chain "
                f"{membership.chain!r} at depth {membership.depth} has an empty "
                f"content hash"
            )
            continue
        hashes.add(digest)
    if len(hashes) > 1:
        problems.append(
            f"block {item.block_id} reports conflicting content hashes "
            f"{sorted(hashes)} across its memberships"
        )
    return tuple(problems)


def validate_request(request: DecisionRequest) -> tuple[str, ...]:
    """Return contract violations as plain strings; empty means the request is valid.

    Deliberately non-throwing so the engine can log and fall back instead of crashing
    the scheduler on a malformed input. Any non-empty result means the decision must
    **not** enter cost scoring: the caller logs the reasons and uses native LRU (see
    :func:`decide`).
    """
    problems: list[str] = []
    if request.required_blocks < 0:
        problems.append("required_blocks must be non-negative")
    if not request.blocks:
        problems.append("no legal blocks supplied")

    seen: set[int] = set()
    #: (chain, depth) -> content hash, to catch one chain position claiming two
    #: different contents across different physical blocks.
    slot_hash: dict[tuple[ChainKey, int], str] = {}
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
        problems.extend(_identity_problems(item))
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
            digest = (membership.content_hash or "").strip()
            if not digest:
                continue
            slot = (membership.chain, membership.depth)
            claimed = slot_hash.get(slot)
            if claimed is None:
                slot_hash[slot] = digest
            elif claimed != digest:
                problems.append(
                    f"chain {membership.chain!r} depth {membership.depth} is claimed "
                    f"with incompatible content hashes {sorted({claimed, digest})} by "
                    f"block {item.block_id}"
                )
    for chain, weight in request.reuse_weight.items():
        if not 0.0 < weight <= 1.0:
            problems.append(f"reuse weight for {chain!r} outside (0, 1]: {weight}")
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """A selection plus the contract verdict that produced it."""

    selection: VictimSelection
    problems: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        """``True`` when the request failed the contract and never reached scoring."""
        return bool(self.problems)


def decide(
    request: DecisionRequest,
    *,
    config: A2Config | None = None,
) -> DecisionOutcome:
    """The prescribed adapter path: validate first, score only if the input is valid.

    A request that violates the contract is **never** scored. The reasons are returned
    in ``problems`` for the caller to log, and the victim set is native LRU order over
    the **distinct** legal block ids restricted to ``required_blocks`` -- the same
    fallback the selector uses for unverifiable content, so no malformed input can
    change a decision. Duplicate ids are collapsed by :func:`_fail_closed_victims`, so
    an invalid request can never produce a victim list naming one block twice.
    """
    problems = validate_request(request)
    if problems:
        return DecisionOutcome(
            selection=VictimSelection(
                blocks=_fail_closed_victims(request),
                selector=SELECTOR_NATIVE_FALLBACK,
                proxy_weighted_loss=None,
                cost_known=False,
                fallbacks=(FALLBACK_CONTRACT_INVALID,),
            ),
            problems=problems,
        )
    selector = A2BlockSelector(config or A2Config())
    return DecisionOutcome(
        selection=selector.select(request.to_geometry(), request.required_blocks)
    )


def _fail_closed_victims(request: DecisionRequest) -> tuple[int, ...]:
    """Native LRU victims for a request that failed the contract.

    A victim list must name **distinct physical blocks**: returning the same
    ``block_id`` twice would tell the engine to evict one block and then evict it
    again, so the count would overstate how much was freed. ``validate_request``
    reports duplicate ids, but the fallback still has to cope with them, because the
    fallback is the one path that runs *on* invalid input.

    Policy, deterministic and independent of input order:

    1. rank each block by ``(native_rank, block_id)`` -- the frozen engine order;
    2. collapse equal ``block_id`` records onto their smallest such key, so a
       duplicate never displaces the colder record;
    3. take the first ``required_blocks`` of the surviving distinct ids.

    The result is therefore truncated at the number of **distinct** candidates, which
    may be fewer than ``required_blocks``. Reporting a short count is honest; padding
    it with a repeat would not be.
    """
    chosen_key: dict[int, tuple[int, int]] = {}
    for item in request.blocks:
        key = (item.native_rank, item.block_id)
        best = chosen_key.get(item.block_id)
        if best is None or key < best:
            chosen_key[item.block_id] = key
    ordered = sorted(chosen_key.items(), key=lambda pair: pair[1])
    need = max(0, min(request.required_blocks, len(ordered)))
    return tuple(block_id for block_id, _ in ordered[:need])


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
