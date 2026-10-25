"""Clock-domain boundary for controlled sparse Native replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import pairwise

from .clock import Clock, FakeClock, SystemMonotonicClock
from .types import _as_non_negative_finite_float

LOGICAL_CLOCK_DOMAIN = "continuum_logical_replay"
NATIVE_CLOCK_DOMAIN = "system_monotonic"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class LogicalTimeBoundary:
    """One immutable lifecycle-time boundary from the frozen replay schedule."""

    boundary_id: str
    logical_timestamp: float
    source: str

    def __post_init__(self) -> None:
        _text(self.boundary_id, "boundary_id")
        _as_non_negative_finite_float(self.logical_timestamp, "logical_timestamp")
        _text(self.source, "source")


@dataclass(frozen=True, slots=True)
class LogicalTimeAdvance:
    """Evidence emitted when logical time advances without wall-clock sleeping."""

    boundary_id: str
    logical_timestamp: float
    logical_clock_domain: str
    native_monotonic_timestamp: float
    native_clock_domain: str
    wall_elapsed_seconds: float
    source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ControlledSparseReplayClock:
    """Keep Continuum lifecycle time separate from Native execution time.

    The controller never sleeps.  A runner may advance lifecycle time only at
    a frozen event boundary and only after every Native request submitted
    through this controller has completed.
    """

    def __init__(
        self,
        *,
        boundaries: Iterable[LogicalTimeBoundary],
        native_clock: Clock | None = None,
        wall_timer: Clock | None = None,
    ) -> None:
        rows = tuple(boundaries)
        if not rows:
            raise ValueError("boundaries must not be empty")
        if any(not isinstance(row, LogicalTimeBoundary) for row in rows):
            raise TypeError("boundaries must contain LogicalTimeBoundary values")
        if len({row.boundary_id for row in rows}) != len(rows):
            raise ValueError("boundary IDs must be unique")
        for earlier, later in pairwise(rows):
            if later.logical_timestamp < earlier.logical_timestamp:
                raise ValueError("logical boundaries must be monotonic")

        self._boundaries = rows
        self._boundary_index = 0
        self._logical_clock = FakeClock(rows[0].logical_timestamp)
        self._native_clock = native_clock or SystemMonotonicClock()
        self._wall_timer = wall_timer or SystemMonotonicClock()
        if not isinstance(self._native_clock, Clock):
            raise TypeError("native_clock must implement Clock")
        if not isinstance(self._wall_timer, Clock):
            raise TypeError("wall_timer must implement Clock")
        self._wall_started = float(self._wall_timer.now())
        self._native_inflight: set[str] = set()
        self._advances: list[LogicalTimeAdvance] = []

    @property
    def logical_clock(self) -> Clock:
        """Clock injected into Continuum lifecycle, TTL and selection state."""
        return self._logical_clock

    @property
    def inflight_request_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._native_inflight))

    @property
    def sequence_sha256(self) -> str:
        payload = json.dumps(
            [asdict(row) for row in self._boundaries],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def native_submitted(self, request_id: str) -> float:
        identity = _text(request_id, "request_id")
        if identity in self._native_inflight:
            raise ValueError("native request is already inflight")
        self._native_inflight.add(identity)
        return float(self._native_clock.now())

    def native_completed(self, request_id: str) -> float:
        identity = _text(request_id, "request_id")
        if identity not in self._native_inflight:
            raise ValueError("native completion has no inflight submission")
        self._native_inflight.remove(identity)
        return float(self._native_clock.now())

    def advance(self, boundary_id: str) -> LogicalTimeAdvance:
        """Advance to the next frozen boundary without sleeping."""
        if self._native_inflight:
            raise RuntimeError("logical time cannot advance with Native requests inflight")
        if self._boundary_index >= len(self._boundaries):
            raise RuntimeError("logical replay has no remaining boundary")
        expected = self._boundaries[self._boundary_index]
        if boundary_id != expected.boundary_id:
            raise ValueError(
                f"logical boundary order mismatch: expected {expected.boundary_id!r}"
            )
        self._logical_clock.set(expected.logical_timestamp)
        native_now = float(self._native_clock.now())
        wall_elapsed = float(self._wall_timer.now()) - self._wall_started
        row = LogicalTimeAdvance(
            boundary_id=expected.boundary_id,
            logical_timestamp=self._logical_clock.now(),
            logical_clock_domain=LOGICAL_CLOCK_DOMAIN,
            native_monotonic_timestamp=native_now,
            native_clock_domain=NATIVE_CLOCK_DOMAIN,
            wall_elapsed_seconds=_as_non_negative_finite_float(
                wall_elapsed, "wall_elapsed_seconds"
            ),
            source=expected.source,
        )
        self._advances.append(row)
        self._boundary_index += 1
        return row

    def advances(self) -> tuple[LogicalTimeAdvance, ...]:
        return tuple(self._advances)

    def assert_complete(self) -> None:
        if self._native_inflight:
            raise RuntimeError("logical replay ended with Native requests inflight")
        if self._boundary_index != len(self._boundaries):
            raise RuntimeError("logical replay ended before every frozen boundary")


def assert_identical_time_sequences(
    controllers: Iterable[ControlledSparseReplayClock],
) -> str:
    """Fail closed unless every policy arm consumes the same time sequence."""
    rows = tuple(controllers)
    if not rows:
        raise ValueError("controllers must not be empty")
    digests = {row.sequence_sha256 for row in rows}
    if len(digests) != 1:
        raise ValueError("policy arms do not share one frozen logical-time sequence")
    return next(iter(digests))
