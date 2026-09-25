"""Read-only Phase 2 observations for Continuum forced-release decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kvopt.continuum.selection import (
    EligibilityPreparation,
    PressureReleaseEffect,
    RetentionEntryKey,
)
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import BlockIdentity, _as_non_negative_finite_float


def _normalize_block_ids(
    value: tuple[BlockIdentity, ...],
    field_name: str,
) -> tuple[BlockIdentity, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be tuple")
    if not all(isinstance(block_id, BlockIdentity) for block_id in value):
        raise TypeError(f"{field_name} items must be BlockIdentity")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return value


@dataclass(frozen=True, slots=True)
class ForcedReleaseCandidateSnapshot:
    """Decision-time facts for one protected logical release candidate.

    Every field is available before the forced-release decision. Future reuse,
    return time, recomputation actually incurred, and downstream latency are
    intentionally excluded from this contract.
    """

    entry_key: RetentionEntryKey
    retention_deadline_timestamp: float
    waiting_followup: bool
    block_ids: tuple[BlockIdentity, ...]
    initially_reclaimable_block_ids: tuple[BlockIdentity, ...]
    next_tool_type: str | None
    elapsed_since_ttl_decision_seconds: float
    prefill_reload_seconds: float
    eta: float
    queue_delay_t_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.entry_key, RetentionEntryKey):
            raise TypeError("entry_key must be RetentionEntryKey")
        deadline = _as_non_negative_finite_float(
            self.retention_deadline_timestamp,
            "retention_deadline_timestamp",
        )
        if not isinstance(self.waiting_followup, bool):
            raise TypeError("waiting_followup must be bool")
        block_ids = _normalize_block_ids(self.block_ids, "block_ids")
        reclaimable = _normalize_block_ids(
            self.initially_reclaimable_block_ids,
            "initially_reclaimable_block_ids",
        )
        if not set(reclaimable).issubset(block_ids):
            raise ValueError(
                "initially_reclaimable_block_ids must belong to the entry"
            )
        if self.next_tool_type is not None and (
            not isinstance(self.next_tool_type, str) or not self.next_tool_type.strip()
        ):
            raise ValueError("next_tool_type must be non-empty text or None")
        elapsed = _as_non_negative_finite_float(
            self.elapsed_since_ttl_decision_seconds,
            "elapsed_since_ttl_decision_seconds",
        )
        prefill = _as_non_negative_finite_float(
            self.prefill_reload_seconds,
            "prefill_reload_seconds",
        )
        if isinstance(self.eta, bool) or not isinstance(self.eta, (int, float)):
            raise TypeError("eta must be a real number")
        eta = float(self.eta)
        if eta != eta or eta in (float("inf"), float("-inf")):
            raise ValueError("eta must be finite")
        queue_delay = _as_non_negative_finite_float(
            self.queue_delay_t_seconds,
            "queue_delay_t_seconds",
        )
        object.__setattr__(self, "retention_deadline_timestamp", deadline)
        object.__setattr__(self, "block_ids", block_ids)
        object.__setattr__(self, "initially_reclaimable_block_ids", reclaimable)
        object.__setattr__(self, "elapsed_since_ttl_decision_seconds", elapsed)
        object.__setattr__(self, "prefill_reload_seconds", prefill)
        object.__setattr__(self, "eta", eta)
        object.__setattr__(self, "queue_delay_t_seconds", queue_delay)


@dataclass(frozen=True, slots=True)
class ForcedReleaseDecisionSnapshot:
    """Immutable observation of one forced protected-cache release decision."""

    preparation: EligibilityPreparation
    candidates: tuple[ForcedReleaseCandidateSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.preparation, EligibilityPreparation):
            raise TypeError("preparation must be EligibilityPreparation")
        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be tuple")
        if not all(
            isinstance(candidate, ForcedReleaseCandidateSnapshot)
            for candidate in self.candidates
        ):
            raise TypeError(
                "candidates items must be ForcedReleaseCandidateSnapshot"
            )
        keys = tuple(candidate.entry_key for candidate in self.candidates)
        if len(keys) != len(set(keys)):
            raise ValueError("candidates must not repeat an entry key")

    @property
    def timestamp(self) -> float:
        return self.preparation.preparation_timestamp

    @property
    def required_blocks(self) -> int:
        return self.preparation.required_blocks

    @property
    def selected_releases(self) -> tuple[PressureReleaseEffect, ...]:
        return self.preparation.pressure_releases


class ForcedReleaseObserver(Protocol):
    """Read-only sink for decision-time forced-release observations."""

    def observe(self, snapshot: ForcedReleaseDecisionSnapshot) -> None:
        """Record one immutable decision snapshot."""


class NullForcedReleaseObserver:
    """Default observer that leaves baseline behavior and state untouched."""

    def observe(self, snapshot: ForcedReleaseDecisionSnapshot) -> None:
        if not isinstance(snapshot, ForcedReleaseDecisionSnapshot):
            raise TypeError("snapshot must be ForcedReleaseDecisionSnapshot")


class InMemoryForcedReleaseObserver:
    """Small deterministic sink for tests and profiling harnesses."""

    def __init__(self) -> None:
        self._snapshots: list[ForcedReleaseDecisionSnapshot] = []

    def observe(self, snapshot: ForcedReleaseDecisionSnapshot) -> None:
        if not isinstance(snapshot, ForcedReleaseDecisionSnapshot):
            raise TypeError("snapshot must be ForcedReleaseDecisionSnapshot")
        self._snapshots.append(snapshot)

    def snapshot(self) -> tuple[ForcedReleaseDecisionSnapshot, ...]:
        return tuple(self._snapshots)


def build_forced_release_snapshot(
    preparation: EligibilityPreparation,
    retention_entries: tuple[RetentionEntrySnapshot, ...],
    initially_reclaimable_by_entry: dict[
        RetentionEntryKey, tuple[BlockIdentity, ...]
    ],
) -> ForcedReleaseDecisionSnapshot:
    """Build the observation from facts already available at decision time."""

    if not isinstance(preparation, EligibilityPreparation):
        raise TypeError("preparation must be EligibilityPreparation")
    if not isinstance(retention_entries, tuple):
        raise TypeError("retention_entries must be tuple")

    candidates: list[ForcedReleaseCandidateSnapshot] = []
    ordinary_expired = set(preparation.ordinary_expired_entries)
    for entry in retention_entries:
        if not isinstance(entry, RetentionEntrySnapshot):
            raise TypeError(
                "retention_entries items must be RetentionEntrySnapshot"
            )
        if not entry.protected:
            continue
        key = RetentionEntryKey(entry.program_id, entry.prefix_id)
        if key in ordinary_expired:
            continue
        ttl_input = entry.ttl_decision.ttl_input
        elapsed = preparation.preparation_timestamp - ttl_input.decision_timestamp
        if elapsed < 0:
            raise ValueError(
                "preparation timestamp must not precede TTL decision timestamp"
            )
        candidates.append(
            ForcedReleaseCandidateSnapshot(
                entry_key=key,
                retention_deadline_timestamp=entry.deadline_timestamp,
                waiting_followup=entry.waiting_followup,
                block_ids=entry.block_ids,
                initially_reclaimable_block_ids=initially_reclaimable_by_entry.get(
                    key, ()
                ),
                next_tool_type=ttl_input.next_tool_type,
                elapsed_since_ttl_decision_seconds=elapsed,
                prefill_reload_seconds=ttl_input.prefill_reload_seconds,
                eta=ttl_input.eta,
                queue_delay_t_seconds=ttl_input.queue_delay_t_seconds,
            )
        )

    candidates.sort(key=lambda candidate: candidate.entry_key.sort_key)
    return ForcedReleaseDecisionSnapshot(
        preparation=preparation,
        candidates=tuple(candidates),
    )
