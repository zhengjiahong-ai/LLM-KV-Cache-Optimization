"""Live Native adapter for the frozen Phase 2I A3 entry selector.

The adapter supplies decision-time event identity and current Native content
identity to :class:`A3SuffixCostStrategy`.  It does not duplicate the A3 score,
change the A1 ladder, or mutate Native block ownership.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, replace
from enum import Enum

from kvopt.continuum.pressure import _CandidateState
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import BlockIdentity
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.forced_release import ForcedReleaseObserver

from .a1_native import A1NativeSelectionCoordinator
from .a2_native import A2NativeSnapshotRegistry
from .a3_suffix import A3SuffixCostStrategy, A3SuffixSelection
from .entry_depth import ChainDepthIndex, DepthVerificationMode
from .replay import DecisionSnapshot, QueueBlock, ReplayState


def _json_safe(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_json_safe(item) for item in value)
    return value


class A3NativeSelectionCoordinator(A1NativeSelectionCoordinator):
    """Run A3 at the actual Native entry-release boundary.

    Every decision builds a fresh strategy with the current process id, current
    slot content identities and latest pre-decision chain proofs.  Any missing or
    inconsistent proof is therefore handled by A3's whole-Step-2 fallback.
    """

    def __init__(
        self,
        observer: ForcedReleaseObserver | None,
        *,
        depth_index: ChainDepthIndex,
        content_registry: A2NativeSnapshotRegistry,
        decision_event_index: Callable[[], int],
        decision_clock_domain: str,
        native_hash_process_id: str | None = None,
        lambda_: float = 0.5,
        tau_seconds: float = 30.0,
    ) -> None:
        super().__init__(observer, lambda_=lambda_, tau_seconds=tau_seconds)
        if not callable(decision_event_index):
            raise TypeError("decision_event_index must be callable")
        if not decision_clock_domain:
            raise ValueError("decision_clock_domain must be non-empty")
        self._depth_index = depth_index
        self._content_registry = content_registry
        self._decision_event_index = decision_event_index
        self._decision_clock_domain = decision_clock_domain
        self._native_hash_process_id = native_hash_process_id or str(os.getpid())
        self._a3_selection_trace: list[A3SuffixSelection] = []
        self._latest_decision_event_index: int | None = None

    def prepare(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self._a3_selection_trace.clear()
        return super().prepare(*args, **kwargs)

    def a3_selection_trace(self) -> tuple[dict[str, object], ...]:
        """JSON-safe audit rows for the latest pressure decision."""
        return tuple(
            _json_safe(asdict(selection)) for selection in self._a3_selection_trace
        )  # type: ignore[return-value]

    @property
    def latest_decision_event_index(self) -> int | None:
        return self._latest_decision_event_index

    @property
    def decision_clock_domain(self) -> str:
        return self._decision_clock_domain

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
        decision_index = self._decision_event_index()
        self._latest_decision_event_index = decision_index
        candidate_keys = tuple(key for key, _entry in candidates)
        owners = {
            block_id.block_id: frozenset(
                (key.program_id.value, key.prefix_id.canonical_value) for key in keys
            )
            for block_id, keys in entries_by_block.items()
        }
        snapshot = DecisionSnapshot(
            run_id="live-native-pressure",
            decision_event_index=decision_index,
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
        rows: tuple[DecisionCandidateRow, ...] = tuple(
            replace(
                self._candidate_row(
                    key,
                    entry,
                    position,
                    states,
                    entries,
                    entries_by_block,
                    released_keys,
                    timestamp,
                ),
                decision_event_index=decision_index,
                source_event_index=decision_index,
            )
            for position, (key, entry) in enumerate(candidates)
        )
        live_hashes: dict[int, str] = {}
        for queue_block in snapshot.queue:
            identity = self._content_registry.content_identity(queue_block.block_id)
            if (
                identity is not None
                and identity.native_hash_process_id == self._native_hash_process_id
            ):
                live_hashes[queue_block.block_id] = identity.content_hash
        strategy = A3SuffixCostStrategy(
            depth_index=self._depth_index,
            native_hash_process_id=self._native_hash_process_id,
            decision_clock_domain=self._decision_clock_domain,
            verification_mode=DepthVerificationMode.NATIVE_LIVE,
            content_hashes=live_hashes,
            lambda_=self.strategy.lambda_,
            tau_seconds=self.strategy.tau_seconds,
        )
        selection = strategy.select(rows, state)
        self._a3_selection_trace.append(selection)
        selected_program, selected_prefix = selection.key
        return next(
            key
            for key in candidate_keys
            if key.program_id.value == selected_program
            and key.prefix_id.canonical_value == selected_prefix
        )
