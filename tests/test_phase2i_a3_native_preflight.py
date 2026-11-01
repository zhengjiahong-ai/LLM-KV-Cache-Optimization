import copy

from kvopt.workload.phase2i_a3_preflight import evaluate_a3_native_preflight
from scripts.spikes.phase2_minimal_observability_metal import (
    _phase2i_a3_campaign_allowed,
)


def _events() -> list[dict[str, object]]:
    decision_id = "native-entry-release-1"
    boundary_id = "pressure:after-round-40"
    request_id = "pressure-request-1"
    stage_id = "round-40"
    context_id = f"controlled-pressure:{request_id}"
    context = {
        "execution_context_id": context_id,
        "boundary_type": "CONTROLLED_PRESSURE",
        "request_ids": [request_id],
        "boundary_id": boundary_id,
        "stage_id": stage_id,
        "pressure_request_id": request_id,
    }
    return [
        {
            "event_index": 10,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "required_blocks": 2,
                "selected_releases": [
                    {"program_id": "program-a", "prefix_id": "prefix-a"}
                ],
            },
        },
        {
            "event_type": "A3_SUFFIX_RELEASE_DECISION",
            "payload": {
                "decision_id": decision_id,
                **context,
                "verification_mode": "native_live",
                "native_hash_process_id": "123",
                "decision_event_index": 10,
                "decision_clock_domain": "continuum_pressure",
                "selection_trace": [
                    {
                        "key": ["program-a", "prefix-a"],
                        "a1_key": ["program-b", "prefix-b"],
                        "fell_back": False,
                        "audits": [
                            {
                                "reuse_proxy": 0.25,
                                "prefill_reload_seconds": 2.0,
                                "suffix_blocks": 4,
                                "chain_length": 8,
                                "score": 0.25,
                                "content_verified": True,
                            },
                            {
                                "reuse_proxy": 0.5,
                                "prefill_reload_seconds": 1.0,
                                "suffix_blocks": 2,
                                "chain_length": 4,
                                "score": 0.25,
                                "content_verified": True,
                            },
                        ],
                    }
                ],
            },
        },
        {
            "event_type": "FORCED_RELEASE_DECISION_BINDING",
            "payload": {
                "decision_id": decision_id,
                **context,
                "forced_release_counter_before": 0,
                "forced_release_counter_after": 1,
                "forced_release_event_index": 10,
                "selected_release_count": 1,
            },
        },
        {
            "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
            "payload": {
                "decision_id": decision_id,
                **context,
                "selected_native_block_ids": [3, 4],
            },
        },
        {
            "event_type": "NATIVE_SELECTION_PLAN_PENDING",
            "payload": {
                "decision_id": decision_id,
                **context,
                "selected_block_ids": [3, 4],
                "content_identity_by_block": [
                    {"block_id": 3, "native_cache_key": "content-3"},
                    {"block_id": 4, "native_cache_key": "content-4"},
                ],
            },
        },
        {
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "decision_id": decision_id,
                **context,
                "block_id": 3,
                "native_cache_key_before": "content-3",
                "physical_attribution": "MATCHED_PENDING_SELECTION_PLAN",
            },
        },
        {
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "decision_id": decision_id,
                **context,
                "block_id": 4,
                "native_cache_key_before": "content-4",
                "physical_attribution": "MATCHED_PENDING_SELECTION_PLAN",
            },
        },
        {
            "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            "payload": {
                "decision_id": decision_id,
                **context,
                "status": "PHYSICAL_EVICTION_OBSERVED",
                "reason": "ALL_HASHED_SELECTION_PLAN_BLOCKS_MATCHED",
                "matched_block_ids": [3, 4],
                "unmatched_block_ids": [],
            },
        },
        {
            "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
            "payload": {
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "bound_decision_count": 1,
                "bound_forced_release_count": 1,
                "bound_decision_ids": [decision_id],
            },
        },
        {
            "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
            "payload": {
                "boundary_id": "pressure:after-round-50",
                "stage_id": "round-50",
                "bound_decision_count": 0,
                "bound_forced_release_count": 0,
                "bound_decision_ids": [],
            },
        },
        {
            "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
            "payload": {
                "boundary_id": "pressure:after-round-55",
                "stage_id": "round-55",
                "bound_decision_count": 0,
                "bound_forced_release_count": 0,
                "bound_decision_ids": [],
            },
        },
    ]


