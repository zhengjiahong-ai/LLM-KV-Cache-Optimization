from __future__ import annotations

import pytest

from kvopt.workload.phase5_calibration_controller import (
    CalibrationControllerError,
    arm_followup_after_terminal,
)


def test_timer_is_created_only_after_observed_terminal() -> None:
    timer = arm_followup_after_terminal(
        candidate_id="program-1",
        chain_id="program-1:turn-1-to-2",
        program_id="program-1",
        session_id="session-1",
        predecessor_request_id="turn-1",
        successor_request_id="turn-2",
        observed_tool_gap_seconds=3.5,
        predecessor_terminal_observed=True,
    )
    assert timer.engine_core_payload() == {
        "candidate_id": "program-1",
        "chain_id": "program-1:turn-1-to-2",
        "program_id": "program-1",
        "session_id": "session-1",
        "timeout_seconds": 3.5,
        "predecessor_request_id": "turn-1",
        "successor_request_id": "turn-2",
        "source": "OBSERVED_PREDECESSOR_TERMINAL_PLUS_FROZEN_TOOL_GAP",
    }


def test_timer_fails_closed_before_predecessor_terminal() -> None:
    with pytest.raises(CalibrationControllerError, match="before predecessor"):
        arm_followup_after_terminal(
            candidate_id="program-1",
            chain_id="chain-1",
            program_id="program-1",
            session_id="session-1",
            predecessor_request_id="turn-1",
            successor_request_id="turn-2",
            observed_tool_gap_seconds=3.5,
            predecessor_terminal_observed=False,
        )


@pytest.mark.parametrize("gap", [-1.0, float("inf")])
def test_timer_rejects_invalid_gap(gap: float) -> None:
    with pytest.raises(CalibrationControllerError, match="duration"):
        arm_followup_after_terminal(
            candidate_id="program-1",
            chain_id="chain-1",
            program_id="program-1",
            session_id="session-1",
            predecessor_request_id="turn-1",
            successor_request_id="turn-2",
            observed_tool_gap_seconds=gap,
            predecessor_terminal_observed=True,
        )
