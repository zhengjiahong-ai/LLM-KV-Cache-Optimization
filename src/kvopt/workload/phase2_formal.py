"""Generate the predeclared Phase 2A M6 formal profiling campaign."""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .phase2 import Phase2Trace, PlannedRequest, PressureStage

FORMAL_SEEDS = (101, 211, 307)


@dataclass(frozen=True, slots=True)
class FormalScenarioSpec:
    family_id: str
    scenario_id: str
    prefix_tokens: tuple[int, ...]
    initial_offsets: tuple[float, ...]
    return_offsets: tuple[float, ...]
    pressure_offsets: tuple[float, ...]
    required_blocks: int
    analysis_horizon_seconds: float
    tags: tuple[str, ...]


def formal_scenario_specs() -> tuple[FormalScenarioSpec, ...]:
    """Return the frozen 18-scenario formal matrix."""

    return (
        FormalScenarioSpec("F1", "f1-two-homogeneous-shallow", (256, 256), (0, 0.2), (4, 5), (2,), 4, 4, ("candidate-scale-2", "homogeneous")),
        FormalScenarioSpec("F1", "f1-three-mixed-medium", (128, 256, 512), (0, 0.2, 0.4), (5, 6, 7), (2,), 16, 5, ("candidate-scale-3", "heterogeneous")),
        FormalScenarioSpec("F1", "f1-five-contention-deep", (128, 128, 256, 512, 512), (0, 0.1, 0.2, 0.3, 0.4), (6, 7, 8, 9, 10), (2,), 32, 6, ("candidate-scale-5", "higher-contention")),
        FormalScenarioSpec("F2", "f2-equal-256", (256, 256, 256), (0, 0.2, 0.4), (5, 6, 7), (2,), 16, 5, ("homogeneous", "cost-control")),
        FormalScenarioSpec("F2", "f2-mixed-128-256-512", (128, 256, 512), (0, 0.2, 0.4), (5, 6, 7), (2,), 16, 5, ("heterogeneous", "cost-spread")),
        FormalScenarioSpec("F2", "f2-large-spread-five", (128, 128, 256, 512, 512), (0, 0.1, 0.2, 0.3, 0.4), (6, 7, 8, 9, 10), (2,), 32, 6, ("heterogeneous", "large-cost-spread")),
        FormalScenarioSpec("F3", "f3-a-early-b-late", (256, 256), (0, 0.2), (3, 7), (2,), 8, 5, ("early-return", "late-return")),
        FormalScenarioSpec("F3", "f3-b-early-a-late", (256, 256), (0, 0.2), (7, 3), (2,), 8, 5, ("return-order-reversed", "late-return")),
        FormalScenarioSpec("F3", "f3-outside-horizon-interleaved", (128, 256, 512), (0, 0.2, 0.4), (3, 5, 12), (2,), 16, 4, ("outside-horizon", "interleaved-return")),
        FormalScenarioSpec("F4", "f4-shallow-single-pressure", (256, 256), (0, 0.2), (5, 6), (2,), 4, 5, ("shallow-pressure",)),
        FormalScenarioSpec("F4", "f4-deep-multi-release", (128, 256, 512), (0, 0.2, 0.4), (7, 8, 9), (2,), 32, 6, ("deep-pressure", "multi-release")),
        FormalScenarioSpec("F4", "f4-repeated-pressure", (256, 256, 512), (0, 0.2, 0.4), (8, 9, 10), (2, 5), 16, 6, ("repeated-pressure", "repeated-release")),
        FormalScenarioSpec("F5", "f5-staggered-low-waiting", (256, 256), (0, 1), (5, 7), (3,), 8, 5, ("staggered", "low-waiting")),
        FormalScenarioSpec("F5", "f5-overlap-high-waiting", (128, 256, 512, 256), (0, 0, 0.1, 0.1), (6, 7, 8, 9), (2,), 16, 6, ("overlap", "high-waiting")),
        FormalScenarioSpec("F5", "f5-same-cost-return-reversal", (256, 256, 256), (0, 0.2, 0.4), (7, 3, 5), (2,), 16, 5, ("return-order-reversed", "queue-state")),
        FormalScenarioSpec("F6", "f6-evolving-prefixes", (128, 256, 512), (0, 0.2, 0.4), (5, 6, 7), (2,), 16, 5, ("evolving-prefix", "identity-audit")),
        FormalScenarioSpec("F6", "f6-repeated-block-reuse", (256, 256, 512), (0, 0.2, 0.4), (8, 9, 10), (2, 5), 32, 6, ("block-slot-reuse", "repeated-pressure")),
        FormalScenarioSpec("F6", "f6-shared-ownership-audit", (512, 512, 512), (0, 0.1, 0.2), (6, 7, 8), (2,), 16, 5, ("shared-ownership", "capability-gated")),
    )


def _program_id(index: int) -> str:
    return f"agent-{chr(ord('a') + index)}"


