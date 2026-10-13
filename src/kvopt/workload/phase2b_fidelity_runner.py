"""Opt-in asynchronous executor for non-holdout Phase 2B fidelity fixtures."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .phase2 import Phase2Trace, PlannedRequest, PressureStage
from .phase2b_fidelity import (
    STATUS_NOT_DEMONSTRATED,
    STATUS_PASS,
    FidelityGateResult,
)


@dataclass(frozen=True, slots=True)
class RequestHandle:
    logical_request_id: str
    native_request_id: str
    external_request_id: str
    submitted_at: float


@dataclass(frozen=True, slots=True)
class RequestCompletion:
    logical_request_id: str
    native_request_id: str
    external_request_id: str
    completed_at: float
    status: str = "success"
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    logical_request_id: str
    program_id: str
    planned_arrival_timestamp: float
    submitted_at: float
    lateness_seconds: float


@dataclass(frozen=True, slots=True)
class AsyncExecutionResult:
    submissions: tuple[SubmissionRecord, ...]
    completions: tuple[RequestCompletion, ...]
    peak_inflight: int
    pressure_attempts: int


class AsyncPhase2Backend(Protocol):
    """A backend whose submit operation never waits for generation completion."""

    def submit(self, request: PlannedRequest) -> RequestHandle: ...

    def collect_completed(
        self, *, until: float | None = None
    ) -> Sequence[RequestCompletion]: ...

    def drain(self, *, timeout_seconds: float) -> Sequence[RequestCompletion]: ...

    @property
    def forced_release_count(self) -> int: ...


class Phase2BExecutionError(RuntimeError):
    """The asynchronous run violated its bounded execution contract."""


def build_inflight_gate(
    result: AsyncExecutionResult,
    *,
    required_peak: int,
    source_event_indices: Sequence[int],
    runtime_identity: dict[str, object],
) -> FidelityGateResult:
    """Qualify request-lifecycle overlap without claiming kernel concurrency."""
    if required_peak < 2:
        raise ValueError("required_peak must be at least two")
    passed = result.peak_inflight >= required_peak
    return FidelityGateResult(
        gate="G-INFLIGHT",
        requested={"peak_inflight": required_peak},
        observed={"peak_inflight": result.peak_inflight},
        status=STATUS_PASS if passed else STATUS_NOT_DEMONSTRATED,
        source_event_indices=tuple(source_event_indices),
        scope="native_request_lifecycle_overlap",
        runtime_identity=runtime_identity,
        reason=(
            "at least the requested number of native requests were submitted "
            "before completion"
            if passed
            else "planned overlap did not produce the requested native in-flight overlap"
        ),
        clock_domain="system_monotonic",
    )


def execute_phase2b_trace(
    trace: Phase2Trace,
    backend: AsyncPhase2Backend,
    *,
    seed: int,
    max_in_flight: int,
    timeout_seconds: float,
    pressure_safety_ceiling: int,
    monotonic: Callable[[], float] = time.monotonic,
    wait_until: Callable[[float], None] | None = None,
) -> AsyncExecutionResult:
    """Submit by absolute trace time and validate every completion exactly once."""
    if max_in_flight < 1:
        raise ValueError("max_in_flight must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if pressure_safety_ceiling < 1:
        raise ValueError("pressure_safety_ceiling must be positive")

    sleep_until = wait_until or (
        lambda target: time.sleep(max(0.0, target - monotonic()))
    )
    run_start = monotonic()
    outstanding: dict[str, tuple[RequestHandle, PlannedRequest]] = {}
    completed_ids: set[str] = set()
    completions: list[RequestCompletion] = []
    submissions: list[SubmissionRecord] = []
    peak_inflight = 0
    pressure_attempts = 0

    def accept(rows: Sequence[RequestCompletion]) -> None:
        for completion in rows:
            logical_id = completion.logical_request_id
            if logical_id in completed_ids:
                raise Phase2BExecutionError(
                    f"duplicate completion for {logical_id}"
                )
            submitted = outstanding.get(logical_id)
            if submitted is None:
                raise Phase2BExecutionError(
                    f"completion for unknown request {logical_id}"
                )
            handle, _request = submitted
            if (
                completion.native_request_id != handle.native_request_id
                or completion.external_request_id != handle.external_request_id
            ):
                raise Phase2BExecutionError(
                    f"completion identity mismatch for {logical_id}"
                )
            if completion.status not in {"success", "failed", "timeout", "cancelled"}:
                raise Phase2BExecutionError(
                    f"unsupported completion status for {logical_id}"
                )
            if completion.status != "success" and not completion.failure_reason:
                raise Phase2BExecutionError(
                    f"failed completion lacks reason for {logical_id}"
                )
            del outstanding[logical_id]
            completed_ids.add(logical_id)
            completions.append(completion)

    def submit(request: PlannedRequest, planned_timestamp: float) -> None:
        nonlocal peak_inflight
        handle = backend.submit(request)
        if handle.logical_request_id != request.request_id:
            raise Phase2BExecutionError("backend handle changed logical request ID")
        if request.request_id in outstanding or request.request_id in completed_ids:
            raise Phase2BExecutionError(f"duplicate submission for {request.request_id}")
        if not handle.native_request_id or not handle.external_request_id:
            raise Phase2BExecutionError("backend handle lacks native/external identity")
        outstanding[request.request_id] = (handle, request)
        submissions.append(
            SubmissionRecord(
                logical_request_id=request.request_id,
                program_id=request.program_id,
                planned_arrival_timestamp=planned_timestamp,
                submitted_at=handle.submitted_at,
                lateness_seconds=max(0.0, handle.submitted_at - planned_timestamp),
            )
        )
        peak_inflight = max(peak_inflight, len(outstanding))

    def wait_for_capacity() -> None:
        while len(outstanding) >= max_in_flight:
            rows = backend.drain(timeout_seconds=timeout_seconds)
            if not rows:
                raise Phase2BExecutionError(
                    "timed out waiting for asynchronous execution capacity"
                )
            accept(rows)

    def drain_all() -> None:
        if not outstanding:
            return
        accept(backend.drain(timeout_seconds=timeout_seconds))
        if outstanding:
            incomplete = ", ".join(sorted(outstanding))
            raise Phase2BExecutionError(
                f"drain returned without terminal states for: {incomplete}"
            )

    def wait_for_program(program_id: str) -> None:
        while any(request.program_id == program_id for _, request in outstanding.values()):
            rows = backend.drain(timeout_seconds=timeout_seconds)
            if not rows:
                raise Phase2BExecutionError(
                    f"timed out waiting for prior turn of {program_id}"
                )
            accept(rows)

    for action in trace.actions():
        planned_timestamp = run_start + action.planned_arrival_offset_seconds
        accept(backend.collect_completed(until=planned_timestamp))
        if monotonic() < planned_timestamp:
            sleep_until(planned_timestamp)

        if isinstance(action, PlannedRequest):
            wait_for_program(action.program_id)
            wait_for_capacity()
            submit(action, planned_timestamp)
            continue

        assert isinstance(action, PressureStage)
        # Default Phase 2B pressure is a barrier: protected target warmups must
        # be complete before allocation pressure begins.
        drain_all()
        ceiling = min(action.max_requests, pressure_safety_ceiling)
        observed_before = backend.forced_release_count
        for attempt in range(1, ceiling + 1):
            pressure_attempts += 1
            request = action.request(attempt, seed)
            submit(request, planned_timestamp)
            drain_all()
            observed_after = backend.forced_release_count
            if observed_after < observed_before:
                raise Phase2BExecutionError(
                    "backend forced_release_count must be monotonic"
                )
            if action.stop_on_forced_release and observed_after > observed_before:
                break

    drain_all()
    failed = [row.logical_request_id for row in completions if row.status != "success"]
    if failed:
        raise Phase2BExecutionError(
            "one or more requests did not complete successfully: "
            + ", ".join(failed)
        )
    return AsyncExecutionResult(
        submissions=tuple(submissions),
        completions=tuple(completions),
        peak_inflight=peak_inflight,
        pressure_attempts=pressure_attempts,
    )
