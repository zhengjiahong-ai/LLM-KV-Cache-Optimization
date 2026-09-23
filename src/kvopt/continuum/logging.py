"""Deterministic structured logging contracts for reproducible experiments."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .config import RetentionMode, SchedulerMode
from .events import LifecycleEventType
from .selection import EligibilityTier
from .snapshots import TTLHistoryMode
from .types import (
    BlockIdentity,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    _as_non_negative_finite_float,
    _require_identity,
    _require_non_empty_text,
    _require_optional_non_empty_text,
)


class StructuredLogEvent(str, Enum):
    """Project-frozen event names for reproducible Phase 1B experiments."""

    PROGRAM_REQUEST_ASSOCIATED = "PROGRAM_REQUEST_ASSOCIATED"
    TOOL_GAP_STARTED = "TOOL_GAP_STARTED"
    TOOL_GAP_ENDED = "TOOL_GAP_ENDED"
    SERVER_GAP_OBSERVED = "SERVER_GAP_OBSERVED"
    PREFIX_BLOCKS_ASSOCIATED = "PREFIX_BLOCKS_ASSOCIATED"
    RETENTION_PROTECTED = "RETENTION_PROTECTED"
    RETENTION_EXPIRED = "RETENTION_EXPIRED"
    RETENTION_EXPIRY_DEFERRED = "RETENTION_EXPIRY_DEFERRED"
    RETENTION_RELEASED_PRESSURE = "RETENTION_RELEASED_PRESSURE"
    RETENTION_SELECTION_PLANNED = "RETENTION_SELECTION_PLANNED"
    TTL_DECIDED = "TTL_DECIDED"
    QUEUE_DELAY_OBSERVED = "QUEUE_DELAY_OBSERVED"
    BLOCK_EVICTED = "BLOCK_EVICTED"
    STALE_ASSOCIATION_REMOVED = "STALE_ASSOCIATION_REMOVED"
    SCHEDULER_SHADOW = "SCHEDULER_SHADOW"
    SCHEDULER_CONTROLLED = "SCHEDULER_CONTROLLED"


_EXPLICIT_ENUM_TYPES = (
    EligibilityTier,
    InputSource,
    LifecycleEventType,
    RetentionMode,
    SchedulerMode,
    StructuredLogEvent,
    TTLHistoryMode,
)


@dataclass(frozen=True, slots=True)
class FrozenJsonObject(Mapping[str, object]):
    """Hashable immutable JSON object with keys stored in lexical order."""

    entries: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("entries must be tuple")
        keys = []
        for entry in self.entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("each entry must be a (key, value) tuple")
            key, value = entry
            _require_non_empty_text(key, "JSON mapping key")
            _require_frozen_json_value(value)
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise ValueError("JSON mapping keys must be unique")
        if keys != sorted(keys):
            raise ValueError("JSON mapping keys must be stored in lexical order")

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, key: str) -> object:
        for entry_key, value in self.entries:
            if entry_key == key:
                return value
        raise KeyError(key)


def _require_frozen_json_value(value: object) -> None:
    if isinstance(value, Enum):
        raise TypeError("frozen JSON values must not contain enum objects")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON float values must be finite")
        return
    if isinstance(value, FrozenJsonObject):
        return
    if isinstance(value, tuple):
        for item in value:
            _require_frozen_json_value(item)
        return
    raise TypeError(f"unsupported frozen JSON value type: {type(value).__name__}")


def _freeze_json_value(value: object, active_path: set[int]) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, _EXPLICIT_ENUM_TYPES):
        return value.value
    if isinstance(value, Enum):
        raise TypeError(f"unsupported JSON enum type: {type(value).__name__}")
    if isinstance(value, str):
        return value
    if isinstance(value, ProgramIdentity):
        return value.value
    if isinstance(value, RequestIdentity):
        return value.value
    if isinstance(value, PrefixIdentity):
        return value.canonical_value
    if isinstance(value, BlockIdentity):
        return value.block_id
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON float values must be finite")
        return value
    if isinstance(value, FrozenJsonObject):
        return value
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in active_path:
            raise ValueError("cyclic JSON mapping is not supported")
        active_path.add(object_id)
        try:
            entries = []
            for key, item in value.items():
                _require_non_empty_text(key, "JSON mapping key")
                entries.append((key, _freeze_json_value(item, active_path)))
            entries.sort(key=lambda entry: entry[0])
            return FrozenJsonObject(tuple(entries))
        finally:
            active_path.remove(object_id)
    if isinstance(value, (list, tuple)):
        object_id = id(value)
        if object_id in active_path:
            raise ValueError("cyclic JSON sequence is not supported")
        active_path.add(object_id)
        try:
            return tuple(_freeze_json_value(item, active_path) for item in value)
        finally:
            active_path.remove(object_id)
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _freeze_fields(value: object) -> FrozenJsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("fields must be a mapping")
    frozen = _freeze_json_value(value, set())
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("fields must freeze to a JSON object")
    return frozen


def _to_json_value(value: object) -> object:
    if isinstance(value, FrozenJsonObject):
        return {key: _to_json_value(item) for key, item in value.entries}
    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class StructuredLogRecord:
    """One deeply immutable structured event with stable top-level fields."""

    event: StructuredLogEvent
    timestamp: float
    mode: RetentionMode | SchedulerMode | None = None
    program_id: ProgramIdentity | None = None
    request_id: RequestIdentity | None = None
    prefix_id: PrefixIdentity | None = None
    source: InputSource | None = None
    reason: str | None = None
    fields: FrozenJsonObject | Mapping[str, object] = FrozenJsonObject(())

    def __post_init__(self) -> None:
        if not isinstance(self.event, StructuredLogEvent):
            raise TypeError("event must be StructuredLogEvent")
        timestamp = _as_non_negative_finite_float(self.timestamp, "timestamp")
        if self.mode is not None and not isinstance(
            self.mode, (RetentionMode, SchedulerMode)
        ):
            raise TypeError("mode must be RetentionMode, SchedulerMode, or None")
        if self.program_id is not None:
            _require_identity(self.program_id, ProgramIdentity, "program_id")
        if self.request_id is not None:
            _require_identity(self.request_id, RequestIdentity, "request_id")
        if self.prefix_id is not None:
            _require_identity(self.prefix_id, PrefixIdentity, "prefix_id")
        if self.source is not None and not isinstance(self.source, InputSource):
            raise TypeError("source must be InputSource or None")
        _require_optional_non_empty_text(self.reason, "reason")
        if (
            self.source in {InputSource.APPROXIMATED, InputSource.UNAVAILABLE}
            and self.reason is None
        ):
            raise ValueError(f"reason is required when source is {self.source.value}")
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "fields", _freeze_fields(self.fields))

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.value,
            "timestamp": self.timestamp,
            "mode": None if self.mode is None else self.mode.value,
            "program_id": None if self.program_id is None else self.program_id.value,
            "request_id": None if self.request_id is None else self.request_id.value,
            "prefix_id": (
                None if self.prefix_id is None else self.prefix_id.canonical_value
            ),
            "source": None if self.source is None else self.source.value,
            "reason": self.reason,
            "fields": _to_json_value(self.fields),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )


@runtime_checkable
class StructuredEventSink(Protocol):
    """Stable destination boundary for immutable structured log records."""

    def emit(self, record: StructuredLogRecord) -> None:
        """Accept one validated record without changing it."""


class NullEventSink:
    """Discard validated records without side effects."""

    __slots__ = ()

    def emit(self, record: StructuredLogRecord) -> None:
        return None


class InMemoryEventSink:
    """Collect records for deterministic tests without exposing mutable storage."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: list[StructuredLogRecord] = []

    def emit(self, record: StructuredLogRecord) -> None:
        if not isinstance(record, StructuredLogRecord):
            raise TypeError("record must be StructuredLogRecord")
        self._records.append(record)

    def snapshot(self) -> tuple[StructuredLogRecord, ...]:
        return tuple(self._records)
