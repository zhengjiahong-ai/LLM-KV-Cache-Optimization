"""Serializable control plane for Phase 5 EngineCore-side integration.

Only commands and detached evidence cross the AsyncMP boundary. Native cache
objects remain owned by the EngineCore process that reads and mutates them.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from importlib.metadata import entry_points
from typing import Protocol

from .phase5_native_async import NativePressureAllocationRequest, PressureExecutionEvidence

INSTALL_METHOD = "kvopt_phase5_install"
G9_METHOD = "kvopt_phase5_g9"
PRESSURE_METHOD = "kvopt_phase5_execute_pressure"
EVIDENCE_METHOD = "kvopt_phase5_evidence"
CONTROLLER_EVENT_METHOD = "kvopt_phase5_controller_event"
PLUGIN_NAME = "kvopt_phase5_engine_core"
PLUGIN_VALUE = (
    "kvopt.workload.phase5e_engine_core_plugin:register_phase5_engine_core_plugin"
)


class Phase5EngineCoreBridgeError(RuntimeError):
    """The EngineCore-side control or evidence contract failed closed."""


class AsyncUtilityClient(Protocol):
    async def call_utility_async(self, method: str, *args: object) -> object: ...


def validate_engine_core_plugin_registration() -> Mapping[str, object]:
    """Fail before authorization consumption if EngineCore cannot load us."""

    matches = [
        point
        for point in entry_points(group="vllm.general_plugins")
        if point.name == PLUGIN_NAME
    ]
    if len(matches) != 1 or matches[0].value != PLUGIN_VALUE:
        raise Phase5EngineCoreBridgeError(
            "Phase 5 EngineCore plugin entry point is not installed exactly once"
        )
    allowlist = os.environ.get("VLLM_PLUGINS")
    if allowlist is not None:
        allowed = {value.strip() for value in allowlist.split(",") if value.strip()}
        if PLUGIN_NAME not in allowed:
            raise Phase5EngineCoreBridgeError(
                "VLLM_PLUGINS excludes the Phase 5 EngineCore plugin"
            )
    return {
        "status": "PASS",
        "entry_point_group": "vllm.general_plugins",
        "entry_point_name": PLUGIN_NAME,
        "entry_point_value": PLUGIN_VALUE,
        "vllm_plugins_allowlist": allowlist,
    }


def resolve_async_utility_client(engine: object) -> AsyncUtilityClient:
    """Resolve the AsyncMP utility client without resolving Native objects."""

    candidate = getattr(engine, "engine_core", None)
    delegate = getattr(candidate, "_delegate", candidate)
    method = getattr(delegate, "call_utility_async", None)
    if not inspect.iscoroutinefunction(method):
        raise Phase5EngineCoreBridgeError(
            "AsyncLLM EngineCore client lacks asynchronous Utility RPC"
        )
    return delegate


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise Phase5EngineCoreBridgeError(f"{label} is not a serialized object")
    return dict(value)


class RemoteRuntimeIntegrationObserver:
    """Frontend marker: request identity is bound by EngineCore.add_request."""

    def bind_request_identity(
        self, *, logical_request_id: str, external_request_id: str, internal_request_id: str
    ) -> None:
        del logical_request_id, external_request_id, internal_request_id


class EngineCoreRemoteEvidenceSource:
    """Local immutable cache of evidence exported by the EngineCore process."""

    def __init__(
        self,
        installation_report: Mapping[str, object],
        bridge: EngineCoreUtilityBridge,
    ) -> None:
        self._installation_report = dict(installation_report)
        self._bridge = bridge
        self._g9: dict[str, object] | None = None
        self._events: tuple[Mapping[str, object], ...] = ()
        self._exposure: dict[str, object] | None = None
        self._integration_observer = RemoteRuntimeIntegrationObserver()

    def runtime_installation_report(self) -> Mapping[str, object]:
        return dict(self._installation_report)

    def runtime_integration(self) -> object:
        return self._integration_observer

    def set_g9(self, value: Mapping[str, object]) -> None:
        self._g9 = dict(value)

    def update_export(self, value: Mapping[str, object]) -> None:
        events = value.get("events")
        exposure = value.get("candidate_exposure_report")
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
            raise Phase5EngineCoreBridgeError("EngineCore evidence export lacks events")
        if not isinstance(exposure, Mapping):
            raise Phase5EngineCoreBridgeError("EngineCore evidence export lacks exposure report")
        detached = []
        for row in events:
            if not isinstance(row, Mapping):
                raise Phase5EngineCoreBridgeError("EngineCore event is not an object")
            detached.append(dict(row))
        indices = [row.get("event_index") for row in detached]
        if indices != list(range(len(detached))):
            raise Phase5EngineCoreBridgeError("EngineCore event indices are not contiguous")
        self._events = tuple(detached)
        self._exposure = dict(exposure)

    async def a3_retention_input_manifest(self) -> Mapping[str, object]:
        if self._g9 is None:
            await self._bridge.g9(self)
        assert self._g9 is not None
        return dict(self._g9)

    def candidate_exposure_report(self) -> Mapping[str, object]:
        if self._exposure is None:
            raise Phase5EngineCoreBridgeError("EngineCore exposure evidence is not cached")
        return dict(self._exposure)

    async def refresh(self) -> None:
        self.update_export(await self._bridge.evidence())

    def raw_evidence(self) -> Sequence[Mapping[str, object]]:
        return tuple(dict(row) for row in self._events)


class EngineCoreUtilityBridge:
    """One EngineCore-targeted RPC bridge used by Part A and formal runners."""

    def __init__(self, client: AsyncUtilityClient) -> None:
        self._client = client

    async def install(self, contract: Mapping[str, object]) -> EngineCoreRemoteEvidenceSource:
        result = _mapping(
            await self._client.call_utility_async(INSTALL_METHOD, dict(contract)),
            "EngineCore installation result",
        )
        report = _mapping(result.get("installation_report"), "installation report")
        if report.get("status") != "PASS" or report.get("execution_process") != "ENGINE_CORE":
            raise Phase5EngineCoreBridgeError("EngineCore production integration did not install")
        return EngineCoreRemoteEvidenceSource(report, self)

    async def g9(self, evidence: EngineCoreRemoteEvidenceSource) -> Mapping[str, object]:
        result = _mapping(
            await self._client.call_utility_async(G9_METHOD), "EngineCore G9 result"
        )
        evidence.set_g9(result)
        return result

    async def controller_event(
        self, event_type: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        return _mapping(
            await self._client.call_utility_async(
                CONTROLLER_EVENT_METHOD, event_type, dict(payload)
            ),
            "EngineCore controller event result",
        )

    async def evidence(self) -> Mapping[str, object]:
        return _mapping(
            await self._client.call_utility_async(EVIDENCE_METHOD),
            "EngineCore evidence export",
        )

    async def execute_pressure(
        self,
        request: NativePressureAllocationRequest,
        *,
        expected_inflight_request_ids: tuple[str, ...],
        actual_inflight_request_ids: tuple[str, ...],
        evidence: EngineCoreRemoteEvidenceSource,
    ) -> PressureExecutionEvidence:
        result = _mapping(
            await self._client.call_utility_async(
                PRESSURE_METHOD,
                asdict(request),
                list(expected_inflight_request_ids),
                list(actual_inflight_request_ids),
            ),
            "EngineCore Pressure result",
        )
        pressure = _mapping(result.get("pressure"), "Pressure evidence")
        exported = _mapping(result.get("evidence"), "EngineCore evidence export")
        evidence.update_export(exported)
        return PressureExecutionEvidence(
            boundary_id=str(pressure["boundary_id"]),
            native_snapshot_timestamp=float(pressure["native_snapshot_timestamp"]),
            inflight_request_ids=tuple(pressure["inflight_request_ids"]),
            pressure_token_ids_sha256=str(pressure["pressure_token_ids_sha256"]),
            required_blocks=int(pressure["required_blocks"]),
            allocated_block_ids=tuple(pressure["allocated_block_ids"]),
            free_blocks_before=int(pressure["free_blocks_before"]),
            free_blocks_after_allocation=int(pressure["free_blocks_after_allocation"]),
            free_blocks_after_release=int(pressure["free_blocks_after_release"]),
            allocation_source=str(pressure["allocation_source"]),
            engine_core_identity_verified=pressure["engine_core_identity_verified"] is True,
            forced_release_decision_ids=tuple(pressure["forced_release_decision_ids"]),
            native_evicted_block_ids=tuple(pressure["native_evicted_block_ids"]),
            allocation_watermark_source=pressure.get("allocation_watermark_source"),
            observed_allocated_blocks_by_request=tuple(
                (str(row[0]), int(row[1]))
                for row in pressure.get("observed_allocated_blocks_by_request", ())
            ),
        )


class RemoteNativePressureExecutor:
    """Async adapter executor; all Native operations occur in EngineCore."""

    def __init__(
        self,
        bridge: EngineCoreUtilityBridge,
        evidence: EngineCoreRemoteEvidenceSource,
    ) -> None:
        self._bridge = bridge
        self._evidence = evidence

    async def execute(
        self,
        request: NativePressureAllocationRequest,
        *,
        expected_inflight_request_ids: tuple[str, ...],
        actual_inflight_request_ids: tuple[str, ...],
    ) -> PressureExecutionEvidence:
        return await self._bridge.execute_pressure(
            request,
            expected_inflight_request_ids=expected_inflight_request_ids,
            actual_inflight_request_ids=actual_inflight_request_ids,
            evidence=self._evidence,
        )
