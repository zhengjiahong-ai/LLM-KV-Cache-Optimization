"""DVA-ER v1: Downstream-Victim-Aware Entry Release.

The policy is deliberately independent of the historical A1/A3 score
implementations.  It consumes one complete, decision-time Native block-pool
snapshot and one explicit follow-up observation per legal candidate:

* A1/A3 ordering is not an input and is never called;
* A0's order is an explicit tie-break input, not a hidden global;
* the Native LRU victim sequence is simulated from the full BlockPool /
  FreeKVCacheBlockQueue / refcount / protection state;
* missing evidence raises :class:`DVAEREvidenceError`; no zero is substituted;
* no future Turn content or future reuse outcome is accepted.

The module is CPU-only.  It does not touch vLLM, a GPU, a protocol history file
or the Phase 3/4 archives.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeAlias

CandidateKey: TypeAlias = tuple[str, str]

DEFAULT_H_SECONDS = 60.0
SENSITIVITY_H_SECONDS = (30.0, 120.0)


class FollowupGapSource(StrEnum):
    """Allowed observation source for an active pending gap."""

    CONTROLLER_ARMED_TIMER = "CONTROLLER_ARMED_TIMER"


class DVAERError(RuntimeError):
    """Base error for DVA-ER policy or evidence failures."""


class DVAEREvidenceError(DVAERError):
    """The decision cannot be made because required evidence is missing."""


def _finite_non_negative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DVAEREvidenceError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise DVAEREvidenceError(f"{name} must be finite and non-negative")
    return number


def _positive(value: object, name: str) -> float:
    number = _finite_non_negative(value, name)
    if number <= 0.0:
        raise DVAEREvidenceError(f"{name} must be positive")
    return number


def _key(value: object, name: str) -> CandidateKey:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise DVAEREvidenceError(f"{name} must be a (program_id, prefix_id) pair")
    return value


@dataclass(frozen=True, slots=True)
class NativeBlock:
    """One block at the decision boundary.

    ``refcount`` is the observed Native refcount. ``owners`` are logical prefix
    owners and ``protected_owners`` are the independent Retention Protection
    owners. A release removes protection only; it never changes refcount, block
    hash or free queue membership. A block is Native-eligible only when
    refcount is zero and either it is unhashed or no protected owner remains.
    """

    block_id: int
    has_hash: bool
    refcount: int
    native_lru_rank: int
    owners: frozenset[CandidateKey]
    protected_owners: frozenset[CandidateKey] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.block_id, bool) or self.block_id < 0:
            raise DVAEREvidenceError("block_id must be a non-negative integer")
        if not isinstance(self.has_hash, bool):
            raise DVAEREvidenceError("has_hash must be bool")
        if isinstance(self.refcount, bool) or self.refcount < 0:
            raise DVAEREvidenceError("refcount must be a non-negative integer")
        if isinstance(self.native_lru_rank, bool) or self.native_lru_rank < 0:
            raise DVAEREvidenceError("native_lru_rank must be a non-negative integer")
        if not isinstance(self.owners, frozenset) or not all(
            isinstance(key, tuple)
            and len(key) == 2
            and all(isinstance(part, str) and part for part in key)
            for key in self.owners
        ):
            raise DVAEREvidenceError("owners must be a set of candidate keys")
        if not isinstance(self.protected_owners, frozenset) or not (
            self.protected_owners <= self.owners
        ):
            raise DVAEREvidenceError("protected_owners must be a subset of owners")

    @property
    def is_free(self) -> bool:
        return self.refcount == 0


@dataclass(frozen=True, slots=True)
class VictimSequence:
    """A0-compatible eligibility and physical victim selection after release.

    ``original_eligible_block_ids`` is Tier 1; ``newly_eligible_block_ids`` is
    the marginal Tier 2 set.  ``virtual_eligible_order`` is Tier 1 followed by
    Tier 2, each ordered by Native LRU rank.  ``physical_victim_block_ids`` is
    the actual prefix selected from that order, with the same
    ``min(required_blocks, eligible_count)`` limit as the frozen A0 adapter.
    """

    candidate_key: CandidateKey
    required_blocks: int
    original_eligible_block_ids: tuple[int, ...]
    newly_eligible_block_ids: tuple[int, ...]
    virtual_eligible_order: tuple[int, ...]
    physical_victim_block_ids: tuple[int, ...]
    full_free_queue_order: tuple[int, ...]
    shortfall: int

    def __post_init__(self) -> None:
        if isinstance(self.required_blocks, bool) or self.required_blocks < 0:
            raise DVAEREvidenceError("required_blocks must be non-negative")
        if self.shortfall < 0:
            raise DVAEREvidenceError("shortfall must be non-negative")
        if set(self.original_eligible_block_ids) & set(self.newly_eligible_block_ids):
            raise DVAEREvidenceError("Tier 1 and Tier 2 blocks must be disjoint")
        if self.virtual_eligible_order != (
            self.original_eligible_block_ids + self.newly_eligible_block_ids
        ):
            raise DVAEREvidenceError("virtual order must be Tier 1 followed by Tier 2")
        expected_count = min(self.required_blocks, len(self.virtual_eligible_order))
        if self.physical_victim_block_ids != self.virtual_eligible_order[:expected_count]:
            raise DVAEREvidenceError("physical victims must be the virtual-order prefix")
        expected_shortfall = max(0, self.required_blocks - len(self.virtual_eligible_order))
        if self.shortfall != expected_shortfall:
            raise DVAEREvidenceError("shortfall accounting is inconsistent")
        if len(set(self.full_free_queue_order)) != len(self.full_free_queue_order):
            raise DVAEREvidenceError("full free queue contains duplicates")

    @property
    def victim_block_ids(self) -> tuple[int, ...]:
        """Compatibility alias for the actual physical victim prefix."""
        return self.physical_victim_block_ids

    @property
    def full_eligible_sequence(self) -> tuple[int, ...]:
        """Compatibility alias for the full virtual eligible order."""
        return self.virtual_eligible_order


@dataclass(frozen=True, slots=True)
class NativePoolSnapshot:
    """Complete decision-time Native pool evidence.

    All blocks are present, the free queue is complete and exact, and every
    candidate is registered.  The snapshot is immutable; simulation never
    mutates the observed pool.
    """

    blocks: tuple[NativeBlock, ...]
    free_queue_order: tuple[int, ...]
    candidate_keys: tuple[CandidateKey, ...]

    def __post_init__(self) -> None:
        if not self.candidate_keys:
            raise DVAEREvidenceError("at least one legal candidate is required")
        keys = tuple(_key(key, "candidate key") for key in self.candidate_keys)
        if len(set(keys)) != len(keys):
            raise DVAEREvidenceError("candidate keys must be unique")
        if not self.blocks:
            raise DVAEREvidenceError("block pool snapshot is empty")
        block_ids = tuple(block.block_id for block in self.blocks)
        if len(set(block_ids)) != len(block_ids):
            raise DVAEREvidenceError("block IDs must be unique")
        ranks = tuple(block.native_lru_rank for block in self.blocks)
        if len(set(ranks)) != len(ranks):
            raise DVAEREvidenceError("Native LRU ranks must be unique")
        by_id = {block.block_id: block for block in self.blocks}
        for block in self.blocks:
            if not block.owners <= frozenset(keys):
                raise DVAEREvidenceError("block owner is not a legal candidate")
        queue = tuple(self.free_queue_order)
        if len(set(queue)) != len(queue):
            raise DVAEREvidenceError("free queue contains duplicate block IDs")
        if any(block_id not in by_id for block_id in queue):
            raise DVAEREvidenceError("free queue references an unknown block")
        for position, block_id in enumerate(queue):
            if by_id[block_id].native_lru_rank != position:
                raise DVAEREvidenceError("free queue position must equal native_lru_rank")
        free_blocks = {block.block_id for block in self.blocks if block.is_free}
        if set(queue) != free_blocks:
            raise DVAEREvidenceError("free queue must exactly equal the refcount-zero blocks")

    @property
    def candidate_set(self) -> frozenset[CandidateKey]:
        return frozenset(self.candidate_keys)

    def _block_map(self) -> dict[int, NativeBlock]:
        return {block.block_id: block for block in self.blocks}

    def eligible_block_ids(self) -> tuple[int, ...]:
        """Current Native-eligible blocks ordered by Native LRU rank."""
        return tuple(
            block.block_id
            for block in sorted(self.blocks, key=lambda item: item.native_lru_rank)
            if block.is_free and (not block.has_hash or not block.protected_owners)
        )

    def victim_sequence_after(
        self, candidate_key: CandidateKey, required_blocks: int
    ) -> VictimSequence:
        """Reproduce A0 Tier 1/Tier 2 eligibility and physical selection."""
        key = _key(candidate_key, "candidate_key")
        if key not in self.candidate_set:
            raise DVAEREvidenceError("candidate is not in the legal candidate set")
        if isinstance(required_blocks, bool) or required_blocks < 0:
            raise DVAEREvidenceError("required_blocks must be non-negative")

        tier_1 = self.eligible_block_ids()
        tier_1_set = set(tier_1)
        simulated: list[NativeBlock] = []
        for block in self.blocks:
            # Release changes Retention Protection only.  Native refcount, hash
            # and free-queue membership remain exactly as observed.
            simulated.append(
                NativeBlock(
                    block_id=block.block_id,
                    has_hash=block.has_hash,
                    refcount=block.refcount,
                    native_lru_rank=block.native_lru_rank,
                    owners=block.owners,
                    protected_owners=block.protected_owners - {key},
                )
            )
        eligible_after = tuple(
            block.block_id
            for block in sorted(simulated, key=lambda item: item.native_lru_rank)
            if block.is_free and (not block.has_hash or not block.protected_owners)
        )
        tier_2 = tuple(block_id for block_id in eligible_after if block_id not in tier_1_set)
        virtual_order = tier_1 + tier_2
        selected_count = min(required_blocks, len(virtual_order))
        physical = virtual_order[:selected_count]
        return VictimSequence(
            candidate_key=key,
            required_blocks=required_blocks,
            original_eligible_block_ids=tier_1,
            newly_eligible_block_ids=tier_2,
            virtual_eligible_order=virtual_order,
            physical_victim_block_ids=physical,
            full_free_queue_order=self.free_queue_order,
            shortfall=max(0, required_blocks - len(virtual_order)),
        )


@dataclass(frozen=True, slots=True)
class FollowupObservation:
    """Decision-time follow-up state for one candidate.

    ``pending_tool_gap_seconds`` is an already-armed controller timer/next
    arrival, not future Turn content or a future reuse outcome. The chain and
    observation must have been established no later than the decision.
    """

    candidate_key: CandidateKey
    chain_id: str
    active: bool
    pending_tool_gap_seconds: float | None = None
    observed_at_timestamp: float = 0.0
    chain_established_at_timestamp: float = 0.0
    pending_tool_gap_source: FollowupGapSource | None = None

    def __post_init__(self) -> None:
        _key(self.candidate_key, "follow-up candidate key")
        if not isinstance(self.chain_id, str) or not self.chain_id:
            raise DVAEREvidenceError("follow-up chain_id must be non-empty")
        if not isinstance(self.active, bool):
            raise DVAEREvidenceError("follow-up active must be bool")
        observed = _finite_non_negative(
            self.observed_at_timestamp, "follow-up observation timestamp"
        )
        established = _finite_non_negative(
            self.chain_established_at_timestamp, "chain establishment timestamp"
        )
        if established > observed:
            raise DVAEREvidenceError(
                "chain establishment timestamp cannot be after its observation"
            )
        if self.active:
            if self.pending_tool_gap_seconds is None:
                raise DVAEREvidenceError("active follow-up requires an observable pending tool gap")
            _finite_non_negative(self.pending_tool_gap_seconds, "pending tool gap")
            if self.pending_tool_gap_source is not FollowupGapSource.CONTROLLER_ARMED_TIMER:
                raise DVAEREvidenceError(
                    "active follow-up gap must come from the controller-armed timer"
                )
        else:
            if self.pending_tool_gap_seconds is not None:
                raise DVAEREvidenceError("inactive follow-up must not carry a pending tool gap")
            if self.pending_tool_gap_source is not None:
                raise DVAEREvidenceError("inactive follow-up must not carry a gap source")

    def risk_weight(self, h_seconds: float) -> int:
        """1 iff the chain is active and its pending gap is within H."""
        if not self.active or self.pending_tool_gap_seconds is None:
            return 0
        return 1 if self.pending_tool_gap_seconds <= h_seconds else 0


@dataclass(frozen=True, slots=True)
class CandidateLoss:
    candidate_key: CandidateKey
    loss: int
    original_eligible_block_ids: tuple[int, ...]
    newly_eligible_block_ids: tuple[int, ...]
    virtual_eligible_order: tuple[int, ...]
    physical_victim_block_ids: tuple[int, ...]
    full_free_queue_order: tuple[int, ...]
    shortfall: int
    a0_rank: int
    risk_chain_ids: tuple[str, ...] = ()

    @property
    def victim_block_ids(self) -> tuple[int, ...]:
        return self.physical_victim_block_ids

    @property
    def full_eligible_sequence(self) -> tuple[int, ...]:
        return self.virtual_eligible_order


@dataclass(frozen=True, slots=True)
class DVAERDecision:
    decision_id: str
    selected: CandidateKey
    selected_loss: int
    candidate_losses: tuple[CandidateLoss, ...]
    h_seconds: float
    a0_tiebreak_used: bool

    @property
    def selected_candidate(self) -> CandidateLoss:
        return next(row for row in self.candidate_losses if row.candidate_key == self.selected)


@dataclass(frozen=True, slots=True)
class DVAERDecisionInput:
    """All and only the decision-time evidence DVA-ER is allowed to use."""

    decision_id: str
    timestamp: float
    required_blocks: int
    pool: NativePoolSnapshot
    followups: Mapping[CandidateKey, FollowupObservation]
    a0_order: tuple[CandidateKey, ...]
    h_seconds: float = DEFAULT_H_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, str) or not self.decision_id:
            raise DVAEREvidenceError("decision_id must be non-empty")
        _finite_non_negative(self.timestamp, "timestamp")
        if isinstance(self.required_blocks, bool) or self.required_blocks < 0:
            raise DVAEREvidenceError("required_blocks must be non-negative")
        _positive(self.h_seconds, "h_seconds")
        candidates = self.pool.candidate_set
        if set(self.followups) != candidates:
            raise DVAEREvidenceError(
                "exactly one follow-up observation is required per legal candidate"
            )
        for key, observation in self.followups.items():
            if not isinstance(observation, FollowupObservation):
                raise DVAEREvidenceError("follow-up value is not an observation")
            if observation.candidate_key != key:
                raise DVAEREvidenceError("follow-up key does not match its mapping key")
            if observation.chain_established_at_timestamp > self.timestamp:
                raise DVAEREvidenceError("follow-up chain was established after the decision")
            if observation.observed_at_timestamp > self.timestamp:
                raise DVAEREvidenceError("follow-up observation is after the decision")
        if len(set(self.a0_order)) != len(self.a0_order):
            raise DVAEREvidenceError("A0 order contains duplicate candidates")
        if set(self.a0_order) != candidates:
            raise DVAEREvidenceError("A0 order must contain exactly the legal candidate set")


class DVAERStrategy:
    """Deterministic DVA-ER v1 selector.

    The loss is the count of blocks in the candidate's Native victim sequence
    that belong to an active follow-up chain with a pending gap within H.
    ``a0_order`` is used only when losses tie; it is never used to score a
    candidate.
    """

    strategy_id = "DVA_ER_v1"

    def __init__(self, h_seconds: float = DEFAULT_H_SECONDS) -> None:
        self.h_seconds = _positive(h_seconds, "h_seconds")

    def choose(self, decision: DVAERDecisionInput) -> DVAERDecision:
        if decision.h_seconds != self.h_seconds:
            raise DVAEREvidenceError("decision H differs from strategy H")
        a0_rank = {key: index for index, key in enumerate(decision.a0_order)}
        losses: list[CandidateLoss] = []
        for key in decision.pool.candidate_keys:
            sequence = decision.pool.victim_sequence_after(key, decision.required_blocks)
            loss = 0
            risk_chains: set[str] = set()
            for block_id in sequence.victim_block_ids:
                block = next(item for item in decision.pool.blocks if item.block_id == block_id)
                for owner in block.owners:
                    observation = decision.followups[owner]
                    if observation.risk_weight(self.h_seconds):
                        loss += 1
                        risk_chains.add(observation.chain_id)
                        break
            losses.append(
                CandidateLoss(
                    candidate_key=key,
                    loss=loss,
                    original_eligible_block_ids=sequence.original_eligible_block_ids,
                    newly_eligible_block_ids=sequence.newly_eligible_block_ids,
                    virtual_eligible_order=sequence.virtual_eligible_order,
                    physical_victim_block_ids=sequence.physical_victim_block_ids,
                    full_free_queue_order=sequence.full_free_queue_order,
                    shortfall=sequence.shortfall,
                    a0_rank=a0_rank[key],
                    risk_chain_ids=tuple(sorted(risk_chains)),
                )
            )
        if not losses:
            raise DVAEREvidenceError("no candidates to select")
        selected = min(losses, key=lambda row: (row.loss, row.a0_rank, row.candidate_key))
        tied = [row for row in losses if row.loss == selected.loss]
        return DVAERDecision(
            decision_id=decision.decision_id,
            selected=selected.candidate_key,
            selected_loss=selected.loss,
            candidate_losses=tuple(losses),
            h_seconds=self.h_seconds,
            a0_tiebreak_used=len(tied) > 1,
        )


class DVAEREvidenceProvider(Protocol):
    """Builds the complete DVA-ER input at a replay decision boundary."""

    def build(self, remaining: Sequence[object], state: object) -> DVAERDecisionInput: ...


@dataclass(frozen=True, slots=True)
class DVAERReplayStrategy:
    """Adapter to the existing ``ReleaseStrategy``/replay boundary.

    The provider is responsible for obtaining the complete Native pool,
    follow-up observations and explicit A0 order.  It must not synthesize
    missing evidence; the DVA-ER input validators fail closed.
    """

    evidence_provider: DVAEREvidenceProvider
    strategy: DVAERStrategy = field(default_factory=DVAERStrategy)

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    def pick_next(self, remaining: Sequence[object], state: object) -> CandidateKey:
        decision = self.evidence_provider.build(remaining, state)
        return self.strategy.choose(decision).selected


def build_decision_input(
    *,
    snapshot: object,
    blocks: Sequence[NativeBlock],
    followups: Mapping[CandidateKey, FollowupObservation],
    a0_order: Sequence[CandidateKey],
    h_seconds: float = DEFAULT_H_SECONDS,
) -> DVAERDecisionInput:
    """Adapt a frozen ``DecisionSnapshot``-shaped object to DVA-ER.

    ``snapshot`` must expose ``run_id``, ``decision_event_index``, ``timestamp``,
    ``required_blocks``, ``queue`` (blocks with ``block_id``) and
    ``candidate_keys``.  Full block records and follow-ups are supplied
    explicitly; missing records fail closed in the dataclass validators.
    """

    run_id = getattr(snapshot, "run_id", None)
    event_index = getattr(snapshot, "decision_event_index", None)
    timestamp = getattr(snapshot, "timestamp", None)
    required_blocks = getattr(snapshot, "required_blocks", None)
    queue = getattr(snapshot, "queue", None)
    candidate_keys = getattr(snapshot, "candidate_keys", None)
    if not isinstance(run_id, str) or not run_id:
        raise DVAEREvidenceError("snapshot.run_id is required")
    if not isinstance(event_index, int) or isinstance(event_index, bool):
        raise DVAEREvidenceError("snapshot.decision_event_index is required")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        raise DVAEREvidenceError("snapshot.timestamp is required")
    if not isinstance(required_blocks, int) or isinstance(required_blocks, bool):
        raise DVAEREvidenceError("snapshot.required_blocks is required")
    if not isinstance(queue, Sequence) or isinstance(queue, (str, bytes)):
        raise DVAEREvidenceError("snapshot.queue is required")
    if not isinstance(candidate_keys, Sequence) or isinstance(candidate_keys, (str, bytes)):
        raise DVAEREvidenceError("snapshot.candidate_keys is required")
    queue_ids = tuple(getattr(block, "block_id", None) for block in queue)
    if any(not isinstance(block_id, int) or isinstance(block_id, bool) for block_id in queue_ids):
        raise DVAEREvidenceError("snapshot.queue contains a block without block_id")
    return DVAERDecisionInput(
        decision_id=f"{run_id}:{event_index}",
        timestamp=float(timestamp),
        required_blocks=required_blocks,
        pool=NativePoolSnapshot(
            blocks=tuple(blocks),
            free_queue_order=queue_ids,
            candidate_keys=tuple(candidate_keys),
        ),
        followups=followups,
        a0_order=tuple(a0_order),
        h_seconds=h_seconds,
    )
