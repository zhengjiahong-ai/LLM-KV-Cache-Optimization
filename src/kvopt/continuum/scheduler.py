"""Runtime-neutral admission ordering for the Continuum scheduler baseline."""

from __future__ import annotations

from collections.abc import Sequence

from .snapshots import SchedulingCandidate
from .types import RequestIdentity


class ContinuumSchedulingPolicy:
    """Order waiting requests using only the frozen Phase 1B priority key."""

    @staticmethod
    def _priority_class(candidate: SchedulingCandidate) -> int:
        if candidate.is_preempted_waiting:
            return 1
        if candidate.is_followup and candidate.program_is_protected:
            return 2
        return 3

    def order(
        self, candidates: Sequence[SchedulingCandidate]
    ) -> tuple[RequestIdentity, ...]:
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            raise TypeError("candidates must be an ordered sequence")
        for candidate in candidates:
            if not isinstance(candidate, SchedulingCandidate):
                raise TypeError("candidates items must be SchedulingCandidate")
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                self._priority_class(candidate),
                candidate.program_arrival_timestamp,
                candidate.request_arrival_timestamp,
                candidate.request_id.value,
            ),
        )
        return tuple(candidate.request_id for candidate in ordered)


__all__ = ["ContinuumSchedulingPolicy"]
