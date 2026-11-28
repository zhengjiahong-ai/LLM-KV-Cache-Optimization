"""Live EngineCore entry-release coordinator for DVA-ER v1."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from kvopt.continuum.pressure import (
    RetentionAwareSelectionCoordinator,
    _CandidateState,
)
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import BlockIdentity
from kvopt.profiling.forced_release import ForcedReleaseObserver


class DVAERNativeSelectionError(RuntimeError):
    """The live DVA selector lacks complete decision-time evidence."""


SnapshotEvaluator = Callable[..., Mapping[str, object]]


class DVAERNativeSelectionCoordinator(RetentionAwareSelectionCoordinator):
    """Select each pressure release from one complete live Native snapshot."""

    def __init__(
        self,
        observer: ForcedReleaseObserver | None,
        *,
        snapshot_evaluator: SnapshotEvaluator,
    ) -> None:
        super().__init__(observer)
        if not callable(snapshot_evaluator):
            raise TypeError("snapshot_evaluator must be callable")
        self._snapshot_evaluator = snapshot_evaluator
        self._selection_trace: list[dict[str, object]] = []

    def prepare(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self._selection_trace.clear()
        return super().prepare(*args, **kwargs)

    def selection_trace(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(row) for row in self._selection_trace)

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
        a0_order = tuple(
            key
            for key, entry in sorted(
                candidates,
                key=lambda item: self._release_sort_key(
                    item[0],
                    item[1],
                    states,
                    entries,
                    entries_by_block,
                    released_keys,
                ),
            )
        )
        result = self._snapshot_evaluator(
            legal_candidate_keys=tuple(key for key, _entry in candidates),
            released_candidate_keys=frozenset(released_keys),
            a0_order=a0_order,
            required_blocks=target,
            decision_timestamp=timestamp,
        )
        selected = result.get("selected_candidate_id")
        if not isinstance(selected, str) or not selected:
            raise DVAERNativeSelectionError("DVA selector returned no candidate identity")
        matches = [key for key, _entry in candidates if key.program_id.value == selected]
        if len(matches) != 1:
            raise DVAERNativeSelectionError("DVA selection is outside the legal candidate set")
        self._selection_trace.append(dict(result))
        return matches[0]
