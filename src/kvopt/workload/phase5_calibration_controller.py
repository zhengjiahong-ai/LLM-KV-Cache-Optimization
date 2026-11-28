"""Outcome-blind controller contracts for Phase 5 Calibration replay."""

from __future__ import annotations

import math
from dataclasses import dataclass


class CalibrationControllerError(ValueError):
    """A replay timer would violate the frozen online-information boundary."""


@dataclass(frozen=True, slots=True)
class ArmedFollowupTimer:
    """One command created only after the preceding request terminates.

    The command carries no timestamp from the frontend clock domain. EngineCore
    samples its own receipt time and derives the expiry from ``timeout_seconds``.
    """

    candidate_id: str
    chain_id: str
    program_id: str
    session_id: str
    predecessor_request_id: str
    successor_request_id: str
    timeout_seconds: float
    source: str = "OBSERVED_PREDECESSOR_TERMINAL_PLUS_FROZEN_TOOL_GAP"

    def __post_init__(self) -> None:
        identities = (
            self.candidate_id,
            self.chain_id,
            self.program_id,
            self.session_id,
            self.predecessor_request_id,
            self.successor_request_id,
        )
        if any(not isinstance(value, str) or not value for value in identities):
            raise CalibrationControllerError("controller timer identities must be non-empty")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) < 0.0
        ):
            raise CalibrationControllerError("controller timer duration must be non-negative")

    def engine_core_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "chain_id": self.chain_id,
            "program_id": self.program_id,
            "session_id": self.session_id,
            "timeout_seconds": float(self.timeout_seconds),
            "predecessor_request_id": self.predecessor_request_id,
            "successor_request_id": self.successor_request_id,
            "source": self.source,
        }


def arm_followup_after_terminal(
    *,
    candidate_id: str,
    chain_id: str,
    program_id: str,
    session_id: str,
    predecessor_request_id: str,
    successor_request_id: str,
    observed_tool_gap_seconds: float,
    predecessor_terminal_observed: bool,
) -> ArmedFollowupTimer:
    """Create the DVA timer only at the observed predecessor terminal boundary."""

    if predecessor_terminal_observed is not True:
        raise CalibrationControllerError(
            "follow-up timer cannot be armed before predecessor terminal observation"
        )
    return ArmedFollowupTimer(
        candidate_id=candidate_id,
        chain_id=chain_id,
        program_id=program_id,
        session_id=session_id,
        predecessor_request_id=predecessor_request_id,
        successor_request_id=successor_request_id,
        timeout_seconds=observed_tool_gap_seconds,
    )
