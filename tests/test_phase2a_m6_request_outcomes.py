from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.profiling.ingestion import RawRunArtifacts
from kvopt.profiling.request_outcomes import build_request_outcomes_table


def _event(
    event_index: int,
    event_type: str,
    timestamp: float,
    clock_domain: str,
    *,
    payload: dict[str, object] | None = None,
    prefix_id: str | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": event_index,
        "event_type": event_type,
        "timestamp": timestamp,
        "clock_domain": clock_domain,
        "source": "test",
        "program_id": "agent-a",
        "request_id": "request-a1",
        "payload": payload or {},
    }
    if prefix_id is not None:
        event["prefix_id"] = prefix_id
    return event


def _raw_run(*events: dict[str, object]) -> RawRunArtifacts:
    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={"run_id": "run-a"},
        trace={"trace_id": "trace-a"},
        replay=(
            {
                "program_id": "agent-a",
                "request_id": "request-a1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": 3.0,
                "tool_gap_seconds": 1.5,
                "kind": "turn",
            },
        ),
        events=events,
    )


def test_request_outcome_preserves_planned_and_observed_facts() -> None:
    run = _raw_run(
        _event(1, "REQUEST_ARRIVED", 10.0, "lifecycle"),
        _event(2, "VLLM_REQUEST_SUBMITTED", 10.1, "backend"),
        _event(3, "REQUEST_ADMITTED", 10.2, "lifecycle"),
        _event(
            4,
            "VLLM_REQUEST_COMPLETED",
            11.0,
            "backend",
            payload={"output_token_count": 2},
        ),
        _event(
            5,
            "VLLM_PREFIX_SNAPSHOT",
            11.1,
            "backend",
            prefix_id="prefix-a",
            payload={"reusable_token_count": 256, "block_ids": [3, 4]},
        ),
    )

    row = build_request_outcomes_table((run,))[0]

    assert row.planned_arrival_offset_seconds == 3.0
    assert row.arrival_timestamp == 10.0
    assert row.logical_admission_timestamp == 10.2
    assert row.logical_admission_delay_seconds == pytest.approx(0.2)
    assert row.logical_admission_delay_status == "available"
    assert row.backend_service_seconds == pytest.approx(0.9)
    assert row.backend_service_status == "available"
    assert row.prefix_id == "prefix-a"
    assert row.reusable_token_count == 256
    assert row.block_ids == (3, 4)
    assert row.output_token_count == 2


def test_request_outcome_does_not_compare_incompatible_clocks() -> None:
    run = _raw_run(
        _event(1, "REQUEST_ARRIVED", 10.0, "lifecycle"),
        _event(2, "REQUEST_ADMITTED", 10.2, "different-clock"),
    )

    row = build_request_outcomes_table((run,))[0]

    assert row.logical_admission_delay_seconds is None
    assert row.logical_admission_delay_status == "incompatible_clock_domain"


def test_incomplete_request_preserves_missingness() -> None:
    row = build_request_outcomes_table((_raw_run(),))[0]

    assert row.arrival_timestamp is None
    assert row.completion_timestamp is None
    assert row.output_token_count is None
    assert row.logical_admission_delay_status == "missing_landmark"
    assert row.backend_service_status == "missing_landmark"
