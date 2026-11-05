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
    concurrent_eligibility_audits: tuple[dict[str, object], ...]


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


def _timestamp(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{name} must be a numeric timestamp")
    result = float(value)
    if result <= 0:
        raise ArtifactValidationError(f"{name} must be positive")
    return result


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


def _block_ids(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{name} must be an array")
    result: list[int] = []
    for item in value:
        result.append(_integer(item, f"{name} item"))
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
    concurrent_eligibility_audits: Sequence[Mapping[str, object]] = (),
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
            "FROZEN_TIMELINE_AND_NATIVE_VISIBILITY_CONTENT_IDENTITY_CHAIN"
            if compatible
            else "FROZEN_HISTORY_NO_PRIOR_ELIGIBLE_CONTENT"
        ),
        concurrent_eligibility_audits=tuple(
            dict(row) for row in concurrent_eligibility_audits
        ),
    )


def _concurrent_visibility_audit(
    *,
    producer_identity: tuple[str, str],
    consumer_identity: tuple[str, str],
    producer_observation: Mapping[str, object],
    consumer_observation: Mapping[str, object],
    producer_snapshot: Mapping[str, object],
    consumer_snapshot: Mapping[str, object] | None,
    minimum_eligible_blocks: int,
) -> tuple[dict[str, object], bool]:
    """Prove same-batch or earlier-forward visibility without consulting C.

    The frozen vLLM 0.27.1 UniProc path registers a producer's full-block
    metadata before a later lookup.  For requests in one Scheduler iteration,
    the attention layer explicitly threads the KV-update dummy dependency into
    unified attention, preserving scatter-write-before-read ordering.  Across
    iterations, UniProc invokes the worker synchronously, so successive model
    submissions preserve that same ordering.  Persisted snapshots must still
    prove that both requests referenced the identical physical prefix blocks.
    """

    producer_payload = _object(
        producer_observation.get("payload"), "producer native observation payload"
    )
    consumer_payload = _object(
        consumer_observation.get("payload"), "consumer native observation payload"
    )
    producer_snapshot_payload = _object(
        producer_snapshot.get("payload"), "producer prefix snapshot payload"
    )
    producer_chain = _chain(
        producer_snapshot_payload,
        hashes_field="ordered_native_hashes",
        label="producer prefix snapshot",
    )
    consumer_chain = _chain(
        consumer_payload,
        hashes_field="native_apc_block_hashes",
        label="consumer native observation",
    )
    if producer_observation.get("clock_domain") != "engine_core_monotonic" or (
        consumer_observation.get("clock_domain") != "engine_core_monotonic"
    ):
        raise ArtifactValidationError(
            f"{consumer_identity} concurrent visibility timestamps require the "
            "engine_core_monotonic clock domain"
        )
    if (
        producer_chain.process_id != consumer_chain.process_id
        or producer_chain.hash_function != consumer_chain.hash_function
        or producer_chain.block_size != consumer_chain.block_size
    ):
        raise ArtifactValidationError(
            f"{consumer_identity} concurrent predecessor {producer_identity} "
            "has incompatible Native hash identity"
        )
    producer_observation_chain = _chain(
        producer_payload,
        hashes_field="native_apc_block_hashes",
        label="producer native observation",
    )
    if (
        producer_observation_chain.process_id != producer_chain.process_id
        or producer_observation_chain.hash_function != producer_chain.hash_function
        or producer_observation_chain.block_size != producer_chain.block_size
        or producer_observation_chain.hashes[: len(producer_chain.hashes)]
        != producer_chain.hashes
    ):
        raise ArtifactValidationError(
            f"{producer_identity} Native observation and Snapshot identity disagree"
        )
    producer_queued = _timestamp(
        producer_payload.get("native_queued_timestamp"),
        "producer native_queued_timestamp",
    )
    producer_scheduled = _timestamp(
        producer_payload.get("native_scheduler_admission_timestamp"),
        "producer native_scheduler_admission_timestamp",
    )
    producer_first_token = _timestamp(
        producer_payload.get("native_first_token_timestamp"),
        "producer native_first_token_timestamp",
    )
    consumer_queued = _timestamp(
        consumer_payload.get("native_queued_timestamp"),
        "consumer native_queued_timestamp",
    )
    consumer_scheduled = _timestamp(
        consumer_payload.get("native_scheduler_admission_timestamp"),
        "consumer native_scheduler_admission_timestamp",
    )
    if producer_scheduled < producer_queued or consumer_scheduled < consumer_queued:
        raise ArtifactValidationError(
            f"{consumer_identity} scheduler admission precedes queue entry"
        )
    if producer_scheduled > consumer_scheduled:
        raise ArtifactValidationError(
            f"{consumer_identity} concurrent predecessor {producer_identity} "
            "was scheduled after the consumer"
        )
    lcp_blocks = _common_prefix(consumer_chain.hashes, producer_chain.hashes)
    if lcp_blocks <= minimum_eligible_blocks:
        return (
            {
                "producer_program_id": producer_identity[0],
                "producer_request_id": producer_identity[1],
                "consumer_program_id": consumer_identity[0],
                "consumer_request_id": consumer_identity[1],
                "native_clock_domain": "engine_core_monotonic",
                "producer_queued_timestamp": producer_queued,
                "producer_scheduler_admission_timestamp": producer_scheduled,
                "producer_first_token_timestamp": producer_first_token,
                "consumer_queued_timestamp": consumer_queued,
                "consumer_scheduler_admission_timestamp": consumer_scheduled,
                "snapshot_event_index": _event_index(
                    producer_snapshot, "producer prefix snapshot"
                ),
                "snapshot_may_follow_consumer_observation": (
                    _event_index(producer_snapshot, "producer prefix snapshot")
                    > _event_index(consumer_observation, "consumer native observation")
                ),
                "hash_lcp_blocks": lcp_blocks,
                "eligible_full_block_tokens": (
                    lcp_blocks * consumer_chain.block_size
                ),
                "minimum_existing_eligible_blocks": minimum_eligible_blocks,
                "qualification_result": (
                    "NOT_QUALIFIED_DOMINATED_BY_EXISTING_HISTORY"
                ),
                "visibility_rule": (
                    "DOMINATED_CANDIDATE_DOES_NOT_CHANGE_INDEPENDENT_E"
                ),
                "uses_native_cached_tokens_c": False,
            },
            False,
        )
    if consumer_snapshot is None:
        raise ArtifactValidationError(
            f"{consumer_identity} concurrent candidate could increase E but lacks "
            "a consumer content-identity Snapshot"
        )
    consumer_snapshot_payload = _object(
        consumer_snapshot.get("payload"), "consumer prefix snapshot payload"
    )
    consumer_snapshot_chain = _chain(
        consumer_snapshot_payload,
        hashes_field="ordered_native_hashes",
        label="consumer prefix snapshot",
    )
    if (
        consumer_snapshot_chain.process_id != consumer_chain.process_id
        or consumer_snapshot_chain.hash_function != consumer_chain.hash_function
        or consumer_snapshot_chain.block_size != consumer_chain.block_size
    ):
        raise ArtifactValidationError(
            f"{consumer_identity} concurrent Snapshot has incompatible Native identity"
        )
    snapshot_lcp_blocks = _common_prefix(
        consumer_snapshot_chain.hashes, producer_chain.hashes
    )
    if snapshot_lcp_blocks < lcp_blocks:
        raise ArtifactValidationError(
            f"{consumer_identity} observation and Snapshot disagree on shared prefix"
        )
    if (
        consumer_chain.hashes[: len(consumer_snapshot_chain.hashes)]
        != consumer_snapshot_chain.hashes
    ):
        raise ArtifactValidationError(
            f"{consumer_identity} Native observation and Snapshot identity disagree"
        )
    producer_blocks = _block_ids(
        producer_snapshot_payload.get("block_ids"),
        "producer prefix snapshot block_ids",
    )
    consumer_blocks = _block_ids(
        consumer_snapshot_payload.get("block_ids"),
        "consumer prefix snapshot block_ids",
    )
    physical_evidence_complete = (
        len(producer_blocks) >= lcp_blocks and len(consumer_blocks) >= lcp_blocks
    )
    physical_prefix_equal = (
        physical_evidence_complete
        and producer_blocks[:lcp_blocks] == consumer_blocks[:lcp_blocks]
    )
    if lcp_blocks > 0 and not physical_evidence_complete:
        raise ArtifactValidationError(
            f"{consumer_identity} shared prefix lacks complete physical Block evidence"
        )
    if lcp_blocks > 0 and not physical_prefix_equal:
        raise ArtifactValidationError(
            f"{consumer_identity} shared prefix physical Block IDs disagree"
        )
    scheduler_relation = (
        "SAME_SCHEDULER_ITERATION"
        if producer_scheduled == consumer_scheduled
        else "EARLIER_SCHEDULER_ITERATION"
    )
    qualified = lcp_blocks > 0 and physical_prefix_equal
    if qualified:
        qualification = (
            "QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR"
            if scheduler_relation == "SAME_SCHEDULER_ITERATION"
            else "QUALIFIED_EARLIER_FORWARD_SHARED_PREDECESSOR"
        )
    elif lcp_blocks == 0:
        qualification = "NOT_QUALIFIED_NO_SHARED_COMPLETE_BLOCK"
    elif not physical_evidence_complete:
        qualification = "NOT_QUALIFIED_PHYSICAL_BLOCK_EVIDENCE_INCOMPLETE"
    else:
        qualification = "NOT_QUALIFIED_PHYSICAL_BLOCK_ID_MISMATCH"
    return (
        {
            "producer_program_id": producer_identity[0],
            "producer_request_id": producer_identity[1],
            "consumer_program_id": consumer_identity[0],
            "consumer_request_id": consumer_identity[1],
            "native_clock_domain": "engine_core_monotonic",
            "producer_queued_timestamp": producer_queued,
            "producer_scheduler_admission_timestamp": producer_scheduled,
            "producer_first_token_timestamp": producer_first_token,
            "consumer_queued_timestamp": consumer_queued,
            "consumer_scheduler_admission_timestamp": consumer_scheduled,
            "snapshot_event_index": _event_index(
                producer_snapshot, "producer prefix snapshot"
            ),
            "snapshot_may_follow_consumer_observation": (
                _event_index(producer_snapshot, "producer prefix snapshot")
                > _event_index(consumer_observation, "consumer native observation")
            ),
            "hash_lcp_blocks": lcp_blocks,
            "eligible_full_block_tokens": lcp_blocks * consumer_chain.block_size,
            "scheduler_relation": scheduler_relation,
            "producer_prefix_block_ids": producer_blocks[:lcp_blocks],
            "consumer_prefix_block_ids": consumer_blocks[:lcp_blocks],
            "physical_block_evidence_complete": physical_evidence_complete,
            "physical_prefix_block_ids_equal": physical_prefix_equal,
            "qualification_result": qualification,
            "visibility_rule": (
                "VLLM_0_27_1_UNIPROC_KV_UPDATE_BEFORE_ATTENTION_READ_WITH_"
                "PHYSICAL_BLOCK_IDENTITY"
            ),
            "uses_native_cached_tokens_c": False,
        },
        qualified,
    )


