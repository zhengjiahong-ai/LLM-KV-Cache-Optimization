from __future__ import annotations

from itertools import pairwise

import pytest

from kvopt.workload.phase2h_history_rich_proposal import (
    MockBoundaryKind,
    materialize_history_rich_mock_timeline,
)


def _sessions():
    sessions = []
    for session_index in range(3):
        calls = []
        cursor = 1000.0 * session_index
        for round_index in range(1, 61):
            gap = 0.2 + session_index * 0.1
            submitted = cursor + gap
            completed = submitted + 0.05
            calls.append(
                {
                    "request_id": f"s{session_index}-r{round_index}",
                    "model_submit_monotonic_seconds": submitted,
                    "model_completion_monotonic_seconds": completed,
                }
            )
            cursor = completed
        sessions.append(tuple(calls))
    return tuple(sessions)


def test_three_session_mock_has_180_requests_and_three_barriers() -> None:
    result = materialize_history_rich_mock_timeline(sessions=_sessions())

    assert result.request_count == 180
    assert len(result.boundaries) == 363
    assert result.pressure_rounds == (40, 50, 55)
    assert result.global_gap_count_before_first_pressure == 117
    assert result.global_gap_count_before_first_pressure > 100
    assert sum(row.kind is MockBoundaryKind.PRESSURE for row in result.boundaries) == 3


def test_pressure_barriers_precede_next_segment_and_leave_later_returns() -> None:
    result = materialize_history_rich_mock_timeline(sessions=_sessions())
    rows = result.boundaries
    for pressure_round in result.pressure_rounds:
        pressure = next(
            row
            for row in rows
            if row.kind is MockBoundaryKind.PRESSURE
            and row.round_index == pressure_round
        )
        next_arrivals = [
            row
            for row in rows
            if row.kind is MockBoundaryKind.ARRIVAL
            and row.round_index == pressure_round + 1
        ]
        assert len(next_arrivals) == 3
        assert all(row.logical_timestamp >= pressure.logical_timestamp for row in next_arrivals)

    later_returns = [
        row
        for row in rows
        if row.kind is MockBoundaryKind.ARRIVAL and (row.round_index or 0) > 55
    ]
    assert len(later_returns) == 15


def test_barrier_delays_never_shorten_observed_session_gaps() -> None:
    sessions = _sessions()
    result = materialize_history_rich_mock_timeline(sessions=sessions)
    arrivals = {
        row.request_id: row.logical_timestamp
        for row in result.boundaries
        if row.kind is MockBoundaryKind.ARRIVAL
    }
    completions = {
        row.request_id: row.logical_timestamp
        for row in result.boundaries
        if row.kind is MockBoundaryKind.COMPLETION
    }
    for calls in sessions:
        for previous, current in pairwise(calls):
            source_gap = (
                current["model_submit_monotonic_seconds"]
                - previous["model_completion_monotonic_seconds"]
            )
            effective_gap = arrivals[current["request_id"]] - completions[
                previous["request_id"]
            ]
            assert effective_gap + 1e-12 >= source_gap


def test_mock_rejects_non_three_session_or_terminal_pressure() -> None:
    sessions = _sessions()
    with pytest.raises(ValueError, match="exactly three"):
        materialize_history_rich_mock_timeline(sessions=sessions[:2])
    with pytest.raises(ValueError, match="later returns"):
        materialize_history_rich_mock_timeline(
            sessions=sessions,
            pressure_after_rounds=(40, 50, 60),
        )
