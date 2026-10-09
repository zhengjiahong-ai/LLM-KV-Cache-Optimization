"""Materialize the authorized H2 cost-curve calibration pilot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

from .phase2 import Phase2Trace, PlannedRequest
from .phase2_h2_design import load_h2_measurement_design


def _trace(prefix_tokens: int) -> Phase2Trace:
    return Phase2Trace(
        trace_id=f"phase2a-h2-calibration-r{prefix_tokens}-v1",
        requests=(
            PlannedRequest(
                program_id="calibration-a",
                request_id="calibration-a:turn:1",
                turn_index=1,
                planned_arrival_offset_seconds=0.0,
                prompt="isolated cost-curve calibration",
                prefix_prompt="deterministic calibration prefix",
                is_terminal=True,
                next_tool_type=None,
                tool_gap_seconds=None,
            ),
        ),
        pressure_stages=(),
    )


def _config(
    prefix_tokens: int,
    base_config: dict[str, object],
) -> dict[str, object]:
    config = copy.deepcopy(base_config)
    config["trace"] = f"r{prefix_tokens}.trace.json"
    config["seed"] = 42
    config["campaign_kind"] = "h2_calibration_pilot"
    config["h2_prefix_tokens"] = prefix_tokens
    cache = config.get("cache")
    pressure = config.get("pressure")
    options = config.get("backend_options")
    if not isinstance(cache, dict) or not isinstance(pressure, dict) or not isinstance(options, dict):
        raise TypeError("base config cache, pressure, and backend_options must be objects")
    block_size = 16
    pressure_tokens = 512
    cache["block_size"] = block_size
    cache["block_override"] = math.ceil(prefix_tokens / block_size) + 32
    pressure["required_blocks"] = 32
    pressure["initial_shortage_blocks"] = 1
    pressure["safety_ceiling"] = 1
    options["program_prefix_tokens"] = {"calibration-a": prefix_tokens}
    options["pressure_prompt_tokens"] = pressure_tokens
    options["pressure_stage_prompt_tokens"] = {}
    options["execute_planned_timing"] = False
    options["capture_terminal_prefix_snapshot"] = False
    options["isolated_native_prefill_timing"] = True
    return config


def materialize_h2_calibration_pilot(
    design_path: str | Path,
    base_config_path: str | Path,
    output_dir: str | Path,
) -> Path:
    design_path = Path(design_path).resolve()
    design = load_h2_measurement_design(design_path)
    if design.get("calibration_pilot_authorized") is not True:
        raise ValueError("H2 calibration pilot is not authorized")
    base_path = Path(base_config_path).resolve()
    base_config = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(base_config, dict):
        raise TypeError("base config must be an object")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    calibration = design["calibration"]
    m1 = design["m1_cost_curve"]
    if not isinstance(calibration, dict) or not isinstance(m1, dict):
        raise TypeError("validated H2 design sections must be objects")
    warmups = calibration["warmup_repeats_per_point"]
    repeats = calibration["pilot_repeats_per_point"]
    grid = m1["prefix_token_grid"]
    if not all(isinstance(value, int) for value in (warmups, repeats)):
        raise TypeError("pilot repeat counts must be integers")
    if not isinstance(grid, list) or any(not isinstance(point, int) for point in grid):
        raise TypeError("prefix token grid must be an integer array")

    points: list[dict[str, object]] = []
    for prefix_tokens in grid:
        trace_text = json.dumps(
            _trace(prefix_tokens).to_dict(), indent=2, sort_keys=True
        ) + "\n"
        config_text = json.dumps(
            _config(prefix_tokens, base_config), indent=2, sort_keys=True
        ) + "\n"
        trace_path = output / f"r{prefix_tokens}.trace.json"
        config_path = output / f"r{prefix_tokens}.config.json"
        trace_path.write_text(trace_text, encoding="utf-8")
        config_path.write_text(config_text, encoding="utf-8")
        runs = [
            {
                "run_id": f"r{prefix_tokens}-warmup-{index}",
                "role": "warmup",
            }
            for index in range(1, warmups + 1)
        ] + [
            {
                "run_id": f"r{prefix_tokens}-measure-{index}",
                "role": "measured",
            }
            for index in range(1, repeats + 1)
        ]
        points.append(
            {
                "prefix_tokens": prefix_tokens,
                "config": config_path.name,
                "config_file_sha256": hashlib.sha256(
                    config_text.encode()
                ).hexdigest(),
                "runtime_config_sha256": hashlib.sha256(
                    json.dumps(
                        json.loads(config_text),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                ).hexdigest(),
                "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                "runs": runs,
            }
        )

    manifest = {
        "schema_version": "phase2a.h2_calibration_pilot.v1",
        "campaign_id": "phase2a-h2-cost-curve-calibration-v1",
        "campaign_kind": "calibration_pilot",
        "design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
        "primary_observation_requested": m1["primary_observation"],
        "available_native_timing_candidate": (
            "native_prefill_to_first_token_seconds"
        ),
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "warmup_repeats_per_point": warmups,
        "measured_repeats_per_point": repeats,
        "planned_run_count": len(grid) * (warmups + repeats),
        "points": points,
    }
    manifest_path = output / "campaign.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    manifest = materialize_h2_calibration_pilot(
        arguments.design,
        arguments.base_config,
        arguments.output,
    )
    print(f"wrote H2 calibration pilot: {manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