def _real_failure_shape_events() -> list[dict[str, object]]:
    """Replay the persisted 123/153/188 lifecycle shape without block dumps."""
    rows: list[dict[str, object]] = []
    decisions = (
        (
            "native-entry-release-123",
            2288,
            0,
            "CONTROLLED_PRESSURE",
            "controlled-pressure:pressure-40",
            ["pressure-40"],
            "pressure:after-round-40",
            "round-40",
            "pressure-40",
            False,
        ),
        (
            "native-entry-release-153",
            4537,
            1,
            "NATIVE_DRAIN_BATCH",
            "native-drain-batch:request-a|request-b",
            ["request-a", "request-b"],
            None,
            None,
            None,
            False,
        ),
        (
            "native-entry-release-188",
            10583,
            2,
            "NATIVE_DRAIN_BATCH",
            "native-drain-batch:request-c|request-d",
            ["request-c", "request-d"],
            None,
            None,
            None,
            True,
        ),
    )
    for (
        decision_id,
        event_index,
        counter_before,
        boundary_type,
        context_id,
        request_ids,
        boundary_id,
        stage_id,
        pressure_request_id,
        fell_back,
    ) in decisions:
        context = {
            "execution_context_id": context_id,
            "boundary_type": boundary_type,
            "request_ids": request_ids,
        }
        if boundary_id is not None:
            context.update(
                {
                    "boundary_id": boundary_id,
                    "stage_id": stage_id,
                    "pressure_request_id": pressure_request_id,
                }
            )
        selected = {
            "program_id": "program-b" if fell_back else "program-a",
            "prefix_id": "prefix-b" if fell_back else "prefix-a",
        }
        rows.extend(
            (
                {
                    "event_index": event_index,
                    "event_type": "FORCED_RELEASE_DECISION",
                    "payload": {"selected_releases": [selected]},
                },
                {
                    "event_type": "A3_SUFFIX_RELEASE_DECISION",
                    "payload": {
                        "decision_id": decision_id,
                        **context,
                        "verification_mode": "native_live",
                        "native_hash_process_id": "123",
                        "decision_event_index": event_index,
                        "decision_clock_domain": "continuum_pressure",
                        "selection_trace": [
                            {
                                "key": (
                                    ["program-b", "prefix-b"]
                                    if fell_back
                                    else ["program-a", "prefix-a"]
                                ),
                                "a1_key": ["program-b", "prefix-b"],
                                "fell_back": fell_back,
                                "audits": (
                                    []
                                    if fell_back
                                    else [
                                        {
                                            "reuse_proxy": 0.25,
                                            "prefill_reload_seconds": 2.0,
                                            "suffix_blocks": 4,
                                            "chain_length": 8,
                                            "score": 0.25,
                                            "content_verified": True,
                                        },
                                        {
                                            "reuse_proxy": 0.5,
                                            "prefill_reload_seconds": 1.0,
                                            "suffix_blocks": 2,
                                            "chain_length": 4,
                                            "score": 0.25,
                                            "content_verified": True,
                                        },
                                    ]
                                ),
                            }
                        ],
                    },
                },
                {
                    "event_type": "FORCED_RELEASE_DECISION_BINDING",
                    "payload": {
                        "decision_id": decision_id,
                        **context,
                        "forced_release_counter_before": counter_before,
                        "forced_release_counter_after": counter_before + 1,
                        "forced_release_event_index": event_index,
                        "selected_release_count": 1,
                    },
                },
                {
                    "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
                    "payload": {
                        "decision_id": decision_id,
                        **context,
                        "selected_native_block_ids": [3, 4],
                    },
                },
                {
                    "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
                    "payload": {
                        "decision_id": decision_id,
                        **context,
                        "status": "NO_PHYSICAL_EVICTION_OBSERVED",
                        "reason": "NATIVE_SELECTION_RETURN_CONTAINED_NO_HASHED_BLOCKS",
                        "matched_block_ids": [],
                        "unmatched_block_ids": [],
                    },
                },
            )
        )
    rows.extend(
        (
            {
                "event_type": "NATIVE_ALLOCATION_ATTEMPT",
                "payload": {
                    "decision_id": "native-entry-release-124",
                    "execution_context_id": "controlled-pressure:pressure-40",
                    "boundary_type": "CONTROLLED_PRESSURE",
                    "request_ids": ["pressure-40"],
                },
            },
            {
                "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
                "payload": {
                    "boundary_id": "pressure:after-round-40",
                    "stage_id": "round-40",
                    "bound_decision_count": 1,
                    "bound_forced_release_count": 1,
                    "bound_decision_ids": ["native-entry-release-123"],
                },
            },
            {
                "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
                "payload": {
                    "boundary_id": "pressure:after-round-50",
                    "stage_id": "round-50",
                    "bound_decision_count": 0,
                    "bound_forced_release_count": 0,
                    "bound_decision_ids": [],
                },
            },
            {
                "event_type": "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
                "payload": {
                    "boundary_id": "pressure:after-round-55",
                    "stage_id": "round-55",
                    "bound_decision_count": 0,
                    "bound_forced_release_count": 0,
                    "bound_decision_ids": [],
                },
            },
        )
    )
    return rows


