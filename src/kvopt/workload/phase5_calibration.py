"""Protocol v1 calibration-set validation and sample-size calculation."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import NormalDist

from .phase5_replay import canonical_sha256

SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "COST_AWARE",
)
BASELINES = ("NATIVE", "CONTINUUM_ADAPTED", "CONTINUUM_OFFICIAL")


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def analyze_calibration(
    records: Sequence[Mapping[str, object]],
    *,
    strata: Sequence[str] = ("SWE_BENCH", "BFCL_WEB_SEARCH"),
    groups_per_stratum: int = 4,
    repeats: int = 3,
    absolute_mde_tokens: float = 512,
    relative_mde_fraction: float = 0.05,
    alpha_family: float = 0.05,
    power: float = 0.8,
    minimum_groups: int = 8,
    maximum_groups: int = 16,
) -> dict[str, object]:
    """Validate all 96 cells and apply the frozen conservative formula.

    ``records`` are independent-evaluator outputs. Calibration is rejected if
    any cell is missing, duplicated, failed, or not disjoint from the declared
    formal cohort. The function never authorizes the formal campaign.
    """

    if not records:
        raise ValueError("calibration records cannot be empty")
    expected_count = len(strata) * groups_per_stratum * len(SYSTEM_IDS) * repeats
    if len(records) != expected_count:
        raise ValueError(f"calibration requires exactly {expected_count} records")
    values: dict[tuple[str, str, str, int], float] = {}
    groups_by_stratum: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if row.get("status") != "PASS":
            raise ValueError("calibration contains a non-PASS record")
        stratum = str(row.get("stratum", ""))
        group_id = str(row.get("group_id", ""))
        system_id = str(row.get("system_id", ""))
        repeat_index = row.get("repeat_index")
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

    alpha_per_contrast = alpha_family / len(BASELINES)
    z_alpha = NormalDist().inv_cdf(1 - alpha_per_contrast / 2)
    z_power = NormalDist().inv_cdf(power)
    factor = (z_alpha + z_power) ** 2
    stratum_reports: dict[str, object] = {}
    campaign_blocked = False
    for stratum in strata:
        group_ids = sorted(groups_by_stratum[stratum])
        native_group_means = [
            statistics.fmean(
                values[(stratum, group_id, "NATIVE", repeat_index)]
                for repeat_index in range(1, repeats + 1)
            )
            for group_id in group_ids
        ]
        native_mean = statistics.fmean(native_group_means)
        mde = max(absolute_mde_tokens, relative_mde_fraction * native_mean)
        contrasts: dict[str, object] = {}
        required_unclamped = 0
        for baseline in BASELINES:
            differences = [
                values[(stratum, group_id, "COST_AWARE", repeat_index)]
                - values[(stratum, group_id, baseline, repeat_index)]
                for group_id in group_ids
                for repeat_index in range(1, repeats + 1)
            ]
            sigma = statistics.stdev(differences)
            required = math.ceil(factor * sigma**2 / mde**2)
            required_unclamped = max(required_unclamped, required)
            contrasts[f"COST_AWARE_vs_{baseline}"] = {
                "paired_observation_count": len(differences),
                "sigma_d": sigma,
                "required_groups_unclamped": required,
            }
        selected = min(max(required_unclamped, minimum_groups), maximum_groups)
        above_cap = required_unclamped > maximum_groups
        campaign_blocked |= above_cap
        stratum_reports[stratum] = {
            "calibration_group_ids": group_ids,
            "native_group_mean_recomputed_tokens": native_mean,
            "mde_tokens": mde,
            "contrasts": contrasts,
            "required_groups_unclamped": required_unclamped,
            "selected_groups_if_authorized": selected,
            "status": (
                "UNDERPOWERED_REQUIRES_M1_DECISION" if above_cap else "CALIBRATED"
            ),
        }
    payload: dict[str, object] = {
        "schema_version": "phase5.calibration_analysis.v1",
        "status": (
            "BLOCKED_REQUIRES_M1_UNDERPOWERED_DECISION"
            if campaign_blocked
            else "CALIBRATION_COMPLETE_EXECUTION_NOT_AUTHORIZED"
        ),
        "record_count": len(records),
        "alpha_family": alpha_family,
        "alpha_per_contrast": alpha_per_contrast,
        "power": power,
        "z_alpha": z_alpha,
        "z_power": z_power,
        "strata": stratum_reports,
        "formal_execution_authorized": False,
        "calibration_reused_as_formal_evidence": False,
    }
    return {**payload, "analysis_sha256": canonical_sha256(payload)}
