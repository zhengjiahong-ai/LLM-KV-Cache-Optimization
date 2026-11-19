from __future__ import annotations

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS
from kvopt.workload.phase5_calibration_backend import (
    _noncentral_t_upper_power,
    _student_t_quantile,
    estimate_calibration_mixed_model,
    run_frozen_calibration_analysis,
    solve_calibration_noncentral_t,
)


def _records():
    rows = []
    for stratum_index, stratum in enumerate(("SWE_BENCH", "BFCL_WEB_SEARCH")):
        for group_index in range(4):
            group_id = f"{stratum}:g{group_index}"
            for system_index, system_id in enumerate(SYSTEM_IDS):
                for repeat in range(1, 4):
                    value = (
                        10_000.0
                        + stratum_index * 50.0
                        + system_index * 100.0
                        + group_index * system_index * 3.0
                        + repeat * system_index
                        + ((group_index + repeat + system_index) % 3) * 2.0
                    )
                    rows.append(
                        {
                            "run_id": (
                                f"cal:{stratum}:g{group_index}:"
                                f"{system_id}:r{repeat}"
                            ),
                            "stratum": stratum,
                            "group_id": group_id,
                            "system_id": system_id,
                            "repeat_index": repeat,
                            "status": "PASS",
                            "formal_group": False,
                            "recomputed_tokens_E_minus_C": value,
                        }
                    )
    return rows


def test_method_of_moments_uses_frozen_df_and_formal_repeat_count() -> None:
    report = estimate_calibration_mixed_model(
        _records(), bootstrap_resamples=200, bootstrap_seed=20261201
    )
    assert report["df_between"] == 6
    assert report["df_within"] == 16
    assert report["df_total"] == 22
    assert report["per_stratum_df"] == 3
    assert report["per_stratum_within_df"] == 8
    assert report["pooled_df_7_used"] is False
    contrast = report["contrast_estimates"]["A1_vs_A0"]["common"]
    assert contrast["formal_group_mean_variance"] == pytest.approx(
        contrast["sigma_between_squared"]
        + contrast["sigma_repeat_squared"] / 2.0
    )


def test_covariance_is_8x8_df6_and_psd_projected() -> None:
    report = estimate_calibration_mixed_model(
        _records(), bootstrap_resamples=50, bootstrap_seed=7
    )
    covariance = report["contrast_covariance"]
    assert covariance["size"] == 8
    assert covariance["df_covariance"] == 6
    matrix = covariance["psd_projection"]["matrix"]
    assert len(matrix) == 8
    assert all(len(row) == 8 for row in matrix)
    assert min(covariance["psd_projection"]["eigenvalues_after"]) >= 0.0


def test_parametric_bootstrap_is_reproducible_and_keeps_negative_point_rule() -> None:
    first = estimate_calibration_mixed_model(
        _records(), bootstrap_resamples=100, bootstrap_seed=19
    )
    second = estimate_calibration_mixed_model(
        _records(), bootstrap_resamples=100, bootstrap_seed=19
    )
    assert first == second
    for row in first["contrast_estimates"].values():
        assert row["common"]["sigma_between_squared"] >= 0.0
        assert row["upper_bound"]["sizing_upper"] >= 0.0


def test_noncentral_t_solver_uses_n_minus_one_and_never_z() -> None:
    variance = estimate_calibration_mixed_model(
        _records(), bootstrap_resamples=100, bootstrap_seed=23
    )
    report = solve_calibration_noncentral_t(variance)
    assert report["distribution"] == "NONCENTRAL_T_ITERATIVE"
    assert report["df_rule"] == "N_MINUS_1_NONCENTRAL_T"
    assert report["z_approximation_used"] is False
    assert report["pooled_df_7_used"] is False
    assert set(report["selected_groups_per_stratum"]) == {
        "SWE_BENCH",
        "BFCL_WEB_SEARCH",
    }
    assert all(8 <= value <= 16 for value in report["selected_groups_per_stratum"].values())
    assert len(set(report["selected_groups_per_stratum"].values())) == 1
    assert report["final_groups_per_stratum"] == max(
        report["stratum_specific_required_n"].values()
    )


def test_student_t_critical_and_noncentral_power_are_numerically_sane() -> None:
    critical = _student_t_quantile(0.975, 9)
    assert critical == pytest.approx(2.262157, rel=2e-5)
    low = _noncentral_t_upper_power(critical=critical, df=9, ncp=1.0)
    high = _noncentral_t_upper_power(critical=critical, df=9, ncp=3.0)
    assert 0.0 < low < high < 1.0


def test_public_calibration_pipeline_consumes_exact_backend() -> None:
    report = run_frozen_calibration_analysis(
        _records(), bootstrap_resamples=100, bootstrap_seed=29
    )
    assert report["status"] == "CALIBRATION_ANALYZED_EXECUTION_NOT_AUTHORIZED"
    assert report["variance_model"]["df_between"] == 6
    assert report["sample_size"]["distribution"] == "NONCENTRAL_T_ITERATIVE"
    assert report["formal_execution_authorized"] is False
