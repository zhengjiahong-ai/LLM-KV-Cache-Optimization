"""Assemble and validate the measured formal long-context PrefillReload profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

from kvopt.continuum.prefill_profile import load_prefill_reload_provider

PROTOCOL_SCHEMA = "continuum.native_costaware_prefill_profile_protocol.v1"
POINT_SCHEMA = "continuum.native_costaware_prefill_profile_point.v1"
PROFILE_SCHEMA = "continuum.prefill_reload.formal_long_context_profile.v1"
INTERPRETED_PROFILE_SCHEMA = (
    "continuum.prefill_reload.formal_long_context_interpreted_profile.v1"
)
INTERPRETATION_CONTRACT_SCHEMA = (
    "continuum.native_costaware_profile_interpretation_contract.v1"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _uncertainty(
    values: list[float], *, iterations: int, seed: int
) -> dict[str, object]:
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    generator = random.Random(seed)
    medians = sorted(
        statistics.median(generator.choices(values, k=len(values)))
        for _ in range(iterations)
    )
    low = medians[int(0.025 * (iterations - 1))]
    high = medians[int(0.975 * (iterations - 1))]
    return {
        "iqr_seconds": quartiles[2] - quartiles[0],
        "q1_seconds": quartiles[0],
        "q3_seconds": quartiles[2],
        "bootstrap_iterations": iterations,
        "bootstrap_seed": seed,
        "bootstrap_median_95_percent_interval_seconds": [low, high],
    }


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
        raise TypeError("formal profile measurement protocol must be an object")
    warmup_pair_count = int(measurement_protocol["warmup_pairs_per_point"])
    measured_pair_count = int(measurement_protocol["measured_pairs_per_point"])
    measurement_git_sha: str | None = None
    base_config_sha: str | None = None
    uncertainty = protocol.get("uncertainty_and_nonlinearity", {})
    bootstrap_iterations = int(uncertainty.get("bootstrap_iterations", 10000))
    bootstrap_seed = int(uncertainty.get("bootstrap_seed", 20261121))
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
        point = dict(point)
        point["uncertainty"] = _uncertainty(
            [float(value) for value in deltas],
            iterations=bootstrap_iterations,
            seed=bootstrap_seed + int(token_count),
        )
        point["validity_status"] = (
            "PASS"
            if float(point["median_raw_delta_seconds"]) > 0.0
            else "REVIEW_REQUIRED_NON_POSITIVE_MEDIAN"
        )
        points.append(point)
        bindings.append({"token_count": token_count, "path": str(path), "sha256": _sha256(path)})
    medians = [float(point["median_raw_delta_seconds"]) for point in points]
    slopes = [
        (medians[index + 1] - medians[index]) / (grid[index + 1] - grid[index])
        for index in range(len(grid) - 1)
    ]
    profile = {
        "schema": PROFILE_SCHEMA,
        "status": (
            "complete"
            if all(point["validity_status"] == "PASS" for point in points)
            else "review_required"
        ),
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
    if profile["status"] == "complete":
        provider = load_prefill_reload_provider(output_path)
        provider.estimate(
            int(protocol["coverage_requirement"]["maximum_known_query_tokens"])
        )
    return profile


def interpret_nonnegative_cost(
    *, raw_profile_path: Path, contract_path: Path, output_path: Path
) -> dict[str, Any]:
    """Create the M1-authorized non-negative view without changing raw evidence."""
    raw = _load(raw_profile_path)
    contract = _load(contract_path)
    raw_sha = _sha256(raw_profile_path)
    if raw.get("schema") != PROFILE_SCHEMA or raw.get("status") != "review_required":
        raise ValueError("interpretation requires the preserved review-required profile")
    if contract.get("schema_version") != INTERPRETATION_CONTRACT_SCHEMA:
        raise ValueError("unsupported Profile Interpretation Contract")
    if contract.get("raw_profile_sha256") != raw_sha:
        raise ValueError("raw Profile SHA-256 does not match the approved contract")
    if contract.get("projection") != {
        "token_count": 1024,
        "raw_status": "REVIEW_REQUIRED_NON_POSITIVE_MEDIAN",
        "interpreted_status": "INDISTINGUISHABLE_FROM_ZERO",
        "effective_cost_seconds": 0.0,
    }:
        raise ValueError("Profile projection differs from the M1-approved rule")

    points: list[dict[str, Any]] = []
    for source in raw.get("points", []):
        point = dict(source)
        token_count = int(point["token_count"])
        raw_median = float(point["median_raw_delta_seconds"])
        if token_count == 1024:
            interval = point.get("uncertainty", {}).get(
                "bootstrap_median_95_percent_interval_seconds"
            )
            if (
                point.get("validity_status")
                != "REVIEW_REQUIRED_NON_POSITIVE_MEDIAN"
                or not isinstance(interval, list)
                or len(interval) != 2
                or float(interval[0]) > 0.0
                or float(interval[1]) < 0.0
            ):
                raise ValueError("1024-token raw evidence is not zero-indistinguishable")
            point["interpretation_status"] = "INDISTINGUISHABLE_FROM_ZERO"
            point["effective_cost_seconds"] = 0.0
        else:
            if point.get("validity_status") != "PASS" or raw_median <= 0.0:
                raise ValueError("only the approved 1024-token point may be projected")
            point["interpretation_status"] = "RAW_POSITIVE_MEASUREMENT"
            point["effective_cost_seconds"] = raw_median
        points.append(point)

    interpreted = {
        "schema": INTERPRETED_PROFILE_SCHEMA,
        "status": "complete",
        "protocol": raw["protocol"],
        "model": raw["model"],
        "provenance": {
            "raw_profile_path": str(raw_profile_path.resolve()),
            "raw_profile_sha256": raw_sha,
            "interpretation_contract_path": str(contract_path.resolve()),
            "interpretation_contract_sha256": _sha256(contract_path),
            "raw_measurement_modified": False,
            "post_outcome_protocol_revision": True,
        },
        "interpretation": {
            "raw_measurement_field": "median_raw_delta_seconds",
            "runtime_cost_field": "effective_cost_seconds",
            "projection_rule": "ONLY_1024_TOKEN_POINT_PROJECTED_TO_ZERO",
            "projection_is_measurement_claim": False,
            "ranking_sensitivity_status": "INCONCLUSIVE_COST_ORDERING",
        },
        "points": points,
        "adjacent_secant_slopes_seconds_per_token": [
            (
                float(points[index + 1]["effective_cost_seconds"])
                - float(points[index]["effective_cost_seconds"])
            )
            / (
                int(points[index + 1]["token_count"])
                - int(points[index]["token_count"])
            )
            for index in range(len(points) - 1)
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(interpreted, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provider = load_prefill_reload_provider(output_path)
    provider.estimate(max(int(point["token_count"]) for point in points))
    return interpreted


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
