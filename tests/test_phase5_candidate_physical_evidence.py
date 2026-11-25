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
        "a0_baseline_selection": "entry-b",
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


def _a0_outcome():
    return {
        "system_id": "CONTINUUM_ADAPTED",
        "pressure_boundary_id": "boundary-1",
        "status": "PHYSICAL_EVICTION_OBSERVED",
        "matched_physical_block_ids": [12, 13],
        "unmatched_physical_block_ids": [],
        "hashless_physical_block_ids": [],
        "block_content_identities": {"12": "content-c", "13": "content-d"},
    }


def test_dva_loss_selection_plan_and_physical_outcome_are_bound() -> None:
    report = join_candidate_physical_evidence(
        evaluation=_evaluation(),
        candidate_id="DVA_ER_V1",
        selection_plan=_plan(),
        physical_outcome=_outcome(),
        a0_physical_outcome=_a0_outcome(),
    )
    assert report["candidate_loss_by_entry"] == {"entry-a": 0.0, "entry-b": 1.0}
    assert report["selected_entry_id"] == "entry-a"
    assert report["a0_selected_entry_id"] == "entry-b"
    assert report["a0_predicted_native_victim_sequence"] == [12, 13]
    assert report["a0_matched_physical_block_ids"] == [12, 13]
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
            a0_physical_outcome=_a0_outcome(),
        )
    outcome = deepcopy(_outcome())
    outcome["status"] = "NOT_OBSERVABLE"
    with pytest.raises(ValueError, match="not observable"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=_plan(),
            physical_outcome=outcome,
            a0_physical_outcome=_a0_outcome(),
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
            a0_physical_outcome=_a0_outcome(),
        )


def test_a0_physical_outcome_must_match_the_same_boundary() -> None:
    a0_outcome = _a0_outcome()
    a0_outcome["pressure_boundary_id"] = "other-boundary"
    with pytest.raises(ValueError, match="A0 physical outcome pressure boundary"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=_plan(),
            physical_outcome=_outcome(),
            a0_physical_outcome=a0_outcome,
        )


def test_a0_physical_outcome_must_come_from_adapted_baseline() -> None:
    a0_outcome = _a0_outcome()
    a0_outcome["system_id"] = "DVA_ER_V1"
    with pytest.raises(ValueError, match="CONTINUUM_ADAPTED"):
        join_candidate_physical_evidence(
            evaluation=_evaluation(),
            candidate_id="DVA_ER_V1",
            selection_plan=_plan(),
            physical_outcome=_outcome(),
            a0_physical_outcome=a0_outcome,
        )
