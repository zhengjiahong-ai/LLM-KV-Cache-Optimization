"""Frozen Phase 5 Calibration mixed-model and noncentral-t backend."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from statistics import fmean

from .phase5_calibration import SYSTEM_IDS, analyze_calibration, validate_calibration_matrix

CONTRASTS = (
    ("A1_vs_A0", "A1_ORIGINAL", "CONTINUUM_ADAPTED"),
    ("A3_vs_A0", "A3_SUFFIX", "CONTINUUM_ADAPTED"),
    ("DVA_vs_A0", "DVA_ER_V1", "CONTINUUM_ADAPTED"),
    ("A3_vs_A1", "A3_SUFFIX", "A1_ORIGINAL"),
    ("DVA_vs_A1", "DVA_ER_V1", "A1_ORIGINAL"),
    ("DVA_vs_A3", "DVA_ER_V1", "A3_SUFFIX"),
    ("NATIVE_vs_A0", "NATIVE", "CONTINUUM_ADAPTED"),
    ("OFFICIAL_vs_A0", "CONTINUUM_OFFICIAL", "CONTINUUM_ADAPTED"),
)
CANDIDATE_CONTRAST_IDS = tuple(row[0] for row in CONTRASTS[:6])
STRATA = ("SWE_BENCH",)
DF_BETWEEN = 3
DF_WITHIN = 8
DF_TOTAL = 11
DF_STRATUM_BETWEEN = 3
DF_STRATUM_WITHIN = 8
DF_COVARIANCE = 3


def project_single_stratum_gpu_hours(
    per_system_seconds: Mapping[str, Mapping[str, float]],
    *,
    formal_groups: int,
    failure_reserve_fraction: float = 0.10,
) -> float:
    """Apply the frozen SWE-only 12-calibration/2N-formal budget formula."""

    if isinstance(formal_groups, bool) or not isinstance(formal_groups, int):
        raise TypeError("formal_groups must be an integer")
    if not 8 <= formal_groups <= 16:
        raise ValueError("formal_groups must be in the inclusive range 8..16")
    if not 0.0 <= failure_reserve_fraction < 1.0:
        raise ValueError("failure reserve fraction is invalid")
    required = {
        "calibration",
        "formal",
        "startup",
        "restart",
        "archive",
        "evaluator",
    }
    total_seconds = 0.0
    for system_id in SYSTEM_IDS:
        row = per_system_seconds.get(system_id)
        if not isinstance(row, Mapping) or set(row) != required:
            raise ValueError(f"resource timing is incomplete for {system_id}")
        values = {key: float(value) for key, value in row.items()}
        if any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError(f"resource timing is invalid for {system_id}")
        overhead = sum(values[key] for key in ("startup", "restart", "archive", "evaluator"))
        total_seconds += (
            12 * values["calibration"]
            + 2 * formal_groups * values["formal"]
            + (12 + 2 * formal_groups) * overhead
        )
    return (1.0 + failure_reserve_fraction) * total_seconds / 3600.0


BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20_261_201


def _records_by_cell(
    records: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, int, str], float]:
    validate_calibration_matrix(records)
    result = {}
    for row in records:
        result[
            (
                str(row["stratum"]),
                str(row["group_id"]),
                int(row["repeat_index"]),
                str(row["system_id"]),
            )
        ] = float(row["recomputed_tokens_E_minus_C"])
    return result


def _contrast_observations(
    records: Sequence[Mapping[str, object]],
) -> tuple[
    dict[str, dict[str, list[list[float]]]],
    dict[str, float],
]:
    cells = _records_by_cell(records)
    groups = {stratum: sorted({key[1] for key in cells if key[0] == stratum}) for stratum in STRATA}
    observations: dict[str, dict[str, list[list[float]]]] = {
        contrast_id: {stratum: [] for stratum in STRATA} for contrast_id, _, _ in CONTRASTS
    }
    native_means = {}
    for stratum in STRATA:
        native_group_means = []
        for group_id in groups[stratum]:
            native_group_means.append(
                fmean(cells[(stratum, group_id, repeat, "NATIVE")] for repeat in range(1, 4))
            )
            for contrast_id, left, right in CONTRASTS:
                observations[contrast_id][stratum].append(
                    [
                        cells[(stratum, group_id, repeat, left)]
                        - cells[(stratum, group_id, repeat, right)]
                        for repeat in range(1, 4)
                    ]
                )
        native_means[stratum] = fmean(native_group_means)
    return observations, native_means


def _mom_components(
    by_stratum: Mapping[str, Sequence[Sequence[float]]],
) -> dict[str, float]:
    if set(by_stratum) != set(STRATA) or any(len(by_stratum[stratum]) != 4 for stratum in STRATA):
        raise ValueError("mixed-model input must contain four Groups per stratum")
    group_means = {
        stratum: [fmean(repeats) for repeats in by_stratum[stratum]] for stratum in STRATA
    }
    stratum_means = {stratum: fmean(group_means[stratum]) for stratum in STRATA}
    ss_between = sum(
        (value - stratum_means[stratum]) ** 2
        for stratum in STRATA
        for value in group_means[stratum]
    )
    ss_within = sum(
        (value - fmean(repeats)) ** 2
        for stratum in STRATA
        for repeats in by_stratum[stratum]
        for value in repeats
    )
    repeat_variance = ss_within / DF_WITHIN
    between_untruncated = ss_between / DF_BETWEEN - repeat_variance / 3.0
    between_variance = max(0.0, between_untruncated)
    return {
        "ss_between": ss_between,
        "ss_within": ss_within,
        "sigma_between_squared_untruncated": between_untruncated,
        "sigma_between_squared": between_variance,
        "sigma_repeat_squared": repeat_variance,
        "formal_group_mean_variance": between_variance + repeat_variance / 2.0,
    }


def _stratum_components(groups: Sequence[Sequence[float]]) -> dict[str, float]:
    if len(groups) != 4 or any(len(row) != 3 for row in groups):
        raise ValueError("stratum variance input must be 4 Groups x 3 repeats")
    means = [fmean(row) for row in groups]
    overall = fmean(means)
    ss_between = sum((value - overall) ** 2 for value in means)
    ss_within = sum((value - fmean(row)) ** 2 for row in groups for value in row)
    repeat_variance = ss_within / DF_STRATUM_WITHIN
    between_untruncated = ss_between / DF_STRATUM_BETWEEN - repeat_variance / 3.0
    between_variance = max(0.0, between_untruncated)
    return {
        "ss_between": ss_between,
        "ss_within": ss_within,
        "sigma_between_squared_untruncated": between_untruncated,
        "sigma_between_squared": between_variance,
        "sigma_repeat_squared": repeat_variance,
        "formal_group_mean_variance": between_variance + repeat_variance / 2.0,
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _simulate_groups(
    *,
    rng: random.Random,
    sigma_between_squared: float,
    sigma_repeat_squared: float,
    strata: int,
    groups_per_stratum: int,
) -> dict[str, list[list[float]]]:
    result = {}
    for stratum_index in range(strata):
        rows = []
        for _ in range(groups_per_stratum):
            group_effect = rng.gauss(0.0, math.sqrt(sigma_between_squared))
            rows.append(
                [group_effect + rng.gauss(0.0, math.sqrt(sigma_repeat_squared)) for _ in range(3)]
            )
        result[STRATA[stratum_index]] = rows
    return result


def _simulate_stratum(
    *,
    rng: random.Random,
    sigma_between_squared: float,
    sigma_repeat_squared: float,
) -> list[list[float]]:
    return [
        [group_effect + rng.gauss(0.0, math.sqrt(sigma_repeat_squared)) for _ in range(3)]
        for group_effect in (rng.gauss(0.0, math.sqrt(sigma_between_squared)) for _ in range(4))
    ]


def _bootstrap_upper_bounds(
    by_stratum: Mapping[str, Sequence[Sequence[float]]],
    *,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    if resamples <= 0:
        raise ValueError("bootstrap resamples must be positive")
    common = _mom_components(by_stratum)
    stratum_components = {stratum: _stratum_components(by_stratum[stratum]) for stratum in STRATA}
    rng = random.Random(seed)
    common_values = []
    stratum_values = {stratum: [] for stratum in STRATA}
    for _ in range(resamples):
        simulated = _simulate_groups(
            rng=rng,
            sigma_between_squared=common["sigma_between_squared"],
            sigma_repeat_squared=common["sigma_repeat_squared"],
            strata=1,
            groups_per_stratum=4,
        )
        common_values.append(_mom_components(simulated)["formal_group_mean_variance"])
        for stratum in STRATA:
            component = stratum_components[stratum]
            stratum_simulated = _simulate_stratum(
                rng=rng,
                sigma_between_squared=component["sigma_between_squared"],
                sigma_repeat_squared=component["sigma_repeat_squared"],
            )
            stratum_values[stratum].append(
                _stratum_components(stratum_simulated)["formal_group_mean_variance"]
            )
    common_upper = _quantile(common_values, 0.8)
    stratum_upper = {stratum: _quantile(values, 0.8) for stratum, values in stratum_values.items()}
    degenerate = common["sigma_between_squared"] == 0.0 and common["sigma_repeat_squared"] == 0.0
    return {
        "method": "PARAMETRIC_BOOTSTRAP",
        "resamples": resamples,
        "seed": seed,
        "quantile": 0.8,
        "common_upper": common_upper,
        "stratum_upper": stratum_upper,
        "sizing_upper": max(common_upper, *stratum_upper.values()),
        "degenerate": degenerate,
    }


def _jacobi_psd(matrix: Sequence[Sequence[float]]) -> dict[str, object]:
    size = len(matrix)
    if size != 8 or any(len(row) != size for row in matrix):
        raise ValueError("contrast covariance must be 8x8")
    values = [list(map(float, row)) for row in matrix]
    vectors = [[float(row == column) for column in range(size)] for row in range(size)]
    for _ in range(200 * size * size):
        left, right = max(
            ((row, column) for row in range(size) for column in range(row + 1, size)),
            key=lambda pair: abs(values[pair[0]][pair[1]]),
        )
        if abs(values[left][right]) < 1.0e-12:
            break
        angle = 0.5 * math.atan2(
            2.0 * values[left][right],
            values[right][right] - values[left][left],
        )
        cosine = math.cos(angle)
        sine = math.sin(angle)
        for index in range(size):
            if index not in {left, right}:
                old_left = values[index][left]
                old_right = values[index][right]
                values[index][left] = values[left][index] = cosine * old_left - sine * old_right
                values[index][right] = values[right][index] = sine * old_left + cosine * old_right
        old_ll = values[left][left]
        old_rr = values[right][right]
        old_lr = values[left][right]
        values[left][left] = (
            cosine * cosine * old_ll - 2.0 * sine * cosine * old_lr + sine * sine * old_rr
        )
        values[right][right] = (
            sine * sine * old_ll + 2.0 * sine * cosine * old_lr + cosine * cosine * old_rr
        )
        values[left][right] = values[right][left] = 0.0
        for index in range(size):
            old_left = vectors[index][left]
            old_right = vectors[index][right]
            vectors[index][left] = cosine * old_left - sine * old_right
            vectors[index][right] = sine * old_left + cosine * old_right
    eigenvalues = [values[index][index] for index in range(size)]
    clipped = [max(0.0, value) for value in eigenvalues]
    projected = [
        [
            sum(
                vectors[row][index] * clipped[index] * vectors[column][index]
                for index in range(size)
            )
            for column in range(size)
        ]
        for row in range(size)
    ]
    return {
        "method": "EIGENVALUE_CLIP_AT_ZERO",
        "eigenvalues_before": eigenvalues,
        "eigenvalues_after": clipped,
        "numerical_rank": sum(value > 1.0e-10 for value in clipped),
        "matrix": projected,
    }


def _contrast_covariance(
    observations: Mapping[str, Mapping[str, Sequence[Sequence[float]]]],
) -> dict[str, object]:
    group_vectors = {stratum: [] for stratum in STRATA}
    for stratum in STRATA:
        for group_index in range(4):
            group_vectors[stratum].append(
                [
                    fmean(observations[contrast_id][stratum][group_index])
                    for contrast_id, _, _ in CONTRASTS
                ]
            )
    means = {
        stratum: [fmean(vector[index] for vector in group_vectors[stratum]) for index in range(8)]
        for stratum in STRATA
    }
    residuals = [
        [value - means[stratum][index] for index, value in enumerate(vector)]
        for stratum in STRATA
        for vector in group_vectors[stratum]
    ]
    matrix = [
        [
            sum(vector[row] * vector[column] for vector in residuals) / DF_COVARIANCE
            for column in range(8)
        ]
        for row in range(8)
    ]
    projection = _jacobi_psd(matrix)
    if int(projection["numerical_rank"]) > 3:
        raise ValueError("four-Group contrast covariance rank exceeds three")
    return {
        "contrast_ids": [row[0] for row in CONTRASTS],
        "size": 8,
        "df_covariance": DF_COVARIANCE,
        "rank_upper_bound": 3,
        "direct_inverse_allowed": False,
        "downstream_rule": "PSEUDOINVERSE_OR_SIMULATION_ONLY",
        "raw_matrix": matrix,
        "psd_projection": projection,
    }


def estimate_calibration_mixed_model(
    records: Sequence[Mapping[str, object]],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    observations, native_means = _contrast_observations(records)
    estimates = {}
    for contrast_id, _, _ in CONTRASTS:
        rows = observations[contrast_id]
        estimates[contrast_id] = {
            "common": _mom_components(rows),
            "by_stratum": {stratum: _stratum_components(rows[stratum]) for stratum in STRATA},
            "upper_bound": _bootstrap_upper_bounds(
                rows,
                resamples=bootstrap_resamples,
                seed=bootstrap_seed,
            ),
        }
    return {
        "estimator": "METHOD_OF_MOMENTS_MIXED_MODEL",
        "pooling_rule": "SINGLE_STRATUM_GROUP_RANDOM_EFFECT",
        "df_between": DF_BETWEEN,
        "df_within": DF_WITHIN,
        "df_total": DF_TOTAL,
        "fixed_effect_rank": 1,
        "formal_repeats": 2,
        "per_stratum_df": DF_STRATUM_BETWEEN,
        "per_stratum_within_df": DF_STRATUM_WITHIN,
        "contrast_covariance_size": 8,
        "contrast_covariance": _contrast_covariance(observations),
        "negative_variance_rule": ("TRUNCATE_POINT_AT_ZERO_AND_USE_BOOTSTRAP_UPPER_BOUND"),
        "bootstrap_resamples": bootstrap_resamples,
        "bootstrap_seed": bootstrap_seed,
        "native_group_mean_recomputed_tokens": native_means,
        "contrast_estimates": estimates,
        "pooled_df_7_used": False,
        "z_approximation_used": False,
    }


def _beta_fraction(a: float, b: float, x: float) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1.0e-300 else 1.0e-300)
    result = d
    for iteration in range(1, 401):
        doubled = 2 * iteration
        coefficient = iteration * (b - iteration) * x / ((qam + doubled) * (a + doubled))
        d = 1.0 + coefficient * d
        d = 1.0 / (d if abs(d) > 1.0e-300 else 1.0e-300)
        c = 1.0 + coefficient / c
        c = c if abs(c) > 1.0e-300 else 1.0e-300
        result *= d * c
        coefficient = -(a + iteration) * (qab + iteration) * x / ((a + doubled) * (qap + doubled))
        d = 1.0 + coefficient * d
        d = 1.0 / (d if abs(d) > 1.0e-300 else 1.0e-300)
        c = 1.0 + coefficient / c
        c = c if abs(c) > 1.0e-300 else 1.0e-300
        change = d * c
        result *= change
        if abs(change - 1.0) <= 3.0e-14:
            return result
    raise ArithmeticError("incomplete beta calculation did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_fraction(a, b, x) / a
    return 1.0 - front * _beta_fraction(b, a, 1.0 - x) / b


def _student_t_cdf(value: float, df: int) -> float:
    x = df / (df + value * value)
    tail = 0.5 * _regularized_beta(x, df / 2.0, 0.5)
    return 1.0 - tail if value >= 0.0 else tail


def _student_t_quantile(probability: float, df: int) -> float:
    if not 0.5 < probability < 1.0:
        raise ValueError("only upper Student-t quantiles are supported")
    low, high = 0.0, 1.0
    while _student_t_cdf(high, df) < probability:
        high *= 2.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if _student_t_cdf(middle, df) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _noncentral_t_upper_power(*, critical: float, df: int, ncp: float) -> float:
    upper = max(12.0, math.sqrt(df) + 10.0)
    intervals = 4096
    step = upper / intervals
    log_constant = -(df / 2.0) * math.log(2.0) - math.lgamma(df / 2.0)

    def integrand(root_v: float) -> float:
        if root_v <= 0.0:
            return 0.0
        v = root_v * root_v
        log_density = (df / 2.0 - 1.0) * math.log(v) - v / 2.0 + log_constant
        chi_root_density = math.exp(log_density) * 2.0 * root_v
        threshold = critical * root_v / math.sqrt(df) - ncp
        return (1.0 - _normal_cdf(threshold)) * chi_root_density

    total = integrand(0.0) + integrand(upper)
    total += 4.0 * sum(integrand(step * index) for index in range(1, intervals, 2))
    total += 2.0 * sum(integrand(step * index) for index in range(2, intervals, 2))
    return min(1.0, max(0.0, total * step / 3.0))


def solve_calibration_noncentral_t(
    variance: Mapping[str, object],
) -> dict[str, object]:
    if variance.get("df_between") != 3 or variance.get("df_within") != 8:
        raise ValueError("Calibration variance does not use df=3/8")
    estimates = variance.get("contrast_estimates")
    native_means = variance.get("native_group_mean_recomputed_tokens")
    if not isinstance(estimates, Mapping) or not isinstance(native_means, Mapping):
        raise TypeError("Calibration variance output is incomplete")
    alpha = 0.05 / 6.0
    mde = {stratum: max(512.0, 0.05 * float(native_means[stratum])) for stratum in STRATA}
    required = {stratum: {} for stratum in STRATA}
    powers = {stratum: {} for stratum in STRATA}
    degenerate_contrasts = []
    for contrast_id in CANDIDATE_CONTRAST_IDS:
        row = estimates[contrast_id]
        if not isinstance(row, Mapping) or not isinstance(row.get("upper_bound"), Mapping):
            raise TypeError("candidate contrast upper bound is incomplete")
        upper = float(row["upper_bound"]["sizing_upper"])
        if row["upper_bound"].get("degenerate"):
            degenerate_contrasts.append(contrast_id)
        for stratum in STRATA:
            selected = None
            power_by_n = {}
            for sample_size in range(8, 17):
                if upper == 0.0:
                    power = 1.0
                else:
                    ncp = mde[stratum] / math.sqrt(upper / sample_size)
                    critical = _student_t_quantile(1.0 - alpha / 2.0, sample_size - 1)
                    power = _noncentral_t_upper_power(
                        critical=critical,
                        df=sample_size - 1,
                        ncp=ncp,
                    )
                power_by_n[str(sample_size)] = power
                if selected is None and power >= 0.8:
                    selected = sample_size
            required[stratum][contrast_id] = selected
            powers[stratum][contrast_id] = power_by_n
    stratum_required = {}
    underpowered = {}
    for stratum in STRATA:
        values = list(required[stratum].values())
        if any(value is None for value in values):
            stratum_required[stratum] = 16
            underpowered[stratum] = True
        else:
            stratum_required[stratum] = max(8, max(values))
            underpowered[stratum] = False
    final_n = max(stratum_required.values())
    selected_by_stratum = {stratum: final_n for stratum in STRATA}
    return {
        "distribution": "NONCENTRAL_T_ITERATIVE",
        "alpha_per_test": alpha,
        "target_power": 0.8,
        "candidate_contrast_ids": list(CANDIDATE_CONTRAST_IDS),
        "mde_by_stratum": mde,
        "required_n_by_stratum_and_contrast": required,
        "power_by_stratum_contrast_and_n": powers,
        "selected_groups_per_stratum": selected_by_stratum,
        "final_groups_per_stratum": final_n,
        "stratum_specific_required_n": stratum_required,
        "underpowered_at_n16": underpowered,
        "degenerate_bootstrap_contrasts": degenerate_contrasts,
        "degenerate_bootstrap_uncertainty_reported": bool(degenerate_contrasts),
        "df_rule": "N_MINUS_1_NONCENTRAL_T",
        "z_approximation_used": False,
        "pooled_df_7_used": False,
    }


def run_frozen_calibration_analysis(
    records: Sequence[Mapping[str, object]],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Run the exact frozen backend through the public Calibration boundary."""

    return analyze_calibration(
        records,
        mixed_model_estimator=lambda rows: estimate_calibration_mixed_model(
            rows,
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        ),
        noncentral_t_solver=solve_calibration_noncentral_t,
    )
