import copy
from pathlib import Path

import pytest

from kvopt.workload.phase2_h1_design import (
    H1CampaignDesignError,
    load_h1_campaign_design,
    validate_h1_campaign_design,
)

DESIGN = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "h1-independent-campaign-design.json"
)


def test_h1_design_has_independent_family_draws_and_runtime_repeats() -> None:
    design = load_h1_campaign_design(DESIGN)

    assert design["independent_scenario_draw_count"] == 42
    assert design["family_draw_quotas"] == {
        family: 7 for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    assert len(design["runtime_repetitions"]["seeds"]) == 3
    assert not design["statistical_unit"]["runtime_seed_counts_as_sample"]


def test_h1_design_is_review_only_and_contains_no_materialized_holdout() -> None:
    design = load_h1_campaign_design(DESIGN)

    assert design["status"] == "AWAITING_M1_REVIEW"
    assert not design["scenario_materialization_authorized"]
    assert not design["outcome_materialization_authorized"]
    assert "scenarios" not in design
    assert "outcomes" not in design
    assert "scenario_draw_seed" not in design


def test_h1_design_covers_required_variation() -> None:
    design = load_h1_campaign_design(DESIGN)
    distributions = design["predeclared_distributions"]

    assert set(range(2, 7)).issubset(distributions["candidate_count"]["values"])
    assert {16, 32, 128, 256, 512}.issubset(
        distributions["prefix_tokens"]["values"]
    )
    assert len(distributions["eta"]["values"]) >= 3
    assert 0 in distributions["queue_delay_seconds"]["values"]
    assert any(
        value > 0
        for value in distributions["queue_delay_seconds"]["values"]
    )
    assert "shared_prefix" in distributions["ownership_pattern"]["values"]
    assert "repeated_pressure" in distributions["pressure_pattern"]["values"]


def test_h1_design_rejects_runtime_seeds_as_independent_samples() -> None:
    design = load_h1_campaign_design(DESIGN)
    invalid = copy.deepcopy(design)
    invalid["statistical_unit"]["runtime_seed_counts_as_sample"] = True

    with pytest.raises(H1CampaignDesignError, match="must not count"):
        validate_h1_campaign_design(invalid)


def test_h1_design_rejects_premature_materialization_authority() -> None:
    design = load_h1_campaign_design(DESIGN)
    invalid = copy.deepcopy(design)
    invalid["outcome_materialization_authorized"] = True

    with pytest.raises(
        H1CampaignDesignError,
        match="must not authorize outcome materialization",
    ):
        validate_h1_campaign_design(invalid)
