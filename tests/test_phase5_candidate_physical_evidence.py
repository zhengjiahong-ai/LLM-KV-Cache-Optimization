from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.profiling.phase5_candidate_physical_evidence import (
    join_candidate_physical_evidence,
)


def _evaluation():
    return {
        "status": "PASS",
        "decision_id": "decision-1",
        "snapshot_sha256": "1" * 64,
        "decisions": {
            "DVA_ER_V1": {
                "scores": {"entry-a": 0.0, "entry-b": 1.0},
                "selected_candidate_id": "entry-a",
                "simulated_native_victim_block_ids": [10, 11],
                "simulated_native_victim_sequences": {
                    "entry-a": [10, 11],
                    "entry-b": [12, 13],
                },
            }
        },
    }


def _plan():
    return {
        "decision_id": "decision-1",
        "candidate_id": "DVA_ER_V1",
        "pressure_boundary_id": "boundary-1",
        "selected_native_block_ids": [10, 11],
    }


def _outcome():
    return {
        "decision_id": "decision-1",
        "candidate_id": "DVA_ER_V1",
        "pressure_boundary_id": "boundary-1",
        "status": "PHYSICAL_EVICTION_OBSERVED",
        "matched_physical_block_ids": [10, 11],
        "unmatched_physical_block_ids": [],
        "hashless_physical_block_ids": [],
        "block_content_identities": {"10": "content-a", "11": "content-b"},
    }


def test_dva_loss_selection_plan_and_physical_outcome_are_bound() -> None:
    report = join_candidate_physical_evidence(
        evaluation=_evaluation(),
        candidate_id="DVA_ER_V1",
        selection_plan=_plan(),
        physical_outcome=_outcome(),
    )
    assert report["candidate_loss_by_entry"] == {"entry-a": 0.0, "entry-b": 1.0}
    assert report["selected_entry_id"] == "entry-a"
    assert report["predicted_equals_observed_matched"] is True
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"


def test_selection_plan_drift_and_unobservable_outcome_fail_closed() -> None:
    plan = deepcopy(_plan())
    plan["selected_native_block_ids"] = [11, 10]
    with pytest.raises(ValueError, match="differs"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=plan,
            physical_outcome=_outcome(),
        )
    outcome = deepcopy(_outcome())
    outcome["status"] = "NOT_OBSERVABLE"
    with pytest.raises(ValueError, match="not observable"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=_plan(),
            physical_outcome=outcome,
        )


def test_unmatched_physical_block_cannot_be_reported_as_planned() -> None:
    outcome = deepcopy(_outcome())
    outcome["matched_physical_block_ids"] = [10]
    outcome["unmatched_physical_block_ids"] = [11]
    with pytest.raises(ValueError, match="overlap"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=_plan(),
            physical_outcome=outcome,
        )
