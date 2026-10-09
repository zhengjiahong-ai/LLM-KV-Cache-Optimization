"""Execute the H2 calibration pilot in isolated resumable processes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CalibrationRunResult:
    run_id: str
    prefix_tokens: int
    role: str
    status: str
    run_directory: str
    failure_reason: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_campaign(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    supported_schemas = {
        "phase2a.h2_calibration_pilot.v1",
        "phase2a.h2_isolated_seam_calibration.v1",
    }
    if not isinstance(value, dict) or value.get("schema_version") not in supported_schemas:
        raise ValueError("unsupported H2 calibration campaign")
    if value.get("formal_measurement") is not False:
        raise ValueError("calibration campaign must not be formal measurement")
    if value.get("formal_verdict") is not False:
        raise ValueError("calibration campaign must not authorize a verdict")
    return value


def _run_isolated(config: Path, output_root: Path, run_id: str) -> Path:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kvopt.workload.phase2_single_runner",
            "--config",
            str(config),
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    run_dir = output_root / run_id
    if run_dir.is_dir():
        if completed.stdout:
            (run_dir / "launcher-stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
        if completed.stderr:
            (run_dir / "launcher-stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
    if not (run_dir / "run.json").is_file():
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"isolated run {run_id} produced no manifest: {detail[-1000:]}"
        )
    return run_dir


def _existing_result(
    run_dir: Path,
    *,
    prefix_tokens: int,
    role: str,
) -> CalibrationRunResult:
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") not in {
        "success",
        "failed",
    }:
        raise ValueError(f"existing run is not terminal: {run_dir}")
    return CalibrationRunResult(
        run_id=run_dir.name,
        prefix_tokens=prefix_tokens,
        role=role,
        status="skipped_existing",
        run_directory=str(run_dir),
        failure_reason=(
            manifest.get("failure_reason")
            if isinstance(manifest.get("failure_reason"), str)
            else None
        ),
    )


def execute_h2_calibration_pilot(
    campaign_path: str | Path,
    output_root: str | Path,
    *,
    resume: bool = False,
    prefix_tokens: Iterable[int] | None = None,
    roles: Iterable[str] | None = None,
) -> tuple[dict[str, object], Path]:
    campaign_path = Path(campaign_path).resolve()
    campaign = _load_campaign(campaign_path)
    selected_prefixes = None if prefix_tokens is None else set(prefix_tokens)
    selected_roles = None if roles is None else set(roles)
    if selected_roles is not None and not selected_roles <= {"warmup", "measured"}:
        raise ValueError("roles must be warmup or measured")
    raw_points = campaign.get("points")
    if not isinstance(raw_points, list):
        raise TypeError("campaign points must be an array")
    selected: list[tuple[int, str, str, Path]] = []
    for point in raw_points:
        if not isinstance(point, dict):
            raise TypeError("campaign point must be an object")
        tokens = point.get("prefix_tokens")
        config_name = point.get("config")
        runs = point.get("runs")
        if not isinstance(tokens, int) or not isinstance(config_name, str):
            raise TypeError("campaign point identity is invalid")
        if selected_prefixes is not None and tokens not in selected_prefixes:
            continue
        if not isinstance(runs, list):
            raise TypeError("campaign point runs must be an array")
        for run in runs:
            if not isinstance(run, dict):
                raise TypeError("campaign run must be an object")
            run_id = run.get("run_id")
            role = run.get("role")
            if not isinstance(run_id, str) or role not in {"warmup", "measured"}:
                raise ValueError("campaign run identity is invalid")
            if selected_roles is None or role in selected_roles:
                selected.append(
                    (tokens, role, run_id, campaign_path.parent / config_name)
                )
    if not selected:
        raise ValueError("calibration filters selected no runs")
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    collisions = [output / run_id for _, _, run_id, _ in selected if (output / run_id).exists()]
    if collisions and not resume:
        raise FileExistsError(f"calibration run already exists: {collisions[0]}")

    started = _now()
    results: list[CalibrationRunResult] = []
    for tokens, role, run_id, config in selected:
        run_dir = output / run_id
        if run_dir.exists():
            results.append(
                _existing_result(run_dir, prefix_tokens=tokens, role=role)
            )
            continue
        try:
            produced = _run_isolated(config, output, run_id)
            manifest = json.loads(
                (produced / "run.json").read_text(encoding="utf-8")
            )
            status = manifest.get("status")
            results.append(
                CalibrationRunResult(
                    run_id=run_id,
                    prefix_tokens=tokens,
                    role=role,
                    status=status if status in {"success", "failed"} else "failed",
                    run_directory=str(produced),
                    failure_reason=(
                        manifest.get("failure_reason")
                        if isinstance(manifest.get("failure_reason"), str)
                        else None
                    ),
                )
            )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            results.append(
                CalibrationRunResult(
                    run_id=run_id,
                    prefix_tokens=tokens,
                    role=role,
                    status="failed",
                    run_directory=str(run_dir),
                    failure_reason=f"{type(error).__name__}: {error}",
                )
            )
    summary = {
        "schema_version": "phase2a.h2_calibration_execution.v1",
        "campaign_id": campaign.get("campaign_id"),
        "campaign_manifest": str(campaign_path),
        "started_at_utc": started,
        "ended_at_utc": _now(),
        "formal_measurement": False,
        "formal_verdict": False,
        "selected_run_count": len(selected),
        "successful_run_count": sum(row.status == "success" for row in results),
        "failed_run_count": sum(row.status == "failed" for row in results),
        "skipped_run_count": sum(row.status == "skipped_existing" for row in results),
        "results": [asdict(row) for row in results],
    }
    summary_path = output / f"calibration-execution-{uuid.uuid4().hex[:12]}.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary, summary_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prefix-tokens", action="append", type=int)
    parser.add_argument("--role", action="append", choices=("warmup", "measured"))
    parser.add_argument("--vllm-metal-source-checkout", type=Path)
    arguments = parser.parse_args(argv)
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    if arguments.vllm_metal_source_checkout is not None:
        os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(
            arguments.vllm_metal_source_checkout.resolve()
        )
    summary, path = execute_h2_calibration_pilot(
        arguments.campaign,
        arguments.output_root,
        resume=arguments.resume,
        prefix_tokens=arguments.prefix_tokens,
        roles=arguments.role,
    )
    print(
        f"H2 calibration pilot: {summary['successful_run_count']} success, "
        f"{summary['failed_run_count']} failed, "
        f"{summary['skipped_run_count']} skipped -> {path}"
    )
    return 0 if summary["failed_run_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
