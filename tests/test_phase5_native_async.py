from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from kvopt.workload.phase2 import PlannedRequest
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_native_async import (
    NativePressureAllocationRequest,
    Phase5NativeExecutionError,
    PressureBoundary,
    PressureContract,
    PressureExecutionEvidence,
    execute_phase5_native_plan,
)
from kvopt.workload.phase5_replay import (
    canonical_sha256,
    create_phase5_workload_seal,
    fixed_arrival_plan,
    materialize_n_session_plan,
)


def _pressure_input(boundary_id: str) -> NativePressureAllocationRequest:
    token_ids = tuple(range(16))
    return NativePressureAllocationRequest(
        boundary_id=boundary_id,
        pressure_token_ids=token_ids,
        pressure_token_ids_sha256=canonical_sha256(list(token_ids)),
        block_size_tokens=16,
        required_blocks=1,
        expected_free_blocks_before=10,
    )


def test_native_pressure_input_rejects_hash_or_geometry_drift() -> None:
    token_ids = tuple(range(16))
    with pytest.raises(ValueError, match="hash mismatch"):
        NativePressureAllocationRequest(
            boundary_id="pressure:bad-hash",
            pressure_token_ids=token_ids,
            pressure_token_ids_sha256="0" * 64,
            block_size_tokens=16,
            required_blocks=1,
            expected_free_blocks_before=10,
        )
    with pytest.raises(ValueError, match="do not match required blocks"):
        NativePressureAllocationRequest(
            boundary_id="pressure:bad-geometry",
            pressure_token_ids=token_ids,
            pressure_token_ids_sha256=canonical_sha256(list(token_ids)),
            block_size_tokens=16,
            required_blocks=2,
            expected_free_blocks_before=10,
        )


def _fixture(program_count: int = 4):
    sessions = {
        f"p{index}": [
            {
                "request_id": f"p{index}:turn:1",
                "turn_index": 1,
                "model_submit_monotonic_seconds": 10.0,
                "model_completion_monotonic_seconds": 12.0,
            }
        ]
        for index in range(1, program_count + 1)
    }
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.0)
    replay = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)
    requests = {
        request_id: PlannedRequest(
            program_id=request_id.split(":", 1)[0],
            request_id=request_id,
            turn_index=1,
            planned_arrival_offset_seconds=0.0,
            prompt=request_id,
            prefix_prompt="shared",
            is_terminal=True,
            next_tool_type=None,
            tool_gap_seconds=None,
        )
        for request_id in replay.expected_native_enqueue_order
    }
    seal = create_phase5_workload_seal(
        workload_id="phase5b-mock",
        source={
            "kind": "CPU_FIXTURE",
            "revision": "v1",
            "license": "TEST_ONLY",
            "content_sha256": "10" * 32,
        },
        request_token_sha256={request_id: "20" * 32 for request_id in requests},
        replay_plan=replay,
    )
    return replay, requests, seal


@dataclass
class _MockBackend:
    completion_order: list[str]
    prepared: set[str] = field(default_factory=set)
    pending: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)
    finished: list[str] = field(default_factory=list)
    pressure: list[str] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    poll_sizes: list[int] = field(default_factory=list)
    bad_identity: bool = False
    completion_status: str = "success"
    failure_reason: str | None = None
    completion_timestamp: float = 2.0

    def prepare_arrival(self, request: PlannedRequest) -> None:
        self.prepared.add(request.request_id)

    def submit_prepared(self, request_id: str) -> RequestHandle:
        assert request_id in self.prepared
        self.pending.add(request_id)
        self.events.append(
            {
                "event_index": len(self.events) + 1,
                "event_type": "VLLM_REQUEST_SUBMITTED",
                "request_id": request_id,
                "payload": {"native_request_id": f"native:{request_id}"},
            }
        )
        return RequestHandle(request_id, f"native:{request_id}", f"ext:{request_id}", 1.0)

    def poll_completed(self, *, timeout_seconds: float, wait_for_one: bool):
        del timeout_seconds, wait_for_one
        selected = next((row for row in self.completion_order if row in self.pending), None)
        if selected is None:
            self.poll_sizes.append(0)
            return ()
        self.pending.remove(selected)
        self.completed.add(selected)
        self.poll_sizes.append(1)
        native_id = "wrong" if self.bad_identity else f"native:{selected}"
        return (
            RequestCompletion(
                selected,
                native_id,
                f"ext:{selected}",
                self.completion_timestamp,
                self.completion_status,
                self.failure_reason,
            ),
        )

    def finish_logical_completion(self, request_id: str) -> None:
        assert request_id in self.completed
        self.finished.append(request_id)

    def execute_pressure(
        self, request: NativePressureAllocationRequest
    ) -> PressureExecutionEvidence:
        self.pressure.append(request.boundary_id)
        return PressureExecutionEvidence(
            request.boundary_id,
            1.5,
            tuple(sorted(self.pending)),
            request.pressure_token_ids_sha256,
            request.required_blocks,
            (99,),
            10,
            9,
            10,
            "PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
            True,
            ("decision-1",),
            (42,),
        )

    def native_events(self):
        return tuple(self.events)


