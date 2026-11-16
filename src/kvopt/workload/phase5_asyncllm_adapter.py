"""Pinned vLLM 0.27.1 AsyncLLM adapter lifecycle contracts.

The adapter deliberately consumes only per-request ``RequestOutputCollector``
objects returned by ``AsyncLLM.add_request``.  The vLLM-owned output handler
remains the sole EngineCore output consumer and continues to own detokenization,
stop-string processing and frontend abort dispatch.

Frontend terminal output and Native terminal confirmation are independent
landmarks.  A request is released to the Phase 5 controller only after both have
been observed.  In particular, successfully sending an abort is not an abort
acknowledgement.
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
    async def get(self) -> object: ...

    def close(self) -> None: ...


class AsyncLLMProtocol(Protocol):
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


class LifecycleEventKind(StrEnum):
    PLANNED_ARRIVAL = "PLANNED_ARRIVAL"
    ADAPTER_DISPATCH_STARTED = "ADAPTER_DISPATCH_STARTED"
    ADAPTER_DISPATCH_RETURNED = "ADAPTER_DISPATCH_RETURNED"
    NATIVE_SUBMISSION_OBSERVED = "NATIVE_SUBMISSION_OBSERVED"
    NATIVE_SCHEDULER_OBSERVED = "NATIVE_SCHEDULER_OBSERVED"
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
    native_request_id: str
    external_request_id: str
    prompt: object
    params: object
    planned_arrival_offset_seconds: float

    def __post_init__(self) -> None:
        _identity(self.logical_request_id, "logical_request_id")
        _identity(self.native_request_id, "native_request_id")
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
    collector: CollectorProtocol | None = None
    collector_task: asyncio.Task[None] | None = None
    dispatch_returned_at: float | None = None
    frontend_terminal_at: float | None = None
    native_terminal_at: float | None = None
    native_terminal_kind: NativeTerminalKind | None = None
    failure_reason: str | None = None
    completion_emitted: bool = False
    abort_dispatched: bool = False
    partial_output_count: int = 0


class AsyncLLMAdapterError(RuntimeError):
    """The pinned adapter or Native lifecycle violated its contract."""


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
    if hasattr(engine, "wait_for_completion"):
        raise AsyncLLMAdapterError("batch wait_for_completion is prohibited")


class AsyncLLMNativeAdapter:
    """Incremental adapter around vLLM-owned RequestOutputCollectors.

    Native Core terminal and abort-confirmation evidence is supplied through
    :meth:`confirm_native_terminal` by a separately verified runtime hook.  This
    class never infers that confirmation from frontend ``finished`` or from the
    return of ``AsyncLLM.abort``.
    """

    def __init__(
        self,
        *,
        engine: AsyncLLMProtocol,
        vllm_version: str,
        run_epoch_monotonic: float,
        clock: Callable[[], float] = time.monotonic,
        frontend_has_request: Callable[[str], bool] | None = None,
    ) -> None:
        validate_pinned_asyncllm(engine, vllm_version=vllm_version)
        self._engine = engine
        self._epoch = _timestamp(run_epoch_monotonic, "run_epoch_monotonic")
        self._clock = clock
        self._frontend_has_request = frontend_has_request
        self._records: dict[str, _RequestLifecycle] = {}
        self._native_ids: set[str] = set()
        self._external_ids: set[str] = set()
        self._events: list[LifecycleEvent] = []
        self._completion_queue: asyncio.Queue[RequestCompletion] = asyncio.Queue()
        self._fatal_error: BaseException | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    async def submit(self, spec: AsyncLLMRequestSpec) -> RequestHandle:
        if self._closed:
            raise AsyncLLMAdapterError("adapter is closed")
        if spec.logical_request_id in self._records:
            raise ValueError("logical request identity is not unique")
        if spec.native_request_id in self._native_ids:
            raise ValueError("Native request identity is not unique")
        if spec.external_request_id in self._external_ids:
            raise ValueError("external request identity is not unique")

        planned_target = self._epoch + spec.planned_arrival_offset_seconds
        self._event(
            spec.logical_request_id,
            LifecycleEventKind.PLANNED_ARRIVAL,
            planned_target,
            "ADAPTER_NATIVE_MONOTONIC",
            {"planned_offset_seconds": spec.planned_arrival_offset_seconds},
        )
        started = _timestamp(self._clock(), "dispatch start")
        if started < planned_target:
            raise AsyncLLMAdapterError("dispatch started before frozen arrival target")
        record = _RequestLifecycle(spec=spec)
        self._records[spec.logical_request_id] = record
        self._native_ids.add(spec.native_request_id)
        self._external_ids.add(spec.external_request_id)
        self._event(
            spec.logical_request_id,
            LifecycleEventKind.ADAPTER_DISPATCH_STARTED,
            started,
            "ADAPTER_NATIVE_MONOTONIC",
        )
        try:
            collector = await self._engine.add_request(
                request_id=spec.native_request_id,
                prompt=spec.prompt,
                params=spec.params,
                arrival_time=started,
            )
            returned = _timestamp(self._clock(), "dispatch return")
            if returned < started:
                raise AsyncLLMAdapterError("dispatch return precedes dispatch start")
            record.collector = collector
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
                native_request_id=spec.native_request_id,
                external_request_id=spec.external_request_id,
                submitted_at=returned,
            )
        except Exception as error:
            await self._cleanup_failed_dispatch(record, error)
            raise

    def observe_native_submission(
        self, logical_request_id: str, *, timestamp: float, native_request_id: str
    ) -> None:
        record = self._record(logical_request_id)
        if native_request_id != record.spec.native_request_id:
            raise AsyncLLMAdapterError("Native submission identity mismatch")
        self._event(
            logical_request_id,
            LifecycleEventKind.NATIVE_SUBMISSION_OBSERVED,
            _timestamp(timestamp, "Native submission timestamp"),
            "ENGINE_CORE_MONOTONIC",
            {"native_request_id": native_request_id},
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

    async def abort(self, logical_request_id: str) -> None:
        record = self._record(logical_request_id)
        await self._engine.abort(record.spec.native_request_id, internal=False)
        if not record.abort_dispatched:
            record.abort_dispatched = True
            self._event(
                logical_request_id,
                LifecycleEventKind.NATIVE_ABORT_DISPATCHED,
                self._clock(),
                "ADAPTER_NATIVE_MONOTONIC",
                {"confirmation": "NOT_IMPLIED_BY_SEND_RETURN"},
            )

    def observe_internal_abort_dispatched(self, logical_request_id: str) -> None:
        """Record vLLM's stop-string abort dispatch without treating it as an ack."""

        record = self._record(logical_request_id)
        if record.abort_dispatched:
            return
        record.abort_dispatched = True
        self._event(
            logical_request_id,
            LifecycleEventKind.NATIVE_ABORT_DISPATCHED,
            self._clock(),
            "ADAPTER_NATIVE_MONOTONIC",
            {"source": "VLLM_OUTPUT_HANDLER", "confirmation": "PENDING"},
        )

    def observe_internal_abort_dispatched_by_native_id(
        self, native_request_id: str
    ) -> None:
        self.observe_internal_abort_dispatched(
            self._record_by_native_id(native_request_id).spec.logical_request_id
        )

    async def confirm_natural_terminal_by_native_id(
        self, native_request_id: str, *, timestamp: float
    ) -> None:
        await self.confirm_native_terminal(
            self._record_by_native_id(native_request_id).spec.logical_request_id,
            kind=NativeTerminalKind.NATURAL,
            timestamp=timestamp,
        )

    async def confirm_native_terminal(
        self,
        logical_request_id: str,
        *,
        kind: NativeTerminalKind,
        timestamp: float,
    ) -> None:
        async with self._lock:
            record = self._record(logical_request_id)
            if record.native_terminal_at is not None:
                raise AsyncLLMAdapterError("Native terminal was confirmed twice")
            if kind is NativeTerminalKind.ABORT_CONFIRMED and not record.abort_dispatched:
                raise AsyncLLMAdapterError("abort confirmation lacks abort dispatch evidence")
            observed = _timestamp(timestamp, "Native terminal timestamp")
            record.native_terminal_at = observed
            record.native_terminal_kind = kind
            self._event(
                logical_request_id,
                LifecycleEventKind.NATIVE_TERMINAL_CONFIRMED,
                observed,
                "ENGINE_CORE_MONOTONIC",
                {"terminal_kind": kind.value},
            )
            self._maybe_emit_completion(record)

    async def collect_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> tuple[RequestCompletion, ...]:
        timeout = _timestamp(timeout_seconds, "completion timeout")
        if self._fatal_error is not None:
            raise AsyncLLMAdapterError("collector pump failed") from self._fatal_error
        if wait_for_one and timeout == 0:
            raise ValueError("wait_for_one requires a positive timeout")
        rows: list[RequestCompletion] = []
        if wait_for_one:
            try:
                rows.append(
                    await asyncio.wait_for(self._completion_queue.get(), timeout=timeout)
                )
            except TimeoutError:
                return ()
        while not self._completion_queue.empty():
            rows.append(self._completion_queue.get_nowait())
        return tuple(rows)

    async def shutdown(self, *, require_native_confirmation: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        for record in tuple(self._records.values()):
            if record.completion_emitted:
                continue
            if not record.abort_dispatched:
                try:
                    await self._engine.abort(record.spec.native_request_id, internal=True)
                    record.abort_dispatched = True
                    self._event(
                        record.spec.logical_request_id,
                        LifecycleEventKind.NATIVE_ABORT_DISPATCHED,
                        self._clock(),
                        "ADAPTER_NATIVE_MONOTONIC",
                        {"source": "ADAPTER_SHUTDOWN", "confirmation": "PENDING"},
                    )
                except Exception as error:  # noqa: BLE001 - external engine boundary
                    self._mark_failure(record, error, "SHUTDOWN_ABORT_FAILED")
            if record.collector_task is not None and not record.collector_task.done():
                record.collector_task.cancel()
            if record.collector is not None:
                record.collector.close()
        tasks = [
            record.collector_task
            for record in self._records.values()
            if record.collector_task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._event(
            None,
            LifecycleEventKind.ADAPTER_SHUTDOWN,
            self._clock(),
            "ADAPTER_NATIVE_MONOTONIC",
        )
        leaked = self._frontend_leaks()
        unresolved = sorted(
            record.spec.logical_request_id
            for record in self._records.values()
            if not record.completion_emitted and record.native_terminal_at is None
        )
        if leaked:
            raise AsyncLLMAdapterError(f"frontend RequestState leaked: {leaked}")
        if require_native_confirmation and unresolved:
            raise AsyncLLMAdapterError(
                f"Native terminal confirmation missing at shutdown: {unresolved}"
            )

    def report(self) -> dict[str, object]:
        requests = []
        for request_id in sorted(self._records):
            record = self._records[request_id]
            requests.append(
                {
                    "logical_request_id": request_id,
                    "native_request_id": record.spec.native_request_id,
                    "external_request_id": record.spec.external_request_id,
                    "dispatch_returned": record.dispatch_returned_at is not None,
                    "partial_output_count": record.partial_output_count,
                    "output_processor_terminal": record.frontend_terminal_at is not None,
                    "native_terminal_confirmed": record.native_terminal_at is not None,
                    "native_terminal_kind": None
                    if record.native_terminal_kind is None
                    else record.native_terminal_kind.value,
                    "abort_dispatched": record.abort_dispatched,
                    "completion_emitted": record.completion_emitted,
                    "failure_reason": record.failure_reason,
                    "collector_task_done": record.collector_task is None
                    or record.collector_task.done(),
                }
            )
        return {
            "schema_version": "phase5.asyncllm_native_adapter.v1",
            "pinned_vllm_version": PINNED_VLLM_VERSION,
            "closed": self._closed,
            "fatal_error": None
            if self._fatal_error is None
            else f"{type(self._fatal_error).__name__}: {self._fatal_error}",
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
                output_request_id = getattr(output, "request_id", None)
                if output_request_id != record.spec.native_request_id:
                    raise AsyncLLMAdapterError("collector output request identity mismatch")
                finished = getattr(output, "finished", None)
                if not isinstance(finished, bool):
                    raise AsyncLLMAdapterError("collector output lacks Boolean finished")
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
            self._fatal_error = error
            self._mark_failure(record, error, "COLLECTOR_PUMP_FAILED")
            try:
                await self._engine.abort(record.spec.native_request_id, internal=True)
                record.abort_dispatched = True
            except Exception as abort_error:  # noqa: BLE001 - cleanup boundary
                self._mark_failure(record, abort_error, "PUMP_FAILURE_ABORT_FAILED")

    async def _cleanup_failed_dispatch(
        self, record: _RequestLifecycle, error: BaseException
    ) -> None:
        self._mark_failure(record, error, "DISPATCH_FAILED")
        try:
            await self._engine.abort(record.spec.native_request_id, internal=True)
            record.abort_dispatched = True
        except Exception as abort_error:  # noqa: BLE001 - cleanup boundary
            self._mark_failure(record, abort_error, "DISPATCH_ROLLBACK_FAILED")
        if self._frontend_has_request is not None and self._frontend_has_request(
            record.spec.native_request_id
        ):
            raise AsyncLLMAdapterError("dispatch failure leaked frontend RequestState") from error

    def _maybe_emit_completion(self, record: _RequestLifecycle) -> None:
        if record.completion_emitted:
            return
        if record.frontend_terminal_at is None or record.native_terminal_at is None:
            return
        record.completion_emitted = True
        # Native terminal evidence may use EngineCore monotonic while frontend
        # observation uses adapter monotonic.  Never compare those domains.
        completed_at = _timestamp(self._clock(), "completion emission timestamp")
        self._completion_queue.put_nowait(
            RequestCompletion(
                logical_request_id=record.spec.logical_request_id,
                native_request_id=record.spec.native_request_id,
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

    def _record(self, logical_request_id: str) -> _RequestLifecycle:
        request_id = _identity(logical_request_id, "logical_request_id")
        try:
            return self._records[request_id]
        except KeyError as error:
            raise KeyError(f"unknown adapter request: {request_id}") from error

    def _record_by_native_id(self, native_request_id: str) -> _RequestLifecycle:
        identity = _identity(native_request_id, "native_request_id")
        matches = [
            record
            for record in self._records.values()
            if record.spec.native_request_id == identity
        ]
        if len(matches) != 1:
            raise KeyError(f"unknown or ambiguous Native request: {identity}")
        return matches[0]

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
        if self._frontend_has_request is None:
            return []
        return sorted(
            record.spec.native_request_id
            for record in self._records.values()
            if self._frontend_has_request(record.spec.native_request_id)
        )


class PinnedEngineCoreLifecycleProxy:
    """Observe the vLLM-owned Core stream without becoming a second consumer.

    The proxy delegates every attribute to the original client.  It wraps the
    *same* ``get_output_async`` call used by AsyncLLM's single output handler and
    reports terminal Core outputs before returning the unchanged batch.  It also
    observes abort dispatch, but intentionally cannot manufacture an abort ack.
    """

    def __init__(self, delegate: object, adapter: AsyncLLMNativeAdapter) -> None:
        get_output = getattr(delegate, "get_output_async", None)
        abort = getattr(delegate, "abort_requests_async", None)
        if not inspect.iscoroutinefunction(get_output):
            raise AsyncLLMAdapterError("EngineCoreClient.get_output_async is missing")
        if not inspect.iscoroutinefunction(abort):
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
        batch_timestamp = getattr(batch, "timestamp", None)
        if outputs is None:
            raise AsyncLLMAdapterError("EngineCore output batch lacks outputs")
        for output in outputs:
            if getattr(output, "finish_reason", None) is None:
                continue
            if batch_timestamp is None:
                raise AsyncLLMAdapterError(
                    "terminal EngineCore batch lacks monotonic timestamp"
                )
            await self._adapter.confirm_natural_terminal_by_native_id(
                getattr(output, "request_id", None),
                timestamp=batch_timestamp,
            )
        return batch

    async def abort_requests_async(self, request_ids: object) -> object:
        result = await self._delegate.abort_requests_async(request_ids)
        identities = (
            (request_ids,) if isinstance(request_ids, str) else tuple(request_ids)
        )
        for request_id in identities:
            self._adapter.observe_internal_abort_dispatched_by_native_id(request_id)
        return result


def install_pinned_engine_core_lifecycle_proxy(
    engine: object, adapter: AsyncLLMNativeAdapter
) -> PinnedEngineCoreLifecycleProxy:
    """Install the narrow observer on one AsyncLLM instance.

    This changes neither Scheduler nor KV-cache ownership.  Installation fails
    closed if the expected instance attribute cannot be replaced.
    """

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
