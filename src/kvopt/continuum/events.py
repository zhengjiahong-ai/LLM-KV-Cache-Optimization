"""Immutable lifecycle events accepted by the Continuum observation layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import (
    BlockIdentity,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    _as_non_negative_finite_float,
    _require_identity,
    _require_non_empty_text,
    _require_optional_non_empty_text,
)


class LifecycleEventType(str, Enum):
    """Frozen names for Phase 1B lifecycle observations."""

    PROGRAM_STARTED = "PROGRAM_STARTED"
    REQUEST_ARRIVED = "REQUEST_ARRIVED"
    REQUEST_ADMITTED = "REQUEST_ADMITTED"
    REQUEST_PREEMPTED = "REQUEST_PREEMPTED"
    TURN_FINISHED = "TURN_FINISHED"
    FOLLOWUP_WAITING = "FOLLOWUP_WAITING"
    FOLLOWUP_CANCELLED = "FOLLOWUP_CANCELLED"
    TOOL_GAP_STARTED = "TOOL_GAP_STARTED"
    TOOL_GAP_ENDED = "TOOL_GAP_ENDED"
    PROGRAM_COMPLETED = "PROGRAM_COMPLETED"
    BLOCKS_OBSERVED = "BLOCKS_OBSERVED"
    BLOCK_EVICTED = "BLOCK_EVICTED"


def _normalize_timestamp(instance: object, field_name: str) -> None:
    value = _as_non_negative_finite_float(getattr(instance, field_name), field_name)
    object.__setattr__(instance, field_name, value)


def _require_boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")


def _normalize_block_id_tuple(value: object) -> tuple[BlockIdentity, ...]:
    if isinstance(value, (set, frozenset)) or not isinstance(value, (list, tuple)):
        raise TypeError("block_ids must be an ordered list or tuple")
    block_ids = tuple(value)
    for block_id in block_ids:
        _require_identity(block_id, BlockIdentity, "block_ids item")
    if len(block_ids) != len(set(block_ids)):
        raise ValueError("block_ids must not contain duplicates")
    return block_ids


@dataclass(frozen=True, slots=True)
class ProgramStarted:
    program_id: ProgramIdentity
    start_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _normalize_timestamp(self, "start_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.PROGRAM_STARTED


@dataclass(frozen=True, slots=True)
class RequestArrived:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    arrival_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "arrival_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.REQUEST_ARRIVED


@dataclass(frozen=True, slots=True)
class RequestAdmitted:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    admission_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "admission_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.REQUEST_ADMITTED


@dataclass(frozen=True, slots=True)
class RequestPreempted:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    preemption_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "preemption_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.REQUEST_PREEMPTED


@dataclass(frozen=True, slots=True)
class TurnFinished:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    finish_timestamp: float
    is_terminal: bool
    next_tool_type: str | None = None

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "finish_timestamp")
        _require_boolean(self.is_terminal, "is_terminal")
        _require_optional_non_empty_text(self.next_tool_type, "next_tool_type")
        if self.is_terminal and self.next_tool_type is not None:
            raise ValueError("terminal turn must not declare next_tool_type")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.TURN_FINISHED


@dataclass(frozen=True, slots=True)
class FollowupWaiting:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    waiting_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "waiting_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.FOLLOWUP_WAITING


@dataclass(frozen=True, slots=True)
class FollowupCancelled:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    cancellation_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _normalize_timestamp(self, "cancellation_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.FOLLOWUP_CANCELLED


@dataclass(frozen=True, slots=True)
class ToolGapStarted:
    program_id: ProgramIdentity
    tool_type: str
    start_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_non_empty_text(self.tool_type, "tool_type")
        _normalize_timestamp(self, "start_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.TOOL_GAP_STARTED


@dataclass(frozen=True, slots=True)
class ToolGapEnded:
    program_id: ProgramIdentity
    tool_type: str
    end_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_non_empty_text(self.tool_type, "tool_type")
        _normalize_timestamp(self, "end_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.TOOL_GAP_ENDED


@dataclass(frozen=True, slots=True)
class ProgramCompleted:
    program_id: ProgramIdentity
    completion_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _normalize_timestamp(self, "completion_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.PROGRAM_COMPLETED


@dataclass(frozen=True, slots=True)
class BlocksObserved:
    program_id: ProgramIdentity
    request_id: RequestIdentity
    prefix_id: PrefixIdentity
    block_ids: tuple[BlockIdentity, ...]
    observation_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        _require_identity(self.prefix_id, PrefixIdentity, "prefix_id")
        object.__setattr__(self, "block_ids", _normalize_block_id_tuple(self.block_ids))
        _normalize_timestamp(self, "observation_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.BLOCKS_OBSERVED


@dataclass(frozen=True, slots=True)
class BlockEvicted:
    block_id: BlockIdentity
    eviction_timestamp: float

    def __post_init__(self) -> None:
        _require_identity(self.block_id, BlockIdentity, "block_id")
        _normalize_timestamp(self, "eviction_timestamp")

    @property
    def event_type(self) -> LifecycleEventType:
        return LifecycleEventType.BLOCK_EVICTED


LifecycleEvent = (
    ProgramStarted
    | RequestArrived
    | RequestAdmitted
    | RequestPreempted
    | TurnFinished
    | FollowupWaiting
    | FollowupCancelled
    | ToolGapStarted
    | ToolGapEnded
    | ProgramCompleted
    | BlocksObserved
    | BlockEvicted
)
