import pytest

from kvopt.continuum.history import (
    CompletedProgramEtaHistory,
    ExternalToolDurationHistory,
    QueueDelayHistory,
    ServerGapHistory,
)
from kvopt.continuum.snapshots import EvictedRequestQueueDelayRecord
from kvopt.continuum.types import (
    ExternalToolDurationRecord,
    InputSource,
    ProgramIdentity,
    RequestIdentity,
    ServerInterRequestGapRecord,
)


def _program(value: str) -> ProgramIdentity:
    return ProgramIdentity(value)


def _request(value: str) -> RequestIdentity:
    return RequestIdentity(value)


def _server_gap(
    program: str,
    previous_request: str,
    next_request: str,
    start: float,
    end: float,
    tool_type: str | None = None,
) -> ServerInterRequestGapRecord:
    return ServerInterRequestGapRecord(
        _program(program),
        _request(previous_request),
        _request(next_request),
        start,
        end,
        tool_type,
    )


def _tool_gap(
    program: str, tool_type: str, start: float, end: float
) -> ExternalToolDurationRecord:
    return ExternalToolDurationRecord(_program(program), tool_type, start, end)


def _queue_delay(
    program: str, request: str, arrival: float, admission: float
) -> EvictedRequestQueueDelayRecord:
    return EvictedRequestQueueDelayRecord(
        _program(program), _request(request), arrival, admission
    )


def test_server_gap_history_keeps_global_and_tool_samples_separate() -> None:
    history = ServerGapHistory()
    history.record(_server_gap("p", "r0", "r1", 0, 2, "search"))
    history.record(_server_gap("p", "r1", "r2", 2, 5, "write"))
    history.record(_server_gap("p", "r2", "r3", 5, 9))

    assert history.global_samples() == (2.0, 3.0, 4.0)
    assert history.samples_for_tool("search") == (2.0,)
    assert history.samples_for_tool("write") == (3.0,)
    assert history.samples_for_tool("missing") == ()


def test_external_tool_duration_history_never_enters_server_gap_history() -> None:
    server_history = ServerGapHistory()
    tool_history = ExternalToolDurationHistory()
    server_history.record(_server_gap("p", "r0", "r1", 0, 2, "search"))
    tool_history.record(_tool_gap("p", "search", 10, 17))

    assert server_history.global_samples() == (2.0,)
    assert server_history.samples_for_tool("search") == (2.0,)
    assert tool_history.global_samples() == (7.0,)
    assert tool_history.samples_for_tool("search") == (7.0,)


def test_queue_delay_history_accepts_typed_eligible_record() -> None:
    history = QueueDelayHistory(100)
    record = _queue_delay("p", "r1", 1, 4)

    history.record(record)
    assert history.samples() == (3.0,)
    assert history.mean_seconds() == 3.0


def test_queue_delay_history_uses_recent_eligible_window_mean() -> None:
    history = QueueDelayHistory(100)
    for index in range(101):
        history.record(_queue_delay("p", f"r{index}", 0, float(index)))

    assert len(history.recent_samples()) == 100
    assert history.recent_samples()[0] == 1.0
    assert history.recent_samples()[-1] == 100.0
    assert history.mean_seconds() == 50.5


def test_completed_program_eta_history_emits_each_program_once() -> None:
    history = CompletedProgramEtaHistory()
    history.record_completed_program(_program("p1"), 4)
    history.record_completed_program(_program("p2"), 3)
    history.record_completed_program(_program("p1"), 4)

    assert history.samples() == (
        (1, 3),
        (2, 2),
        (3, 1),
        (1, 2),
        (2, 1),
    )


def test_completed_program_eta_history_rejects_conflicting_duplicate() -> None:
    history = CompletedProgramEtaHistory()
    history.record_completed_program(_program("p1"), 2)

    with pytest.raises(ValueError, match="already recorded"):
        history.record_completed_program(_program("p1"), 3)


def test_eta_history_uses_specified_cold_start_for_undefined_correlation() -> None:
    history = CompletedProgramEtaHistory()
    history.record_completed_program(_program("p1"), 2)

    eta, provenance = history.eta()

    assert eta == 1.0
    assert provenance.source is InputSource.APPROXIMATED
    assert provenance.reason == "FULLY_MEMORYFUL_COLD_START"


def test_eta_history_returns_defined_observed_eta() -> None:
    history = CompletedProgramEtaHistory()
    history.record_completed_program(_program("p1"), 3)
    history.record_completed_program(_program("p2"), 4)

    eta, provenance = history.eta()

    assert eta == pytest.approx(0.7857142857142857)
    assert provenance.source is InputSource.OBSERVED


def test_eta_history_uses_cold_start_for_zero_variance_correlation() -> None:
    history = CompletedProgramEtaHistory()
    history.record_completed_program(_program("p1"), 2)
    history.record_completed_program(_program("p2"), 2)

    eta, provenance = history.eta()

    assert eta == 1.0
    assert provenance.source is InputSource.APPROXIMATED
    assert provenance.reason == "FULLY_MEMORYFUL_COLD_START"


def test_history_rejects_wrong_record_types() -> None:
    history = ServerGapHistory()

    with pytest.raises(TypeError, match="ServerInterRequestGapRecord"):
        history.record(object())
