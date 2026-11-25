from __future__ import annotations

import os

import pytest

from kvopt.continuum import ProgramIdentity, RequestIdentity
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.runtime.vllm.continuum_observation import (
    NativeBlockSnapshot,
    ObservationAvailability,
    RequestBlockSnapshot,
)
from kvopt.workload.phase5e_a3_retention import Phase5EG9Error, evaluate_p5e_g9
from kvopt.workload.phase5e_native_runtime import Phase5ERuntimeEventSource
from kvopt.workload.phase5e_production_integration import (
    Phase5EProductionIntegrationError,
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


def test_production_factory_builds_real_prepressure_manifest_and_binding() -> None:
    source, integration = _integration()
    _register_first_wave(integration)
    manifest = integration.a3_retention_input_manifest()
    assert evaluate_p5e_g9(manifest)["status"] == "PASS"
    integration.begin_pressure_context(
        boundary_id="phase5e-pressure-01",
        stage_id="P5E_PART_A_NATIVE_PRESSURE",
        pressure_request_id="pressure:phase5e-pressure-01",
    )
    binding = next(
        row
        for row in source.snapshot()
        if row["event_type"] == "PHASE5E_G9_ACTUAL_PRESSURE_BINDING"
    )
    assert binding["payload"]["g9_manifest_sha256"] == manifest["manifest_sha256"]
    integration.end_pressure_context()


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
    with pytest.raises(Phase5EProductionIntegrationError, match="incomplete"):
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
