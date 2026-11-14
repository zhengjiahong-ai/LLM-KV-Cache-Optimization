"""Generate the read-only Phase 3 final gate evidence pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.profiling.phase3_final_gate_audit import audit_phase3_final_gates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-archive", required=True, type=Path)
    parser.add_argument("--g0-archive", required=True, type=Path)
    parser.add_argument("--cohort-seal", required=True, type=Path)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--prelaunch", required=True, type=Path)
    parser.add_argument("--algorithm-audit-directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    arguments = parser.parse_args()
    result = audit_phase3_final_gates(
        execution_archive=arguments.execution_archive.resolve(),
        g0_archive=arguments.g0_archive.resolve(),
        cohort_seal=arguments.cohort_seal.resolve(),
        authorization=arguments.authorization.resolve(),
        prelaunch=arguments.prelaunch.resolve(),
        algorithm_audit_directory=arguments.algorithm_audit_directory.resolve(),
        output_directory=arguments.output_directory.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
