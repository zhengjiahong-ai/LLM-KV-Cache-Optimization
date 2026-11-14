"""Bind M1's unified 270-run approval to the reviewed code and G0 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--g0-directory", type=Path, required=True)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--cohort-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repository = arguments.repository.resolve()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("authorization record requires a clean worktree")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    g0 = arguments.g0_directory.resolve()
    inputs = arguments.input_directory.resolve()
    paths = {
        "g0_freeze_manifest_sha256": g0 / "g0-freeze-manifest.json",
        "noise_plan_sha256": g0 / "noise-run-plan.json",
        "main_plan_sha256": g0 / "main-run-plan.json",
        "input_bundle_sha256": inputs / "manifest.json",
        "cohort_seal_sha256": arguments.cohort_seal.resolve(),
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    record = {
        "schema_version": "phase3.option_f_unified_execution_authorization.v1",
        "authorization_basis": "M1_SINGLE_WINDOW_270_RUN_UNIFIED_EXECUTION_APPROVED",
        "g0_accepted": True,
        "one_shot_270_run_pipeline_authorized": True,
        "noise_runs_authorized": 30,
        "main_runs_authorized": 240,
        "intermediate_manual_m1_review_required": False,
        "git_sha": git_sha,
        **{field: _sha256(path) for field, path in paths.items()},
    }
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("PHASE3_UNIFIED_270_AUTHORIZATION_RECORD: PREPARED")
    print("git_sha:", git_sha)
    print("authorization_sha256:", _sha256(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
