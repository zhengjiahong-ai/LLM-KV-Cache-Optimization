#!/usr/bin/env python3
"""Build one exact Calibration run contract without initializing CUDA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_calibration_run_contract import (
    materialize_calibration_run_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    contract = materialize_calibration_run_contract(
        execution_manifest_path=arguments.execution_manifest.resolve(),
        run_id=arguments.run_id,
    )
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": contract["status"],
        "run_id": contract["run_id"],
        "run_contract_sha256": contract["run_contract_sha256"],
        "output": str(output),
        "gpu_initialized": False,
        "authorization_consumed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
