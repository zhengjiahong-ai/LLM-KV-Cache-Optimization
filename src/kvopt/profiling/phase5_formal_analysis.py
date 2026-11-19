"""Protocol-frozen Group-level analysis for the Phase 5 six-system campaign."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean, median

SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)

CONTRASTS = {
    "A1_vs_A0": ("A1_ORIGINAL", "CONTINUUM_ADAPTED"),
    "A3_vs_A0": ("A3_SUFFIX", "CONTINUUM_ADAPTED"),
    "DVA_vs_A0": ("DVA_ER_V1", "CONTINUUM_ADAPTED"),
    "A3_vs_A1": ("A3_SUFFIX", "A1_ORIGINAL"),
    "DVA_vs_A1": ("DVA_ER_V1", "A1_ORIGINAL"),
    "DVA_vs_A3": ("DVA_ER_V1", "A3_SUFFIX"),
    "NATIVE_vs_A0": ("NATIVE", "CONTINUUM_ADAPTED"),
    "OFFICIAL_vs_A0": ("CONTINUUM_OFFICIAL", "CONTINUUM_ADAPTED"),
}

PRIMARY_FAMILIES = {
    "CANDIDATE_MECHANISM": (
        "A1_vs_A0",
        "A3_vs_A0",
        "DVA_vs_A0",
        "A3_vs_A1",
        "DVA_vs_A1",
        "DVA_vs_A3",
    ),
    "SYSTEM_CONTEXT": ("NATIVE_vs_A0", "OFFICIAL_vs_A0"),
}


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _bootstrap_ci(
    values: Sequence[float], *, resamples: int, seed: int, confidence: float
) -> tuple[float, float]:
    if resamples <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    rng = random.Random(seed)
    count = len(values)
    estimates = [
        fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    ]
    tail = (1.0 - confidence) / 2.0
    return _percentile(estimates, tail), _percentile(estimates, 1.0 - tail)


def _paired_permutation_pvalue(values: Sequence[float]) -> float:
    """Exact two-sided paired sign-flip p-value at the Group level."""

    observed = abs(fmean(values))
    extreme = 0
    total = 1 << len(values)
    tolerance = 1e-12
    for mask in range(total):
        estimate = fmean(
            value if mask & (1 << index) else -value
            for index, value in enumerate(values)
        )
        if abs(estimate) + tolerance >= observed:
            extreme += 1
    return extreme / total


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    maximum_iterations = 400
    epsilon = 3.0e-14
    floor = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / max(abs(d), floor) * (1.0 if d >= 0 else -1.0)
    result = d
    for iteration in range(1, maximum_iterations + 1):
        doubled = 2 * iteration
        coefficient = iteration * (b - iteration) * x / (
            (qam + doubled) * (a + doubled)
        )
        d = 1.0 + coefficient * d
        d = d if abs(d) >= floor else floor
        c = 1.0 + coefficient / c
        c = c if abs(c) >= floor else floor
        d = 1.0 / d
        result *= d * c
        coefficient = -(a + iteration) * (qab + iteration) * x / (
            (a + doubled) * (qap + doubled)
        )
        d = 1.0 + coefficient * d
        d = d if abs(d) >= floor else floor
        c = 1.0 + coefficient / c
        c = c if abs(c) >= floor else floor
        d = 1.0 / d
        change = d * c
        result *= change
        if abs(change - 1.0) <= epsilon:
            return result
    raise ArithmeticError("incomplete beta continued fraction did not converge")


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    if not 0.0 <= x <= 1.0 or a <= 0.0 or b <= 0.0:
        raise ValueError("regularized incomplete beta arguments are invalid")
    if x in {0.0, 1.0}:
        return x
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _paired_t_test(values: Sequence[float]) -> dict[str, object]:
    count = len(values)
    if count < 2:
        return {"status": "NOT_EVALUABLE_N_LT_2", "df": max(0, count - 1)}
    mean = fmean(values)
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    if variance == 0.0:
        return {
            "status": "DEGENERATE_ZERO_VARIANCE",
            "df": count - 1,
            "statistic": 0.0 if mean == 0.0 else math.copysign(math.inf, mean),
            "two_sided_pvalue": 1.0 if mean == 0.0 else 0.0,
        }
    statistic = mean / math.sqrt(variance / count)
    df = count - 1
    x = df / (df + statistic * statistic)
    pvalue = _regularized_incomplete_beta(x, df / 2.0, 0.5)
    return {
        "status": "PASS",
        "df": df,
        "statistic": statistic,
        "two_sided_pvalue": min(1.0, max(0.0, pvalue)),
    }


def _holm_adjust(raw: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(raw, key=lambda name: (raw[name], name))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, name in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * raw[name]))
        adjusted[name] = running
    return adjusted


def analyze_phase5_formal_groups(
    rows: Sequence[Mapping[str, object]],
    *,
    bootstrap_resamples: int = 10_000,
    bootstrap_seed: int = 20_261_201,
    confidence_level: float = 0.95,
    expected_repeats: Sequence[int] = (1, 2),
) -> dict[str, object]:
    """Analyze complete Groups without request/cell-level inference or imputation.

    Each input row is one run-level metric and must contain ``run_id``,
    ``group_id``, ``stratum``, ``system_id``, ``repeat_index``, ``status`` and
    ``metric_value``. A Group enters the primary analysis only when every one
    of the six Systems has every frozen repeat with a finite PASS value.
    """

    repeats = tuple(expected_repeats)
    if not repeats or len(repeats) != len(set(repeats)):
        raise ValueError("expected_repeats must be unique and non-empty")
    cells: dict[tuple[str, str, str, int], float] = {}
    group_reasons: dict[tuple[str, str], list[str]] = defaultdict(list)
    run_ids: set[str] = set()

    for ordinal, row in enumerate(rows):
        run_id = row.get("run_id")
        group_id = row.get("group_id")
        stratum = row.get("stratum")
        system_id = row.get("system_id")
        repeat_index = row.get("repeat_index")
        if not all(isinstance(value, str) and value for value in (run_id, group_id, stratum)):
            raise ValueError(f"row {ordinal} has incomplete identity")
        if run_id in run_ids:
            raise ValueError(f"duplicate run_id: {run_id}")
        run_ids.add(run_id)
        if system_id not in SYSTEM_IDS:
            raise ValueError(f"unknown system_id: {system_id}")
        if repeat_index not in repeats:
            raise ValueError(f"unexpected repeat_index: {repeat_index}")
        key = (stratum, group_id, system_id, repeat_index)
        if key in cells:
            raise ValueError(f"duplicate Group/System/repeat cell: {key}")
        value = row.get("metric_value")
        if row.get("status") != "PASS":
            group_reasons[(stratum, group_id)].append(
                f"{system_id}:repeat:{repeat_index}:STATUS_{row.get('status') or 'MISSING'}"
            )
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            group_reasons[(stratum, group_id)].append(
                f"{system_id}:repeat:{repeat_index}:METRIC_NOT_FINITE"
            )
            continue
        cells[key] = float(value)

    group_keys = sorted(
        {(stratum, group_id) for stratum, group_id, _, _ in cells} | set(group_reasons)
    )
    group_means: dict[tuple[str, str], dict[str, float]] = {}
    exclusions: list[dict[str, object]] = []
    for stratum, group_id in group_keys:
        reasons = list(group_reasons[(stratum, group_id)])
        means: dict[str, float] = {}
        for system_id in SYSTEM_IDS:
            values = []
            for repeat_index in repeats:
                key = (stratum, group_id, system_id, repeat_index)
                if key not in cells:
                    reasons.append(f"{system_id}:repeat:{repeat_index}:MISSING")
                else:
                    values.append(cells[key])
            if len(values) == len(repeats):
                means[system_id] = fmean(values)
        if reasons:
            exclusions.append(
                {
                    "stratum": stratum,
                    "group_id": group_id,
                    "reasons": sorted(set(reasons)),
                }
            )
        else:
            group_means[(stratum, group_id)] = means

    strata = sorted({stratum for stratum, _ in group_keys})
    results: dict[str, dict[str, object]] = {}
    for stratum in strata:
        stratum_groups = sorted(
            (group_id, means)
            for (row_stratum, group_id), means in group_means.items()
            if row_stratum == stratum
        )
        contrasts: dict[str, dict[str, object]] = {}
        for contrast_index, (contrast_id, (left, reference)) in enumerate(
            CONTRASTS.items()
        ):
            differences = [means[left] - means[reference] for _, means in stratum_groups]
            if not differences:
                contrasts[contrast_id] = {
                    "status": "NOT_EVALUABLE_NO_COMPLETE_GROUPS",
                    "group_count": 0,
                }
                continue
            reference_mean = fmean(means[reference] for _, means in stratum_groups)
            ci_low, ci_high = _bootstrap_ci(
                differences,
                resamples=bootstrap_resamples,
                seed=bootstrap_seed + contrast_index,
                confidence=confidence_level,
            )
            contrasts[contrast_id] = {
                "status": "PASS",
                "group_count": len(differences),
                "group_ids": [group_id for group_id, _ in stratum_groups],
                "mean_difference": fmean(differences),
                "median_difference": median(differences),
                "reference_mean": reference_mean,
                "relative_effect": (
                    fmean(differences) / abs(reference_mean)
                    if reference_mean != 0.0
                    else None
                ),
                "bootstrap_ci": [ci_low, ci_high],
                "paired_permutation_pvalue": _paired_permutation_pvalue(differences),
                "paired_t_test": _paired_t_test(differences),
            }

        families: dict[str, object] = {}
        for family_id, contrast_ids in PRIMARY_FAMILIES.items():
            raw = {
                contrast_id: contrasts[contrast_id]["paired_permutation_pvalue"]
                for contrast_id in contrast_ids
                if contrasts[contrast_id]["status"] == "PASS"
            }
            if len(raw) != len(contrast_ids):
                families[family_id] = {
                    "status": "NOT_EVALUABLE_INCOMPLETE_FAMILY",
                    "expected_contrasts": list(contrast_ids),
                }
                continue
            adjusted = _holm_adjust(raw)
            families[family_id] = {
                "status": "PASS",
                "alpha": 0.05,
                "holm_adjusted_pvalues": adjusted,
                "reject": {name: value <= 0.05 for name, value in adjusted.items()},
            }
            for contrast_id, adjusted_value in adjusted.items():
                contrasts[contrast_id]["holm_family"] = family_id
                contrasts[contrast_id]["holm_adjusted_pvalue"] = adjusted_value

        results[stratum] = {
            "complete_group_count": len(stratum_groups),
            "contrasts": contrasts,
            "families": families,
        }

    return {
        "schema_version": "phase5.formal_group_analysis.v1",
        "status": "PASS" if group_means else "NOT_EVALUABLE_NO_COMPLETE_GROUPS",
        "independent_unit": "WORKLOAD_GROUP",
        "repeat_aggregation": "MEAN_WITHIN_GROUP_SYSTEM",
        "missing_policy": "COMPLETE_CASE_GROUP_NO_IMPUTATION",
        "bootstrap_resamples": bootstrap_resamples,
        "bootstrap_seed": bootstrap_seed,
        "confidence_level": confidence_level,
        "systems": list(SYSTEM_IDS),
        "primary_contrasts": list(CONTRASTS),
        "primary_families": {
            name: list(contrasts) for name, contrasts in PRIMARY_FAMILIES.items()
        },
        "complete_group_count": len(group_means),
        "incomplete_groups": exclusions,
        "strata": results,
    }
