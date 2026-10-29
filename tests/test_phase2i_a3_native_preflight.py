import copy

from kvopt.workload.phase2i_a3_preflight import evaluate_a3_native_preflight
from scripts.spikes.phase2_minimal_observability_metal import (
    _phase2i_a3_campaign_allowed,
)


def _events() -> list[dict[str, object]]:
    decision_id = "native-entry-release-1"
    boundary_id = "pressure:round-40"
    request_id = "pressure-request-1"
    stage_id = "round-40"
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
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
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
                            }
                        ],
                    }
                ],
            },
        },
        {
            "event_type": "FORCED_RELEASE_DECISION_BINDING",
            "payload": {
                "decision_id": decision_id,
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
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
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
                "selected_native_block_ids": [3, 4],
            },
        },
        {
            "event_type": "NATIVE_SELECTION_PLAN_PENDING",
            "payload": {
                "decision_id": decision_id,
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
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
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
                "block_id": 3,
                "native_cache_key_before": "content-3",
                "physical_attribution": "MATCHED_PENDING_SELECTION_PLAN",
            },
        },
        {
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "decision_id": decision_id,
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "pressure_request_id": request_id,
                "block_id": 4,
                "native_cache_key_before": "content-4",
                "physical_attribution": "MATCHED_PENDING_SELECTION_PLAN",
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
    ]


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


def test_gate_d_rejects_a3_choice_not_committed_as_actual_release() -> None:
    events = copy.deepcopy(_events())
    events[0]["payload"]["selected_releases"][0]["program_id"] = "program-b"

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
    events[7]["payload"]["bound_forced_release_count"] = 0

    result = evaluate_a3_native_preflight(events)

    assert result["gates"]["O"]["status"] == "FAIL"


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
