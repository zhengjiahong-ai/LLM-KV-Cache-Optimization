from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from kvopt.continuum import ProgramIdentity, RequestIdentity, RetentionMode
from kvopt.continuum.selection import (
    BlockEligibilitySnapshot,
    EligibilityPreparation,
    EligibilityTier,
    PressureReleaseEffect,
    RetentionEntryKey,
)
from kvopt.continuum.types import BlockIdentity, PrefixIdentity
from kvopt.profiling.forced_release import (
    ForcedReleaseCandidateSnapshot,
    ForcedReleaseDecisionSnapshot,
)
from kvopt.runtime.vllm.continuum_observation import (
    NativeBlockSnapshot,
    ObservationAvailability,
    RequestBlockSnapshot,
)
from kvopt.workload.phase5e_a3_retention import Phase5EG9Error, evaluate_p5e_g9
from kvopt.workload.phase5e_native_runtime import Phase5ERuntimeEventSource
from kvopt.workload.phase5e_production_integration import (
    Phase5EProductionIntegrationError,
    _BoundForcedReleaseObserver,
    build_phase5_calibration_production_integration,
    build_phase5e_production_integration,
)


class _Pool:
    free_block_queue = None


def _integration():
    source = Phase5ERuntimeEventSource()
    integration = build_phase5e_production_integration(source)
    core = object()
    integration.build_dva_er_native_decision_provider(
        engine_core=core,
        scheduler=object(),
        kv_cache_manager=object(),
        block_pool=_Pool(),
    )
    source._mark_installed(
        {"status": "PASS", "mode": "CONTROLLED_A3", "same_engine_core": True},
        integration,
    )
    return source, integration


def _register_first_wave(integration) -> None:
    for index in range(1, 5):
        logical = f"p{index}:r1"
        internal = f"internal:{logical}"
        integration.bind_request_identity(
            logical_request_id=logical,
            external_request_id=f"external:{logical}",
            internal_request_id=internal,
        )
        blocks = tuple(
            NativeBlockSnapshot(
                block_id=index * 10 + offset,
                ref_count=0,
                native_hash_hex=(bytes([index, offset]) * 16).hex(),
                hash_num_tokens=16,
                cache_group_id=0,
                is_null=False,
            )
            for offset in range(2)
        )
        integration.observe_terminal_request_snapshot(
            RequestBlockSnapshot(
                program_id=ProgramIdentity(f"p{index}"),
                request_id=RequestIdentity(internal),
                block_groups=(blocks,),
                availability=ObservationAvailability.AVAILABLE,
            ),
            observed_at=1.0 + index / 10,
            native_hash_process_id=str(os.getpid()),
        )


def test_bound_observer_emits_direct_decision_and_boundary_identity() -> None:
    source = Phase5ERuntimeEventSource()
    observer = _BoundForcedReleaseObserver(source)
    key = RetentionEntryKey(ProgramIdentity("p1"), PrefixIdentity("prefix:1"))
    block_id = BlockIdentity(7)
    preparation = EligibilityPreparation(
        required_blocks=1,
        original_free_queue=(
            BlockEligibilitySnapshot(
                block_id=block_id,
                native_lru_rank=0,
                has_block_hash=True,
                eligibility_tier=EligibilityTier.TIER_2,
            ),
        ),
        ordinary_expired_entries=(),
        pressure_releases=(PressureReleaseEffect(key, (block_id,)),),
        preparation_timestamp=2.0,
    )
    snapshot = ForcedReleaseDecisionSnapshot(
        preparation=preparation,
        candidates=(
            ForcedReleaseCandidateSnapshot(
                entry_key=key,
                retention_deadline_timestamp=5.0,
                waiting_followup=False,
                block_ids=(block_id,),
                initially_reclaimable_block_ids=(block_id,),
                next_tool_type="search",
                elapsed_since_ttl_decision_seconds=2.0,
                prefill_reload_seconds=0.2,
                eta=1.0,
                queue_delay_t_seconds=0.0,
            ),
        ),
    )
    observer.begin(
        {
            "decision_id": "decision:1",
            "frozen_decision_boundary_id": "phase5e-pressure-01",
        }
    )
    observer.observe(snapshot)
    observer.end()

    decision, binding = source.snapshot()
    assert decision["event_type"] == "FORCED_RELEASE_DECISION"
    assert decision["payload"]["decision_id"] == "decision:1"
    assert decision["payload"]["frozen_decision_boundary_id"] == ("phase5e-pressure-01")
    assert binding["payload"]["forced_release_event_index"] == decision["event_index"]


