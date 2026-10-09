"""Materialize and seal the authorized H1 independent scenario draws."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from .phase2_h1_design import (
    H1_FAMILIES,
    load_h1_campaign_design,
    load_h1_materialization_freeze,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _choice(generator: random.Random, distribution: dict[str, Any]) -> Any:
    return generator.choices(distribution["values"], weights=distribution["weights"], k=1)[0]


def _varied_choices(
    generator: random.Random, distribution: dict[str, Any], count: int
) -> list[Any]:
    values = [_choice(generator, distribution) for _ in range(count)]
    if count > 1 and len(set(values)) == 1:
        support = distribution["values"]
        replacement = support[(support.index(values[0]) + 1) % len(support)]
        values[-1] = replacement
    return values


def _return_offset(behavior: str, pressure_offset: float, horizon: float) -> float | None:
    if behavior == "early_within_horizon":
        return pressure_offset + 0.25 * horizon
    if behavior == "near_horizon":
        return pressure_offset + 0.95 * horizon
    if behavior == "late_outside_horizon":
        return pressure_offset + 1.5 * horizon
    if behavior == "no_return_within_trace":
        return None
    raise ValueError("unsupported H1 return behavior")


def _draw_scenario(
    generator: random.Random,
    distributions: dict[str, Any],
    family: str,
    family_index: int,
) -> dict[str, object]:
    candidate_count = int(_choice(generator, distributions["candidate_count"]))
    prefix_tokens = [
        int(_choice(generator, distributions["prefix_tokens"])) for _ in range(candidate_count)
    ]
    if family == "F1" and family_index % 2 == 0:
        prefix_tokens = [prefix_tokens[0]] * candidate_count
    elif family in {"F1", "F2"} and candidate_count > 1 and len(set(prefix_tokens)) == 1:
        support = distributions["prefix_tokens"]["values"]
        prefix_tokens[-1] = support[(support.index(prefix_tokens[0]) + 1) % len(support)]
    etas = [
        float(value) for value in _varied_choices(generator, distributions["eta"], candidate_count)
    ]
    queue_delays = [
        float(value)
        for value in _varied_choices(
            generator, distributions["queue_delay_seconds"], candidate_count
        )
    ]
    return_behaviors = [
        str(_choice(generator, distributions["return_behavior"])) for _ in range(candidate_count)
    ]
    if family == "F3" and family_index < 4:
        return_behaviors[0] = "near_horizon"
    if family == "F3" and family_index >= 4:
        return_behaviors[0] = "no_return_within_trace"
    pressure_pattern = str(_choice(generator, distributions["pressure_pattern"]))
    if family == "F4":
        pressure_pattern = "repeated_pressure" if family_index < 4 else "single_deep_multi_release"
    ownership_pattern = str(_choice(generator, distributions["ownership_pattern"]))
    if family == "F6" and family_index < 4:
        ownership_pattern = "shared_prefix"
    concurrency = str(_choice(generator, distributions["concurrency_pattern"]))
    if family == "F5":
        concurrency = distributions["concurrency_pattern"]["values"][family_index % 4]
    horizon = float(generator.choice((2.0, 4.0, 6.0, 8.0)))
    pressure_offset = float(generator.choice((1.0, 1.5, 2.0, 2.5)))
    candidates = []
    for index in range(candidate_count):
        ownership_group = (
            "shared-0"
            if ownership_pattern == "shared_prefix" and index < 2
            else f"exclusive-{index}"
        )
        behavior = return_behaviors[index]
        candidates.append(
            {
                "candidate_id": f"candidate-{index + 1}",
                "prefix_tokens": prefix_tokens[index],
                "eta": etas[index],
                "queue_delay_seconds": queue_delays[index],
                "return_behavior": behavior,
                "planned_return_offset_seconds": _return_offset(behavior, pressure_offset, horizon),
                "tool_type": str(_choice(generator, distributions["tool_type"])),
                "lifecycle_pattern": str(_choice(generator, distributions["lifecycle_pattern"])),
                "ownership_group": ownership_group,
            }
        )
    repeated = pressure_pattern == "repeated_pressure"
    multi_release = pressure_pattern in {"single_deep_multi_release", "repeated_pressure"}
    scenario: dict[str, object] = {
        "family_id": family,
        "candidate_count": candidate_count,
        "analysis_horizon_seconds": horizon,
        "concurrency_pattern": concurrency,
        "ownership_pattern": ownership_pattern,
        "pressure_pattern": pressure_pattern,
        "pressure_stages": 2 if repeated else 1,
        "decisions": 2 if repeated else 1,
        "multi_release": multi_release,
        "repeated_pressure": repeated,
        "pressure_offset_seconds": pressure_offset,
        "candidates": candidates,
        "runtime_seeds": [101, 211, 307],
    }
    signature_payload = {key: value for key, value in scenario.items() if key != "family_id"}
    scenario["structural_sha256"] = _canonical_sha(signature_payload)
    return scenario


def validate_materialized_scenarios(
    scenarios: list[dict[str, object]], freeze: dict[str, Any]
) -> dict[str, object]:
    if len(scenarios) != 42:
        raise ValueError("H1 materialization requires exactly 42 scenarios")
    family_counts = Counter(str(row.get("family_id")) for row in scenarios)
    if family_counts != Counter({family: 7 for family in H1_FAMILIES}):
        raise ValueError("H1 materialization requires exactly seven draws per family")
    signatures = [row.get("structural_sha256") for row in scenarios]
    if len(set(signatures)) != 42:
        raise ValueError("H1 materialized scenarios must be structurally unique")
    for row in scenarios:
        candidates = row.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != row.get("candidate_count"):
            raise ValueError("H1 scenario candidate count is inconsistent")
        if len({candidate["eta"] for candidate in candidates}) < 2:
            raise ValueError("H1 scenario lacks per-candidate eta variation")
        if len({candidate["queue_delay_seconds"] for candidate in candidates}) < 2:
            raise ValueError("H1 scenario lacks per-candidate queue-delay variation")
        if row.get("runtime_seeds") != [101, 211, 307]:
            raise ValueError("H1 runtime seeds differ from the frozen repetitions")
        alignment = int(freeze.get("runtime_block_alignment_tokens", 1))
        if any(int(candidate["prefix_tokens"]) % alignment for candidate in candidates):
            raise ValueError("H1 scenario prefix is not runtime-block aligned")
    quotas = {
        "multi_release": sum(bool(row["multi_release"]) for row in scenarios),
        "near_horizon": sum(
            any(candidate["return_behavior"] == "near_horizon" for candidate in row["candidates"])
            for row in scenarios
        ),
        "no_return_within_trace": sum(
            any(
                candidate["return_behavior"] == "no_return_within_trace"
                for candidate in row["candidates"]
            )
            for row in scenarios
        ),
        "repeated_pressure": sum(bool(row["repeated_pressure"]) for row in scenarios),
        "shared_prefix": sum(row["ownership_pattern"] == "shared_prefix" for row in scenarios),
    }
    for key, required in freeze["minimum_corner_case_draws"].items():
        if quotas[key] < required:
            raise ValueError(f"H1 corner-case quota is not met: {key}")
    return {
        "scenario_count": len(scenarios),
        "family_counts": dict(sorted(family_counts.items())),
        "unique_structural_signature_count": len(set(signatures)),
        "corner_case_counts": quotas,
        "runtime_run_count_after_authorization": 126,
        "runtime_seeds_are_independent_samples": False,
        "runtime_block_alignment_tokens": int(freeze.get("runtime_block_alignment_tokens", 1)),
        "runtime_block_alignment_valid": True,
    }


def materialize_h1_scenarios(design_path: Path, freeze_path: Path, output: Path) -> Path:
    design_path = design_path.resolve()
    freeze_path = freeze_path.resolve()
    design = load_h1_campaign_design(design_path)
    freeze = load_h1_materialization_freeze(freeze_path, design_path)
    generator = random.Random(freeze["sampler_seed"])
    distributions = design["predeclared_distributions"]
    scenarios = []
    signatures: set[str] = set()
    for family in H1_FAMILIES:
        for family_index in range(7):
            for _attempt in range(1000):
                scenario = _draw_scenario(generator, distributions, family, family_index)
                signature = str(scenario["structural_sha256"])
                if signature not in signatures:
                    signatures.add(signature)
                    scenario["scenario_id"] = f"h1-{family.lower()}-draw-{family_index + 1:02d}"
                    scenario["draw_index"] = len(scenarios) + 1
                    scenarios.append(scenario)
                    break
            else:
                raise RuntimeError("failed to draw a structurally unique H1 scenario")
    validation = validate_materialized_scenarios(scenarios, freeze)
    revision = "v2" if design["schema_version"] == "phase2a.h1_campaign_design.v2" else "v1"
    manifest = {
        "schema_version": f"phase2a.h1_sealed_scenario_manifest.{revision}",
        "campaign_id": design["campaign_id"],
        "sampler_seed": freeze["sampler_seed"],
        "distribution_manifest_sha256": _sha(design_path),
        "materialization_freeze_sha256": _sha(freeze_path),
        "scenario_outcomes_materialized": False,
        "formal_h1_outcome_execution_authorized": False,
        "statistical_unit": "independent_scenario_draw",
        "runtime_seed_counts_as_sample": False,
        "validation": validation,
        "scenarios": scenarios,
    }
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "scenario-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    root = Path(__file__).resolve().parents[3]
    seal = {
        "schema_version": f"phase2a.h1_scenario_seal.{revision}",
        "campaign_id": design["campaign_id"],
        "scenario_manifest_sha256": _sha(manifest_path),
        "distribution_manifest_sha256": _sha(design_path),
        "materialization_freeze_sha256": _sha(freeze_path),
        "rule_implementation_sha256": _sha(root / "src/kvopt/costaware/rules.py"),
        "preregistration_implementation_sha256": _sha(
            root / "src/kvopt/costaware/preregistrations.py"
        ),
        "acceptance_implementation_sha256": _sha(root / "src/kvopt/costaware/acceptance.py"),
        "acceptance_protocol_sha256": _sha(root / "docs/phase2a-m4-rule-acceptance-protocol.md"),
        "scenario_count": 42,
        "family_draws": {family: 7 for family in H1_FAMILIES},
        "outcome_execution_authorized": False,
        "status": "SEALED_AWAITING_H1_PRE_EXECUTION_REVIEW",
    }
    seal_path = output / "seal.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n")
    return seal_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(
        "wrote sealed H1 scenarios: "
        f"{materialize_h1_scenarios(arguments.design, arguments.freeze, arguments.output)}"
    )
