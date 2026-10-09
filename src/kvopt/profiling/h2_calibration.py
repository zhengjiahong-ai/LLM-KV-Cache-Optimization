"""Summarize H2 pilot timing resolution without producing a verdict."""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Sequence
from pathlib import Path

from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _dispersion(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("dispersion requires at least one value")
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    return {
        "repeat_count": len(values),
        "median_seconds": median,
        "median_absolute_deviation_seconds": statistics.median(deviations),
        "minimum_seconds": min(values),
        "maximum_seconds": max(values),
        "maximum_absolute_deviation_seconds": max(deviations),
    }


def build_h2_calibration_report(
    campaign_path: str | Path,
    run_root: str | Path,
) -> dict[str, object]:
    campaign_path = Path(campaign_path).resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if not isinstance(campaign, dict) or campaign.get("schema_version") != (
        "phase2a.h2_calibration_pilot.v1"
    ):
        raise ValueError("unsupported H2 calibration campaign")
    points = campaign.get("points")
    if not isinstance(points, list):
        raise TypeError("campaign points must be an array")
    root = Path(run_root)
    git_shas: set[str] = set()
    point_rows: list[dict[str, object]] = []
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
        native_values: list[float] = []
        e2e_values: list[float] = []
        queue_values: list[float] = []
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
            if len(rows) != 1:
                raise ValueError(f"calibration run must contain one request: {run_id}")
            row = rows[0]
            if row.native_prompt_tokens != prefix_tokens + 1:
                raise ValueError(f"calibration prompt length mismatch: {run_id}")
            if (
                row.native_prefill_to_first_token_status != "available"
                or row.native_prefill_to_first_token_seconds is None
                or row.backend_service_e2e_status != "available"
                or row.backend_service_e2e_seconds is None
                or row.native_queue_delay_status != "available"
                or row.native_queue_delay_seconds is None
            ):
                raise ValueError(f"calibration timing is unavailable: {run_id}")
            native_values.append(row.native_prefill_to_first_token_seconds)
            e2e_values.append(row.backend_service_e2e_seconds)
            queue_values.append(row.native_queue_delay_seconds)
            run_ids.append(run_id)
        expected_repeats = campaign.get("measured_repeats_per_point")
        if len(run_ids) != expected_repeats:
            raise ValueError(
                f"prefix {prefix_tokens} requires {expected_repeats} measured runs"
            )
        point_rows.append(
            {
                "prefix_tokens": prefix_tokens,
                "run_ids": run_ids,
                "native_prefill_to_first_token": _dispersion(native_values),
                "backend_service_e2e": _dispersion(e2e_values),
                "native_queue_delay": _dispersion(queue_values),
            }
        )
    if len(git_shas) != 1:
        raise ValueError("measured calibration runs must share one git SHA")
    maximum_native_mad = max(
        row["native_prefill_to_first_token"][
            "median_absolute_deviation_seconds"
        ]
        for row in point_rows
    )
    maximum_native_deviation = max(
        row["native_prefill_to_first_token"][
            "maximum_absolute_deviation_seconds"
        ]
        for row in point_rows
    )
    return {
        "schema_version": "phase2a.h2_calibration_report.v1",
        "campaign_id": campaign.get("campaign_id"),
        "git_sha": next(iter(git_shas)),
        "formal_measurement": False,
        "formal_verdict": False,
        "numeric_thresholds_frozen": False,
        "requested_primary_observation": campaign.get(
            "primary_observation_requested"
        ),
        "requested_primary_observation_status": "UNAVAILABLE",
        "timing_candidate": campaign.get("available_native_timing_candidate"),
        "timing_candidate_role": "SENSITIVITY_ONLY_PENDING_M1_M4_REVIEW",
        "maximum_native_mad_seconds": maximum_native_mad,
        "maximum_native_absolute_deviation_seconds": maximum_native_deviation,
        "point_summaries": point_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_h2_calibration_report(arguments.campaign, arguments.run_root)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote H2 calibration report: {arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
