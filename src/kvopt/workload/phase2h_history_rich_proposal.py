"""Pure planning helpers for the Phase 2H history-rich smoke proposal.

This module does not execute Native requests.  It makes the proposed
three-session logical schedule auditable before M1 authorizes Runner work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class MockBoundaryKind(StrEnum):
    ARRIVAL = "ARRIVAL"
    COMPLETION = "COMPLETION"
    PRESSURE = "PRESSURE"


@dataclass(frozen=True, slots=True)
class MockBoundary:
    boundary_id: str
    logical_timestamp: float
    kind: MockBoundaryKind
    session_index: int | None
    round_index: int | None
    request_id: str | None
    source: str


@dataclass(frozen=True, slots=True)
class HistoryRichMockTimeline:
    boundaries: tuple[MockBoundary, ...]
    request_count: int
    pressure_rounds: tuple[int, ...]
    global_gap_count_before_first_pressure: int
    controlled_join_delay_seconds_by_session: tuple[float, ...]


def _numeric(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    return float(value)


def materialize_history_rich_mock_timeline(
    *,
    sessions: Sequence[Sequence[Mapping[str, object]]],
    pressure_after_rounds: Sequence[int] = (40, 50, 55),
    cross_session_start_stagger_seconds: float = 0.25,
) -> HistoryRichMockTimeline:
    """Materialize the proposed source-time merge without Native execution.

    Source submit/completion offsets and within-session gaps are preserved as
    lower bounds.  A pressure barrier may delay the next segment, but never
    shortens a source gap.  Equal timestamps use session index as the stable
    tie-break rather than claiming strict round-robin wall-clock fidelity.
    """
    if len(sessions) != 3:
        raise ValueError("history-rich proposal requires exactly three sessions")
    if cross_session_start_stagger_seconds < 0:
        raise ValueError("cross-session start stagger must be non-negative")
    lengths = {len(session) for session in sessions}
    if lengths != {60}:
        raise ValueError("each history-rich proposal session must contain 60 calls")
    pressure_rounds = tuple(pressure_after_rounds)
    if pressure_rounds != tuple(sorted(set(pressure_rounds))):
        raise ValueError("pressure rounds must be unique and increasing")
    if not pressure_rounds or pressure_rounds[0] < 2 or pressure_rounds[-1] >= 60:
        raise ValueError("pressure rounds must leave source history and later returns")

    normalized: list[list[tuple[str, float, float]]] = []
    request_ids: set[str] = set()
    for session_index, calls in enumerate(sessions):
        first_submit = _numeric(calls[0], "model_submit_monotonic_seconds")
        offset = session_index * cross_session_start_stagger_seconds
        previous_completion: float | None = None
        session_rows: list[tuple[str, float, float]] = []
        for row in calls:
            request_id = row.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("source request identity must be non-empty")
            if request_id in request_ids:
                raise ValueError("source request identities must be unique")
            submitted = _numeric(row, "model_submit_monotonic_seconds")
            completed = _numeric(row, "model_completion_monotonic_seconds")
            if completed < submitted:
                raise ValueError("source completion precedes submission")
            if previous_completion is not None and submitted < previous_completion:
                raise ValueError("source sessions must not overlap themselves")
            request_ids.add(request_id)
            previous_completion = completed
            session_rows.append(
                (
                    request_id,
                    offset + submitted - first_submit,
                    offset + completed - first_submit,
                )
            )
        normalized.append(session_rows)

    delays = [0.0, 0.0, 0.0]
    boundaries: list[MockBoundary] = []
    for zero_based_round in range(60):
        round_index = zero_based_round + 1
        round_completions: list[float] = []
        for session_index, calls in enumerate(normalized):
            request_id, arrival, completion = calls[zero_based_round]
            arrival += delays[session_index]
            completion += delays[session_index]
            round_completions.append(completion)
            boundaries.extend(
                (
                    MockBoundary(
                        boundary_id=f"arrival:{request_id}",
                        logical_timestamp=arrival,
                        kind=MockBoundaryKind.ARRIVAL,
                        session_index=session_index,
                        round_index=round_index,
                        request_id=request_id,
                        source="W1C_SOURCE_TIME_MERGE",
                    ),
                    MockBoundary(
                        boundary_id=f"completion:{request_id}",
                        logical_timestamp=completion,
                        kind=MockBoundaryKind.COMPLETION,
                        session_index=session_index,
                        round_index=round_index,
                        request_id=request_id,
                        source="W1C_SOURCE_TIME_MERGE",
                    ),
                )
            )
        if round_index not in pressure_rounds:
            continue
        pressure_timestamp = max(round_completions)
        boundaries.append(
            MockBoundary(
                boundary_id=f"pressure:after-round-{round_index}",
                logical_timestamp=pressure_timestamp,
                kind=MockBoundaryKind.PRESSURE,
                session_index=None,
                round_index=round_index,
                request_id=None,
                source="FROZEN_THREE_SESSION_PRESSURE_BARRIER",
            )
        )
        next_index = zero_based_round + 1
        for session_index, calls in enumerate(normalized):
            _, next_arrival, _ = calls[next_index]
            next_arrival += delays[session_index]
            delays[session_index] += max(0.0, pressure_timestamp - next_arrival)

    kind_order = {
        MockBoundaryKind.COMPLETION: 0,
        MockBoundaryKind.PRESSURE: 1,
        MockBoundaryKind.ARRIVAL: 2,
    }
    boundaries.sort(
        key=lambda row: (
            row.logical_timestamp,
            kind_order[row.kind],
            -1 if row.session_index is None else row.session_index,
            row.boundary_id,
        )
    )
    first_pressure_round = pressure_rounds[0]
    return HistoryRichMockTimeline(
        boundaries=tuple(boundaries),
        request_count=len(request_ids),
        pressure_rounds=pressure_rounds,
        global_gap_count_before_first_pressure=len(sessions)
        * (first_pressure_round - 1),
        controlled_join_delay_seconds_by_session=tuple(delays),
    )

