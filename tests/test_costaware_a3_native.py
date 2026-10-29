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
from kvopt.costaware.a2_native import A2NativeChainSnapshot, A2NativeSnapshotRegistry
from kvopt.costaware.a3_native import A3NativeSelectionCoordinator
from kvopt.costaware.entry_depth import ChainDepthIndex
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
        prefill_reload_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
        default_ttl_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
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


def _run(
    *,
    live_identity: bool = True,
    proof_process: str = "native-process",
    native_process: str = "native-process",
    registry_process: str | None = None,
):
    manager = RetentionManager(FakeClock())
    chains = {"a": tuple(range(1, 9)), "b": (9, 10)}
    manager.upsert(_entry("a", chains["a"], 10.0))
    manager.upsert(_entry("b", chains["b"], 20.0))
    depth_index = ChainDepthIndex()
    registry = A2NativeSnapshotRegistry()
    for ordinal, (program, blocks) in enumerate(chains.items(), start=10):
        hashes = tuple(f"hash-{block}" for block in blocks)
        depth_index.observe_chain(
            (program, "prefix"),
            proof_process,
            blocks,
            content_hashes=hashes,
            observation_index=ordinal,
            observed_at=0.5,
            clock_domain="continuum_pressure",
        )
        if live_identity:
            registry.observe(
                A2NativeChainSnapshot(
                    chain_id=f"{program}:prefix",
                    block_ids=blocks,
                    content_hashes=hashes,
                    native_hash_process_id=registry_process or proof_process,
                )
            )
    observer = InMemoryForcedReleaseObserver()
    coordinator = A3NativeSelectionCoordinator(
        observer,
        depth_index=depth_index,
        content_registry=registry,
        decision_event_index=lambda: 100,
        decision_clock_domain="continuum_pressure",
        native_hash_process_id=native_process,
    )
    integration = RetentionRuntimeIntegration(
        manager, observer, selection_coordinator=coordinator
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
    return result.selected_block_ids, selected_programs, coordinator


def test_a3_native_intervenes_with_live_content_and_records_formula_inputs() -> None:
    blocks, programs, coordinator = _run()

    assert programs == ("a",)
    assert blocks == (1, 2)
    selection = coordinator.a3_selection_trace()[0]
    assert selection["a1_key"] == ("b", "prefix")
    assert selection["key"] == ("a", "prefix")
    assert selection["fell_back"] is False
    selected = next(audit for audit in selection["audits"] if audit["selected"])
    assert selected["victim_block_ids"] == (1, 2)
    assert selected["chain_length"] == 8
    assert selected["d_min"] == 1
    assert selected["suffix_blocks"] == 8
    assert selected["content_verified"] is True


def test_a3_native_missing_live_identity_falls_back_for_whole_step2() -> None:
    blocks, programs, coordinator = _run(live_identity=False)

    assert programs == ("b",)
    assert blocks == (9, 10)
    selection = coordinator.a3_selection_trace()[0]
    assert selection["fell_back"] is True
    assert str(selection["fallback_reason"]).startswith("STEP2_UNSCORABLE:")


def test_a3_native_wrong_process_content_falls_back() -> None:
    blocks, programs, coordinator = _run(
        proof_process="old-process",
        native_process="current-process",
        registry_process="current-process",
    )

    assert programs == ("b",)
    assert blocks == (9, 10)
    selection = coordinator.a3_selection_trace()[0]
    assert selection["fell_back"] is True
    assert "WRONG_PROCESS" in str(selection["fallback_reason"])
