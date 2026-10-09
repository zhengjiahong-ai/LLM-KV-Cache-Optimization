"""Run non-holdout H1 compiler fixtures in isolated processes."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .phase2_h2_calibration_runner import _run_isolated


def execute_fidelity_campaign(
    campaign_path: Path, output_root: Path, *, resume: bool = False
) -> tuple[dict[str, object], Path]:
    campaign_path = campaign_path.resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("campaign_kind") != "NON_HOLDOUT_FIDELITY_VALIDATION":
        raise ValueError("unsupported H1 fidelity campaign")
    if campaign.get("formal_h1_outcome_execution_authorized") is not False:
        raise ValueError("fidelity campaign must not authorize formal outcomes")
    fixtures = campaign.get("fixtures")
    if not isinstance(fixtures, list):
        raise TypeError("fixtures must be an array")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise TypeError("fixture must be an object")
        run_id = fixture.get("scenario_id")
        config_name = fixture.get("config")
        if not isinstance(run_id, str) or not isinstance(config_name, str):
            raise TypeError("fixture identity is invalid")
        directory = output_root / run_id
        if directory.exists():
            if not resume:
                raise FileExistsError(f"fidelity run already exists: {directory}")
            status = "skipped_existing"
        else:
            directory = _run_isolated(campaign_path.parent / config_name, output_root, run_id)
            manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
            status = str(manifest.get("status", "failed"))
        results.append({"run_id": run_id, "status": status, "run_directory": str(directory)})
        print(f"{run_id}: {status}")
    summary = {
        "schema_version": "phase2a.h1_compiler_fidelity_execution.v1",
        "campaign_manifest": str(campaign_path),
        "formal_h1_outcome_execution_authorized": False,
        "challenger_runtime_policy_switch_authorized": False,
        "started_and_ended_date_utc": datetime.now(UTC).date().isoformat(),
        "successful_run_count": sum(item["status"] == "success" for item in results),
        "failed_run_count": sum(item["status"] == "failed" for item in results),
        "skipped_run_count": sum(item["status"] == "skipped_existing" for item in results),
        "results": results,
    }
    path = output_root / f"fidelity-execution-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    arguments = parser.parse_args(argv)
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(arguments.vllm_metal_source_checkout.resolve())
    summary, path = execute_fidelity_campaign(
        arguments.campaign, arguments.output_root, resume=arguments.resume
    )
    print(
        f"H1 compiler fidelity: {summary['successful_run_count']} success, "
        f"{summary['failed_run_count']} failed, "
        f"{summary['skipped_run_count']} skipped -> {path}"
    )
    return 0 if summary["failed_run_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
