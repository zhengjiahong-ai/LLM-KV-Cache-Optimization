"""Observation-only EngineCore plugin for frozen Official Continuum.

This plugin must not alter scheduling, cache selection, pinning or tool-time
estimation. It only validates the frozen Official source/policy and exports
request plus Native APC observations through Utility RPC.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from pathlib import Path

OFFICIAL_REVISION = "316a58794a6ff86b216e579b74fd56ed0c5a911f"
OFFICIAL_SOURCE_SHA256 = {
    "vllm.v1.engine.core": "d1219de0d526b2326a471fe8464b3b8a55730dcab63ea99eb9b15e8b90bb116b",
    "vllm.v1.core.sched.scheduler": "e2f4d30fef5d98ec3d5b8dd50419d3df33aaf074309905e838437bac668b470e",
    "vllm.v1.core.kv_cache_manager": "78eeaf0d466a3aad358353a352993b79610e9838aadde57168235f3f9b4acecd",
}

_STATE = "_kvopt_phase5_official_observer_state"
_PATCHED = "_kvopt_phase5_official_observer_patched"
_MANAGER_STATE = "_kvopt_phase5_official_observer_owner"
_SCHEDULER_STATE = "_kvopt_phase5_official_observer_owner"


class OfficialContinuumObserverError(RuntimeError):
    """Official runtime identity or observation coverage is invalid."""


class _OfficialState:
    def __init__(self, run_id: str, request_prefix: str) -> None:
        self.run_id = run_id
        self.request_prefix = request_prefix
        self.engine_core_pid = os.getpid()
        self._events: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        request_id: str | None = None,
        program_id: str | None = None,
    ) -> None:
        with self._lock:
            self._events.append(
                {
                    "event_index": len(self._events),
                    "event_type": event_type,
                    "timestamp": time.monotonic(),
                    "clock_domain": "OFFICIAL_ENGINE_CORE_MONOTONIC",
                    "request_id": request_id,
                    "program_id": program_id,
                    "payload": dict(payload),
                }
            )

    def export(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(row) for row in self._events]


def validate_official_source_identity() -> dict[str, str]:
    observed = {}
    for module_name, expected in OFFICIAL_SOURCE_SHA256.items():
        module = importlib.import_module(module_name)
        source = Path(str(getattr(module, "__file__", "")))
        if not source.is_file():
            raise OfficialContinuumObserverError(
                f"Official source is unavailable: {module_name}"
            )
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected:
            raise OfficialContinuumObserverError(
                f"Official source identity mismatch: {module_name}"
            )
        observed[module_name] = digest
    return observed


def _policy_value(scheduler: object) -> str:
    value = getattr(scheduler, "policy", None)
    normalized = getattr(value, "value", value)
    return str(normalized).lower()


def _logical_identity(state: _OfficialState, request: object) -> tuple[str, str]:
    external = getattr(request, "request_id", None)
    if not isinstance(external, str) or not external.startswith(state.request_prefix):
        raise OfficialContinuumObserverError(
            "Official request lacks frozen external identity"
        )
    logical = external[len(state.request_prefix) :]
    program_id, separator, _suffix = logical.partition(":")
    if not separator or not program_id:
        raise OfficialContinuumObserverError("Official request lacks Program identity")
    return program_id, logical


def _native_hashes(request: object) -> list[str]:
    values = getattr(request, "block_hashes", None)
    if not isinstance(values, list):
        raise OfficialContinuumObserverError("Official Native hash chain is unavailable")
    result = []
    for value in values:
        if type(value) is not bytes or len(value) != 32:
            raise OfficialContinuumObserverError("Official Native block hash is invalid")
        result.append(value.hex())
    return result


def _install(core: object, contract: Mapping[str, object]) -> dict[str, object]:
    if getattr(core, _STATE, None) is not None:
        raise OfficialContinuumObserverError("Official observer is already installed")
    if contract.get("schema_version") != "phase5.official_continuum_install.v1":
        raise OfficialContinuumObserverError("Official install schema differs")
    if contract.get("system_id") != "CONTINUUM_OFFICIAL":
        raise OfficialContinuumObserverError("Official system identity differs")
    if contract.get("policy_id") != "CONTINUUM_OFFICIAL_316A5879":
        raise OfficialContinuumObserverError("Official policy identity differs")
    if contract.get("source_revision") != OFFICIAL_REVISION:
        raise OfficialContinuumObserverError("Official source revision differs")
    run_id = contract.get("run_id")
    request_prefix = contract.get("request_identity_prefix")
    if not isinstance(run_id, str) or not run_id:
        raise OfficialContinuumObserverError("Official run identity is missing")
    if not isinstance(request_prefix, str) or not request_prefix:
        raise OfficialContinuumObserverError("Official request prefix is missing")
    scheduler = getattr(core, "scheduler", None)
    manager = getattr(scheduler, "kv_cache_manager", None)
    if scheduler is None or manager is None:
        raise OfficialContinuumObserverError("Official Native cache hierarchy is unavailable")
    if _policy_value(scheduler) != "continuum":
        raise OfficialContinuumObserverError("Official Scheduler is not continuum")
    source_hashes = validate_official_source_identity()
    state = _OfficialState(run_id, request_prefix)
    setattr(core, _STATE, state)
    setattr(manager, _MANAGER_STATE, state)
    setattr(scheduler, _SCHEDULER_STATE, state)
    return {
        "installation_report": {
            "status": "PASS",
            "system_id": "CONTINUUM_OFFICIAL",
            "policy_id": "CONTINUUM_OFFICIAL_316A5879",
            "source_revision": OFFICIAL_REVISION,
            "source_sha256": source_hashes,
            "execution_process": "ENGINE_CORE",
            "engine_core_pid": state.engine_core_pid,
            "control_transport": "ASYNCMPLCLIENT_UTILITY_RPC",
            "native_objects_cross_process": False,
            "observation_only": True,
        }
    }


def _evidence(core: object) -> dict[str, object]:
    state = getattr(core, _STATE, None)
    if not isinstance(state, _OfficialState):
        raise OfficialContinuumObserverError("Official observer is not installed")
    return {
        "events": state.export(),
        "engine_core_pid": state.engine_core_pid,
        "system_id": "CONTINUUM_OFFICIAL",
        "policy_id": "CONTINUUM_OFFICIAL_316A5879",
    }


def install_official_observer_methods(
    engine_core_class: type[object],
    kv_cache_manager_class: type[object],
    scheduler_class: type[object],
) -> None:
    if getattr(engine_core_class, _PATCHED, False):
        return
    original_add = getattr(engine_core_class, "add_request", None)
    original_computed = getattr(kv_cache_manager_class, "get_computed_blocks", None)
    original_free = getattr(scheduler_class, "_free_request", None)
    if not all(callable(value) for value in (original_add, original_computed, original_free)):
        raise OfficialContinuumObserverError("Official observation seam is unavailable")

    @wraps(original_add)
    def add_request(receiver: object, request: object, *args: object, **kwargs: object):
        state = getattr(receiver, _STATE, None)
        if isinstance(state, _OfficialState):
            program_id, logical = _logical_identity(state, request)
            state.emit(
                "PHASE5_OFFICIAL_REQUEST_ADDED",
                {
                    "request_id": logical,
                    "job_id": getattr(request, "job_id", None),
                },
                request_id=logical,
                program_id=program_id,
            )
        return original_add(receiver, request, *args, **kwargs)

    @wraps(original_computed)
    def get_computed_blocks(
        receiver: object, request: object, *args: object, **kwargs: object
    ):
        result = original_computed(receiver, request, *args, **kwargs)
        state = getattr(receiver, _MANAGER_STATE, None)
        if isinstance(state, _OfficialState):
            if not isinstance(result, tuple) or len(result) != 2:
                raise OfficialContinuumObserverError(
                    "Official APC observation shape differs"
                )
            computed_tokens = result[1]
            if (
                isinstance(computed_tokens, bool)
                or not isinstance(computed_tokens, int)
                or computed_tokens < 0
            ):
                raise OfficialContinuumObserverError(
                    "Official APC computed-token count is invalid"
                )
            program_id, logical = _logical_identity(state, request)
            prompt_tokens = getattr(request, "num_tokens", None)
            if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int):
                raise OfficialContinuumObserverError(
                    "Official Native prompt-token count is invalid"
                )
            block_size = getattr(receiver, "block_size", None)
            if isinstance(block_size, bool) or not isinstance(block_size, int) or block_size <= 0:
                raise OfficialContinuumObserverError("Official block size is invalid")
            state.emit(
                "VLLM_NATIVE_REQUEST_OBSERVATION",
                {
                    "request_id": logical,
                    "job_id": getattr(request, "job_id", None),
                    "native_prompt_tokens": prompt_tokens,
                    "native_cached_prefix_tokens": computed_tokens,
                    "native_apc_block_hashes": _native_hashes(request),
                    "native_hash_block_size": block_size,
                    "native_hash_process_id": str(state.engine_core_pid),
                    "native_hash_function": "SHA256_CBOR_BYTES",
                    "source": "OFFICIAL_KV_CACHE_MANAGER_GET_COMPUTED_BLOCKS",
                },
                request_id=logical,
                program_id=program_id,
            )
        return result

    @wraps(original_free)
    def free_request(receiver: object, request: object, *args: object, **kwargs: object):
        state = getattr(receiver, _SCHEDULER_STATE, None)
        if isinstance(state, _OfficialState):
            program_id, logical = _logical_identity(state, request)
            block_size = getattr(getattr(receiver, "kv_cache_manager", None), "block_size", None)
            if isinstance(block_size, bool) or not isinstance(block_size, int) or block_size <= 0:
                raise OfficialContinuumObserverError("Official block size is invalid")
            hashes = _native_hashes(request)
            state.emit(
                "VLLM_PREFIX_SNAPSHOT",
                {
                    "ordered_native_hashes": hashes,
                    "hash_num_tokens": len(hashes) * block_size,
                    "native_hash_block_size": block_size,
                    "native_hash_process_id": str(state.engine_core_pid),
                    "native_hash_function": "SHA256_CBOR_BYTES",
                    "source": "OFFICIAL_SCHEDULER_FREE_REQUEST_BEFORE_NATIVE_CALL",
                },
                request_id=logical,
                program_id=program_id,
            )
        return original_free(receiver, request, *args, **kwargs)

    engine_core_class.add_request = add_request  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_official_install = _install  # type: ignore[attr-defined]
    engine_core_class.kvopt_phase5_official_evidence = _evidence  # type: ignore[attr-defined]
    kv_cache_manager_class.get_computed_blocks = get_computed_blocks  # type: ignore[attr-defined]
    scheduler_class._free_request = free_request  # type: ignore[attr-defined]
    setattr(engine_core_class, _PATCHED, True)


def register_phase5_official_observer() -> None:
    from vllm.v1.core.kv_cache_manager import KVCacheManager  # type: ignore[import-not-found]
    from vllm.v1.core.sched.scheduler import Scheduler  # type: ignore[import-not-found]
    from vllm.v1.engine.core import EngineCore  # type: ignore[import-not-found]

    install_official_observer_methods(EngineCore, KVCacheManager, Scheduler)
