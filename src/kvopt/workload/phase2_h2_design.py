"""Validate the review-stage H2 measurement and calibration design."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REQUIRED_COST_GRID = {
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
    2048,
    4096,
    8192,
    12288,
    16384,
    20480,
    24576,
}


class H2MeasurementDesignError(ValueError):
    """Raised when H2 planning violates the measurement-only protocol."""


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise H2MeasurementDesignError(f"{key} must be an object")
    return value


def _integer_list(parent: Mapping[str, Any], key: str) -> list[int]:
    value = parent.get(key)
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise H2MeasurementDesignError(f"{key} must be an integer array")
    return value


def load_h2_measurement_design(path: str | Path) -> dict[str, Any]:
    """Load an H2 design while refusing premature verdict authorization."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise H2MeasurementDesignError("H2 measurement design must be an object")
    validate_h2_measurement_design(payload)
    return payload


def validate_h2_measurement_design(design: Mapping[str, Any]) -> None:
    """Validate grids, controls, and calibration-before-threshold ordering."""

    if design.get("schema_version") != "phase2a.h2_measurement_design.v1":
        raise H2MeasurementDesignError("unsupported H2 measurement design schema")
    if design.get("status") != "CALIBRATION_PLAN_AWAITING_REVIEW":
        raise H2MeasurementDesignError("H2 design must await calibration review")
    if design.get("formal_measurement_authorized") is not False:
        raise H2MeasurementDesignError(
            "review-stage H2 design must not authorize formal measurement"
        )
    if design.get("b1_method_or_implementation_authorized") is not False:
        raise H2MeasurementDesignError("H2 measurement must not authorize B1")

    calibration = _mapping(design, "calibration")
    pilot_repeats = calibration.get("pilot_repeats_per_point")
    if (
        isinstance(pilot_repeats, bool)
        or not isinstance(pilot_repeats, int)
        or pilot_repeats < 3
    ):
        raise H2MeasurementDesignError(
            "H2 calibration requires at least three pilot repeats per point"
        )
    if calibration.get("formal_repeat_count") is not None:
        raise H2MeasurementDesignError(
            "formal repeat count must remain unset before calibration"
        )

    m1 = _mapping(design, "m1_cost_curve")
    grid = _integer_list(m1, "prefix_token_grid")
    if not REQUIRED_COST_GRID.issubset(grid):
        raise H2MeasurementDesignError("C(r) grid misses a required point")
    if len([point for point in grid if point > 24576]) < 3:
        raise H2MeasurementDesignError(
            "C(r) grid requires at least three points above 24576"
        )
    if m1.get("primary_observation") != "isolated_native_prefill_elapsed_seconds":
        raise H2MeasurementDesignError(
            "isolated native prefill elapsed time must be primary"
        )

    m2 = _mapping(design, "m2_partial_prefix_apc")
    prefix_blocks = m2.get("prefix_blocks")
    if isinstance(prefix_blocks, bool) or not isinstance(prefix_blocks, int):
        raise H2MeasurementDesignError("M2 prefix_blocks must be an integer")
    retained = _integer_list(m2, "retained_leading_blocks")
    if not retained or min(retained) != 0 or max(retained) != prefix_blocks:
        raise H2MeasurementDesignError("M2 requires full-evict and full-retain controls")
    if len([value for value in retained if 0 < value < prefix_blocks]) < 3:
        raise H2MeasurementDesignError(
            "M2 requires at least three partial-prefix points"
        )
    if m2.get("no_eviction_rerequest_control") is not True:
        raise H2MeasurementDesignError("M2 requires a no-eviction re-request control")

    m3 = _mapping(design, "m3_position_effect")
    if set(m3.get("positions", [])) != {"leading", "trailing"}:
        raise H2MeasurementDesignError(
            "M3 requires matched leading and trailing eviction"
        )
    if not _integer_list(m3, "equal_evicted_block_counts"):
        raise H2MeasurementDesignError("M3 requires positive eviction counts")

    m4 = _mapping(design, "m4_extra_headroom")
    if m4.get("comparison") != (
        "best_entry_level_loss_vs_best_block_level_loss"
    ):
        raise H2MeasurementDesignError("M4 headroom comparison is not frozen")

    thresholds = _mapping(design, "numeric_thresholds")
    if thresholds.get("status") != "UNFROZEN_PENDING_CALIBRATION":
        raise H2MeasurementDesignError(
            "numeric thresholds must remain unfrozen before calibration"
        )
    if any(
        value is not None
        for key, value in thresholds.items()
        if key != "status"
    ):
        raise H2MeasurementDesignError(
            "numeric threshold values must be null before calibration"
        )
