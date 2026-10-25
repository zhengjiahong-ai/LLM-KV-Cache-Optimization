from __future__ import annotations

from dataclasses import dataclass

import pytest

from kvopt.continuum import ControlledSparseReplayClock
from kvopt.workload.continuum_bounded_timeline import (
    BoundaryKind,
    ReplayBoundary,
    execute_controlled_sparse_replay,
    insert_pressure_join_boundary,
    materialize_request_boundaries,
)
from kvopt.workload.phase2 import PlannedRequest
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle


def _request(identity: str, program: str) -> PlannedRequest:
    return PlannedRequest(
        program_id=program,
        request_id=identity,
        turn_index=1,
        planned_arrival_offset_seconds=0.0,
        prompt="exact tokens",
        prefix_prompt="",
        is_terminal=False,
        next_tool_type="tool",
        tool_gap_seconds=1.0,
    )


@dataclass
class _Backend:
    prepared: list[str]
    submitted: list[str]
    finished: list[str]
    pressure: list[str]

    def record_logical_time_advance(self, advance) -> None:
        assert advance.logical_clock_domain == "continuum_logical_replay"

    def prepare_arrival(self, request: PlannedRequest) -> None:
        self.prepared.append(request.request_id)

    def submit_prepared(self, request_id: str) -> RequestHandle:
        self.submitted.append(request_id)
        return RequestHandle(request_id, f"native-{request_id}", f"external-{request_id}", 1.0)

    def drain_native(self, *, timeout_seconds: float):
        assert timeout_seconds == 30.0
        rows = tuple(
            RequestCompletion(row, f"native-{row}", f"external-{row}", 2.0)
            for row in self.submitted
            if row not in {item.logical_request_id for item in getattr(self, "_returned", ())}
        )
        self._returned = (*getattr(self, "_returned", ()), *rows)
        return rows

    def finish_logical_completion(self, request_id: str) -> None:
        self.finished.append(request_id)

    def execute_prepared_pressure(self, boundary_id: str) -> None:
        self.pressure.append(boundary_id)


def _timeline():
    return (
        ReplayBoundary("a:arrive", 0.0, "SOURCE_SUBMIT", BoundaryKind.ARRIVAL, "a"),
        ReplayBoundary("b:arrive", 0.25, "SOURCE_SUBMIT", BoundaryKind.ARRIVAL, "b"),
        ReplayBoundary("a:complete", 3.0, "SOURCE_COMPLETE", BoundaryKind.COMPLETION, "a"),
        ReplayBoundary("b:complete", 4.0, "SOURCE_COMPLETE", BoundaryKind.COMPLETION, "b"),
        ReplayBoundary("pressure", 5.0, "FROZEN_PRESSURE", BoundaryKind.PRESSURE),
    )


def test_two_arrivals_are_submitted_before_native_drain() -> None:
    boundaries = _timeline()
    clock = ControlledSparseReplayClock(
        boundaries=tuple(row.clock_boundary() for row in boundaries)
    )
    backend = _Backend([], [], [], [])
    result = execute_controlled_sparse_replay(
        boundaries=boundaries,
        requests={"a": _request("a", "pa"), "b": _request("b", "pb")},
        backend=backend,
        clock=clock,
        max_inflight=2,
        timeout_seconds=30.0,
    )

    assert result.peak_inflight == 2
    assert backend.prepared == ["a", "b"]
    assert backend.submitted == ["a", "b"]
    assert backend.finished == ["a", "b"]
    assert backend.pressure == ["pressure"]


def test_completion_boundary_flushes_a_partial_batch_before_time_advance() -> None:
    boundaries = (
        ReplayBoundary("a:arrive", 0.0, "SOURCE_SUBMIT", BoundaryKind.ARRIVAL, "a"),
        ReplayBoundary("a:complete", 1.0, "SOURCE_COMPLETE", BoundaryKind.COMPLETION, "a"),
    )
    clock = ControlledSparseReplayClock(
        boundaries=tuple(row.clock_boundary() for row in boundaries)
    )
    backend = _Backend([], [], [], [])
    result = execute_controlled_sparse_replay(
        boundaries=boundaries,
        requests={"a": _request("a", "pa")},
        backend=backend,
        clock=clock,
        max_inflight=2,
        timeout_seconds=30.0,
    )
    assert result.peak_inflight == 1
    assert backend.finished == ["a"]


