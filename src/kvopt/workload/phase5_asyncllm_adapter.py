"""Pinned vLLM 0.27.1 AsyncLLM adapter lifecycle contracts.

The adapter consumes only the per-request ``RequestOutputCollector`` returned by
``AsyncLLM.add_request``. It never becomes a second EngineCore output consumer.
External, internal and logical request identities are deliberately distinct.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Protocol

from .phase2b_fidelity_runner import RequestCompletion, RequestHandle
from .phase5_native_async import (
    NativePressureAllocationRequest,
    PressureExecutionEvidence,
)

PINNED_VLLM_VERSION = "0.27.1"


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _timestamp(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


class CollectorProtocol(Protocol):
    request_id: str

    async def get(self) -> object: ...


class AsyncLLMProtocol(Protocol):
    output_handler: asyncio.Task[None] | None
    engine_core: object

    async def add_request(
        self,
        *,
        request_id: str,
        prompt: object,
        params: object,
        arrival_time: float,
    ) -> CollectorProtocol: ...

    async def abort(self, request_id: str, *, internal: bool = False) -> None: ...


class NativeTerminalKind(StrEnum):
    NATURAL = "NATURAL_CORE_TERMINAL"
    ABORT_CONFIRMED = "ABORT_CONFIRMED"


class AdapterState(StrEnum):
    OPEN = "OPEN"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    CLOSED = "CLOSED"


class LifecycleEventKind(StrEnum):
    PLANNED_ARRIVAL = "PLANNED_ARRIVAL"
    ADAPTER_DISPATCH_STARTED = "ADAPTER_DISPATCH_STARTED"
    ADAPTER_DISPATCH_RETURNED = "ADAPTER_DISPATCH_RETURNED"
    INTERNAL_REQUEST_ID_BOUND = "INTERNAL_REQUEST_ID_BOUND"
    NATIVE_SUBMISSION_OBSERVED = "NATIVE_SUBMISSION_OBSERVED"
    NATIVE_SCHEDULER_OBSERVED = "NATIVE_SCHEDULER_OBSERVED"
    NATIVE_PRESSURE_ALLOCATED = "NATIVE_PRESSURE_ALLOCATED"
    OUTPUT_PROCESSOR_PARTIAL = "OUTPUT_PROCESSOR_PARTIAL"
    OUTPUT_PROCESSOR_TERMINAL = "OUTPUT_PROCESSOR_TERMINAL"
    NATIVE_ABORT_DISPATCHED = "NATIVE_ABORT_DISPATCHED"
    NATIVE_TERMINAL_CONFIRMED = "NATIVE_TERMINAL_CONFIRMED"
    ADAPTER_COMPLETION_EMITTED = "ADAPTER_COMPLETION_EMITTED"
    ADAPTER_REQUEST_FAILED = "ADAPTER_REQUEST_FAILED"
    ADAPTER_SHUTDOWN = "ADAPTER_SHUTDOWN"


@dataclass(frozen=True, slots=True)
class AsyncLLMRequestSpec:
    logical_request_id: str
    external_request_id: str
    prompt: object
    params: object
    planned_arrival_offset_seconds: float

    def __post_init__(self) -> None:
        _identity(self.logical_request_id, "logical_request_id")
        _identity(self.external_request_id, "external_request_id")
        _timestamp(
            self.planned_arrival_offset_seconds,
            "planned_arrival_offset_seconds",
        )


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    index: int
    request_id: str | None
    kind: LifecycleEventKind
    timestamp: float
    clock_domain: str
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["kind"] = self.kind.value
        return row


@dataclass(slots=True)
class _RequestLifecycle:
    spec: AsyncLLMRequestSpec
    internal_request_id: str | None = None
    collector: CollectorProtocol | None = None
    collector_task: asyncio.Task[None] | None = None
    dispatch_returned_at: float | None = None
    frontend_terminal_at: float | None = None
    native_terminal_at: float | None = None
    native_terminal_kind: NativeTerminalKind | None = None
    native_terminal_source: str | None = None
    failure_reason: str | None = None
    completion_emitted: bool = False
    abort_dispatched: bool = False
    abort_in_progress: bool = False
    partial_output_count: int = 0


class AsyncLLMAdapterError(RuntimeError):
    """The pinned adapter or Native lifecycle violated its contract."""


class NativeKVCacheBlockProtocol(Protocol):
    block_id: int


class NativeBlockPoolProtocol(Protocol):
    def get_num_free_blocks(self) -> int: ...

    def get_new_blocks(
        self, num_blocks: int
    ) -> list[NativeKVCacheBlockProtocol]: ...

    def free_blocks(
        self, ordered_blocks: list[NativeKVCacheBlockProtocol]
    ) -> None: ...


@dataclass(slots=True)
class PinnedNativeBlockPoolPressureExecutor:
    """Execute controlled pressure through pinned BlockPool allocation.

    The token input freezes allocation geometry and identity; this executor does
    not claim that the tokens were evaluated by the model.
    """

    block_pool: NativeBlockPoolProtocol
    adapter_engine_core: object
    scheduler_engine_core: object
    kv_instrumentation_engine_core: object
    evidence_reader: Callable[
        [str, tuple[int, ...]], Mapping[str, object]
    ]
    clock: Callable[[], float] = time.monotonic

    def execute(
        self,
        request: NativePressureAllocationRequest,
        *,
        expected_inflight_request_ids: tuple[str, ...],
        actual_inflight_request_ids: tuple[str, ...],
    ) -> PressureExecutionEvidence:
        if not (
            self.adapter_engine_core is self.scheduler_engine_core
            and self.adapter_engine_core is self.kv_instrumentation_engine_core
        ):
            raise AsyncLLMAdapterError(
                "Pressure Adapter, Scheduler and KV instrumentation EngineCore differ"
            )
        scheduler = getattr(self.adapter_engine_core, "scheduler", None)
        kv_cache_manager = getattr(scheduler, "kv_cache_manager", None)
        if getattr(kv_cache_manager, "block_pool", None) is not self.block_pool:
            raise AsyncLLMAdapterError(
                "Pressure BlockPool is not owned by the verified EngineCore"
            )
        if set(actual_inflight_request_ids) != set(expected_inflight_request_ids):
            raise AsyncLLMAdapterError("Pressure Native inflight set mismatch")
        before = self.block_pool.get_num_free_blocks()
        if before != request.expected_free_blocks_before:
            raise AsyncLLMAdapterError(
                "Native BlockPool free count differs from frozen Pressure geometry"
            )
        if before < request.required_blocks:
            raise AsyncLLMAdapterError(
                "Native BlockPool lacks frozen Pressure allocation capacity"
            )
        allocated: list[NativeKVCacheBlockProtocol] = []
        after_allocation = before
        evidence: Mapping[str, object]
        try:
            allocated = self.block_pool.get_new_blocks(request.required_blocks)
            block_ids = tuple(int(block.block_id) for block in allocated)
            after_allocation = self.block_pool.get_num_free_blocks()
            evidence = self.evidence_reader(request.boundary_id, block_ids)
        finally:
            if allocated:
                self.block_pool.free_blocks(allocated)
        after_release = self.block_pool.get_num_free_blocks()
        forced = evidence.get("forced_release_decision_ids")
        evicted = evidence.get("native_evicted_block_ids")
        if not isinstance(forced, (list, tuple)) or not all(
            isinstance(row, str) and row for row in forced
        ):
            raise AsyncLLMAdapterError("Pressure Forced Release evidence is invalid")
        if not isinstance(evicted, (list, tuple)) or not all(
            isinstance(row, int) and not isinstance(row, bool) and row >= 0
            for row in evicted
        ):
            raise AsyncLLMAdapterError("Pressure Native eviction evidence is invalid")
        return PressureExecutionEvidence(
            boundary_id=request.boundary_id,
            native_snapshot_timestamp=_timestamp(self.clock(), "Pressure timestamp"),
            inflight_request_ids=actual_inflight_request_ids,
            pressure_token_ids_sha256=request.pressure_token_ids_sha256,
            required_blocks=request.required_blocks,
            allocated_block_ids=block_ids,
            free_blocks_before=before,
            free_blocks_after_allocation=after_allocation,
            free_blocks_after_release=after_release,
            allocation_source="PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
            engine_core_identity_verified=True,
            forced_release_decision_ids=tuple(forced),
            native_evicted_block_ids=tuple(evicted),
        )


def validate_pinned_asyncllm(engine: object, *, vllm_version: str) -> None:
    """Fail closed on version or public coroutine surface drift."""

    if vllm_version != PINNED_VLLM_VERSION:
        raise AsyncLLMAdapterError(
            f"vLLM version must be {PINNED_VLLM_VERSION}, got {vllm_version}"
        )
    for name in ("add_request", "abort"):
        method = getattr(engine, name, None)
        if method is None or not inspect.iscoroutinefunction(method):
            raise AsyncLLMAdapterError(f"AsyncLLM.{name} must be an async method")
    if not hasattr(engine, "output_handler"):
        raise AsyncLLMAdapterError("AsyncLLM.output_handler is missing")
    if hasattr(engine, "wait_for_completion"):
        raise AsyncLLMAdapterError("batch wait_for_completion is prohibited")


class AsyncLLMNativeAdapter:
    """Incremental, dual-terminal adapter for pinned AsyncLLM."""

    def __init__(
        self,
        *,
        engine: AsyncLLMProtocol,
        vllm_version: str,
        run_epoch_monotonic: float,
        clock: Callable[[], float] = time.monotonic,
        frontend_has_internal_request: Callable[[str], bool] | None = None,
        verified_abort_confirmation_sources: frozenset[str] = frozenset(),
        native_pressure_executor: PinnedNativeBlockPoolPressureExecutor | None = None,
    ) -> None:
        validate_pinned_asyncllm(engine, vllm_version=vllm_version)
        self._engine = engine
        self._epoch = _timestamp(run_epoch_monotonic, "run_epoch_monotonic")
        self._clock = clock
        if frontend_has_internal_request is not None:
            self._frontend_has_internal_request = frontend_has_internal_request
            self._frontend_state_query_source = "INJECTED_INTERNAL_ID_QUERY"
        else:
            output_processor = getattr(engine, "output_processor", None)
            has_request = getattr(output_processor, "has_request", None)
            if callable(has_request):
                self._frontend_has_internal_request = has_request
                self._frontend_state_query_source = (
                    "ASYNCLLM_OUTPUT_PROCESSOR_HAS_REQUEST"
                )
            elif isinstance(
                getattr(output_processor, "request_states", None), Mapping
            ):
                request_states = output_processor.request_states
                self._frontend_has_internal_request = (
                    lambda request_id: request_id in request_states
                )
                self._frontend_state_query_source = (
                    "ASYNCLLM_OUTPUT_PROCESSOR_REQUEST_STATES_MAPPING"
                )
            else:
                self._frontend_has_internal_request = None
                self._frontend_state_query_source = "NOT_OBSERVABLE"
        if any(
            not isinstance(source, str) or not source
            for source in verified_abort_confirmation_sources
        ):
            raise ValueError("verified abort confirmation sources must be non-empty")
        self._verified_abort_confirmation_sources = (
            verified_abort_confirmation_sources
        )
        self._native_pressure_executor = native_pressure_executor
        self._records: dict[str, _RequestLifecycle] = {}
        self._by_external: dict[str, _RequestLifecycle] = {}
        self._by_internal: dict[str, _RequestLifecycle] = {}
        self._events: list[LifecycleEvent] = []
        self._completion_queue: asyncio.Queue[RequestCompletion] = asyncio.Queue()
        self._fatal_event = asyncio.Event()
        self._fatal_error: BaseException | None = None
        self._state = AdapterState.OPEN
        self._lock = asyncio.Lock()
        self._submit_tasks: set[asyncio.Task[object]] = set()
        self._shutdown_task: asyncio.Task[None] | None = None
        self._pending_natural_terminal: dict[str, float] = {}
        self._pending_abort_dispatch: set[str] = set()
        self._core_proxy = install_pinned_engine_core_lifecycle_proxy(engine, self)

    async def submit(self, spec: AsyncLLMRequestSpec) -> RequestHandle:
        task = asyncio.current_task()
        if task is None:
            raise AsyncLLMAdapterError("submit requires an asyncio task")
        record: _RequestLifecycle
        async with self._lock:
            if self._state is not AdapterState.OPEN:
                raise AsyncLLMAdapterError("adapter is not accepting submissions")
            if spec.logical_request_id in self._records:
                raise ValueError("logical request identity is not unique")
            if spec.external_request_id in self._by_external:
                raise ValueError("external request identity is not unique")
            target = self._epoch + spec.planned_arrival_offset_seconds
            started = _timestamp(self._clock(), "dispatch start")
            if started < target:
                raise AsyncLLMAdapterError(
                    "dispatch started before frozen arrival target"
                )
            record = _RequestLifecycle(spec=spec)
            self._records[spec.logical_request_id] = record
            self._by_external[spec.external_request_id] = record
            self._submit_tasks.add(task)
            self._event(
                spec.logical_request_id,
                LifecycleEventKind.PLANNED_ARRIVAL,
                target,
                "ADAPTER_NATIVE_MONOTONIC",
                {"planned_offset_seconds": spec.planned_arrival_offset_seconds},
            )
            self._event(
                spec.logical_request_id,
                LifecycleEventKind.ADAPTER_DISPATCH_STARTED,
                started,
                "ADAPTER_NATIVE_MONOTONIC",
                {"external_request_id": spec.external_request_id},
            )

        try:
            collector = await self._engine.add_request(
                request_id=spec.external_request_id,
                prompt=spec.prompt,
                params=spec.params,
                arrival_time=started,
            )
            internal_id = _identity(
                getattr(collector, "request_id", None),
                "collector internal request_id",
            )
            returned = _timestamp(self._clock(), "dispatch return")
            async with self._lock:
                if internal_id in self._by_internal:
                    raise AsyncLLMAdapterError(
                        "vLLM internal request identity is not unique"
                    )
                record.internal_request_id = internal_id
                record.collector = collector
                self._by_internal[internal_id] = record
                self._event(
                    spec.logical_request_id,
                    LifecycleEventKind.INTERNAL_REQUEST_ID_BOUND,
                    returned,
                    "ADAPTER_NATIVE_MONOTONIC",
                    {
                        "external_request_id": spec.external_request_id,
                        "internal_request_id": internal_id,
                    },
                )
                self._apply_pending_core_evidence(record)
                if self._state is not AdapterState.OPEN:
                    raise AsyncLLMAdapterError(
                        "shutdown began while submission was in flight"
                    )
                record.dispatch_returned_at = returned
                self._event(
                    spec.logical_request_id,
                    LifecycleEventKind.ADAPTER_DISPATCH_RETURNED,
                    returned,
                    "ADAPTER_NATIVE_MONOTONIC",
                )
                record.collector_task = asyncio.create_task(
                    self._consume_collector(record),
                    name=f"phase5-output:{spec.logical_request_id}",
                )
            return RequestHandle(
                logical_request_id=spec.logical_request_id,
                native_request_id=internal_id,
                external_request_id=spec.external_request_id,
                submitted_at=returned,
            )
        except asyncio.CancelledError as error:
            await asyncio.shield(
                self._cleanup_failed_dispatch(record, error, "SUBMIT_CANCELLED")
            )
            raise
        except Exception as error:
            await asyncio.shield(
                self._cleanup_failed_dispatch(record, error, "DISPATCH_FAILED")
            )
            raise
        finally:
            async with self._lock:
                self._submit_tasks.discard(task)

    def observe_native_submission(
        self, logical_request_id: str, *, timestamp: float, internal_request_id: str
    ) -> None:
        record = self._record(logical_request_id)
        if internal_request_id != record.internal_request_id:
            raise AsyncLLMAdapterError("Native submission identity mismatch")
        self._event(
            logical_request_id,
            LifecycleEventKind.NATIVE_SUBMISSION_OBSERVED,
            _timestamp(timestamp, "Native submission timestamp"),
            "ENGINE_CORE_MONOTONIC",
            {"internal_request_id": internal_request_id},
        )

    def observe_scheduler_timing(
        self,
        logical_request_id: str,
        *,
        queued_timestamp: float,
        scheduled_timestamp: float,
    ) -> None:
        queued = _timestamp(queued_timestamp, "Native queued timestamp")
        scheduled = _timestamp(scheduled_timestamp, "Native scheduled timestamp")
        if scheduled < queued:
            raise AsyncLLMAdapterError("Native schedule precedes queue admission")
        self._record(logical_request_id)
        self._event(
            logical_request_id,
            LifecycleEventKind.NATIVE_SCHEDULER_OBSERVED,
            scheduled,
            "ENGINE_CORE_MONOTONIC",
            {"queued_timestamp": queued, "scheduled_timestamp": scheduled},
        )

    async def execute_native_pressure(
        self,
        request: NativePressureAllocationRequest,
        *,
        expected_inflight_request_ids: tuple[str, ...],
    ) -> PressureExecutionEvidence:
        """Allocate and release real blocks through the bound Native BlockPool."""

        if self._native_pressure_executor is None:
            raise AsyncLLMAdapterError("Native Pressure executor is not configured")
        async with self._lock:
            actual = tuple(
                logical_id
                for logical_id, record in self._records.items()
                if record.internal_request_id is not None
                and record.native_terminal_at is None
                and record.failure_reason is None
            )
            if set(actual) != set(expected_inflight_request_ids):
                raise AsyncLLMAdapterError("Pressure Adapter inflight set mismatch")
            result = self._native_pressure_executor.execute(
                request,
                expected_inflight_request_ids=expected_inflight_request_ids,
                actual_inflight_request_ids=actual,
            )
            self._event(
                None,
                LifecycleEventKind.NATIVE_PRESSURE_ALLOCATED,
                result.native_snapshot_timestamp,
                "ENGINE_CORE_MONOTONIC",
                {
                    "boundary_id": request.boundary_id,
                    "required_blocks": request.required_blocks,
                    "allocated_block_ids": list(result.allocated_block_ids),
                    "pressure_token_ids_sha256": request.pressure_token_ids_sha256,
                },
            )
            return result

    async def abort(self, logical_request_id: str) -> None:
        record = self._record(logical_request_id)
        await self._abort_record(
            record,
            source="EXPLICIT_EXTERNAL_ABORT",
            prefer_internal=False,
        )

    async def observe_core_natural_terminal(
        self, internal_request_id: str, *, timestamp: float
    ) -> None:
        internal_id = _identity(internal_request_id, "internal_request_id")
        observed = _timestamp(timestamp, "Native terminal timestamp")
        async with self._lock:
            record = self._by_internal.get(internal_id)
            if record is None:
                if internal_id in self._pending_natural_terminal:
                    raise AsyncLLMAdapterError(
                        "pending Native terminal was observed twice"
                    )
                self._pending_natural_terminal[internal_id] = observed
                return
            self._confirm_native_terminal_locked(
                record,
                kind=NativeTerminalKind.NATURAL,
                timestamp=observed,
                confirmation_source="ENGINE_CORE_TERMINAL_OUTPUT",
            )

    def observe_internal_abort_dispatched(self, internal_request_id: str) -> None:
        internal_id = _identity(internal_request_id, "internal_request_id")
        record = self._by_internal.get(internal_id)
        if record is None:
            self._pending_abort_dispatch.add(internal_id)
            return
        if record.abort_in_progress:
            return
        self._record_abort_dispatch(
            record,
            source="VLLM_OUTPUT_HANDLER_INTERNAL_ABORT",
            identity=internal_id,
            identity_kind="INTERNAL",
        )

    async def confirm_native_terminal(
        self,
        logical_request_id: str,
        *,
        kind: NativeTerminalKind,
        timestamp: float,
        confirmation_source: str,
    ) -> None:
        source = _identity(confirmation_source, "confirmation_source")
        if (
            kind is NativeTerminalKind.ABORT_CONFIRMED
            and source not in self._verified_abort_confirmation_sources
        ):
            raise AsyncLLMAdapterError(
                "abort confirmation source is not independently verified"
            )
        async with self._lock:
            self._confirm_native_terminal_locked(
                self._record(logical_request_id),
                kind=kind,
                timestamp=_timestamp(timestamp, "Native terminal timestamp"),
                confirmation_source=source,
            )

    async def collect_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> tuple[RequestCompletion, ...]:
        timeout = _timestamp(timeout_seconds, "completion timeout")
        self._raise_if_fatal()
        if wait_for_one and timeout == 0:
            raise ValueError("wait_for_one requires a positive timeout")
        rows: list[RequestCompletion] = []
        if wait_for_one:
            completion_wait = asyncio.create_task(self._completion_queue.get())
            fatal_wait = asyncio.create_task(self._fatal_event.wait())
            done, pending = await asyncio.wait(
                {completion_wait, fatal_wait},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                return ()
            self._raise_if_fatal()
            rows.append(completion_wait.result())
        while not self._completion_queue.empty():
            rows.append(self._completion_queue.get_nowait())
        self._raise_if_fatal()
        return tuple(rows)

    async def shutdown(
        self,
        *,
        require_native_confirmation: bool = True,
        require_frontend_observability: bool = False,
    ) -> None:
        async with self._lock:
            if self._shutdown_task is None:
                self._state = AdapterState.SHUTTING_DOWN
                self._shutdown_task = asyncio.create_task(
                    self._shutdown_impl(
                        require_native_confirmation=require_native_confirmation,
                        require_frontend_observability=require_frontend_observability,
                    ),
                    name="phase5-adapter-shutdown",
                )
            shutdown_task = self._shutdown_task
        await asyncio.shield(shutdown_task)

    def report(self) -> dict[str, object]:
        requests = []
        for request_id in sorted(self._records):
            record = self._records[request_id]
            requests.append(
                {
                    "logical_request_id": request_id,
                    "external_request_id": record.spec.external_request_id,
                    "internal_request_id": record.internal_request_id,
                    "dispatch_returned": record.dispatch_returned_at is not None,
                    "partial_output_count": record.partial_output_count,
                    "output_processor_terminal": record.frontend_terminal_at is not None,
                    "native_terminal_confirmed": record.native_terminal_at is not None,
                    "native_terminal_kind": None
                    if record.native_terminal_kind is None
                    else record.native_terminal_kind.value,
                    "native_terminal_source": record.native_terminal_source,
                    "abort_dispatched": record.abort_dispatched,
                    "completion_emitted": record.completion_emitted,
                    "failure_reason": record.failure_reason,
                    "collector_task_done": record.collector_task is None
                    or record.collector_task.done(),
                }
            )
        observability = (
            "OBSERVABLE"
            if self._frontend_has_internal_request is not None
            else "NOT_OBSERVABLE"
        )
        blockers = []
        if observability != "OBSERVABLE":
            blockers.append("REQUEST_STATE_NOT_OBSERVABLE")
        if not self._verified_abort_confirmation_sources:
            blockers.append("ABORT_CONFIRMATION_SOURCE_NOT_ESTABLISHED")
        if self._pending_natural_terminal or self._pending_abort_dispatch:
            blockers.append("UNBOUND_ENGINE_CORE_EVIDENCE")
        return {
            "schema_version": "phase5.asyncllm_native_adapter.v2",
            "pinned_vllm_version": PINNED_VLLM_VERSION,
            "state": self._state.value,
            "request_state_observability": observability,
            "request_state_query_source": self._frontend_state_query_source,
            "verified_abort_confirmation_sources": sorted(
                self._verified_abort_confirmation_sources
            ),
            "gpu_conformance_ready": not blockers,
            "gpu_conformance_blockers": blockers,
            "unbound_core_evidence": {
                "natural_terminal_internal_ids": sorted(
                    self._pending_natural_terminal
                ),
                "abort_dispatch_internal_ids": sorted(
                    self._pending_abort_dispatch
                ),
            },
            "fatal_error": None
            if self._fatal_error is None
            else f"{type(self._fatal_error).__name__}: {self._fatal_error}",
            "active_submit_count": len(self._submit_tasks),
            "requests": requests,
            "events": [event.to_dict() for event in self._events],
            "clock_contract": {
                "planned_dispatch_output": "ADAPTER_NATIVE_MONOTONIC",
                "native_submission_queue_schedule_terminal": "ENGINE_CORE_MONOTONIC",
                "cross_domain_subtraction": "PROHIBITED",
            },
        }

    async def _consume_collector(self, record: _RequestLifecycle) -> None:
        assert record.collector is not None
        try:
            while record.frontend_terminal_at is None:
                output = await record.collector.get()
                if getattr(output, "request_id", None) != record.spec.external_request_id:
                    raise AsyncLLMAdapterError(
                        "processed RequestOutput external identity mismatch"
                    )
                finished = getattr(output, "finished", None)
                if not isinstance(finished, bool):
                    raise AsyncLLMAdapterError(
                        "collector output lacks Boolean finished"
                    )
                async with self._lock:
                    if finished:
                        record.frontend_terminal_at = _timestamp(
                            self._clock(), "frontend terminal timestamp"
                        )
                        self._event(
                            record.spec.logical_request_id,
                            LifecycleEventKind.OUTPUT_PROCESSOR_TERMINAL,
                            record.frontend_terminal_at,
                            "ADAPTER_NATIVE_MONOTONIC",
                        )
                        self._maybe_emit_completion(record)
                    else:
                        record.partial_output_count += 1
                        self._event(
                            record.spec.logical_request_id,
                            LifecycleEventKind.OUTPUT_PROCESSOR_PARTIAL,
                            self._clock(),
                            "ADAPTER_NATIVE_MONOTONIC",
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - collector task boundary
            async with self._lock:
                self._set_fatal(error)
                self._mark_failure(record, error, "COLLECTOR_PUMP_FAILED")
            await self._abort_record(
                record,
                source="COLLECTOR_FAILURE",
                prefer_internal=True,
            )

    async def _cleanup_failed_dispatch(
        self,
        record: _RequestLifecycle,
        error: BaseException,
        prefix: str,
    ) -> None:
        async with self._lock:
            self._mark_failure(record, error, prefix)
        if record.collector is not None:
            self._close_collector(record.collector)
        await self._abort_record(
            record,
            source=f"{prefix}_ROLLBACK",
            prefer_internal=record.internal_request_id is not None,
        )
        leaks = self._frontend_leaks()
        if leaks:
            raise AsyncLLMAdapterError(
                f"dispatch failure leaked frontend RequestState: {leaks}"
            ) from error

    async def _abort_record(
        self,
        record: _RequestLifecycle,
        *,
        source: str,
        prefer_internal: bool,
    ) -> None:
        if record.abort_dispatched:
            return
        use_internal = prefer_internal and record.internal_request_id is not None
        identity = (
            record.internal_request_id
            if use_internal
            else record.spec.external_request_id
        )
        assert identity is not None
        try:
            record.abort_in_progress = True
            await self._engine.abort(identity, internal=use_internal)
            record.abort_in_progress = False
            self._record_abort_dispatch(
                record,
                source=source,
                identity=identity,
                identity_kind="INTERNAL" if use_internal else "EXTERNAL",
            )
        except Exception as error:  # noqa: BLE001 - cleanup boundary
            record.abort_in_progress = False
            async with self._lock:
                self._mark_failure(record, error, f"{source}_ABORT_FAILED")

    async def _shutdown_impl(
        self,
        *,
        require_native_confirmation: bool,
        require_frontend_observability: bool,
    ) -> None:
        try:
            current = asyncio.current_task()
            while True:
                async with self._lock:
                    submits = tuple(
                        task
                        for task in self._submit_tasks
                        if task is not current and not task.done()
                    )
                if not submits:
                    break
                await asyncio.gather(*submits, return_exceptions=True)
            for record in tuple(self._records.values()):
                if not record.completion_emitted:
                    await self._abort_record(
                        record,
                        source="ADAPTER_SHUTDOWN",
                        prefer_internal=True,
                    )
                if record.collector is not None:
                    self._close_collector(record.collector)
                task = record.collector_task
                if task is not None and not task.done():
                    task.cancel()
            collector_tasks = [
                record.collector_task
                for record in self._records.values()
                if record.collector_task is not None
            ]
            if collector_tasks:
                await asyncio.gather(*collector_tasks, return_exceptions=True)
            leaks = self._frontend_leaks()
            unresolved = sorted(
                record.spec.logical_request_id
                for record in self._records.values()
                if not record.completion_emitted and record.native_terminal_at is None
            )
            if require_frontend_observability and (
                self._frontend_has_internal_request is None
            ):
                raise AsyncLLMAdapterError(
                    "frontend RequestState cleanup is NOT_OBSERVABLE"
                )
            if leaks:
                raise AsyncLLMAdapterError(f"frontend RequestState leaked: {leaks}")
            if require_native_confirmation and unresolved:
                raise AsyncLLMAdapterError(
                    f"Native terminal confirmation missing at shutdown: {unresolved}"
                )
        finally:
            async with self._lock:
                self._state = AdapterState.CLOSED
                self._event(
                    None,
                    LifecycleEventKind.ADAPTER_SHUTDOWN,
                    self._clock(),
                    "ADAPTER_NATIVE_MONOTONIC",
                )

    def _apply_pending_core_evidence(self, record: _RequestLifecycle) -> None:
        internal_id = record.internal_request_id
        assert internal_id is not None
        if internal_id in self._pending_abort_dispatch:
            self._pending_abort_dispatch.remove(internal_id)
            self._record_abort_dispatch(
                record,
                source="VLLM_OUTPUT_HANDLER_INTERNAL_ABORT",
                identity=internal_id,
                identity_kind="INTERNAL",
            )
        timestamp = self._pending_natural_terminal.pop(internal_id, None)
        if timestamp is not None:
            self._confirm_native_terminal_locked(
                record,
                kind=NativeTerminalKind.NATURAL,
                timestamp=timestamp,
                confirmation_source="ENGINE_CORE_TERMINAL_OUTPUT",
            )

    def _confirm_native_terminal_locked(
        self,
        record: _RequestLifecycle,
        *,
        kind: NativeTerminalKind,
        timestamp: float,
        confirmation_source: str,
    ) -> None:
        if record.native_terminal_at is not None:
            raise AsyncLLMAdapterError("Native terminal was confirmed twice")
        if kind is NativeTerminalKind.ABORT_CONFIRMED and not record.abort_dispatched:
            raise AsyncLLMAdapterError(
                "abort confirmation lacks abort dispatch evidence"
            )
        record.native_terminal_at = timestamp
        record.native_terminal_kind = kind
        record.native_terminal_source = confirmation_source
        self._event(
            record.spec.logical_request_id,
            LifecycleEventKind.NATIVE_TERMINAL_CONFIRMED,
            timestamp,
            "ENGINE_CORE_MONOTONIC",
            {
                "terminal_kind": kind.value,
                "confirmation_source": confirmation_source,
                "internal_request_id": record.internal_request_id,
            },
        )
        self._maybe_emit_completion(record)

    def _maybe_emit_completion(self, record: _RequestLifecycle) -> None:
        if record.completion_emitted:
            return
        if record.frontend_terminal_at is None or record.native_terminal_at is None:
            return
        if record.internal_request_id is None:
            raise AsyncLLMAdapterError("completion lacks bound internal request ID")
        record.completion_emitted = True
        completed_at = _timestamp(self._clock(), "completion emission timestamp")
        self._completion_queue.put_nowait(
            RequestCompletion(
                logical_request_id=record.spec.logical_request_id,
                native_request_id=record.internal_request_id,
                external_request_id=record.spec.external_request_id,
                completed_at=completed_at,
                status="failed" if record.failure_reason else "success",
                failure_reason=record.failure_reason,
            )
        )
        self._event(
            record.spec.logical_request_id,
            LifecycleEventKind.ADAPTER_COMPLETION_EMITTED,
            completed_at,
            "ADAPTER_NATIVE_MONOTONIC",
        )

    def _record_abort_dispatch(
        self,
        record: _RequestLifecycle,
        *,
        source: str,
        identity: str,
        identity_kind: str,
    ) -> None:
        if record.abort_dispatched:
            return
        record.abort_dispatched = True
        self._event(
            record.spec.logical_request_id,
            LifecycleEventKind.NATIVE_ABORT_DISPATCHED,
            self._clock(),
            "ADAPTER_NATIVE_MONOTONIC",
            {
                "source": source,
                "identity": identity,
                "identity_kind": identity_kind,
                "confirmation": "NOT_IMPLIED_BY_SEND_RETURN",
            },
        )

    def _mark_failure(
        self, record: _RequestLifecycle, error: BaseException, prefix: str
    ) -> None:
        detail = f"{prefix}: {type(error).__name__}: {error}"
        record.failure_reason = (
            detail
            if record.failure_reason is None
            else f"{record.failure_reason}; {detail}"
        )
        self._event(
            record.spec.logical_request_id,
            LifecycleEventKind.ADAPTER_REQUEST_FAILED,
            self._clock(),
            "ADAPTER_NATIVE_MONOTONIC",
            {"failure": detail},
        )

    def _set_fatal(self, error: BaseException) -> None:
        if self._fatal_error is None:
            self._fatal_error = error
            self._fatal_event.set()

    def _raise_if_fatal(self) -> None:
        if self._fatal_error is not None:
            raise AsyncLLMAdapterError("collector pump failed") from self._fatal_error

    def _record(self, logical_request_id: str) -> _RequestLifecycle:
        request_id = _identity(logical_request_id, "logical_request_id")
        try:
            return self._records[request_id]
        except KeyError as error:
            raise KeyError(f"unknown adapter request: {request_id}") from error

    def _event(
        self,
        request_id: str | None,
        kind: LifecycleEventKind,
        timestamp: float,
        clock_domain: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self._events.append(
            LifecycleEvent(
                index=len(self._events),
                request_id=request_id,
                kind=kind,
                timestamp=_timestamp(timestamp, f"{kind.value} timestamp"),
                clock_domain=_identity(clock_domain, "clock_domain"),
                details={} if details is None else dict(details),
            )
        )

    def _frontend_leaks(self) -> list[str]:
        if self._frontend_has_internal_request is None:
            return []
        return sorted(
            internal_id
            for internal_id in self._by_internal
            if self._frontend_has_internal_request(internal_id)
        )

    @staticmethod
    def _close_collector(collector: CollectorProtocol) -> None:
        close = getattr(collector, "close", None)
        if close is not None:
            close()


class PinnedEngineCoreLifecycleProxy:
    """Observe the exact Core stream used by AsyncLLM's output handler."""

    def __init__(self, delegate: object, adapter: AsyncLLMNativeAdapter) -> None:
        if not inspect.iscoroutinefunction(
            getattr(delegate, "get_output_async", None)
        ):
            raise AsyncLLMAdapterError("EngineCoreClient.get_output_async is missing")
        if not inspect.iscoroutinefunction(
            getattr(delegate, "abort_requests_async", None)
        ):
            raise AsyncLLMAdapterError(
                "EngineCoreClient.abort_requests_async is missing"
            )
        self._delegate = delegate
        self._adapter = adapter

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def get_output_async(self) -> object:
        batch = await self._delegate.get_output_async()
        outputs = getattr(batch, "outputs", None)
        timestamp = getattr(batch, "timestamp", None)
        if outputs is None:
            raise AsyncLLMAdapterError("EngineCore output batch lacks outputs")
        for output in outputs:
            if getattr(output, "finish_reason", None) is None:
                continue
            if timestamp is None:
                raise AsyncLLMAdapterError(
                    "terminal EngineCore batch lacks monotonic timestamp"
                )
            await self._adapter.observe_core_natural_terminal(
                getattr(output, "request_id", None), timestamp=timestamp
            )
        return batch

    async def abort_requests_async(self, request_ids: object) -> object:
        result = await self._delegate.abort_requests_async(request_ids)
        identities = (
            (request_ids,) if isinstance(request_ids, str) else tuple(request_ids)
        )
        for request_id in identities:
            self._adapter.observe_internal_abort_dispatched(request_id)
        return result


def install_pinned_engine_core_lifecycle_proxy(
    engine: object, adapter: AsyncLLMNativeAdapter
) -> PinnedEngineCoreLifecycleProxy:
    """Install before AsyncLLM starts its background output handler."""

    if getattr(engine, "output_handler", None) is not None:
        raise AsyncLLMAdapterError(
            "EngineCore observer must be installed before output handler startup"
        )
    delegate = getattr(engine, "engine_core", None)
    if delegate is None:
        raise AsyncLLMAdapterError("AsyncLLM.engine_core is missing")
    if isinstance(delegate, PinnedEngineCoreLifecycleProxy):
        raise AsyncLLMAdapterError("EngineCore lifecycle proxy already installed")
    proxy = PinnedEngineCoreLifecycleProxy(delegate, adapter)
    try:
        engine.engine_core = proxy  # type: ignore[attr-defined]
    except (AttributeError, TypeError) as error:
        raise AsyncLLMAdapterError(
            "AsyncLLM.engine_core cannot be replaced by the observer proxy"
        ) from error
    if engine.engine_core is not proxy:  # type: ignore[attr-defined]
        raise AsyncLLMAdapterError("EngineCore lifecycle proxy installation failed")
    return proxy
