"""Construct request-level outcomes without crossing incompatible clocks."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .ingestion import ArtifactValidationError, RawRunArtifacts


@dataclass(frozen=True, slots=True)
class RequestOutcomeRow:
    """One planned request joined to its observed runtime landmarks."""

    run_id: str
    request_id: str
    program_id: str
    turn_index: int
    kind: str
    planned_arrival_offset_seconds: float
    tool_gap_seconds: float | None
    arrival_event_index: int | None
    arrival_timestamp: float | None
    arrival_clock_domain: str | None
    logical_admission_event_index: int | None
    logical_admission_timestamp: float | None
    logical_admission_clock_domain: str | None
    logical_admission_delay_seconds: float | None
    logical_admission_delay_status: str
    submission_event_index: int | None
    submission_timestamp: float | None
    submission_clock_domain: str | None
    completion_event_index: int | None
    completion_timestamp: float | None
    completion_clock_domain: str | None
    backend_service_seconds: float | None
    backend_service_status: str
    prefix_snapshot_event_index: int | None
    prefix_id: str | None
    reusable_token_count: int | None
    block_ids: tuple[int, ...] | None
    output_token_count: int | None


@dataclass(frozen=True, slots=True)
class _Landmark:
    event_index: int
    timestamp: float
    clock_domain: str


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{field_name} must be an object")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{field_name} must be non-empty text")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactValidationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    result = _non_negative_int(value, field_name)
    if result == 0:
        raise ArtifactValidationError(f"{field_name} must be positive")
    return result


def _non_negative_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ArtifactValidationError(
            f"{field_name} must be finite and non-negative"
        )
    return result


def _optional_non_negative_float(
    value: object,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    return _non_negative_float(value, field_name)


def _landmark(event: dict[str, object], field_name: str) -> _Landmark:
    return _Landmark(
        event_index=_non_negative_int(
            event.get("event_index"),
            f"{field_name} event_index",
        ),
        timestamp=_non_negative_float(
            event.get("timestamp"),
            f"{field_name} timestamp",
        ),
        clock_domain=_text(
            event.get("clock_domain"),
            f"{field_name} clock_domain",
        ),
    )


def _duration(
    start: _Landmark | None,
    end: _Landmark | None,
) -> tuple[float | None, str]:
    if start is None or end is None:
        return None, "missing_landmark"
    if start.clock_domain != end.clock_domain:
        return None, "incompatible_clock_domain"
    if end.event_index < start.event_index or end.timestamp < start.timestamp:
        raise ArtifactValidationError("runtime landmarks are causally reversed")
    return end.timestamp - start.timestamp, "available"


def _optional_landmark(
    event: dict[str, object] | None,
    field_name: str,
) -> _Landmark | None:
    return None if event is None else _landmark(event, field_name)


def _event_by_type(
    events: tuple[dict[str, object], ...],
) -> dict[tuple[str, str], dict[str, object]]:
    supported = {
        "REQUEST_ARRIVED",
        "REQUEST_ADMITTED",
        "VLLM_REQUEST_SUBMITTED",
        "VLLM_REQUEST_COMPLETED",
        "VLLM_PREFIX_SNAPSHOT",
    }
    result: dict[tuple[str, str], dict[str, object]] = {}
    for event in events:
        event_type = event.get("event_type")
        if event_type not in supported:
            continue
        assert isinstance(event_type, str)
        request_id = _text(
            event.get("request_id"),
            f"{event_type} request_id",
        )
        key = (request_id, event_type)
        if key in result:
            raise ArtifactValidationError(
                f"request {request_id} has duplicate {event_type} event"
            )
        result[key] = event
    return result


def _request_event(
    events: dict[tuple[str, str], dict[str, object]],
    request_id: str,
    program_id: str,
    event_type: str,
) -> dict[str, object] | None:
    value = events.get((request_id, event_type))
    if value is not None and value.get("program_id") != program_id:
        raise ArtifactValidationError(
            f"request {request_id} has mismatched program_id"
        )
    return value


def _block_ids(value: object, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{field_name} must be a list")
    result = tuple(
        _non_negative_int(block_id, f"{field_name} item")
        for block_id in value
    )
    if len(result) != len(set(result)):
        raise ArtifactValidationError(f"{field_name} must not contain duplicates")
    return result


def build_request_outcomes_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[RequestOutcomeRow, ...]:
    """Join replay intent to request-scoped raw observations."""

    rows: list[RequestOutcomeRow] = []
    seen_keys: set[tuple[str, str]] = set()

    for artifacts in runs:
        events = _event_by_type(artifacts.events)
        replay_ids: set[str] = set()

        for position, replay_value in enumerate(artifacts.replay, start=1):
            replay = _mapping(replay_value, f"replay row {position}")
            request_id = _text(
                replay.get("request_id"),
                f"replay row {position} request_id",
            )
            program_id = _text(
                replay.get("program_id"),
                f"replay row {position} program_id",
            )
            if request_id in replay_ids:
                raise ArtifactValidationError(
                    f"duplicate replay request_id: {request_id}"
                )
            replay_ids.add(request_id)

            row_key = (artifacts.run_id, request_id)
            if row_key in seen_keys:
                raise ArtifactValidationError(
                    f"duplicate request outcome key: {row_key}"
                )
            seen_keys.add(row_key)

            arrival = _optional_landmark(
                _request_event(
                    events,
                    request_id,
                    program_id,
                    "REQUEST_ARRIVED",
                ),
                f"request {request_id} arrival",
            )
            admission = _optional_landmark(
                _request_event(
                    events,
                    request_id,
                    program_id,
                    "REQUEST_ADMITTED",
                ),
                f"request {request_id} logical admission",
            )
            submission = _optional_landmark(
                _request_event(
                    events,
                    request_id,
                    program_id,
                    "VLLM_REQUEST_SUBMITTED",
                ),
                f"request {request_id} submission",
            )
            completion_event = _request_event(
                events,
                request_id,
                program_id,
                "VLLM_REQUEST_COMPLETED",
            )
            completion = _optional_landmark(
                completion_event,
                f"request {request_id} completion",
            )
            prefix_event = _request_event(
                events,
                request_id,
                program_id,
                "VLLM_PREFIX_SNAPSHOT",
            )

            admission_delay, admission_status = _duration(arrival, admission)
            service_time, service_status = _duration(submission, completion)

            prefix_landmark: _Landmark | None = None
            prefix_id: str | None = None
            reusable_token_count: int | None = None
            observed_block_ids: tuple[int, ...] | None = None
            if prefix_event is not None:
                prefix_landmark = _landmark(
                    prefix_event,
                    f"request {request_id} prefix snapshot",
                )
                prefix_id = _text(
                    prefix_event.get("prefix_id"),
                    f"request {request_id} prefix_id",
                )
                prefix_payload = _mapping(
                    prefix_event.get("payload"),
                    f"request {request_id} prefix payload",
                )
                reusable_token_count = _non_negative_int(
                    prefix_payload.get("reusable_token_count"),
                    f"request {request_id} reusable_token_count",
                )
                observed_block_ids = _block_ids(
                    prefix_payload.get("block_ids"),
                    f"request {request_id} block_ids",
                )

            output_token_count: int | None = None
            if completion_event is not None:
                completion_payload = _mapping(
                    completion_event.get("payload"),
                    f"request {request_id} completion payload",
                )
                output_token_count = _non_negative_int(
                    completion_payload.get("output_token_count"),
                    f"request {request_id} output_token_count",
                )

            rows.append(
                RequestOutcomeRow(
                    run_id=artifacts.run_id,
                    request_id=request_id,
                    program_id=program_id,
                    turn_index=_positive_int(
                        replay.get("turn_index"),
                        f"request {request_id} turn_index",
                    ),
                    kind=_text(
                        replay.get("kind"),
                        f"request {request_id} kind",
                    ),
                    planned_arrival_offset_seconds=_non_negative_float(
                        replay.get("planned_arrival_offset_seconds"),
                        f"request {request_id} planned arrival",
                    ),
                    tool_gap_seconds=_optional_non_negative_float(
                        replay.get("tool_gap_seconds"),
                        f"request {request_id} tool gap",
                    ),
                    arrival_event_index=(
                        None if arrival is None else arrival.event_index
                    ),
                    arrival_timestamp=(
                        None if arrival is None else arrival.timestamp
                    ),
                    arrival_clock_domain=(
                        None if arrival is None else arrival.clock_domain
                    ),
                    logical_admission_event_index=(
                        None if admission is None else admission.event_index
                    ),
                    logical_admission_timestamp=(
                        None if admission is None else admission.timestamp
                    ),
                    logical_admission_clock_domain=(
                        None if admission is None else admission.clock_domain
                    ),
                    logical_admission_delay_seconds=admission_delay,
                    logical_admission_delay_status=admission_status,
                    submission_event_index=(
                        None if submission is None else submission.event_index
                    ),
                    submission_timestamp=(
                        None if submission is None else submission.timestamp
                    ),
                    submission_clock_domain=(
                        None if submission is None else submission.clock_domain
                    ),
                    completion_event_index=(
                        None if completion is None else completion.event_index
                    ),
                    completion_timestamp=(
                        None if completion is None else completion.timestamp
                    ),
                    completion_clock_domain=(
                        None if completion is None else completion.clock_domain
                    ),
                    backend_service_seconds=service_time,
                    backend_service_status=service_status,
                    prefix_snapshot_event_index=(
                        None
                        if prefix_landmark is None
                        else prefix_landmark.event_index
                    ),
                    prefix_id=prefix_id,
                    reusable_token_count=reusable_token_count,
                    block_ids=observed_block_ids,
                    output_token_count=output_token_count,
                )
            )

        event_request_ids = {request_id for request_id, _ in events}
        unknown_request_ids = event_request_ids.difference(replay_ids)
        if unknown_request_ids:
            raise ArtifactValidationError(
                "request events are missing from replay: "
                f"{sorted(unknown_request_ids)}"
            )

    return tuple(rows)
