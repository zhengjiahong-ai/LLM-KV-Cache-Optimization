"""Materialize and execute the controlled sparse replay timeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from kvopt.continuum import (
    ControlledSparseReplayClock,
    LogicalTimeAdvance,
    LogicalTimeBoundary,
)

from .phase2 import PlannedRequest
from .phase2b_fidelity_runner import RequestCompletion, RequestHandle


class BoundaryKind(StrEnum):
    ARRIVAL = "ARRIVAL"
    COMPLETION = "COMPLETION"
    PRESSURE = "PRESSURE"


@dataclass(frozen=True, slots=True)
class ReplayBoundary:
    boundary_id: str
    logical_timestamp: float
    source: str
    kind: BoundaryKind
    request_id: str | None = None

    def clock_boundary(self) -> LogicalTimeBoundary:
        return LogicalTimeBoundary(
            boundary_id=self.boundary_id,
            logical_timestamp=self.logical_timestamp,
            source=self.source,
        )


@dataclass(frozen=True, slots=True)
class ControlledReplayResult:
    native_submissions: tuple[RequestHandle, ...]
    native_completions: tuple[RequestCompletion, ...]
    peak_inflight: int
    logical_sequence_sha256: str


class ControlledReplayBackend(Protocol):
    """Split lifecycle preparation from Native execution and finalization."""

    def prepare_arrival(self, request: PlannedRequest) -> None: ...

    def record_logical_time_advance(self, advance: LogicalTimeAdvance) -> None: ...

    def submit_prepared(self, request_id: str) -> RequestHandle: ...

    def drain_native(self, *, timeout_seconds: float) -> Sequence[RequestCompletion]: ...

    def finish_logical_completion(self, request_id: str) -> None: ...

    def execute_prepared_pressure(self, boundary_id: str) -> None: ...


def materialize_request_boundaries(
    *,
    sessions: Sequence[Sequence[Mapping[str, object]]],
    cross_session_start_stagger_seconds: float,
) -> tuple[ReplayBoundary, ...]:
    """Build the immutable two-session event sequence from source timestamps."""
    if len(sessions) != 2:
        raise ValueError("controlled replay requires exactly two sessions")
    if cross_session_start_stagger_seconds < 0:
        raise ValueError("cross-session start stagger must be non-negative")
    rows: list[ReplayBoundary] = []
    request_ids: set[str] = set()
    for session_index, calls in enumerate(sessions):
        if not calls:
            raise ValueError("each replay session must contain requests")
        first_submit = calls[0].get("model_submit_monotonic_seconds")
        if not isinstance(first_submit, (int, float)):
            raise TypeError("source submit timestamp must be numeric")
        offset = cross_session_start_stagger_seconds if session_index else 0.0
        previous_submit = float("-inf")
        for call in calls:
            request_id = call.get("request_id")
            submitted = call.get("model_submit_monotonic_seconds")
            completed = call.get("model_completion_monotonic_seconds")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("source request identity must be non-empty")
            if request_id in request_ids:
                raise ValueError("source request identities must be unique")
            if not isinstance(submitted, (int, float)) or not isinstance(
                completed, (int, float)
            ):
                raise TypeError("source request timestamps must be numeric")
            submitted_value = float(submitted)
            completed_value = float(completed)
            if submitted_value < previous_submit:
                raise ValueError("source submissions must be monotonic per session")
            if completed_value < submitted_value:
                raise ValueError("source completion precedes submission")
            previous_submit = submitted_value
            request_ids.add(request_id)
            base = float(first_submit)
            rows.extend(
                (
                    ReplayBoundary(
                        boundary_id=f"arrival:{request_id}",
                        logical_timestamp=offset + submitted_value - base,
                        source="W1C_MODEL_SUBMIT_MONOTONIC_SECONDS",
                        kind=BoundaryKind.ARRIVAL,
                        request_id=request_id,
                    ),
                    ReplayBoundary(
                        boundary_id=f"completion:{request_id}",
                        logical_timestamp=offset + completed_value - base,
                        source="W1C_MODEL_COMPLETION_MONOTONIC_SECONDS",
                        kind=BoundaryKind.COMPLETION,
                        request_id=request_id,
                    ),
                )
            )
    kind_order = {BoundaryKind.ARRIVAL: 0, BoundaryKind.COMPLETION: 1}
    rows.sort(
        key=lambda row: (
            row.logical_timestamp,
            kind_order[row.kind],
            row.boundary_id,
        )
    )
    return tuple(rows)


def insert_pressure_join_boundary(
    *,
    boundaries: Sequence[ReplayBoundary],
    final_request_ids: Sequence[str],
    boundary_id: str,
) -> tuple[ReplayBoundary, ...]:
    """Insert pressure after both penultimate completions and before returns.

    Independently observed sessions often have no common wall-clock interval in
    which both are waiting.  The controlled replay therefore adds only the
    minimum non-negative logical delay needed to create the pre-registered
    two-session pressure join.  It never shortens an observed gap and preserves
    each delayed final request's Native duration.
    """
    finals = tuple(final_request_ids)
    if len(finals) != 2 or len(set(finals)) != 2:
        raise ValueError("pressure join requires two distinct final requests")
    final_set = set(finals)
    arrivals = {
        row.request_id: row
        for row in boundaries
        if row.kind is BoundaryKind.ARRIVAL and row.request_id in final_set
    }
    completions = {
        row.request_id: row
        for row in boundaries
        if row.kind is BoundaryKind.COMPLETION and row.request_id in final_set
    }
    if set(arrivals) != final_set or set(completions) != final_set:
        raise ValueError("pressure join final request boundaries are incomplete")
    pre_return_completions = [
        row.logical_timestamp
        for row in boundaries
        if row.kind is BoundaryKind.COMPLETION and row.request_id not in final_set
    ]
    if not pre_return_completions:
        raise ValueError("pressure join lacks pre-return completions")
    pressure_timestamp = max(pre_return_completions)
    shifted: list[ReplayBoundary] = []
    for row in boundaries:
        if row.request_id not in final_set:
            shifted.append(row)
            continue
        arrival = arrivals[row.request_id]
        delay = max(0.0, pressure_timestamp - arrival.logical_timestamp)
        shifted.append(
            ReplayBoundary(
                boundary_id=row.boundary_id,
                logical_timestamp=row.logical_timestamp + delay,
                source=(
                    row.source
                    if delay == 0.0
                    else f"{row.source}+CONTROLLED_PRESSURE_JOIN_DELAY"
                ),
                kind=row.kind,
                request_id=row.request_id,
            )
        )
    shifted.append(
        ReplayBoundary(
            boundary_id=boundary_id,
            logical_timestamp=pressure_timestamp,
            source="FROZEN_TWO_SESSION_PRESSURE_JOIN",
            kind=BoundaryKind.PRESSURE,
        )
    )
    kind_order = {
        BoundaryKind.COMPLETION: 0,
        BoundaryKind.PRESSURE: 1,
        BoundaryKind.ARRIVAL: 2,
    }
    shifted.sort(
        key=lambda row: (
            row.logical_timestamp,
            kind_order[row.kind],
            row.boundary_id,
        )
    )
    return tuple(shifted)


def execute_controlled_sparse_replay(
    *,
    boundaries: Sequence[ReplayBoundary],
    requests: Mapping[str, PlannedRequest],
    backend: ControlledReplayBackend,
    clock: ControlledSparseReplayClock,
    max_inflight: int,
    timeout_seconds: float,
) -> ControlledReplayResult:
    """Execute one timeline without sleeping or advancing across Native work."""
    if not isinstance(boundaries, Sequence) or not boundaries:
        raise ValueError("boundaries must be a non-empty sequence")
    if max_inflight < 1:
        raise ValueError("max_inflight must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    pending: list[str] = []
    submitted: dict[str, RequestHandle] = {}
    completed: dict[str, RequestCompletion] = {}
    submissions: list[RequestHandle] = []
    completions: list[RequestCompletion] = []
    peak = 0

    def submit_pending() -> None:
        nonlocal peak
        for request_id in pending:
            handle = backend.submit_prepared(request_id)
            if handle.logical_request_id != request_id:
                raise RuntimeError("prepared submission changed logical request identity")
            if request_id in submitted:
                raise RuntimeError("prepared request was submitted twice")
            clock.native_submitted(request_id)
            submitted[request_id] = handle
            submissions.append(handle)
        peak = max(peak, len(pending))
        pending.clear()

    def drain_submitted() -> None:
        if not submitted:
            return
        rows = tuple(backend.drain_native(timeout_seconds=timeout_seconds))
        seen: set[str] = set()
        for row in rows:
            request_id = row.logical_request_id
            handle = submitted.get(request_id)
            if handle is None or request_id in seen:
                raise RuntimeError("Native drain returned an unknown or duplicate request")
            if (
                row.native_request_id != handle.native_request_id
                or row.external_request_id != handle.external_request_id
            ):
                raise RuntimeError("Native completion identity mismatch")
            if row.status != "success":
                raise RuntimeError(f"Native request failed: {request_id}")
            clock.native_completed(request_id)
            completed[request_id] = row
            completions.append(row)
            seen.add(request_id)
        if seen != set(submitted):
            raise RuntimeError("Native drain omitted one or more submitted requests")
        submitted.clear()

    for boundary in boundaries:
        if not isinstance(boundary, ReplayBoundary):
            raise TypeError("boundaries must contain ReplayBoundary values")
        if boundary.kind is BoundaryKind.ARRIVAL:
            if boundary.request_id not in requests:
                raise KeyError(boundary.request_id)
            advance = clock.advance(boundary.boundary_id)
            backend.record_logical_time_advance(advance)
            assert boundary.request_id is not None
            backend.prepare_arrival(requests[boundary.request_id])
            pending.append(boundary.request_id)
            if len(pending) == max_inflight:
                submit_pending()
                drain_submitted()
            continue

        # A logical completion or pressure decision cannot cross pending Native
        # work.  Finish the batch first, then advance the lifecycle clock.
        submit_pending()
        drain_submitted()
        advance = clock.advance(boundary.boundary_id)
        backend.record_logical_time_advance(advance)
        if boundary.kind is BoundaryKind.COMPLETION:
            request_id = boundary.request_id
            if request_id is None or request_id not in completed:
                raise RuntimeError("logical completion lacks a Native completion")
            backend.finish_logical_completion(request_id)
            del completed[request_id]
        else:
            if boundary.request_id is not None:
                raise ValueError("pressure boundary cannot name a request")
            backend.execute_prepared_pressure(boundary.boundary_id)

    submit_pending()
    drain_submitted()
    if completed:
        raise RuntimeError("Native completions lack logical completion boundaries")
    clock.assert_complete()
    return ControlledReplayResult(
        native_submissions=tuple(submissions),
        native_completions=tuple(completions),
        peak_inflight=peak,
        logical_sequence_sha256=clock.sequence_sha256,
    )
