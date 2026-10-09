"""Audit H1 identical-baseline runs and freeze latency epsilon."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from kvopt.costaware.acceptance import calibrate_latency_epsilon

from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_h1_baseline_report(
    campaign_path: str | Path,
    run_root: str | Path,
) -> dict[str, object]:
    campaign_path = Path(campaign_path).resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("campaign_kind") != "h1_latency_baseline_calibration":
        raise ValueError("unsupported H1 baseline campaign")
    if campaign.get("formal_h1_outcome_execution_authorized") is not False:
        raise ValueError("baseline campaign must not authorize H1 outcomes")
    points = campaign.get("points")
    if not isinstance(points, list) or len(points) != 1:
        raise ValueError("baseline campaign must contain exactly one point")
    runs = points[0].get("runs") if isinstance(points[0], dict) else None
    if not isinstance(runs, list) or len(runs) != 5:
        raise ValueError("baseline campaign must contain exactly five repeats")
    target = campaign.get("target_request_id")
    if not isinstance(target, str):
        raise TypeError("target_request_id must be text")

    observations: list[dict[str, object]] = []
    values: list[float] = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str):
            raise TypeError("baseline run identity is invalid")
        run_id = run["run_id"]
        directory = Path(run_root).resolve() / run_id
        artifacts = load_run_artifacts(directory)
        rows = [
            row
            for row in build_request_runtime_evidence_table((artifacts,))
            if row.request_id == target
        ]
        if len(rows) != 1:
            raise ValueError(f"{run_id} must have exactly one target evidence row")
        row = rows[0]
        if row.availability != "AVAILABLE" or row.apc_outcome != "FULL_HIT":
            raise ValueError(f"{run_id} lacks validated native FULL_HIT evidence")
        if row.backend_service_e2e_status != "available" or row.backend_service_e2e_seconds is None:
            raise ValueError(f"{run_id} lacks backend service E2E timing")
        values.append(row.backend_service_e2e_seconds)
        observations.append(
            {
                "run_id": run_id,
                "run_manifest_sha256": _file_sha256(directory / "run.json"),
                "request_id": target,
                "backend_service_e2e_seconds": row.backend_service_e2e_seconds,
                "native_queue_delay_seconds": row.native_queue_delay_seconds,
                "native_prefill_to_first_token_seconds": row.native_prefill_to_first_token_seconds,
                "native_cached_prefix_tokens": row.native_cached_prefix_tokens,
                "observed_recomputed_tokens": row.observed_recomputed_tokens,
                "apc_outcome": row.apc_outcome,
            }
        )
    epsilon = calibrate_latency_epsilon(values, minimum_repeats=5)
    return {
        "schema_version": "phase2a.h1_latency_baseline_report.v1",
        "campaign_id": campaign.get("campaign_id"),
        "campaign_sha256": _file_sha256(campaign_path),
        "formal_h1_outcome_execution_authorized": False,
        "primary_metric": "backend_service_e2e_seconds",
        "epsilon_latency": asdict(epsilon),
        "observations": observations,
        "level_b_native_evidence_check": "PASS",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_h1_baseline_report(arguments.campaign, arguments.run_root)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote H1 baseline calibration report: {arguments.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
