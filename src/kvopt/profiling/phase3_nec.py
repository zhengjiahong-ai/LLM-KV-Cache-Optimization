"""Independent Phase 3 N/E/C evaluation from persisted Native evidence.

This module deliberately does not reuse ``runtime_evidence._eligible_prefix_tokens``.
In particular, Native APC hits (C) are never used to fill or lower-bound missing
eligibility evidence (E).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from .ingestion import ArtifactValidationError

_NATIVE_OBSERVATION = "VLLM_NATIVE_REQUEST_OBSERVATION"
_PREFIX_SNAPSHOT = "VLLM_PREFIX_SNAPSHOT"
_PHASE3_ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")


@dataclass(frozen=True, slots=True)
class _HashChain:
    hashes: tuple[str, ...]
    block_size: int
    process_id: str
    hash_function: str


@dataclass(frozen=True, slots=True)
class NECRequestResult:
    request_id: str
    program_id: str
    native_prompt_tokens: int
    eligible_prefix_tokens: int
    native_cached_prefix_tokens: int
    actual_prefill_tokens: int
    recomputed_tokens: int
    new_suffix_tokens: int
    apc_outcome: str
    eligibility_source: str


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactValidationError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactValidationError(f"{name} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise ArtifactValidationError(f"{name} must be {qualifier}")
    return value


def _hashes(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{name} must be an array")
    result: list[str] = []
    for item in value:
        text = _text(item, f"{name} item")
        if (
            len(text) != 64
            or text != text.lower()
            or any(character not in "0123456789abcdef" for character in text)
        ):
            raise ArtifactValidationError(
                f"{name} items must be 64-character lowercase SHA-256 digests"
            )
        result.append(text)
    return tuple(result)


def _chain(
    payload: Mapping[str, object],
    *,
    hashes_field: str,
    label: str,
) -> _HashChain:
    return _HashChain(
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


def _event_index(event: Mapping[str, object], label: str) -> int:
    return _integer(event.get("event_index"), f"{label} event_index")


def _identity(event: Mapping[str, object], label: str) -> tuple[str, str]:
    return (
        _text(event.get("program_id"), f"{label} program_id"),
        _text(event.get("request_id"), f"{label} request_id"),
    )


def _common_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_value, right_value in zip(left, right):
        if left_value != right_value:
            break
        count += 1
    return count


def _derive_request(
    observation: Mapping[str, object],
    prior_snapshots: Sequence[Mapping[str, object]],
    *,
    completion_output_tokens: int | None,
) -> NECRequestResult:
    program_id, request_id = _identity(observation, "native observation")
    payload = _object(observation.get("payload"), "native observation payload")
    n = _integer(payload.get("native_prompt_tokens"), "native_prompt_tokens")
    c = _integer(
        payload.get("native_cached_prefix_tokens"),
        "native_cached_prefix_tokens",
    )
    current = _chain(
        payload,
        hashes_field="native_apc_block_hashes",
        label="native observation",
    )
    complete_prompt_blocks = n // current.block_size
    expected_hash_count = complete_prompt_blocks
    generated_tail_allowed = (
        n % current.block_size == current.block_size - 1
        and completion_output_tokens == 1
    )
    if len(current.hashes) not in {
        expected_hash_count,
        expected_hash_count + int(generated_tail_allowed),
    }:
        raise ArtifactValidationError(
            f"{request_id} Native hash chain does not cover all complete prompt blocks"
        )
    current = _HashChain(
        hashes=current.hashes[:expected_hash_count],
        block_size=current.block_size,
        process_id=current.process_id,
        hash_function=current.hash_function,
    )

    compatible: list[_HashChain] = []
    for snapshot in prior_snapshots:
        snapshot_payload = _object(
            snapshot.get("payload"), "prior prefix snapshot payload"
        )
        evidence = _chain(
            snapshot_payload,
            hashes_field="ordered_native_hashes",
            label="prior prefix snapshot",
        )
        hash_tokens = _integer(
            snapshot_payload.get("hash_num_tokens"),
            "prior prefix snapshot hash_num_tokens",
        )
        if not evidence.hashes or hash_tokens == 0:
            raise ArtifactValidationError(
                "prior prefix snapshot hash chain must be non-empty"
            )
        if hash_tokens != len(evidence.hashes) * evidence.block_size:
            raise ArtifactValidationError(
                "prior prefix snapshot token count disagrees with its hash chain"
            )
        if (
            evidence.process_id == current.process_id
            and evidence.hash_function == current.hash_function
            and evidence.block_size == current.block_size
        ):
            compatible.append(evidence)

    if prior_snapshots and not compatible:
        raise ArtifactValidationError(
            f"{request_id} has prior history but no compatible content-identity chain"
        )
    longest_blocks = max(
        (_common_prefix(current.hashes, prior.hashes) for prior in compatible),
        default=0,
    )
    # Prefix caching only covers complete blocks preceding the request tail.
    maximum_reusable_blocks = (n - 1) // current.block_size if n else 0
    e = min(longest_blocks, maximum_reusable_blocks) * current.block_size
    if not 0 <= c <= e <= n:
        raise ArtifactValidationError(
            f"{request_id} violates Phase 3 invariant 0 <= C <= E <= N: "
            f"N={n}, E={e}, C={c}"
        )
    actual_prefill = n - c
    recomputed = e - c
    new_suffix = n - e
    if actual_prefill != recomputed + new_suffix:
        raise ArtifactValidationError(
            f"{request_id} violates N-C = (E-C) + (N-E)"
        )
    if e == 0:
        outcome = "NO_REUSE_ELIGIBLE_PREFIX"
    elif c == e:
        outcome = "FULL_HIT"
    elif c == 0:
        outcome = "MISS"
    else:
        outcome = "PARTIAL_HIT"
    return NECRequestResult(
        request_id=request_id,
        program_id=program_id,
        native_prompt_tokens=n,
        eligible_prefix_tokens=e,
        native_cached_prefix_tokens=c,
        actual_prefill_tokens=actual_prefill,
        recomputed_tokens=recomputed,
        new_suffix_tokens=new_suffix,
        apc_outcome=outcome,
        eligibility_source=(
            "FROZEN_PRIOR_CONTENT_IDENTITY_CHAIN"
            if compatible
            else "FROZEN_HISTORY_NO_PRIOR_ELIGIBLE_CONTENT"
        ),
    )


def _evaluate_arm(
    arm: str,
    events: Sequence[Mapping[str, object]],
    frozen_requests: Sequence[tuple[str, str]],
    pressure_request_ids: frozenset[str],
) -> dict[str, object]:
    expected = tuple(frozen_requests)
    if len(expected) != len(set(expected)):
        raise ArtifactValidationError("frozen request identities must be unique")
    expected_set = set(expected)
    indexed_events = sorted(
        events, key=lambda event: _event_index(event, f"{arm} event")
    )
    observations: dict[tuple[str, str], Mapping[str, object]] = {}
    completions: dict[tuple[str, str], int] = {}
    for event in indexed_events:
        if event.get("event_type") == "VLLM_REQUEST_COMPLETED":
            identity = _identity(event, f"{arm} request completion")
            if identity in expected_set:
                payload = _object(
                    event.get("payload"), f"{arm} request completion payload"
                )
                if identity in completions:
                    raise ArtifactValidationError(
                        f"{arm} request {identity} has duplicate completions"
                    )
                completions[identity] = _integer(
                    payload.get("output_token_count"), "output_token_count"
                )
            continue
        if event.get("event_type") != _NATIVE_OBSERVATION:
            continue
        identity = _identity(event, f"{arm} native observation")
        # Pressure requests are persisted in the same event stream but are not
        # members of the frozen effect-estimation request set.
        if identity not in expected_set:
            if identity[1] in pressure_request_ids:
                continue
            raise ArtifactValidationError(
                f"{arm} has unknown non-pressure Native observation {identity}"
            )
        if identity in observations:
            raise ArtifactValidationError(
                f"{arm} request {identity} has duplicate Native observations"
            )
        observations[identity] = event
    if set(observations) != expected_set:
        missing = sorted(expected_set - set(observations))
        extra = sorted(set(observations) - expected_set)
        raise ArtifactValidationError(
            f"{arm} frozen request set mismatch: missing={missing}, extra={extra}"
        )

    rows: list[NECRequestResult] = []
    for request_position, identity in enumerate(expected):
        observation = observations[identity]
        observation_index = _event_index(observation, "native observation")
        prior_snapshots = [
            event
            for event in indexed_events
            if event.get("event_type") == _PREFIX_SNAPSHOT
            and _event_index(event, "prefix snapshot") < observation_index
        ]
        if request_position > 0 and not prior_snapshots:
            raise ArtifactValidationError(
                f"{identity} is missing frozen prior request-history snapshots"
            )
        rows.append(
            _derive_request(
                observation,
                prior_snapshots,
                completion_output_tokens=completions.get(identity),
            )
        )

    sum_n = sum(row.native_prompt_tokens for row in rows)
    sum_c = sum(row.native_cached_prefix_tokens for row in rows)
    actual = sum(row.actual_prefill_tokens for row in rows)
    recomputed = sum(row.recomputed_tokens for row in rows)
    new_suffix = sum(row.new_suffix_tokens for row in rows)
    if actual != recomputed + new_suffix:
        raise ArtifactValidationError(
            f"{arm} aggregate identity N-C = (E-C) + (N-E) failed"
        )
    return {
        "arm": arm,
        "status": "PASS",
        "request_count": len(rows),
        "requests": [asdict(row) for row in rows],
        "aggregate_native_prompt_tokens": sum_n,
        "aggregate_cached_tokens": sum_c,
        "aggregate_actual_prefill_tokens": actual,
        "aggregate_recomputed_tokens": recomputed,
        "aggregate_new_suffix_tokens": new_suffix,
        "apc_reuse_ratio": (None if sum_n == 0 else sum_c / sum_n),
        "recompute_ratio": (None if actual == 0 else recomputed / actual),
    }


def _pressure_request_ids(cell_manifest: Mapping[str, object]) -> frozenset[str]:
    if cell_manifest.get("schema_version") != "phase3.six_arm_cell_manifest.v1":
        raise ArtifactValidationError("unsupported Phase 3 cell manifest")
    if cell_manifest.get("arms") != list(_PHASE3_ARMS):
        raise ArtifactValidationError("cell manifest must freeze all six Phase 3 arms")
    contract = cell_manifest.get("pressure_request_contract")
    if not isinstance(contract, list) or not contract:
        raise ArtifactValidationError(
            "cell manifest pressure_request_contract must be a non-empty array"
        )
    result: list[str] = []
    for row in contract:
        mapping = _object(row, "pressure request contract row")
        request_ids = mapping.get("request_ids")
        if not isinstance(request_ids, list) or not request_ids:
            raise ArtifactValidationError(
                "pressure request contract request_ids must be a non-empty array"
            )
        result.extend(
            _text(value, "pressure request id") for value in request_ids
        )
    if len(result) != len(set(result)):
        raise ArtifactValidationError("pressure request IDs must be unique")
    return frozenset(result)


def evaluate_phase3_nec_cell(
    *,
    events_by_arm: Mapping[str, Sequence[Mapping[str, object]]],
    frozen_requests: Sequence[tuple[str, str]],
    cell_manifest: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate one Phase 3 cell and fail closed on any evidence defect."""

    required = _PHASE3_ARMS
    issues: list[str] = []
    pressure_ids: frozenset[str] = frozenset()
    if not frozen_requests:
        issues.append("frozen request set must not be empty")
    try:
        pressure_ids = _pressure_request_ids(cell_manifest)
    except (ArtifactValidationError, TypeError, ValueError) as error:
        issues.append(f"manifest: {error}")
    if set(events_by_arm) != set(required):
        issues.append(
            "arm set mismatch: "
            f"expected={sorted(required)}, observed={sorted(events_by_arm)}"
        )
    arm_reports: dict[str, dict[str, object]] = {}
    if not issues:
        for arm in required:
            try:
                arm_reports[arm] = _evaluate_arm(
                    arm, events_by_arm[arm], frozen_requests, pressure_ids
                )
            except (ArtifactValidationError, TypeError, ValueError) as error:
                issues.append(f"{arm}: {error}")

    if not issues:
        for request_index, identity in enumerate(frozen_requests):
            values = {
                arm: (
                    arm_reports[arm]["requests"][request_index][
                        "native_prompt_tokens"
                    ],
                    arm_reports[arm]["requests"][request_index][
                        "eligible_prefix_tokens"
                    ],
                )
                for arm in required
            }
            if len(set(values.values())) != 1:
                issues.append(
                    f"request {identity} has cross-arm N/E mismatch: {values}"
                )

    return {
        "schema_version": "phase3.nec_cell_report.v1",
        "status": "PASS" if not issues else "FAIL_CLOSED",
        "primary_metric": "aggregate_recomputed_tokens",
        "primary_metric_formula": "sum(E-C)",
        "eligibility_is_arm_independent": not issues,
        "c_used_as_eligibility_fallback": False,
        "ownership_level_attribution": "NOT_ESTABLISHED",
        "issues": issues,
        "arms": arm_reports,
    }
