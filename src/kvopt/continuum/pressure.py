"""Pure retention-aware pressure planning for the Phase 1B baseline."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .selection import (
    BlockEligibilitySnapshot,
    EligibilityPreparation,
    EligibilityTier,
    PressureReleaseEffect,
    RetentionEntryKey,
)
from .snapshots import RetentionEntrySnapshot
from .types import BlockIdentity, _as_non_negative_finite_float


class _CandidateLike(Protocol):
    """Minimal ranked candidate shape accepted from a runtime bridge."""

    block_id: int
    has_block_hash: bool
    lru_rank: int


@dataclass(frozen=True, slots=True)
class _CandidateState:
    block_id: BlockIdentity
    has_block_hash: bool
    native_lru_rank: int


class RetentionAwareSelectionCoordinator:
    """Prepare immutable eligibility and pressure-release decisions.

    The coordinator only reasons over candidate and retention snapshots. It
    does not mutate the live retention manager, native queue, or block state.
    """

    def prepare(
        self,
        candidates: Sequence[_CandidateLike],
        retention_entries: Sequence[RetentionEntrySnapshot],
        *,
        required_blocks: int,
        timestamp: float,
    ) -> EligibilityPreparation:
        states = self._normalize_candidates(candidates)
        required = self._require_non_negative_int(required_blocks, "required_blocks")
        now = _as_non_negative_finite_float(timestamp, "timestamp")
        entries = self._normalize_entries(retention_entries)
        entries_by_block = self._entries_by_block(entries)

        ordinary_expired = tuple(
            key
            for key, entry in entries.items()
            if entry.protected
            and not entry.waiting_followup
            and entry.deadline_timestamp <= now
        )
        released_keys = set(ordinary_expired)
        target = min(required, len(states))
        # Tier 1 is eligibility that exists before any pressure release:
        # unhashed blocks and blocks whose protection has already expired.
        tier_1_ids = self._eligible_block_ids(
            states,
            entries,
            entries_by_block,
            released_keys,
        )
        tier_2_ids: set[BlockIdentity] = set()

        pressure_releases: list[PressureReleaseEffect] = []
        while len(tier_1_ids | tier_2_ids) < target:
            candidates_for_release = [
                (key, entry)
                for key, entry in entries.items()
                if entry.protected and key not in released_keys
            ]
            if not candidates_for_release:
                raise ValueError("retention entries cannot satisfy pressure target")

            ranked_releases = sorted(
                candidates_for_release,
                key=lambda item: self._release_sort_key(
                    item[0],
                    item[1],
                    states,
                    entries,
                    entries_by_block,
                    released_keys,
                ),
            )
            key, _entry = ranked_releases[0]
            newly_eligible = self._newly_eligible_blocks_after_release(
                key,
                states,
                entries,
                entries_by_block,
                released_keys,
            )
            released_keys.add(key)
            pressure_releases.append(
                PressureReleaseEffect(key, tuple(newly_eligible))
            )
            tier_2_ids.update(newly_eligible)
        snapshots = tuple(
            BlockEligibilitySnapshot(
                block_id=state.block_id,
                native_lru_rank=state.native_lru_rank,
                has_block_hash=state.has_block_hash,
                eligibility_tier=(
                    EligibilityTier.TIER_1
                    if state.block_id in tier_1_ids
                    else EligibilityTier.TIER_2
                    if state.block_id in tier_2_ids
                    else None
                ),
            )
            for state in states
        )
        return EligibilityPreparation(
            required_blocks=required,
            original_free_queue=snapshots,
            ordinary_expired_entries=ordinary_expired,
            pressure_releases=tuple(pressure_releases),
            preparation_timestamp=now,
        )

    @staticmethod
    def _normalize_candidates(
        candidates: Sequence[_CandidateLike],
    ) -> tuple[_CandidateState, ...]:
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise TypeError("candidates must be an ordered sequence")
        states: list[_CandidateState] = []
        seen: set[BlockIdentity] = set()
        for index, candidate in enumerate(candidates):
            block_id = BlockIdentity(candidate.block_id)
            if block_id in seen:
                raise ValueError("candidates must not contain duplicate block IDs")
            seen.add(block_id)
            if not isinstance(candidate.has_block_hash, bool):
                raise TypeError("candidate has_block_hash must be bool")
            if (
                isinstance(candidate.lru_rank, bool)
                or not isinstance(candidate.lru_rank, int)
                or candidate.lru_rank != index
            ):
                raise ValueError(
                    "candidate native_lru_rank must match complete queue position"
                )
            states.append(
                _CandidateState(block_id, candidate.has_block_hash, candidate.lru_rank)
            )
        return tuple(states)

    @staticmethod
    def _normalize_entries(
        retention_entries: Sequence[RetentionEntrySnapshot],
    ) -> dict[RetentionEntryKey, RetentionEntrySnapshot]:
        if isinstance(retention_entries, (str, bytes)) or not isinstance(
            retention_entries, Sequence
        ):
            raise TypeError("retention_entries must be an ordered sequence")
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot] = {}
        for entry in retention_entries:
            if not isinstance(entry, RetentionEntrySnapshot):
                raise TypeError("retention entry must be RetentionEntrySnapshot")
            key = RetentionEntryKey(entry.program_id, entry.prefix_id)
            if key in entries:
                raise ValueError("retention_entries must not repeat an entry key")
            entries[key] = entry
        return entries

    @staticmethod
    def _entries_by_block(
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
    ) -> dict[BlockIdentity, tuple[RetentionEntryKey, ...]]:
        owners: dict[BlockIdentity, list[RetentionEntryKey]] = {}
        for key, entry in entries.items():
            for block_id in entry.block_ids:
                owners.setdefault(block_id, []).append(key)
        return {block_id: tuple(keys) for block_id, keys in owners.items()}

    @staticmethod
    def _require_non_negative_int(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be int")
        if value < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return value

    @staticmethod
    def _entry_remains_protected(
        key: RetentionEntryKey,
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        released_keys: set[RetentionEntryKey],
    ) -> bool:
        entry = entries[key]
        return entry.protected and key not in released_keys

    def _eligible_block_ids(
        self,
        states: tuple[_CandidateState, ...],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
    ) -> set[BlockIdentity]:
        eligible: set[BlockIdentity] = set()
        for state in states:
            if not state.has_block_hash:
                eligible.add(state.block_id)
                continue
            owners = entries_by_block.get(state.block_id, ())
            if not any(
                self._entry_remains_protected(key, entries, released_keys)
                for key in owners
            ):
                eligible.add(state.block_id)
        return eligible

    def _newly_eligible_blocks_after_release(
        self,
        key: RetentionEntryKey,
        states: tuple[_CandidateState, ...],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
    ) -> tuple[BlockIdentity, ...]:
        before = self._eligible_block_ids(
            states, entries, entries_by_block, released_keys
        )
        after = self._eligible_block_ids(
            states, entries, entries_by_block, released_keys | {key}
        )
        return tuple(
            state.block_id
            for state in states
            if state.block_id in after and state.block_id not in before
        )

    def _release_sort_key(
        self,
        key: RetentionEntryKey,
        entry: RetentionEntrySnapshot,
        states: tuple[_CandidateState, ...],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
    ) -> tuple[float, float, tuple[str, str]]:
        newly_eligible = self._newly_eligible_blocks_after_release(
            key,
            states,
            entries,
            entries_by_block,
            released_keys,
        )
        ranks = {
            state.block_id: state.native_lru_rank
            for state in states
        }
        native_key = min(
            (ranks[block_id] for block_id in newly_eligible),
            default=math.inf,
        )
        return (entry.deadline_timestamp, native_key, key.sort_key)
