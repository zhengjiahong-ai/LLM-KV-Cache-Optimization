from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_swe_dataset_readiness import (
    SWEDatasetReadinessError,
    build_swe_dataset_readiness,
    validate_swe_dataset_readiness,
)


def _rows() -> list[dict[str, object]]:
    rows = []
    for index in range(57):
        qualified = index < 35
        rows.append(
            {
                "program_id": f"program-{index:02d}",
                "session_id": f"session-{index:02d}",
                "trace_id": f"trace-{index:02d}",
                "terminal_class": "RIGHT_CENSORED" if index else "NATURAL_TERMINAL",
                "qualification_status": "QUALIFIED" if qualified else "EXCLUDED",
                "qualification_checks": {f"Q{i}": qualified for i in range(1, 10)},
                "failed_rules": [] if qualified else ["Q1_COMPLETE_PAYLOAD"],
            }
        )
    return rows


def test_readiness_reports_independent_program_shortfall_without_cohort() -> None:
    candidates, exclusions, summary = build_swe_dataset_readiness(
        session_evidence=_rows(),
        input_bindings={"protocol": "a" * 64},
    )
    validate_swe_dataset_readiness(candidates, exclusions, summary)
    assert candidates["independent_program_count"] == 35
    assert exclusions["excluded_session_count"] == 22
    assert summary["minimum_program_shortfall"] == 13
    assert summary["maximum_complete_four_program_groups_from_current_pool"] == 8
    assert summary["formal_cohort_selected"] is False


def test_readiness_rejects_duplicate_qualified_program_identity() -> None:
    rows = _rows()
    rows[1]["program_id"] = rows[0]["program_id"]
    with pytest.raises(SWEDatasetReadinessError, match="not independent"):
        build_swe_dataset_readiness(session_evidence=rows, input_bindings={})


def test_readiness_validator_rejects_claim_drift() -> None:
    outputs = list(build_swe_dataset_readiness(session_evidence=_rows(), input_bindings={}))
    outputs[2] = deepcopy(outputs[2])
    outputs[2]["formal_cohort_selected"] = True
    with pytest.raises(SWEDatasetReadinessError, match="mismatch"):
        validate_swe_dataset_readiness(*outputs)
