"""Injectable monotonic clocks for deterministic Continuum decisions."""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from .types import _as_non_negative_finite_float


@runtime_checkable
class Clock(Protocol):
    """Source of monotonic timestamps expressed in seconds."""

    def now(self) -> float:
        """Return a finite, non-negative monotonic timestamp."""


class SystemMonotonicClock:
    """Production clock backed by :func:`time.monotonic`."""

    def now(self) -> float:
        return _as_non_negative_finite_float(time.monotonic(), "clock timestamp")


class FakeClock:
    """Deterministic monotonic clock for tests and trace replay."""

    __slots__ = ("_timestamp",)

    def __init__(self, initial_timestamp: float = 0.0) -> None:
        self._timestamp = _as_non_negative_finite_float(
            initial_timestamp, "initial_timestamp"
        )

    def now(self) -> float:
        return self._timestamp

    def advance(self, seconds: float) -> float:
        increment = _as_non_negative_finite_float(seconds, "seconds")
        next_timestamp = self._timestamp + increment
        self._timestamp = _as_non_negative_finite_float(
            next_timestamp, "clock timestamp"
        )
        return self._timestamp

    def set(self, timestamp: float) -> None:
        next_timestamp = _as_non_negative_finite_float(timestamp, "timestamp")
        if next_timestamp < self._timestamp:
            raise ValueError("timestamp must not move backwards")
        self._timestamp = next_timestamp
