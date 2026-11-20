"""Pinned same-core runtime installation for Phase 5E Part A.

This module deliberately does not construct synthetic A3 state.  The caller
must supply the reviewed retention integration populated from live request
lifecycle evidence.  Installation fails closed before touching vLLM when the
pinned source identity or EngineCore ownership differs from the reviewed
contract.
"""

from __future__ import annotations

import hashlib
import importlib
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from kvopt.continuum.clock import Clock
from kvopt.continuum.config import RetentionMode
from kvopt.profiling.experiment_events import ExperimentEvent
from kvopt.runtime.vllm.observer import install_retention_hook

PINNED_VLLM_SOURCE_SHA256 = {
    "vllm.v1.core.block_pool": (
        "51cad2fd425128a0ff433ca4685acfc022e40659153ea5d7180fc586e1eebb6c"
    ),
    "vllm.v1.core.kv_cache_manager": (
        "70f7f608c0963af155540630a5633483e5c19c0c0280dfd621760d5db2a419a6"
    ),
    "vllm.v1.core.sched.scheduler": (
        "c67bda2886b52865ddafabaae7d797c359e930752f374421a33e537d94a5f45a"
    ),
}


class Phase5ENativeRuntimeError(RuntimeError):
    """The live runtime cannot satisfy the reviewed same-core contract."""


def validate_pinned_vllm_source_identity() -> dict[str, str]:
    """Hash the three reviewed vLLM modules from their installed locations."""

    observed: dict[str, str] = {}
    for module_name, expected_sha256 in PINNED_VLLM_SOURCE_SHA256.items():
        module = importlib.import_module(module_name)
        source_path_value = getattr(module, "__file__", None)
        if not isinstance(source_path_value, str) or not source_path_value:
            raise Phase5ENativeRuntimeError(
                f"pinned vLLM source path is unavailable: {module_name}"
            )
        source_path = Path(source_path_value)
        if not source_path.is_file():
            raise Phase5ENativeRuntimeError(
                f"pinned vLLM source file is unavailable: {module_name}"
            )
        observed_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if observed_sha256 != expected_sha256:
            raise Phase5ENativeRuntimeError(
                f"pinned vLLM source identity mismatch: {module_name}"
            )
        observed[module_name] = observed_sha256
    return observed


class Phase5ERuntimeEventSource:
    """Thread-safe append-only evidence source owned by one EngineCore."""

    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []
        self._lock = threading.Lock()
        self._installation_report: dict[str, object] | None = None

    def emit(self, event: ExperimentEvent | Mapping[str, object]) -> None:
        """Append one immutable event and assign its stable stream index."""

        if isinstance(event, ExperimentEvent):
            row: dict[str, object] = {
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "clock_domain": event.clock_domain,
                "source": event.source,
                "native_request_id": event.native_request_id,
                "program_id": (
                    None if event.program_id is None else event.program_id.value
                ),
                "request_id": (
                    None if event.request_id is None else event.request_id.value
                ),
                "prefix_id": (
                    None
                    if event.prefix_id is None
                    else event.prefix_id.canonical_value
                ),
                "payload": event.payload.to_dict(),
            }
        elif isinstance(event, Mapping):
            row = dict(event)
            if "event_index" in row:
                raise Phase5ENativeRuntimeError(
                    "runtime event producer cannot assign event_index"
                )
            if not isinstance(row.get("event_type"), str):
                raise Phase5ENativeRuntimeError("runtime event_type is missing")
            if not isinstance(row.get("payload"), Mapping):
                raise Phase5ENativeRuntimeError("runtime event payload is missing")
        else:
            raise TypeError("runtime event must be ExperimentEvent or Mapping")
        with self._lock:
            row["event_index"] = len(self._rows)
            self._rows.append(row)

    def snapshot(self) -> Sequence[Mapping[str, object]]:
        """Return a detached complete prefix for fail-closed evaluation."""

        with self._lock:
            return tuple(dict(row) for row in self._rows)

    def installation_report(self) -> Mapping[str, object]:
        """Return the verified installation identity or fail closed."""

        with self._lock:
            if self._installation_report is None:
                raise Phase5ENativeRuntimeError(
                    "runtime event source is not attached to a controlled A3 hook"
                )
            return dict(self._installation_report)

    def _mark_installed(self, report: Mapping[str, object]) -> None:
        with self._lock:
            if self._installation_report is not None:
                raise Phase5ENativeRuntimeError("runtime event source is already installed")
            self._installation_report = dict(report)


def install_phase5e_a3_runtime(
    *,
    engine_core: object,
    scheduler: object,
    kv_cache_manager: object,
    block_pool: object,
    integration: object,
    clock: Clock,
    event_source: Phase5ERuntimeEventSource,
) -> dict[str, object]:
    """Install controlled A3 selection on one verified in-process EngineCore.

    ``integration`` must be the reviewed live A3 integration and must emit its
    decision binding, selection plan and physical outcome to ``event_source``.
    This function never supplies an LRU or empty-state fallback.
    """

    if getattr(engine_core, "scheduler", None) is not scheduler:
        raise Phase5ENativeRuntimeError("Scheduler is not owned by the EngineCore")
    if getattr(scheduler, "kv_cache_manager", None) is not kv_cache_manager:
        raise Phase5ENativeRuntimeError("KVCacheManager is not owned by the Scheduler")
    if getattr(kv_cache_manager, "block_pool", None) is not block_pool:
        raise Phase5ENativeRuntimeError("BlockPool is not owned by the KVCacheManager")
    if not callable(getattr(integration, "apply_pressure", None)) or not callable(
        getattr(integration, "observe_native_eviction", None)
    ):
        raise Phase5ENativeRuntimeError("live A3 integration contract is incomplete")
    integration_source = getattr(integration, "event_source", None)
    if integration_source is not event_source:
        raise Phase5ENativeRuntimeError(
            "live A3 integration is not bound to the same runtime event source"
        )
    if hasattr(engine_core, "kvopt_phase5_event_source"):
        raise Phase5ENativeRuntimeError("EngineCore runtime event source is already installed")

    source_hashes = validate_pinned_vllm_source_identity()
    engine_core.kvopt_phase5_event_source = event_source
    try:
        install_retention_hook(
            mode=RetentionMode.CONTROLLED,
            integration=integration,
            clock=clock,
        )
    except BaseException:
        del engine_core.kvopt_phase5_event_source
        raise
    report = {
        "status": "PASS",
        "mode": "CONTROLLED_A3",
        "same_engine_core": True,
        "source_sha256": source_hashes,
    }
    event_source._mark_installed(report)
    return report
