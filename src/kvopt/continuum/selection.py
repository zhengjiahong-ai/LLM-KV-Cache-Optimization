"""Immutable eligibility and selection-plan contracts for Phase 1B."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .types import (
    BlockIdentity,
    PrefixIdentity,
    ProgramIdentity,
    _as_non_negative_finite_float,
    _require_identity,
    _require_non_empty_text,
)


def _require_boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _normalize_ordered_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (set, frozenset)) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return tuple(value)


def _normalize_typed_unique_tuple(
    value: object,
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    items = _normalize_ordered_tuple(value, field_name)
    for item in items:
        if not isinstance(item, expected_type):
            raise TypeError(f"{field_name} item must be {expected_type.__name__}")
    if len(items) != len(set(items)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return items


class EligibilityTier(IntEnum):
    """Explicit virtual selection tier; not a replacement native LRU rank."""

    TIER_1 = 0
    TIER_2 = 1


@dataclass(frozen=True, slots=True)
class RetentionEntryKey:
    """Stable identity of the logical pressure-release unit."""

    program_id: ProgramIdentity
    prefix_id: PrefixIdentity

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.prefix_id, PrefixIdentity, "prefix_id")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.program_id.value, self.prefix_id.canonical_value)


@dataclass(frozen=True, slots=True)
class BlockEligibilitySnapshot:
    """One block's native rank plus separate retention eligibility metadata."""

    block_id: BlockIdentity
    native_lru_rank: int
    has_block_hash: bool
    eligibility_tier: EligibilityTier | None

    def __post_init__(self) -> None:
        _require_identity(self.block_id, BlockIdentity, "block_id")
        _require_non_negative_int(self.native_lru_rank, "native_lru_rank")
        _require_boolean(self.has_block_hash, "has_block_hash")
        if self.eligibility_tier is not None and not isinstance(
            self.eligibility_tier, EligibilityTier
        ):
            raise TypeError("eligibility_tier must be EligibilityTier or None")
        if not self.has_block_hash and self.eligibility_tier is None:
            raise ValueError("unhashed free block must be eligible in Tier 1")
        if not self.has_block_hash and self.eligibility_tier is not EligibilityTier.TIER_1:
            raise ValueError("unhashed free block must remain in Tier 1")

    @property
    def eligible(self) -> bool:
        return self.eligibility_tier is not None

    @property
    def selection_key(self) -> tuple[int, int] | None:
        if self.eligibility_tier is None:
            return None
        return (int(self.eligibility_tier), self.native_lru_rank)


@dataclass(frozen=True, slots=True)
class PressureReleaseEffect:
    """One planned logical release and its marginally eligible physical blocks."""

    entry_key: RetentionEntryKey
    newly_eligible_block_ids: tuple[BlockIdentity, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entry_key, RetentionEntryKey):
            raise TypeError("entry_key must be RetentionEntryKey")
        block_ids = _normalize_typed_unique_tuple(
            self.newly_eligible_block_ids,
            BlockIdentity,
            "newly_eligible_block_ids",
        )
        object.__setattr__(self, "newly_eligible_block_ids", block_ids)


