from __future__ import annotations

from copy import deepcopy

from kvopt.profiling.phase3_nec import (
    evaluate_phase3_nec_cell as _evaluate_phase3_nec_cell,
)

ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")
HASH_A = "01" * 32
HASH_B = "02" * 32
HASH_C = "03" * 32
HASH_D = "04" * 32
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
    native_enqueue_order: tuple[tuple[str, str], ...] | None = None,
    history_predecessors: dict[
        tuple[str, str], tuple[tuple[str, str], ...]
    ]
    | None = None,
) -> dict:
    if history_predecessors is None:
        history_predecessors = {
            identity: tuple(frozen_requests[:index])
            for index, identity in enumerate(frozen_requests)
        }
    return _evaluate_phase3_nec_cell(
        events_by_arm=events_by_arm,
        frozen_requests=frozen_requests,
        native_enqueue_order=(
            frozen_requests
            if native_enqueue_order is None
            else native_enqueue_order
        ),
        history_predecessors=history_predecessors,
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


def _observation(
    index: int,
    request: str,
    *,
    prompt: int,
    cached: int,
    queued: float | None = None,
    scheduled: float | None = None,
    first_token: float | None = None,
) -> dict:
    event = _event(
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
            "native_queued_timestamp": (
                float(index) if queued is None else queued
            ),
            "native_scheduler_admission_timestamp": (
                float(index) + 0.1 if scheduled is None else scheduled
            ),
            "native_first_token_timestamp": (
                float(index) + 0.8 if first_token is None else first_token
            ),
        },
    )
    event["clock_domain"] = "engine_core_monotonic"
    return event


