"""vLLM general plugin that installs Phase 5 inside EngineCoreProc.

The plugin adds a small Utility RPC surface to the pinned EngineCore class.
Every Native object is resolved and used in the child process; only JSON-like
commands and detached evidence are returned to the frontend.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from kvopt.continuum.clock import SystemMonotonicClock
from kvopt.profiling.phase5_candidate_exposure import evaluate_run_candidate_exposure

from .phase5_asyncllm_adapter import PinnedNativeBlockPoolPressureExecutor
from .phase5_native_async import NativePressureAllocationRequest
from .phase5_system_runtime import validate_system_runtime_identity
from .phase5e_native_evidence_source import RuntimeEventEvidenceSource
from .phase5e_native_runtime import (
    Phase5ERuntimeEventSource,
    install_phase5_calibration_runtime,
    install_phase5e_a3_runtime,
)
from .phase5e_production_integration import (
    build_phase5_calibration_production_integration,
    build_phase5e_production_integration,
)

_STATE_ATTRIBUTE = "_kvopt_phase5_engine_core_state"
_PATCHED_ATTRIBUTE = "_kvopt_phase5_engine_core_plugin_patched"
_SCHEDULER_PATCHED_ATTRIBUTE = "_kvopt_phase5_scheduler_pressure_patched"
_VLLM_REQUEST_SUFFIX = re.compile(r"^(?P<logical>.+)-(?P<suffix>[0-9a-f]{8})$")
_SCHEDULER_CORES: dict[int, object] = {}


class Phase5EngineCorePluginError(RuntimeError):
    """The child-process Native integration violated its frozen contract."""


@dataclass(slots=True)
class _EngineCoreState:
    source: Phase5ERuntimeEventSource
    integration: object
    installation_report: Mapping[str, object]
    expected_initial_free_blocks: int
    run_id: str = "P5E-A-01"
    system_id: str = "A3_SUFFIX"
    request_identity_prefix: str = "P5E-A-01:"
    armed_pressure_request: NativePressureAllocationRequest | None = None
    armed_pressure_ids: tuple[str, ...] = ()
    pressure_result: Mapping[str, object] | None = None
    pressure_max_watermark: dict[str, int] | None = None
    pressure_min_free_blocks: int | None = None


def _state(core: object) -> _EngineCoreState:
    value = getattr(core, _STATE_ATTRIBUTE, None)
    if not isinstance(value, _EngineCoreState):
        raise Phase5EngineCorePluginError("Phase 5 EngineCore integration is not installed")
    return value


def _external_logical_identity(
    request: object, *, identity_prefix: str
) -> tuple[str, str, str]:
    # Pinned vLLM 0.27.1 serializes the caller-supplied request_id directly
    # into EngineCoreRequest. It does not add an ``external_req_id`` field or
    # replace the identity with a second EngineCore-local value.
    external = getattr(request, "request_id", None)
    if not isinstance(external, str) or not external:
        raise Phase5EngineCorePluginError("EngineCore request lacks request identity")
    shadow_external = getattr(request, "external_req_id", None)
    if shadow_external is not None and shadow_external != external:
        raise Phase5EngineCorePluginError("EngineCore request contains conflicting identity fields")
    if not external.startswith(identity_prefix) or len(external) == len(identity_prefix):
        raise Phase5EngineCorePluginError("EngineCore request lacks frozen logical identity")
    serialized_identity = external[len(identity_prefix) :]
    match = _VLLM_REQUEST_SUFFIX.fullmatch(serialized_identity)
    logical = match.group("logical") if match is not None else serialized_identity
    return logical, external, external


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
            (str(row[0]), int(row[1]))
            for row in watermark  # type: ignore[index]
        ),
    )


def _evidence_export(state: _EngineCoreState) -> dict[str, object]:
    finalize = getattr(state.integration, "finalize_pending_physical_outcome", None)
    if callable(finalize):
        finalize()
    rows = tuple(state.source.snapshot())
    exposure = evaluate_run_candidate_exposure(
        run_id=state.run_id, arm=state.system_id, events=rows
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
    schema_version = contract.get("schema_version")
    calibration = schema_version == "phase5.calibration_engine_core_install.v1"
    if not calibration and schema_version not in {None, "phase5e.engine_core_install.v1"}:
        raise Phase5EngineCorePluginError("EngineCore installation schema is unsupported")
    run_id = contract.get("run_id", "P5E-A-01")
    if not isinstance(run_id, str) or not run_id:
        raise Phase5EngineCorePluginError("EngineCore run identity is missing")
    system_id = str(contract.get("system_id", "A3_SUFFIX"))
    if calibration:
        policy_id = str(contract.get("policy_id", ""))
        validate_system_runtime_identity(
            system_id=system_id,
            policy_id=policy_id,
            native_execution_architecture=str(
                contract.get("native_execution_architecture", "")
            ),
        )
    elif contract.get("algorithm", "CONTROLLED_A3") != "CONTROLLED_A3":
        raise Phase5EngineCorePluginError("Part A algorithm identity differs")
    identity_prefix = contract.get("request_identity_prefix", f"{run_id}:")
    if not isinstance(identity_prefix, str) or not identity_prefix:
        raise Phase5EngineCorePluginError("request identity prefix is missing")
    source = Phase5ERuntimeEventSource()
    integration = (
        build_phase5_calibration_production_integration(source, system_id=system_id)
        if calibration
        else build_phase5e_production_integration(source)
    )
    configure_requests = getattr(integration, "configure_frozen_request_ids", None)
    if not callable(configure_requests):
        raise Phase5EngineCorePluginError(
            "EngineCore integration lacks frozen request configuration"
        )
    configure_requests(
        all_request_ids=contract.get("all_logical_request_ids"),
        first_wave_request_ids=contract.get("first_wave_logical_request_ids", ()),
    )
    if calibration:
        configure_calibration = getattr(
            integration, "configure_calibration_identities", None
        )
        if not callable(configure_calibration):
            raise Phase5EngineCorePluginError(
                "EngineCore integration lacks Calibration identity configuration"
            )
        configure_calibration(
            group_id=contract.get("group_id"),
            session_by_program=contract.get("session_by_program"),
            trace_sha256_by_program=contract.get("trace_sha256_by_program"),
        )
    install = install_phase5_calibration_runtime if calibration else install_phase5e_a3_runtime
    install_kwargs = {
        "engine_core": core,
        "scheduler": scheduler,
        "kv_cache_manager": manager,
        "block_pool": block_pool,
        "integration": integration,
        "clock": SystemMonotonicClock(),
        "event_source": source,
    }
    if calibration:
        install_kwargs["system_id"] = system_id
    report = install(**install_kwargs)
    report = {
        **report,
        "execution_process": "ENGINE_CORE",
        "engine_core_pid": os.getpid(),
        "control_transport": "ASYNCMPLCLIENT_UTILITY_RPC",
        "native_objects_cross_process": False,
        "configured_kv_pool_blocks": configured,
        "reserved_null_blocks": reserved,
        "initial_allocatable_kv_blocks": observed_free,
        "frozen_logical_request_ids": list(contract["all_logical_request_ids"]),
        "frozen_first_wave_request_ids": list(
            contract.get("first_wave_logical_request_ids", ())
        ),
        "run_id": run_id,
        "system_id": system_id,
        "request_identity_prefix": identity_prefix,
    }
    setattr(
        core,
        _STATE_ATTRIBUTE,
        _EngineCoreState(
            source,
            integration,
            report,
            expected_free,
            run_id=run_id,
            system_id=system_id,
            request_identity_prefix=identity_prefix,
        ),
    )
    if not calibration:
        _install_scheduler_pressure_hook(core, scheduler)
    return {"installation_report": report}


def _g9(core: object) -> dict[str, object]:
    state = _state(core)
    readiness = getattr(state.integration, "first_wave_prefix_readiness", None)
    if callable(readiness):
        readiness_value = readiness()
        if not isinstance(readiness_value, Mapping):
            raise Phase5EngineCorePluginError("EngineCore G9 readiness is invalid")
        observed = readiness_value.get("observed_prefix_count")
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise Phase5EngineCorePluginError("EngineCore G9 prefix count is invalid")
        expected_ids = readiness_value.get("expected_first_wave_request_ids")
        observed_ids = readiness_value.get("observed_first_wave_request_ids")
        bound_ids = readiness_value.get("bound_logical_request_ids")
        if (
            not isinstance(expected_ids, list)
            or not isinstance(observed_ids, list)
            or not isinstance(bound_ids, list)
            or len(expected_ids) != 4
            or len(set(expected_ids)) != 4
            or any(not isinstance(value, str) or not value for value in expected_ids)
            or len(observed_ids) != observed
            or len(set(observed_ids)) != observed
            or any(value not in expected_ids for value in observed_ids)
            or any(value not in bound_ids for value in observed_ids)
        ):
            raise Phase5EngineCorePluginError(
                "EngineCore G9 first-wave identity evidence is invalid"
            )
        if observed > 4:
            raise Phase5EngineCorePluginError("EngineCore G9 observed excess prefixes")
        if observed < 4:
            return {
                "status": "WAITING_FOR_TERMINAL_PREFIXES",
                **dict(readiness_value),
                "required_prefix_count": 4,
            }
    read = getattr(state.integration, "a3_retention_input_manifest", None)
    if not callable(read):
        raise Phase5EngineCorePluginError("EngineCore integration lacks G9 provider")
    value = read()
    if not isinstance(value, Mapping):
        raise Phase5EngineCorePluginError("G9 provider did not return an object")
    return dict(value)


def _pressure_watermark(
    core: object, state: _EngineCoreState, logical_ids: tuple[str, ...]
) -> dict[str, int]:
    manager = core.scheduler.kv_cache_manager  # type: ignore[attr-defined]
    resolve_internal = getattr(state.integration, "try_internal_request_id", None)
    if not callable(resolve_internal):
        raise Phase5EngineCorePluginError("EngineCore partial identity resolver is unavailable")
    observed: dict[str, int] = {}
    for logical_id in logical_ids:
        internal_id = resolve_internal(logical_id)
        observed[logical_id] = (
            0 if internal_id is None else _request_block_count(manager, internal_id)
        )
    return observed


def _pressure_readiness(core: object, state: _EngineCoreState) -> dict[str, object]:
    request = state.armed_pressure_request
    ids = state.armed_pressure_ids
    if request is None or not ids:
        raise Phase5EngineCorePluginError("Native Pressure boundary is not armed")
    observed = _pressure_watermark(core, state, ids)
    expected = dict(request.expected_allocated_blocks_by_request)
    free = core.scheduler.kv_cache_manager.block_pool.get_num_free_blocks()  # type: ignore[attr-defined]
    previous = state.pressure_max_watermark or {key: 0 for key in expected}
    state.pressure_max_watermark = {
        key: max(previous.get(key, 0), observed[key]) for key in expected
    }
    state.pressure_min_free_blocks = (
        free
        if state.pressure_min_free_blocks is None
        else min(state.pressure_min_free_blocks, free)
    )
    if any(observed[key] > expected[key] for key in expected) or free < request.expected_free_blocks_before:
        raise Phase5EngineCorePluginError("Native Pressure geometry passed its frozen boundary")
    return {
        "status": "WAITING_FOR_PRESSURE_GEOMETRY",
        "expected_allocated_blocks_by_request": sorted(expected.items()),
        "observed_allocated_blocks_by_request": sorted(observed.items()),
        "expected_free_blocks_before": request.expected_free_blocks_before,
        "observed_free_blocks": free,
        "maximum_observed_allocated_blocks_by_request": sorted(
            state.pressure_max_watermark.items()
        ),
        "minimum_observed_free_blocks": state.pressure_min_free_blocks,
    }


def _execute_pressure_now(
    core: object,
    request: NativePressureAllocationRequest,
    expected_ids: tuple[str, ...],
) -> dict[str, object]:
    state = _state(core)
    manager = core.scheduler.kv_cache_manager  # type: ignore[attr-defined]
    block_pool = manager.block_pool

    def watermark(logical_ids: tuple[str, ...]) -> Mapping[str, int]:
        return _pressure_watermark(core, state, logical_ids)

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
        request,
        expected_inflight_request_ids=expected_ids,
        actual_inflight_request_ids=expected_ids,
    )
    return {"pressure": asdict(pressure), "evidence": _evidence_export(state)}


def _arm_pressure(
    core: object,
    request_value: Mapping[str, object],
    expected_ids: Sequence[str],
) -> dict[str, object]:
    state = _state(core)
    request = _pressure_request(request_value)
    ids = tuple(expected_ids)
    if state.armed_pressure_request is not None or state.pressure_result is not None:
        raise Phase5EngineCorePluginError("Native Pressure boundary is already armed")
    if len(ids) != 4 or len(set(ids)) != 4:
        raise Phase5EngineCorePluginError("Native Pressure identities are invalid")
    if tuple(row[0] for row in request.expected_allocated_blocks_by_request) != ids:
        raise Phase5EngineCorePluginError("Pressure watermark identity order differs")
    state.armed_pressure_request = request
    state.armed_pressure_ids = ids
    return {"status": "ARMED", "boundary_id": request.boundary_id}


def _maybe_execute_armed_pressure(core: object) -> None:
    state = _state(core)
    if state.armed_pressure_request is None or state.pressure_result is not None:
        return
    readiness = _pressure_readiness(core, state)
    if (
        readiness["observed_allocated_blocks_by_request"]
        == readiness["expected_allocated_blocks_by_request"]
        and readiness["observed_free_blocks"]
        == readiness["expected_free_blocks_before"]
    ):
        state.pressure_result = _execute_pressure_now(
            core, state.armed_pressure_request, state.armed_pressure_ids
        )


def _execute_pressure(
    core: object,
    request_value: Mapping[str, object],
    expected_ids: Sequence[str],
    actual_ids: Sequence[str],
) -> dict[str, object]:
    state = _state(core)
    if tuple(expected_ids) != tuple(actual_ids):
        raise Phase5EngineCorePluginError("frontend Pressure inflight identities differ")
    request = _pressure_request(request_value)
    if request != state.armed_pressure_request or tuple(expected_ids) != state.armed_pressure_ids:
        raise Phase5EngineCorePluginError("Pressure result request differs from armed boundary")
    if state.pressure_result is not None:
        return dict(state.pressure_result)
    return _pressure_readiness(core, state)


def _install_scheduler_pressure_hook(core: object, scheduler: object) -> None:
    scheduler_class = type(scheduler)
    _SCHEDULER_CORES[id(scheduler)] = core
    if getattr(scheduler_class, _SCHEDULER_PATCHED_ATTRIBUTE, False):
        return
    original_schedule = getattr(scheduler_class, "schedule", None)
    if not callable(original_schedule):
        raise Phase5EngineCorePluginError("Scheduler.schedule is unavailable")

    def schedule(receiver: object, *args: object, **kwargs: object):
        result = original_schedule(receiver, *args, **kwargs)
        bound_core = _SCHEDULER_CORES.get(id(receiver))
        if bound_core is not None:
            _maybe_execute_armed_pressure(bound_core)
        return result

    scheduler_class.schedule = schedule  # type: ignore[attr-defined]
    setattr(scheduler_class, _SCHEDULER_PATCHED_ATTRIBUTE, True)


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
    elif event_type == "CONTROLLER_ARM_TIMER":
        method = getattr(integration, "observe_controller_timer_command", None)
        fields = (
            "candidate_id",
            "chain_id",
            "program_id",
            "session_id",
            "timeout_seconds",
            "predecessor_request_id",
            "successor_request_id",
            "source",
        )
        if not callable(method) or any(field not in payload for field in fields):
            raise Phase5EngineCorePluginError("Controller timer command is incomplete")
        source_event_index = len(state.source.snapshot())
        method(
            **{field: payload[field] for field in fields},
            source_event_index=source_event_index,
        )
    elif event_type == "DVA_DECISION_IDENTITY":
        method = getattr(integration, "bind_dva_decision_identity", None)
        if not callable(method):
            raise Phase5EngineCorePluginError("DVA identity binding is unavailable")
        method(
            program_id=payload.get("program_id"),
            session_id=payload.get("session_id"),
            group_id=payload.get("group_id"),
            turn_id=payload.get("turn_id"),
            trace_sha256=payload.get("trace_sha256"),
        )
        state.source.emit(
            {
                "event_type": event_type,
                "payload": {
                    "program_id": payload.get("program_id"),
                    "session_id": payload.get("session_id"),
                    "group_id": payload.get("group_id"),
                    "turn_id": payload.get("turn_id"),
                    "trace_sha256": payload.get("trace_sha256"),
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
            logical, external, internal = _external_logical_identity(
                request, identity_prefix=state.request_identity_prefix
            )
            state.integration.bind_request_identity(
                logical_request_id=logical,
                external_request_id=external,
                internal_request_id=internal,
            )
        return original_add(receiver, request, *args, **kwargs)

    engine_core_class.add_request = add_request  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_install = _install  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_g9 = _g9  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_arm_pressure = _arm_pressure  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_execute_pressure = _execute_pressure  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_evidence = _export  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_controller_event = _controller_event  # type: ignore[attr-defined]
    setattr(engine_core_class, _PATCHED_ATTRIBUTE, True)


def register_phase5_engine_core_plugin() -> None:
    """Entry point loaded by vLLM in frontend, EngineCore and workers."""

    from vllm.v1.engine.core import EngineCore  # type: ignore[import-not-found]

    install_engine_core_methods(EngineCore)
