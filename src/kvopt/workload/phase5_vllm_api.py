"""CPU contracts for a pinned-vLLM incremental completion adapter.

This module does not import vLLM.  It models the narrow seam *after* vLLM's
OutputProcessor has converted EngineCore outputs into RequestOutput objects.
That distinction is intentional: EngineCore outputs are incremental and must
not be interpreted as request completion by the Phase 5 controller.
"""

from __future__ import annotations

import math
import queue
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from .phase2b_fidelity_runner import RequestCompletion


def _timestamp(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty")
    return value


class TimingState(StrEnum):
    PLANNED = "PLANNED"
    DISPATCH_STARTED = "DISPATCH_STARTED"
    CLIENT_DISPATCHED = "CLIENT_DISPATCHED"
    OUTPUT_OBSERVED = "OUTPUT_OBSERVED"
    TERMINAL = "TERMINAL"
    DISPATCH_FAILED = "DISPATCH_FAILED"


@dataclass(slots=True)
class _TimingRow:
    request_id: str
    planned_offset_seconds: float
    planned_target_native_monotonic: float
    state: TimingState = TimingState.PLANNED
    dispatch_started_native_monotonic: float | None = None
    dispatch_returned_native_monotonic: float | None = None
    native_queued_engine_monotonic: float | None = None
    native_scheduled_engine_monotonic: float | None = None
    first_processed_output_native_monotonic: float | None = None
    terminal_processed_output_native_monotonic: float | None = None
    engine_core_batch_timestamps: list[float] | None = None
    partial_output_count: int = 0

    def __post_init__(self) -> None:
        self.engine_core_batch_timestamps = []


class NativeArrivalTimingLedger:
    """Keep planned, client-dispatch, scheduler and terminal landmarks separate."""

    def __init__(self, *, run_epoch_native_monotonic: float) -> None:
        self.run_epoch_native_monotonic = _timestamp(
            run_epoch_native_monotonic, "run epoch"
        )
        self._rows: dict[str, _TimingRow] = {}

    def add_planned_request(self, request_id: str, *, planned_offset_seconds: float) -> None:
        identity = _identity(request_id, "request_id")
        if identity in self._rows:
            raise ValueError("request timing identity is not unique")
        offset = _timestamp(planned_offset_seconds, "planned offset")
        self._rows[identity] = _TimingRow(
            request_id=identity,
            planned_offset_seconds=offset,
            planned_target_native_monotonic=self.run_epoch_native_monotonic + offset,
        )

    def dispatch_started(self, request_id: str, *, timestamp: float) -> None:
        row = self._row(request_id)
        observed = _timestamp(timestamp, "dispatch start")
        if row.state is not TimingState.PLANNED:
            raise RuntimeError("dispatch start has invalid predecessor state")
        if observed < row.planned_target_native_monotonic:
            raise ValueError("Native dispatch started before the frozen arrival target")
        row.dispatch_started_native_monotonic = observed
        row.state = TimingState.DISPATCH_STARTED

    def dispatch_returned(self, request_id: str, *, timestamp: float) -> None:
        row = self._row(request_id)
        observed = _timestamp(timestamp, "dispatch return")
        if row.state is not TimingState.DISPATCH_STARTED:
            raise RuntimeError("dispatch return has invalid predecessor state")
        assert row.dispatch_started_native_monotonic is not None
        if observed < row.dispatch_started_native_monotonic:
            raise ValueError("dispatch return precedes dispatch start")
        row.dispatch_returned_native_monotonic = observed
        row.state = TimingState.CLIENT_DISPATCHED

    def dispatch_failed(self, request_id: str) -> None:
        row = self._row(request_id)
        if row.state is not TimingState.DISPATCH_STARTED:
            raise RuntimeError("dispatch failure has invalid predecessor state")
        row.state = TimingState.DISPATCH_FAILED

    def scheduler_observed(
        self,
        request_id: str,
        *,
        queued_engine_monotonic: float,
        scheduled_engine_monotonic: float,
    ) -> None:
        row = self._row(request_id)
        if row.state not in {
            TimingState.CLIENT_DISPATCHED,
            TimingState.OUTPUT_OBSERVED,
            TimingState.TERMINAL,
        }:
            raise RuntimeError("scheduler evidence precedes client dispatch")
        queued = _timestamp(queued_engine_monotonic, "Native queued timestamp")
        scheduled = _timestamp(
            scheduled_engine_monotonic, "Native scheduled timestamp"
        )
        if scheduled < queued:
            raise ValueError("Native scheduled timestamp precedes queued timestamp")
        row.native_queued_engine_monotonic = queued
        row.native_scheduled_engine_monotonic = scheduled

    def processed_output_observed(
        self,
        request_id: str,
        *,
        adapter_timestamp: float,
        engine_core_batch_timestamp: float,
        finished: bool,
    ) -> None:
        row = self._row(request_id)
        observed = _timestamp(adapter_timestamp, "adapter output timestamp")
        core = _timestamp(engine_core_batch_timestamp, "EngineCore batch timestamp")
        if row.state not in {TimingState.CLIENT_DISPATCHED, TimingState.OUTPUT_OBSERVED}:
            raise RuntimeError("processed output has invalid predecessor state")
        assert row.dispatch_returned_native_monotonic is not None
        if observed < row.dispatch_returned_native_monotonic:
            raise ValueError("processed output precedes client dispatch return")
        if row.first_processed_output_native_monotonic is None:
            row.first_processed_output_native_monotonic = observed
        assert row.engine_core_batch_timestamps is not None
        row.engine_core_batch_timestamps.append(core)
        if finished:
            row.terminal_processed_output_native_monotonic = observed
            row.state = TimingState.TERMINAL
        else:
            row.partial_output_count += 1
            row.state = TimingState.OUTPUT_OBSERVED

    def report(self) -> dict[str, object]:
        rows = []
        for request_id in sorted(self._rows):
            row = self._rows[request_id]
            payload = asdict(row)
            payload["state"] = row.state.value
            start = row.dispatch_started_native_monotonic
            returned = row.dispatch_returned_native_monotonic
            payload["arrival_lateness_seconds"] = (
                None if start is None else start - row.planned_target_native_monotonic
            )
            payload["client_dispatch_duration_seconds"] = (
                None if start is None or returned is None else returned - start
            )
            rows.append(payload)
        return {
            "schema_version": "phase5.vllm_arrival_timing.v1",
            "run_epoch_native_monotonic": self.run_epoch_native_monotonic,
            "clock_contract": {
                "planned_target": "RUN_EPOCH_PLUS_FROZEN_LOGICAL_OFFSET",
                "dispatch_and_adapter": "ADAPTER_NATIVE_MONOTONIC",
                "queued_and_scheduled": "ENGINE_CORE_MONOTONIC",
                "engine_core_batch": "ENGINE_CORE_OUTPUT_BATCH_TIMESTAMP",
                "cross_domain_subtraction": "PROHIBITED",
            },
            "requests": rows,
        }

    def _row(self, request_id: str) -> _TimingRow:
        identity = _identity(request_id, "request_id")
        try:
            return self._rows[identity]
        except KeyError as error:
            raise KeyError(f"unknown timing request: {identity}") from error


@dataclass(frozen=True, slots=True)
class ProcessedRequestOutput:
    """One output after vLLM OutputProcessor semantics have been applied."""

    logical_request_id: str
    external_request_id: str
    finished: bool
    engine_core_batch_timestamp: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _RegisteredRequest:
    logical_request_id: str
    native_request_id: str
    external_request_id: str


class VLLMOutputProcessorPump:
    """Single-owner bridge from processed RequestOutputs to local completions."""

    def __init__(self, *, timing: NativeArrivalTimingLedger) -> None:
        self._timing = timing
        self._owner_id: str | None = None
        self._registered: dict[str, _RegisteredRequest] = {}
        self._terminal: set[str] = set()
        self._completions: queue.Queue[RequestCompletion] = queue.Queue()
        self._failed: BaseException | None = None

    def bind_output_owner(self, owner_id: str) -> None:
        identity = _identity(owner_id, "owner_id")
        if self._owner_id is not None:
            raise RuntimeError("vLLM output pump already has an owner")
        self._owner_id = identity

    def register_request(
        self,
        *,
        logical_request_id: str,
        native_request_id: str,
        external_request_id: str,
    ) -> None:
        logical = _identity(logical_request_id, "logical_request_id")
        row = _RegisteredRequest(
            logical,
            _identity(native_request_id, "native_request_id"),
            _identity(external_request_id, "external_request_id"),
        )
        if logical in self._registered or logical in self._terminal:
            raise ValueError("output pump request identity is not unique")
        if any(
            existing.native_request_id == row.native_request_id
            or existing.external_request_id == row.external_request_id
            for existing in self._registered.values()
        ):
            raise ValueError("Native/external request identity is not unique")
        self._registered[logical] = row

    def rollback_registration(self, logical_request_id: str) -> None:
        if self._registered.pop(logical_request_id, None) is None:
            raise KeyError("cannot roll back an unknown request")

    def process_output_batch(
        self,
        *,
        owner_id: str,
        outputs: Sequence[ProcessedRequestOutput],
        adapter_receive_timestamp: float,
    ) -> None:
        if owner_id != self._owner_id:
            raise RuntimeError("only the bound owner may consume vLLM outputs")
        received = _timestamp(adapter_receive_timestamp, "adapter receive timestamp")
        seen: set[str] = set()
        for output in outputs:
            logical = _identity(output.logical_request_id, "logical_request_id")
            if logical in seen:
                raise ValueError("one processed output batch contains duplicate request IDs")
            seen.add(logical)
            registration = self._registered.get(logical)
            if registration is None:
                raise KeyError(f"processed output for unknown request: {logical}")
            if output.external_request_id != registration.external_request_id:
                raise ValueError("processed output external request identity mismatch")
            self._timing.processed_output_observed(
                logical,
                adapter_timestamp=received,
                engine_core_batch_timestamp=output.engine_core_batch_timestamp,
                finished=output.finished,
            )
            if not output.finished:
                continue
            self._registered.pop(logical)
            self._terminal.add(logical)
            self._completions.put_nowait(
                RequestCompletion(
                    logical_request_id=logical,
                    native_request_id=registration.native_request_id,
                    external_request_id=registration.external_request_id,
                    completed_at=received,
                    status="failed" if output.error else "success",
                    failure_reason=output.error,
                )
            )

    def fail_pump(self, error: BaseException, *, timestamp: float) -> None:
        if self._failed is not None:
            raise RuntimeError("output pump failure was reported twice")
        observed = _timestamp(timestamp, "pump failure timestamp")
        self._failed = error
        for logical, registration in tuple(self._registered.items()):
            self._completions.put_nowait(
                RequestCompletion(
                    logical_request_id=logical,
                    native_request_id=registration.native_request_id,
                    external_request_id=registration.external_request_id,
                    completed_at=observed,
                    status="failed",
                    failure_reason=f"OUTPUT_PUMP_FAILED: {type(error).__name__}: {error}",
                )
            )
            self._terminal.add(logical)
            self._registered.pop(logical)

    def collect_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> tuple[RequestCompletion, ...]:
        timeout = _timestamp(timeout_seconds, "completion timeout")
        if wait_for_one and timeout == 0:
            raise ValueError("wait_for_one requires a positive timeout")
        rows: list[RequestCompletion] = []
        if wait_for_one:
            try:
                rows.append(self._completions.get(timeout=timeout))
            except queue.Empty:
                return ()
        while True:
            try:
                rows.append(self._completions.get_nowait())
            except queue.Empty:
                break
        return tuple(rows)

    def state_report(self) -> Mapping[str, object]:
        return {
            "schema_version": "phase5.vllm_output_pump.v1",
            "owner_bound": self._owner_id is not None,
            "outstanding_request_ids": sorted(self._registered),
            "terminal_request_ids": sorted(self._terminal),
            "pump_failure": None
            if self._failed is None
            else f"{type(self._failed).__name__}: {self._failed}",
            "completion_queue_size": self._completions.qsize(),
        }
