"""Materialize the read-only Phase 5 session-turn sensitivity report."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kvopt.workload.phase5_turn_sensitivity import (
    build_analysis,
    load_phase5_swe_sessions,
    write_outputs,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repository = args.repository.resolve()
    rows, metadata = load_phase5_swe_sessions(
        repository=repository,
        processed_root=repository / "artifacts/phase5-swe-acquisition-processed-v1",
        adapted_root=repository / "artifacts/phase5-swe-acquisition-adapted-v2/records",
        attempt_ledger_path=(
            repository
            / "artifacts/phase5-swe-acquisition-reconciliation-v1/attempt-reconciliation.json"
        ),
    )
    analysis = build_analysis(rows=rows, acquisition_metadata=metadata)
    base_git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hashes = write_outputs(
        repository=repository,
        output_root=args.output_root,
        rows=rows,
        analysis=analysis,
        base_git_sha=base_git_sha,
    )
    print("PHASE5_SESSION_TURN_SENSITIVITY: COMPLETE")
    print(json.dumps(analysis["observed_distribution"], indent=2, sort_keys=True))
    print(json.dumps(analysis["recommendation"], indent=2, sort_keys=True))
    for name, digest in sorted(hashes.items()):
        print(digest, args.output_root / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
