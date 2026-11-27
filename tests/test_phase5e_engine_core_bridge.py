from __future__ import annotations

import asyncio
import multiprocessing
import os
from types import SimpleNamespace

import pytest

from kvopt.workload.phase5_native_async import NativePressureAllocationRequest
from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5e_engine_core_bridge import (
    EVIDENCE_METHOD,
    G9_METHOD,
    INSTALL_METHOD,
    PRESSURE_METHOD,
    EngineCoreUtilityBridge,
    Phase5EngineCoreBridgeError,
    resolve_async_utility_client,
    validate_engine_core_plugin_registration,
)
from kvopt.workload.phase5e_engine_core_plugin import (
    _EngineCoreState,
    _install,
    install_engine_core_methods,
)


class _UtilityClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def call_utility_async(self, method: str, *args: object) -> object:
        self.calls.append((method, args))
        return self.responses[method]


class _BlockPool:
    def __init__(self, free_blocks: int) -> None:
        self.free_blocks = free_blocks

    def get_num_free_blocks(self) -> int:
        return self.free_blocks


def _core_with_free_blocks(free_blocks: int) -> object:
    pool = _BlockPool(free_blocks)
    manager = SimpleNamespace(block_pool=pool)
    return SimpleNamespace(
        scheduler=SimpleNamespace(kv_cache_manager=manager),
    )


def _install_contract() -> dict[str, object]:
    return {
        "kv_pool_blocks": 2048,
        "reserved_null_blocks": 1,
        "expected_initial_free_blocks": 2047,
    }


def test_engine_core_install_distinguishes_configured_and_allocatable_blocks(
    monkeypatch,
) -> None:
    report = {"status": "PASS"}
    monkeypatch.setattr(
        "kvopt.workload.phase5e_engine_core_plugin.build_phase5e_production_integration",
        lambda _source: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_engine_core_plugin.install_phase5e_a3_runtime",
        lambda **_kwargs: report,
    )
    result = _install(_core_with_free_blocks(2047), _install_contract())
    installation = result["installation_report"]
    assert installation["configured_kv_pool_blocks"] == 2048
    assert installation["reserved_null_blocks"] == 1
    assert installation["initial_allocatable_kv_blocks"] == 2047


def test_engine_core_install_rejects_unreserved_free_block_geometry() -> None:
    with pytest.raises(Exception, match="observed_free=2048"):
        _install(_core_with_free_blocks(2048), _install_contract())


def test_engine_core_install_rejects_incoherent_frozen_geometry() -> None:
    contract = _install_contract()
    contract["expected_initial_free_blocks"] = 2048
    with pytest.raises(Exception, match="frozen KV pool geometry"):
        _install(_core_with_free_blocks(2047), contract)


def _bridge_child(connection) -> None:
    try:
        while True:
            command = connection.recv()
            if command is None:
                return
            method, _args = command
            if method == INSTALL_METHOD:
                response = {
                    "installation_report": {
                        "status": "PASS",
                        "execution_process": "ENGINE_CORE",
                        "engine_core_pid": os.getpid(),
                    }
                }
            elif method == G9_METHOD:
                response = {"status": "G9", "engine_core_pid": os.getpid()}
            elif method == EVIDENCE_METHOD:
                response = {
                    "events": [],
                    "candidate_exposure_report": {"status": "PASS"},
                    "engine_core_pid": os.getpid(),
                }
            else:
                raise AssertionError(method)
            connection.send(response)
    finally:
        connection.close()


class _ProcessUtilityClient:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def call_utility_async(self, method: str, *args: object) -> object:
        def exchange() -> object:
            self.connection.send((method, args))
            return self.connection.recv()

        return await asyncio.to_thread(exchange)