def test_production_factory_builds_real_prepressure_manifest_and_binding() -> None:
    source, integration = _integration()
    assert integration.pressure_context_active() is False
    assert integration.first_wave_prefix_readiness()["observed_prefix_count"] == 0
    _register_first_wave(integration)
    readiness = integration.first_wave_prefix_readiness()
    assert readiness["observed_prefix_count"] == 4
    assert readiness["observed_first_wave_request_ids"] == ["p1:r1", "p2:r1", "p3:r1", "p4:r1"]
    manifest = integration.a3_retention_input_manifest()
    assert evaluate_p5e_g9(manifest)["status"] == "PASS"
    lifecycle_indices = [row["event_index"] for row in manifest["lifecycle"]]
    assert lifecycle_indices == sorted(lifecycle_indices)
    integration.begin_pressure_context(
        boundary_id="phase5e-pressure-01",
        stage_id="P5E_PART_A_NATIVE_PRESSURE",
        pressure_request_id="pressure:phase5e-pressure-01",
    )
    assert integration.pressure_context_active() is True
    binding = next(
        row
        for row in source.snapshot()
        if row["event_type"] == "PHASE5E_G9_ACTUAL_PRESSURE_BINDING"
    )
    assert binding["payload"]["g9_manifest_sha256"] == manifest["manifest_sha256"]
    integration.end_pressure_context()
    assert integration.pressure_context_active() is False


def test_g9_lifecycle_uses_native_event_order_not_prefix_hash_order() -> None:
    _source, integration = _integration()
    for index in range(1, 5):
        logical = f"p{index}:r1"
        internal = f"internal:{logical}"
        integration.bind_request_identity(
            logical_request_id=logical,
            external_request_id=f"external:{logical}",
            internal_request_id=internal,
        )
        # Descending hashes deliberately make PrefixIdentity lexical order the
        # reverse of the real EngineCore event order.
        hash_byte = 255 - index
        block = NativeBlockSnapshot(
            block_id=index,
            ref_count=0,
            native_hash_hex=(bytes([hash_byte]) * 32).hex(),
            hash_num_tokens=16,
            cache_group_id=0,
            is_null=False,
        )
        integration.observe_terminal_request_snapshot(
            RequestBlockSnapshot(
                program_id=ProgramIdentity(f"p{index}"),
                request_id=RequestIdentity(internal),
                block_groups=((block,),),
                availability=ObservationAvailability.AVAILABLE,
            ),
            observed_at=1.0 + index / 10,
            native_hash_process_id=str(os.getpid()),
        )

    manifest = integration.a3_retention_input_manifest()
    indices = [row["event_index"] for row in manifest["lifecycle"]]
    assert indices == sorted(indices)
    assert evaluate_p5e_g9(manifest)["status"] == "PASS"


