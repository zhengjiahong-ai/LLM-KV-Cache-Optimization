"""Runtime-neutral raw experiment event contracts for Phase 2."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from kvopt.continuum.events import (
    BlockEvicted,
    BlocksObserved,
    FollowupCancelled,
    FollowupWaiting,
    ProgramCompleted,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    RequestPreempted,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from kvopt.continuum.types import PrefixIdentity, ProgramIdentity, RequestIdentity
from kvopt.profiling.forced_release import ForcedReleaseDecisionSnapshot


def _require_non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _as_timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timestamp must be a real number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError("timestamp must be finite and non-negative")
    return number


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("experiment payload floats must be finite")
        return value
    if isinstance(value, ProgramIdentity):
        return value.value
    if isinstance(value, RequestIdentity):
        return value.value
    if isinstance(value, PrefixIdentity):
        return value.canonical_value
    if isinstance(value, Mapping):
        frozen_items = tuple(
            sorted(
                (
                    _require_non_empty_text(key, "payload key"),
                    _freeze_json(item),
                )
                for key, item in value.items()
            )
        )
        return FrozenExperimentPayload(frozen_items)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError(f"unsupported experiment payload value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class FrozenExperimentPayload(Mapping[str, object]):
    """Deeply immutable JSON-compatible raw event payload."""

    _items: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self._items)
        if len(keys) != len(set(keys)):
            raise ValueError("payload keys must be unique")

    def __iter__(self):
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, key: str) -> object:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def to_dict(self) -> dict[str, object]:
        def thaw(value: object) -> object:
            if isinstance(value, FrozenExperimentPayload):
                return {key: thaw(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [thaw(item) for item in value]
            return value

        return {key: thaw(value) for key, value in self._items}


@dataclass(frozen=True, slots=True)
class ExperimentEvent:
    """One raw observation independent of run/artifact serialization."""

    event_type: str
    timestamp: float
    clock_domain: str
    source: str
    program_id: ProgramIdentity | None = None
    request_id: RequestIdentity | None = None
    prefix_id: PrefixIdentity | None = None
    payload: FrozenExperimentPayload = FrozenExperimentPayload(())

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_type", _require_non_empty_text(self.event_type, "event_type")
        )
        object.__setattr__(self, "timestamp", _as_timestamp(self.timestamp))
        object.__setattr__(
            self, "clock_domain", _require_non_empty_text(self.clock_domain, "clock_domain")
        )
        object.__setattr__(self, "source", _require_non_empty_text(self.source, "source"))
        if self.program_id is not None and not isinstance(
            self.program_id, ProgramIdentity
        ):
            raise TypeError("program_id must be ProgramIdentity or None")
        if self.request_id is not None and not isinstance(
            self.request_id, RequestIdentity
        ):
            raise TypeError("request_id must be RequestIdentity or None")
        if self.prefix_id is not None and not isinstance(
            self.prefix_id, PrefixIdentity
        ):
            raise TypeError("prefix_id must be PrefixIdentity or None")
        if not isinstance(self.payload, FrozenExperimentPayload):
            raise TypeError("payload must be FrozenExperimentPayload")

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        timestamp: float,
        clock_domain: str,
        source: str,
        program_id: ProgramIdentity | None = None,
        request_id: RequestIdentity | None = None,
        prefix_id: PrefixIdentity | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> "ExperimentEvent":
        frozen = _freeze_json({} if payload is None else payload)
        if not isinstance(frozen, FrozenExperimentPayload):
            raise AssertionError("mapping payload must freeze to FrozenExperimentPayload")
        return cls(
            event_type=event_type,
            timestamp=timestamp,
            clock_domain=clock_domain,
            source=source,
            program_id=program_id,
            request_id=request_id,
            prefix_id=prefix_id,
            payload=frozen,
        )


class ExperimentEventSink(Protocol):
    """Destination boundary for raw Phase 2 experiment events."""

    def emit(self, event: ExperimentEvent) -> None:
        """Consume one immutable raw event."""


class NullExperimentEventSink:
    def emit(self, event: ExperimentEvent) -> None:
        if not isinstance(event, ExperimentEvent):
            raise TypeError("event must be ExperimentEvent")


class InMemoryExperimentEventSink:
    def __init__(self) -> None:
        self._events: list[ExperimentEvent] = []

    def emit(self, event: ExperimentEvent) -> None:
        if not isinstance(event, ExperimentEvent):
            raise TypeError("event must be ExperimentEvent")
        self._events.append(event)

    def snapshot(self) -> tuple[ExperimentEvent, ...]:
        return tuple(self._events)


_SUPPORTED_LIFECYCLE = (
    ProgramStarted,
    RequestArrived,
    RequestAdmitted,
    RequestPreempted,
    TurnFinished,
    FollowupWaiting,
    FollowupCancelled,
    ToolGapStarted,
    ToolGapEnded,
    BlocksObserved,
    BlockEvicted,
    ProgramCompleted,
)


def experiment_event_from_lifecycle(event: object) -> ExperimentEvent:
    """Convert one already-supported Continuum lifecycle event into raw evidence."""

    if not isinstance(event, _SUPPORTED_LIFECYCLE):
        raise TypeError("unsupported lifecycle event for experiment observation")

    program_id = getattr(event, "program_id", None)
    request_id = getattr(event, "request_id", None)
    prefix_id = getattr(event, "prefix_id", None)

    if isinstance(event, ProgramStarted):
        timestamp = event.start_timestamp
        payload = {}
    elif isinstance(event, ProgramCompleted):
        timestamp = event.completion_timestamp
        payload = {}
    elif isinstance(event, RequestArrived):
        timestamp = event.arrival_timestamp
        payload = {}
    elif isinstance(event, RequestAdmitted):
        timestamp = event.admission_timestamp
        payload = {}
    elif isinstance(event, RequestPreempted):
        timestamp = event.preemption_timestamp
        payload = {}
    elif isinstance(event, TurnFinished):
        timestamp = event.finish_timestamp
        payload = {
            "is_terminal": event.is_terminal,
            "next_tool_type": event.next_tool_type,
        }
    elif isinstance(event, FollowupWaiting):
        timestamp = event.waiting_timestamp
        payload = {}
    elif isinstance(event, FollowupCancelled):
        timestamp = event.cancellation_timestamp
        payload = {}
    elif isinstance(event, ToolGapStarted):
        timestamp = event.start_timestamp
        payload = {"tool_type": event.tool_type}
    elif isinstance(event, ToolGapEnded):
        timestamp = event.end_timestamp
        payload = {"tool_type": event.tool_type}
    elif isinstance(event, BlocksObserved):
        timestamp = event.observation_timestamp
        payload = {"block_ids": tuple(block.block_id for block in event.block_ids)}
    else:
        assert isinstance(event, BlockEvicted)
        timestamp = event.eviction_timestamp
        payload = {"block_id": event.block_id.block_id}

    return ExperimentEvent.create(
        event_type=event.event_type.value,
        timestamp=timestamp,
        clock_domain="continuum_lifecycle",
        source="continuum.lifecycle",
        program_id=program_id,
        request_id=request_id,
        prefix_id=prefix_id,
        payload=payload,
    )


class ExperimentForcedReleaseObserver:
    """Adapter that mirrors forced-release snapshots into the common event sink."""

    def __init__(self, sink: ExperimentEventSink) -> None:
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")
        self._sink = sink

    def observe(self, snapshot: ForcedReleaseDecisionSnapshot) -> None:
        if not isinstance(snapshot, ForcedReleaseDecisionSnapshot):
            raise TypeError("snapshot must be ForcedReleaseDecisionSnapshot")

        candidates = tuple(
            {
                "program_id": candidate.entry_key.program_id.value,
                "prefix_id": candidate.entry_key.prefix_id.canonical_value,
                "retention_deadline_timestamp": candidate.retention_deadline_timestamp,
                "waiting_followup": candidate.waiting_followup,
                "block_ids": tuple(block.block_id for block in candidate.block_ids),
                "initially_reclaimable_block_ids": tuple(
                    block.block_id
                    for block in candidate.initially_reclaimable_block_ids
                ),
                "next_tool_type": candidate.next_tool_type,
                "elapsed_since_ttl_decision_seconds": (
                    candidate.elapsed_since_ttl_decision_seconds
                ),
                "prefill_reload_seconds": candidate.prefill_reload_seconds,
                "eta": candidate.eta,
                "queue_delay_t_seconds": candidate.queue_delay_t_seconds,
            }
            for candidate in snapshot.candidates
        )
        selected = tuple(
            {
                "program_id": release.entry_key.program_id.value,
                "prefix_id": release.entry_key.prefix_id.canonical_value,
                "newly_eligible_block_ids": tuple(
                    block.block_id for block in release.newly_eligible_block_ids
                ),
            }
            for release in snapshot.selected_releases
        )
        self._sink.emit(
            ExperimentEvent.create(
                event_type="FORCED_RELEASE_DECISION",
                timestamp=snapshot.timestamp,
                clock_domain="continuum_pressure",
                source="continuum.forced_release",
                payload={
                    "required_blocks": snapshot.required_blocks,
                    "original_free_queue": tuple(
                        {
                            "block_id": block.block_id.block_id,
                            "native_lru_rank": block.native_lru_rank,
                            "has_block_hash": block.has_block_hash,
                            "eligibility_tier": (
                                block.eligibility_tier.value
                                if block.eligibility_tier is not None else None
                            ),
                        }
                        for block in snapshot.preparation.original_free_queue
                    ),
                    "ordinary_expired_entries": tuple(
                        {
                            "program_id": key.program_id.value,
                            "prefix_id": key.prefix_id.canonical_value,
                        }
                        for key in snapshot.preparation.ordinary_expired_entries
                    ),
                    "candidates": candidates,
                    "selected_releases": selected,
                },
            )
        )
