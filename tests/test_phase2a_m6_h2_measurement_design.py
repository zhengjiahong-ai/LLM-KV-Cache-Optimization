import copy
from pathlib import Path

import pytest

from kvopt.workload.phase2_h2_design import (
    H2MeasurementDesignError,
    load_h2_measurement_design,
    validate_h2_measurement_design,
)

DESIGN = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "h2-measurement-design.json"
)


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