def test_production_factory_uses_exact_frozen_first_wave_identities() -> None:
    _source, integration = _integration()
    all_ids = [
        "task-a:first",
        "task-b:first",
        "task-c:first",
        "task-d:first",
        "task-a:second",
        "task-b:second",
        "task-c:second",
        "task-d:second",
    ]
    first_wave = all_ids[:4]
    integration.configure_frozen_request_ids(
        all_request_ids=all_ids,
        first_wave_request_ids=first_wave,
    )
    integration.bind_request_identity(
        logical_request_id="task-a:first",
        external_request_id="external:a",
        internal_request_id="internal:a",
    )
    block = NativeBlockSnapshot(7, 0, "ab" * 32, 16, 0, False)
    integration.observe_terminal_request_snapshot(
        RequestBlockSnapshot(
            ProgramIdentity("task-a"),
            RequestIdentity("internal:a"),
            ((block,),),
            ObservationAvailability.AVAILABLE,
        ),
        observed_at=1.0,
        native_hash_process_id=str(os.getpid()),
    )
    readiness = integration.first_wave_prefix_readiness()
    assert readiness["expected_first_wave_request_ids"] == sorted(first_wave)
    assert readiness["observed_first_wave_request_ids"] == ["task-a:first"]
    with pytest.raises(
        Phase5EProductionIntegrationError,
        match=r"logical_request_id='task-z:first'.*task-a:first",
    ):
        integration.bind_request_identity(
            logical_request_id="task-z:first",
            external_request_id="external:z",
            internal_request_id="internal:z",
        )


def test_production_factory_maps_vllm_suffixed_native_identity_to_frozen_logical_id() -> None:
    _source, integration = _integration()
    all_ids = [
        "p1:r1",
        "p2:r1",
        "p3:r1",
        "p4:r1",
        "p1:r2",
        "p2:r2",
        "p3:r2",
        "p4:r2",
    ]
    integration.configure_frozen_request_ids(
        all_request_ids=all_ids,
        first_wave_request_ids=all_ids[:4],
    )
    assert integration.try_internal_request_id("p1:r2") is None
    native_id = "P5E-A-01:p1:r1-a4358e48"
    integration.bind_request_identity(
        logical_request_id="p1:r1",
        external_request_id=native_id,
        internal_request_id=native_id,
    )
    assert integration.try_internal_request_id("p1:r1") == native_id
    assert integration.internal_request_id("p1:r1") == native_id
    assert integration.program_for_internal_request(native_id) == ProgramIdentity("p1")


def test_terminal_snapshot_excludes_one_real_hashless_tail_from_retention() -> None:
    source, integration = _integration()
    integration.bind_request_identity(
        logical_request_id="p1:r1",
        external_request_id="P5E-A-01:p1:r1",
        internal_request_id="P5E-A-01:p1:r1",
    )
    hashed = NativeBlockSnapshot(7, 0, "ab" * 32, 16, 0, False)
    partial = NativeBlockSnapshot(8, 0, None, None, 0, False)
    integration.observe_terminal_request_snapshot(
        RequestBlockSnapshot(
            program_id=ProgramIdentity("p1"),
            request_id=RequestIdentity("P5E-A-01:p1:r1"),
            block_groups=((hashed, partial),),
            availability=ObservationAvailability.AVAILABLE,
        ),
        observed_at=1.0,
        native_hash_process_id=str(os.getpid()),
    )

    event = next(row for row in source.snapshot() if row["event_type"] == "VLLM_PREFIX_SNAPSHOT")
    assert event["payload"]["block_ids"] == [7]
    assert event["payload"]["excluded_hashless_tail_block_ids"] == [8]
    entry = integration._manager.planning_snapshots()[0]
    assert tuple(block.block_id for block in entry.block_ids) == (7,)


def test_production_factory_rejects_pressure_before_g9_and_missing_hash() -> None:
    _source, integration = _integration()
    with pytest.raises(Phase5EProductionIntegrationError, match="before G9"):
        integration.begin_pressure_context(
            boundary_id="phase5e-pressure-01",
            stage_id="stage",
            pressure_request_id="pressure",
        )

    integration.bind_request_identity(
        logical_request_id="p1:r1",
        external_request_id="external",
        internal_request_id="internal",
    )
    bad = NativeBlockSnapshot(1, 0, None, None, 0, False)
    with pytest.raises(Phase5EProductionIntegrationError, match="complete hashed prefix"):
        integration.observe_terminal_request_snapshot(
            RequestBlockSnapshot(
                ProgramIdentity("p1"),
                RequestIdentity("internal"),
                ((bad,),),
                ObservationAvailability.AVAILABLE,
            ),
            observed_at=1.0,
            native_hash_process_id=str(os.getpid()),
        )


