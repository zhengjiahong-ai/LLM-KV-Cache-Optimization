"""Small orchestration boundary for retention-aware pressure decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from kvopt.continuum.config import RetentionMode
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.selection import SelectionPlan
from kvopt.continuum.types import BlockIdentity, ProgramIdentity
from kvopt.profiling import ForcedReleaseObserver

from .adapter import NativeLRUAdapter, RetentionAwareLRUAdapter
from .bridge import VLLMBlockLike, VLLMEvictionBridge


@dataclass(frozen=True, slots=True)
class RetentionPressureResult:
    """Result of one retention integration decision."""

    selected_block_ids: tuple[int, ...]
    selection_plan: SelectionPlan | None


class RetentionRuntimeIntegration:
    """Coordinate native, shadow, and controlled retention pressure modes."""

    def __init__(
        self,
        manager: RetentionManager,
        forced_release_observer: ForcedReleaseObserver | None = None,
        diagnostic_first_release_program_id: ProgramIdentity | None = None,
        selection_coordinator: RetentionAwareSelectionCoordinator | None = None,
    ) -> None:
        if not isinstance(manager, RetentionManager):
            raise TypeError("manager must be RetentionManager")
        self._manager = manager
        self._forced_release_observer = forced_release_observer
        self._diagnostic_first_release_program_id = diagnostic_first_release_program_id
        if selection_coordinator is not None and not isinstance(
            selection_coordinator, RetentionAwareSelectionCoordinator
        ):
            raise TypeError(
                "selection_coordinator must be RetentionAwareSelectionCoordinator or None"
            )
        self._selection_coordinator = selection_coordinator

    def apply_pressure(
        self,
        *,
        mode: RetentionMode,
        blocks: Iterable[VLLMBlockLike],
        required_blocks: int,
        timestamp: float,
        remove_selected: Callable[[tuple[int, ...]], None],
    ) -> RetentionPressureResult:
        """Plan pressure from live state and optionally commit/remove victims."""
        if not isinstance(mode, RetentionMode):
            raise TypeError("mode must be RetentionMode")
        native_blocks = tuple(blocks)
        native_bridge = VLLMEvictionBridge(
            policy=NativeLRUAdapter(), total_blocks=len(native_blocks)
        )

        if mode is RetentionMode.NATIVE:
            selected = tuple(
                native_bridge.select_blocks(
                    native_blocks,
                    required_blocks,
                    timestamp=timestamp,
                )
            )
            remove_selected(selected)
            return RetentionPressureResult(selected, None)

        candidates = native_bridge.build_candidates(native_blocks)
        coordinator = self._selection_coordinator or RetentionAwareSelectionCoordinator(
            self._forced_release_observer
        )
        preparation = coordinator.prepare(
            candidates,
            self._manager.planning_snapshots(),
            required_blocks=required_blocks,
            timestamp=timestamp,
            diagnostic_first_release_program_id=(
                self._diagnostic_first_release_program_id
            ),
        )
        adapter = RetentionAwareLRUAdapter(preparation)
        bridge = VLLMEvictionBridge(policy=adapter, total_blocks=len(native_blocks))
        selected = tuple(
            bridge.select_blocks(
                native_blocks,
                required_blocks,
                timestamp=timestamp,
            )
        )
        plan = SelectionPlan(
            preparation,
            "RetentionAwareLRUAdapter",
            tuple(BlockIdentity(block_id) for block_id in selected),
        )

        if mode is RetentionMode.SHADOW:
            return RetentionPressureResult(selected, plan)

        release_keys = preparation.ordinary_expired_entries + tuple(
            effect.entry_key for effect in preparation.pressure_releases
        )
        self._manager.commit_pressure_releases(release_keys)
        remove_selected(selected)
        return RetentionPressureResult(selected, plan)

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        """Forward an observed native eviction to the retention manager."""
        self._manager.observe_eviction(block_id)
