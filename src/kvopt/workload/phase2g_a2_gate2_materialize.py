"""Materialize the execution-locked Phase 2G A2 Gate 2 campaign."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2c_native_pilot import PILOT_PREFIX_GENERATOR_VERSION
from .phase2g_a1_bounded_materialize import _scenario, _sha, _write

SCHEMA = "phase2g.a2_gate2_distribution.v1"
VALUE_SCHEMA = "phase2g.a2_bounded_value_distribution.v2"
MANIFEST_SCHEMA = "phase2g.a2_gate2_materialization.v1"


def _input_contract(config: dict[str, Any]) -> dict[str, Any]:
    backend = config["backend_options"]
    return {
        "model": config["model"],
        "tokenizer": config["tokenizer"],
        "generation": config["generation"],
        "batching": config["batching"],
        "cache": config["cache"],
        "pressure": config["pressure"],
        "seed": config["seed"],
        "trace": config["trace"],
        "prefix_segments_by_request": backend["prefix_segments_by_request"],
        "program_prefix_tokens": backend["program_prefix_tokens"],
        "pressure_prompt_tokens": backend["pressure_prompt_tokens"],
    }


def _digest(value: object) -> str:
    import hashlib

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_value_evaluation_repairs(
    *,
    family: str,
    trace: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """Apply the preregistered construction repairs without altering v1 artifacts."""
    if family != "F6":
        return
    realized = str(metadata["family_parameters"]["return_realization"])
    if not realized.startswith("omit-"):
        return
    requests = trace["requests"]
    by_program: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        by_program.setdefault(str(request["program_id"]), []).append(request)
    omitted = [rows for rows in by_program.values() if len(rows) == 1]
    if len(omitted) != 1:
        raise ValueError("F6 omission must identify exactly one non-returning program")
    first = omitted[0][0]
    first["is_terminal"] = False
    first["next_tool_type"] = "phase2g-f6"
    first["tool_gap_seconds"] = float(
        metadata["family_parameters"]["declared_return_gap_seconds"][
            list(by_program).index(str(first["program_id"]))
        ]
    )
    metadata["family_parameters"]["omitted_program_id"] = first["program_id"]
    metadata["family_parameters"]["future_nonreturn_leaked_before_pressure"] = False
    trace["allow_incomplete_programs"] = True


def _capacity_basis(
    *, trace: dict[str, Any], request_segments: dict[str, list[list[object]]]
) -> tuple[int, list[str], dict[str, int]]:
    """Return unique content resident by the first pressure stage."""
    first_pressure = min(
        float(stage["planned_arrival_offset_seconds"])
        for stage in trace["pressure_stages"]
    )
    arrived = [
        str(request["request_id"])
        for request in trace["requests"]
        if float(request["planned_arrival_offset_seconds"]) <= first_pressure
    ]
    segments: dict[str, int] = {}
    for request_id in arrived:
        for key, token_count in request_segments[request_id]:
            count = int(token_count)
            if key in segments and segments[str(key)] != count:
                raise ValueError(f"segment size drift for {key}")
            segments[str(key)] = count
    return first_pressure, arrived, segments


def materialize_gate2_campaign(*, distribution_path: Path, output_dir: Path) -> Path:
    distribution: dict[str, Any] = json.loads(distribution_path.read_text(encoding="utf-8"))
    schema = distribution.get("schema_version")
    if schema not in {SCHEMA, VALUE_SCHEMA}:
        raise ValueError("unsupported Phase 2G A2 Gate 2 distribution")
    value_evaluation = schema == VALUE_SCHEMA
    base_distribution_path: Path | None = None
    if value_evaluation:
        base_name = distribution.get("base_distribution")
        if not isinstance(base_name, str) or not base_name:
            raise ValueError("bounded value distribution must bind a base distribution")
        base_distribution_path = distribution_path.parent / base_name
        base = json.loads(base_distribution_path.read_text(encoding="utf-8"))
        if base.get("schema_version") != SCHEMA:
            raise ValueError("bounded value base distribution schema mismatch")
        distribution = {
            **base,
            **distribution,
            "schema_version": VALUE_SCHEMA,
        }
    if distribution.get("execution_authorized") is not False:
        raise ValueError("Gate 2 preparation must remain execution-locked")
    if distribution.get("formal_native_execution_authorized") is not False:
        raise ValueError("formal Native execution has not been authorized")
    if distribution.get("gate1_status") != "LIMITED_PASS":
        raise ValueError("A2 Gate 1 status must be LIMITED_PASS")
    output_dir.mkdir(parents=True, exist_ok=False)

    block_size = int(distribution["block_size_tokens"])
    scenarios: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    for family_index, family_value in enumerate(distribution["families"], start=1):
        family = str(family_value)
        contract = distribution["family_contracts"][family]
        for draw in range(1, int(distribution["independent_draws_per_family"]) + 1):
            scenario_id = f"{family.lower()}-draw-{draw:02d}"
            trace, metadata = _scenario(family, draw, contract)
            if value_evaluation:
                _apply_value_evaluation_repairs(
                    family=family,
                    trace=trace,
                    metadata=metadata,
                )
            trace["trace_id"] = f"phase2g-a2-{family.lower()}-{draw:02d}"
            for request in trace["requests"]:
                request["prompt"] = str(request["prompt"]).replace("Phase 2G A1", "Phase 2G A2")
            for stage in trace["pressure_stages"]:
                stage["prompt"] = str(stage["prompt"]).replace("Phase 2G A1", "Phase 2G A2")
            trace_path = output_dir / f"{scenario_id}.trace.json"
            _write(trace_path, trace)

            pressure_tokens = int(distribution["pressure_prompt_tokens"][(draw - 1) % 3])
            shortage = int(distribution["initial_shortage_blocks"][(draw - 1) % 3])
            pressure_blocks = pressure_tokens // block_size
            unique_segments: dict[str, int] = {}
            for request_segments in metadata["request_segments"].values():
                for key, tokens in request_segments:
                    if key in unique_segments and unique_segments[key] != int(tokens):
                        raise ValueError(f"segment size drift for {key}: {scenario_id}")
                    unique_segments[str(key)] = int(tokens)
            if value_evaluation:
                first_pressure, arrived_requests, capacity_segments = _capacity_basis(
                    trace=trace,
                    request_segments=metadata["request_segments"],
                )
            else:
                first_pressure = None
                arrived_requests = []
                capacity_segments = unique_segments
            protected_blocks = sum(capacity_segments.values()) // block_size
            block_override = protected_blocks + pressure_blocks + 1 - shortage
            if block_override < 37:
                raise ValueError(f"insufficient Metal cache capacity: {scenario_id}")

            scenario_runs: list[str] = []
            scenario_input_digest: str | None = None
            for repeat in distribution["runtime_repeats"]:
                order = (
                    distribution["policies"]
                    if (family_index + draw + int(repeat)) % 2 == 0
                    else list(reversed(distribution["policies"]))
                )
                for order_index, policy_value in enumerate(order, start=1):
                    policy = str(policy_value)
                    run_id = f"{scenario_id}-{policy.lower()}-repeat-{repeat}"
                    config_path = output_dir / f"{run_id}.config.json"
                    config: dict[str, Any] = {
                        "schema_version": "phase2.config.v1",
                        "runtime_mode": "vllm-metal-observability",
                        "backend_factory": distribution["runtime"]["backend_factory"],
                        "backend_revision": (
                            "phase2g-a2-bounded-value-v2"
                            if value_evaluation
                            else "phase2g-a2-gate2-preparation-v1"
                        ),
                        "campaign_kind": "phase2g_a2_gate2_bounded_evaluation",
                        "policy": f"continuum-a0-entry-{policy.lower()}-block",
                        "seed": int(distribution["sampler_seed"]) + family_index * 100 + draw,
                        "observe": True,
                        "model": distribution["model"],
                        "tokenizer": distribution["model"],
                        "generation": {
                            "max_new_tokens": distribution["runtime"]["max_new_tokens"],
                            "temperature": distribution["runtime"]["temperature"],
                        },
                        "batching": {"max_concurrent_requests": 1},
                        "cache": {"block_size": block_size, "block_override": block_override},
                        "pressure": {
                            "initial_shortage_blocks": shortage,
                            "required_blocks": pressure_blocks,
                            "safety_ceiling": metadata["pressure_count"],
                        },
                        "backend_options": {
                            "execute_planned_timing": False,
                            "executor_mode": distribution["runtime"]["executor_mode"],
                            "gpu_memory_utilization": distribution["runtime"]["gpu_memory_utilization"],
                            "phase2c_native_pilot_mode": True,
                            "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                            "phase2g_release_policy": "A0",
                            "phase2g_block_policy": policy,
                            "phase2g_a2_tau_seconds": distribution["a2"]["tau_seconds"],
                            "phase2g_unique_protected_blocks": protected_blocks,
                            "prefix_segments_by_request": metadata["request_segments"],
                            "program_prefix_tokens": metadata["program_prefix_tokens"],
                            "pressure_prompt_tokens": pressure_tokens,
                            "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                        },
                        "trace": trace_path.name,
                        "phase2g_stage": {
                            "stage": "A2_GATE2_PREPARATION",
                            "scenario_id": scenario_id,
                            "family": family,
                            "draw": draw,
                            "policy": policy,
                            "repeat": repeat,
                            "execution_order": order_index,
                            "independent_statistical_unit": scenario_id,
                            "runtime_repeat_is_independent": False,
                            "primary_metric": distribution["primary_metric"],
                            "family_parameters": metadata["family_parameters"],
                        },
                    }
                    input_digest = _digest(_input_contract(config))
                    if scenario_input_digest is None:
                        scenario_input_digest = input_digest
                    elif input_digest != scenario_input_digest:
                        raise ValueError(f"paired input drift: {scenario_id}")
                    _write(config_path, config)
                    scenario_runs.append(run_id)
                    runs.append(
                        {
                            "run_id": run_id,
                            "scenario_id": scenario_id,
                            "family": family,
                            "draw": draw,
                            "policy": policy,
                            "repeat": repeat,
                            "execution_order": order_index,
                            "config": config_path.name,
                            "config_sha256": _sha(config_path),
                            "trace": trace_path.name,
                            "trace_sha256": _sha(trace_path),
                            "input_contract_sha256": input_digest,
                        }
                    )
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "family": family,
                    "draw": draw,
                    "trace": trace_path.name,
                    "trace_sha256": _sha(trace_path),
                    "input_contract_sha256": scenario_input_digest,
                    "entry_count": metadata["entry_count"],
                    "turn_request_count": metadata["turn_request_count"],
                    "pressure_count": metadata["pressure_count"],
                    "family_parameters": metadata["family_parameters"],
                    "capacity_basis": {
                        "mode": (
                            "FIRST_PRESSURE_RESIDENT_UNIQUE_CONTENT"
                            if value_evaluation
                            else "ALL_SCENARIO_UNIQUE_CONTENT"
                        ),
                        "first_pressure_offset_seconds": first_pressure,
                        "arrived_request_ids": arrived_requests,
                        "unique_segment_tokens": capacity_segments,
                        "protected_blocks": protected_blocks,
                    },
                    "design_kind": "PREDEFINED_BALANCED_PARAMETER_GRID",
                    "run_ids": scenario_runs,
                }
            )

    if Counter(str(row["family"]) for row in scenarios) != Counter(
        {family: 6 for family in distribution["families"]}
    ):
        raise ValueError("Gate 2 campaign must contain six scenarios per family")
    if len(scenarios) != 36 or len(runs) != 144:
        raise ValueError("Gate 2 campaign cardinality is invalid")
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "run_kind": distribution["run_kind"],
        "distribution_sha256": _sha(distribution_path),
        "base_distribution_sha256": (
            _sha(base_distribution_path) if base_distribution_path is not None else None
        ),
        "tested_a2_implementation_git_sha": distribution["tested_a2_implementation_git_sha"],
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "independent_statistical_unit": distribution["statistical_unit"],
        "runtime_repeats_are_independent": False,
        "primary_metric": distribution["primary_metric"],
        "statistics": distribution["statistics"],
        "execution_authorized": False,
        "formal_native_execution_authorized": False,
        "outcomes_materialized": False,
        "workload_construction_repairs": (
            {
                "f4_capacity_uses_first_pressure_resident_content": True,
                "f6_nonreturn_not_terminal_before_pressure": True,
                "old_gate2_v3_artifacts_modified": False,
            }
            if value_evaluation
            else None
        ),
        "execution_lock_reason": "M1 authorized preparation only; formal Native Gate 2 execution is pending review",
        "scenarios": scenarios,
        "runs": runs,
    }
    path = output_dir / "manifest.json"
    _write(path, manifest)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    path = materialize_gate2_campaign(
        distribution_path=args.distribution,
        output_dir=args.output_dir,
    )
    print(f"wrote execution-locked Phase 2G A2 Gate 2 campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
