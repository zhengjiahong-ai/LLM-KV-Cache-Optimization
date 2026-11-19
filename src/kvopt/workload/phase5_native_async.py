"""Phase 5B asynchronous Native integration contracts.

The controller in this module is deliberately backend-neutral.  It maps the
frozen Phase 5 replay plan onto an incremental Native lifecycle without using
the legacy all-pending ``drain_native`` operation.  A real GPU binding must
implement :class:`Phase5AsyncNativeBackend` and expose the Native event stream;
CPU tests use the same contract with a deterministic mock.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from .phase2 import PlannedRequest
from .phase2b_fidelity_runner import RequestCompletion, RequestHandle
from .phase5_replay import (
    EventKind,
    NSessionReplayPlan,
    canonical_sha256,
    evaluate_native_enqueue_order,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class NativeRequestState(StrEnum):
    PLANNED = "PLANNED"
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    NATIVE_COMPLETED = "NATIVE_COMPLETED"
    LOGICAL_COMPLETED = "LOGICAL_COMPLETED"
    FAILED = "FAILED"


class PressureContract(StrEnum):
    QUIESCENT_BARRIER = "QUIESCENT_BARRIER"
    LIVE_STATE = "LIVE_STATE"


@dataclass(frozen=True, slots=True)
class NativePressureAllocationRequest:
    """Frozen input to one real Native BlockPool allocation."""

    boundary_id: str
    pressure_token_ids: tuple[int, ...]
    pressure_token_ids_sha256: str
    block_size_tokens: int
    required_blocks: int
    expected_free_blocks_before: int
    expected_allocated_blocks_by_request: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not self.boundary_id:
            raise ValueError("Native pressure boundary ID must be non-empty")
        if not self.pressure_token_ids or any(
            isinstance(token_id, bool) or not isinstance(token_id, int) or token_id < 0
            for token_id in self.pressure_token_ids
        ):
            raise ValueError("Native pressure token IDs must be non-negative integers")
        if _SHA256.fullmatch(self.pressure_token_ids_sha256) is None:
            raise ValueError("Native pressure token hash must be SHA-256")
        if canonical_sha256(list(self.pressure_token_ids)) != (
            self.pressure_token_ids_sha256
        ):
            raise ValueError("Native pressure token hash mismatch")
        if (
            self.block_size_tokens <= 0
            or self.required_blocks <= 0
            or self.expected_free_blocks_before <= 0
        ):
            raise ValueError("Native pressure block geometry must be positive")
        if len(self.pressure_token_ids) != (
            self.block_size_tokens * self.required_blocks
        ):
            raise ValueError("Native pressure tokens do not match required blocks")
        request_ids = [row[0] for row in self.expected_allocated_blocks_by_request]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("Native pressure allocation watermark IDs must be unique")
        if any(
            not isinstance(request_id, str)
            or not request_id
            or isinstance(blocks, bool)
            or not isinstance(blocks, int)
            or blocks <= 0
            for request_id, blocks in self.expected_allocated_blocks_by_request
        ):
            raise ValueError("Native pressure allocation watermark is invalid")


@dataclass(frozen=True, slots=True)
class PressureBoundary:
    boundary_id: str
    logical_timestamp: float
    contract: PressureContract
    allocation_request: NativePressureAllocationRequest
    expected_inflight_request_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.boundary_id, str) or not self.boundary_id:
            raise ValueError("pressure boundary_id must be non-empty")
        if (
            isinstance(self.logical_timestamp, bool)
            or not isinstance(self.logical_timestamp, (int, float))
            or not math.isfinite(float(self.logical_timestamp))
            or self.logical_timestamp < 0
        ):
            raise ValueError("pressure logical_timestamp must be finite and non-negative")
        if len(self.expected_inflight_request_ids) != len(
            set(self.expected_inflight_request_ids)
        ):
            raise ValueError("pressure expected inflight IDs must be unique")
        if not isinstance(self.contract, PressureContract):
            raise TypeError("pressure contract must be PressureContract")
        if self.allocation_request.boundary_id != self.boundary_id:
            raise ValueError("pressure allocation changed boundary identity")
        if any(
            not isinstance(request_id, str) or not request_id
            for request_id in self.expected_inflight_request_ids
        ):
            raise ValueError("pressure expected inflight IDs must be non-empty strings")
        if (
            self.contract is PressureContract.QUIESCENT_BARRIER
            and self.expected_inflight_request_ids
        ):
            raise ValueError("quiescent pressure cannot declare inflight requests")


@dataclass(frozen=True, slots=True)
class StateTransition:
    ordinal: int
    request_id: str | None
    boundary_id: str | None
    logical_timestamp: float
    native_timestamp: float | None
    previous_state: str | None
    new_state: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Phase5AsyncExecutionResult:
    status: str
    transitions: tuple[StateTransition, ...]
    controller_submission_order: tuple[str, ...]
    native_completion_order: tuple[str, ...]
    logical_completion_order: tuple[str, ...]
    pressure_boundary_ids: tuple[str, ...]
    peak_inflight: int
    enqueue_gate: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.async_native_execution.v1",
            "status": self.status,
            "transitions": [row.to_dict() for row in self.transitions],
            "controller_submission_order": list(self.controller_submission_order),
            "native_completion_order": list(self.native_completion_order),
            "logical_completion_order": list(self.logical_completion_order),
            "pressure_boundary_ids": list(self.pressure_boundary_ids),
            "peak_inflight": self.peak_inflight,
            "enqueue_gate": dict(self.enqueue_gate),
        }


@dataclass(frozen=True, slots=True)
class PressureExecutionEvidence:
    boundary_id: str
    native_snapshot_timestamp: float
    inflight_request_ids: tuple[str, ...]
    pressure_token_ids_sha256: str
    required_blocks: int
    allocated_block_ids: tuple[int, ...]
    free_blocks_before: int
    free_blocks_after_allocation: int
    free_blocks_after_release: int
    allocation_source: str
    engine_core_identity_verified: bool
    forced_release_decision_ids: tuple[str, ...]
    native_evicted_block_ids: tuple[int, ...]
    allocation_watermark_source: str | None = None
    observed_allocated_blocks_by_request: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not self.boundary_id:
            raise ValueError("pressure execution evidence lacks boundary ID")
        if (
            isinstance(self.native_snapshot_timestamp, bool)
            or not isinstance(self.native_snapshot_timestamp, (int, float))
            or not math.isfinite(float(self.native_snapshot_timestamp))
            or self.native_snapshot_timestamp < 0
        ):
            raise ValueError("pressure Native timestamp must be finite and non-negative")
        if len(self.inflight_request_ids) != len(set(self.inflight_request_ids)):
            raise ValueError("pressure execution inflight IDs must be unique")
        if _SHA256.fullmatch(self.pressure_token_ids_sha256) is None:
            raise ValueError("pressure execution token hash must be SHA-256")
        if self.required_blocks <= 0:
            raise ValueError("pressure execution required_blocks must be positive")
        if len(self.allocated_block_ids) != self.required_blocks or len(
            set(self.allocated_block_ids)
        ) != len(self.allocated_block_ids):
            raise ValueError("pressure Native allocation block set is incomplete")
        if self.free_blocks_before - self.free_blocks_after_allocation != (
            self.required_blocks
        ):
            raise ValueError("pressure Native free-block accounting is inconsistent")
        if self.free_blocks_after_release != self.free_blocks_before:
            raise ValueError("pressure Native blocks were not fully released")
        if self.allocation_source != "PINNED_BLOCK_POOL_GET_NEW_BLOCKS":
            raise ValueError("pressure did not use the approved Native allocation path")
        if self.engine_core_identity_verified is not True:
            raise ValueError("pressure EngineCore identity was not verified")
        if not self.forced_release_decision_ids:
            raise ValueError("pressure lacks Forced Entry Release evidence")
        if not self.native_evicted_block_ids:
            raise ValueError("pressure lacks Native physical eviction evidence")
        if self.observed_allocated_blocks_by_request:
            if not self.allocation_watermark_source:
                raise ValueError("pressure allocation watermark lacks its source")
            request_ids = [row[0] for row in self.observed_allocated_blocks_by_request]
            if len(request_ids) != len(set(request_ids)) or any(
                not request_id
                or isinstance(blocks, bool)
                or not isinstance(blocks, int)
                or blocks <= 0
                for request_id, blocks in self.observed_allocated_blocks_by_request
            ):
                raise ValueError("pressure allocation watermark evidence is invalid")
        elif self.allocation_watermark_source is not None:
            raise ValueError("pressure allocation watermark source lacks observations")


class Phase5AsyncNativeBackend(Protocol):
    """Incremental Native lifecycle required by the Phase 5B controller."""

    def prepare_arrival(self, request: PlannedRequest) -> None: ...

    def submit_prepared(self, request_id: str) -> RequestHandle: ...

    def poll_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> Sequence[RequestCompletion]: ...

    def finish_logical_completion(self, request_id: str) -> None: ...

    def execute_pressure(
        self, request: NativePressureAllocationRequest
    ) -> PressureExecutionEvidence: ...

    def native_events(self) -> Sequence[Mapping[str, object]]: ...


@dataclass(slots=True)
class CallbackPhase5NativeAdapter:
    """Concrete adapter surface for a Native engine with incremental polling.

    The callback interface intentionally has no all-pending drain callback.
    GPU integration is therefore blocked until the pinned Native engine can
    supply a genuine incremental poll implementation.
    """

    prepare_arrival_callback: Callable[[PlannedRequest], None]
    submit_prepared_callback: Callable[[str], RequestHandle]
    poll_completed_callback: Callable[[float, bool], Sequence[RequestCompletion]]
    finish_logical_completion_callback: Callable[[str], None]
    execute_pressure_callback: Callable[
        [NativePressureAllocationRequest], PressureExecutionEvidence
    ]
    native_events_callback: Callable[[], Sequence[Mapping[str, object]]]

    def prepare_arrival(self, request: PlannedRequest) -> None:
        self.prepare_arrival_callback(request)

    def submit_prepared(self, request_id: str) -> RequestHandle:
        return self.submit_prepared_callback(request_id)

    def poll_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> Sequence[RequestCompletion]:
        return self.poll_completed_callback(timeout_seconds, wait_for_one)

    def finish_logical_completion(self, request_id: str) -> None:
        self.finish_logical_completion_callback(request_id)

    def execute_pressure(
        self, request: NativePressureAllocationRequest
    ) -> PressureExecutionEvidence:
        return self.execute_pressure_callback(request)

    def native_events(self) -> Sequence[Mapping[str, object]]:
        return self.native_events_callback()


class Phase5NativeExecutionError(RuntimeError):
    """The backend violated the frozen asynchronous execution contract."""


def execute_phase5_native_plan(
    *,
    replay_plan: NSessionReplayPlan,
    workload_seal: Mapping[str, object],
    requests: Mapping[str, PlannedRequest],
    backend: Phase5AsyncNativeBackend,
    maximum_inflight_requests: int,
    completion_timeout_seconds: float,
    pressure_boundaries: Sequence[PressureBoundary] = (),
) -> Phase5AsyncExecutionResult:
    """Execute one frozen N-session plan with incremental completion polling.

    Logical completion remains tied to the frozen replay boundary.  Native
    completions may arrive earlier and are buffered.  When capacity is full,
    the controller waits for incremental progress; it never requests a full
    drain of all in-flight work.
    """

    if (
        isinstance(maximum_inflight_requests, bool)
        or not isinstance(maximum_inflight_requests, int)
        or maximum_inflight_requests < 1
    ):
        raise ValueError("maximum_inflight_requests must be positive")
    if (
        isinstance(completion_timeout_seconds, bool)
        or not isinstance(completion_timeout_seconds, (int, float))
        or not math.isfinite(float(completion_timeout_seconds))
        or completion_timeout_seconds <= 0
    ):
        raise ValueError("completion_timeout_seconds must be finite and positive")
    expected = replay_plan.expected_native_enqueue_order
    if set(requests) != set(expected):
        raise ValueError("request materialization does not match replay plan")
    pressure_ids = [row.boundary_id for row in pressure_boundaries]
    if len(pressure_ids) != len(set(pressure_ids)):
        raise ValueError("pressure boundary IDs must be unique")

    scheduled: list[tuple[float, int, int, str, object]] = []
    for ordinal, row in enumerate(replay_plan.events):
        priority = 0 if row.kind is EventKind.COMPLETION else 2
        scheduled.append((row.logical_timestamp, priority, ordinal, row.event_id, row))
    for ordinal, row in enumerate(pressure_boundaries):
        scheduled.append((row.logical_timestamp, 1, ordinal, row.boundary_id, row))
    scheduled.sort(key=lambda row: (row[0], row[1], row[2], row[3]))

    states = {request_id: NativeRequestState.PLANNED for request_id in expected}
    handles: dict[str, RequestHandle] = {}
    native_completed: set[str] = set()
    transitions: list[StateTransition] = []
    submissions: list[str] = []
    native_completion_order: list[str] = []
    logical_completion_order: list[str] = []
    executed_pressure: list[str] = []
    peak = 0

    def transition(
        request_id: str | None,
        new_state: NativeRequestState,
        timestamp: float,
        reason: str,
        *,
        boundary_id: str | None = None,
        native_timestamp: float | None = None,
    ) -> None:
        previous = None if request_id is None else states[request_id]
        if request_id is not None:
            states[request_id] = new_state
        transitions.append(
            StateTransition(
                ordinal=len(transitions) + 1,
                request_id=request_id,
                boundary_id=boundary_id,
                logical_timestamp=timestamp,
                native_timestamp=native_timestamp,
                previous_state=None if previous is None else previous.value,
                new_state=new_state.value if request_id is not None else "PRESSURE_EXECUTED",
                reason=reason,
            )
        )

    def accept(rows: Sequence[RequestCompletion], logical_timestamp: float) -> int:
        accepted = 0
        seen_batch: set[str] = set()
        for completion in rows:
            request_id = completion.logical_request_id
            if request_id in seen_batch:
                raise Phase5NativeExecutionError("one poll returned duplicate completions")
            seen_batch.add(request_id)
            handle = handles.get(request_id)
            if handle is None or states.get(request_id) is not NativeRequestState.SUBMITTED:
                raise Phase5NativeExecutionError(
                    f"completion for unknown or non-submitted request {request_id}"
                )
            if (
                completion.native_request_id != handle.native_request_id
                or completion.external_request_id != handle.external_request_id
            ):
                raise Phase5NativeExecutionError(
                    f"completion identity mismatch for {request_id}"
                )
            if (
                isinstance(completion.completed_at, bool)
                or not isinstance(completion.completed_at, (int, float))
                or not math.isfinite(float(completion.completed_at))
                or completion.completed_at < handle.submitted_at
            ):
                raise Phase5NativeExecutionError(
                    f"completion Native timestamp precedes submission for {request_id}"
                )
            if completion.status not in {"success", "failed", "timeout", "cancelled"}:
                raise Phase5NativeExecutionError(
                    f"unsupported completion status for {request_id}"
                )
            if completion.status != "success":
                if not completion.failure_reason:
                    raise Phase5NativeExecutionError(
                        f"failed completion lacks reason for {request_id}"
                    )
                transition(
                    request_id,
                    NativeRequestState.FAILED,
                    logical_timestamp,
                    completion.failure_reason,
                )
                raise Phase5NativeExecutionError(
                    f"Native request {request_id} ended as {completion.status}"
                )
            native_completed.add(request_id)
            native_completion_order.append(request_id)
            transition(
                request_id,
                NativeRequestState.NATIVE_COMPLETED,
                logical_timestamp,
                "INCREMENTAL_NATIVE_COMPLETION",
                    native_timestamp=completion.completed_at,
            )
            accepted += 1
        return accepted

    def wait_for_progress(logical_timestamp: float) -> None:
        rows = backend.poll_completed(
            timeout_seconds=float(completion_timeout_seconds),
            wait_for_one=True,
        )
        if not rows or accept(rows, logical_timestamp) == 0:
            raise Phase5NativeExecutionError(
                "incremental Native poll made no progress while progress was required"
            )

    for logical_timestamp, _priority, _ordinal, _identity, item in scheduled:
        if isinstance(item, PressureBoundary):
            observed_inflight = tuple(
                request_id
                for request_id in expected
                if states[request_id] is NativeRequestState.SUBMITTED
            )
            if item.contract is PressureContract.QUIESCENT_BARRIER:
                while observed_inflight:
                    wait_for_progress(logical_timestamp)
                    observed_inflight = tuple(
                        request_id
                        for request_id in expected
                        if states[request_id] is NativeRequestState.SUBMITTED
                    )
            elif set(observed_inflight) != set(item.expected_inflight_request_ids):
                raise Phase5NativeExecutionError(
                    f"live pressure inflight set mismatch at {item.boundary_id}"
                )
            pressure_evidence = backend.execute_pressure(item.allocation_request)
            if pressure_evidence.boundary_id != item.boundary_id:
                raise Phase5NativeExecutionError("pressure evidence changed boundary ID")
            if pressure_evidence.pressure_token_ids_sha256 != (
                item.allocation_request.pressure_token_ids_sha256
            ) or pressure_evidence.required_blocks != (
                item.allocation_request.required_blocks
            ):
                raise Phase5NativeExecutionError(
                    "pressure evidence changed frozen allocation input"
                )
            if set(pressure_evidence.inflight_request_ids) != set(observed_inflight):
                raise Phase5NativeExecutionError(
                    "pressure Native snapshot inflight set mismatch"
                )
            executed_pressure.append(item.boundary_id)
            transition(
                None,
                NativeRequestState.PLANNED,
                logical_timestamp,
                "FROZEN_PRESSURE_BOUNDARY",
                boundary_id=item.boundary_id,
                native_timestamp=pressure_evidence.native_snapshot_timestamp,
            )
            continue
        request_id = item.request_id
        if item.kind is EventKind.ARRIVAL:
            while sum(
                state is NativeRequestState.SUBMITTED for state in states.values()
            ) >= maximum_inflight_requests:
                wait_for_progress(logical_timestamp)
            if states[request_id] is not NativeRequestState.PLANNED:
                raise Phase5NativeExecutionError("arrival state is not PLANNED")
            backend.prepare_arrival(requests[request_id])
            transition(
                request_id,
                NativeRequestState.PREPARED,
                logical_timestamp,
                "FROZEN_LOGICAL_ARRIVAL",
            )
            handle = backend.submit_prepared(request_id)
            if handle.logical_request_id != request_id:
                raise Phase5NativeExecutionError("backend changed logical request ID")
            if not handle.native_request_id or not handle.external_request_id:
                raise Phase5NativeExecutionError("backend handle lacks Native identity")
            if (
                isinstance(handle.submitted_at, bool)
                or not isinstance(handle.submitted_at, (int, float))
                or not math.isfinite(float(handle.submitted_at))
                or handle.submitted_at < 0
            ):
                raise Phase5NativeExecutionError("backend handle has invalid Native timestamp")
            handles[request_id] = handle
            submissions.append(request_id)
            transition(
                request_id,
                NativeRequestState.SUBMITTED,
                logical_timestamp,
                "ASYNC_NATIVE_SUBMISSION",
                native_timestamp=handle.submitted_at,
            )
            peak = max(
                peak,
                sum(state is NativeRequestState.SUBMITTED for state in states.values()),
            )
        else:
            while states[request_id] is NativeRequestState.SUBMITTED:
                wait_for_progress(logical_timestamp)
            if states[request_id] is not NativeRequestState.NATIVE_COMPLETED:
                raise Phase5NativeExecutionError(
                    f"logical completion lacks successful Native completion: {request_id}"
                )
            backend.finish_logical_completion(request_id)
            native_completed.remove(request_id)
            logical_completion_order.append(request_id)
            transition(
                request_id,
                NativeRequestState.LOGICAL_COMPLETED,
                logical_timestamp,
                "FROZEN_LOGICAL_COMPLETION",
            )

    if any(state is not NativeRequestState.LOGICAL_COMPLETED for state in states.values()):
        raise Phase5NativeExecutionError("execution ended with incomplete request states")
    if native_completed:
        raise Phase5NativeExecutionError("execution ended with unconsumed Native completions")
    if tuple(submissions) != expected:
        raise Phase5NativeExecutionError("controller submission order drifted from replay plan")
    enqueue_gate = evaluate_native_enqueue_order(
        seal=workload_seal,
        events=backend.native_events(),
    )
    if enqueue_gate.get("status") != "PASS":
        raise Phase5NativeExecutionError("actual Native enqueue-order gate failed")
    return Phase5AsyncExecutionResult(
        status="PASS",
        transitions=tuple(transitions),
        controller_submission_order=tuple(submissions),
        native_completion_order=tuple(native_completion_order),
        logical_completion_order=tuple(logical_completion_order),
        pressure_boundary_ids=tuple(executed_pressure),
        peak_inflight=peak,
        enqueue_gate=enqueue_gate,
    )
