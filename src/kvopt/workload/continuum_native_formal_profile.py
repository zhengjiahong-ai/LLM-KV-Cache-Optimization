"""Assemble and validate the measured formal long-context PrefillReload profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from kvopt.continuum.prefill_profile import load_prefill_reload_provider

PROTOCOL_SCHEMA = "continuum.native_costaware_prefill_profile_protocol.v1"
POINT_SCHEMA = "continuum.native_costaware_prefill_profile_point.v1"
PROFILE_SCHEMA = "continuum.prefill_reload.formal_long_context_profile.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(*, protocol_path: Path, points_dir: Path, output_path: Path) -> dict[str, Any]:
    protocol = _load(protocol_path)
    if protocol.get("schema_version") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported formal profile protocol")
    grid = protocol.get("token_grid")
    if not isinstance(grid, list) or grid != sorted(set(grid)):
        raise ValueError("formal profile grid must be unique and increasing")
    bindings: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    protocol_sha = _sha256(protocol_path)
    measurement_protocol = protocol.get("measurement")
    if not isinstance(measurement_protocol, dict):
        raise ValueError("formal profile measurement protocol is missing")
    warmup_pair_count = int(measurement_protocol["warmup_pairs_per_point"])
    measured_pair_count = int(measurement_protocol["measured_pairs_per_point"])
    measurement_git_sha: str | None = None
    base_config_sha: str | None = None
    for token_count in grid:
        path = points_dir / f"point-{token_count}.json"
        measurement = _load(path)
        if measurement.get("schema_version") != POINT_SCHEMA or measurement.get(
            "protocol_sha256"
        ) != protocol_sha:
            raise ValueError(f"measurement binding failed for {token_count}")
        point = measurement.get("point")
        if not isinstance(point, dict) or point.get("token_count") != token_count:
            raise ValueError("measurement point identity mismatch")
        warmups = point.get("warmup_pairs")
        measured = point.get("measured_pairs")
        deltas = point.get("measured_raw_deltas_seconds")
        if not isinstance(warmups, list) or len(warmups) != warmup_pair_count:
            raise ValueError("profile point warmup-pair count mismatch")
        if not isinstance(measured, list) or len(measured) != measured_pair_count:
            raise ValueError("profile point measured-pair count mismatch")
        if not isinstance(deltas, list) or len(deltas) != measured_pair_count or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in deltas
        ):
            raise ValueError("profile point deltas are incomplete")
        if not math.isclose(
            float(point["median_raw_delta_seconds"]),
            float(statistics.median(deltas)),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("profile point median mismatch")
        current_git_sha = str(measurement.get("git_sha"))
        current_base_sha = str(measurement.get("base_config_sha256"))
        if measurement_git_sha is None:
            measurement_git_sha = current_git_sha
            base_config_sha = current_base_sha
        elif current_git_sha != measurement_git_sha or current_base_sha != base_config_sha:
            raise ValueError("profile measurement execution binding changed")
        points.append(point)
        bindings.append({"token_count": token_count, "path": str(path), "sha256": _sha256(path)})
    medians = [float(point["median_raw_delta_seconds"]) for point in points]
    slopes = [
        (medians[index + 1] - medians[index]) / (grid[index + 1] - grid[index])
        for index in range(len(grid) - 1)
    ]
    profile = {
        "schema": PROFILE_SCHEMA,
        "status": "complete",
        "protocol": {
            "canonical_unit": "seconds",
            "grid": grid,
            "warmup_pairs_per_point": warmup_pair_count,
            "measured_pairs_per_point": measured_pair_count,
            "raw_delta_definition": "MISS - HIT TTFT",
            "interpolation_rule": "piecewise_linear_between_measured_points",
            "extrapolation": "PROHIBITED",
        },
        "model": protocol["model"],
        "provenance": {
            "execution_backend": protocol.get("execution_backend"),
            "protocol_path": str(protocol_path),
            "protocol_sha256": protocol_sha,
            "base_config_sha256": base_config_sha,
            "measurement_git_sha": measurement_git_sha,
            "point_bindings": bindings,
            "legacy_w1b_profile_modified": False,
        },
        "points": points,
        "adjacent_secant_slopes_seconds_per_token": slopes,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provider = load_prefill_reload_provider(output_path)
    provider.estimate(int(protocol["coverage_requirement"]["maximum_known_query_tokens"]))
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--points-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = assemble(
        protocol_path=args.protocol, points_dir=args.points_dir, output_path=args.output
    )
    print(f"wrote formal PrefillReload profile: {len(profile['points'])} points -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
