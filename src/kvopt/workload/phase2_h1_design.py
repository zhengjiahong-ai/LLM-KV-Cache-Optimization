"""Validate the review-stage design for the sealed H1 holdout campaign."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

H1_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6")
MINIMUM_INDEPENDENT_DRAWS = 40
MINIMUM_DRAWS_PER_FAMILY = 6
REQUIRED_PREFIX_TOKEN_SUPPORT = {16, 32, 128, 256, 512}
REQUIRED_RETURN_BEHAVIORS = {
    "early_within_horizon",
    "near_horizon",
    "late_outside_horizon",
    "no_return_within_trace",
}
REQUIRED_PRESSURE_PATTERNS = {
    "single_shallow",
    "single_deep_multi_release",
    "repeated_pressure",
}
REQUIRED_OWNERSHIP_PATTERNS = {
    "exclusive",
    "shared_prefix",
}


class H1CampaignDesignError(ValueError):
    """Raised when an H1 design violates the preregistered campaign contract."""


def load_h1_campaign_design(path: str | Path) -> dict[str, Any]:
    """Load and validate a design manifest without materializing any holdout."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise H1CampaignDesignError("H1 campaign design must be a JSON object")
    validate_h1_campaign_design(payload)
    return payload


def _require_mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise H1CampaignDesignError(f"{key} must be an object")
    return value


