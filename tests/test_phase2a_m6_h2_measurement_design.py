import copy
from pathlib import Path

import pytest

from kvopt.workload.phase2_h2_design import (
    H2MeasurementDesignError,
    load_h2_final_freeze_record,
    load_h2_formal_freeze_spec,
    load_h2_measurement_design,
    validate_h2_final_freeze_record,
    validate_h2_formal_freeze_spec,
    validate_h2_measurement_design,
)

DESIGN = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "h2-measurement-design.json"
)
FREEZE_SPEC = DESIGN.with_name("h2-formal-freeze-spec.json")
FINAL_FREEZE = DESIGN.with_name("h2-final-freeze-record.json")


def test_h2_design_covers_long_context_and_partial_prefix_controls() -> None:
    design = load_h2_measurement_design(DESIGN)

    grid = design["m1_cost_curve"]["prefix_token_grid"]
    assert 24576 in grid
    assert len([point for point in grid if point > 24576]) >= 3
    assert design["m2_partial_prefix_apc"]["retained_leading_blocks"] == [
        0,
        16,
        32,
        48,
        64,
    ]
    assert design["m2_partial_prefix_apc"]["no_eviction_rerequest_control"]


def test_h2_design_keeps_thresholds_and_b1_locked() -> None:
    design = load_h2_measurement_design(DESIGN)

    assert design["numeric_thresholds"]["status"] == (
        "UNFROZEN_PENDING_CALIBRATION"
    )
    assert all(
        value is None
        for key, value in design["numeric_thresholds"].items()
        if key != "status"
    )
    assert not design["formal_measurement_authorized"]
    assert design["calibration_pilot_authorized"]
    assert not design["formal_verdict_authorized"]
    assert not design["b1_method_or_implementation_authorized"]


def test_h2_design_rejects_short_cost_grid() -> None:
    design = load_h2_measurement_design(DESIGN)
    invalid = copy.deepcopy(design)
    invalid["m1_cost_curve"]["prefix_token_grid"] = [16, 32, 128, 256, 512]

    with pytest.raises(H2MeasurementDesignError, match="required point"):
        validate_h2_measurement_design(invalid)


def test_h2_design_rejects_threshold_chosen_before_calibration() -> None:
    design = load_h2_measurement_design(DESIGN)
    invalid = copy.deepcopy(design)
    invalid["numeric_thresholds"]["m1_fit_improvement"] = 0.02

    with pytest.raises(H2MeasurementDesignError, match="must be null"):
        validate_h2_measurement_design(invalid)


def test_h2_formal_freeze_spec_records_reviewed_rules_but_stays_locked() -> None:
    spec = load_h2_formal_freeze_spec(FREEZE_SPEC)

    assert spec["formal_measured_repeats"] == 9
    assert spec["isolated_seam_calibration"]["delta_M1_seconds"] is None
    assert spec["m2_partial_prefix_rule"]["token_tolerance"] == 0
    assert spec["m3_position_rule"]["supporting_repeats_required"] == 8
    assert spec["m4_headroom_rule"]["supporting_cells_required"] == 10
    assert not spec["formal_measurement_authorized"]
    assert not spec["formal_verdict_authorized"]
    assert not spec["b1_method_or_implementation_authorized"]


def test_h2_formal_freeze_rejects_premature_delta_or_authority() -> None:
    spec = load_h2_formal_freeze_spec(FREEZE_SPEC)
    with_delta = copy.deepcopy(spec)
    with_delta["isolated_seam_calibration"]["delta_M1_seconds"] = 0.01
    with pytest.raises(H2MeasurementDesignError, match="await isolated"):
        validate_h2_formal_freeze_spec(with_delta)

    authorized = copy.deepcopy(spec)
    authorized["formal_measurement_authorized"] = True
    with pytest.raises(H2MeasurementDesignError, match="must remain false"):
        validate_h2_formal_freeze_spec(authorized)


def test_h2_formal_freeze_rejects_changed_reproducibility_rule() -> None:
    spec = load_h2_formal_freeze_spec(FREEZE_SPEC)
    invalid = copy.deepcopy(spec)
    invalid["m3_position_rule"]["supporting_repeats_required"] = 7

    with pytest.raises(H2MeasurementDesignError, match="8-of-9"):
        validate_h2_formal_freeze_spec(invalid)


def test_h2_final_freeze_records_delta_but_awaits_review() -> None:
    record = load_h2_final_freeze_record(
        FINAL_FREEZE,
        freeze_spec_path=FREEZE_SPEC,
    )

    assert record["delta_M1_seconds"] == pytest.approx(0.19029591700382298)
    assert record["formal_measured_repeats"] == 9
    assert record["calibration_run_count"] == 56
    assert record["calibration_measured_run_count"] == 40
    assert not record["formal_measurement_authorized"]
    assert not record["formal_verdict_authorized"]
    assert not record["b1_method_or_implementation_authorized"]


def test_h2_final_freeze_rejects_premature_authority() -> None:
    record = load_h2_final_freeze_record(FINAL_FREEZE)
    invalid = copy.deepcopy(record)
    invalid["formal_measurement_authorized"] = True

    with pytest.raises(H2MeasurementDesignError, match="must remain false"):
        validate_h2_final_freeze_record(invalid)
