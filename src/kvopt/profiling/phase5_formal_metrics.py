"""Protocol-neutral raw-evidence metrics for the Phase 5 Formal Campaign.

The evaluator never consumes policy-produced aggregate metrics.  Eligibility
``E`` is derived from frozen predecessor snapshots and Native content identity;
Native cached tokens ``C`` are only checked after that independent derivation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .ingestion import ArtifactValidationError

_REQUEST_EVENT_TYPES = frozenset(
    {
        "REQUEST_ARRIVED",
        "CLIENT_DISPATCH_ACCEPTED",
        "FIRST_OUTPUT_TOKEN",
        "VLLM_REQUEST_SUBMITTED",
        "VLLM_REQUEST_COMPLETED",
        "VLLM_NATIVE_REQUEST_OBSERVATION",
        "VLLM_PREFIX_SNAPSHOT",
    }
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(f"{label} must be non-empty text")
    return value


def _integer(value: object, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactValidationError(f"{label} must be an integer")
    if value < (1 if positive else 0):
        raise ArtifactValidationError(
            f"{label} must be {'positive' if positive else 'non-negative'}"
        )
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ArtifactValidationError(f"{label} must be finite and non-negative")
    return result


def _payload(event: Mapping[str, object], label: str) -> Mapping[str, object]:
    value = event.get("payload")
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{label} payload must be an object")
    return value


def _event_index(event: Mapping[str, object]) -> int:
    return _integer(event.get("event_index"), "event_index")


def _identity(event: Mapping[str, object], label: str) -> tuple[str, str]:
    return (
        _text(event.get("program_id"), f"{label} program_id"),
        _text(event.get("request_id"), f"{label} request_id"),
    )


def _hashes(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{label} must be an array")
    result = []
    for item in value:
        digest = _text(item, f"{label} item")
        if (
            len(digest) != 64
            or digest != digest.lower()
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ArtifactValidationError(
                f"{label} items must be lowercase SHA-256 digests"
            )
        result.append(digest)
    return tuple(result)


def _lcp(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_value, right_value in zip(left, right):
        if left_value != right_value:
            break
        count += 1
    return count


@dataclass(frozen=True, slots=True)
class _Chain:
    hashes: tuple[str, ...]
    block_size: int
    process_id: str
    hash_function: str


def _chain(
    payload: Mapping[str, object], *, hashes_field: str, label: str
) -> _Chain:
    return _Chain(
        hashes=_hashes(payload.get(hashes_field), f"{label} {hashes_field}"),
        block_size=_integer(
            payload.get("native_hash_block_size"),
            f"{label} native_hash_block_size",
            positive=True,
        ),
        process_id=_text(
            payload.get("native_hash_process_id"),
            f"{label} native_hash_process_id",
        ),
        hash_function=_text(
            payload.get("native_hash_function"),
            f"{label} native_hash_function",
        ),
    )


class FormalEvidenceRecorder:
    """Collect one immutable event stream while rejecting identity ambiguity."""

    def __init__(
        self,
        *,
        expected_requests: Sequence[tuple[str, str]],
        pressure_request_ids: Sequence[str] = (),
    ) -> None:
        self._expected = frozenset(expected_requests)
        if not self._expected or len(self._expected) != len(expected_requests):
            raise ValueError("expected request identities must be non-empty and unique")
        self._pressure = frozenset(pressure_request_ids)
        self._events: list[dict[str, object]] = []
        self._indices: set[int] = set()

    def record(self, event: Mapping[str, object]) -> None:
        index = _event_index(event)
        if index in self._indices:
            raise ArtifactValidationError("event stream contains duplicate event_index")
        event_type = _text(event.get("event_type"), "event_type")
        if event_type in _REQUEST_EVENT_TYPES:
            identity = _identity(event, event_type)
            if identity not in self._expected and identity[1] not in self._pressure:
                raise ArtifactValidationError(
                    f"unknown non-pressure request evidence {identity}"
                )
        self._indices.add(index)
        self._events.append(dict(event))

    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(sorted(self._events, key=_event_index))


def _one_by_identity(
    events: Sequence[Mapping[str, object]],
    event_type: str,
    expected: frozenset[tuple[str, str]],
) -> dict[tuple[str, str], Mapping[str, object]]:
    result: dict[tuple[str, str], Mapping[str, object]] = {}
    for event in events:
        if event.get("event_type") != event_type:
            continue
        identity = _identity(event, event_type)
        if identity not in expected:
            continue
        if identity in result:
            raise ArtifactValidationError(
                f"request {identity} has duplicate {event_type}"
            )
        result[identity] = event
    return result


def _landmark(event: Mapping[str, object], label: str) -> tuple[float, str]:
    return (
        _number(event.get("timestamp"), f"{label} timestamp"),
        _text(event.get("clock_domain"), f"{label} clock_domain"),
    )


def _duration(
    start: tuple[float, str] | None,
    end: tuple[float, str] | None,
) -> tuple[float | None, str]:
    if start is None or end is None:
        return None, "MISSING"
    if start[1] != end[1]:
        return None, "INCOMPATIBLE_CLOCK_DOMAIN"
    if end[0] < start[0]:
        raise ArtifactValidationError("timing landmarks are causally reversed")
    return end[0] - start[0], "AVAILABLE"


def evaluate_formal_run_metrics(
    *,
    run_id: str,
    arm_id: str,
    events: Sequence[Mapping[str, object]],
    frozen_requests: Sequence[tuple[str, str]],
    expected_native_enqueue_order: Sequence[tuple[str, str]],
    history_predecessors: Mapping[
        tuple[str, str], Sequence[tuple[str, str]]
    ],
    pressure_request_ids: Sequence[str] = (),
    right_censored_request_ids: Sequence[str] = (),
) -> dict[str, object]:
    """Independently derive one run's request metrics and evidence coverage."""

    _text(run_id, "run_id")
    _text(arm_id, "arm_id")
    frozen = tuple(frozen_requests)
    if not frozen or len(frozen) != len(set(frozen)):
        raise ArtifactValidationError(
            "frozen request identities must be non-empty and unique"
        )
    if tuple(expected_native_enqueue_order) != frozen:
        raise ArtifactValidationError(
            "expected Native enqueue order must equal frozen request order"
        )
    expected = frozenset(frozen)
    if set(history_predecessors) != set(frozen):
        raise ArtifactValidationError(
            "history predecessor keys must equal frozen request identities"
        )
    positions = {identity: index for index, identity in enumerate(frozen)}
    normalized_predecessors = {}
    for identity in frozen:
        predecessors = tuple(history_predecessors[identity])
        if len(predecessors) != len(set(predecessors)) or any(
            predecessor not in expected
            or positions[predecessor] >= positions[identity]
            for predecessor in predecessors
        ):
            raise ArtifactValidationError(
                f"request {identity} has invalid history predecessors"
            )
        normalized_predecessors[identity] = predecessors

    recorder = FormalEvidenceRecorder(
        expected_requests=frozen,
        pressure_request_ids=pressure_request_ids,
    )
    for event in events:
        recorder.record(event)
    ordered_events = recorder.events()
    submitted = _one_by_identity(
        ordered_events, "VLLM_REQUEST_SUBMITTED", expected
    )
    arrivals = _one_by_identity(ordered_events, "REQUEST_ARRIVED", expected)
    dispatches = _one_by_identity(
        ordered_events, "CLIENT_DISPATCH_ACCEPTED", expected
    )
    first_outputs = _one_by_identity(
        ordered_events, "FIRST_OUTPUT_TOKEN", expected
    )
    observed_order = tuple(
        _identity(event, "VLLM_REQUEST_SUBMITTED")
        for event in ordered_events
        if event.get("event_type") == "VLLM_REQUEST_SUBMITTED"
        and _identity(event, "VLLM_REQUEST_SUBMITTED") in expected
    )
    if observed_order != frozen or set(submitted) != expected:
        raise ArtifactValidationError("actual Native enqueue order is not exact")

    observations = _one_by_identity(
        ordered_events, "VLLM_NATIVE_REQUEST_OBSERVATION", expected
    )
    if set(observations) != expected:
        raise ArtifactValidationError("Native observation request set is incomplete")
    completions = _one_by_identity(
        ordered_events, "VLLM_REQUEST_COMPLETED", expected
    )
    censored = frozenset(right_censored_request_ids)
    known_request_ids = {identity[1] for identity in frozen}
    if not censored <= known_request_ids:
        raise ArtifactValidationError("right-censored request identity is unknown")
    missing_completion_ids = {
        identity[1] for identity in expected if identity not in completions
    }
    if missing_completion_ids != censored:
        raise ArtifactValidationError(
            "completion missingness does not exactly match right-censoring contract"
        )

    snapshots = _one_by_identity(
        ordered_events, "VLLM_PREFIX_SNAPSHOT", expected
    )
    rows = []
    coverage = {
        "nec": 0,
        "ttft": 0,
        "latency": 0,
        "terminal": len(completions),
    }
    for identity in frozen:
        observation = observations[identity]
        payload = _payload(observation, "Native observation")
        completion_event = completions.get(identity)
        output_tokens = (
            None
            if completion_event is None
            else _integer(
                _payload(completion_event, "completion").get("output_token_count"),
                "output_token_count",
            )
        )
        n = _integer(payload.get("native_prompt_tokens"), "N")
        c = _integer(payload.get("native_cached_prefix_tokens"), "C")
        current = _chain(
            payload,
            hashes_field="native_apc_block_hashes",
            label="Native observation",
        )
        full_blocks = n // current.block_size
        generated_tail_allowed = (
            n % current.block_size == current.block_size - 1
            and output_tokens == 1
        )
        if len(current.hashes) not in {
            full_blocks,
            full_blocks + int(generated_tail_allowed),
        }:
            raise ArtifactValidationError(
                f"request {identity} Native hash chain does not exactly cover "
                "complete prompt blocks"
            )
        current_hashes = current.hashes[:full_blocks]
        compatible = []
        for predecessor in normalized_predecessors[identity]:
            snapshot = snapshots.get(predecessor)
            if snapshot is None:
                raise ArtifactValidationError(
                    f"request {identity} lacks predecessor snapshot {predecessor}"
                )
            snapshot_payload = _payload(snapshot, "Prefix Snapshot")
            prior = _chain(
                snapshot_payload,
                hashes_field="ordered_native_hashes",
                label="Prefix Snapshot",
            )
            hash_tokens = _integer(
                snapshot_payload.get("hash_num_tokens"),
                "Prefix Snapshot hash_num_tokens",
                positive=True,
            )
            if not prior.hashes or hash_tokens != len(prior.hashes) * prior.block_size:
                raise ArtifactValidationError("Prefix Snapshot hash chain is incomplete")
            if (
                prior.block_size == current.block_size
                and prior.process_id == current.process_id
                and prior.hash_function == current.hash_function
            ):
                compatible.append(prior)
        if normalized_predecessors[identity] and not compatible:
            raise ArtifactValidationError(
                f"request {identity} has no compatible predecessor identity"
            )
        longest = max(
            (_lcp(current_hashes, prior.hashes) for prior in compatible), default=0
        )
        reusable_blocks = (n - 1) // current.block_size if n else 0
        e = min(longest, reusable_blocks) * current.block_size
        if not 0 <= c <= e <= n:
            raise ArtifactValidationError(
                f"request {identity} violates 0 <= C <= E <= N"
            )
        recomputed = e - c
        actual_prefill = n - c
        new_suffix = n - e
        if actual_prefill != recomputed + new_suffix:
            raise ArtifactValidationError(
                f"request {identity} violates N-C=(E-C)+(N-E)"
            )
        coverage["nec"] += 1

        dispatch_landmark = (
            None
            if identity not in dispatches
            else _landmark(dispatches[identity], "client dispatch accepted")
        )
        first_output_landmark = (
            None
            if identity not in first_outputs
            else _landmark(first_outputs[identity], "first output token")
        )
        ttft, ttft_status = _duration(dispatch_landmark, first_output_landmark)
        if ttft_status == "AVAILABLE":
            coverage["ttft"] += 1

        arrival_landmark = (
            None
            if identity not in arrivals
            else _landmark(arrivals[identity], "arrival")
        )
        completion_landmark = (
            None
            if completion_event is None
            else _landmark(completion_event, "completion")
        )
        latency, latency_status = _duration(arrival_landmark, completion_landmark)
        if latency_status == "AVAILABLE":
            coverage["latency"] += 1
        rows.append(
            {
                "program_id": identity[0],
                "request_id": identity[1],
                "N": n,
                "E": e,
                "C": c,
                "actual_prefill_tokens": actual_prefill,
                "recomputed_tokens": recomputed,
                "new_suffix_tokens": new_suffix,
                "eligibility_source": (
                    "FROZEN_PREDECESSOR_NATIVE_CONTENT_IDENTITY"
                    if compatible
                    else "NO_FROZEN_PREDECESSOR"
                ),
                "right_censored": identity[1] in censored,
                "output_token_count": output_tokens,
                "ttft_seconds": ttft,
                "ttft_ms": None if ttft is None else ttft * 1000.0,
                "ttft_status": ttft_status,
                "latency_seconds": latency,
                "latency_ms": None if latency is None else latency * 1000.0,
                "latency_status": latency_status,
            }
        )

    request_count = len(frozen)
    run_window_seconds = None
    run_window_status = "MISSING"
    arrival_landmarks = [
        _landmark(arrivals[identity], "arrival")
        for identity in frozen
        if identity in arrivals
    ]
    completion_landmarks = [
        _landmark(completions[identity], "completion")
        for identity in frozen
        if identity in completions
    ]
    if (
        len(arrival_landmarks) == request_count
        and len(completion_landmarks) == request_count
    ):
        domains = {
            landmark[1] for landmark in (*arrival_landmarks, *completion_landmarks)
        }
        if len(domains) != 1:
            run_window_status = "INCOMPATIBLE_CLOCK_DOMAIN"
        else:
            start = min(landmark[0] for landmark in arrival_landmarks)
            end = max(landmark[0] for landmark in completion_landmarks)
            if end < start:
                raise ArtifactValidationError(
                    "run timing landmarks are causally reversed"
                )
            run_window_seconds = end - start
            run_window_status = "AVAILABLE" if run_window_seconds > 0 else "ZERO_DURATION"
    total_output_tokens = sum(row["output_token_count"] or 0 for row in rows)
    request_throughput = (
        request_count / run_window_seconds
        if run_window_status == "AVAILABLE" and run_window_seconds is not None
        else None
    )
    token_throughput = (
        total_output_tokens / run_window_seconds
        if run_window_status == "AVAILABLE" and run_window_seconds is not None
        else None
    )
    missingness = {
        metric: {
            "available": count,
            "missing": request_count - count,
            "coverage": count / request_count,
        }
        for metric, count in coverage.items()
    }
    return {
        "schema_version": "phase5.formal_run_metrics.v1",
        "status": "PASS",
        "run_id": run_id,
        "arm_id": arm_id,
        "request_count": request_count,
        "actual_native_enqueue_order": [
            {"program_id": program_id, "request_id": request_id}
            for program_id, request_id in observed_order
        ],
        "requests": rows,
        "aggregates": {
            "native_prompt_tokens": sum(row["N"] for row in rows),
            "eligible_prefix_tokens": sum(row["E"] for row in rows),
            "native_cached_prefix_tokens": sum(row["C"] for row in rows),
            "recomputed_tokens": sum(row["recomputed_tokens"] for row in rows),
            "actual_prefill_tokens": sum(row["actual_prefill_tokens"] for row in rows),
            "output_tokens": total_output_tokens,
            "observed_run_window_seconds": run_window_seconds,
            "observed_run_window_status": run_window_status,
            "throughput_requests_per_second": request_throughput,
            "throughput_tokens_per_second": token_throughput,
            "completion_time_seconds": run_window_seconds,
            "completion_time_ms": (
                None if run_window_seconds is None else run_window_seconds * 1000.0
            ),
            "completion_time_status": (
                run_window_status
                if not censored
                else "CENSORED_INCOMPLETE"
            ),
        },
        "missingness": missingness,
        "policy_aggregate_fields_consumed": False,
        "eligibility_uses_native_cached_tokens_c": False,
    }