def test_static_preflight_passes_only_with_recomputable_intervention_and_joins() -> None:
    result = evaluate_a3_native_preflight(_events())

    assert result["status"] == "PASS_STATIC_PREFLIGHT"
    assert all(gate["status"] == "PASS" for gate in result["gates"].values())


def test_gate_c_fails_closed_on_score_tamper() -> None:
    events = copy.deepcopy(_events())
    events[1]["payload"]["selection_trace"][0]["audits"][0]["score"] = 99.0

    result = evaluate_a3_native_preflight(events)

    assert result["status"] == "FAIL_CLOSED"
    assert result["gates"]["C"]["status"] == "FAIL"
    assert result["gates"]["D"]["status"] == "FAIL"


def test_gate_c_rejects_nonfallback_selection_with_empty_audits() -> None:
    events = copy.deepcopy(_events())
    events[1]["payload"]["selection_trace"][0]["audits"] = []

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["C"]["status"] == "FAIL"


def test_gate_d_rejects_a3_choice_not_committed_as_actual_release() -> None:
    events = copy.deepcopy(_events())
    events[0]["payload"]["selected_releases"][0]["program_id"] = "program-b"

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["D"]["status"] == "FAIL"


def test_gate_d_requires_exact_entry_set_not_subset() -> None:
    events = copy.deepcopy(_events())
    events[0]["payload"]["selected_releases"].append(
        {"program_id": "program-extra", "prefix_id": "prefix-extra"}
    )
    events[2]["payload"]["selected_release_count"] = 2

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["D"]["status"] == "FAIL"


def test_native_gate_d_accepts_nonfallback_multi_candidate_same_choice() -> None:
    events = copy.deepcopy(_events())
    selection = events[1]["payload"]["selection_trace"][0]
    selection["a1_key"] = selection["key"]
    selection["audits"].append(
        {
            "reuse_proxy": 0.5,
            "prefill_reload_seconds": 1.0,
            "suffix_blocks": 2,
            "chain_length": 4,
            "score": 0.25,
            "content_verified": True,
        }
    )

    static_result = evaluate_a3_native_preflight(events)
    native_result = evaluate_a3_native_preflight(
        events, require_a1_a3_intervention=False
    )

    assert static_result["gates"]["D"]["status"] == "FAIL"
    assert native_result["gates"]["D"]["status"] == "PASS"
    assert native_result["gates"]["D"]["multi_candidate_decision_count"] == 1


def test_gate_o_rejects_stale_or_unbound_pressure_selection() -> None:
    events = copy.deepcopy(_events())
    events[3]["payload"]["pressure_request_id"] = "another-request"

    result = evaluate_a3_native_preflight(events)

    assert result["status"] == "FAIL_CLOSED"
    assert result["gates"]["O"]["status"] == "FAIL"


def test_gate_o_rejects_pressure_counter_chain_anomaly() -> None:
    events = copy.deepcopy(_events())
    events[8]["payload"]["bound_forced_release_count"] = 0

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["O"]["status"] == "FAIL"


