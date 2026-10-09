"""Derive Level-B evidence strictly from request-scoped native observations."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingestion import ArtifactValidationError, RawRunArtifacts

NATIVE_REQUEST_OBSERVATION = "VLLM_NATIVE_REQUEST_OBSERVATION"
ENGINE_CORE_CLOCK_DOMAIN = "engine_core_monotonic"
_REQUIRED_TOKEN_FIELDS = {
    "native_prompt_tokens",
    "native_cached_prefix_tokens",
    "native_apc_block_hashes",
    "native_hash_block_size",
    "native_hash_process_id",
    "native_hash_function",
}
_REQUIRED_RAW_FIELDS = {
    *_REQUIRED_TOKEN_FIELDS,
    "native_queued_timestamp",
    "native_scheduler_admission_timestamp",
    "native_first_token_timestamp",
}


@dataclass(frozen=True, slots=True)
class RequestRuntimeEvidenceRow:
    """One request's raw native facts and validated M6-side derivations."""

    run_id: str
    request_id: str
    program_id: str
    kind: str
    observation_event_index: int | None
    native_request_id: str | None
    availability: str
    unavailable_reason: str | None
    native_prompt_tokens: int | None
    native_cached_prefix_tokens: int | None
    native_apc_block_hashes: tuple[str, ...] | None
    native_hash_block_size: int | None
    native_hash_process_id: str | None
    native_hash_function: str | None
    eligible_prefix_tokens: int | None
    actual_prefill_tokens: int | None
    observed_recomputed_tokens: int | None
    apc_outcome: str | None
    invariant_status: str
    native_clock_domain: str | None
    native_queued_timestamp: float | None
    native_scheduler_admission_timestamp: float | None
    native_first_token_timestamp: float | None
    native_queue_delay_seconds: float | None
    native_queue_delay_status: str
    native_prefill_to_first_token_seconds: float | None
    native_prefill_to_first_token_status: str
    isolated_native_prefill_elapsed_seconds: float | None
    isolated_native_prefill_elapsed_status: str
    backend_submission_timestamp: float | None
    backend_completion_timestamp: float | None
    backend_service_e2e_seconds: float | None
    backend_service_e2e_status: str


@dataclass(frozen=True, slots=True)
class _Landmark:
    timestamp: float
    clock_domain: str


@dataclass(frozen=True, slots=True)
class _NativeHashEvidence:
    hashes: tuple[str, ...]
    block_size: int
    process_id: str
    hash_function: str


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
    payload: Mapping[str, object],
    key: str,
) -> float | None:
    value = payload.get(key)
    return None if value is None else _timestamp(value, key)


def _optional_positive_duration(
    payload: Mapping[str, object],
    key: str,
) -> tuple[float | None, str]:
    value = payload.get(key)
    if value is None:
        return None, "missing_observation"
    result = _timestamp(value, key)
    if result <= 0:
        raise ArtifactValidationError(f"{key} must be positive")
    return result, "available"