def test_production_factory_rejects_wrong_boundary_and_invalidated_state() -> None:
    _source, integration = _integration()
    _register_first_wave(integration)
    manifest = integration.a3_retention_input_manifest()
    with pytest.raises(Phase5EG9Error, match="boundary identity mismatch"):
        integration.begin_pressure_context(
            boundary_id="wrong-boundary",
            stage_id="stage",
            pressure_request_id="pressure",
        )

    entry = integration._manager.planning_snapshots()[0]
    integration._manager.commit_pressure_releases(
        (RetentionEntryKey(entry.program_id, entry.prefix_id),)
    )
    assert manifest["runtime_state_sha256"]
    with pytest.raises(Phase5EProductionIntegrationError, match="no longer valid"):
        integration.begin_pressure_context(
            boundary_id="phase5e-pressure-01",
            stage_id="stage",
            pressure_request_id="pressure",
        )


@pytest.mark.parametrize(
    ("system_id", "coordinator_name"),
    [
        ("NATIVE", None),
        ("CONTINUUM_ADAPTED", "RetentionAwareSelectionCoordinator"),
        ("A1_ORIGINAL", "A1NativeSelectionCoordinator"),
        ("A3_SUFFIX", "A3NativeSelectionCoordinator"),
    ],
)
def test_calibration_factory_selects_exact_project_policy(
    system_id: str, coordinator_name: str | None
) -> None:
    source = Phase5ERuntimeEventSource()
    integration = build_phase5_calibration_production_integration(
        source, system_id=system_id
    )
    assert integration.system_id == system_id
    if coordinator_name is None:
        assert integration._coordinator is None
    else:
        assert type(integration._coordinator).__name__ == coordinator_name


def test_calibration_factory_rejects_official_fallback() -> None:
    source = Phase5ERuntimeEventSource()
    with pytest.raises(
        Phase5EProductionIntegrationError, match="lacks an installed"
    ):
        build_phase5_calibration_production_integration(
            source, system_id="CONTINUUM_OFFICIAL"
        )


def test_calibration_factory_installs_dva_selector() -> None:
    integration = build_phase5_calibration_production_integration(
        Phase5ERuntimeEventSource(), system_id="DVA_ER_V1"
    )
    assert type(integration._coordinator).__name__ == "DVAERNativeSelectionCoordinator"
    assert integration._dva_adapter.candidate_id == "DVA_ER_V1"


def test_calibration_retains_terminal_prefixes_beyond_part_a_first_wave() -> None:
    integration = build_phase5_calibration_production_integration(
        Phase5ERuntimeEventSource(), system_id="A3_SUFFIX"
    )
    integration.configure_frozen_request_ids(
        all_request_ids=["program-1:turn:1", "program-1:turn:2"],
        first_wave_request_ids=["program-1:turn:1"],
    )
    integration.bind_request_identity(
        logical_request_id="program-1:turn:2",
        external_request_id="run:program-1:turn:2",
        internal_request_id="internal-2",
    )
    integration.observe_terminal_request_snapshot(
        RequestBlockSnapshot(
            program_id=ProgramIdentity("program-1"),
            request_id=RequestIdentity("internal-2"),
            block_groups=((NativeBlockSnapshot(
                block_id=7,
                ref_count=0,
                native_hash_hex=(b"terminal-prefix" * 2)[:32].hex(),
                hash_num_tokens=16,
                cache_group_id=0,
                is_null=False,
            ),),),
            availability=ObservationAvailability.AVAILABLE,
        ),
        observed_at=2.0,
        native_hash_process_id=str(os.getpid()),
    )
    assert [row["request_id"] for row in integration._terminal_records.values()] == [
        "program-1:turn:2"
    ]


