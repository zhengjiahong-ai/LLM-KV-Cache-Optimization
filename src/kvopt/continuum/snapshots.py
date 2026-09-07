"""Immutable, runtime-neutral snapshots for Continuum policies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .types import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    _as_non_negative_finite_float,
    _require_identity,
    _require_optional_non_empty_text,
)


def _as_finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{field_name} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _require_boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_optional_int(value: object, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError(f"{field_name} must be int or None")


def _normalize_non_negative_float_tuple(
    value: object, field_name: str
) -> tuple[float, ...]:
    if isinstance(value, (set, frozenset)) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return tuple(
        _as_non_negative_finite_float(item, f"{field_name} item") for item in value
    )


def _normalize_block_id_tuple(value: object) -> tuple[BlockIdentity, ...]:
    if isinstance(value, (set, frozenset)) or not isinstance(value, (list, tuple)):
        raise TypeError("block_ids must be an ordered list or tuple")
    block_ids = tuple(value)
    for block_id in block_ids:
        _require_identity(block_id, BlockIdentity, "block_ids item")
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("block_ids must not contain duplicates")
    return block_ids


def _require_provenance(value: object, field_name: str) -> None:
    if not isinstance(value, InputProvenance):
        raise TypeError(f"{field_name} must be InputProvenance")


def _require_provenance_source(
    value: InputProvenance,
    allowed_sources: frozenset[InputSource],
    field_name: str,
) -> None:
    _require_provenance(value, field_name)
    if value.source not in allowed_sources:
        allowed = ", ".join(sorted(source.value for source in allowed_sources))
        raise ValueError(f"{field_name}.source must be one of: {allowed}")


class TTLHistoryMode(str, Enum):
    """History tier selected by the frozen TTL cold-start hierarchy."""

    COLD_START = "cold_start"
    GLOBAL = "global"
    TOOL_SPECIFIC = "tool_specific"


@dataclass(frozen=True, slots=True)
class EvictedRequestQueueDelayRecord:
    """Observed queue delay for a request whose reusable GPU KV was evicted."""

    program_id: ProgramIdentity
    request_id: RequestIdentity
    arrival_timestamp: float
    admission_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        arrival = _as_non_negative_finite_float(
            self.arrival_timestamp, "arrival_timestamp"
        )
        admission = _as_non_negative_finite_float(
            self.admission_timestamp, "admission_timestamp"
        )
        if admission < arrival:
            raise ValueError("admission_timestamp must not precede arrival_timestamp")
        object.__setattr__(self, "arrival_timestamp", arrival)
        object.__setattr__(self, "admission_timestamp", admission)

    @property
    def duration_seconds(self) -> float:
        return self.admission_timestamp - self.arrival_timestamp

    @property
    def source(self) -> InputSource:
        return InputSource.OBSERVED


@dataclass(frozen=True, slots=True)
class PrefixAssociationSnapshot:
    """Observed logical prefix to physical block association."""

    program_id: ProgramIdentity
    prefix_id: PrefixIdentity
    block_ids: tuple[BlockIdentity, ...]
    observation_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.prefix_id, PrefixIdentity, "prefix_id")
        block_ids = _normalize_block_id_tuple(self.block_ids)
        timestamp = _as_non_negative_finite_float(
            self.observation_timestamp, "observation_timestamp"
        )
        object.__setattr__(self, "block_ids", block_ids)
        object.__setattr__(self, "observation_timestamp", timestamp)

    @property
    def source(self) -> InputSource:
        return InputSource.OBSERVED


@dataclass(frozen=True, slots=True)
class RetentionEntrySnapshot:
    """Read-only state of one logical ``(program, prefix)`` retention entry."""

    ttl_decision: TTLDecision
    protected: bool
    waiting_followup: bool
    block_ids: tuple[BlockIdentity, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.ttl_decision, TTLDecision):
            raise TypeError("ttl_decision must be TTLDecision")
        _require_boolean(self.protected, "protected")
        _require_boolean(self.waiting_followup, "waiting_followup")
        object.__setattr__(self, "block_ids", _normalize_block_id_tuple(self.block_ids))

    @property
    def program_id(self) -> ProgramIdentity:
        return self.ttl_decision.program_id

    @property
    def prefix_id(self) -> PrefixIdentity:
        return self.ttl_decision.prefix_id

    @property
    def deadline_timestamp(self) -> float:
        return self.ttl_decision.deadline_timestamp


@dataclass(frozen=True, slots=True)
class TTLInput:
    """Complete immutable input to one dynamic-TTL decision."""

    program_id: ProgramIdentity
    request_id: RequestIdentity
    prefix_id: PrefixIdentity
    decision_timestamp: float
    next_tool_type: str | None
    global_server_gap_samples_seconds: tuple[float, ...]
    tool_server_gap_samples_seconds: tuple[float, ...]
    queue_delay_t_seconds: float
    eta: float
    prefill_reload_seconds: float
    default_ttl_seconds: float
    server_gap_history_provenance: InputProvenance
    queue_delay_provenance: InputProvenance
    eta_provenance: InputProvenance
    prefill_reload_provenance: InputProvenance
    default_ttl_provenance: InputProvenance

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _require_identity(self.prefix_id, PrefixIdentity, "prefix_id")
        _require_optional_non_empty_text(self.next_tool_type, "next_tool_type")
        object.__setattr__(
            self,
            "decision_timestamp",
            _as_non_negative_finite_float(
                self.decision_timestamp, "decision_timestamp"
            ),
        )
        object.__setattr__(
            self,
            "global_server_gap_samples_seconds",
            _normalize_non_negative_float_tuple(
                self.global_server_gap_samples_seconds,
                "global_server_gap_samples_seconds",
            ),
        )
        object.__setattr__(
            self,
            "tool_server_gap_samples_seconds",
            _normalize_non_negative_float_tuple(
                self.tool_server_gap_samples_seconds,
                "tool_server_gap_samples_seconds",
            ),
        )
        if (
            self.next_tool_type is None
            and self.tool_server_gap_samples_seconds
        ):
            raise ValueError(
                "tool-specific server gap samples require next_tool_type"
            )
        object.__setattr__(
            self,
            "queue_delay_t_seconds",
            _as_non_negative_finite_float(
                self.queue_delay_t_seconds, "queue_delay_t_seconds"
            ),
        )
        object.__setattr__(self, "eta", _as_finite_float(self.eta, "eta"))
        object.__setattr__(
            self,
            "prefill_reload_seconds",
            _as_non_negative_finite_float(
                self.prefill_reload_seconds, "prefill_reload_seconds"
            ),
        )
        object.__setattr__(
            self,
            "default_ttl_seconds",
            _as_non_negative_finite_float(
                self.default_ttl_seconds, "default_ttl_seconds"
            ),
        )
        _require_provenance_source(
            self.server_gap_history_provenance,
            frozenset({InputSource.OBSERVED}),
            "server_gap_history_provenance",
        )
        _require_provenance_source(
            self.queue_delay_provenance,
            frozenset({InputSource.OBSERVED}),
            "queue_delay_provenance",
        )
        _require_provenance_source(
            self.eta_provenance,
            frozenset({InputSource.OBSERVED, InputSource.APPROXIMATED}),
            "eta_provenance",
        )
        _require_provenance_source(
            self.prefill_reload_provenance,
            frozenset({InputSource.APPROXIMATED}),
            "prefill_reload_provenance",
        )
        _require_provenance_source(
            self.default_ttl_provenance,
            frozenset({InputSource.APPROXIMATED}),
            "default_ttl_provenance",
        )


@dataclass(frozen=True, slots=True)
class TTLDecision:
    """A TTL result whose absolute deadline is derived, never caller supplied."""

    ttl_input: TTLInput
    ttl_seconds: float
    history_mode: TTLHistoryMode
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ttl_input, TTLInput):
            raise TypeError("ttl_input must be TTLInput")
        if not isinstance(self.history_mode, TTLHistoryMode):
            raise TypeError("history_mode must be TTLHistoryMode")
        _require_optional_non_empty_text(self.reason, "reason")
        if (
            self.history_mode is TTLHistoryMode.TOOL_SPECIFIC
            and self.ttl_input.next_tool_type is None
        ):
            raise ValueError("tool-specific history requires next_tool_type")
        if self.ttl_input.next_tool_type is None and self.reason is None:
            raise ValueError("missing next_tool_type fallback requires reason")
        if self.history_mode is TTLHistoryMode.COLD_START and self.reason is None:
            raise ValueError("cold-start TTL decision requires reason")
        ttl_seconds = _as_non_negative_finite_float(self.ttl_seconds, "ttl_seconds")
        _as_non_negative_finite_float(
            self.decision_timestamp + ttl_seconds, "deadline_timestamp"
        )
        object.__setattr__(self, "ttl_seconds", ttl_seconds)

    @property
    def program_id(self) -> ProgramIdentity:
        return self.ttl_input.program_id

    @property
    def request_id(self) -> RequestIdentity:
        return self.ttl_input.request_id

    @property
    def prefix_id(self) -> PrefixIdentity:
        return self.ttl_input.prefix_id

    @property
    def decision_timestamp(self) -> float:
        return self.ttl_input.decision_timestamp

    @property
    def deadline_timestamp(self) -> float:
        return self.decision_timestamp + self.ttl_seconds


@dataclass(frozen=True, slots=True)
class SchedulingCandidate:
    """Minimum immutable state for frozen Phase 1B admission ordering."""

    program_id: ProgramIdentity
    request_id: RequestIdentity
    program_arrival_timestamp: float
    request_arrival_timestamp: float
    snapshot_timestamp: float
    turn_index: int
    is_preempted_waiting: bool
    is_followup: bool
    program_is_protected: bool
    native_priority: int | None = None
    retention_deadline_timestamp: float | None = None

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        program_arrival = _as_non_negative_finite_float(
            self.program_arrival_timestamp, "program_arrival_timestamp"
        )
        request_arrival = _as_non_negative_finite_float(
            self.request_arrival_timestamp, "request_arrival_timestamp"
        )
        snapshot = _as_non_negative_finite_float(
            self.snapshot_timestamp, "snapshot_timestamp"
        )
        if request_arrival < program_arrival:
            raise ValueError(
                "request_arrival_timestamp must not precede program_arrival_timestamp"
            )
        if snapshot < request_arrival:
            raise ValueError("snapshot_timestamp must not precede request_arrival_timestamp")
        _require_non_negative_int(self.turn_index, "turn_index")
        _require_boolean(self.is_preempted_waiting, "is_preempted_waiting")
        _require_boolean(self.is_followup, "is_followup")
        _require_boolean(self.program_is_protected, "program_is_protected")
        _require_optional_int(self.native_priority, "native_priority")
        deadline = self.retention_deadline_timestamp
        if deadline is not None:
            deadline = _as_non_negative_finite_float(
                deadline, "retention_deadline_timestamp"
            )
        object.__setattr__(self, "program_arrival_timestamp", program_arrival)
        object.__setattr__(self, "request_arrival_timestamp", request_arrival)
        object.__setattr__(self, "snapshot_timestamp", snapshot)
        object.__setattr__(self, "retention_deadline_timestamp", deadline)

    @property
    def waiting_age_seconds(self) -> float:
        return self.snapshot_timestamp - self.request_arrival_timestamp
