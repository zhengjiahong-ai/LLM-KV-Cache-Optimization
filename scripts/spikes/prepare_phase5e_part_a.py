"""Prepare the final Phase 5E Part A package for M1 read-only confirmation."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kvopt.workload.phase5e_freeze import materialize_phase5e_freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
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
        raise RuntimeError("final Phase 5E freeze requires a clean worktree")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = materialize_phase5e_freeze(
        repository=repository,
        git_sha=git_sha,
        output_root=arguments.output_root,
    )
    print("PHASE5E_PART_A_FINAL_FREEZE: PASS")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
