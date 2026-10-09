"""Validate the review-stage design for the sealed H1 holdout campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

H1_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6")
FROZEN_INDEPENDENT_DRAWS = 42
FROZEN_DRAWS_PER_FAMILY = 7
REQUIRED_CANDIDATE_COUNT_SUPPORT = set(range(2, 8))
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


def load_h1_materialization_freeze(
    path: str | Path,
    distribution_path: str | Path,
) -> dict[str, Any]:
    """Load an immutable authorization record and bind it to its distribution."""

    freeze_path = Path(path)
    distribution_path = Path(distribution_path)
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise H1CampaignDesignError("H1 materialization freeze must be an object")
    validate_h1_materialization_freeze(payload)
    actual_sha = hashlib.sha256(distribution_path.read_bytes()).hexdigest()
    if payload["distribution_manifest_sha256"] != actual_sha:
        raise H1CampaignDesignError("materialization freeze distribution hash does not match")
    load_h1_campaign_design(distribution_path)
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
        raise H1CampaignDesignError(f"distribution {name} weights must be positive integers")
    return values


def validate_h1_campaign_design(design: Mapping[str, Any]) -> None:
    """Validate counts, variation, and the freeze-before-materialization guard."""

    schema = design.get("schema_version")
    if schema not in {
        "phase2a.h1_campaign_design.v1",
        "phase2a.h1_campaign_design.v2",
    }:
        raise H1CampaignDesignError("unsupported H1 campaign design schema")
    if schema == "phase2a.h1_campaign_design.v1":
        if design.get("status") != "AWAITING_M1_REVIEW":
            raise H1CampaignDesignError("review-stage design must await M1 review")
        if design.get("scenario_materialization_authorized") is not False:
            raise H1CampaignDesignError(
                "review-stage design must not authorize scenario materialization"
            )
    else:
        if design.get("status") != "ALIGNMENT_REVISION_APPROVED_FOR_REMATERIALIZATION":
            raise H1CampaignDesignError("v2 design must record D1 approval")
        if design.get("scenario_materialization_authorized") is not True:
            raise H1CampaignDesignError("v2 design must authorize rematerialization")
        alignment = _require_mapping(design, "sampling_constraints").get(
            "runtime_block_alignment_tokens"
        )
        if alignment != 16:
            raise H1CampaignDesignError("v2 design must freeze 16-token alignment")
    if design.get("outcome_materialization_authorized") is not False:
        raise H1CampaignDesignError(
            "review-stage design must not authorize outcome materialization"
        )
    for forbidden_key in ("scenarios", "outcomes", "scenario_draw_seed"):
        if forbidden_key in design:
            raise H1CampaignDesignError(f"review-stage design must not contain {forbidden_key}")

    sampling_unit = _require_mapping(design, "statistical_unit")
    if sampling_unit.get("name") != "independent_scenario_draw":
        raise H1CampaignDesignError("statistical unit must be an independent scenario draw")
    if sampling_unit.get("runtime_seed_counts_as_sample") is not False:
        raise H1CampaignDesignError("runtime seeds must not count as samples")

    quotas = _require_mapping(design, "family_draw_quotas")
    if set(quotas) != set(H1_FAMILIES):
        raise H1CampaignDesignError("family quotas must cover exactly F1-F6")
    if any(quotas[family] != FROZEN_DRAWS_PER_FAMILY for family in H1_FAMILIES):
        raise H1CampaignDesignError(
            f"every family requires exactly {FROZEN_DRAWS_PER_FAMILY} draws"
        )
    draw_count = design.get("independent_scenario_draw_count")
    if draw_count != FROZEN_INDEPENDENT_DRAWS:
        raise H1CampaignDesignError(f"campaign requires exactly {FROZEN_INDEPENDENT_DRAWS} draws")
    if draw_count != sum(quotas.values()):
        raise H1CampaignDesignError("draw count must equal the family quota sum")

    repetitions = _require_mapping(design, "runtime_repetitions")
    seeds = _require_sequence(repetitions, "seeds")
    if len(seeds) < 3 or len(seeds) != len(set(seeds)):
        raise H1CampaignDesignError("runtime repetitions require at least three unique seeds")
    if repetitions.get("purpose") != "runtime_noise_and_reproducibility_only":
        raise H1CampaignDesignError("runtime seed purpose must exclude statistical independence")

    distributions = _require_mapping(design, "predeclared_distributions")
    candidate_counts = set(_distribution_values(distributions, "candidate_count"))
    if not REQUIRED_CANDIDATE_COUNT_SUPPORT.issubset(candidate_counts):
        raise H1CampaignDesignError("candidate count distribution must cover 2 through 7")
    prefix_tokens = set(_distribution_values(distributions, "prefix_tokens"))
    if not REQUIRED_PREFIX_TOKEN_SUPPORT.issubset(prefix_tokens):
        raise H1CampaignDesignError("prefix distribution is missing required token support")
    if not REQUIRED_RETURN_BEHAVIORS.issubset(
        set(_distribution_values(distributions, "return_behavior"))
    ):
        raise H1CampaignDesignError("return distribution is missing a required behavior")
    eta_values = set(_distribution_values(distributions, "eta"))
    if len(eta_values) < 3 or eta_values == {1}:
        raise H1CampaignDesignError("eta requires meaningful variation")
    queue_delays = set(_distribution_values(distributions, "queue_delay_seconds"))
    if 0 not in queue_delays or not any(delay > 0 for delay in queue_delays):
        raise H1CampaignDesignError("queue delay must include both zero and positive support")
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

    scenario_gates = _require_sequence(design, "scenario_materialization_gates")
    expected_scenario_gate = (
        "M1_DESIGN_APPROVAL"
        if schema == "phase2a.h1_campaign_design.v1"
        else "M1_PRE_EXECUTION_REVIEW_2026-10-09_D1"
    )
    if expected_scenario_gate not in scenario_gates:
        raise H1CampaignDesignError("M1 approval must gate scenario materialization")
    outcome_gates = _require_sequence(design, "outcome_materialization_gates")
    if "SEALED_SCENARIO_MANIFEST" not in outcome_gates:
        raise H1CampaignDesignError("a sealed scenario manifest must gate outcome materialization")
    if "LEVEL_B_OBSERVATION_SEAM_READY" not in outcome_gates:
        raise H1CampaignDesignError(
            "Level-B observation readiness must gate outcome materialization"
        )


def validate_h1_materialization_freeze(freeze: Mapping[str, Any]) -> None:
    """Validate approval to materialize scenarios, never runtime outcomes."""

    schema = freeze.get("schema_version")
    if schema not in {
        "phase2a.h1_scenario_materialization_freeze.v1",
        "phase2a.h1_scenario_materialization_freeze.v2",
    }:
        raise H1CampaignDesignError("unsupported H1 materialization freeze schema")
    if schema == "phase2a.h1_scenario_materialization_freeze.v1":
        if freeze.get("status") != "SCENARIO_MATERIALIZATION_AUTHORIZED":
            raise H1CampaignDesignError("freeze must authorize scenario materialization")
        if freeze.get("m1_authorization_status") != "APPROVED_WITH_MINOR_FIXES":
            raise H1CampaignDesignError("freeze must record the M1 authorization")
    else:
        if freeze.get("status") != "ALIGNMENT_REVISION_REMATERIALIZATION_AUTHORIZED":
            raise H1CampaignDesignError("v2 freeze must record D1 authorization")
        if freeze.get("runtime_block_alignment_tokens") != 16:
            raise H1CampaignDesignError("v2 freeze must require 16-token alignment")
    if freeze.get("outcome_execution_authorized") is not False:
        raise H1CampaignDesignError("freeze must not authorize outcome execution")
    if freeze.get("expected_draw_count") != FROZEN_INDEPENDENT_DRAWS:
        raise H1CampaignDesignError("freeze must require exactly 42 draws")
    quotas = _require_mapping(freeze, "family_quotas")
    if set(quotas) != set(H1_FAMILIES) or any(
        quotas[family] != FROZEN_DRAWS_PER_FAMILY for family in H1_FAMILIES
    ):
        raise H1CampaignDesignError("freeze must require exactly 7 draws per family")
    if not isinstance(freeze.get("sampler_seed"), int):
        raise H1CampaignDesignError("freeze sampler_seed must be an integer")
    if freeze.get("structural_uniqueness_required") is not True:
        raise H1CampaignDesignError("freeze must require structural uniqueness")
    corner_quotas = _require_mapping(freeze, "minimum_corner_case_draws")
    required_corner_quotas = {
        "multi_release": 4,
        "near_horizon": 4,
        "no_return_within_trace": 3,
        "repeated_pressure": 4,
        "shared_prefix": 4,
    }
    if dict(corner_quotas) != required_corner_quotas:
        raise H1CampaignDesignError("freeze corner-case quotas do not match approval")
    required_identity = (
        ("distribution_manifest_sha256", "approved_distribution_commit")
        if schema == "phase2a.h1_scenario_materialization_freeze.v1"
        else ("distribution_manifest_sha256", "reviewed_pre_execution_commit")
    )
    for key in required_identity:
        value = freeze.get(key)
        if not isinstance(value, str) or not value:
            raise H1CampaignDesignError(f"freeze {key} must be non-empty text")
