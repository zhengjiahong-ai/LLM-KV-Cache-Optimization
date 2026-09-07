"""Immutable, runtime-neutral identity and duration record types."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


def _require_identity(value: object, expected_type: type[object], field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be {expected_type.__name__}")


def _require_non_empty_text(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_optional_non_empty_text(value: object, field_name: str) -> None:
    if value is not None:
        _require_non_empty_text(value, field_name)


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _as_non_negative_finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{field_name} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


@dataclass(frozen=True, slots=True)
class ProgramIdentity:
    """Stable program identity supplied by the workload or orchestrator."""

    value: str

    def __post_init__(self) -> None:
        _require_non_empty_text(self.value, "value")


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """Identity of one request within a program lifecycle."""

    value: str

    def __post_init__(self) -> None:
        _require_non_empty_text(self.value, "value")


@dataclass(frozen=True, slots=True)
class PrefixIdentity:
    """Opaque canonical prefix identity produced by an observation adapter."""

    canonical_value: str

    def __post_init__(self) -> None:
        _require_non_empty_text(self.canonical_value, "canonical_value")


@dataclass(frozen=True, slots=True)
class BlockIdentity:
    """Snapshot-scoped physical block identity; never a logical prefix identity."""

    block_id: int

    def __post_init__(self) -> None:
        _require_non_negative_int(self.block_id, "block_id")


class InputSource(str, Enum):
    """Frozen provenance categories for Phase 1B inputs."""

    NATIVE = "NATIVE"
    OBSERVED = "OBSERVED"
    EXTERNAL = "EXTERNAL"
    APPROXIMATED = "APPROXIMATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class InputProvenance:
    """Source classification plus an explicit reason when one is required."""

    source: InputSource
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, InputSource):
            raise TypeError("source must be InputSource")
        _require_optional_non_empty_text(self.reason, "reason")
        requires_reason = self.source in {
            InputSource.APPROXIMATED,
            InputSource.UNAVAILABLE,
        }
        if requires_reason and self.reason is None:
            raise ValueError(f"reason is required when source is {self.source.value}")


@dataclass(frozen=True, slots=True)
class ServerInterRequestGapRecord:
    """Observed server gap between one turn finishing and the next request arriving."""

    program_id: ProgramIdentity
    previous_request_id: RequestIdentity
    next_request_id: RequestIdentity
    previous_finish_timestamp: float
    next_arrival_timestamp: float
    tool_type: str | None = None

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.previous_request_id, RequestIdentity, "previous_request_id")
        _require_identity(self.next_request_id, RequestIdentity, "next_request_id")
        _require_optional_non_empty_text(self.tool_type, "tool_type")
        start = _as_non_negative_finite_float(
            self.previous_finish_timestamp, "previous_finish_timestamp"
        )
        end = _as_non_negative_finite_float(
            self.next_arrival_timestamp, "next_arrival_timestamp"
        )
        if end < start:
            raise ValueError("next_arrival_timestamp must not precede previous_finish_timestamp")
        object.__setattr__(self, "previous_finish_timestamp", start)
        object.__setattr__(self, "next_arrival_timestamp", end)

    @property
    def duration_seconds(self) -> float:
        return self.next_arrival_timestamp - self.previous_finish_timestamp

    @property
    def source(self) -> InputSource:
        return InputSource.OBSERVED


@dataclass(frozen=True, slots=True)
class ExternalToolDurationRecord:
    """Duration reported by explicit external tool-gap lifecycle events."""

    program_id: ProgramIdentity
    tool_type: str
    start_timestamp: float
    end_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_non_empty_text(self.tool_type, "tool_type")
        start = _as_non_negative_finite_float(self.start_timestamp, "start_timestamp")
        end = _as_non_negative_finite_float(self.end_timestamp, "end_timestamp")
        if end < start:
            raise ValueError("end_timestamp must not precede start_timestamp")
        object.__setattr__(self, "start_timestamp", start)
        object.__setattr__(self, "end_timestamp", end)

    @property
    def duration_seconds(self) -> float:
        return self.end_timestamp - self.start_timestamp

    @property
    def source(self) -> InputSource:
        return InputSource.EXTERNAL
