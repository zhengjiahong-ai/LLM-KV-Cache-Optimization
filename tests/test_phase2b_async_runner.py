from collections.abc import Sequence

import pytest

from kvopt.workload.phase2 import Phase2Trace, PlannedRequest, PressureStage
from kvopt.workload.phase2b_fidelity_runner import (
    Phase2BExecutionError,
    RequestCompletion,
    RequestHandle,
    build_inflight_gate,
    execute_phase2b_trace,
)


def _request(program: str, request_id: str, arrival: float = 0.0) -> PlannedRequest:
    return PlannedRequest(
        program_id=program,
        request_id=request_id,
        turn_index=1,
        planned_arrival_offset_seconds=arrival,
        prompt="prompt",
        prefix_prompt="prefix",
        is_terminal=True,
        next_tool_type=None,
        tool_gap_seconds=None,
    )


class FakeAsyncBackend:
    def __init__(self) -> None:
        self.outstanding: dict[str, RequestHandle] = {}
        self.submission_order: list[str] = []
        self.forced_release_count = 0
        self.complete_on_collect = False
        self.duplicate_on_drain = False

    def submit(self, request: PlannedRequest) -> RequestHandle:
        index = len(self.submission_order) + 1
        handle = RequestHandle(
            request.request_id,
            f"native-{index}",
            f"external-{index}",
            float(index),
        )
        self.outstanding[request.request_id] = handle
        self.submission_order.append(request.request_id)
        return handle

    @staticmethod
    def _completion(handle: RequestHandle) -> RequestCompletion:
        return RequestCompletion(
            handle.logical_request_id,
            handle.native_request_id,
            handle.external_request_id,
            handle.submitted_at + 1.0,
        )

    def collect_completed(
        self, *, until: float | None = None
    ) -> Sequence[RequestCompletion]:
        del until
        if not self.complete_on_collect or len(self.outstanding) < 2:
            return ()
        logical_id = next(iter(self.outstanding))
        handle = self.outstanding.pop(logical_id)
        return (self._completion(handle),)

    def drain(self, *, timeout_seconds: float) -> Sequence[RequestCompletion]:
        del timeout_seconds
        handles = tuple(reversed(tuple(self.outstanding.values())))
        self.outstanding.clear()
        rows = tuple(self._completion(handle) for handle in handles)
        if self.duplicate_on_drain and rows:
            return (*rows, rows[0])
        if any(handle.logical_request_id.startswith("pressure:") for handle in handles):
            self.forced_release_count += 1
        return rows


def test_same_arrival_submits_two_requests_before_out_of_order_completion() -> None:
    backend = FakeAsyncBackend()
    trace = Phase2Trace(
        "same-arrival",
        (_request("a", "a:1"), _request("b", "b:1")),
        (),
    )

    result = execute_phase2b_trace(
        trace,
        backend,
        seed=1,
        max_in_flight=2,
        timeout_seconds=5,
        pressure_safety_ceiling=1,
        monotonic=lambda: 0.0,
    )

    assert backend.submission_order == ["a:1", "b:1"]
    assert [row.logical_request_id for row in result.completions] == ["b:1", "a:1"]
    assert result.peak_inflight == 2
    gate = build_inflight_gate(
        result,
        required_peak=2,
        source_event_indices=(1, 2, 3, 4),
        runtime_identity={"backend": "fake"},
    )
    assert gate.status == "PASS"
    assert gate.scope == "native_request_lifecycle_overlap"


def test_capacity_collects_before_third_submission() -> None:
    backend = FakeAsyncBackend()
    backend.complete_on_collect = True
    trace = Phase2Trace(
        "cap",
        (
            _request("a", "a:1"),
            _request("b", "b:1"),
            _request("c", "c:1"),
        ),
        (),
    )

    result = execute_phase2b_trace(
        trace,
        backend,
        seed=1,
        max_in_flight=2,
        timeout_seconds=5,
        pressure_safety_ceiling=1,
        monotonic=lambda: 0.0,
    )

    assert result.peak_inflight == 2
    assert len(result.completions) == 3


def test_duplicate_completion_is_rejected() -> None:
    backend = FakeAsyncBackend()
    backend.duplicate_on_drain = True
    trace = Phase2Trace("duplicate", (_request("a", "a:1"),), ())

    with pytest.raises(Phase2BExecutionError, match="duplicate completion"):
        execute_phase2b_trace(
            trace,
            backend,
            seed=1,
            max_in_flight=1,
            timeout_seconds=5,
            pressure_safety_ceiling=1,
            monotonic=lambda: 0.0,
        )


def test_pressure_is_a_completion_barrier_and_counter_is_read_after_attempt() -> None:
    backend = FakeAsyncBackend()
    trace = Phase2Trace(
        "pressure-barrier",
        (_request("target", "target:1"),),
        (PressureStage("p", 0.0, "pressure", 3, True),),
    )

    result = execute_phase2b_trace(
        trace,
        backend,
        seed=1,
        max_in_flight=2,
        timeout_seconds=5,
        pressure_safety_ceiling=3,
        monotonic=lambda: 0.0,
    )

    assert backend.submission_order == ["target:1", "pressure:p:1"]
    assert result.pressure_attempts == 1
    assert backend.forced_release_count == 1


def test_incomplete_drain_fails_bounded_execution() -> None:
    backend = FakeAsyncBackend()
    backend.drain = lambda *, timeout_seconds: ()
    trace = Phase2Trace("timeout", (_request("a", "a:1"),), ())

    with pytest.raises(Phase2BExecutionError, match="terminal states"):
        execute_phase2b_trace(
            trace,
            backend,
            seed=1,
            max_in_flight=1,
            timeout_seconds=0.01,
            pressure_safety_ceiling=1,
            monotonic=lambda: 0.0,
        )
