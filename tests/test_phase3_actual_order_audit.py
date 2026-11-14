from __future__ import annotations

from copy import deepcopy

from kvopt.profiling.phase3_actual_order_audit import (
    ARMS,
    audit_arm_actual_order,
    classify_observed_sequences,
)

HASH_A = "01" * 32
HASH_B = "02" * 32
HASH_C = "03" * 32
REQUESTS = (("program-a", "request-1"), ("program-a", "request-2"))


def _event(index: int, kind: str, request_id: str, payload: dict) -> dict:
    return {
        "event_index": index,
        "event_type": kind,
        "program_id": "program-a",
        "request_id": request_id,
        "payload": payload,
    }


def _submission(index: int, request_id: str) -> dict:
    return _event(index, "VLLM_REQUEST_SUBMITTED", request_id, {})


def _observation(
    index: int, request_id: str, prompt: int, cached: int, scheduled: float
) -> dict:
    row = _event(
        index,
        "VLLM_NATIVE_REQUEST_OBSERVATION",
        request_id,
        {
            "native_prompt_tokens": prompt,
            "native_cached_prefix_tokens": cached,
            "native_apc_block_hashes": [HASH_A, HASH_B, HASH_C][:(prompt // 16)],
            "native_hash_block_size": 16,
            "native_hash_process_id": "native-1",
            "native_hash_function": "sha256",
            "native_queued_timestamp": scheduled - 0.1,
            "native_scheduler_admission_timestamp": scheduled,
            "native_first_token_timestamp": scheduled + 0.5,
        },
    )
    row["clock_domain"] = "engine_core_monotonic"
    return row


def _snapshot(index: int, request_id: str, blocks: list[int]) -> dict:
    hashes = [HASH_A, HASH_B, HASH_C][: len(blocks)]
    return _event(
        index,
        "VLLM_PREFIX_SNAPSHOT",
        request_id,
        {
            "ordered_native_hashes": hashes,
            "hash_num_tokens": len(hashes) * 16,
            "block_ids": blocks,
            "native_hash_block_size": 16,
            "native_hash_process_id": "native-1",
            "native_hash_function": "sha256",
        },
    )


def _frozen() -> list[dict]:
    return [
        {"request_id": "request-1", "eligible_prefix_tokens": 0},
        {"request_id": "request-2", "eligible_prefix_tokens": 32},
    ]


def test_six_arms_can_share_one_nonfrozen_actual_order() -> None:
    frozen = ("request-1", "request-2")
    sequences = {arm: ("request-2", "request-1") for arm in ARMS}
    assert classify_observed_sequences(sequences, frozen) == (
        "CROSS_ARM_IDENTICAL_BUT_FROZEN_MISMATCH"
    )


def test_cross_arm_actual_order_difference_is_detected() -> None:
    frozen = ("request-1", "request-2")
    sequences = {arm: frozen for arm in ARMS}
    sequences["A3"] = tuple(reversed(frozen))
    assert classify_observed_sequences(sequences, frozen) == "CROSS_ARM_DIFFERENT"


def test_snapshot_visible_before_consumer_submission_proves_e() -> None:
    events = [
        _submission(1, "request-1"),
        _observation(2, "request-1", 32, 0, 1.0),
        _snapshot(3, "request-1", [10, 11]),
        _submission(4, "request-2"),
        _observation(5, "request-2", 48, 32, 2.0),
    ]
    report = audit_arm_actual_order(
        arm="A0",
        events=events,
        frozen_requests=REQUESTS,
        frozen_request_results=_frozen(),
    )
    assert report["status"] == "PASS"
    assert report["requests"][1]["actual_eligible_prefix_tokens"] == 32
    assert report["requests"][1]["visibility_audits"][0]["qualification"] == (
        "SNAPSHOT_VISIBLE_BEFORE_CONSUMER_SUBMISSION"
    )


def test_snapshot_after_consumer_uses_same_batch_physical_proof() -> None:
    events = [
        _submission(1, "request-1"),
        _observation(2, "request-1", 32, 0, 1.0),
        _submission(3, "request-2"),
        _observation(4, "request-2", 48, 32, 1.0),
        _snapshot(5, "request-1", [10, 11]),
        _snapshot(6, "request-2", [10, 11, 12]),
    ]
    report = audit_arm_actual_order(
        arm="A0",
        events=events,
        frozen_requests=REQUESTS,
        frozen_request_results=_frozen(),
    )
    assert report["status"] == "PASS"
    audit = report["requests"][1]["visibility_audits"][0]
    assert audit["scheduler_relation"] == "SAME_SCHEDULER_ITERATION"
    assert audit["physical_prefix_block_ids_equal"] is True


def test_snapshot_after_consumer_without_physical_proof_is_indeterminate() -> None:
    events = [
        _submission(1, "request-1"),
        _observation(2, "request-1", 32, 0, 1.0),
        _submission(3, "request-2"),
        _observation(4, "request-2", 48, 32, 1.0),
        _snapshot(5, "request-1", [10, 11]),
    ]
    report = audit_arm_actual_order(
        arm="A0",
        events=events,
        frozen_requests=REQUESTS,
        frozen_request_results=_frozen(),
    )
    assert report["status"] == "INDETERMINATE"
    assert report["requests"][1]["actual_eligible_prefix_tokens"] is None


def test_missing_visibility_snapshot_fails_closed_as_indeterminate() -> None:
    events = [
        _submission(1, "request-1"),
        _observation(2, "request-1", 32, 0, 1.0),
        _submission(3, "request-2"),
        _observation(4, "request-2", 48, 0, 1.0),
    ]
    report = audit_arm_actual_order(
        arm="A0",
        events=deepcopy(events),
        frozen_requests=REQUESTS,
        frozen_request_results=_frozen(),
    )
    assert report["status"] == "INDETERMINATE"
    assert report["requests"][1]["actual_eligible_prefix_tokens"] is None
    assert report["requests"][1]["indeterminate_reasons"]
