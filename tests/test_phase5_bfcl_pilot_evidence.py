from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_pilot_evidence import (
    BFCLPilotEvidenceError,
    BFCLPilotEvidenceRecorder,
    evaluate_paired_pilot_lifecycle,
    load_lifecycle_events,
)
from kvopt.workload.phase5_workload_qualification import AcquisitionTerminalState


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


class _Handler:
    def _query_FC(self, _input: dict[str, object]) -> tuple[str, float]:
        return "response", 1.0


def test_recorder_captures_model_gap_and_explicit_terminal(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = BFCLPilotEvidenceRecorder(
        path=path, monotonic=_Clock(), utc_now=lambda: "2026-11-22T00:00:00Z"
    )
    handler = _Handler()
    for case_id in ("snippet", "no-snippet"):
        with recorder.bind_case(case_id), recorder.instrument_model_query(handler):
            handler._query_FC({})
            recorder.record("TOOL_CALL_EMISSION")
            recorder.record("TOOL_RESULT_DELIVERY")
            handler._query_FC({})
            recorder.terminal(AcquisitionTerminalState.NATURAL_COMPLETION)

    report = evaluate_paired_pilot_lifecycle(
        load_lifecycle_events(path),
        expected_case_ids=("snippet", "no-snippet"),
    )
    assert report["status"] == "PASS"
    assert all(case["tool_gaps"][0]["tool_gap_seconds"] == 3.0 for case in report["cases"])


def test_missing_terminal_or_model_completion_fails_closed() -> None:
    events = (
        {
            "case_id": "snippet",
            "event_ordinal": 1,
            "event": "MODEL_REQUEST_DISPATCH",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 1.0,
        },
    )
    report = evaluate_paired_pilot_lifecycle(
        events, expected_case_ids=("snippet", "no-snippet")
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["cases"][0]["checks"]["EXACTLY_ONE_TERMINAL"] is False


def test_failed_terminal_requires_failure_reason(tmp_path: Path) -> None:
    recorder = BFCLPilotEvidenceRecorder(path=tmp_path / "events.jsonl")
    with recorder.bind_case("case"), pytest.raises(
        BFCLPilotEvidenceError, match="failure_reason"
    ):
        recorder.terminal(AcquisitionTerminalState.PROVIDER_TIMEOUT)
