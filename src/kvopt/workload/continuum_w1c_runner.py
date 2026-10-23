"""Authorize and execute the frozen W1-C paired S50/S100 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .continuum_w1a_runner import load_acquisition_config, run_one

AUTH_SCHEMA = "continuum.w1c_pilot_authorization.v1"
SUMMARY_SCHEMA = "continuum.w1c_pilot_execution.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()


def _inputs(repository: Path, s50_path: Path, s100_path: Path) -> dict[str, Any]:
    s50, freeze50 = load_acquisition_config(s50_path, repository=repository)
    s100, freeze100 = load_acquisition_config(s100_path, repository=repository)
    if freeze50 != freeze100:
        raise ValueError("S50 and S100 do not bind the same sampling freeze")
    if s50.get("condition") != "S50" or s100.get("condition") != "S100":
        raise ValueError("paired configs must be S50 and S100")
    ids = freeze50.get("pilot_instance_ids")
    if not isinstance(ids, list) or len(ids) != 20 or len(set(ids)) != 20:
        raise ValueError("W1-C pilot must contain exactly 20 unique task IDs")
    return {"S50": s50, "S100": s100, "freeze": freeze50, "ids": ids}


def build_authorization(
    repository: Path, s50_path: Path, s100_path: Path
) -> dict[str, Any]:
    if _git(repository, "status", "--porcelain"):
        raise ValueError("authorization requires a clean Git worktree")
    inputs = _inputs(repository, s50_path, s100_path)
    freeze_path = repository / str(inputs["S50"]["sample_manifest"])
    snapshot_path = repository / str(inputs["S50"]["candidate_snapshot"])
    code_paths = (
        Path("src/kvopt/workload/continuum_w1a_runner.py"),
        Path("src/kvopt/workload/continuum_w1a_acquisition.py"),
        Path("src/kvopt/workload/continuum_w1a_conversion.py"),
        Path("src/kvopt/workload/continuum_w1c_runner.py"),
        Path("src/kvopt/profiling/continuum_w1c_report.py"),
    )
    return {
        "schema_version": AUTH_SCHEMA,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "W1C_BOUNDED_PAIRED_S50_S100_FEASIBILITY_PILOT",
        "repository_git_sha": _git(repository, "rev-parse", "HEAD"),
        "sampling_freeze_complete": True,
        "bounded_s50_s100_pilot_authorized": True,
        "full_100_task_acquisition_authorized": False,
        "formal_native_policy_campaign_authorized": False,
        "task_count": 20,
        "planned_run_count": 40,
        "pilot_instance_ids": inputs["ids"],
        "bindings": {
            "s50_config_sha256": _sha256(s50_path),
            "s100_config_sha256": _sha256(s100_path),
            "sampling_freeze_sha256": _sha256(freeze_path),
            "candidate_snapshot_sha256": _sha256(snapshot_path),
            "author_runner_commit": inputs["S50"]["author_runner"]["commit"],
            "code_sha256": {
                str(path): _sha256(repository / path) for path in code_paths
            },
        },
    }


def validate_authorization(
    authorization: dict[str, Any], repository: Path, s50_path: Path, s100_path: Path
) -> list[str]:
    problems: list[str] = []
    if authorization.get("schema_version") != AUTH_SCHEMA:
        problems.append("unsupported authorization schema")
        return problems
    if authorization.get("bounded_s50_s100_pilot_authorized") is not True:
        problems.append("bounded pilot is not authorized")
    if authorization.get("full_100_task_acquisition_authorized") is not False:
        problems.append("full 100-task acquisition must remain unauthorized")
    if authorization.get("formal_native_policy_campaign_authorized") is not False:
        problems.append("Native policy campaign must remain unauthorized")
    if _git(repository, "status", "--porcelain"):
        problems.append("Git worktree is not clean")
    if authorization.get("repository_git_sha") != _git(repository, "rev-parse", "HEAD"):
        problems.append("repository Git SHA drift")
    inputs = _inputs(repository, s50_path, s100_path)
    bindings = authorization.get("bindings", {})
    expected = {
        "s50_config_sha256": _sha256(s50_path),
        "s100_config_sha256": _sha256(s100_path),
        "sampling_freeze_sha256": _sha256(
            repository / str(inputs["S50"]["sample_manifest"])
        ),
        "candidate_snapshot_sha256": _sha256(
            repository / str(inputs["S50"]["candidate_snapshot"])
        ),
    }
    for key, value in expected.items():
        if bindings.get(key) != value:
            problems.append(f"{key} drift")
    for relative, expected_sha in bindings.get("code_sha256", {}).items():
        path = repository / relative
        if not path.is_file() or _sha256(path) != expected_sha:
            problems.append(f"code binding drift: {relative}")
    if authorization.get("pilot_instance_ids") != inputs["ids"]:
        problems.append("pilot task identity drift")
    return problems


def execute(
    *, repository: Path, source_checkout: Path, s50_path: Path, s100_path: Path,
    authorization_path: Path, output_root: Path
) -> dict[str, Any]:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    problems = validate_authorization(authorization, repository, s50_path, s100_path)
    if problems:
        raise ValueError("W1-C authorization invalid: " + "; ".join(problems))
    inputs = _inputs(repository, s50_path, s100_path)
    output_root.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    summary_path = output_root / "execution-summary.json"
    for instance_id in inputs["ids"]:
        for condition, config_path in (("S50", s50_path), ("S100", s100_path)):
            run_dir = output_root / condition / instance_id
            if (run_dir / "run.json").is_file():
                manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                state = "existing"
            else:
                run_one(
                    repository=repository,
                    source_checkout=source_checkout,
                    config_path=config_path,
                    instance_id=instance_id,
                    output_root=output_root / condition,
                )
                manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                state = "executed"
            attempts.append({
                "instance_id": instance_id,
                "condition": condition,
                "attempt_state": state,
                "run_status": manifest.get("status"),
                "agent_outcome": manifest.get("agent_outcome"),
                "run_manifest": str((run_dir / "run.json").resolve()),
                "run_manifest_sha256": _sha256(run_dir / "run.json"),
            })
            summary = {
                "schema_version": SUMMARY_SCHEMA,
                "authorization_sha256": _sha256(authorization_path),
                "planned_run_count": 40,
                "recorded_run_count": len(attempts),
                "attempts": attempts,
            }
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    authorize = subparsers.add_parser("authorize")
    run = subparsers.add_parser("run")
    for command in (authorize, run):
        command.add_argument("--repository", type=Path, default=Path.cwd())
        command.add_argument("--s50-config", type=Path, required=True)
        command.add_argument("--s100-config", type=Path, required=True)
    authorize.add_argument("--output", type=Path, required=True)
    run.add_argument("--authorization", type=Path, required=True)
    run.add_argument("--source-checkout", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    if args.command == "authorize":
        result = build_authorization(repository, args.s50_config.resolve(), args.s100_config.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"wrote W1-C authorization: {args.output}")
    else:
        result = execute(
            repository=repository, source_checkout=args.source_checkout.resolve(),
            s50_path=args.s50_config.resolve(), s100_path=args.s100_config.resolve(),
            authorization_path=args.authorization.resolve(), output_root=args.output_root.resolve(),
        )
        print(f"W1-C pilot: {result['recorded_run_count']}/40 recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