def test_bridge_installs_and_exports_pressure_evidence() -> None:
    token_ids = tuple(range(16))
    request = NativePressureAllocationRequest(
        boundary_id="boundary-1",
        pressure_token_ids=token_ids,
        pressure_token_ids_sha256=canonical_sha256(list(token_ids)),
        block_size_tokens=4,
        required_blocks=4,
        expected_free_blocks_before=10,
    )
    client = _UtilityClient(
        {
            INSTALL_METHOD: {
                "installation_report": {
                    "status": "PASS",
                    "execution_process": "ENGINE_CORE",
                    "same_engine_core": True,
                }
            },
            G9_METHOD: {"status": "G9"},
            PRESSURE_METHOD: {
                "pressure": {
                    "boundary_id": "boundary-1",
                    "native_snapshot_timestamp": 5.0,
                    "inflight_request_ids": ["p1", "p2"],
                    "pressure_token_ids_sha256": request.pressure_token_ids_sha256,
                    "required_blocks": 4,
                    "allocated_block_ids": [10, 11, 12, 13],
                    "free_blocks_before": 10,
                    "free_blocks_after_allocation": 6,
                    "free_blocks_after_release": 10,
                    "allocation_source": "PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
                    "engine_core_identity_verified": True,
                    "forced_release_decision_ids": ["decision-1"],
                    "native_evicted_block_ids": [10],
                    "allocation_watermark_source": None,
                    "observed_allocated_blocks_by_request": [],
                },
                "evidence": {
                    "events": [
                        {"event_index": 0, "event_type": "A", "payload": {}},
                        {"event_index": 1, "event_type": "B", "payload": {}},
                    ],
                    "candidate_exposure_report": {"status": "PASS"},
                },
            },
            EVIDENCE_METHOD: {},
        }
    )
    async def run() -> None:
        bridge = EngineCoreUtilityBridge(client)
        evidence = await bridge.install({"kv_pool_blocks": 2048})
        assert await evidence.a3_retention_input_manifest() == {"status": "G9"}
        result = await bridge.execute_pressure(
            request,
            expected_inflight_request_ids=("p1", "p2"),
            actual_inflight_request_ids=("p1", "p2"),
            evidence=evidence,
        )
        assert result.allocated_block_ids == (10, 11, 12, 13)
        assert evidence.candidate_exposure_report()["status"] == "PASS"
        assert [row["event_index"] for row in evidence.raw_evidence()] == [0, 1]

    asyncio.run(run())
    assert [call[0] for call in client.calls] == [INSTALL_METHOD, G9_METHOD, PRESSURE_METHOD]


def test_bridge_rejects_frontend_installation_claim() -> None:
    bridge = EngineCoreUtilityBridge(
        _UtilityClient(
            {
                INSTALL_METHOD: {
                    "installation_report": {
                        "status": "PASS",
                        "execution_process": "FRONTEND",
                    }
                }
            }
        )
    )
    async def run() -> None:
        with pytest.raises(Phase5EngineCoreBridgeError, match="did not install"):
            await bridge.install({"kv_pool_blocks": 2048})

    asyncio.run(run())


