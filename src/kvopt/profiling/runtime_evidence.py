"""Collect request-scoped Level-B evidence from direct runtime observations."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .ingestion import ArtifactValidationError, RawRunArtifacts

NATIVE_REQUEST_OBSERVATION = "VLLM_NATIVE_REQUEST_OBSERVATION"
_REQUIRED_NATIVE_FIELDS = {
    "eligible_prefix_tokens",
    "native_cached_prefix_tokens",
    "actual_prefill_tokens",
    "native_scheduler_admission_timestamp",
    "native_first_token_timestamp",
}


@dataclass(frozen=True, slots=True)
class RequestRuntimeEvidenceRow:
    """One request joined to direct native cache, work, and timing facts."""

    run_id: str
    request_id: str
    program_id: str
    kind: str
    observation_event_index: int | None
    native_clock_domain: str | None
    eligible_prefix_tokens: int | None
    native_cached_prefix_tokens: int | None
    actual_prefill_tokens: int | None
    recomputed_prefill_tokens: int | None
    recomputed_prefill_status: str
    derived_apc_result: str | None
    derived_apc_status: str
    backend_submission_timestamp: float | None
    native_scheduler_admission_timestamp: float | None
    native_first_token_timestamp: float | None
    backend_completion_timestamp: float | None
    native_queue_delay_seconds: float | None
    native_queue_delay_status: str
    native_ttft_seconds: float | None
    native_ttft_status: str
    native_e2e_seconds: float | None
    native_e2e_status: str


@dataclass(frozen=True, slots=True)
class _Landmark:
    timestamp: float
    clock_domain: str


def load_level_b_collection_design(path: str | Path) -> dict[str, object]:
    """Load the review-stage Level-B collection and calibration design."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ArtifactValidationError("Level-B collection design must be an object")
    if payload.get("schema_version") != "phase2a.level_b_collection_design.v1":
        raise ArtifactValidationError("unsupported Level-B collection design schema")
    if payload.get("status") != "AWAITING_M1_M5_SEAM_REVIEW":
        raise ArtifactValidationError("Level-B design must await seam review")
    event = _mapping(payload.get("raw_event"), "raw_event")
    if event.get("event_type") != NATIVE_REQUEST_OBSERVATION:
        raise ArtifactValidationError("Level-B design has the wrong event type")
    raw_fields = event.get("direct_payload_fields")
    if not isinstance(raw_fields, list) or not _REQUIRED_NATIVE_FIELDS.issubset(
        set(raw_fields)
    ):
        raise ArtifactValidationError("Level-B design is missing native fields")
    calibration = _mapping(payload.get("latency_calibration"), "latency_calibration")
    repeats = calibration.get("identical_baseline_repeats")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 3:
        raise ArtifactValidationError(
            "latency calibration requires at least three baseline repeats"
        )
    if calibration.get("epsilon_rule") != (
        "max_absolute_deviation_from_baseline_mean"
    ):
        raise ArtifactValidationError("unsupported epsilon_latency rule")
    if payload.get("formal_collection_authorized") is not False:
        raise ArtifactValidationError(
            "review-stage Level-B design must not authorize formal collection"
        )
    return payload


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


