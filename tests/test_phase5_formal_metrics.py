from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.profiling.ingestion import ArtifactValidationError
from kvopt.profiling.phase5_formal_metrics import (
    FormalEvidenceRecorder,
    evaluate_formal_run_metrics,
)


def _digest(value: int) -> str:
    return f"{value:064x}"


def _events(*, cached: int = 16, completion_clock: str = "system_monotonic"):
    rows = [
        {
            "event_index": 1,
            "event_type": "VLLM_REQUEST_SUBMITTED",
            "program_id": "p1",
            "request_id": "r1",
            "timestamp": 1.0,
            "clock_domain": "system_monotonic",
            "payload": {},
        },
        {
            "event_index": 2,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "program_id": "p1",
            "request_id": "r1",
            "clock_domain": "engine_core_monotonic",
            "payload": {
                "native_prompt_tokens": 32,
                "native_cached_prefix_tokens": 0,
                "native_apc_block_hashes": [_digest(1), _digest(2)],
                "native_hash_block_size": 16,
                "native_hash_process_id": "proc",
                "native_hash_function": "sha256",
                "native_queued_timestamp": 10.0,
                "native_first_token_timestamp": 12.0,
            },
        },
        {
            "event_index": 3,
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "program_id": "p1",
            "request_id": "r1",
            "payload": {
                "ordered_native_hashes": [_digest(1), _digest(2)],
                "hash_num_tokens": 32,
                "native_hash_block_size": 16,
                "native_hash_process_id": "proc",
                "native_hash_function": "sha256",
            },
        },
        {
            "event_index": 4,
            "event_type": "VLLM_REQUEST_COMPLETED",
            "program_id": "p1",
            "request_id": "r1",
            "timestamp": 5.0,
            "clock_domain": completion_clock,
            "payload": {"output_token_count": 8},
        },
        {
            "event_index": 5,
            "event_type": "VLLM_REQUEST_SUBMITTED",
            "program_id": "p2",
            "request_id": "r2",
            "timestamp": 6.0,
            "clock_domain": "system_monotonic",
            "payload": {},
        },
        {
            "event_index": 6,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "program_id": "p2",
            "request_id": "r2",
            "clock_domain": "engine_core_monotonic",
            "payload": {
                "native_prompt_tokens": 48,
                "native_cached_prefix_tokens": cached,
                "native_apc_block_hashes": [_digest(1), _digest(2), _digest(3)],
                "native_hash_block_size": 16,
                "native_hash_process_id": "proc",
                "native_hash_function": "sha256",
                "native_queued_timestamp": 20.0,
                "native_first_token_timestamp": 23.0,
            },
        },
        {
            "event_index": 7,
            "event_type": "VLLM_REQUEST_COMPLETED",
            "program_id": "p2",
            "request_id": "r2",
            "timestamp": 10.0,
            "clock_domain": completion_clock,
            "payload": {"output_token_count": 12},
        },
    ]
    for row in rows:
        row["event_index"] *= 10
    rows.extend(
        [
            {
                "event_index": 1,
                "event_type": "REQUEST_ARRIVED",
                "program_id": "p1",
                "request_id": "r1",
                "timestamp": 0.5,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
            {
                "event_index": 5,
                "event_type": "CLIENT_DISPATCH_ACCEPTED",
                "program_id": "p1",
                "request_id": "r1",
                "timestamp": 1.0,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
            {
                "event_index": 25,
                "event_type": "FIRST_OUTPUT_TOKEN",
                "program_id": "p1",
                "request_id": "r1",
                "timestamp": 3.0,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
            {
                "event_index": 41,
                "event_type": "REQUEST_ARRIVED",
                "program_id": "p2",
                "request_id": "r2",
                "timestamp": 5.5,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
            {
                "event_index": 45,
                "event_type": "CLIENT_DISPATCH_ACCEPTED",
                "program_id": "p2",
                "request_id": "r2",
                "timestamp": 6.0,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
            {
                "event_index": 65,
                "event_type": "FIRST_OUTPUT_TOKEN",
                "program_id": "p2",
                "request_id": "r2",
                "timestamp": 9.0,
                "clock_domain": "system_monotonic",
                "payload": {},
            },
        ]
    )
    return rows


def _evaluate(events=None):
    return evaluate_formal_run_metrics(
        run_id="formal-1",
        arm_id="arm-x",
        events=_events() if events is None else events,
        frozen_requests=(("p1", "r1"), ("p2", "r2")),
        expected_native_enqueue_order=(("p1", "r1"), ("p2", "r2")),
        history_predecessors={
            ("p1", "r1"): (),
            ("p2", "r2"): (("p1", "r1"),),
        },
    )


def test_formal_metrics_recomputes_nec_timing_and_coverage() -> None:
    report = _evaluate()

    assert report["status"] == "PASS"
    assert report["aggregates"]["recomputed_tokens"] == 16
    assert report["requests"][1]["E"] == 32
    assert report["requests"][1]["C"] == 16
    assert report["requests"][1]["ttft_seconds"] == 3.0
    assert report["requests"][1]["latency_seconds"] == 4.5
    assert report["aggregates"]["observed_run_window_seconds"] == 9.5
    assert report["aggregates"]["throughput_requests_per_second"] == pytest.approx(
        2 / 9.5
    )
    assert report["aggregates"]["throughput_tokens_per_second"] == pytest.approx(
        20 / 9.5
    )
    assert report["eligibility_uses_native_cached_tokens_c"] is False


def test_formal_e_does_not_change_when_c_changes() -> None:
    first = _evaluate(_events(cached=0))
    second = _evaluate(_events(cached=16))

    assert first["requests"][1]["E"] == second["requests"][1]["E"] == 32
    assert first["requests"][1]["recomputed_tokens"] == 32
    assert second["requests"][1]["recomputed_tokens"] == 16


def test_formal_metrics_fails_on_missing_history_even_when_c_zero() -> None:
    rows = [
        row for row in _events(cached=0) if row["event_type"] != "VLLM_PREFIX_SNAPSHOT"
    ]

    with pytest.raises(ArtifactValidationError, match="lacks predecessor snapshot"):
        _evaluate(rows)


def test_formal_recorder_rejects_unknown_request_and_duplicate_index() -> None:
    recorder = FormalEvidenceRecorder(expected_requests=(("p1", "r1"),))
    recorder.record(_events()[0])
    duplicate = deepcopy(_events()[0])
    duplicate["request_id"] = "unknown"
    with pytest.raises(ArtifactValidationError, match="duplicate event_index"):
        recorder.record(duplicate)

    recorder = FormalEvidenceRecorder(expected_requests=(("p1", "r1"),))
    unknown = deepcopy(_events()[0])
    unknown["event_index"] = 99
    unknown["request_id"] = "unknown"
    with pytest.raises(ArtifactValidationError, match="unknown non-pressure"):
        recorder.record(unknown)


def test_formal_metrics_rejects_actual_enqueue_order_drift() -> None:
    rows = _events()
    rows[0]["event_index"] = 50
    rows[4]["event_index"] = 10

    with pytest.raises(ArtifactValidationError, match="enqueue order"):
        _evaluate(rows)


def test_formal_metrics_marks_cross_clock_latency_missing() -> None:
    report = _evaluate(_events(completion_clock="other_monotonic"))

    assert all(
        row["latency_status"] == "INCOMPATIBLE_CLOCK_DOMAIN"
        for row in report["requests"]
    )
    assert report["missingness"]["latency"] == {
        "available": 0,
        "missing": 2,
        "coverage": 0.0,
    }
    assert report["aggregates"]["observed_run_window_status"] == (
        "INCOMPATIBLE_CLOCK_DOMAIN"
    )
    assert report["aggregates"]["throughput_requests_per_second"] is None


def test_formal_metrics_requires_explicit_right_censoring() -> None:
    rows = [row for row in _events() if row["event_index"] != 70]
    with pytest.raises(ArtifactValidationError, match="right-censoring"):
        _evaluate(rows)

    report = evaluate_formal_run_metrics(
        run_id="formal-1",
        arm_id="arm-x",
        events=rows,
        frozen_requests=(("p1", "r1"), ("p2", "r2")),
        expected_native_enqueue_order=(("p1", "r1"), ("p2", "r2")),
        history_predecessors={
            ("p1", "r1"): (),
            ("p2", "r2"): (("p1", "r1"),),
        },
        right_censored_request_ids=("r2",),
    )
    assert report["requests"][1]["right_censored"] is True
    assert report["requests"][1]["latency_status"] == "MISSING"
    assert report["missingness"]["terminal"]["missing"] == 1
