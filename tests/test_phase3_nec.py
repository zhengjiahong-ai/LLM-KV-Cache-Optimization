from __future__ import annotations

from copy import deepcopy

from kvopt.profiling.phase3_nec import (
    evaluate_phase3_nec_cell as _evaluate_phase3_nec_cell,
)

ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")
HASH_A = "01" * 32
HASH_B = "02" * 32
HASH_C = "03" * 32
REQUESTS = (("program-a", "request-1"), ("program-a", "request-2"))


def _manifest() -> dict:
    return {
        "schema_version": "phase3.six_arm_cell_manifest.v1",
        "arms": list(ARMS),
        "pressure_request_contract": [
            {
                "boundary_id": "pressure:stage-1",
                "stage_id": "stage-1",
                "request_ids": ["pressure:stage-1:1"],
            }
        ],
    }


def evaluate_phase3_nec_cell(
    *,
    events_by_arm: dict[str, list[dict]],
    frozen_requests: tuple[tuple[str, str], ...],
    cell_manifest: dict | None = None,
) -> dict:
    return _evaluate_phase3_nec_cell(
        events_by_arm=events_by_arm,
        frozen_requests=frozen_requests,
        cell_manifest=_manifest() if cell_manifest is None else cell_manifest,
    )


def _event(index: int, event_type: str, request: str, payload: dict) -> dict:
    return {
        "event_index": index,
        "event_type": event_type,
        "program_id": "program-a",
        "request_id": request,
        "payload": payload,
    }


def _observation(index: int, request: str, *, prompt: int, cached: int) -> dict:
    return _event(
        index,
        "VLLM_NATIVE_REQUEST_OBSERVATION",
        request,
        {
            "native_prompt_tokens": prompt,
            "native_cached_prefix_tokens": cached,
            "native_apc_block_hashes": [HASH_A, HASH_B, HASH_C][
                : (prompt // 16)
            ],
            "native_hash_block_size": 16,
            "native_hash_process_id": "native-1",
            "native_hash_function": "sha256",
        },
    )


def _snapshot(index: int) -> dict:
    return _event(
        index,
        "VLLM_PREFIX_SNAPSHOT",
        "request-1",
        {
            "ordered_native_hashes": [HASH_A, HASH_B],
            "hash_num_tokens": 32,
            "native_hash_block_size": 16,
            "native_hash_process_id": "native-1",
            "native_hash_function": "sha256",
        },
    )


def _completion(index: int, request: str, output_tokens: int) -> dict:
    return _event(
        index,
        "VLLM_REQUEST_COMPLETED",
        request,
        {"output_token_count": output_tokens},
    )


def _events(*, second_cached: int = 16) -> list[dict]:
    return [
        _observation(1, "request-1", prompt=32, cached=0),
        _snapshot(2),
        _observation(3, "request-2", prompt=48, cached=second_cached),
    ]


def _cell(*, second_cached: int = 16) -> dict[str, list[dict]]:
    return {arm: _events(second_cached=second_cached) for arm in ARMS}


def test_nec_primary_metric_and_aggregate_identity() -> None:
    report = evaluate_phase3_nec_cell(
        events_by_arm=_cell(), frozen_requests=REQUESTS
    )

    assert report["status"] == "PASS"
    assert report["c_used_as_eligibility_fallback"] is False
    assert report["ownership_level_attribution"] == "NOT_ESTABLISHED"
    for arm in ARMS:
        result = report["arms"][arm]
        assert result["aggregate_actual_prefill_tokens"] == 64
        assert result["aggregate_recomputed_tokens"] == 16
        assert result["aggregate_new_suffix_tokens"] == 48
        assert result["aggregate_actual_prefill_tokens"] == (
            result["aggregate_recomputed_tokens"]
            + result["aggregate_new_suffix_tokens"]
        )
        assert result["requests"][1]["apc_outcome"] == "PARTIAL_HIT"


def test_missing_history_does_not_fall_back_to_c() -> None:
    cell = _cell()
    cell["A1"] = [event for event in cell["A1"] if event["event_type"] != "VLLM_PREFIX_SNAPSHOT"]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("prior request-history" in issue for issue in report["issues"])


def test_cross_arm_content_identity_drift_fails_closed() -> None:
    cell = _cell(second_cached=0)
    cell["A2"][1]["payload"]["ordered_native_hashes"][0] = "ff" * 32

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("cross-arm N/E mismatch" in issue for issue in report["issues"])


def test_missing_or_duplicate_request_fails_closed() -> None:
    missing = _cell()
    missing["E0"].pop()
    duplicate = _cell()
    duplicate["A3"].append(deepcopy(duplicate["A3"][-1]))
    duplicate["A3"][-1]["event_index"] = 4

    missing_report = evaluate_phase3_nec_cell(
        events_by_arm=missing, frozen_requests=REQUESTS
    )
    duplicate_report = evaluate_phase3_nec_cell(
        events_by_arm=duplicate, frozen_requests=REQUESTS
    )

    assert missing_report["status"] == "FAIL_CLOSED"
    assert duplicate_report["status"] == "FAIL_CLOSED"
    assert any("request set mismatch" in issue for issue in missing_report["issues"])
    assert any("duplicate Native observations" in issue for issue in duplicate_report["issues"])


def test_invalid_ceiling_and_boolean_tokens_fail_closed() -> None:
    too_much_cached = _cell(second_cached=48)
    boolean_n = _cell()
    boolean_n["N0"][0]["payload"]["native_prompt_tokens"] = True

    ceiling_report = evaluate_phase3_nec_cell(
        events_by_arm=too_much_cached, frozen_requests=REQUESTS
    )
    boolean_report = evaluate_phase3_nec_cell(
        events_by_arm=boolean_n, frozen_requests=REQUESTS
    )

    assert ceiling_report["status"] == "FAIL_CLOSED"
    assert boolean_report["status"] == "FAIL_CLOSED"


def test_arm_set_and_frozen_request_set_are_strict() -> None:
    cell = _cell()
    del cell["N0"]
    arm_report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )
    frozen_report = evaluate_phase3_nec_cell(
        events_by_arm=_cell(), frozen_requests=(*REQUESTS, REQUESTS[0])
    )

    assert arm_report["status"] == "FAIL_CLOSED"
    assert frozen_report["status"] == "FAIL_CLOSED"


