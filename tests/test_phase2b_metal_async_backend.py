from types import SimpleNamespace

import pytest

from kvopt.workload.phase2 import PlannedRequest
from scripts.spikes.phase2_minimal_observability_metal import (
    MinimalMetalObservabilityBackend,
    _positive_float,
    _unit_float,
)


def _request(program: str, request_id: str) -> PlannedRequest:
    return PlannedRequest(
        program_id=program,
        request_id=request_id,
        turn_index=1,
        planned_arrival_offset_seconds=0.0,
        prompt="prompt",
        prefix_prompt="prefix",
        is_terminal=True,
        next_tool_type=None,
        tool_gap_seconds=None,
    )


def test_positive_float_accepts_time_constants_above_one() -> None:
    assert _positive_float(30.0, "tau_seconds") == 30.0


def test_unit_float_retains_fraction_upper_bound() -> None:
    assert _unit_float(0.75, "gpu_memory_utilization") == 0.75

    with pytest.raises(ValueError, match=r"must be in \(0, 1\]"):
        _unit_float(30.0, "gpu_memory_utilization")


def test_collect_does_not_wrap_blocking_wait_as_native_poll() -> None:
    backend = MinimalMetalObservabilityBackend.__new__(
        MinimalMetalObservabilityBackend
    )

    assert backend.collect_completed(until=10.0) == ()


def test_drain_joins_batched_out_of_order_outputs_by_external_id() -> None:
    backend = MinimalMetalObservabilityBackend.__new__(
        MinimalMetalObservabilityBackend
    )
    request_a = _request("a", "a:1")
    request_b = _request("b", "b:1")
    backend._phase2b_pending = {
        "external-a": (request_a, "native-a", 256),
        "external-b": (request_b, "native-b", 256),
    }
    backend._wait_for_completion_bounded = lambda _timeout: (
        SimpleNamespace(request_id="external-b"),
        SimpleNamespace(request_id="external-a"),
    )
    backend._observe_completed_output = (
        lambda request, _native, _external, _output: (
            2.0 if request.request_id == "b:1" else 3.0
        )
    )
    finished = []
    backend._finish_turn = (
        lambda request, native, completed, prefix: finished.append(
            (request.request_id, native, completed, prefix)
        )
    )

    rows = backend.drain(timeout_seconds=5.0)

    assert [row.logical_request_id for row in rows] == ["b:1", "a:1"]
    assert [row.native_request_id for row in rows] == ["native-b", "native-a"]
    assert finished == [
        ("b:1", "native-b", 2.0, 256),
        ("a:1", "native-a", 3.0, 256),
    ]
    assert backend._phase2b_pending == {}