def build_formal_trace(spec: FormalScenarioSpec) -> Phase2Trace:
    """Materialize one deterministic trace from a formal scenario spec."""

    candidate_count = len(spec.prefix_tokens)
    if not (
        candidate_count
        == len(spec.initial_offsets)
        == len(spec.return_offsets)
    ):
        raise ValueError("formal scenario candidate dimensions must match")
    if not spec.pressure_offsets:
        raise ValueError("formal scenario must contain pressure")

    requests: list[PlannedRequest] = []
    for index, (initial_offset, return_offset) in enumerate(
        zip(spec.initial_offsets, spec.return_offsets, strict=True)
    ):
        program_id = _program_id(index)
        prefix_prompt = f"formal reusable prefix for {program_id}"
        requests.extend(
            (
                PlannedRequest(
                    program_id=program_id,
                    request_id=f"{program_id}:turn:1",
                    turn_index=1,
                    planned_arrival_offset_seconds=initial_offset,
                    prompt=f"establish {program_id}",
                    prefix_prompt=prefix_prompt,
                    is_terminal=False,
                    next_tool_type=("search", "database", "code")[index % 3],
                    tool_gap_seconds=max(0.1, return_offset - initial_offset),
                ),
                PlannedRequest(
                    program_id=program_id,
                    request_id=f"{program_id}:turn:2",
                    turn_index=2,
                    planned_arrival_offset_seconds=return_offset,
                    prompt=f"return {program_id}",
                    prefix_prompt=prefix_prompt,
                    is_terminal=True,
                    next_tool_type=None,
                    tool_gap_seconds=None,
                ),
            )
        )
    stages = tuple(
        PressureStage(
            stage_id=f"pressure-{index}",
            planned_arrival_offset_seconds=offset,
            prompt=f"formal pressure for {spec.scenario_id} stage {index}",
            max_requests=3,
            stop_on_forced_release=True,
        )
        for index, offset in enumerate(spec.pressure_offsets, start=1)
    )
    return Phase2Trace(
        trace_id=f"phase2a-formal-{spec.scenario_id}-v1",
        requests=tuple(requests),
        pressure_stages=stages,
    )


def build_formal_config(
    spec: FormalScenarioSpec,
    base_config: dict[str, object],
) -> dict[str, object]:
    """Apply one formal scenario to a validated Phase 2 base configuration."""

    config = copy.deepcopy(base_config)
    config["schema_version"] = "phase2.config.v1"
    config["trace"] = f"{spec.scenario_id}.trace.json"
    config["seed"] = FORMAL_SEEDS[0]
    config["profiling_scenario_id"] = spec.scenario_id
    config["profiling_scenario_family"] = spec.family_id
    config["analysis_horizon_seconds"] = spec.analysis_horizon_seconds
    config["formal_scenario_tags"] = list(spec.tags)

    block_size = 16
    cache = config.setdefault("cache", {})
    if not isinstance(cache, dict):
        raise TypeError("base config cache must be an object")
    block_size_value = cache.get("block_size", block_size)
    if not isinstance(block_size_value, int) or block_size_value <= 0:
        raise ValueError("base config cache.block_size must be positive")
    candidate_blocks = sum(
        math.ceil(tokens / block_size_value) for tokens in spec.prefix_tokens
    )
    pressure_prompt_tokens = max(512, spec.required_blocks * block_size_value)
    pressure_blocks = math.ceil(pressure_prompt_tokens / block_size_value)
    cache["block_size"] = block_size_value
    cache["block_override"] = candidate_blocks + pressure_blocks

    pressure = config.setdefault("pressure", {})
    if not isinstance(pressure, dict):
        raise TypeError("base config pressure must be an object")
    pressure["required_blocks"] = spec.required_blocks
    pressure["safety_ceiling"] = max(3, int(pressure.get("safety_ceiling", 1)))

    backend_options = config.setdefault("backend_options", {})
    if not isinstance(backend_options, dict):
        raise TypeError("base config backend_options must be an object")
    backend_options["program_prefix_tokens"] = {
        _program_id(index): tokens
        for index, tokens in enumerate(spec.prefix_tokens)
    }
    backend_options["pressure_prompt_tokens"] = pressure_prompt_tokens
    backend_options["execute_planned_timing"] = True
    return config


def materialize_formal_campaign(
    base_config_path: str | Path,
    output_dir: str | Path,
) -> Path:
    """Write a new deterministic formal campaign directory."""

    base_path = Path(base_config_path).resolve()
    base_config = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(base_config, dict):
        raise TypeError("base config must contain a JSON object")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)

    specs = formal_scenario_specs()
    scenarios: list[dict[str, object]] = []
    for spec in specs:
        trace_path = output / f"{spec.scenario_id}.trace.json"
        config_path = output / f"{spec.scenario_id}.config.json"
        trace_path.write_text(
            json.dumps(
                build_formal_trace(spec).to_dict(),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                build_formal_config(spec, base_config),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        scenarios.append(
            {
                "scenario_id": spec.scenario_id,
                "family_id": spec.family_id,
                "config": config_path.name,
                "tags": list(spec.tags),
            }
        )

    manifest = {
        "schema_version": "phase2a.formal_campaign.v1",
        "campaign_id": "phase2a-m6-formal-v1",
        "campaign_kind": "formal",
        "seeds": list(FORMAL_SEEDS),
        "predeclared_repetitions_per_scenario": len(FORMAL_SEEDS),
        "planned_run_count": len(specs) * len(FORMAL_SEEDS),
        "family_scenario_counts": dict(
            sorted(Counter(spec.family_id for spec in specs).items())
        ),
        "scenarios": scenarios,
    }
    manifest_path = output / "campaign.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    manifest = materialize_formal_campaign(
        arguments.base_config,
        arguments.output,
    )
    print(f"wrote formal campaign manifest: {manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
