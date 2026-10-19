"""Small orchestration boundary for retention-aware pressure decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from kvopt.continuum.config import RetentionMode
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.selection import SelectionPlan
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import BlockIdentity, ProgramIdentity
from kvopt.profiling import ForcedReleaseObserver

from .adapter import NativeLRUAdapter, RetentionAwareLRUAdapter
from .bridge import VLLMBlockLike, VLLMEvictionBridge
from .types import EvictionCandidate


class BlockSelectionCoordinator(Protocol):
    """Post-entry-release block selector; it cannot change eligibility."""

    def select_victims(
        self,
        candidates: tuple[EvictionCandidate, ...],
        preparation: object,
        retention_entries: tuple[RetentionEntrySnapshot, ...],
        *,
        required_blocks: int,
        timestamp: float,
    ) -> tuple[int, ...]: ...


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
        block_selection_coordinator: BlockSelectionCoordinator | None = None,
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
        if block_selection_coordinator is not None and not callable(
            getattr(block_selection_coordinator, "select_victims", None)
        ):
            raise TypeError(
                "block_selection_coordinator must provide select_victims or be None"
            )
        self._block_selection_coordinator = block_selection_coordinator

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
        retention_entries = self._manager.planning_snapshots()
        preparation = coordinator.prepare(
            candidates,
            retention_entries,
            required_blocks=required_blocks,
            timestamp=timestamp,
            diagnostic_first_release_program_id=(
                self._diagnostic_first_release_program_id
            ),
        )
        if self._block_selection_coordinator is None:
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
        else:
            selected = self._block_selection_coordinator.select_victims(
                tuple(candidates),
                preparation,
                retention_entries,
                required_blocks=required_blocks,
                timestamp=timestamp,
            )
            legal_ids = {
                block.block_id for block in preparation.virtual_eligible_order
            }
            if len(selected) != min(required_blocks, len(legal_ids)):
                raise ValueError("block selector returned the wrong victim count")
            if len(selected) != len(set(selected)):
                raise ValueError("block selector returned duplicate victim IDs")
            if not set(selected).issubset(legal_ids):
                raise ValueError("block selector returned a block outside the legal set")
            # SelectionPlan encodes A0's tier/LRU ordering and therefore cannot
            # truthfully represent an A2 order.  The immutable eligibility
            # preparation remains available through the forced-release evidence;
            # A2 emits its own decision audit.
            plan = None

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
