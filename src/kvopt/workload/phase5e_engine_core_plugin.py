"""vLLM general plugin that installs Phase 5 inside EngineCoreProc.

The plugin adds a small Utility RPC surface to the pinned EngineCore class.
Every Native object is resolved and used in the child process; only JSON-like
commands and detached evidence are returned to the frontend.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from kvopt.continuum.clock import SystemMonotonicClock
from kvopt.profiling.phase5_candidate_exposure import evaluate_run_candidate_exposure

from .phase5_asyncllm_adapter import PinnedNativeBlockPoolPressureExecutor
from .phase5_native_async import NativePressureAllocationRequest
from .phase5e_native_evidence_source import RuntimeEventEvidenceSource
from .phase5e_native_runtime import Phase5ERuntimeEventSource, install_phase5e_a3_runtime
from .phase5e_production_integration import build_phase5e_production_integration

_STATE_ATTRIBUTE = "_kvopt_phase5_engine_core_state"
_PATCHED_ATTRIBUTE = "_kvopt_phase5_engine_core_plugin_patched"


class Phase5EngineCorePluginError(RuntimeError):
    """The child-process Native integration violated its frozen contract."""


@dataclass(slots=True)
class _EngineCoreState:
    source: Phase5ERuntimeEventSource
    integration: object
    installation_report: Mapping[str, object]
    expected_initial_free_blocks: int


def _state(core: object) -> _EngineCoreState:
    value = getattr(core, _STATE_ATTRIBUTE, None)
    if not isinstance(value, _EngineCoreState):
        raise Phase5EngineCorePluginError("Phase 5 EngineCore integration is not installed")
    return value


def _external_logical_identity(request: object) -> tuple[str, str, str]:
    internal = getattr(request, "request_id", None)
    external = getattr(request, "external_req_id", None)
    if not isinstance(internal, str) or not internal:
        raise Phase5EngineCorePluginError("EngineCore request lacks internal identity")
    if not isinstance(external, str) or not external:
        raise Phase5EngineCorePluginError("EngineCore request lacks external identity")
    prefix = "P5E-A-01:"
    if not external.startswith(prefix) or len(external) == len(prefix):
        raise Phase5EngineCorePluginError("EngineCore request lacks frozen logical identity")
    return external[len(prefix) :], external, internal


def _request_block_count(manager: object, request_id: str) -> int:
    method = getattr(manager, "get_block_ids", None)
    if not callable(method):
        method = getattr(manager, "get_blocks", None)
    if not callable(method):
        raise Phase5EngineCorePluginError("KVCacheManager request BlockTable is unavailable")
    value = method(request_id)
    if isinstance(value, Mapping):
        rows: Sequence[object] = tuple(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = value
    else:
        raise Phase5EngineCorePluginError("request BlockTable has unsupported shape")
    count = 0
    for row in rows:
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            count += len(row)
        else:
            count += 1
    return count


def _pressure_request(value: Mapping[str, object]) -> NativePressureAllocationRequest:
    watermark = value.get("expected_allocated_blocks_by_request", ())
    if not isinstance(watermark, Sequence) or isinstance(watermark, (str, bytes)):
        raise Phase5EngineCorePluginError("Pressure watermark is not serialized")
    return NativePressureAllocationRequest(
        boundary_id=str(value["boundary_id"]),
        pressure_token_ids=tuple(value["pressure_token_ids"]),  # type: ignore[arg-type]
        pressure_token_ids_sha256=str(value["pressure_token_ids_sha256"]),
        block_size_tokens=int(value["block_size_tokens"]),
        required_blocks=int(value["required_blocks"]),
        expected_free_blocks_before=int(value["expected_free_blocks_before"]),
        expected_allocated_blocks_by_request=tuple(
            (str(row[0]), int(row[1])) for row in watermark  # type: ignore[index]
        ),
    )


def _evidence_export(state: _EngineCoreState) -> dict[str, object]:
    rows = tuple(state.source.snapshot())
    exposure = evaluate_run_candidate_exposure(
        run_id="P5E-A-01", arm="A3_SUFFIX", events=rows
    )
    return {
        "events": [dict(row) for row in rows],
        "candidate_exposure_report": {
            **exposure,
            "downstream_recompute_attribution": "NOT_ESTABLISHED",
            "algorithmic_benefit_claim": "NOT_ESTABLISHED",
        },
        "engine_core_pid": os.getpid(),
    }


def _install(core: object, contract: Mapping[str, object]) -> dict[str, object]:
    if getattr(core, _STATE_ATTRIBUTE, None) is not None:
        raise Phase5EngineCorePluginError("Phase 5 EngineCore integration is already installed")
    configured = contract.get("kv_pool_blocks")
    reserved = contract.get("reserved_null_blocks")
    expected_free = contract.get("expected_initial_free_blocks")
    for name, value in (
        ("kv_pool_blocks", configured),
        ("reserved_null_blocks", reserved),
        ("expected_initial_free_blocks", expected_free),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise Phase5EngineCorePluginError(f"frozen {name} is invalid")
    assert isinstance(configured, int)
    assert isinstance(reserved, int)
    assert isinstance(expected_free, int)
    if configured - reserved != expected_free:
        raise Phase5EngineCorePluginError("frozen KV pool geometry is invalid")
    scheduler = getattr(core, "scheduler", None)
    manager = getattr(scheduler, "kv_cache_manager", None)
    block_pool = getattr(manager, "block_pool", None)
    if scheduler is None or manager is None or block_pool is None:
        raise Phase5EngineCorePluginError("EngineCore Native cache hierarchy is unavailable")
    free = getattr(block_pool, "get_num_free_blocks", None)
    observed_free = free() if callable(free) else None
    if observed_free != expected_free:
        raise Phase5EngineCorePluginError(
            "initial allocatable Native BlockPool differs from freeze: "
            f"configured={configured}, reserved={reserved}, "
            f"expected_free={expected_free}, observed_free={observed_free}"
        )
    source = Phase5ERuntimeEventSource()
    integration = build_phase5e_production_integration(source)
    report = install_phase5e_a3_runtime(
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=SystemMonotonicClock(),
        event_source=source,
    )
    report = {
        **report,
        "execution_process": "ENGINE_CORE",
        "engine_core_pid": os.getpid(),
        "control_transport": "ASYNCMPLCLIENT_UTILITY_RPC",
        "native_objects_cross_process": False,
        "configured_kv_pool_blocks": configured,
        "reserved_null_blocks": reserved,
        "initial_allocatable_kv_blocks": observed_free,
    }
    setattr(
        core,
        _STATE_ATTRIBUTE,
        _EngineCoreState(source, integration, report, expected_free),
    )
    return {"installation_report": report}


def _g9(core: object) -> dict[str, object]:
    state = _state(core)
    read = getattr(state.integration, "a3_retention_input_manifest", None)
    if not callable(read):
        raise Phase5EngineCorePluginError("EngineCore integration lacks G9 provider")
    value = read()
    if not isinstance(value, Mapping):
        raise Phase5EngineCorePluginError("G9 provider did not return an object")
    return dict(value)


def _execute_pressure(
    core: object,
    request_value: Mapping[str, object],
    expected_ids: Sequence[str],
    actual_ids: Sequence[str],
) -> dict[str, object]:
    state = _state(core)
    if tuple(expected_ids) != tuple(actual_ids):
        raise Phase5EngineCorePluginError("frontend Pressure inflight identities differ")
    scheduler = core.scheduler  # type: ignore[attr-defined]
    manager = scheduler.kv_cache_manager
    block_pool = manager.block_pool
    resolve_internal = getattr(state.integration, "internal_request_id", None)
    if not callable(resolve_internal):
        raise Phase5EngineCorePluginError("EngineCore identity resolver is unavailable")

    def watermark(logical_ids: tuple[str, ...]) -> Mapping[str, int]:
        return {
            logical_id: _request_block_count(manager, resolve_internal(logical_id))
            for logical_id in logical_ids
        }

    evidence_reader = RuntimeEventEvidenceSource(
        run_id="P5E-A-01",
        event_reader=state.source.snapshot,
        runtime_installation_report=state.installation_report,
        runtime_integration=state.integration,
    )
    executor = PinnedNativeBlockPoolPressureExecutor(
        block_pool=block_pool,
        adapter_engine_core=core,
        scheduler_engine_core=core,
        kv_instrumentation_engine_core=core,
        evidence_reader=evidence_reader.pressure_outcome,
        allocation_watermark_reader=watermark,
        execution_context_observer=state.integration,
    )
    pressure = executor.execute(
        _pressure_request(request_value),
        expected_inflight_request_ids=tuple(expected_ids),
        actual_inflight_request_ids=tuple(actual_ids),
    )
    return {"pressure": asdict(pressure), "evidence": _evidence_export(state)}


def _export(core: object) -> dict[str, object]:
    return _evidence_export(_state(core))


def _controller_event(
    core: object, event_type: str, payload: Mapping[str, object]
) -> dict[str, object]:
    """Register only controller facts already observed by the frontend."""

    state = _state(core)
    integration = state.integration
    if event_type == "CONTROLLER_ARMED_TIMER":
        method = getattr(integration, "observe_controller_timer_armed", None)
        fields = (
            "candidate_id",
            "chain_id",
            "program_id",
            "session_id",
            "armed_at_timestamp",
            "expires_at_timestamp",
            "clock_domain",
        )
        if not callable(method) or any(field not in payload for field in fields):
            raise Phase5EngineCorePluginError("Controller timer payload is incomplete")
        source_event_index = len(state.source.snapshot())
        method(
            **{field: payload[field] for field in fields},
            source_event_index=source_event_index,
        )
    elif event_type == "DVA_DECISION_IDENTITY":
        method = getattr(integration, "bind_dva_decision_identity", None)
        if not callable(method):
            raise Phase5EngineCorePluginError("DVA identity binding is unavailable")
        method(program_id=payload.get("program_id"), session_id=payload.get("session_id"))
        state.source.emit(
            {
                "event_type": event_type,
                "payload": {
                    "program_id": payload.get("program_id"),
                    "session_id": payload.get("session_id"),
                    "source": "FRONTEND_OBSERVED_CONTROLLER_EVENT",
                },
            }
        )
    else:
        raise Phase5EngineCorePluginError("unsupported controller event type")
    return {
        "status": "PASS",
        "event_type": event_type,
        "engine_core_event_count": len(state.source.snapshot()),
    }


def install_engine_core_methods(engine_core_class: type[object]) -> None:
    """Idempotently patch the exact EngineCore class loaded in this process."""

    if getattr(engine_core_class, _PATCHED_ATTRIBUTE, False):
        return
    original_add = getattr(engine_core_class, "add_request", None)
    if not callable(original_add):
        raise Phase5EngineCorePluginError("EngineCore.add_request is unavailable")

    def add_request(receiver: object, request: object, *args: object, **kwargs: object):
        state = getattr(receiver, _STATE_ATTRIBUTE, None)
        if isinstance(state, _EngineCoreState):
            logical, external, internal = _external_logical_identity(request)
            state.integration.bind_request_identity(
                logical_request_id=logical,
                external_request_id=external,
                internal_request_id=internal,
            )
        return original_add(receiver, request, *args, **kwargs)

    engine_core_class.add_request = add_request  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_install = _install  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_g9 = _g9  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_execute_pressure = _execute_pressure  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_evidence = _export  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_controller_event = _controller_event  # type: ignore[attr-defined]
    setattr(engine_core_class, _PATCHED_ATTRIBUTE, True)


def register_phase5_engine_core_plugin() -> None:
    """Entry point loaded by vLLM in frontend, EngineCore and workers."""

    from vllm.v1.engine.core import EngineCore  # type: ignore[import-not-found]

    install_engine_core_methods(EngineCore)
