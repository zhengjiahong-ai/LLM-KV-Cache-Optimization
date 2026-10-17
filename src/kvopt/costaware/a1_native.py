"""Opt-in native coordinator for Phase 2G A1 entry release.

The coordinator changes only the logical protected-entry release order. Native
LRU still selects physical blocks from the resulting eligible queue.
"""

from __future__ import annotations

from dataclasses import asdict

from kvopt.continuum.pressure import (
    RetentionAwareSelectionCoordinator,
    _CandidateState,
)
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import BlockIdentity
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.forced_release import ForcedReleaseObserver

from .a1_entry import A1EntryCostAwareStrategy, A1Selection
from .replay import DecisionSnapshot, QueueBlock, ReplayState


class A1NativeSelectionCoordinator(RetentionAwareSelectionCoordinator):
    """Execute the frozen A1 ladder at the live pressure-release boundary."""

    def __init__(
        self,
        observer: ForcedReleaseObserver | None = None,
        *,
        lambda_: float = 0.5,
        tau_seconds: float = 30.0,
    ) -> None:
        super().__init__(observer)
        self._strategy = A1EntryCostAwareStrategy(
            lambda_=lambda_, tau_seconds=tau_seconds
        )
        self._selection_trace: list[A1Selection] = []

    @property
    def strategy(self) -> A1EntryCostAwareStrategy:
        return self._strategy

    def selection_trace(self) -> tuple[dict[str, object], ...]:
        """Return JSON-safe decision-time diagnostics for the latest pressure."""
        return tuple(asdict(selection) for selection in self._selection_trace)

    def prepare(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self._selection_trace.clear()
        return super().prepare(*args, **kwargs)

    def _pick_pressure_release(
        self,
        candidates: list[tuple[RetentionEntryKey, RetentionEntrySnapshot]],
        states: tuple[_CandidateState, ...],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
        target: int,
        timestamp: float,
    ) -> RetentionEntryKey:
        candidate_keys = tuple(key for key, _entry in candidates)
        owners = {
            block_id.block_id: frozenset(
                (key.program_id.value, key.prefix_id.canonical_value) for key in keys
            )
            for block_id, keys in entries_by_block.items()
        }
        snapshot = DecisionSnapshot(
            run_id="live-native-pressure",
            decision_event_index=0,
            timestamp=timestamp,
            required_blocks=target,
            queue=tuple(
                QueueBlock(
                block_id=state.block_id.block_id,
                    has_block_hash=state.has_block_hash,
                    native_lru_rank=state.native_lru_rank,
                )
                for state in states
            ),
            candidate_keys=tuple(
                (key.program_id.value, key.prefix_id.canonical_value)
                for key in candidate_keys
            ),
            owners_by_block=owners,
            observed_selected=(),
            observed_initial_reclaimable={},
            ranking_by_block={
                state.block_id.block_id: state.native_lru_rank for state in states
            },
        )
        state = ReplayState(snapshot)
        rows = tuple(
            self._candidate_row(
                key,
                entry,
                position,
                states,
                entries,
                entries_by_block,
                released_keys,
                timestamp,
            )
            for position, (key, entry) in enumerate(candidates)
        )
        selection = self._strategy.select(rows, state)
        self._selection_trace.append(selection)
        selected_program, selected_prefix = selection.key
        return next(
            key
            for key in candidate_keys
            if key.program_id.value == selected_program
            and key.prefix_id.canonical_value == selected_prefix
        )

    def _candidate_row(
        self,
        key: RetentionEntryKey,
        entry: RetentionEntrySnapshot,
        position: int,
        states: tuple[_CandidateState, ...],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
        timestamp: float,
    ) -> DecisionCandidateRow:
        reclaimable = self._newly_eligible_blocks_after_release(
            key, states, entries, entries_by_block, released_keys
        )
        ttl_input = entry.ttl_decision.ttl_input
        ranks = {
            state.block_id: state.native_lru_rank for state in states
        }
        return DecisionCandidateRow(
            run_id="live-native-pressure",
            decision_event_index=0,
            source_event_index=0,
            candidate_position=position,
            program_id=key.program_id.value,
            prefix_id=key.prefix_id.canonical_value,
            selected=False,
            release_order=None,
            retention_deadline_timestamp=entry.deadline_timestamp,
            waiting_followup=entry.waiting_followup,
            block_ids=tuple(value.block_id for value in entry.block_ids),
            block_count=len(entry.block_ids),
            initially_reclaimable_block_ids=tuple(
                value.block_id for value in reclaimable
            ),
            initially_reclaimable_block_count=len(reclaimable),
            next_tool_type=ttl_input.next_tool_type,
            elapsed_since_ttl_decision_seconds=(
                timestamp - ttl_input.decision_timestamp
            ),
            prefill_reload_seconds=ttl_input.prefill_reload_seconds,
            eta=ttl_input.eta,
            queue_delay_t_seconds=ttl_input.queue_delay_t_seconds,
            decision_native_lru_position=min(
                (ranks[block_id] for block_id in reclaimable), default=None
            ),
        )