def _native_hash(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if (
        len(result) % 2 != 0
        or result.lower() != result
        or any(character not in "0123456789abcdef" for character in result)
    ):
        raise ArtifactValidationError(
            f"{field_name} must be lowercase hexadecimal bytes"
        )
    return result


def _native_hashes(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{field_name} must be an array")
    result = tuple(
        _native_hash(item, f"{field_name} item") for item in value
    )
    if len(result) != len(set(result)):
        raise ArtifactValidationError(f"{field_name} must not contain duplicates")
    return result


def _event_index(event: Mapping[str, object], field_name: str) -> int:
    return _non_negative_int(event.get("event_index"), f"{field_name} event_index")


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


def _duration(
    start: _Landmark | None,
    end: _Landmark | None,
    *,
    required_clock_domain: str | None = None,
) -> tuple[float | None, str]:
    if start is None or end is None:
        return None, "missing_landmark"
    if start.clock_domain != end.clock_domain:
        return None, "incompatible_clock_domain"
    if (
        required_clock_domain is not None
        and start.clock_domain != required_clock_domain
    ):
        return None, "incompatible_clock_domain"
    if end.timestamp < start.timestamp:
        raise ArtifactValidationError("runtime landmarks are causally reversed")
    return end.timestamp - start.timestamp, "available"


def _hash_evidence(
    payload: Mapping[str, object],
    *,
    hashes_field: str,
    field_prefix: str,
) -> _NativeHashEvidence:
    return _NativeHashEvidence(
        hashes=_native_hashes(
            payload.get(hashes_field),
            f"{field_prefix} {hashes_field}",
        ),
        block_size=_positive_int(
            payload.get("native_hash_block_size"),
            f"{field_prefix} native_hash_block_size",
        ),
        process_id=_text(
            payload.get("native_hash_process_id"),
            f"{field_prefix} native_hash_process_id",
        ),
        hash_function=_text(
            payload.get("native_hash_function"),
            f"{field_prefix} native_hash_function",
        ),
    )


def _longest_common_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_hash, right_hash in zip(left, right):
        if left_hash != right_hash:
            break
        count += 1
    return count


def _eligible_prefix_tokens(
    *,
    current: _NativeHashEvidence,
    native_prompt_tokens: int,
    prior_events: Sequence[dict[str, object]],
) -> tuple[int | None, str | None]:
    if not prior_events:
        return 0, None

    compatible: list[_NativeHashEvidence] = []
    invalid_prior_evidence = False
    for event in prior_events:
        try:
            payload = _mapping(
                event.get("payload"),
                "prior VLLM_PREFIX_SNAPSHOT payload",
            )
            evidence = _hash_evidence(
                payload,
                hashes_field="ordered_native_hashes",
                field_prefix="prior prefix snapshot",
            )
            hash_num_tokens = _non_negative_int(
                payload.get("hash_num_tokens"),
                "prior prefix snapshot hash_num_tokens",
            )
            if hash_num_tokens != len(evidence.hashes) * evidence.block_size:
                raise ArtifactValidationError(
                    "prior prefix snapshot hash_num_tokens disagrees with hash chain"
                )
        except ArtifactValidationError:
            invalid_prior_evidence = True
            continue
        if (
            evidence.process_id == current.process_id
            and evidence.hash_function == current.hash_function
            and evidence.block_size == current.block_size
        ):
            compatible.append(evidence)

    if not compatible:
        reason = (
            "prior_native_hash_provenance_unavailable"
            if invalid_prior_evidence
            else "no_compatible_prior_native_hash_provenance"
        )
        return None, reason

    longest_blocks = max(
        _longest_common_prefix(current.hashes, prior.hashes)
        for prior in compatible
    )
    maximum_reusable_blocks = (native_prompt_tokens - 1) // current.block_size
    eligible_blocks = min(longest_blocks, maximum_reusable_blocks)
    return eligible_blocks * current.block_size, None


def derive_level_b_token_semantics(
    *,
    native_prompt_tokens: int,
    eligible_prefix_tokens: int,
    native_cached_prefix_tokens: int,
) -> tuple[int, int, str]:
    prompt = native_prompt_tokens
    eligible = eligible_prefix_tokens
    cached = native_cached_prefix_tokens
    if not 0 <= cached <= eligible <= prompt:
        raise ArtifactValidationError(
            "Level-B invariant failed: expected 0 <= C <= E <= N"
        )
    actual_prefill = prompt - cached
    recomputed = eligible - cached
    if actual_prefill != recomputed + (prompt - eligible):
        raise ArtifactValidationError(
            "Level-B invariant failed: W != R + (N - E)"
        )
    if eligible == 0:
        outcome = "NO_REUSE_ELIGIBLE_PREFIX"
    elif cached == eligible:
        outcome = "FULL_HIT"
    elif cached == 0:
        outcome = "MISS"
    else:
        outcome = "PARTIAL_HIT"
    return actual_prefill, recomputed, outcome


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


def _prior_prefix_snapshots(
    events: tuple[dict[str, object], ...],
    before_event_index: int,
) -> tuple[dict[str, object], ...]:
    return tuple(
        event
        for event in events
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
        and _event_index(event, "prefix snapshot") < before_event_index
    )


def _native_timing(
    payload: Mapping[str, object],
    clock_domain: str,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    str,
    float | None,
    str,
]:
    queued_value = _optional_timestamp(payload, "native_queued_timestamp")
    admitted_value = _optional_timestamp(
        payload, "native_scheduler_admission_timestamp"
    )
    first_value = _optional_timestamp(payload, "native_first_token_timestamp")
    queued = (
        None
        if queued_value is None
        else _Landmark(queued_value, clock_domain)
    )
    admitted = (
        None
        if admitted_value is None
        else _Landmark(admitted_value, clock_domain)
    )
    first = (
        None
        if first_value is None
        else _Landmark(first_value, clock_domain)
    )
    queue_delay, queue_status = _duration(
        queued,
        admitted,
        required_clock_domain=ENGINE_CORE_CLOCK_DOMAIN,
    )
    prefill, prefill_status = _duration(
        admitted,
        first,
        required_clock_domain=ENGINE_CORE_CLOCK_DOMAIN,
    )
    return (
        queued_value,
        admitted_value,
        first_value,
        queue_delay,
        queue_status,
        prefill,
        prefill_status,
    )


def _missing_row(
    *,
    run_id: str,
    request_id: str,
    program_id: str,
    kind: str,
    submission: _Landmark | None,
    completion: _Landmark | None,
) -> RequestRuntimeEvidenceRow:
    e2e, e2e_status = _duration(submission, completion)
    return RequestRuntimeEvidenceRow(
        run_id=run_id,
        request_id=request_id,
        program_id=program_id,
        kind=kind,
        observation_event_index=None,
        native_request_id=None,
        availability="UNAVAILABLE",
        unavailable_reason="native_request_observation_missing",
        native_prompt_tokens=None,
        native_cached_prefix_tokens=None,
        native_apc_block_hashes=None,
        native_hash_block_size=None,
        native_hash_process_id=None,
        native_hash_function=None,
        eligible_prefix_tokens=None,
        actual_prefill_tokens=None,
        observed_recomputed_tokens=None,
        apc_outcome=None,
        invariant_status="unavailable",
        native_clock_domain=None,
        native_queued_timestamp=None,
        native_scheduler_admission_timestamp=None,
        native_first_token_timestamp=None,
        native_queue_delay_seconds=None,
        native_queue_delay_status="missing_landmark",
        native_prefill_to_first_token_seconds=None,
        native_prefill_to_first_token_status="missing_landmark",
        isolated_native_prefill_elapsed_seconds=None,
        isolated_native_prefill_elapsed_status="missing_observation",
        backend_submission_timestamp=(
            None if submission is None else submission.timestamp
        ),
        backend_completion_timestamp=(
            None if completion is None else completion.timestamp
        ),
        backend_service_e2e_seconds=e2e,
        backend_service_e2e_status=e2e_status,
    )


def build_request_runtime_evidence_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[RequestRuntimeEvidenceRow, ...]:
    """Join replay requests to native evidence without logical/proxy fallback."""

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
            kind = _text(replay.get("kind"), f"request {request_id} kind")
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
            submission = _event_landmark(submission_event, "submission")
            completion = _event_landmark(completion_event, "completion")
            if native_event is None:
                rows.append(
                    _missing_row(
                        run_id=artifacts.run_id,
                        request_id=request_id,
                        program_id=program_id,
                        kind=kind,
                        submission=submission,
                        completion=completion,
                    )
                )
                continue

            event_index = _event_index(native_event, "native observation")
            native_request_id = _text(
                native_event.get("native_request_id"),
                "native observation native_request_id",
            )
            clock_domain = _text(
                native_event.get("clock_domain"),
                "native observation clock_domain",
            )
            payload = _mapping(
                native_event.get("payload"), "native observation payload"
            )
            prompt = payload.get("native_prompt_tokens")
            cached = payload.get("native_cached_prefix_tokens")
            missing_fields = sorted(
                field
                for field in _REQUIRED_TOKEN_FIELDS
                if payload.get(field) is None
            )

            current: _NativeHashEvidence | None = None
            eligible: int | None = None
            unavailable_reason: str | None = None
            if missing_fields:
                unavailable_reason = "missing_native_fields:" + ",".join(
                    missing_fields
                )
            else:
                native_prompt_tokens = _positive_int(
                    prompt, "native_prompt_tokens"
                )
                _non_negative_int(cached, "native_cached_prefix_tokens")
                current = _hash_evidence(
                    payload,
                    hashes_field="native_apc_block_hashes",
                    field_prefix="native observation",
                )
                eligible, unavailable_reason = _eligible_prefix_tokens(
                    current=current,
                    native_prompt_tokens=native_prompt_tokens,
                    prior_events=_prior_prefix_snapshots(
                        artifacts.events, event_index
                    ),
                )

            actual_prefill: int | None = None
            recomputed: int | None = None
            apc_outcome: str | None = None
            invariant_status = "unavailable"
            if unavailable_reason is None:
                assert current is not None
                assert eligible is not None
                native_prompt_tokens = _positive_int(
                    prompt, "native_prompt_tokens"
                )
                native_cached_prefix_tokens = _non_negative_int(
                    cached, "native_cached_prefix_tokens"
                )
                actual_prefill, recomputed, apc_outcome = (
                    derive_level_b_token_semantics(
                        native_prompt_tokens=native_prompt_tokens,
                        eligible_prefix_tokens=eligible,
                        native_cached_prefix_tokens=(
                            native_cached_prefix_tokens
                        ),
                    )
                )
                invariant_status = "valid"

            (
                queued_timestamp,
                admitted_timestamp,
                first_timestamp,
                queue_delay,
                queue_status,
                prefill_to_first,
                prefill_status,
            ) = _native_timing(payload, clock_domain)
            e2e, e2e_status = _duration(submission, completion)
            isolated_prefill, isolated_prefill_status = _optional_positive_duration(
                payload,
                "isolated_native_prefill_elapsed_seconds",
            )

            rows.append(
                RequestRuntimeEvidenceRow(
                    run_id=artifacts.run_id,
                    request_id=request_id,
                    program_id=program_id,
                    kind=kind,
                    observation_event_index=event_index,
                    native_request_id=native_request_id,
                    availability=(
                        "AVAILABLE"
                        if unavailable_reason is None
                        else "UNAVAILABLE"
                    ),
                    unavailable_reason=unavailable_reason,
                    native_prompt_tokens=(
                        None
                        if prompt is None
                        else _positive_int(prompt, "native_prompt_tokens")
                    ),
                    native_cached_prefix_tokens=(
                        None
                        if cached is None
                        else _non_negative_int(
                            cached, "native_cached_prefix_tokens"
                        )
                    ),
                    native_apc_block_hashes=(
                        None if current is None else current.hashes
                    ),
                    native_hash_block_size=(
                        None if current is None else current.block_size
                    ),
                    native_hash_process_id=(
                        None if current is None else current.process_id
                    ),
                    native_hash_function=(
                        None if current is None else current.hash_function
                    ),
                    eligible_prefix_tokens=eligible,
                    actual_prefill_tokens=actual_prefill,
                    observed_recomputed_tokens=recomputed,
                    apc_outcome=apc_outcome,
                    invariant_status=invariant_status,
                    native_clock_domain=clock_domain,
                    native_queued_timestamp=queued_timestamp,
                    native_scheduler_admission_timestamp=admitted_timestamp,
                    native_first_token_timestamp=first_timestamp,
                    native_queue_delay_seconds=queue_delay,
                    native_queue_delay_status=queue_status,
                    native_prefill_to_first_token_seconds=prefill_to_first,
                    native_prefill_to_first_token_status=prefill_status,
                    isolated_native_prefill_elapsed_seconds=isolated_prefill,
                    isolated_native_prefill_elapsed_status=isolated_prefill_status,
                    backend_submission_timestamp=(
                        None if submission is None else submission.timestamp
                    ),
                    backend_completion_timestamp=(
                        None if completion is None else completion.timestamp
                    ),
                    backend_service_e2e_seconds=e2e,
                    backend_service_e2e_status=e2e_status,
                )
            )
    return tuple(rows)


def load_level_b_collection_design(path: str | Path) -> dict[str, Any]:
    """Load the authorized design and enforce its observation-only boundary."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ArtifactValidationError("Level-B collection design must be an object")
    if payload.get("schema_version") != "phase2a.level_b_collection_design.v2":
        raise ArtifactValidationError("unsupported Level-B collection design schema")
    if payload.get("status") != "AUTHORIZED_FOR_SEAM_VALIDATION":
        raise ArtifactValidationError("Level-B design must authorize seam validation")
    event = _mapping(payload.get("raw_event"), "raw_event")
    if event.get("event_type") != NATIVE_REQUEST_OBSERVATION:
        raise ArtifactValidationError("Level-B design has the wrong event type")
    raw_fields = event.get("direct_payload_fields")
    if not isinstance(raw_fields, list) or not _REQUIRED_RAW_FIELDS.issubset(
        set(raw_fields)
    ):
        raise ArtifactValidationError("Level-B design is missing native fields")
    calibration = _mapping(payload.get("latency_calibration"), "latency_calibration")
    if calibration.get("primary_metric") != "backend_service_e2e_seconds":
        raise ArtifactValidationError("unsupported primary latency metric")
    repeats = calibration.get("identical_baseline_repeats")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats != 5:
        raise ArtifactValidationError("latency calibration requires five repeats")
    if payload.get("formal_h1_outcome_execution_authorized") is not False:
        raise ArtifactValidationError("formal H1 outcome execution must remain locked")
    return payload
