"""Compute the frozen M1 timing resolution without producing an H2 verdict."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections.abc import Sequence
from pathlib import Path

from .h2_calibration import _dispersion
from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _nearest_rank_percentile(values: list[float], probability: float) -> float:
    if not values or not 0 < probability <= 1:
        raise ValueError("percentile requires values and probability in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(probability * len(ordered)) - 1]


def bootstrap_median_resolution(
    values: Sequence[float],
    *,
    iterations: int,
    resample_size: int,
    seed: int,
) -> float:
    """Return q95 absolute error of a resampled formal-size median."""

    if len(values) != 5:
        raise ValueError("isolated calibration requires exactly five values")
    if iterations != 10_000 or resample_size != 9:
        raise ValueError("bootstrap protocol requires 10000 resamples of size 9")
    baseline = statistics.median(values)
    generator = random.Random(seed)
    deviations = [
        abs(
            statistics.median(
                generator.choices(tuple(values), k=resample_size)
            )
            - baseline
        )
        for _ in range(iterations)
    ]
    return _nearest_rank_percentile(deviations, 0.95)


def build_h2_isolated_calibration_report(
    campaign_path: str | Path,
    run_root: str | Path,
) -> dict[str, object]:
    campaign_path = Path(campaign_path).resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if not isinstance(campaign, dict) or campaign.get("schema_version") != (
        "phase2a.h2_isolated_seam_calibration.v1"
    ):
        raise ValueError("unsupported isolated-seam calibration campaign")
    points = campaign.get("points")
    if not isinstance(points, list) or len(points) != 8:
        raise ValueError("isolated-seam calibration requires eight points")
    iterations = campaign.get("bootstrap_iterations")
    resample_size = campaign.get("bootstrap_resample_size")
    seed = campaign.get("bootstrap_seed")
    if not all(isinstance(value, int) for value in (iterations, resample_size, seed)):
        raise TypeError("bootstrap controls must be integers")
    root = Path(run_root)
    git_shas: set[str] = set()
    summaries: list[dict[str, object]] = []
    for point in points:
        if not isinstance(point, dict):
            raise TypeError("campaign point must be an object")
        prefix_tokens = point.get("prefix_tokens")
        expected_config_sha = point.get("runtime_config_sha256")
        runs = point.get("runs")
        if not isinstance(prefix_tokens, int) or not isinstance(expected_config_sha, str):
            raise TypeError("campaign point identity is invalid")
        if not isinstance(runs, list):
            raise TypeError("campaign point runs must be an array")
        values: list[float] = []
        run_ids: list[str] = []
        for run in runs:
            if not isinstance(run, dict) or run.get("role") != "measured":
                continue
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                raise TypeError("measured run_id must be text")
            artifacts = load_run_artifacts(root / run_id)
            if artifacts.manifest.get("status") != "success":
                raise ValueError(f"measured run is not successful: {run_id}")
            if artifacts.manifest.get("git_dirty") is not False:
                raise ValueError(f"measured run used a dirty worktree: {run_id}")
            git_sha = artifacts.manifest.get("git_sha")
            if not isinstance(git_sha, str) or not git_sha:
                raise ValueError(f"measured run lacks git SHA: {run_id}")
            git_shas.add(git_sha)
            if artifacts.manifest.get("config_sha256") != expected_config_sha:
                raise ValueError(f"measured run config hash mismatch: {run_id}")
            rows = build_request_runtime_evidence_table((artifacts,))
            if len(rows) != 1 or rows[0].native_prompt_tokens != prefix_tokens + 1:
                raise ValueError(f"calibration request shape mismatch: {run_id}")
            row = rows[0]
            if (
                row.isolated_native_prefill_elapsed_status != "available"
                or row.isolated_native_prefill_elapsed_seconds is None
            ):
                raise ValueError(f"isolated prefill timing unavailable: {run_id}")
            values.append(row.isolated_native_prefill_elapsed_seconds)
            run_ids.append(run_id)
        if len(values) != campaign.get("measured_repeats_per_point"):
            raise ValueError(f"prefix {prefix_tokens} lacks measured repetitions")
        delta_r = bootstrap_median_resolution(
            values,
            iterations=iterations,
            resample_size=resample_size,
            seed=seed,
        )
        summaries.append(
            {
                "prefix_tokens": prefix_tokens,
                "run_ids": run_ids,
                "isolated_native_prefill": _dispersion(values),
                "delta_r_seconds": delta_r,
            }
        )
    if len(git_shas) != 1:
        raise ValueError("measured calibration runs must share one git SHA")
    return {
        "schema_version": "phase2a.h2_isolated_seam_calibration_report.v1",
        "campaign_id": campaign.get("campaign_id"),
        "git_sha": next(iter(git_shas)),
        "formal_measurement": False,
        "formal_verdict": False,
        "primary_observation": "isolated_native_prefill_elapsed_seconds",
        "primary_observation_status": "AVAILABLE",
        "bootstrap_iterations": iterations,
        "bootstrap_resample_size": resample_size,
        "bootstrap_seed": seed,
        "bootstrap_point_seed_rule": "same_frozen_seed_per_point",
        "percentile_rule": "nearest_rank",
        "delta_M1_seconds": max(row["delta_r_seconds"] for row in summaries),
        "status": "READY_FOR_FINAL_FREEZE_REVIEW",
        "point_summaries": summaries,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_h2_isolated_calibration_report(
        arguments.campaign,
        arguments.run_root,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote H2 isolated-seam calibration report: {arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
