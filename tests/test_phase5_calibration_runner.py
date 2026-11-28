from __future__ import annotations

import asyncio

import pytest

from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_calibration_runner import (
    CalibrationRequestInput,
    CalibrationRunnerError,
    execute_calibration_replay,
)
from kvopt.workload.phase5_replay import canonical_sha256


class _Adapter:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[RequestCompletion] = asyncio.Queue()
        self.submitted: list[str] = []
        self.shutdown_called = False

    async def submit(self, spec):
        self.submitted.append(spec.logical_request_id)
        handle = RequestHandle(
            logical_request_id=spec.logical_request_id,
            native_request_id=f"native:{spec.logical_request_id}",
            external_request_id=spec.external_request_id,
            submitted_at=float(len(self.submitted)),
        )
        await self.queue.put(
            RequestCompletion(
                logical_request_id=spec.logical_request_id,
                native_request_id=handle.native_request_id,
                external_request_id=handle.external_request_id,
                status="success",
                completed_at=handle.submitted_at + 0.1,
                failure_reason=None,
            )
        )
        return handle

    async def collect_completed(self, *, timeout_seconds, wait_for_one):
        del timeout_seconds, wait_for_one
        return (await self.queue.get(),)

    async def shutdown(self, **_kwargs):
        self.shutdown_called = True

    def report(self):
        return {"status": "PASS"}


def _request(request_id: str, arrival: float, predecessor: str | None = None):
    return CalibrationRequestInput(
        logical_request_id=request_id,
        prompt_token_ids=(1, 2, 3),
        sampling_params=object(),
        logical_arrival_seconds=arrival,
        program_id=request_id.split(":", 1)[0],
        session_id="session-1",
        predecessor_request_id=predecessor,
    )


def test_calibration_replay_preserves_order_and_arms_after_terminal() -> None:
    adapter = _Adapter()
    timer_payloads = []

    async def timer_sink(payload):
        timer_payloads.append(dict(payload))
        return {"status": "PASS"}

    clock = iter((10.0, 10.0, 10.1, 10.1, 10.2, 10.2, 10.3, 10.3))
    order = ("p1:turn:1", "p2:turn:1", "p1:turn:2")
    result = asyncio.run(
        execute_calibration_replay(
            run_id="run-1",
            expected_enqueue_order=order,
            requests={
                order[0]: _request(order[0], 0.0),
                order[1]: _request(order[1], 0.0),
                order[2]: _request(order[2], 0.2, order[0]),
            },
            adapter=adapter,
            timer_sink=timer_sink,
            run_epoch_monotonic=10.0,
            completion_timeout_seconds=10.0,
            monotonic=lambda: next(clock),
            sleep=lambda _delay: asyncio.sleep(0),
        )
    )
    assert result["status"] == "PASS"
    assert result["actual_enqueue_sequence_sha256"] == canonical_sha256(list(order))
    assert adapter.submitted == list(order)
    assert adapter.shutdown_called is True
    assert timer_payloads[0]["predecessor_request_id"] == order[0]
    assert timer_payloads[0]["successor_request_id"] == order[2]


def test_calibration_replay_rejects_request_set_drift() -> None:
    with pytest.raises(CalibrationRunnerError, match="request inputs"):
        asyncio.run(
            execute_calibration_replay(
                run_id="run-1",
                expected_enqueue_order=("p1:turn:1",),
                requests={},
                adapter=_Adapter(),
                timer_sink=lambda _payload: asyncio.sleep(
                    0, result={"status": "PASS"}
                ),
                run_epoch_monotonic=1.0,
                completion_timeout_seconds=1.0,
                monotonic=lambda: 1.0,
            )
        )