def test_missing_native_completion_fails_closed() -> None:
    class _Broken(_Backend):
        def drain_native(self, *, timeout_seconds: float):
            return ()

    boundaries = _timeline()[:3]
    clock = ControlledSparseReplayClock(
        boundaries=tuple(row.clock_boundary() for row in boundaries)
    )
    with pytest.raises(RuntimeError, match="omitted"):
        execute_controlled_sparse_replay(
            boundaries=boundaries,
            requests={"a": _request("a", "pa"), "b": _request("b", "pb")},
            backend=_Broken([], [], [], []),
            clock=clock,
            max_inflight=2,
            timeout_seconds=30.0,
        )


def test_materialize_request_boundaries_preserves_gaps_and_stagger() -> None:
    rows = materialize_request_boundaries(
        sessions=(
            (
                {
                    "request_id": "a1",
                    "model_submit_monotonic_seconds": 10.0,
                    "model_completion_monotonic_seconds": 12.0,
                },
                {
                    "request_id": "a2",
                    "model_submit_monotonic_seconds": 20.0,
                    "model_completion_monotonic_seconds": 21.0,
                },
            ),
            (
                {
                    "request_id": "b1",
                    "model_submit_monotonic_seconds": 100.0,
                    "model_completion_monotonic_seconds": 103.0,
                },
            ),
        ),
        cross_session_start_stagger_seconds=0.25,
    )

    assert [(row.boundary_id, row.logical_timestamp) for row in rows] == [
        ("arrival:a1", 0.0),
        ("arrival:b1", 0.25),
        ("completion:a1", 2.0),
        ("completion:b1", 3.25),
        ("arrival:a2", 10.0),
        ("completion:a2", 11.0),
    ]


def test_materialize_request_boundaries_rejects_completion_before_submit() -> None:
    with pytest.raises(ValueError, match="completion precedes"):
        materialize_request_boundaries(
            sessions=(
                (
                    {
                        "request_id": "a",
                        "model_submit_monotonic_seconds": 2.0,
                        "model_completion_monotonic_seconds": 1.0,
                    },
                ),
                (
                    {
                        "request_id": "b",
                        "model_submit_monotonic_seconds": 3.0,
                        "model_completion_monotonic_seconds": 4.0,
                    },
                ),
            ),
            cross_session_start_stagger_seconds=0.25,
        )


def test_pressure_join_delays_only_early_return_and_preserves_duration() -> None:
    rows = (
        ReplayBoundary("a5c", 10.0, "SOURCE", BoundaryKind.COMPLETION, "a5"),
        ReplayBoundary("a6a", 12.0, "SOURCE", BoundaryKind.ARRIVAL, "a6"),
        ReplayBoundary("a6c", 14.0, "SOURCE", BoundaryKind.COMPLETION, "a6"),
        ReplayBoundary("b5c", 20.0, "SOURCE", BoundaryKind.COMPLETION, "b5"),
        ReplayBoundary("b6a", 25.0, "SOURCE", BoundaryKind.ARRIVAL, "b6"),
        ReplayBoundary("b6c", 28.0, "SOURCE", BoundaryKind.COMPLETION, "b6"),
    )
    joined = insert_pressure_join_boundary(
        boundaries=rows,
        final_request_ids=("a6", "b6"),
        boundary_id="pressure",
    )

    by_id = {row.boundary_id: row for row in joined}
    assert by_id["pressure"].logical_timestamp == 20.0
    assert by_id["a6a"].logical_timestamp == 20.0
    assert by_id["a6c"].logical_timestamp == 22.0
    assert by_id["b6a"].logical_timestamp == 25.0
    assert by_id["b6c"].logical_timestamp == 28.0
    assert "CONTROLLED_PRESSURE_JOIN_DELAY" in by_id["a6a"].source
