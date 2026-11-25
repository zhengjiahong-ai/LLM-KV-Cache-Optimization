from __future__ import annotations

import pytest

from kvopt.profiling.phase5_native_evidence import evaluate_phase5_decision_evidence


def _inputs():
    evaluation = {
        "status": "PASS",
        "decision_id": "d1",
        "snapshot_sha256": "1" * 64,
        "decisions": {
            "DVA_ER_V1": {
                "scores": {"a": 1.0, "b": 2.0},
                "selected_candidate_id": "a",
                "simulated_native_victim_sequences": {"a": [10], "b": [11]},
                "simulated_native_victim_block_ids": [10],
            }
        },
    }
    plan = {
        "decision_id": "d1",
        "candidate_id": "DVA_ER_V1",
        "pressure_boundary_id": "pb1",
        "selected_native_block_ids": [10],
    }
    outcome = {
        "decision_id": "d1",
        "candidate_id": "DVA_ER_V1",
        "pressure_boundary_id": "pb1",
        "status": "PHYSICAL_EVICTION_OBSERVED",
        "matched_physical_block_ids": [10],
        "unmatched_physical_block_ids": [],
        "hashless_physical_block_ids": [],
        "block_content_identities": {"10": "content-a"},
    }
    downstream = {
        "d1": [
            {
                "request_id": "r2",
                "program_id": "p",
                "session_id": "s",
                "prefix_content_identities": ["content-a"],
                "native_prompt_tokens": 20,
                "reusable_prefix_tokens": 10,
                "native_cached_tokens": 5,
            }
        ]
    }
    return evaluation, plan, outcome, downstream


def test_complete_decision_chain_is_independently_joined() -> None:
    evaluation, plan, outcome, downstream = _inputs()
    report = evaluate_phase5_decision_evidence(
        candidate_evaluations=[evaluation],
        selection_plans=[plan],
        physical_outcomes=[outcome],
        downstream_by_decision=downstream,
        candidate_id="DVA_ER_V1",
    )
    assert report["status"] == "PASS"
    assert (
        report["decisions"][0]["downstream"]["observations"][0]["observed_recomputed_tokens"] == 5
    )
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"


def test_missing_physical_or_downstream_evidence_fails_closed() -> None:
    evaluation, plan, outcome, downstream = _inputs()
    with pytest.raises(ValueError, match="coverage differs"):
        evaluate_phase5_decision_evidence(
            candidate_evaluations=[evaluation],
            selection_plans=[plan],
            physical_outcomes=[],
            downstream_by_decision=downstream,
            candidate_id="DVA_ER_V1",
        )
    with pytest.raises(ValueError, match="downstream observation coverage"):
        evaluate_phase5_decision_evidence(
            candidate_evaluations=[evaluation],
            selection_plans=[plan],
            physical_outcomes=[outcome],
            downstream_by_decision={},
            candidate_id="DVA_ER_V1",
        )