def test_bridge_uses_serializable_evidence_across_process_boundary() -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_bridge_child, args=(child,))
    process.start()
    child.close()

    async def run() -> None:
        bridge = EngineCoreUtilityBridge(_ProcessUtilityClient(parent))
        evidence = await bridge.install({"kv_pool_blocks": 2048})
        report = evidence.runtime_installation_report()
        assert report["engine_core_pid"] != os.getpid()
        g9 = await evidence.a3_retention_input_manifest()
        assert g9["engine_core_pid"] == report["engine_core_pid"]
        await evidence.refresh()
        assert evidence.candidate_exposure_report()["status"] == "PASS"

    try:
        asyncio.run(run())
        parent.send(None)
        process.join(timeout=5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()


def test_resolve_utility_client_uses_proxy_delegate() -> None:
    client = _UtilityClient({})
    engine = SimpleNamespace(engine_core=SimpleNamespace(_delegate=client))
    assert resolve_async_utility_client(engine) is client


def test_plugin_registration_validation_precedes_runtime(monkeypatch) -> None:
    point = SimpleNamespace(
        name="kvopt_phase5_engine_core",
        value=(
            "kvopt.workload.phase5e_engine_core_plugin:"
            "register_phase5_engine_core_plugin"
        ),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_engine_core_bridge.entry_points",
        lambda **kwargs: [point] if kwargs == {"group": "vllm.general_plugins"} else [],
    )
    monkeypatch.delenv("VLLM_PLUGINS", raising=False)
    assert validate_engine_core_plugin_registration()["status"] == "PASS"
    monkeypatch.setenv("VLLM_PLUGINS", "some_other_plugin")
    with pytest.raises(Phase5EngineCoreBridgeError, match="excludes"):
        validate_engine_core_plugin_registration()


def test_plugin_binds_identity_inside_engine_core_before_add() -> None:
    observed: list[tuple[str, str, str]] = []

    class Integration:
        def bind_request_identity(self, **kwargs: str) -> None:
            observed.append(
                (
                    kwargs["logical_request_id"],
                    kwargs["external_request_id"],
                    kwargs["internal_request_id"],
                )
            )

    class Core:
        def add_request(self, request: object) -> str:
            assert observed
            return "added"

    install_engine_core_methods(Core)
    core = Core()
    core._kvopt_phase5_engine_core_state = _EngineCoreState(SimpleNamespace(), Integration(), {}, 2048)
    request = SimpleNamespace(
        request_id="P5E-A-01:program-1:r1",
    )
    assert core.add_request(request) == "added"
    assert observed == [
        (
            "program-1:r1",
            "P5E-A-01:program-1:r1",
            "P5E-A-01:program-1:r1",
        )
    ]


def test_plugin_rejects_non_frozen_external_identity() -> None:
    class Integration:
        def bind_request_identity(self, **kwargs: str) -> None:
            raise AssertionError(kwargs)

    class Core:
        def add_request(self, request: object) -> None:
            raise AssertionError(request)

    install_engine_core_methods(Core)
    core = Core()
    core._kvopt_phase5_engine_core_state = _EngineCoreState(SimpleNamespace(), Integration(), {}, 2048)
    with pytest.raises(Exception, match="frozen logical identity"):
        core.add_request(SimpleNamespace(request_id="other:r1"))


def test_plugin_rejects_conflicting_shadow_external_identity() -> None:
    class Integration:
        def bind_request_identity(self, **_kwargs) -> None:
            raise AssertionError("conflicting identity must fail before binding")

    class Core:
        def add_request(self, request: object) -> None:
            raise AssertionError(request)

    install_engine_core_methods(Core)
    core = Core()
    core._kvopt_phase5_engine_core_state = _EngineCoreState(  # type: ignore[attr-defined]
        SimpleNamespace(), Integration(), {}, 2048
    )
    with pytest.raises(Exception, match="conflicting identity"):
        core.add_request(
            SimpleNamespace(
                request_id="P5E-A-01:program-1:r1",
                external_req_id="P5E-A-01:program-2:r1",
            )
        )


def test_controller_timer_requires_explicit_clock_domain() -> None:
    class Source:
        def snapshot(self):
            return ()

    class Integration:
        def observe_controller_timer_armed(self, **kwargs: object) -> None:
            raise AssertionError(kwargs)

    class Core:
        def add_request(self, request: object) -> None:
            raise AssertionError(request)

    install_engine_core_methods(Core)
    core = Core()
    core._kvopt_phase5_engine_core_state = _EngineCoreState(  # type: ignore[attr-defined]
        Source(), Integration(), {}, 2048
    )
    with pytest.raises(Exception, match="timer payload is incomplete"):
        core.kvopt_phase5_controller_event(  # type: ignore[attr-defined]
            "CONTROLLER_ARMED_TIMER",
            {
                "candidate_id": "candidate",
                "chain_id": "chain",
                "program_id": "program",
                "session_id": "session",
                "armed_at_timestamp": 1.0,
                "expires_at_timestamp": 2.0,
            },
        )
