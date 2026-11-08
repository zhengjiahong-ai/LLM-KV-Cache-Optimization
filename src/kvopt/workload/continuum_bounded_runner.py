"""Execute the authorized 54-run bounded Native campaign in isolated processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .continuum_bounded_gate import AUTHORIZATION_SCHEMA, CODE_BINDINGS
from .phase2_runner import run_phase2


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_authorization(
    *, repository: Path, manifest_path: Path, authorization_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    repository = repository.resolve()
    manifest_path = manifest_path.resolve()
    manifest = _load(manifest_path)
    authorization = _load(authorization_path)
    if authorization.get("schema_version") != AUTHORIZATION_SCHEMA:
        raise ValueError("unsupported bounded authorization schema")
    if authorization.get("measured_campaign_authorized") is not True:
        raise ValueError("bounded campaign is not authorized")
    if authorization.get("manifest_sha256") != _sha(manifest_path):
        raise ValueError("authorization manifest binding mismatch")
    fidelity_path = Path(str(authorization.get("fidelity_report_path", "")))
    if not fidelity_path.is_file() or _sha(fidelity_path) != authorization.get(
        "fidelity_report_sha256"
    ):
        raise ValueError("integrated Native fidelity report binding mismatch")
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_sha != authorization.get("experiment_tooling_git_sha"):
        raise ValueError("runtime Git SHA does not match authorization")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("dirty worktree is not authorized")
    for relative in CODE_BINDINGS:
        if _sha(repository / relative) != authorization["code_sha256"].get(relative):
            raise ValueError(f"authorized code binding mismatch: {relative}")
    root = manifest_path.parent
    for row in manifest["runs"]:
        config_path = root / row["config"]
        trace_path = root / row["trace"]
        if _sha(config_path) != row["config_sha256"]:
            raise ValueError(f"config changed after authorization: {row['run_id']}")
        if _sha(trace_path) != row["trace_sha256"]:
            raise ValueError(f"trace changed after authorization: {row['run_id']}")
    if _sha(Path(manifest["profile_path"])) != authorization.get("profile_sha256"):
        raise ValueError("measured profile changed after authorization")
    if _sha(Path(manifest["resource_record_path"])) != authorization.get(
        "resource_record_sha256"
    ):
        raise ValueError("resource record changed after authorization")
    return manifest, authorization


def run_one(
    *, repository: Path, manifest_path: Path, authorization_path: Path,
    output_root: Path, run_id: str,
) -> Path:
    manifest, _ = verify_authorization(
        repository=repository,
        manifest_path=manifest_path,
        authorization_path=authorization_path,
    )
    rows = [row for row in manifest["runs"] if row["run_id"] == run_id]
    if len(rows) != 1:
        raise ValueError("run ID is not uniquely present in the manifest")
    config_path = manifest_path.resolve().parent / rows[0]["config"]
    return run_phase2(config_path, output_root=output_root, run_id=run_id)


def _run_isolated(
    *, repository: Path, manifest_path: Path, authorization_path: Path,
    output_root: Path, run_id: str,
) -> Path:
    environment = os.environ.copy()
    environment["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kvopt.workload.continuum_bounded_runner",
            "--repository",
            str(repository.resolve()),
            "--manifest",
            str(manifest_path.resolve()),
            "--authorization",
            str(authorization_path.resolve()),
            "--output-root",
            str(output_root.resolve()),
            "--run-id",
            run_id,
        ],
        check=False,
        env=environment,
    )
    output = output_root.resolve() / run_id
    run_path = output / "run.json"
    if not run_path.is_file():
        raise RuntimeError(
            f"isolated run exited {completed.returncode} without evidence: {run_id}"
        )
    status = _load(run_path).get("status")
    expected = 0 if status == "success" else 1
    if completed.returncode != expected:
        raise RuntimeError("isolated process exit status disagrees with run evidence")
    return output


def run_campaign(
    *, repository: Path, manifest_path: Path, authorization_path: Path,
    output_root: Path, budget_hours: float,
) -> list[Path]:
    if budget_hours <= 0:
        raise ValueError("budget_hours must be positive")
    manifest, _ = verify_authorization(
        repository=repository,
        manifest_path=manifest_path,
        authorization_path=authorization_path,
    )
    started = time.monotonic()
    outputs: list[Path] = []
    for row in manifest["runs"]:
        elapsed_hours = (time.monotonic() - started) / 3600.0
        if elapsed_hours >= budget_hours:
            raise RuntimeError("bounded campaign reached its wall-clock budget cap")
        output = _run_isolated(
            repository=repository,
            manifest_path=manifest_path,
            authorization_path=authorization_path,
            output_root=output_root,
            run_id=row["run_id"],
        )
        outputs.append(output)
        if _load(output / "run.json").get("status") != "success":
            break
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--budget-hours", type=float, default=30.0)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.run_id:
        output = run_one(
            repository=args.repository,
            manifest_path=args.manifest,
            authorization_path=args.authorization,
            output_root=args.output_root,
            run_id=args.run_id,
        )
        run = _load(output / "run.json")
        print(f"{run['status']}: {output}")
        return 0 if run["status"] == "success" else 1
    outputs = run_campaign(
        repository=args.repository,
        manifest_path=args.manifest,
        authorization_path=args.authorization,
        output_root=args.output_root,
        budget_hours=args.budget_hours,
    )
    failed = [
        path.name for path in outputs if _load(path / "run.json").get("status") != "success"
    ]
    print(f"completed {len(outputs)} bounded run attempt(s); failed={len(failed)}")
    return 1 if failed or len(outputs) != 54 else 0


if __name__ == "__main__":
    raise SystemExit(main())
