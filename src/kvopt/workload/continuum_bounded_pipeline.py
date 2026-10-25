"""Run the authorized bounded evaluation from preflight through final report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path
from typing import Any

from kvopt.profiling.continuum_bounded_report import build_report, evaluate_run

from .continuum_bounded_campaign import materialize_campaign
from .continuum_bounded_gate import authorize_campaign, validate_campaign
from .continuum_bounded_preflight import run_preflight
from .continuum_bounded_profile_runner import run_profile
from .continuum_bounded_runner import run_campaign
from .phase2_runner import run_phase2


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_fidelity_preflight(
    *, repository: Path, manifest_path: Path, output_root: Path
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = [
        row
        for row in manifest["runs"]
        if row["group_id"] == "g01-short-extreme"
        and row["pressure_regime"] == "moderate"
    ]
    if len(bindings) != 3:
        raise RuntimeError("integrated fidelity preflight requires all three arms")
    evaluated: list[dict[str, Any]] = []
    for binding in bindings:
        run_id = f"preflight-{binding['arm'].lower()}"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "kvopt.workload.continuum_bounded_pipeline",
                "preflight-one",
                "--config",
                str((manifest_path.parent / binding["config"]).resolve()),
                "--output-root",
                str(output_root.resolve()),
                "--run-id",
                run_id,
            ],
            cwd=repository,
            check=False,
        )
        run_dir = output_root / run_id
        if completed.returncode != 0 or not (run_dir / "run.json").is_file():
            raise RuntimeError(f"integrated fidelity preflight failed: {binding['arm']}")
        evaluated.append(evaluate_run(run_dir, binding))
    input_sets = [
        {
            request_id: row["N"]
            for request_id, row in result["request_outcomes"].items()
        }
        for result in evaluated
    ]
    result = {
        "schema_version": "continuum.native_costaware_bounded_fidelity_preflight.v1",
        "status": (
            "PASS"
            if all(row["status"] == "VALID" for row in evaluated)
            and all(row["mechanism_status"] == "REALIZED" for row in evaluated)
            and input_sets[0] == input_sets[1] == input_sets[2]
            else "FAIL"
        ),
        "manifest_sha256": _sha(manifest_path),
        "arms": evaluated,
        "cross_arm_native_prompt_tokens_equal": (
            input_sets[0] == input_sets[1] == input_sets[2]
        ),
        "claim_boundary": "INTEGRATED_PREFLIGHT_NOT_A_FORMAL_OUTCOME",
    }
    return result


def _archive(root: Path, output: Path) -> dict[str, Any]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    inventory = [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": _sha(path),
        }
        for path in files
    ]
    inventory_path = root / "evidence-manifest.json"
    _write(inventory_path, {"files": inventory})
    with tarfile.open(output, "w:gz") as archive:
        archive.add(root, arcname=root.name)
    return {
        "archive_path": str(output.resolve()),
        "archive_size": output.stat().st_size,
        "archive_sha256": _sha(output),
        "inventory_path": str(inventory_path.resolve()),
        "inventory_sha256": _sha(inventory_path),
    }


def run_all(
    *, repository: Path, output_root: Path, protocol_path: Path,
    source_freeze_path: Path, profile_protocol_path: Path,
    profile_base_config_path: Path, budget_hours: float,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    started = time.monotonic()
    resource_path = output_root / "preflight/resource-record.json"
    run_preflight(source_freeze_path=source_freeze_path, output_path=resource_path)

    profile_root = output_root / "profile"
    profile_path = run_profile(
        base_config_path=profile_base_config_path,
        protocol_path=profile_protocol_path,
        preflight_path=resource_path,
        output_dir=profile_root,
        budget_hours=budget_hours,
    )
    elapsed_hours = (time.monotonic() - started) / 3600.0
    if elapsed_hours >= budget_hours:
        raise RuntimeError("budget exhausted before campaign materialization")

    campaign_root = output_root / "campaign"
    manifest = materialize_campaign(
        protocol_path=protocol_path,
        source_freeze_path=source_freeze_path,
        profile_path=profile_path,
        resource_record_path=resource_path,
        output_dir=campaign_root,
    )
    manifest_path = campaign_root / "manifest.json"
    validation = validate_campaign(manifest_path)
    validation_path = campaign_root / "validation-report.json"
    _write(validation_path, validation)
    if validation["status"] != "PASS":
        raise RuntimeError("campaign structural validation failed")

    fidelity_root = output_root / "preflight/native-fidelity-runs"
    fidelity = _run_fidelity_preflight(
        repository=repository,
        manifest_path=manifest_path,
        output_root=fidelity_root,
    )
    fidelity_path = output_root / "preflight/native-fidelity-report.json"
    _write(fidelity_path, fidelity)
    if fidelity["status"] != "PASS":
        raise RuntimeError("integrated Native fidelity preflight failed")

    authorization_path = campaign_root / "authorization.json"
    authorize_campaign(
        repository=repository,
        manifest_path=manifest_path,
        validation_path=validation_path,
        fidelity_report_path=fidelity_path,
        output_path=authorization_path,
    )
    remaining = budget_hours - (time.monotonic() - started) / 3600.0
    if remaining <= 0:
        raise RuntimeError("budget exhausted before formal Native campaign")
    runs_root = output_root / "runs"
    outputs = run_campaign(
        repository=repository,
        manifest_path=manifest_path,
        authorization_path=authorization_path,
        output_root=runs_root,
        budget_hours=remaining,
    )
    if len(outputs) != 54:
        raise RuntimeError("formal Native campaign stopped before all 54 runs")
    report = build_report(manifest_path=manifest_path, runs_root=runs_root)
    report_path = output_root / "analysis/campaign-report.json"
    _write(report_path, report)
    if report["gate"] != "PASS":
        raise RuntimeError("formal campaign evidence is incomplete or invalid")
    summary = {
        "schema_version": "continuum.native_costaware_bounded_pipeline_summary.v1",
        "status": "COMPLETE",
        "tooling_git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "profile_sha256": _sha(profile_path),
        "manifest_sha256": _sha(manifest_path),
        "authorization_sha256": _sha(authorization_path),
        "report_sha256": _sha(report_path),
        "planned_run_count": manifest["planned_run_count"],
        "completed_run_count": len(outputs),
        "wall_elapsed_seconds": time.monotonic() - started,
        "result_summary": report["summary"],
    }
    summary_path = output_root / "execution-summary.json"
    _write(summary_path, summary)
    archive = _archive(
        output_root,
        output_root.parent / f"{output_root.name}-evidence.tar.gz",
    )
    summary["archive"] = archive
    _write(summary_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    one = subparsers.add_parser("preflight-one")
    one.add_argument("--config", type=Path, required=True)
    one.add_argument("--output-root", type=Path, required=True)
    one.add_argument("--run-id", required=True)
    all_parser = subparsers.add_parser("run-all")
    all_parser.add_argument("--repository", type=Path, required=True)
    all_parser.add_argument("--output-root", type=Path, required=True)
    all_parser.add_argument("--protocol", type=Path, required=True)
    all_parser.add_argument("--source-freeze", type=Path, required=True)
    all_parser.add_argument("--profile-protocol", type=Path, required=True)
    all_parser.add_argument("--profile-base-config", type=Path, required=True)
    all_parser.add_argument("--budget-hours", type=float, default=30.0)
    args = parser.parse_args()
    if args.command == "preflight-one":
        output = run_phase2(
            args.config, output_root=args.output_root, run_id=args.run_id
        )
        status = json.loads((output / "run.json").read_text())["status"]
        print(f"{status}: {output}")
        return 0 if status == "success" else 1
    try:
        summary = run_all(
            repository=args.repository,
            output_root=args.output_root,
            protocol_path=args.protocol,
            source_freeze_path=args.source_freeze,
            profile_protocol_path=args.profile_protocol,
            profile_base_config_path=args.profile_base_config,
            budget_hours=args.budget_hours,
        )
    except Exception as error:  # noqa: BLE001 - preserve every fail-closed attempt
        failure = {
            "schema_version": "continuum.native_costaware_bounded_pipeline_summary.v1",
            "status": "FAILED",
            "failure_type": type(error).__name__,
            "failure_reason": str(error),
            "traceback": traceback.format_exc(),
        }
        if args.output_root.is_dir():
            summary_path = args.output_root / "execution-summary.json"
            _write(summary_path, failure)
            failure["partial_archive"] = _archive(
                args.output_root,
                args.output_root.parent / f"{args.output_root.name}-partial-evidence.tar.gz",
            )
            _write(summary_path, failure)
        print(f"bounded pipeline FAILED: {error}", file=sys.stderr)
        return 1
    print(f"bounded pipeline {summary['status']}: {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
