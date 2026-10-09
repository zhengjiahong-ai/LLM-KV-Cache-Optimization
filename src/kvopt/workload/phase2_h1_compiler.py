"""Compile H1 abstract scenarios into auditable Phase 2 inputs.

This module prepares inputs only. It never runs a sealed holdout and never
authorizes a challenger runtime-policy switch.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .phase2 import Phase2Trace, PlannedRequest, PressureStage

BLOCK_SIZE = 16


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _candidate_offsets(pattern: str, count: int) -> list[float]:
    if pattern == "serialized":
        return [0.5 * index for index in range(count)]
    if pattern == "staggered_overlap":
        return [0.1 * index for index in range(count)]
    if pattern == "burst_overlap":
        return [0.0 if index < 3 else 0.1 for index in range(count)]
    if pattern == "sustained_queue":
        return [0.0 for _ in range(count)]
    raise ValueError(f"unsupported concurrency pattern: {pattern}")


def _program_id(index: int) -> str:
    return f"h1-agent-{index + 1}"


def compile_h1_scenario(
    scenario: Mapping[str, Any], base_config: Mapping[str, Any]
) -> tuple[dict[str, object], Phase2Trace, dict[str, object]]:
    """Compile one scenario and emit a field-level evidence contract."""
    scenario_id = scenario.get("scenario_id")
    family_id = scenario.get("family_id")
    candidates = scenario.get("candidates")
    if not isinstance(scenario_id, str) or not isinstance(family_id, str):
        raise TypeError("scenario identity must be text")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("H1 scenario requires at least two candidates")
    if scenario.get("candidate_count") != len(candidates):
        raise ValueError("candidate_count does not match candidates")
    pressure_offset = float(scenario["pressure_offset_seconds"])
    horizon = float(scenario["analysis_horizon_seconds"])
    offsets = _candidate_offsets(str(scenario["concurrency_pattern"]), len(candidates))

    requests: list[PlannedRequest] = []
    prefix_sizes: dict[str, int] = {}
    candidate_contracts: list[dict[str, object]] = []
    shared_prompts: dict[str, str] = {}
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise TypeError("candidate must be an object")
        program_id = _program_id(index)
        tokens = int(raw["prefix_tokens"])
        if tokens % BLOCK_SIZE:
            raise ValueError("candidate prefix must align to the runtime block size")
        ownership = str(raw["ownership_group"])
        prefix_prompt = shared_prompts.setdefault(
            ownership, f"H1 reusable prefix for ownership group {ownership}"
        )
        first_offset = offsets[index]
        behavior = str(raw["return_behavior"])
        declared_return = raw.get("planned_return_offset_seconds")
        if declared_return is None:
            # A cleanup request after the analysis window keeps the Phase 2 trace
            # lifecycle valid while preserving censoring within the H1 horizon.
            return_offset = pressure_offset + 2.0 * horizon + 0.1 + index * 0.01
            return_role = "post_horizon_cleanup_not_an_h1_return"
        else:
            return_offset = float(declared_return)
            return_role = "declared_h1_return"
        lifecycle = str(raw["lifecycle_pattern"])
        tool = str(raw["tool_type"])
        requests.append(
            PlannedRequest(
                program_id=program_id,
                request_id=f"{program_id}:turn:1",
                turn_index=1,
                planned_arrival_offset_seconds=first_offset,
                prompt=f"establish {program_id}",
                prefix_prompt=prefix_prompt,
                is_terminal=False,
                next_tool_type=tool,
                tool_gap_seconds=max(0.0, return_offset - first_offset),
            )
        )
        if lifecycle == "multi_tool_return":
            middle = min(return_offset - 0.001, first_offset + (return_offset - first_offset) / 2)
            requests.append(
                PlannedRequest(
                    program_id=program_id,
                    request_id=f"{program_id}:turn:2",
                    turn_index=2,
                    planned_arrival_offset_seconds=middle,
                    prompt=f"intermediate tool return for {program_id}",
                    prefix_prompt=prefix_prompt,
                    is_terminal=False,
                    next_tool_type=tool,
                    tool_gap_seconds=max(0.0, return_offset - middle),
                )
            )
            final_turn = 3
        else:
            final_turn = 2
        requests.append(
            PlannedRequest(
                program_id=program_id,
                request_id=f"{program_id}:turn:{final_turn}",
                turn_index=final_turn,
                planned_arrival_offset_seconds=return_offset,
                prompt=f"{return_role} for {program_id}",
                prefix_prompt=prefix_prompt,
                is_terminal=True,
                next_tool_type=None,
                tool_gap_seconds=None,
            )
        )
        prefix_sizes[program_id] = tokens
        candidate_contracts.append(
            {
                "candidate_id": raw["candidate_id"],
                "program_id": program_id,
                "controlled_inputs": {
                    "prefix_tokens": tokens,
                    "initial_arrival_offset_seconds": first_offset,
                    "tool_type": tool,
                    "lifecycle_pattern": lifecycle,
                    "ownership_group": ownership,
                    "return_behavior": behavior,
                },
                "trace_derived_proxy_inputs": {
                    "eta": float(raw["eta"]),
                    "queue_delay_seconds": float(raw["queue_delay_seconds"]),
                    "planned_return_offset_seconds": declared_return,
                },
                "native_observation_obligations": [
                    "eta",
                    "queue_delay_t_seconds",
                    "retention_deadline_timestamp",
                    "native_cached_prefix_tokens",
                    "observed_recomputed_tokens",
                ],
                "return_request_id": (
                    None if declared_return is None else f"{program_id}:turn:{final_turn}"
                ),
                "cleanup_request_id": (
                    f"{program_id}:turn:{final_turn}" if declared_return is None else None
                ),
            }
        )

    stages = 2 if scenario.get("repeated_pressure") is True else 1
    # Keep repeated pressure ahead of the earliest return/cleanup boundary so
    # that the second stage cannot silently lose every protected candidate.
    pressure_offsets = [
        pressure_offset + index * max(0.25, horizon * 0.125) for index in range(stages)
    ]
    pressure_blocks = max(1, math.ceil(sum(prefix_sizes.values()) / BLOCK_SIZE / 2))
    if scenario.get("multi_release") is not True:
        pressure_blocks = max(1, min(pressure_blocks, min(prefix_sizes.values()) // BLOCK_SIZE))
    stage_blocks = [pressure_blocks * (index + 1) for index in range(stages)]
    trace = Phase2Trace(
        trace_id=f"phase2a-h1-compiled-{scenario_id}-v1",
        requests=tuple(requests),
        pressure_stages=tuple(
            PressureStage(
                stage_id=f"h1-pressure-{index + 1}",
                planned_arrival_offset_seconds=offset,
                prompt=f"H1 pressure {scenario_id} stage {index + 1}",
                max_requests=max(2, len(candidates)),
                stop_on_forced_release=True,
            )
            for index, offset in enumerate(pressure_offsets)
        ),
    )
    config = copy.deepcopy(dict(base_config))
    config.update(
        {
            "trace": f"{scenario_id}.trace.json",
            "seed": 101,
            "campaign_kind": "h1_compiler_fidelity_validation",
            "profiling_scenario_id": scenario_id,
            "profiling_scenario_family": family_id,
            "analysis_horizon_seconds": horizon,
        }
    )
    cache = config.setdefault("cache", {})
    pressure = config.setdefault("pressure", {})
    options = config.setdefault("backend_options", {})
    if (
        not isinstance(cache, dict)
        or not isinstance(pressure, dict)
        or not isinstance(options, dict)
    ):
        raise TypeError("base config cache, pressure, and backend_options must be objects")
    initial_shortage = min(
        pressure_blocks, max(1, len(candidates) if scenario.get("multi_release") else 1)
    )
    cache["block_size"] = BLOCK_SIZE
    cache["block_override"] = (
        sum(value // BLOCK_SIZE for value in prefix_sizes.values())
        + pressure_blocks
        + 1
        - initial_shortage
    )
    pressure.update(
        {
            "required_blocks": pressure_blocks,
            "initial_shortage_blocks": initial_shortage,
            "safety_ceiling": max(3, len(candidates)),
            "stage_required_blocks": stage_blocks,
        }
    )
    options.update(
        {
            "program_prefix_tokens": prefix_sizes,
            "pressure_prompt_tokens": pressure_blocks * BLOCK_SIZE,
            "pressure_stage_prompt_tokens": {
                f"h1-pressure-{index + 1}": blocks * BLOCK_SIZE
                for index, blocks in enumerate(stage_blocks)
            },
            "execute_planned_timing": True,
        }
    )
    evidence = {
        "schema_version": "phase2a.h1_compiler_evidence_contract.v1",
        "scenario_id": scenario_id,
        "family_id": family_id,
        "formal_h1_outcome_execution_authorized": False,
        "challenger_runtime_policy_switch_authorized": False,
        "evidence_tier": "LEVEL_A_PROXY_FIRST",
        "primary_metric": "planned_return_weighted_prefill_proxy",
        "controlled_input_fields": [
            "prefix_tokens",
            "initial_arrival_offset_seconds",
            "tool_type",
            "lifecycle_pattern",
            "ownership_group",
            "return_behavior",
            "pressure_pattern",
            "concurrency_pattern",
        ],
        "trace_derived_proxy_fields": [
            "planned_return_offset_seconds",
            "eta",
            "queue_delay_seconds",
        ],
        "native_observation_fields": [
            "native_cached_prefix_tokens",
            "observed_recomputed_tokens",
            "native_queue_delay_seconds",
            "retention_deadline_timestamp",
        ],
        "candidate_contracts": candidate_contracts,
        "pressure_contract": {
            "pattern": scenario["pressure_pattern"],
            "stage_count": stages,
            "stage_required_blocks": stage_blocks,
            "multi_release_required": scenario["multi_release"],
            "forced_release_decision_required_per_stage": True,
        },
        "silent_fallback_permitted": False,
    }
    return config, trace, evidence


def non_holdout_fixtures() -> tuple[dict[str, object], ...]:
    """Small fixtures covering all compiler axes without using sealed draws."""
    common = {
        "family_id": "FIXTURE",
        "analysis_horizon_seconds": 4.0,
        "pressure_offset_seconds": 1.5,
        "runtime_seeds": [999],
    }
    return (
        {
            **common,
            "scenario_id": "h1-fixture-exclusive-repeated",
            "candidate_count": 2,
            "concurrency_pattern": "staggered_overlap",
            "ownership_pattern": "exclusive",
            "pressure_pattern": "repeated_pressure",
            "pressure_stages": 2,
            "decisions": 2,
            "multi_release": True,
            "repeated_pressure": True,
            "candidates": [
                {
                    "candidate_id": "fixture-a",
                    "prefix_tokens": 128,
                    "eta": 0.5,
                    "queue_delay_seconds": 0.025,
                    "return_behavior": "early_within_horizon",
                    "planned_return_offset_seconds": 2.5,
                    "tool_type": "search",
                    "lifecycle_pattern": "multi_tool_return",
                    "ownership_group": "exclusive-a",
                },
                {
                    "candidate_id": "fixture-b",
                    "prefix_tokens": 256,
                    "eta": 2.0,
                    "queue_delay_seconds": 0.5,
                    "return_behavior": "late_outside_horizon",
                    "planned_return_offset_seconds": 7.5,
                    "tool_type": "code",
                    "lifecycle_pattern": "terminal_after_return",
                    "ownership_group": "exclusive-b",
                },
            ],
        },
        {
            **common,
            "scenario_id": "h1-fixture-shared-censored",
            "candidate_count": 3,
            "concurrency_pattern": "burst_overlap",
            "ownership_pattern": "shared_prefix",
            "pressure_pattern": "single_deep_multi_release",
            "pressure_stages": 1,
            "decisions": 1,
            "multi_release": True,
            "repeated_pressure": False,
            "candidates": [
                {
                    "candidate_id": "fixture-c",
                    "prefix_tokens": 256,
                    "eta": 0.25,
                    "queue_delay_seconds": 0.0,
                    "return_behavior": "no_return_within_trace",
                    "planned_return_offset_seconds": None,
                    "tool_type": "database",
                    "lifecycle_pattern": "nonreturning_branch",
                    "ownership_group": "shared-0",
                },
                {
                    "candidate_id": "fixture-d",
                    "prefix_tokens": 256,
                    "eta": 1.0,
                    "queue_delay_seconds": 0.1,
                    "return_behavior": "near_horizon",
                    "planned_return_offset_seconds": 5.3,
                    "tool_type": "database",
                    "lifecycle_pattern": "single_tool_return",
                    "ownership_group": "shared-0",
                },
                {
                    "candidate_id": "fixture-e",
                    "prefix_tokens": 64,
                    "eta": 4.0,
                    "queue_delay_seconds": 2.0,
                    "return_behavior": "early_within_horizon",
                    "planned_return_offset_seconds": 2.5,
                    "tool_type": "search",
                    "lifecycle_pattern": "terminal_after_return",
                    "ownership_group": "exclusive-e",
                },
            ],
        },
    )


def materialize_fidelity_campaign(base_config_path: Path, output: Path) -> Path:
    base = json.loads(base_config_path.read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise TypeError("base config must be an object")
    output.mkdir(parents=True, exist_ok=False)
    items = []
    for fixture in non_holdout_fixtures():
        scenario_id = str(fixture["scenario_id"])
        config, trace, evidence = compile_h1_scenario(fixture, base)
        trace_text = json.dumps(trace.to_dict(), indent=2, sort_keys=True) + "\n"
        config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
        evidence_text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        (output / f"{scenario_id}.trace.json").write_text(trace_text, encoding="utf-8")
        (output / f"{scenario_id}.config.json").write_text(config_text, encoding="utf-8")
        (output / f"{scenario_id}.evidence-contract.json").write_text(
            evidence_text, encoding="utf-8"
        )
        items.append(
            {
                "scenario_id": scenario_id,
                "config": f"{scenario_id}.config.json",
                "config_sha256": _sha(config_text),
                "trace_sha256": _sha(trace_text),
                "evidence_contract_sha256": _sha(evidence_text),
            }
        )
    manifest = {
        "schema_version": "phase2a.h1_compiler_fidelity_campaign.v1",
        "campaign_kind": "NON_HOLDOUT_FIDELITY_VALIDATION",
        "formal_h1_outcome_execution_authorized": False,
        "challenger_runtime_policy_switch_authorized": False,
        "fixtures": items,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = materialize_fidelity_campaign(arguments.base_config, arguments.output)
    print(f"wrote H1 non-holdout fidelity campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