def test_gate_o_rejects_unknown_barrier_decision_without_crashing() -> None:
    events = copy.deepcopy(_events())
    events[8]["payload"]["bound_decision_ids"].append("native-entry-release-122")
    events[8]["payload"]["bound_decision_count"] = 2

    result = evaluate_a3_native_preflight(events)

    assert result["status"] == "FAIL_CLOSED"
    assert result["gates"]["O"]["status"] == "FAIL"
    assert result["gates"]["O"]["barrier_binding_valid"] is False


def test_real_123_153_188_shape_separates_decision_from_physical_outcome() -> None:
    result = evaluate_a3_native_preflight(
        _real_failure_shape_events(), require_a1_a3_intervention=False
    )

    assert result["gates"]["I"]["status"] == "PASS"
    assert result["gates"]["C"]["status"] == "PASS"
    assert result["gates"]["D"]["status"] == "PASS"
    assert result["gates"]["O"]["status"] == "FAIL"
    assert result["gates"]["O"]["no_physical_eviction_decision_count"] == 3


def test_gate_d_rejects_fallback_that_does_not_select_a1_key() -> None:
    events = _real_failure_shape_events()
    fallback = next(
        event
        for event in events
        if event.get("event_type") == "A3_SUFFIX_RELEASE_DECISION"
        and event.get("payload", {}).get("decision_id") == "native-entry-release-188"
    )
    fallback["payload"]["selection_trace"][0]["key"] = ["program-a", "prefix-a"]

    result = evaluate_a3_native_preflight(
        events, require_a1_a3_intervention=False
    )

    assert result["gates"]["D"]["status"] == "FAIL"
    assert result["gates"]["D"]["fallback_selection_valid"] is False


def test_gate_d_rejects_fallback_release_not_equal_to_a1_key() -> None:
    events = _real_failure_shape_events()
    forced = next(
        event
        for event in events
        if event.get("event_index") == 10583
    )
    forced["payload"]["selected_releases"] = [
        {"program_id": "program-a", "prefix_id": "prefix-a"}
    ]

    result = evaluate_a3_native_preflight(
        events, require_a1_a3_intervention=False
    )

    assert result["gates"]["D"]["status"] == "FAIL"


def test_gate_o_requires_each_frozen_barrier_once() -> None:
    events = copy.deepcopy(_events())
    events.pop()

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["O"]["status"] == "FAIL"
    assert result["gates"]["O"]["barrier_binding_valid"] is False


def test_gate_o_rejects_unknown_or_incomplete_physical_outcome() -> None:
    unknown = copy.deepcopy(_events())
    unknown[7]["payload"]["status"] = "MADE_UP"
    assert evaluate_a3_native_preflight(unknown)["gates"]["O"]["status"] == "FAIL"

    incomplete = copy.deepcopy(_events())
    incomplete[7]["payload"]["matched_block_ids"] = [3]
    assert (
        evaluate_a3_native_preflight(incomplete)["gates"]["O"]["status"]
        == "FAIL"
    )


def test_gate_o_rejects_no_counter_increment_for_forced_release() -> None:
    events = copy.deepcopy(_events())
    events[2]["payload"]["forced_release_counter_before"] = 2
    events[2]["payload"]["forced_release_counter_after"] = 2

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["O"]["status"] == "FAIL"


def test_gate_o_rejects_physical_block_outside_native_selection_plan() -> None:
    events = copy.deepcopy(_events())
    events[3]["payload"]["selected_native_block_ids"] = [99, 4]

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["O"]["status"] == "FAIL"


def test_gate_i_rejects_historical_mode_in_native_path() -> None:
    events = copy.deepcopy(_events())
    events[1]["payload"]["verification_mode"] = "historical_replay"

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["I"]["status"] == "FAIL"


def test_a3_campaign_allowlist_is_exact_and_does_not_expand_a1_or_a2() -> None:
    assert _phase2i_a3_campaign_allowed("phase2i_a3_native_integration") is True
    assert _phase2i_a3_campaign_allowed("phase2i_a3_native_integration_extra") is False
    assert _phase2i_a3_campaign_allowed("phase2h_history_rich_native_smoke") is False
