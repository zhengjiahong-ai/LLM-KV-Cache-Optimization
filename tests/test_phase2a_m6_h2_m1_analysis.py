import math

import pytest

from kvopt.profiling.h2_m1 import (
    _fit,
    _lopo_rmse,
    analyze_m1_observations,
)

GRID = (
    16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 12288,
    16384, 20480, 24576, 26624, 28672, 30720,
)


def test_nested_model_fits_recover_quadratic_coefficients() -> None:
    points = [(tokens, 0.2 + 0.00001 * tokens + 2e-9 * tokens**2) for tokens in GRID]

    quadratic = _fit(points, "quadratic")

    assert quadratic["coefficients"]["a"] == pytest.approx(0.2)
    assert quadratic["coefficients"]["beta"] == pytest.approx(0.00001)
    assert quadratic["coefficients"]["gamma"] == pytest.approx(2e-9)
    assert quadratic["r_squared"] == pytest.approx(1.0)


def test_lopo_prefers_quadratic_for_convex_curve() -> None:
    points = [(tokens, 0.1 + 8e-6 * tokens + 3e-9 * tokens**2) for tokens in GRID[-8:]]

    assert _lopo_rmse(points, "quadratic") < _lopo_rmse(points, "affine")


def test_formal_analysis_is_deterministic_and_uses_frozen_controls() -> None:
    observations = {
        tokens: [
            0.1 + 8e-6 * tokens + 3e-9 * tokens**2 + (repeat - 4) * 1e-5
            for repeat in range(9)
        ]
        for tokens in GRID
    }

    first, first_distribution = analyze_m1_observations(
        observations,
        delta_m1_seconds=0.0,
    )
    second, second_distribution = analyze_m1_observations(
        observations,
        delta_m1_seconds=0.0,
    )

    assert first == second
    assert first_distribution == second_distribution
    assert len(first_distribution) == 10_000
    assert first["candidate_outcome"] == "PASS_PENDING_REVIEW"
    assert first["bootstrap"]["q05_delta_fit_seconds"] > 0
    assert first["bootstrap"]["q05_gamma_seconds_per_token_squared"] > 0
    assert math.isfinite(first["observed_delta_fit_seconds"])


def test_formal_analysis_rejects_non_frozen_repetition_count() -> None:
    observations = {tokens: [float(tokens)] * 8 for tokens in GRID}

    with pytest.raises(ValueError, match="nine measured repetitions"):
        analyze_m1_observations(observations, delta_m1_seconds=0.1)