def _require_sequence(parent: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise H1CampaignDesignError(f"{key} must be an array")
    return value


def _distribution_values(
    distributions: Mapping[str, Any],
    name: str,
) -> list[Any]:
    distribution = _require_mapping(distributions, name)
    values = list(_require_sequence(distribution, "values"))
    weights = list(_require_sequence(distribution, "weights"))
    if not values or len(values) != len(weights):
        raise H1CampaignDesignError(
            f"distribution {name} must have equally sized values and weights"
        )
    if any(not isinstance(weight, int) or weight <= 0 for weight in weights):
        raise H1CampaignDesignError(
            f"distribution {name} weights must be positive integers"
        )
    return values


def validate_h1_campaign_design(design: Mapping[str, Any]) -> None:
    """Validate counts, variation, and the freeze-before-materialization guard."""

    if design.get("schema_version") != "phase2a.h1_campaign_design.v1":
        raise H1CampaignDesignError("unsupported H1 campaign design schema")
    if design.get("status") != "AWAITING_M1_REVIEW":
        raise H1CampaignDesignError("review-stage design must await M1 review")
    if design.get("scenario_materialization_authorized") is not False:
        raise H1CampaignDesignError(
            "review-stage design must not authorize scenario materialization"
        )
    if design.get("outcome_materialization_authorized") is not False:
        raise H1CampaignDesignError(
            "review-stage design must not authorize outcome materialization"
        )
    for forbidden_key in ("scenarios", "outcomes", "scenario_draw_seed"):
        if forbidden_key in design:
            raise H1CampaignDesignError(
                f"review-stage design must not contain {forbidden_key}"
            )

    sampling_unit = _require_mapping(design, "statistical_unit")
    if sampling_unit.get("name") != "independent_scenario_draw":
        raise H1CampaignDesignError(
            "statistical unit must be an independent scenario draw"
        )
    if sampling_unit.get("runtime_seed_counts_as_sample") is not False:
        raise H1CampaignDesignError("runtime seeds must not count as samples")

    quotas = _require_mapping(design, "family_draw_quotas")
    if set(quotas) != set(H1_FAMILIES):
        raise H1CampaignDesignError("family quotas must cover exactly F1-F6")
    if any(
        not isinstance(quotas[family], int)
        or quotas[family] < MINIMUM_DRAWS_PER_FAMILY
        for family in H1_FAMILIES
    ):
        raise H1CampaignDesignError(
            f"every family requires at least {MINIMUM_DRAWS_PER_FAMILY} draws"
        )
    draw_count = design.get("independent_scenario_draw_count")
    if not isinstance(draw_count, int) or draw_count < MINIMUM_INDEPENDENT_DRAWS:
        raise H1CampaignDesignError(
            f"campaign requires at least {MINIMUM_INDEPENDENT_DRAWS} draws"
        )
    if draw_count != sum(quotas.values()):
        raise H1CampaignDesignError("draw count must equal the family quota sum")

    repetitions = _require_mapping(design, "runtime_repetitions")
    seeds = _require_sequence(repetitions, "seeds")
    if len(seeds) < 3 or len(seeds) != len(set(seeds)):
        raise H1CampaignDesignError(
            "runtime repetitions require at least three unique seeds"
        )
    if repetitions.get("purpose") != "runtime_noise_and_reproducibility_only":
        raise H1CampaignDesignError(
            "runtime seed purpose must exclude statistical independence"
        )

    distributions = _require_mapping(design, "predeclared_distributions")
    candidate_counts = set(
        _distribution_values(distributions, "candidate_count")
    )
    if not set(range(2, 7)).issubset(candidate_counts):
        raise H1CampaignDesignError(
            "candidate count distribution must cover 2 through 6"
        )
    prefix_tokens = set(_distribution_values(distributions, "prefix_tokens"))
    if not REQUIRED_PREFIX_TOKEN_SUPPORT.issubset(prefix_tokens):
        raise H1CampaignDesignError(
            "prefix distribution is missing required token support"
        )
    if not REQUIRED_RETURN_BEHAVIORS.issubset(
        set(_distribution_values(distributions, "return_behavior"))
    ):
        raise H1CampaignDesignError(
            "return distribution is missing a required behavior"
        )
    eta_values = set(_distribution_values(distributions, "eta"))
    if len(eta_values) < 3 or eta_values == {1}:
        raise H1CampaignDesignError("eta requires meaningful variation")
    queue_delays = set(_distribution_values(distributions, "queue_delay_seconds"))
    if 0 not in queue_delays or not any(delay > 0 for delay in queue_delays):
        raise H1CampaignDesignError(
            "queue delay must include both zero and positive support"
        )
    if not REQUIRED_PRESSURE_PATTERNS.issubset(
        set(_distribution_values(distributions, "pressure_pattern"))
    ):
        raise H1CampaignDesignError(
            "pressure distribution must cover shallow, multi-release, and repeated pressure"
        )
    if not REQUIRED_OWNERSHIP_PATTERNS.issubset(
        set(_distribution_values(distributions, "ownership_pattern"))
    ):
        raise H1CampaignDesignError(
            "ownership distribution must include exclusive and shared prefixes"
        )

    freeze = _require_mapping(design, "freeze_protocol")
    if freeze.get("outcomes_hidden_until_freeze") is not True:
        raise H1CampaignDesignError("holdout outcomes must remain hidden")
    required_inputs = set(_require_sequence(freeze, "required_frozen_inputs"))
    if not {
        "distribution_manifest_sha256",
        "scenario_manifest_sha256",
        "rule_implementation_sha256",
        "acceptance_protocol_sha256",
        "epsilon_latency_calibration_sha256",
    }.issubset(required_inputs):
        raise H1CampaignDesignError("freeze protocol is missing required hashes")

    scenario_gates = _require_sequence(
        design, "scenario_materialization_gates"
    )
    if "M1_DESIGN_APPROVAL" not in scenario_gates:
        raise H1CampaignDesignError(
            "M1 approval must gate scenario materialization"
        )
    outcome_gates = _require_sequence(design, "outcome_materialization_gates")
    if "SEALED_SCENARIO_MANIFEST" not in outcome_gates:
        raise H1CampaignDesignError(
            "a sealed scenario manifest must gate outcome materialization"
        )
    if "LEVEL_B_OBSERVATION_SEAM_READY" not in outcome_gates:
        raise H1CampaignDesignError(
            "Level-B observation readiness must gate outcome materialization"
        )
