"""Separate in-memory histories for the frozen Phase 1B TTL inputs."""

from __future__ import annotations

import math

from .snapshots import EvictedRequestQueueDelayRecord
from .types import (
    ExternalToolDurationRecord,
    InputProvenance,
    InputSource,
    ProgramIdentity,
    ServerInterRequestGapRecord,
    _require_identity,
    _require_non_empty_text,
)


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


class ServerGapHistory:
    """Insertion-ordered server inter-request gap samples."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: list[ServerInterRequestGapRecord] = []

    def record(self, record: ServerInterRequestGapRecord) -> None:
        if not isinstance(record, ServerInterRequestGapRecord):
            raise TypeError("record must be ServerInterRequestGapRecord")
        self._records.append(record)

    def global_samples(self) -> tuple[float, ...]:
        return tuple(record.duration_seconds for record in self._records)

    def samples_for_tool(self, tool_type: str) -> tuple[float, ...]:
        _require_non_empty_text(tool_type, "tool_type")
        return tuple(
            record.duration_seconds
            for record in self._records
            if record.tool_type == tool_type
        )


class ExternalToolDurationHistory:
    """Insertion-ordered external tool duration samples kept separately."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: list[ExternalToolDurationRecord] = []

    def record(self, record: ExternalToolDurationRecord) -> None:
        if not isinstance(record, ExternalToolDurationRecord):
            raise TypeError("record must be ExternalToolDurationRecord")
        self._records.append(record)

    def global_samples(self) -> tuple[float, ...]:
        return tuple(record.duration_seconds for record in self._records)

    def samples_for_tool(self, tool_type: str) -> tuple[float, ...]:
        _require_non_empty_text(tool_type, "tool_type")
        return tuple(
            record.duration_seconds
            for record in self._records
            if record.tool_type == tool_type
        )


class QueueDelayHistory:
    """Eligible queue-delay samples for the frozen T term."""

    __slots__ = ("_samples", "_window_size")

    def __init__(self, window_size: int) -> None:
        self._window_size = _require_positive_int(window_size, "window_size")
        self._samples: list[float] = []

    def record(
        self,
        record: EvictedRequestQueueDelayRecord,
    ) -> None:
        if not isinstance(record, EvictedRequestQueueDelayRecord):
            raise TypeError("record must be EvictedRequestQueueDelayRecord")
        self._samples.append(record.duration_seconds)

    def samples(self) -> tuple[float, ...]:
        return tuple(self._samples)

    def recent_samples(self) -> tuple[float, ...]:
        return tuple(self._samples[-self._window_size:])

    def mean_seconds(self) -> float:
        samples = self.recent_samples()
        if not samples:
            return 0.0
        return sum(samples) / len(samples)


class CompletedProgramEtaHistory:
    """Complete-program turn pairs used by the memoryfulness estimator."""

    __slots__ = ("_pairs", "_program_turn_counts")

    def __init__(self) -> None:
        self._program_turn_counts: dict[ProgramIdentity, int] = {}
        self._pairs: list[tuple[int, int]] = []

    def record_completed_program(
        self, program_id: ProgramIdentity, final_turn_count: int
    ) -> None:
        _require_identity(program_id, ProgramIdentity, "program_id")
        count = _require_positive_int(final_turn_count, "final_turn_count")
        if program_id in self._program_turn_counts:
            if self._program_turn_counts[program_id] != count:
                raise ValueError("program_id was already recorded with another turn count")
            return
        self._program_turn_counts[program_id] = count
        self._pairs.extend((turn_index, count - turn_index) for turn_index in range(1, count))

    def samples(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._pairs)

    def eta(self) -> tuple[float, InputProvenance]:
        if len(self._pairs) < 2:
            return 1.0, InputProvenance(
                InputSource.APPROXIMATED, "FULLY_MEMORYFUL_COLD_START"
            )
        x_values = [pair[0] for pair in self._pairs]
        y_values = [pair[1] for pair in self._pairs]
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(y_values) / len(y_values)
        covariance = sum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in self._pairs
        )
        x_variance = sum((value - x_mean) ** 2 for value in x_values)
        y_variance = sum((value - y_mean) ** 2 for value in y_values)
        denominator = math.sqrt(x_variance * y_variance)
        if denominator == 0.0:
            return 1.0, InputProvenance(
                InputSource.APPROXIMATED, "FULLY_MEMORYFUL_COLD_START"
            )
        return -covariance / denominator, InputProvenance(InputSource.OBSERVED)