@pytest.mark.parametrize("program_count", [2, 4, 8, 16])
def test_async_controller_supports_n_sessions_and_incremental_capacity(
    program_count: int,
) -> None:
    replay, requests, seal = _fixture(program_count)
    completion_order = list(reversed(replay.expected_native_enqueue_order))
    backend = _MockBackend(completion_order)
    result = execute_phase5_native_plan(
        replay_plan=replay,
        workload_seal=seal,
        requests=requests,
        backend=backend,
        maximum_inflight_requests=2,
        completion_timeout_seconds=1.0,
    )
    assert result.status == "PASS"
    assert result.controller_submission_order == replay.expected_native_enqueue_order
    assert result.peak_inflight == 2
    assert backend.poll_sizes and set(backend.poll_sizes) == {1}
    assert set(result.native_completion_order) == set(completion_order)
    if program_count > 1:
        assert result.native_completion_order != result.controller_submission_order


def test_live_pressure_binds_exact_inflight_set_without_drain() -> None:
    replay, requests, seal = _fixture(2)
    order = list(replay.expected_native_enqueue_order)
    backend = _MockBackend(list(reversed(order)))
    result = execute_phase5_native_plan(
        replay_plan=replay,
        workload_seal=seal,
        requests=requests,
        backend=backend,
        maximum_inflight_requests=2,
        completion_timeout_seconds=1.0,
        pressure_boundaries=(
            PressureBoundary(
                "pressure:live-1",
                1.0,
                PressureContract.LIVE_STATE,
                _pressure_input("pressure:live-1"),
                tuple(order),
            ),
        ),
    )
    assert result.pressure_boundary_ids == ("pressure:live-1",)
    assert backend.pressure == ["pressure:live-1"]
    assert not backend.poll_sizes or backend.poll_sizes[0] == 1


def test_live_pressure_rejects_wrong_inflight_contract() -> None:
    replay, requests, seal = _fixture(2)
    backend = _MockBackend(list(replay.expected_native_enqueue_order))
    with pytest.raises(Phase5NativeExecutionError, match="inflight set mismatch"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=backend,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
            pressure_boundaries=(
                PressureBoundary(
                    "pressure:wrong",
                    1.0,
                    PressureContract.LIVE_STATE,
                    _pressure_input("pressure:wrong"),
                    (replay.expected_native_enqueue_order[0],),
                ),
            ),
        )


def test_controller_fails_on_completion_identity_or_no_progress() -> None:
    replay, requests, seal = _fixture(2)
    bad = _MockBackend(list(replay.expected_native_enqueue_order), bad_identity=True)
    with pytest.raises(Phase5NativeExecutionError, match="identity mismatch"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=bad,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
        )


@pytest.mark.parametrize("status", ["failed", "timeout", "cancelled"])
def test_controller_fails_closed_on_unsuccessful_native_terminal_state(
    status: str,
) -> None:
    replay, requests, seal = _fixture(2)
    backend = _MockBackend(
        list(replay.expected_native_enqueue_order),
        completion_status=status,
        failure_reason=f"mock {status}",
    )
    with pytest.raises(Phase5NativeExecutionError, match=f"ended as {status}"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=backend,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
        )


def test_controller_rejects_native_completion_before_native_submission() -> None:
    replay, requests, seal = _fixture(2)
    backend = _MockBackend(
        list(replay.expected_native_enqueue_order),
        completion_timestamp=0.5,
    )
    with pytest.raises(Phase5NativeExecutionError, match="precedes submission"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=backend,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
        )


def test_controller_fails_when_incremental_poll_makes_no_progress() -> None:
    replay, requests, seal = _fixture(2)
    stalled = _MockBackend([])
    with pytest.raises(Phase5NativeExecutionError, match="made no progress"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=stalled,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
        )


def test_controller_fails_if_backend_submission_evidence_drifts() -> None:
    replay, requests, seal = _fixture(2)
    backend = _MockBackend(list(replay.expected_native_enqueue_order))
    original = backend.native_events

    def reversed_events():
        rows = list(original())
        for index, row in enumerate(reversed(rows), start=1):
            row["event_index"] = index
        return rows

    backend.native_events = reversed_events  # type: ignore[method-assign]
    with pytest.raises(Phase5NativeExecutionError, match="enqueue-order gate"):
        execute_phase5_native_plan(
            replay_plan=replay,
            workload_seal=seal,
            requests=requests,
            backend=backend,
            maximum_inflight_requests=2,
            completion_timeout_seconds=1.0,
        )
