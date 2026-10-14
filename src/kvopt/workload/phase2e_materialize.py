"""Materialize the 36-draw Phase 2E paired baseline freeze candidate."""

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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _segments(family: str, draw: int, agent: str, turn: int) -> list[list[object]]:
    branch = 64 + (16 * ((draw + ord(agent[-1])) % 3))
    if family == "F3":
        branch = (96, 160, 224, 128)[ord(agent[-1]) % 4]
    root_key = f"{family.lower()}-{draw}-root"
    if family != "F4" or draw % 2 == 0:
        root_key = f"{root_key}-{agent}"
    rows: list[list[object]] = [[root_key, 96], [f"{family.lower()}-{draw}-{agent}-branch", branch]]
    if family == "F5" and turn > 1:
        rows.extend(
            [f"f5-{draw}-{agent}-growth-{index}", 32]
            for index in range(2, turn + 1)
        )
    return rows


def _scenario(family: str, draw: int) -> tuple[dict[str, object], dict[str, object]]:
    agent_count = 4 if draw in {3, 6} else 3
    agents = tuple(f"a{index}" for index in range(1, agent_count + 1))
    turn_count = 3 if family in {"F1", "F5"} else (4 if family == "F2" else 2)
    requests: list[dict[str, object]] = []
    request_segments: dict[str, list[list[object]]] = {}
    for agent_index, agent in enumerate(agents):
        actual_turns = turn_count
        if family == "F2" and agent != "a1":
            actual_turns = 2
        for turn in range(1, actual_turns + 1):
            if family == "F6":
                offset = 0.0 if turn == 1 else 3.0
            elif family == "F1":
                offset = float(agent_index + (turn - 1) * (agent_count + 1))
            elif family == "F2":
                offset = float(agent_index + (turn - 1) * (1 if agent == "a1" else 4))
            else:
                offset = float(agent_index + (turn - 1) * (agent_count + 1))
            request_id = f"{family.lower()}-{draw}-{agent}:{turn}"
            requests.append(
                {
                    "program_id": f"{family.lower()}-{draw}-{agent}",
                    "request_id": request_id,
                    "turn_index": turn,
                    "planned_arrival_offset_seconds": offset,
                    "prompt": f"Phase 2E {family} draw {draw} {agent} turn {turn}",
                    "prefix_prompt": "identity-is-defined-by-explicit-token-segments",
                    "is_terminal": turn == actual_turns,
                    "next_tool_type": None if turn == actual_turns else f"phase2e-{family.lower()}",
                    "tool_gap_seconds": None if turn == actual_turns else 0.5 + 0.25 * draw,
                }
            )
            request_segments[request_id] = _segments(family, draw, agent, turn)
    pressure_offsets = [2.5]
    if family == "F5":
        pressure_offsets.append(7.5)
    if family == "F6":
        pressure_offsets = [1.0, 4.0]
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": f"phase2e-{family.lower()}-{draw:02d}",
        "requests": sorted(requests, key=lambda row: (row["planned_arrival_offset_seconds"], row["request_id"])),
        "pressure_stages": [
            {
                "stage_id": f"{family.lower()}-{draw}-pressure-{index}",
                "planned_arrival_offset_seconds": offset,
                "prompt": f"Phase 2E {family} draw {draw} pressure {index}",
                "max_requests": 1,
                "stop_on_forced_release": False,
            }
            for index, offset in enumerate(pressure_offsets, start=1)
        ],
    }
    max_prefix_by_program: dict[str, int] = {}
    for row in requests:
        request_id = str(row["request_id"])
        program_id = str(row["program_id"])
        size = sum(int(segment[1]) for segment in request_segments[request_id])
        max_prefix_by_program[program_id] = max(max_prefix_by_program.get(program_id, 0), size)
    return trace, {
        "request_segments": request_segments,
        "program_prefix_tokens": max_prefix_by_program,
        "agent_count": agent_count,
        "turn_request_count": len(requests),
        "pressure_count": len(pressure_offsets),
        "max_concurrent_requests": 3 if family == "F6" else 1,
        "shared_prefix_control": family == "F4" and draw % 2 == 0,
        "family_parameters": {
            "agent_turn_counts": dict(
                Counter(str(row["program_id"]) for row in requests)
            ),
            "pressure_offsets_seconds": pressure_offsets,
            "arrival_offsets_seconds": sorted(
                float(row["planned_arrival_offset_seconds"]) for row in requests
            ),
            "prefix_sizes_tokens": sorted(max_prefix_by_program.values()),
            "shared_prefix_mode": (
                "NO_SHARED_PREFIX_NEGATIVE_CONTROL"
                if family == "F4" and draw % 2 == 0
                else ("SHARED_ROOT" if family == "F4" else "FAMILY_DEFAULT")
            ),
            "pressure_execution_semantics": "POST_COMPLETION_BARRIER",
            "generation_scope": "PREFILL_FOCUSED_MAX_NEW_TOKENS_1",
        },
    }