def _evaluate_arm(
    arm: str,
    events: Sequence[Mapping[str, object]],
    frozen_requests: Sequence[tuple[str, str]],
    pressure_request_ids: frozenset[str],
    history_predecessors: Mapping[
        tuple[str, str], tuple[tuple[str, str], ...]
    ],
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
    snapshots_by_identity: dict[
        tuple[str, str], list[Mapping[str, object]]
    ] = {}
    for event in indexed_events:
        if event.get("event_type") != _PREFIX_SNAPSHOT:
            continue
        snapshot_identity = _identity(event, f"{arm} prefix snapshot")
        if snapshot_identity in expected_set:
            snapshots_by_identity.setdefault(snapshot_identity, []).append(event)

    positions = {identity: index for index, identity in enumerate(expected)}
    for identity in expected:
        observation = observations[identity]
        observation_index = _event_index(observation, "native observation")
        prior_snapshots: list[Mapping[str, object]] = []
        for predecessor in history_predecessors[identity]:
            matches = [
                snapshot
                for snapshot in snapshots_by_identity.get(predecessor, [])
                if _event_index(snapshot, "prefix snapshot") < observation_index
            ]
            if len(matches) != 1:
                raise ArtifactValidationError(
                    f"{identity} requires exactly one prior snapshot for "
                    f"history predecessor {predecessor}; observed={len(matches)}"
                )
            prior_snapshots.append(matches[0])
        concurrent_audits: list[dict[str, object]] = []
        observation_payload = _object(
            observation.get("payload"), "native observation payload"
        )
        current_chain = _chain(
            observation_payload,
            hashes_field="native_apc_block_hashes",
            label="native observation",
        )
        minimum_eligible_blocks = 0
        for snapshot in prior_snapshots:
            snapshot_chain = _chain(
                _object(snapshot.get("payload"), "prior prefix snapshot payload"),
                hashes_field="ordered_native_hashes",
                label="prior prefix snapshot",
            )
            if (
                snapshot_chain.process_id == current_chain.process_id
                and snapshot_chain.hash_function == current_chain.hash_function
                and snapshot_chain.block_size == current_chain.block_size
            ):
                minimum_eligible_blocks = max(
                    minimum_eligible_blocks,
                    _common_prefix(current_chain.hashes, snapshot_chain.hashes),
                )
        completed_predecessors = set(history_predecessors[identity])
        for producer_identity in expected[: positions[identity]]:
            if producer_identity in completed_predecessors:
                continue
            producer_snapshots = snapshots_by_identity.get(producer_identity, [])
            if len(producer_snapshots) != 1:
                raise ArtifactValidationError(
                    f"{identity} concurrent predecessor {producer_identity} requires "
                    "exactly one content-identity snapshot"
                )
            consumer_snapshots = snapshots_by_identity.get(identity, [])
            if len(consumer_snapshots) > 1:
                raise ArtifactValidationError(
                    f"{identity} has duplicate consumer content-identity Snapshots"
                )
            audit, qualified = _concurrent_visibility_audit(
                producer_identity=producer_identity,
                consumer_identity=identity,
                producer_observation=observations[producer_identity],
                consumer_observation=observation,
                producer_snapshot=producer_snapshots[0],
                consumer_snapshot=(
                    consumer_snapshots[0] if consumer_snapshots else None
                ),
                minimum_eligible_blocks=minimum_eligible_blocks,
            )
            concurrent_audits.append(audit)
            if qualified:
                prior_snapshots.append(producer_snapshots[0])
                minimum_eligible_blocks = max(
                    minimum_eligible_blocks,
                    int(audit["hash_lcp_blocks"]),
                )
        rows.append(
            _derive_request(
                observation,
                prior_snapshots,
                completion_output_tokens=completions.get(identity),
                concurrent_eligibility_audits=concurrent_audits,
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


def evaluate_phase3_nec_arm(
    *,
    arm: str,
    events: Sequence[Mapping[str, object]],
    frozen_requests: Sequence[tuple[str, str]],
    native_enqueue_order: Sequence[tuple[str, str]],
    history_predecessors: Mapping[
        tuple[str, str], Sequence[tuple[str, str]]
    ],
    pressure_request_ids: frozenset[str],
) -> dict[str, object]:
    """Evaluate one calibration arm under the same frozen N/E/C contract."""

    if arm not in _PHASE3_ARMS:
        raise ArtifactValidationError("unsupported Phase 3 arm")
    frozen_order = tuple(frozen_requests)
    if not frozen_order:
        raise ArtifactValidationError("frozen request set must not be empty")
    if tuple(native_enqueue_order) != frozen_order:
        raise ArtifactValidationError(
            "native enqueue order must exactly equal frozen request order"
        )
    frozen_set = set(frozen_order)
    if set(history_predecessors) != frozen_set:
        raise ArtifactValidationError(
            "history predecessor keys must exactly equal the frozen request set"
        )
    positions = {identity: index for index, identity in enumerate(frozen_order)}
    normalized: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
    for identity in frozen_order:
        predecessors = tuple(history_predecessors[identity])
        if len(predecessors) != len(set(predecessors)):
            raise ArtifactValidationError(f"{identity} has duplicate history predecessors")
        if any(
            predecessor not in frozen_set
            or positions[predecessor] >= positions[identity]
            for predecessor in predecessors
        ):
            raise ArtifactValidationError(f"{identity} has invalid history predecessors")
        normalized[identity] = predecessors
    return _evaluate_arm(
        arm,
        events,
        frozen_order,
        pressure_request_ids,
        normalized,
    )


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
    native_enqueue_order: Sequence[tuple[str, str]],
    history_predecessors: Mapping[
        tuple[str, str], Sequence[tuple[str, str]]
    ],
    cell_manifest: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate one Phase 3 cell and fail closed on any evidence defect.

    ``frozen_requests`` and ``native_enqueue_order`` must be identical ordered
    contracts.  ``history_predecessors`` comes from the frozen Replay Timeline
    and names only requests whose logical completion boundary makes their
    Snapshot available before the current Native enqueue.  Snapshot
    completeness must not be inferred from Native completion or event-write
    order.
    """

    required = _PHASE3_ARMS
    issues: list[str] = []
    pressure_ids: frozenset[str] = frozenset()
    normalized_predecessors: dict[
        tuple[str, str], tuple[tuple[str, str], ...]
    ] = {}
    if not frozen_requests:
        issues.append("frozen request set must not be empty")
    frozen_order = tuple(frozen_requests)
    if tuple(native_enqueue_order) != frozen_order:
        issues.append(
            "native enqueue order must exactly equal frozen request order"
        )
    frozen_set = set(frozen_order)
    if set(history_predecessors) != frozen_set:
        issues.append(
            "history predecessor keys must exactly equal the frozen request set"
        )
    if not issues:
        positions = {identity: index for index, identity in enumerate(frozen_order)}
        for identity in frozen_order:
            predecessors = tuple(history_predecessors[identity])
            if len(predecessors) != len(set(predecessors)):
                issues.append(f"{identity} has duplicate history predecessors")
                continue
            invalid = [
                predecessor
                for predecessor in predecessors
                if predecessor not in frozen_set
                or positions[predecessor] >= positions[identity]
            ]
            if invalid:
                issues.append(
                    f"{identity} has invalid history predecessors: {invalid}"
                )
                continue
            normalized_predecessors[identity] = predecessors
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
                    arm,
                    events_by_arm[arm],
                    frozen_requests,
                    pressure_ids,
                    normalized_predecessors,
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
        "frozen_request_order_contract": "DETERMINISTIC_NATIVE_ENQUEUE_ORDER",
        "history_predecessor_contract": "FROZEN_REPLAY_TIMELINE",
        "eligibility_is_arm_independent": not issues,
        "c_used_as_eligibility_fallback": False,
        "ownership_level_attribution": "NOT_ESTABLISHED",
        "issues": issues,
        "arms": arm_reports,
    }
