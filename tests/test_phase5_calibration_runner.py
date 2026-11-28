from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_calibration_runner import (
    CalibrationRequestInput,
    CalibrationRunnerError,
    execute_calibration_replay,
    install_official_calibration_runtime,
    install_project_calibration_runtime,
    official_timer_sink,
    project_timer_sink,
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


def test_project_runtime_installs_exact_engine_core_contract(monkeypatch) -> None:
    calls = []

    class Bridge:
        def __init__(self, client):
            assert client == "utility-client"

        async def install(self, contract):
            calls.append(dict(contract))
            report = {
                "status": "PASS",
                "system_id": "A3_SUFFIX",
                "policy_id": "A3_SUFFIX_COST_V1",
                "control_transport": "ASYNCMPLCLIENT_UTILITY_RPC",
                "native_objects_cross_process": False,
            }
            return SimpleNamespace(
                runtime_installation_report=lambda: report,
            )

        async def controller_event(self, event_type, payload):
            calls.append((event_type, dict(payload)))
            return {"status": "PASS"}

    monkeypatch.setattr(
        "kvopt.workload.phase5_calibration_runner.AsyncLLMNativeAdapter",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5_calibration_runner.resolve_async_utility_client",
        lambda _engine: "utility-client",
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5_calibration_runner.EngineCoreUtilityBridge", Bridge
    )
    contract = {
        "run_id": "run-1",
        "system_id": "A3_SUFFIX",
        "policy_id": "A3_SUFFIX_COST_V1",
        "group_id": "SWE_G01",
        "expected_native_enqueue_order": ["program-1:turn:1"],
        "request_inputs": [{
            "request_id": "program-1:turn:1",
            "program_id": "program-1",
            "session_id": "session-1",
            "source_trace_sha256": "a" * 64,
        }],
    }
    runtime = asyncio.run(
        install_project_calibration_runtime(
            engine=SimpleNamespace(),
            run_contract=contract,
            run_epoch_monotonic=1.0,
            clock=lambda: 1.0,
        )
    )
    assert calls[0]["schema_version"] == "phase5.calibration_engine_core_install.v1"
    assert calls[0]["all_logical_request_ids"] == ["program-1:turn:1"]
    assert calls[0]["session_by_program"] == {"program-1": "session-1"}
    result = asyncio.run(project_timer_sink(runtime)({"candidate_id": "program-1"}))
    assert result == {"status": "PASS"}
    assert calls[1][0] == "CONTROLLER_ARM_TIMER"


def test_project_runtime_rejects_official_arm() -> None:
    with pytest.raises(CalibrationRunnerError, match="independent runtime"):
        asyncio.run(
            install_project_calibration_runtime(
                engine=SimpleNamespace(),
                run_contract={"system_id": "CONTINUUM_OFFICIAL"},
                run_epoch_monotonic=1.0,
                clock=lambda: 1.0,
            )
        )


def test_official_runtime_uses_observation_only_utility_rpc(monkeypatch) -> None:
    calls = []

    class Client:
        async def call_utility_async(self, method, *args):
            calls.append((method, args))
            if method == "kvopt_phase5_official_install":
                return {"installation_report": {
                    "status": "PASS",
                    "system_id": "CONTINUUM_OFFICIAL",
                    "policy_id": "CONTINUUM_OFFICIAL_316A5879",
                    "observation_only": True,
                    "control_transport": "ASYNCMPLCLIENT_UTILITY_RPC",
                    "native_objects_cross_process": False,
                }}
            return {"events": [], "engine_core_pid": 7}

    client = Client()
    monkeypatch.setattr(
        "kvopt.workload.phase5_calibration_runner.AsyncLLMNativeAdapter",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5_calibration_runner.resolve_async_utility_client",
        lambda _engine: client,
    )
    runtime = asyncio.run(
        install_official_calibration_runtime(
            engine=SimpleNamespace(),
            run_contract={
                "run_id": "run-official",
                "system_id": "CONTINUUM_OFFICIAL",
                "policy_id": "CONTINUUM_OFFICIAL_316A5879",
            },
            run_epoch_monotonic=1.0,
            clock=lambda: 1.0,
        )
    )
    assert calls[0][0] == "kvopt_phase5_official_install"
    assert asyncio.run(runtime.export_evidence())["engine_core_pid"] == 7
    assert asyncio.run(official_timer_sink()({}))["policy_input"] is False
