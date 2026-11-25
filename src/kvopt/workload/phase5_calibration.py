"""Phase 5 six-system Calibration matrix and analyzer contracts.

The final protocol requires a mixed-model method-of-moments estimator and an
iterative noncentral-t power solve. This module validates the complete 72-run
input and exposes the exact analyzer boundary; it intentionally rejects the
obsolete four-system/z-approximation implementation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from .phase5_replay import canonical_sha256

SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)
CANDIDATE_CONTRASTS = (
    "A1_vs_A0",
    "A3_vs_A0",
    "DVA_vs_A0",
    "A3_vs_A1",
    "DVA_vs_A1",
    "DVA_vs_A3",
)


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def validate_calibration_matrix(
    records: Sequence[Mapping[str, object]],
    *,
    strata: Sequence[str] = ("SWE_BENCH",),
    groups_per_stratum: int = 4,
    repeats: int = 3,
) -> dict[str, object]:
    """Validate the exact 1×4×6×3 Calibration result matrix."""

    expected_count = len(strata) * groups_per_stratum * len(SYSTEM_IDS) * repeats
    if len(records) != expected_count:
        raise ValueError(f"calibration requires exactly {expected_count} records")
    values: dict[tuple[str, str, str, int], float] = {}
    groups_by_stratum: dict[str, set[str]] = defaultdict(set)
    run_ids: set[str] = set()
    for row in records:
        if row.get("status") != "PASS":
            raise ValueError("calibration contains a non-PASS record")
        run_id = str(row.get("run_id", ""))
        stratum = str(row.get("stratum", ""))
        group_id = str(row.get("group_id", ""))
        system_id = str(row.get("system_id", ""))
        repeat_index = row.get("repeat_index")
        if not run_id or run_id in run_ids:
            raise ValueError("calibration run_id must be non-empty and unique")
        run_ids.add(run_id)
        if stratum not in strata or system_id not in SYSTEM_IDS:
            raise ValueError("calibration contains an unknown stratum or system")
        if not group_id:
            raise ValueError("calibration group_id must be non-empty")
        if isinstance(repeat_index, bool) or not isinstance(repeat_index, int):
            raise TypeError("calibration repeat_index must be int")
        if repeat_index not in range(1, repeats + 1):
            raise ValueError("calibration repeat_index is outside the frozen set")
        if row.get("formal_group") is True:
            raise ValueError("calibration Group cannot be reused as formal evidence")
        key = (stratum, group_id, system_id, repeat_index)
        if key in values:
            raise ValueError("duplicate calibration cell")
        values[key] = _finite_number(
            row.get("recomputed_tokens_E_minus_C"), "calibration primary metric"
        )
        groups_by_stratum[stratum].add(group_id)
    if any(len(groups_by_stratum[name]) != groups_per_stratum for name in strata):
        raise ValueError("calibration Group set does not match the frozen design")
    expected_keys = {
        (stratum, group_id, system_id, repeat_index)
        for stratum in strata
        for group_id in groups_by_stratum[stratum]
        for system_id in SYSTEM_IDS
        for repeat_index in range(1, repeats + 1)
    }
    if set(values) != expected_keys:
        raise ValueError("calibration cell matrix is incomplete")
    payload = {
        "schema_version": "phase5.calibration_matrix_validation.v2",
        "status": "PASS",
        "record_count": len(records),
        "systems": list(SYSTEM_IDS),
        "strata": {
            name: {"group_ids": sorted(groups_by_stratum[name])} for name in strata
        },
        "repeats": repeats,
        "formal_execution_authorized": False,
        "calibration_reused_as_formal_evidence": False,
    }
    return {**payload, "matrix_sha256": canonical_sha256(payload)}


def analyze_calibration(
    records: Sequence[Mapping[str, object]],
    *,
    mixed_model_estimator: Callable[
        [Sequence[Mapping[str, object]]], Mapping[str, object]
    ]
    | None = None,
    noncentral_t_solver: Callable[[Mapping[str, object]], Mapping[str, object]]
    | None = None,
) -> dict[str, object]:
    """Run only an explicitly supplied exact Protocol-v1 numerical backend."""

    matrix = validate_calibration_matrix(records)
    if mixed_model_estimator is None or noncentral_t_solver is None:
        raise RuntimeError(
            "exact mixed-model estimator and iterative noncentral-t solver are required"
        )
    variance = dict(mixed_model_estimator(records))
    if variance.get("estimator") != "METHOD_OF_MOMENTS_MIXED_MODEL":
        raise ValueError("Calibration estimator does not match the frozen contract")
    if variance.get("contrast_covariance_size") != 8:
        raise ValueError("Calibration contrast covariance must be 8x8")
    if variance.get("negative_variance_rule") != (
        "TRUNCATE_POINT_AT_ZERO_AND_USE_BOOTSTRAP_UPPER_BOUND"
    ):
        raise ValueError("Calibration negative-variance rule changed")
    sizing = dict(noncentral_t_solver(variance))
    if sizing.get("distribution") != "NONCENTRAL_T_ITERATIVE":
        raise ValueError("Calibration power solver cannot use a z approximation")
    selected = sizing.get("selected_groups_per_stratum")
    if not isinstance(selected, Mapping) or set(selected) != {"SWE_BENCH"}:
        raise ValueError("Calibration sizing lacks the frozen SWE stratum")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 8 <= value <= 16
        for value in selected.values()
    ):
        raise ValueError("Calibration selected N is outside the frozen 8..16 range")
    payload = {
        "schema_version": "phase5.calibration_analysis.v2",
        "status": "CALIBRATION_ANALYZED_EXECUTION_NOT_AUTHORIZED",
        "matrix_sha256": matrix["matrix_sha256"],
        "variance_model": variance,
        "sample_size": sizing,
        "candidate_contrasts": list(CANDIDATE_CONTRASTS),
        "formal_execution_authorized": False,
    }
    return {**payload, "analysis_sha256": canonical_sha256(payload)}
