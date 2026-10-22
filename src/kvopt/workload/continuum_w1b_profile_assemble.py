"""Assemble and validate the measured W1-B 3B PrefillReload profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from kvopt.continuum.prefill_profile import load_prefill_reload_provider

from .continuum_w1b_profile import W1B_TOKEN_GRID


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(*, protocol_path: Path, points_dir: Path, output_path: Path) -> dict[str, Any]:
    protocol = _load(protocol_path)
    if protocol.get("token_grid") != list(W1B_TOKEN_GRID):
        raise ValueError("W1-B profile protocol grid changed")
    protocol_sha = _sha256(protocol_path)
    points: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    base_config_sha: str | None = None
    git_sha: str | None = None
    for token_count in W1B_TOKEN_GRID:
        path = points_dir / f"point-{token_count}.json"
        measurement = _load(path)
        if (
            measurement.get("schema_version")
            != "continuum.w1b_prefill_profile_point.v1"
            or measurement.get("status") != "complete"
            or measurement.get("protocol_sha256") != protocol_sha
        ):
            raise ValueError(f"W1-B measurement binding failed for {token_count}")
        point = measurement.get("point")
        if not isinstance(point, dict) or point.get("token_count") != token_count:
            raise ValueError("W1-B measurement point identity mismatch")
        warmups = point.get("warmup_pairs")
        measured = point.get("measured_pairs")
        deltas = point.get("measured_raw_deltas_seconds")
        if not isinstance(warmups, list) or len(warmups) != 5:
            raise ValueError("W1-B point must contain five warmup pairs")
        if not isinstance(measured, list) or len(measured) != 20:
            raise ValueError("W1-B point must contain twenty measured pairs")
        if not isinstance(deltas, list) or len(deltas) != 20 or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in deltas
        ):
            raise ValueError("W1-B measured deltas are incomplete")
        median = float(point.get("median_raw_delta_seconds"))
        if not math.isclose(
            median,
            float(statistics.median(deltas)),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("W1-B point median does not match raw deltas")
        current_config_sha = str(measurement.get("base_config_sha256"))
        current_git_sha = str(measurement.get("git_sha"))
        if base_config_sha is None:
            base_config_sha = current_config_sha
            git_sha = current_git_sha
        elif current_config_sha != base_config_sha or current_git_sha != git_sha:
            raise ValueError("W1-B measurement execution binding changed across points")
        points.append(point)
        bindings.append(
            {
                "token_count": token_count,
                "path": str(path),
                "sha256": _sha256(path),
            }
        )
    profile = {
        "schema": "continuum.prefill_reload.w1b_long_context_profile.v1",
        "status": "complete",
        "protocol": {
            "canonical_unit": "seconds",
            "grid": list(W1B_TOKEN_GRID),
            "warmup_pairs_per_point": 5,
            "measured_pairs_per_point": 20,
            "raw_delta_definition": "MISS - HIT TTFT",
            "interpolation_rule": "piecewise_linear_between_measured_points",
            "extrapolation": "PROHIBITED",
        },
        "model": protocol["model"],
        "provenance": {
            "protocol_path": str(protocol_path),
            "protocol_sha256": protocol_sha,
            "base_config_sha256": base_config_sha,
            "measurement_git_sha": git_sha,
            "point_bindings": bindings,
            "legacy_phase1b_profile_modified": False,
        },
        "points": points,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provider = load_prefill_reload_provider(output_path)
    for token_count in (1456, 5088):
        provider.estimate(token_count)
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--points-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"W1-B profile already exists: {args.output}")
    profile = assemble(
        protocol_path=args.protocol,
        points_dir=args.points_dir,
        output_path=args.output,
    )
    medians = [point["median_raw_delta_seconds"] for point in profile["points"]]
    print(f"wrote W1-B 3B PrefillReload profile: {medians} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