@dataclass(frozen=True, slots=True)
class EligibilityPreparation:
    """Pure coordinator output over one complete native free-queue snapshot."""

    required_blocks: int
    original_free_queue: tuple[BlockEligibilitySnapshot, ...]
    ordinary_expired_entries: tuple[RetentionEntryKey, ...]
    pressure_releases: tuple[PressureReleaseEffect, ...]
    preparation_timestamp: float

    def __post_init__(self) -> None:
        _require_non_negative_int(self.required_blocks, "required_blocks")
        queue = _normalize_typed_unique_tuple(
            self.original_free_queue,
            BlockEligibilitySnapshot,
            "original_free_queue",
        )
        block_ids = tuple(candidate.block_id for candidate in queue)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("original_free_queue must not contain duplicate block IDs")
        expected_ranks = tuple(range(len(queue)))
        actual_ranks = tuple(candidate.native_lru_rank for candidate in queue)
        if actual_ranks != expected_ranks:
            raise ValueError(
                "native_lru_rank must equal position in the complete original free queue"
            )
        expired_entries = _normalize_typed_unique_tuple(
            self.ordinary_expired_entries,
            RetentionEntryKey,
            "ordinary_expired_entries",
        )
        releases = _normalize_typed_unique_tuple(
            self.pressure_releases,
            PressureReleaseEffect,
            "pressure_releases",
        )
        release_keys = tuple(release.entry_key for release in releases)
        if len(release_keys) != len(set(release_keys)):
            raise ValueError("pressure_releases must not repeat an entry key")
        if set(expired_entries).intersection(release_keys):
            raise ValueError("an entry cannot be both ordinarily expired and pressure released")
        tier_2_ids = {
            candidate.block_id
            for candidate in queue
            if candidate.eligibility_tier is EligibilityTier.TIER_2
        }
        effect_ids = [
            block_id
            for release in releases
            for block_id in release.newly_eligible_block_ids
        ]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("a block may become newly eligible in only one pressure release")
        if set(effect_ids) != tier_2_ids:
            raise ValueError(
                "pressure release effects must exactly explain all Tier 2 blocks"
            )
        tier_1_count = sum(
            candidate.eligibility_tier is EligibilityTier.TIER_1
            for candidate in queue
        )
        required_target = min(self.required_blocks, len(queue))
        eligible_so_far = tier_1_count
        for release in releases:
            if eligible_so_far >= required_target:
                raise ValueError(
                    "pressure releases must stop once the target is satisfied"
                )
            eligible_so_far += len(release.newly_eligible_block_ids)
        eligible_count = sum(candidate.eligible for candidate in queue)
        if eligible_count < required_target:
            raise ValueError("eligibility plan cannot satisfy the available-block target")
        timestamp = _as_non_negative_finite_float(
            self.preparation_timestamp, "preparation_timestamp"
        )
        object.__setattr__(self, "original_free_queue", queue)
        object.__setattr__(self, "ordinary_expired_entries", expired_entries)
        object.__setattr__(self, "pressure_releases", releases)
        object.__setattr__(self, "preparation_timestamp", timestamp)

    @property
    def original_block_order(self) -> tuple[BlockIdentity, ...]:
        return tuple(candidate.block_id for candidate in self.original_free_queue)

    @property
    def tier_1_block_ids(self) -> tuple[BlockIdentity, ...]:
        return tuple(
            candidate.block_id
            for candidate in self.original_free_queue
            if candidate.eligibility_tier is EligibilityTier.TIER_1
        )

    @property
    def tier_2_block_ids(self) -> tuple[BlockIdentity, ...]:
        return tuple(
            candidate.block_id
            for candidate in self.original_free_queue
            if candidate.eligibility_tier is EligibilityTier.TIER_2
        )

    @property
    def still_protected_block_ids(self) -> tuple[BlockIdentity, ...]:
        return tuple(
            candidate.block_id
            for candidate in self.original_free_queue
            if candidate.eligibility_tier is None
        )

    @property
    def virtual_eligible_order(self) -> tuple[BlockIdentity, ...]:
        eligible = [candidate for candidate in self.original_free_queue if candidate.eligible]
        eligible.sort(key=lambda candidate: candidate.selection_key)
        return tuple(candidate.block_id for candidate in eligible)


@dataclass(frozen=True, slots=True)
class SelectionPlan:
    """Auditable eligibility preparation plus actual validated adapter output."""

    preparation: EligibilityPreparation
    adapter_identity: str
    selected_block_ids: tuple[BlockIdentity, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.preparation, EligibilityPreparation):
            raise TypeError("preparation must be EligibilityPreparation")
        _require_non_empty_text(self.adapter_identity, "adapter_identity")
        selected = _normalize_typed_unique_tuple(
            self.selected_block_ids,
            BlockIdentity,
            "selected_block_ids",
        )
        virtual_order = self.preparation.virtual_eligible_order
        if selected != virtual_order[: len(selected)]:
            raise ValueError(
                "selected_block_ids must follow (eligibility_tier, native_lru_rank)"
            )
        required_target = min(
            self.preparation.required_blocks,
            len(self.preparation.original_free_queue),
        )
        if len(selected) < required_target:
            raise ValueError("adapter selected too few eligible block IDs")
        object.__setattr__(self, "selected_block_ids", selected)
