from __future__ import annotations

import copy

import pytest

from kvopt.workload.phase5_calibration import (
    SYSTEM_IDS,
    analyze_calibration,
    validate_calibration_matrix,
)


def _records():
    rows = []
    for stratum_index, stratum in enumerate(("SWE_BENCH",)):
        for group_index in range(1, 5):
            for system_index, system_id in enumerate(SYSTEM_IDS):
                for repeat_index in range(1, 4):
                    rows.append(
                        {
                            "run_id": (
                                f"cal-{stratum_index}-{group_index}-"
                                f"{system_id}-{repeat_index}"
                            ),
                            "status": "PASS",
                            "stratum": stratum,
                            "group_id": f"{stratum_index}-{group_index}",
                            "system_id": system_id,
                            "repeat_index": repeat_index,
                            "formal_group": False,
                            "recomputed_tokens_E_minus_C": (
                                4000 + group_index * 100 + system_index * 10
                            ),
                        }
                    )
    return rows


def test_exact_72_run_calibration_matrix() -> None:
    report = validate_calibration_matrix(_records())
    assert report["record_count"] == 72
    assert report["systems"] == list(SYSTEM_IDS)
    assert report["formal_execution_authorized"] is False


def test_missing_duplicate_failed_and_formal_reuse_fail_closed() -> None:
    rows = _records()
    with pytest.raises(ValueError, match="exactly 72"):
        validate_calibration_matrix(rows[:-1])
    duplicated = copy.deepcopy(rows)
    duplicated[-1] = copy.deepcopy(duplicated[0])
    with pytest.raises(ValueError, match="run_id"):
        validate_calibration_matrix(duplicated)
    failed = copy.deepcopy(rows)
    failed[0]["status"] = "FAIL_CLOSED"
    with pytest.raises(ValueError, match="non-PASS"):
        validate_calibration_matrix(failed)
    reused = copy.deepcopy(rows)
    reused[0]["formal_group"] = True
    with pytest.raises(ValueError, match="reused"):
        validate_calibration_matrix(reused)


def test_analyzer_requires_exact_mixed_model_and_noncentral_t() -> None:
    with pytest.raises(RuntimeError, match="noncentral-t"):
        analyze_calibration(_records())

    def estimator(_records):
        return {
            "estimator": "METHOD_OF_MOMENTS_MIXED_MODEL",
            "contrast_covariance_size": 8,
            "negative_variance_rule": (
                "TRUNCATE_POINT_AT_ZERO_AND_USE_BOOTSTRAP_UPPER_BOUND"
            ),
        }

    def solver(_variance):
        return {
            "distribution": "NONCENTRAL_T_ITERATIVE",
            "selected_groups_per_stratum": {"SWE_BENCH": 8},
        }

    report = analyze_calibration(
        _records(), mixed_model_estimator=estimator, noncentral_t_solver=solver
    )
    assert report["status"] == "CALIBRATION_ANALYZED_EXECUTION_NOT_AUTHORIZED"
    assert report["sample_size"]["selected_groups_per_stratum"]["SWE_BENCH"] == 8


def test_z_approximation_is_rejected() -> None:
    def estimator(_records):
        return {
            "estimator": "METHOD_OF_MOMENTS_MIXED_MODEL",
            "contrast_covariance_size": 8,
            "negative_variance_rule": (
                "TRUNCATE_POINT_AT_ZERO_AND_USE_BOOTSTRAP_UPPER_BOUND"
            ),
        }

    with pytest.raises(ValueError, match="z approximation"):
        analyze_calibration(
            _records(),
            mixed_model_estimator=estimator,
            noncentral_t_solver=lambda _: {
                "distribution": "NORMAL_Z",
                "selected_groups_per_stratum": {
                    "SWE_BENCH": 8,
                },
            },
        )