def _snapshot(
    index: int,
    *,
    request: str = "request-1",
    hashes: list[str] | None = None,
    block_ids: list[int] | None = None,
) -> dict:
    snapshot_hashes = [HASH_A, HASH_B] if hashes is None else hashes
    return _event(
        index,
        "VLLM_PREFIX_SNAPSHOT",
        request,
        {
            "ordered_native_hashes": snapshot_hashes,
            "hash_num_tokens": len(snapshot_hashes) * 16,
            "block_ids": [10, 11] if block_ids is None else block_ids,
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
    assert any("history predecessor" in issue for issue in report["issues"])


def test_first_enqueued_request_without_prior_history_has_zero_e() -> None:
    first_request_events = {
        arm: [_observation(1, "request-1", prompt=32, cached=0)]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=first_request_events,
        frozen_requests=(REQUESTS[0],),
    )

    assert report["status"] == "PASS"
    assert report["frozen_request_order_contract"] == (
        "DETERMINISTIC_NATIVE_ENQUEUE_ORDER"
    )
    for arm in ARMS:
        request = report["arms"][arm]["requests"][0]
        assert request["eligible_prefix_tokens"] == 0
        assert request["native_cached_prefix_tokens"] == 0
        assert request["eligibility_source"] == (
            "FROZEN_HISTORY_NO_PRIOR_ELIGIBLE_CONTENT"
        )


def test_same_drain_uses_independently_proven_physical_predecessor() -> None:
    cell: dict[str, list[dict]] = {}
    for arm in ARMS:
        cell[arm] = [
            _observation(
                1,
                "request-1",
                prompt=32,
                cached=0,
                first_token=3.0,
            ),
            _observation(
                2,
                "request-2",
                prompt=48,
                cached=0,
                scheduled=2.1,
            ),
            # The first Snapshot is written only after both requests in this
            # Native drain were already enqueued/observed.
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "PASS"
    for arm in ARMS:
        assert [
            request["eligible_prefix_tokens"]
            for request in report["arms"][arm]["requests"]
        ] == [0, 32]


def test_same_batch_shared_predecessor_is_eligible() -> None:
    cell: dict[str, list[dict]] = {}
    for arm in ARMS:
        cell[arm] = [
            _observation(
                1,
                "request-1",
                prompt=32,
                cached=0,
                queued=1.0,
                scheduled=1.5,
                first_token=1.8,
            ),
            _observation(
                2,
                "request-2",
                prompt=48,
                cached=32,
                queued=1.2,
                scheduled=1.5,
                first_token=2.8,
            ),
            # Content identity may be persisted after the consumer observation;
            # first-token/scheduler timing independently proves visibility.
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "PASS"
    for arm in ARMS:
        consumer = report["arms"][arm]["requests"][1]
        assert consumer["eligible_prefix_tokens"] == 32
        audit = consumer["concurrent_eligibility_audits"][0]
        assert audit["hash_lcp_blocks"] == 2
        assert audit["snapshot_may_follow_consumer_observation"] is True
        assert audit["uses_native_cached_tokens_c"] is False
        assert audit["scheduler_relation"] == "SAME_SCHEDULER_ITERATION"
        assert audit["physical_prefix_block_ids_equal"] is True
        assert audit["qualification_result"] == (
            "QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR"
        )


def test_same_batch_eligibility_does_not_use_c_or_first_token_order() -> None:
    def cell(second_cached: int, producer_first_token: float) -> dict[str, list[dict]]:
        return {
            arm: [
                _observation(
                    1,
                    "request-1",
                    prompt=32,
                    cached=0,
                    queued=1.0,
                    scheduled=1.5,
                    first_token=producer_first_token,
                ),
                _observation(
                    2,
                    "request-2",
                    prompt=48,
                    cached=second_cached,
                    queued=1.2,
                    scheduled=1.5,
                ),
                _snapshot(3),
                _snapshot(
                    4,
                    request="request-2",
                    hashes=[HASH_A, HASH_B, HASH_C],
                    block_ids=[10, 11, 12],
                ),
            ]
            for arm in ARMS
        }

    visible_zero_c = evaluate_phase3_nec_cell(
        events_by_arm=cell(0, 1.8),
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )
    later_first_token = evaluate_phase3_nec_cell(
        events_by_arm=cell(0, 3.0),
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )
    visible_full_c = evaluate_phase3_nec_cell(
        events_by_arm=cell(32, 1.8),
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert visible_zero_c["status"] == "PASS"
    assert visible_full_c["status"] == "PASS"
    assert later_first_token["status"] == "PASS"
    assert visible_zero_c["arms"]["A0"]["requests"][1][
        "eligible_prefix_tokens"
    ] == 32
    assert visible_full_c["arms"]["A0"]["requests"][1][
        "eligible_prefix_tokens"
    ] == 32
    assert later_first_token["arms"]["A0"]["requests"][1][
        "eligible_prefix_tokens"
    ] == 32


def test_earlier_uniproc_forward_shared_predecessor_is_eligible() -> None:
    cell = {
        arm: [
            _observation(
                1,
                "request-1",
                prompt=32,
                cached=0,
                scheduled=1.1,
                first_token=3.0,
            ),
            _observation(
                2,
                "request-2",
                prompt=48,
                cached=32,
                scheduled=2.1,
            ),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "PASS"
    audit = report["arms"]["A0"]["requests"][1][
        "concurrent_eligibility_audits"
    ][0]
    assert audit["scheduler_relation"] == "EARLIER_SCHEDULER_ITERATION"
    assert audit["qualification_result"] == (
        "QUALIFIED_EARLIER_FORWARD_SHARED_PREDECESSOR"
    )


def test_historical_and_same_batch_predecessors_are_combined() -> None:
    requests = (*REQUESTS, ("program-a", "request-3"))
    cell = {
        arm: [
            _observation(1, "request-1", prompt=32, cached=0, scheduled=1.1),
            _snapshot(2, hashes=[HASH_A], block_ids=[10]),
            _observation(
                3,
                "request-2",
                prompt=32,
                cached=0,
                queued=2.0,
                scheduled=2.5,
            ),
            _observation(
                4,
                "request-3",
                prompt=48,
                cached=32,
                queued=2.1,
                scheduled=2.5,
            ),
            _snapshot(5, request="request-2", block_ids=[10, 11]),
            _snapshot(
                6,
                request="request-3",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=requests,
        history_predecessors={
            requests[0]: (),
            requests[1]: (requests[0],),
            requests[2]: (requests[0],),
        },
    )

    assert report["status"] == "PASS"
    for arm in ARMS:
        request = report["arms"][arm]["requests"][2]
        assert request["eligible_prefix_tokens"] == 32
        assert request["native_cached_prefix_tokens"] == 32
        assert request["concurrent_eligibility_audits"][0][
            "qualification_result"
        ] == "QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR"


def test_consumer_lookup_before_producer_registration_fails_closed() -> None:
    cell = {
        arm: [
            _observation(1, "request-1", prompt=32, cached=0, scheduled=2.2),
            _observation(2, "request-2", prompt=48, cached=0, scheduled=2.1),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("scheduled after the consumer" in issue for issue in report["issues"])


def test_shared_hashes_with_partial_physical_block_evidence_fail_closed() -> None:
    cell = {
        arm: [
            _observation(
                1, "request-1", prompt=32, cached=0, queued=1.0, scheduled=1.5
            ),
            _observation(
                2, "request-2", prompt=48, cached=0, queued=1.2, scheduled=1.5
            ),
            _snapshot(3, block_ids=[10]),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("physical Block evidence" in issue for issue in report["issues"])


def test_allocated_producer_without_forward_evidence_fails_closed() -> None:
    cell = {
        arm: [
            _observation(
                1, "request-1", prompt=32, cached=0, queued=1.0, scheduled=1.5
            ),
            _observation(
                2, "request-2", prompt=48, cached=0, queued=1.2, scheduled=1.5
            ),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }
    for events in cell.values():
        events[0]["payload"]["native_first_token_timestamp"] = None

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("first_token" in issue for issue in report["issues"])


def test_concurrent_cached_tokens_c_cannot_exceed_independent_e() -> None:
    cell = {
        arm: [
            _observation(1, "request-1", prompt=32, cached=0, first_token=1.8),
            _observation(2, "request-2", prompt=48, cached=48, scheduled=2.1),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("0 <= C <= E <= N" in issue for issue in report["issues"])


def test_concurrent_no_shared_blocks_is_legitimate_zero_e() -> None:
    cell = {
        arm: [
            _observation(1, "request-1", prompt=32, cached=0, first_token=1.8),
            _observation(2, "request-2", prompt=48, cached=0, scheduled=2.1),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[20, 21, 22],
            ),
        ]
        for arm in ARMS
    }
    for events in cell.values():
        events[0]["payload"]["native_apc_block_hashes"] = [HASH_D, HASH_D]
        events[-2]["payload"]["ordered_native_hashes"] = [HASH_D, HASH_D]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "PASS"
    assert report["arms"]["A0"]["requests"][1]["eligible_prefix_tokens"] == 0


def test_concurrent_hash_identity_mismatch_fails_closed() -> None:
    cell = {
        arm: [
            _observation(1, "request-1", prompt=32, cached=0, first_token=1.8),
            _observation(2, "request-2", prompt=48, cached=0, scheduled=2.1),
            _snapshot(3),
            _snapshot(
                4,
                request="request-2",
                hashes=[HASH_A, HASH_B, HASH_C],
                block_ids=[10, 11, 12],
            ),
        ]
        for arm in ARMS
    }
    cell["A0"][-1]["payload"]["native_hash_process_id"] = "other-process"

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell,
        frozen_requests=REQUESTS,
        history_predecessors={REQUESTS[0]: (), REQUESTS[1]: ()},
    )

    assert report["status"] == "FAIL_CLOSED"
    assert any("incompatible Native hash identity" in issue for issue in report["issues"])


def test_completed_history_predecessor_supplies_snapshot_evidence() -> None:
    report = evaluate_phase3_nec_cell(
        events_by_arm=_cell(),
        frozen_requests=REQUESTS,
        history_predecessors={
            REQUESTS[0]: (),
            REQUESTS[1]: (REQUESTS[0],),
        },
    )

    assert report["status"] == "PASS"
    assert all(
        report["arms"][arm]["requests"][1]["eligible_prefix_tokens"] == 32
        for arm in ARMS
    )


def test_zero_c_does_not_hide_missing_prior_history() -> None:
    cell = _cell(second_cached=0)
    for events in cell.values():
        events[:] = [
            event
            for event in events
            if event["event_type"] != "VLLM_PREFIX_SNAPSHOT"
        ]

    report = evaluate_phase3_nec_cell(
        events_by_arm=cell, frozen_requests=REQUESTS
    )

    assert report["status"] == "FAIL_CLOSED"
    assert report["c_used_as_eligibility_fallback"] is False
    assert any("history predecessor" in issue for issue in report["issues"])


def test_enqueue_order_and_history_predecessors_are_frozen_contracts() -> None:
    enqueue_mismatch = evaluate_phase3_nec_cell(
        events_by_arm=_cell(),
        frozen_requests=REQUESTS,
        native_enqueue_order=tuple(reversed(REQUESTS)),
    )
    predecessor_mismatch = evaluate_phase3_nec_cell(
        events_by_arm=_cell(),
        frozen_requests=REQUESTS,
        history_predecessors={
            REQUESTS[0]: (REQUESTS[1],),
            REQUESTS[1]: (),
        },
    )

    assert enqueue_mismatch["status"] == "FAIL_CLOSED"
    assert predecessor_mismatch["status"] == "FAIL_CLOSED"
    assert any("enqueue order" in issue for issue in enqueue_mismatch["issues"])
    assert any(
        "invalid history predecessors" in issue
        for issue in predecessor_mismatch["issues"]
    )


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
