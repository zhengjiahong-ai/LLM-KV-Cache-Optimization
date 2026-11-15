from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.profiling.phase5_candidate_exposure import (
    compare_candidate_exposure,
    evaluate_run_candidate_exposure,
)


def _events(selected: str = "program-a", blocks: list[int] | None = None) -> list[dict]:
    selected_blocks = blocks or [10, 11]
    candidates = [
        {
            "program_id": "program-a",
            "prefix_id": "prefix-a",
            "block_ids": [10, 11],
            "initially_reclaimable_block_ids": [10, 11],
            "native_hash_process_id": "native-1",
            "score": 1.0,
        },
        {
            "program_id": "program-b",
            "prefix_id": "prefix-b",
            "block_ids": [20, 21],
            "initially_reclaimable_block_ids": [20],
            "native_hash_process_id": "native-1",
            "score": 2.0,
        },
    ]
    return [
        {
            "event_index": 5,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "candidates": candidates,
                "selected_releases": [{"program_id": selected}],
            },
        },
        {
            "event_index": 6,
            "event_type": "FORCED_RELEASE_DECISION_BINDING",
            "payload": {
                "forced_release_event_index": 5,
                "decision_id": "decision-1",
            },
        },
        {
            "event_index": 7,
            "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
            "payload": {
                "decision_id": "decision-1",
                "selected_native_block_ids": selected_blocks,
            },
        },
        {
            "event_index": 8,
            "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            "payload": {
                "decision_id": "decision-1",
                "matched_physical_block_ids": selected_blocks,
                "unmatched_physical_block_ids": [],
                "hashless_physical_block_ids": [],
            },
        },
        {
            "event_index": 9,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "program_id": "program-b",
            "request_id": "program-b:turn:2",
            "payload": {"native_cached_prefix_tokens": 16},
        },
    ]


def test_candidate_exposure_records_competition_physical_and_reuse_tiers() -> None:
    report = evaluate_run_candidate_exposure(run_id="run-a0", arm="A0", events=_events())
    assert report["status"] == "PASS"
    assert report["multi_candidate_decision_count"] == 1
    decision = report["decisions"][0]
    assert decision["legal_candidate_count"] == 2
    assert decision["scored_candidate_count"] == 2
    assert decision["physical_identity_complete_candidate_count"] == 2
    assert decision["downstream_reuse_opportunity_program_ids"] == ["program-b"]
    assert decision["downstream_recompute_attribution"] == "NOT_ESTABLISHED"


def test_candidate_exposure_fails_closed_on_missing_binding_or_plan() -> None:
    events = _events()
    without_binding = [
        row for row in events if row["event_type"] != "FORCED_RELEASE_DECISION_BINDING"
    ]
    with pytest.raises(ValueError, match="lacks Native binding"):
        evaluate_run_candidate_exposure(
            run_id="invalid", arm="A0", events=without_binding
        )

    without_plan = [
        row
        for row in events
        if row["event_type"] != "NATIVE_ENTRY_RELEASE_SELECTION_PLAN"
    ]
    with pytest.raises(ValueError, match="selection plan or physical outcome"):
        evaluate_run_candidate_exposure(run_id="invalid", arm="A0", events=without_plan)


def test_candidate_exposure_rejects_selection_outside_legal_candidates() -> None:
    with pytest.raises(ValueError, match="outside the legal candidate set"):
        evaluate_run_candidate_exposure(
            run_id="invalid", arm="A0", events=_events(selected="program-x")
        )


def test_cross_arm_comparison_detects_logical_and_physical_divergence() -> None:
    a0 = evaluate_run_candidate_exposure(run_id="a0", arm="A0", events=_events())
    a1 = evaluate_run_candidate_exposure(
        run_id="a1", arm="A1", events=_events(selected="program-b", blocks=[20, 21])
    )
    report = compare_candidate_exposure(
        {"A0": a0, "A1": a1}, required_arms=("A0", "A1")
    )
    assert report["status"] == "PASS"
    assert report["logical_selection_divergence_count"] == 1
    assert report["physical_victim_set_divergence_count"] == 1
    assert report["downstream_recompute_attribution"] == "NOT_ESTABLISHED"


def test_cross_arm_comparison_rejects_missing_arm_and_decision_mismatch() -> None:
    a0 = evaluate_run_candidate_exposure(run_id="a0", arm="A0", events=_events())
    with pytest.raises(ValueError, match="arm set mismatch"):
        compare_candidate_exposure({"A0": a0}, required_arms=("A0", "A1"))

    a1 = deepcopy(a0)
    a1["arm"] = "A1"
    a1["decisions"] = []
    with pytest.raises(ValueError, match="different decision counts"):
        compare_candidate_exposure(
            {"A0": a0, "A1": a1}, required_arms=("A0", "A1")
        )

