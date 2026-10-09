"""Materialize the authorized eight-point isolated-prefill calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2_h2_calibration import _config, _trace
from .phase2_h2_design import load_h2_formal_freeze_spec


def materialize_h2_isolated_calibration(
    freeze_spec_path: str | Path,
    base_config_path: str | Path,
    output_dir: str | Path,
) -> Path:
    """Write only calibration inputs; never execute or reveal an H2 verdict."""

    freeze_path = Path(freeze_spec_path).resolve()
    freeze = load_h2_formal_freeze_spec(freeze_path)
    calibration = freeze["isolated_seam_calibration"]
    if not isinstance(calibration, dict):
        raise TypeError("isolated_seam_calibration must be an object")
    base_path = Path(base_config_path).resolve()
    base_config = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(base_config, dict):
        raise TypeError("base config must be an object")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    grid = calibration["confirmatory_prefix_token_grid"]
    warmups = calibration["warmup_repeats"]
    repeats = calibration["measured_repeats"]
    if not isinstance(grid, list) or not all(isinstance(value, int) for value in grid):
        raise TypeError("isolated calibration grid must be an integer array")
    if not isinstance(warmups, int) or not isinstance(repeats, int):
        raise TypeError("isolated calibration repeat counts must be integers")

    points: list[dict[str, object]] = []
    for prefix_tokens in grid:
        trace_text = json.dumps(
            _trace(prefix_tokens).to_dict(), indent=2, sort_keys=True
        ) + "\n"
        config = _config(prefix_tokens, base_config)
        config["campaign_kind"] = "h2_isolated_seam_calibration"
        config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
        trace_path = output / f"r{prefix_tokens}.trace.json"
        config_path = output / f"r{prefix_tokens}.config.json"
        trace_path.write_text(trace_text, encoding="utf-8")
        config_path.write_text(config_text, encoding="utf-8")
        runs = [
            {"run_id": f"r{prefix_tokens}-warmup-{index}", "role": "warmup"}
            for index in range(1, warmups + 1)
        ] + [
            {"run_id": f"r{prefix_tokens}-measure-{index}", "role": "measured"}
            for index in range(1, repeats + 1)
        ]
        points.append(
            {
                "prefix_tokens": prefix_tokens,
                "config": config_path.name,
                "config_file_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
                "runtime_config_sha256": hashlib.sha256(
                    json.dumps(
                        config,
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
        "schema_version": "phase2a.h2_isolated_seam_calibration.v1",
        "campaign_id": "phase2a-h2-isolated-seam-calibration-v1",
        "campaign_kind": "isolated_seam_calibration",
        "freeze_spec_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "primary_observation": "isolated_native_prefill_elapsed_seconds",
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "warmup_repeats_per_point": warmups,
        "measured_repeats_per_point": repeats,
        "planned_run_count": len(grid) * (warmups + repeats),
        "bootstrap_iterations": calibration["bootstrap_iterations"],
        "bootstrap_resample_size": calibration["bootstrap_resample_size"],
        "bootstrap_seed": calibration["bootstrap_seed"],
        "points": points,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-spec", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = materialize_h2_isolated_calibration(
        arguments.freeze_spec,
        arguments.base_config,
        arguments.output,
    )
    print(f"wrote H2 isolated-seam calibration: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
