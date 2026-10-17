from dataclasses import dataclass

from kvopt.continuum import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntrySnapshot,
    RetentionMode,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.continuum.clock import FakeClock
from kvopt.continuum.retention import RetentionManager
from kvopt.costaware.a1_native import A1NativeSelectionCoordinator
from kvopt.profiling import InMemoryForcedReleaseObserver
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration


@dataclass(frozen=True, slots=True)
class _Block:
    block_id: int
    ref_cnt: int = 0
    block_hash: object = object()


def _entry(program: str, blocks: tuple[int, ...], deadline: float) -> RetentionEntrySnapshot:
    ttl_input = TTLInput(
        program_id=ProgramIdentity(program),
        request_id=RequestIdentity(f"request-{program}"),
        prefix_id=PrefixIdentity("prefix"),
        decision_timestamp=0.0,
        next_tool_type="search",
        global_server_gap_samples_seconds=(2.0,),
        tool_server_gap_samples_seconds=(2.0,),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=deadline,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(InputSource.OBSERVED),
        prefill_reload_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test"
        ),
        default_ttl_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test"
        ),
    )
    return RetentionEntrySnapshot(
        ttl_decision=TTLDecision(
            ttl_input=ttl_input,
            ttl_seconds=deadline,
            history_mode=TTLHistoryMode.GLOBAL,
        ),
        protected=True,
        waiting_followup=True,
        block_ids=tuple(BlockIdentity(value) for value in blocks),
    )


def _manager() -> RetentionManager:
    manager = RetentionManager(FakeClock())
    manager.upsert(_entry("a", tuple(range(1, 9)), 10.0))
    manager.upsert(_entry("b", (9, 10), 20.0))
    return manager


def _run(
    coordinator: A1NativeSelectionCoordinator | None,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    manager = _manager()
    observer = InMemoryForcedReleaseObserver()
    integration = RetentionRuntimeIntegration(
        manager,
        observer,
        selection_coordinator=coordinator,
    )
    result = integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=tuple(_Block(value) for value in range(1, 11)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda _ids: None,
    )
    selected_programs = tuple(
        effect.entry_key.program_id.value
        for effect in result.selection_plan.preparation.pressure_releases
    )
    return result.selected_block_ids, selected_programs


def test_opt_in_a1_changes_logical_release_and_native_victims() -> None:
    observer = InMemoryForcedReleaseObserver()
    coordinator = A1NativeSelectionCoordinator(observer)

    a0_blocks, a0_releases = _run(None)
    a1_blocks, a1_releases = _run(coordinator)

    assert a0_releases == ("a",)
    assert a1_releases == ("b",)
    assert a0_blocks == (1, 2)
    assert a1_blocks == (9, 10)
    assert coordinator.selection_trace()[0]["branch"] == "single_step"


def test_default_runtime_path_remains_frozen_a0() -> None:
    first = _run(None)
    second = _run(None)

    assert first == second == ((1, 2), ("a",))