def _optional_non_negative_int(
    payload: dict[str, object],
    key: str,
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    return _non_negative_int(value, key)


def _timestamp(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ArtifactValidationError(
            f"{field_name} must be finite and non-negative"
        )
    return result


def _optional_timestamp(
    payload: dict[str, object],
    key: str,
) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    return _timestamp(value, key)


def _event_landmark(
    event: dict[str, object] | None,
    field_name: str,
) -> _Landmark | None:
    if event is None:
        return None
    return _Landmark(
        timestamp=_timestamp(event.get("timestamp"), f"{field_name} timestamp"),
        clock_domain=_text(
            event.get("clock_domain"),
            f"{field_name} clock_domain",
        ),
    )


def _native_landmark(
    timestamp: float | None,
    clock_domain: str | None,
) -> _Landmark | None:
    if timestamp is None:
        return None
    if clock_domain is None:
        raise AssertionError("native timestamp requires a clock domain")
    return _Landmark(timestamp=timestamp, clock_domain=clock_domain)


def _duration(
    start: _Landmark | None,
    end: _Landmark | None,
) -> tuple[float | None, str]:
    if start is None or end is None:
        return None, "missing_landmark"
    if start.clock_domain != end.clock_domain:
        return None, "incompatible_clock_domain"
    if end.timestamp < start.timestamp:
        raise ArtifactValidationError("native runtime landmarks are reversed")
    return end.timestamp - start.timestamp, "available"


def _derive_apc_result(
    eligible: int | None,
    cached: int | None,
) -> tuple[str | None, str]:
    if eligible is None or cached is None:
        return None, "missing_native_token_count"
    if cached > eligible:
        raise ArtifactValidationError(
            "native_cached_prefix_tokens exceeds eligible_prefix_tokens"
        )
    if eligible == 0:
        return "NOT_APPLICABLE", "available"
    if cached == 0:
        return "MISS", "available"
    if cached == eligible:
        return "FULL_HIT", "available"
    return "PARTIAL_HIT", "available"


def _derive_recomputed_prefill_tokens(
    eligible: int | None,
    cached: int | None,
    actual_prefill: int | None,
) -> tuple[int | None, str]:
    if eligible is None or cached is None:
        return None, "missing_native_token_count"
    if cached > eligible:
        raise ArtifactValidationError(
            "native_cached_prefix_tokens exceeds eligible_prefix_tokens"
        )
    recomputed = eligible - cached
    if actual_prefill is not None and actual_prefill < recomputed:
        raise ArtifactValidationError(
            "actual_prefill_tokens is below derived recomputed prefix work"
        )
    return recomputed, "available"


def _events_by_request(
    events: tuple[dict[str, object], ...],
) -> dict[tuple[str, str], dict[str, object]]:
    supported = {
        NATIVE_REQUEST_OBSERVATION,
        "VLLM_REQUEST_SUBMITTED",
        "VLLM_REQUEST_COMPLETED",
    }
    result: dict[tuple[str, str], dict[str, object]] = {}
    for event in events:
        event_type = event.get("event_type")
        if event_type not in supported:
            continue
        assert isinstance(event_type, str)
        request_id = _text(event.get("request_id"), f"{event_type} request_id")
        key = (request_id, event_type)
        if key in result:
            raise ArtifactValidationError(
                f"request {request_id} has duplicate {event_type} event"
            )
        result[key] = event
    return result


def build_request_runtime_evidence_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[RequestRuntimeEvidenceRow, ...]:
    """Join replay requests to direct native facts without proxy inference."""

    rows: list[RequestRuntimeEvidenceRow] = []
    seen_keys: set[tuple[str, str]] = set()
    for artifacts in runs:
        events = _events_by_request(artifacts.events)
        for position, replay_value in enumerate(artifacts.replay, start=1):
            replay = _mapping(replay_value, f"replay row {position}")
            request_id = _text(
                replay.get("request_id"), f"replay row {position} request_id"
            )
            program_id = _text(
                replay.get("program_id"), f"replay row {position} program_id"
            )
            row_key = (artifacts.run_id, request_id)
            if row_key in seen_keys:
                raise ArtifactValidationError(
                    f"duplicate request runtime evidence key: {row_key}"
                )
            seen_keys.add(row_key)

            native_event = events.get((request_id, NATIVE_REQUEST_OBSERVATION))
            submission_event = events.get((request_id, "VLLM_REQUEST_SUBMITTED"))
            completion_event = events.get((request_id, "VLLM_REQUEST_COMPLETED"))
            for event in (native_event, submission_event, completion_event):
                if event is not None and event.get("program_id") != program_id:
                    raise ArtifactValidationError(
                        f"request {request_id} has mismatched program_id"
                    )

            event_index: int | None = None
            native_domain: str | None = None
            eligible: int | None = None
            cached: int | None = None
            actual_prefill: int | None = None
            admission_timestamp: float | None = None
            first_token_timestamp: float | None = None
            if native_event is not None:
                event_index = _non_negative_int(
                    native_event.get("event_index"),
                    "native observation event_index",
                )
                native_domain = _text(
                    native_event.get("clock_domain"),
                    "native observation clock_domain",
                )
                payload = _mapping(
                    native_event.get("payload"),
                    "native observation payload",
                )
                eligible = _optional_non_negative_int(
                    payload, "eligible_prefix_tokens"
                )
                cached = _optional_non_negative_int(
                    payload, "native_cached_prefix_tokens"
                )
                actual_prefill = _optional_non_negative_int(
                    payload, "actual_prefill_tokens"
                )
                admission_timestamp = _optional_timestamp(
                    payload, "native_scheduler_admission_timestamp"
                )
                first_token_timestamp = _optional_timestamp(
                    payload, "native_first_token_timestamp"
                )

            derived_apc, apc_status = _derive_apc_result(eligible, cached)
            recomputed_prefill, recomputed_status = (
                _derive_recomputed_prefill_tokens(
                    eligible,
                    cached,
                    actual_prefill,
                )
            )

            submission = _event_landmark(submission_event, "submission")
            completion = _event_landmark(completion_event, "completion")
            admission = _native_landmark(admission_timestamp, native_domain)
            first_token = _native_landmark(first_token_timestamp, native_domain)
            queue_delay, queue_status = _duration(submission, admission)
            ttft, ttft_status = _duration(submission, first_token)
            e2e, e2e_status = _duration(submission, completion)

            rows.append(
                RequestRuntimeEvidenceRow(
                    run_id=artifacts.run_id,
                    request_id=request_id,
                    program_id=program_id,
                    kind=_text(replay.get("kind"), f"request {request_id} kind"),
                    observation_event_index=event_index,
                    native_clock_domain=native_domain,
                    eligible_prefix_tokens=eligible,
                    native_cached_prefix_tokens=cached,
                    actual_prefill_tokens=actual_prefill,
                    recomputed_prefill_tokens=recomputed_prefill,
                    recomputed_prefill_status=recomputed_status,
                    derived_apc_result=derived_apc,
                    derived_apc_status=apc_status,
                    backend_submission_timestamp=(
                        None if submission is None else submission.timestamp
                    ),
                    native_scheduler_admission_timestamp=admission_timestamp,
                    native_first_token_timestamp=first_token_timestamp,
                    backend_completion_timestamp=(
                        None if completion is None else completion.timestamp
                    ),
                    native_queue_delay_seconds=queue_delay,
                    native_queue_delay_status=queue_status,
                    native_ttft_seconds=ttft,
                    native_ttft_status=ttft_status,
                    native_e2e_seconds=e2e,
                    native_e2e_status=e2e_status,
                )
            )
    return tuple(rows)