def materialize_phase2e(*, distribution_path: Path, output_dir: Path) -> Path:
    distribution: dict[str, Any] = json.loads(distribution_path.read_text(encoding="utf-8"))
    if distribution.get("schema_version") != "phase2e.workload_distribution.v1":
        raise ValueError("unsupported Phase 2E workload distribution")
    if distribution.get("execution_authorized") is not False:
        raise ValueError("freeze candidate must remain execution-locked")
    if distribution.get("joint_freeze_complete") is not False:
        raise ValueError("freeze candidate cannot claim completed joint freeze")
    if distribution.get("cost_aware_policy") is not False:
        raise ValueError("Phase 2E cannot enable Cost-Aware policy")
    output_dir.mkdir(parents=True, exist_ok=False)
    block_size = int(distribution["block_size_tokens"])
    pressure_tokens = int(distribution["pressure_prompt_tokens"])
    scenarios: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    for family in distribution["families"]:
        for draw in range(1, int(distribution["independent_draws_per_family"]) + 1):
            scenario_id = f"{family.lower()}-draw-{draw:02d}"
            trace, metadata = _scenario(str(family), draw)
            trace_path = output_dir / f"{scenario_id}.trace.json"
            _write(trace_path, trace)
            shortage = int(distribution["initial_shortage_blocks"][(draw - 1) % 3])
            pressure_blocks = pressure_tokens // block_size
            protected_blocks = sum(
                int(value) // block_size
                for value in metadata["program_prefix_tokens"].values()
            )
            block_override = protected_blocks + pressure_blocks + 1 - shortage
            scenario_runs: list[str] = []
            for repeat in distribution["runtime_repeats"]:
                order = (
                    distribution["baselines"]
                    if (draw + int(repeat)) % 2 == 0
                    else list(reversed(distribution["baselines"]))
                )
                for order_index, baseline in enumerate(order):
                    run_id = f"{scenario_id}-{baseline}-repeat-{repeat}"
                    config_path = output_dir / f"{run_id}.config.json"
                    config = {
                        "schema_version": "phase2.config.v1",
                        "runtime_mode": "vllm-metal-observability",
                        "backend_factory": distribution["runtime"]["backend_factory"],
                        "backend_revision": "phase2e-native-baseline-v1",
                        "campaign_kind": "phase2e_non_holdout_research_discovery",
                        "policy": baseline,
                        "seed": int(distribution["sampler_seed"])
                        + (int(str(family)[1:]) * 100)
                        + draw,
                        "observe": True,
                        "model": distribution["model"],
                        "tokenizer": distribution["model"],
                        "generation": {
                            "max_new_tokens": distribution["runtime"]["max_new_tokens"],
                            "temperature": distribution["runtime"]["temperature"],
                        },
                        "batching": {"max_concurrent_requests": metadata["max_concurrent_requests"]},
                        "cache": {"block_size": block_size, "block_override": block_override},
                        "pressure": {
                            "initial_shortage_blocks": shortage,
                            "required_blocks": pressure_blocks,
                            "safety_ceiling": metadata["pressure_count"],
                        },
                        "backend_options": {
                            "execute_planned_timing": False,
                            "executor_mode": "submit_collect",
                            "gpu_memory_utilization": distribution["runtime"]["gpu_memory_utilization"],
                            "phase2c_native_pilot_mode": True,
                            "phase2c_prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                            "prefix_segments_by_request": metadata["request_segments"],
                            "program_prefix_tokens": metadata["program_prefix_tokens"],
                            "pressure_prompt_tokens": pressure_tokens,
                            "prefill_profile_path": "docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
                        },
                        "trace": trace_path.name,
                        "phase2e_stage": {
                            "stage": "MEASURED",
                            "scenario_id": scenario_id,
                            "family": family,
                            "draw": draw,
                            "baseline": baseline,
                            "repeat": repeat,
                            "execution_order": order_index + 1,
                            "independent_statistical_unit": scenario_id,
                            "runtime_repeat_is_independent": False,
                            "measured": True,
                            "shared_prefix_control": metadata["shared_prefix_control"],
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
                            "baseline": baseline,
                            "repeat": repeat,
                            "execution_order": order_index + 1,
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
                    "agent_count": metadata["agent_count"],
                    "turn_request_count": metadata["turn_request_count"],
                    "pressure_count": metadata["pressure_count"],
                    "shared_prefix_control": metadata["shared_prefix_control"],
                    "design_kind": "PREDEFINED_BALANCED_PARAMETER_GRID",
                    "family_parameters": metadata["family_parameters"],
                    "run_ids": scenario_runs,
                }
            )
    family_counts = Counter(str(row["family"]) for row in scenarios)
    if len(scenarios) != 36 or set(family_counts.values()) != {6} or len(runs) != 144:
        raise ValueError("Phase 2E materialization cardinality is invalid")
    manifest = {
        "schema_version": "phase2e.campaign_materialization.v1",
        "run_kind": distribution["run_kind"],
        "distribution_sha256": _sha(distribution_path),
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "independent_statistical_unit": "scenario_draw",
        "runtime_repeats_are_independent": False,
        "joint_freeze_complete": False,
        "measured_campaign_authorized": False,
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
    path = materialize_phase2e(distribution_path=args.distribution, output_dir=args.output_dir)
    print(f"wrote Phase 2E freeze candidate: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
