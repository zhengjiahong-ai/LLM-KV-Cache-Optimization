"""Materialize the execution-locked Phase 2G A1 bounded campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .phase2c_native_pilot import PILOT_PREFIX_GENERATOR_VERSION


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(contract: dict[str, Any], name: str, draw: int) -> Any:
    values = contract[name]
    if not isinstance(values, list) or len(values) != 6:
        raise ValueError(f"family field must contain six draws: {name}")
    return values[draw - 1]


def _scenario(
    family: str,
    draw: int,
    contract: dict[str, Any],
) -> tuple[dict[str, object], dict[str, object]]:
    entry_count = int(_value(contract, "entry_counts", draw))
    programs = [f"{family.lower()}-{draw}-a{index}" for index in range(1, entry_count + 1)]
    pressure_count = int(_value(contract, "pressure_count", draw))
    turn_count = int(_value(contract, "turn_counts", draw)) if family == "F4" else 2
    segments: dict[str, list[list[object]]] = {}
    requests: list[dict[str, object]] = []

    def base_segments(program_index: int) -> list[list[object]]:
        program = programs[program_index]
        if family == "F1":
            root = int(_value(contract, "shared_root_tokens", draw))
            tails = _value(contract, "private_tail_tokens", draw)
            return [
                [f"{family.lower()}-{draw}-shared-root", root],
                [f"{program}-tail", int(tails[program_index])],
            ]
        if family == "F2":
            root = int(_value(contract, "shared_root_tokens", draw))
            tail = int(_value(contract, "private_tail_tokens", draw))
            group_size = int(_value(contract, "shared_group_sizes", draw))
            group = program_index // group_size
            return [
                [f"{family.lower()}-{draw}-group-{group}-root", root],
                [f"{program}-tail", tail + 16 * program_index],
            ]
        if family == "F4":
            base = int(_value(contract, "base_prefix_tokens", draw))
            return [
                [f"{family.lower()}-{draw}-shared-root", 64],
                [f"{program}-base", base + 16 * program_index],
            ]
        sizes = _value(contract, "prefix_tokens", draw)
        return [[f"{program}-private", int(sizes[program_index])]]

    if family in {"F1", "F2", "F4", "F5"}:
        gaps = [float(_value(contract, "return_gap_seconds", draw))] * entry_count
    elif family == "F3":
        gaps = [float(value) for value in _value(contract, "return_gap_seconds", draw)]
    else:
        gaps = [float(value) for value in _value(contract, "declared_gap_seconds", draw)]
    if len(gaps) != entry_count:
        raise ValueError(f"gap cardinality mismatch: {family} draw {draw}")
    return_mode = (
        str(_value(contract, "realized_return_order", draw)) if family == "F6" else "AS_DECLARED"
    )
    omitted_program_index: int | None = None
    if return_mode == "omit-longest":
        omitted_program_index = max(range(entry_count), key=gaps.__getitem__)
    elif return_mode == "omit-shortest":
        omitted_program_index = min(range(entry_count), key=gaps.__getitem__)
    elif return_mode == "omit-middle":
        omitted_program_index = entry_count // 2

    for program_index, program in enumerate(programs):
        first_offset = program_index * 0.25
        program_turn_count = 1 if program_index == omitted_program_index else turn_count
        for turn in range(1, program_turn_count + 1):
            request_id = f"{program}:{turn}"
            if turn == 1:
                offset = first_offset
            else:
                offset = 2.0 + gaps[program_index] + (turn - 2) * 2.0
                if family == "F6" and return_mode == "reverse":
                    offset = 2.0 + gaps[-program_index - 1]
            request_segments = base_segments(program_index)
            if family == "F4" and turn > 1:
                growth = int(_value(contract, "growth_tokens_per_turn", draw))
                request_segments.extend(
                    [f"{program}-growth-{index}", growth] for index in range(2, turn + 1)
                )
            segments[request_id] = request_segments
            requests.append(
                {
                    "program_id": program,
                    "request_id": request_id,
                    "turn_index": turn,
                    "planned_arrival_offset_seconds": offset,
                    "prompt": f"Phase 2G A1 {family} draw {draw} entry {program_index + 1} turn {turn}",
                    "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                    "is_terminal": turn == program_turn_count,
                    "next_tool_type": None
                    if turn == program_turn_count
                    else f"phase2g-{family.lower()}",
                    "tool_gap_seconds": None if turn == program_turn_count else gaps[program_index],
                }
            )
    pressure_offsets = [1.25 + 2.0 * index for index in range(pressure_count)]
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": f"phase2g-a1-{family.lower()}-{draw:02d}",
        "requests": sorted(
            requests,
            key=lambda row: (
                row["planned_arrival_offset_seconds"],
                row["request_id"],
            ),
        ),
        "pressure_stages": [
            {
                "stage_id": f"{family.lower()}-{draw}-pressure-{index + 1}",
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2G A1 {family} draw {draw} pressure {index + 1}",
                "max_requests": 1,
                "stop_on_forced_release": False,
            }
            for index, offset in enumerate(pressure_offsets)
        ],
    }
    program_prefix_tokens: dict[str, int] = {}
    for row in requests:
        request_id = str(row["request_id"])
        program = str(row["program_id"])
        size = sum(int(segment[1]) for segment in segments[request_id])
        program_prefix_tokens[program] = max(program_prefix_tokens.get(program, 0), size)
    return trace, {
        "request_segments": segments,
        "program_prefix_tokens": program_prefix_tokens,
        "entry_count": entry_count,
        "turn_request_count": len(requests),
        "pressure_count": pressure_count,
        "family_parameters": {
            "focus": contract["focus"],
            "declared_return_gap_seconds": gaps,
            "prefix_sizes_tokens": sorted(program_prefix_tokens.values()),
            "pressure_offsets_seconds": pressure_offsets,
            "return_realization": return_mode,
        },
    }


def materialize_bounded_campaign(*, distribution_path: Path, output_dir: Path) -> Path:
    distribution: dict[str, Any] = json.loads(distribution_path.read_text(encoding="utf-8"))
    if distribution.get("schema_version") != "phase2g.a1_bounded_distribution.v1":
        raise ValueError("unsupported Phase 2G A1 bounded distribution")
    if distribution.get("execution_authorized") is not False:
        raise ValueError("bounded campaign materialization must remain execution-locked")
    if distribution.get("gate1_status") != "PASS":
        raise ValueError("Gate 1 must pass before Gate 2 materialization")
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
            trace_path = output_dir / f"{scenario_id}.trace.json"
            _write(trace_path, trace)
            pressure_tokens = int(distribution["pressure_prompt_tokens"][(draw - 1) % 3])
            shortage = int(distribution["initial_shortage_blocks"][(draw - 1) % 3])
            pressure_blocks = pressure_tokens // block_size
            protected_blocks = sum(
                int(value) // block_size for value in metadata["program_prefix_tokens"].values()
            )
            block_override = protected_blocks + pressure_blocks + 1 - shortage
            if block_override < 37:
                raise ValueError(f"insufficient Metal cache capacity: {scenario_id}")
            scenario_runs: list[str] = []
            for repeat in distribution["runtime_repeats"]:
                order = (
                    distribution["policies"]
                    if (family_index + draw + int(repeat)) % 2 == 0
                    else list(reversed(distribution["policies"]))
                )
                for order_index, policy in enumerate(order, start=1):
                    run_id = f"{scenario_id}-{policy.lower()}-repeat-{repeat}"
                    config_path = output_dir / f"{run_id}.config.json"
                    config = {
                        "schema_version": "phase2.config.v1",
                        "runtime_mode": "vllm-metal-observability",
                        "backend_factory": distribution["runtime"]["backend_factory"],
                        "backend_revision": "phase2g-a1-bounded-v1",
                        "campaign_kind": "phase2g_a1_bounded_evaluation",
                        "policy": f"continuum-{policy.lower()}",
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
                            "gpu_memory_utilization": distribution["runtime"][
                                "gpu_memory_utilization"
                            ],
                            "phase2c_native_pilot_mode": True,
                            "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                            "phase2g_release_policy": policy,
                            "phase2g_a1_lambda": distribution["a1"]["lambda"],
                            "phase2g_a1_tau_seconds": distribution["a1"]["tau_seconds"],
                            "prefix_segments_by_request": metadata["request_segments"],
                            "program_prefix_tokens": metadata["program_prefix_tokens"],
                            "pressure_prompt_tokens": pressure_tokens,
                            "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                        },
                        "trace": trace_path.name,
                        "phase2g_stage": {
                            "stage": "A1_BOUNDED",
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
                        }
                    )
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "family": family,
                    "draw": draw,
                    "trace": trace_path.name,
                    "trace_sha256": _sha(trace_path),
                    "entry_count": metadata["entry_count"],
                    "turn_request_count": metadata["turn_request_count"],
                    "pressure_count": metadata["pressure_count"],
                    "family_parameters": metadata["family_parameters"],
                    "design_kind": "PREDEFINED_BALANCED_PARAMETER_GRID",
                    "run_ids": scenario_runs,
                }
            )
    counts = Counter(str(row["family"]) for row in scenarios)
    if counts != Counter({family: 6 for family in distribution["families"]}):
        raise ValueError("bounded campaign must contain six scenarios per family")
    if len(scenarios) != 36 or len(runs) != 144:
        raise ValueError("bounded campaign cardinality is invalid")
    manifest = {
        "schema_version": "phase2g.a1_bounded_materialization.v1",
        "run_kind": distribution["run_kind"],
        "distribution_sha256": _sha(distribution_path),
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "independent_statistical_unit": distribution["statistical_unit"],
        "runtime_repeats_are_independent": False,
        "gate1_status": "PASS",
        "execution_authorized": False,
        "outcomes_materialized": False,
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
    path = materialize_bounded_campaign(
        distribution_path=args.distribution,
        output_dir=args.output_dir,
    )
    print(f"wrote Phase 2G A1 bounded campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
