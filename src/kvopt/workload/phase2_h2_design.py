"""Validate the review-stage H2 measurement and calibration design."""

from __future__ import annotations

import hashlib
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
FROZEN_COST_GRID = (
    16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 12288,
    16384, 20480, 24576, 26624, 28672, 30720,
)
FROZEN_CONFIRMATORY_GRID = (8192, 12288, 16384, 20480, 24576, 26624, 28672, 30720)


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


def load_h2_formal_freeze_spec(path: str | Path) -> dict[str, Any]:
    """Load frozen decision rules that still prohibit formal measurement."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise H2MeasurementDesignError("H2 formal freeze spec must be an object")
    validate_h2_formal_freeze_spec(payload)
    return payload


def load_h2_final_freeze_record(
    path: str | Path,
    *,
    freeze_spec_path: str | Path | None = None,
    calibration_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the final-review record and optionally verify its bound artifacts."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise H2MeasurementDesignError("H2 final freeze record must be an object")
    validate_h2_final_freeze_record(payload)
    bindings = (
        (freeze_spec_path, "formal_freeze_spec_sha256"),
        (calibration_report_path, "isolated_calibration_report_sha256"),
    )
    for artifact_path, hash_key in bindings:
        if artifact_path is None:
            continue
        actual = hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest()
        if payload[hash_key] != actual:
            raise H2MeasurementDesignError(f"{hash_key} does not match artifact")
    return payload


def validate_h2_measurement_design(design: Mapping[str, Any]) -> None:
    """Validate grids, controls, and calibration-before-threshold ordering."""

    if design.get("schema_version") != "phase2a.h2_measurement_design.v1":
        raise H2MeasurementDesignError("unsupported H2 measurement design schema")
    if design.get("status") != "CALIBRATION_PILOT_AUTHORIZED":
        raise H2MeasurementDesignError("H2 calibration pilot must be authorized")
    if design.get("calibration_pilot_authorized") is not True:
        raise H2MeasurementDesignError("H2 calibration pilot authorization is missing")
    if design.get("formal_measurement_authorized") is not False:
        raise H2MeasurementDesignError(
            "review-stage H2 design must not authorize formal measurement"
        )
    if design.get("formal_verdict_authorized") is not False:
        raise H2MeasurementDesignError("H2 formal verdict must remain locked")
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


def validate_h2_formal_freeze_spec(spec: Mapping[str, Any]) -> None:
    """Enforce the M1/M4 rules without prematurely authorizing outcomes."""

    if spec.get("schema_version") != "phase2a.h2_formal_freeze_spec.v1":
        raise H2MeasurementDesignError("unsupported H2 formal freeze spec schema")
    if spec.get("status") != "RULES_FROZEN_PENDING_ISOLATED_CALIBRATION":
        raise H2MeasurementDesignError("H2 rule freeze has the wrong status")
    for key in (
        "formal_measurement_authorized",
        "formal_verdict_authorized",
        "b1_method_or_implementation_authorized",
    ):
        if spec.get(key) is not False:
            raise H2MeasurementDesignError(f"{key} must remain false")
    if spec.get("formal_measured_repeats") != 9:
        raise H2MeasurementDesignError("formal repeat count must be exactly 9")
    if _integer_list(spec, "complete_prefix_token_grid") != list(FROZEN_COST_GRID):
        raise H2MeasurementDesignError("formal C(r) grid does not match the freeze")

    calibration = _mapping(spec, "isolated_seam_calibration")
    if _integer_list(calibration, "confirmatory_prefix_token_grid") != list(
        FROZEN_CONFIRMATORY_GRID
    ):
        raise H2MeasurementDesignError("isolated calibration grid is not frozen")
    if calibration.get("warmup_repeats") != 2 or calibration.get(
        "measured_repeats"
    ) != 5:
        raise H2MeasurementDesignError("isolated calibration requires 2 + 5 repeats")
    if calibration.get("bootstrap_iterations") != 10_000:
        raise H2MeasurementDesignError("M1 calibration requires 10000 bootstraps")
    if calibration.get("bootstrap_seed") != 20_261_007:
        raise H2MeasurementDesignError("M1 bootstrap seed is not frozen")
    if calibration.get("delta_M1_seconds") is not None:
        raise H2MeasurementDesignError("delta_M1 must await isolated calibration")

    m1 = _mapping(spec, "m1_curvature_rule")
    if m1.get("cross_validation") != "leave_one_prefix_point_out":
        raise H2MeasurementDesignError("M1 must use LOPO cross validation")
    if m1.get("bootstrap_iterations") != 10_000 or m1.get(
        "bootstrap_seed"
    ) != 20_261_007:
        raise H2MeasurementDesignError("M1 formal bootstrap is not frozen")

    m2 = _mapping(spec, "m2_partial_prefix_rule")
    if m2.get("token_tolerance") != 0:
        raise H2MeasurementDesignError("M2 token tolerance must be zero")
    if _integer_list(m2, "retained_leading_blocks") != [0, 16, 32, 48, 64]:
        raise H2MeasurementDesignError("M2 retained-prefix grid is not frozen")

    for name in ("m3_position_rule", "m4_headroom_rule"):
        rule = _mapping(spec, name)
        if rule.get("resolved_effect_tokens") != 16:
            raise H2MeasurementDesignError(f"{name} effect must be 16 tokens")
        if rule.get("supporting_repeats_required") != 8 or rule.get(
            "repeats_per_cell"
        ) != 9:
            raise H2MeasurementDesignError(f"{name} must use the 8-of-9 rule")
        if rule.get("supporting_cells_required") != 10 or rule.get(
            "total_cells"
        ) != 12:
            raise H2MeasurementDesignError(f"{name} must use the 10-of-12 rule")
    if _mapping(spec, "m4_headroom_rule").get("comparator") != (
        "single_prefix_native_lru_entry_path_vs_controlled_trailing_j_oracle"
    ):
        raise H2MeasurementDesignError("M4 single-prefix comparator is not frozen")


def validate_h2_final_freeze_record(record: Mapping[str, Any]) -> None:
    """Validate calibration closure while retaining the final review gate."""

    if record.get("schema_version") != "phase2a.h2_final_freeze_record.v1":
        raise H2MeasurementDesignError("unsupported H2 final freeze record schema")
    if record.get("status") != "AWAITING_M1_M4_FINAL_REVIEW":
        raise H2MeasurementDesignError("H2 final freeze record must await review")
    for key in (
        "formal_measurement_authorized",
        "formal_verdict_authorized",
        "b1_method_or_implementation_authorized",
    ):
        if record.get(key) is not False:
            raise H2MeasurementDesignError(f"{key} must remain false before review")
    if record.get("formal_measured_repeats") != 9:
        raise H2MeasurementDesignError("final freeze must retain nine repeats")
    delta = record.get("delta_M1_seconds")
    if (
        isinstance(delta, bool)
        or not isinstance(delta, (int, float))
        or not 0 < float(delta) < 1
    ):
        raise H2MeasurementDesignError("delta_M1_seconds must be in (0, 1)")
    if record.get("primary_observation") != (
        "isolated_native_prefill_elapsed_seconds"
    ):
        raise H2MeasurementDesignError("final freeze has the wrong primary observation")
    if record.get("calibration_run_count") != 56:
        raise H2MeasurementDesignError("final freeze requires all 56 calibration runs")
    if record.get("calibration_measured_run_count") != 40:
        raise H2MeasurementDesignError("final freeze requires 40 measured runs")
    if record.get("calibration_git_dirty") is not False:
        raise H2MeasurementDesignError("final freeze requires a clean calibration")
    for key in (
        "formal_freeze_spec_sha256",
        "isolated_calibration_campaign_sha256",
        "isolated_calibration_execution_sha256",
        "isolated_calibration_report_sha256",
        "calibration_code_git_sha",
        "vllm_metal_source_commit",
        "model_revision",
        "tokenizer_revision",
    ):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            raise H2MeasurementDesignError(f"{key} must be non-empty text")
