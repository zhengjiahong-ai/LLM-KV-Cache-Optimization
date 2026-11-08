"""Run the minimal Phase 2 real-runtime observability check on native CUDA vLLM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from kvopt.workload.phase2_runner import run_phase2
from scripts.spikes.run_phase2_minimal_observability_metal import (
    build_observation_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs/phase2/cuda-observability-smoke-config.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "artifacts/phase2-cuda-observability-smoke",
    )
    parser.add_argument("--run-id")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    output = run_phase2(
        args.config.resolve(),
        output_root=args.output_root.resolve(),
        run_id=args.run_id,
    )
    report = build_observation_report(output)
    report_path = output / "observation-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(report_path)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
