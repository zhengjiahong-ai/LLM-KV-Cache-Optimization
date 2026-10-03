from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.profiling.decision_outcomes import build_decision_outcomes_table
from kvopt.profiling.ingestion import RawRunArtifacts


def _candidate(
    program_id: str,
    prefix_id: str,
    block_id: int,
) -> dict[str, object]:
    return {
        "program_id": program_id,
        "prefix_id": prefix_id,
        "retention_deadline_timestamp": 20.0,
        "waiting_followup": True,
        "block_ids": [block_id],
        "initially_reclaimable_block_ids": [block_id],
        "next_tool_type": "search",
        "elapsed_since_ttl_decision_seconds": 2.0,
        "prefill_reload_seconds": 0.1,
        "eta": 1.0,
        "queue_delay_t_seconds": 0.0,
    }


def _event(
    event_index: int,
    event_type: str,
    *,
    program_id: str | None = None,
    request_id: str | None = None,
    prefix_id: str | None = None,
    payload: dict[str, object] | None = None,
    clock_domain: str = "shared-clock",
) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": event_index,
        "event_type": event_type,
        "timestamp": float(event_index),
        "clock_domain": clock_domain,
        "source": "test",
        "payload": payload or {},
    }
    if program_id is not None:
        event["program_id"] = program_id
    if request_id is not None:
        event["request_id"] = request_id
    if prefix_id is not None:
        event["prefix_id"] = prefix_id
    return event


def _run(*extra_events: dict[str, object]) -> RawRunArtifacts:
    decision = _event(
        10,
        "FORCED_RELEASE_DECISION",
        payload={
            "required_blocks": 1,
            "original_free_queue": [],
            "ordinary_expired_entries": [],
            "candidates": [
                _candidate("agent-a", "prefix-a", 1),
                _candidate("agent-b", "prefix-b", 2),
            ],
            "selected_releases": [
                {
                    "program_id": "agent-a",
                    "prefix_id": "prefix-a",
                    "newly_eligible_block_ids": [1],
                }
            ],
        },
    )
    events = (
        _event(
            5,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="old-request",
        ),
        decision,
        *extra_events,
    )
    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={
            "run_id": "run-a",
            "config": {"analysis_horizon_seconds": 3.0},
        },
        trace={"trace_id": "trace-a"},
        replay=(),
        events=events,
    )


def _with_decision_clock(
    run: RawRunArtifacts,
    clock_domain: str,
) -> RawRunArtifacts:
    events = tuple(
        {**event, "clock_domain": clock_domain}
        if event["event_type"] == "FORCED_RELEASE_DECISION"
        else event
        for event in run.events
    )
    return RawRunArtifacts(
        run_dir=run.run_dir,
        run_id=run.run_id,
        manifest=run.manifest,
        trace=run.trace,
        replay=run.replay,
        events=events,
    )


def test_decision_outcome_uses_only_post_decision_return() -> None:
    run = _run(
        _event(11, "BLOCK_EVICTED", payload={"block_id": 1}),
        _event(
            12,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="future-request",
        ),
        _event(
            13,
            "VLLM_PREFIX_SNAPSHOT",
            program_id="agent-a",
            request_id="future-request",
            prefix_id="prefix-a",
            payload={"block_ids": [3], "reusable_token_count": 256},
        ),
    )

    rows = build_decision_outcomes_table((run,))
    by_program = {row.program_id: row for row in rows}
    returned = by_program["agent-a"]

    assert returned.return_request_id == "future-request"
    assert returned.return_arrival_event_index == 12
    assert returned.event_distance_to_return == 2
    assert returned.time_to_return_seconds == pytest.approx(2.0)
    assert returned.time_to_return_status == "available"
    assert returned.analysis_horizon_seconds == pytest.approx(3.0)
    assert returned.returned_within_horizon is True
    assert returned.return_horizon_status == "available"
    assert returned.same_prefix_reobserved is True
    assert returned.physical_eviction_event_indexes == (11,)
    assert returned.physical_eviction_match_status == "block_slot_proxy"

    no_return = by_program["agent-b"]
    assert no_return.returned_after_decision is False
    assert no_return.return_request_id is None
    assert no_return.time_to_return_status == "no_return"
    assert no_return.returned_within_horizon is False
    assert no_return.return_horizon_status == "no_return"


def test_decision_outcome_does_not_compare_incompatible_clocks() -> None:
    run = _run(
        _event(
            12,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="future-request",
            clock_domain="other-clock",
        ),
    )

    row = build_decision_outcomes_table((run,))[0]

    assert row.time_to_return_seconds is None
    assert row.time_to_return_status == "incompatible_clock_domain"
    assert row.returned_within_horizon is None
    assert row.return_horizon_status == "incompatible_clock_domain"


def test_decision_outcome_compares_known_continuum_clock_domains() -> None:
    run = _with_decision_clock(
        _run(
            _event(
                12,
                "REQUEST_ARRIVED",
                program_id="agent-a",
                request_id="future-request",
                clock_domain="continuum_lifecycle",
            ),
        ),
        "continuum_pressure",
    )

    row = build_decision_outcomes_table((run,))[0]

    assert row.time_to_return_seconds == pytest.approx(2.0)
    assert row.time_to_return_status == "available"
    assert row.returned_within_horizon is True
    assert row.return_horizon_status == "available"


def test_decision_outcome_marks_return_outside_analysis_horizon() -> None:
    run = _run(
        _event(
            14,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="late-request",
        ),
    )

    row = build_decision_outcomes_table((run,))[0]

    assert row.returned_after_decision is True
    assert row.time_to_return_seconds == pytest.approx(4.0)
    assert row.returned_within_horizon is False
    assert row.return_horizon_status == "available"


def test_decision_outcome_preserves_missing_horizon() -> None:
    run = _run(
        _event(
            12,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="future-request",
        ),
    )
    run = RawRunArtifacts(
        run_dir=run.run_dir,
        run_id=run.run_id,
        manifest={"run_id": "run-a"},
        trace=run.trace,
        replay=run.replay,
        events=run.events,
    )

    row = build_decision_outcomes_table((run,))[0]

    assert row.analysis_horizon_seconds is None
    assert row.returned_within_horizon is None
    assert row.return_horizon_status == "horizon_not_configured"


def test_decision_outcome_marks_block_slot_reuse_as_ambiguous() -> None:
    run = _run(
        _event(
            11,
            "VLLM_PREFIX_SNAPSHOT",
            program_id="pressure",
            request_id="pressure-1",
            prefix_id="other-prefix",
            payload={"block_ids": [1], "reusable_token_count": 16},
        ),
        _event(12, "BLOCK_EVICTED", payload={"block_id": 1}),
        _event(
            13,
            "REQUEST_ARRIVED",
            program_id="agent-a",
            request_id="future-request",
        ),
    )

    row = build_decision_outcomes_table((run,))[0]

    assert row.physical_eviction_event_indexes == ()
    assert row.physical_eviction_count == 0
    assert row.physical_eviction_match_status == "ambiguous_block_reuse"