def test_pressure_native_observations_are_not_effect_requests() -> None:
    cell = _cell()
    for events in cell.values():
        pressure = _observation(4, "pressure:stage-1:1", prompt=16, cached=0)
        pressure["program_id"] = "pressure:stage-1"
        events.append(pressure)

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "PASS"
    assert all(report["arms"][arm]["request_count"] == 2 for arm in ARMS)


def test_unknown_non_pressure_observation_fails_closed() -> None:
    cell = _cell()
    cell["A1"].append(
        _observation(4, "unknown-formal-request", prompt=16, cached=0)
    )

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("unknown non-pressure" in issue for issue in report["issues"])


def test_c_may_vary_while_n_and_e_remain_arm_independent() -> None:
    cell = _cell(second_cached=16)
    cell["A3"][-1]["payload"]["native_cached_prefix_tokens"] = 32

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "PASS"
    assert report["arms"]["A0"]["aggregate_recomputed_tokens"] == 16
    assert report["arms"]["A3"]["aggregate_recomputed_tokens"] == 0
    assert {
        report["arms"][arm]["requests"][1]["eligible_prefix_tokens"]
        for arm in ARMS
    } == {32}


def test_empty_frozen_request_set_fails_closed() -> None:
    report = evaluate_phase3_nec_cell(
        events_by_arm={arm: [] for arm in ARMS}, frozen_requests=()
    )

    assert report["status"] == "FAIL_CLOSED"
    assert "frozen request set must not be empty" in report["issues"]


def test_single_arm_call_fails_closed() -> None:
    report = evaluate_phase3_nec_cell(
        events_by_arm={"A0": _events()}, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("arm set mismatch" in issue for issue in report["issues"])


def test_empty_current_hash_chain_for_multiblock_prompt_fails_closed() -> None:
    cell = _cell()
    cell["A0"][0]["payload"]["native_apc_block_hashes"] = []

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("complete prompt blocks" in issue for issue in report["issues"])


def test_short_current_hash_chain_fails_closed() -> None:
    cell = _cell()
    cell["E0"][-1]["payload"]["native_apc_block_hashes"] = [HASH_A, HASH_B]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("complete prompt blocks" in issue for issue in report["issues"])


def test_empty_snapshot_hash_chain_fails_closed() -> None:
    cell = _cell()
    cell["N0"][1]["payload"]["ordered_native_hashes"] = []
    cell["N0"][1]["payload"]["hash_num_tokens"] = 0

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("must be non-empty" in issue for issue in report["issues"])


def test_snapshot_hash_must_be_sha256_length() -> None:
    cell = _cell()
    cell["A3"][1]["payload"]["ordered_native_hashes"][0] = "ab"

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("64-character" in issue for issue in report["issues"])


def test_one_generated_tail_hash_requires_exact_native_rule() -> None:
    allowed = _cell()
    rejected = _cell()
    for cell, output_tokens in ((allowed, 1), (rejected, 0)):
        for events in cell.values():
            events[0]["payload"]["native_prompt_tokens"] = 15
            events[0]["payload"]["native_apc_block_hashes"] = [HASH_A]
            events[1]["event_index"] = 3
            events[2]["event_index"] = 4
            events.insert(1, _completion(2, "request-1", output_tokens))

    allowed_report = evaluate_phase3_nec_cell(
        events_by_arm=allowed, frozen_requests=REQUESTS
    )
    rejected_report = evaluate_phase3_nec_cell(
        events_by_arm=rejected, frozen_requests=REQUESTS
    )

    assert allowed_report["status"] == "PASS"
    assert rejected_report["status"] == "FAIL_CLOSED"