def test_dva_allocation_identity_comes_from_engine_core_request_binding() -> None:
    integration = build_phase5_calibration_production_integration(
        Phase5ERuntimeEventSource(), system_id="DVA_ER_V1"
    )
    integration.configure_frozen_request_ids(
        all_request_ids=["program-1:turn:1"], first_wave_request_ids=[]
    )
    integration.configure_calibration_identities(
        group_id="SWE_G01",
        session_by_program={"program-1": "session-1"},
        trace_sha256_by_program={"program-1": "a" * 64},
    )
    integration.bind_request_identity(
        logical_request_id="program-1:turn:1",
        external_request_id="run:program-1:turn:1",
        internal_request_id="internal-1",
    )
    integration.bind_dva_allocation_request("internal-1")
    assert integration._decision_program_session == ("program-1", "session-1")
    assert integration._dva_decision_metadata == {
        "group_id": "SWE_G01",
        "turn_id": "program-1:turn:1",
        "trace_sha256": "a" * 64,
    }


def test_controller_timer_command_uses_engine_core_clock() -> None:
    source = Phase5ERuntimeEventSource()
    integration = build_phase5e_production_integration(source)
    integration.observe_controller_timer_command(
        candidate_id="program-1",
        chain_id="chain-1",
        program_id="program-1",
        session_id="session-1",
        timeout_seconds=60.0,
        predecessor_request_id="turn-1",
        successor_request_id="turn-2",
        source="OBSERVED_PREDECESSOR_TERMINAL_PLUS_FROZEN_TOOL_GAP",
        source_event_index=0,
    )
    timer = integration._controller_timers["program-1"]
    assert timer["clock_domain"] == "continuum_lifecycle"
    assert timer["pending_tool_gap_source"] == "CONTROLLER_ARMED_TIMER"
    assert float(timer["expires_at_timestamp"]) - float(
        timer["armed_at_timestamp"]
    ) == 60.0
    assert source.snapshot()[0]["event_type"] == "CONTROLLER_ARMED_TIMER"


@pytest.mark.parametrize("timeout", [-1.0, float("inf")])
def test_controller_timer_command_rejects_invalid_timeout(timeout: float) -> None:
    integration = build_phase5e_production_integration(Phase5ERuntimeEventSource())
    with pytest.raises(Phase5EProductionIntegrationError, match="invalid"):
        integration.observe_controller_timer_command(
            candidate_id="program-1",
            chain_id="chain-1",
            program_id="program-1",
            session_id="session-1",
            timeout_seconds=timeout,
            predecessor_request_id="turn-1",
            successor_request_id="turn-2",
            source="OBSERVED_PREDECESSOR_TERMINAL_PLUS_FROZEN_TOOL_GAP",
            source_event_index=0,
        )


def test_calibration_policy_observes_natural_pressure_without_part_a_g9() -> None:
    source = Phase5ERuntimeEventSource()
    integration = build_phase5_calibration_production_integration(
        source, system_id="CONTINUUM_ADAPTED"
    )
    removed = []
    result = integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(
            SimpleNamespace(block_id=7, ref_cnt=0, block_hash=None),
            SimpleNamespace(block_id=8, ref_cnt=0, block_hash=None),
        ),
        required_blocks=1,
        timestamp=1.0,
        remove_selected=lambda block_ids: removed.append(tuple(block_ids)),
    )
    integration.observe_native_selection_returned(((result.selected_block_ids[0], None),))
    event_types = [row["event_type"] for row in source.snapshot()]
    assert event_types == [
        "PHASE5_CALIBRATION_NATIVE_PRESSURE_BOUNDARY",
        "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
        "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
    ]
    assert removed == [result.selected_block_ids]
