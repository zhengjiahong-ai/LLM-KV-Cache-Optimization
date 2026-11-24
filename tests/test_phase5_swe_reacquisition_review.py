from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_swe_reacquisition_review import (
    SWEReacquisitionReviewError,
    build_swe_reacquisition_review,
    validate_swe_reacquisition_review,
)


def _inputs():
    old_rows = [
        {"program_id": f"old-{index:02d}", "qualification_status": "QUALIFIED"}
        for index in range(35)
    ]
    existing = {
        "qualified_programs": old_rows,
        "program_identity_order": [row["program_id"] for row in old_rows],
    }
    ordered = [f"new-{index:02d}" for index in range(20)]
    attempts = [
        {"instance_id": identity, "status": "completed"} for identity in ordered
    ]
    conversions = [
        {
            "instance_id": identity,
            "status": (
                "CONVERTED" if index < 17 else "EXCLUDED_PRE_NORMALIZATION"
            ),
        }
        for index, identity in enumerate(ordered)
    ]
    qualifications = []
    for index, identity in enumerate(ordered[:17]):
        qualified = index < 13
        qualifications.append(
            {
                "program_id": identity,
                "qualification_status": "QUALIFIED" if qualified else "EXCLUDED",
                "qualification_checks": {
                    f"Q{number}": qualified for number in range(1, 10)
                },
                "failed_rules": [] if qualified else ["Q1_COMPLETE_PAYLOAD"],
            }
        )
    return existing, ordered, attempts, conversions, qualifications


def test_builds_48_program_review_pool_without_selecting_cohort() -> None:
    values = _inputs()
    ledger, candidates, summary = build_swe_reacquisition_review(
        existing_inventory=values[0],
        ordered_instance_ids=values[1],
        attempt_rows=values[2],
        conversion_rows=values[3],
        qualification_rows=values[4],
        input_bindings={"frame": "a" * 64},
    )
    validate_swe_reacquisition_review(ledger, candidates, summary)
    assert ledger["converted_count"] == 17
    assert ledger["pre_normalization_excluded_count"] == 3
    assert candidates["combined_independent_program_count"] == 48
    assert summary["minimum_dataset_gate"] == "PASS"
    assert summary["formal_cohort_selected"] is False


def test_rejects_cross_batch_program_overlap() -> None:
    values = list(_inputs())
    values[0]["qualified_programs"][0]["program_id"] = "new-00"
    values[0]["program_identity_order"][0] = "new-00"
    with pytest.raises(SWEReacquisitionReviewError, match="overlap"):
        build_swe_reacquisition_review(
            existing_inventory=values[0],
            ordered_instance_ids=values[1],
            attempt_rows=values[2],
            conversion_rows=values[3],
            qualification_rows=values[4],
            input_bindings={},
        )


def test_rejects_authorization_claim_drift() -> None:
    values = _inputs()
    outputs = list(
        build_swe_reacquisition_review(
            existing_inventory=values[0],
            ordered_instance_ids=values[1],
            attempt_rows=values[2],
            conversion_rows=values[3],
            qualification_rows=values[4],
            input_bindings={},
        )
    )
    outputs[2] = deepcopy(outputs[2])
    outputs[2]["gpu_execution_authorized"] = True
    with pytest.raises(SWEReacquisitionReviewError, match="mismatch"):
        validate_swe_reacquisition_review(*outputs)
