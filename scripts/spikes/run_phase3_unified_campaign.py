"""Run the authorized Phase 3 Option F Noise-to-Main 270-run pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from kvopt.workload.phase3_unified_campaign import (
    FrozenInputs,
    run_unified_campaign,
    validate_native_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--g0-directory", type=Path, required=True)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--cohort-seal", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    arguments = parser.parse_args()
    if arguments.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    environment = validate_native_environment()
    result = run_unified_campaign(
        inputs=FrozenInputs(
            repository=arguments.repository.resolve(),
            g0_directory=arguments.g0_directory.resolve(),
            input_directory=arguments.input_directory.resolve(),
            cohort_seal_path=arguments.cohort_seal.resolve(),
            authorization_path=arguments.authorization.resolve(),
        ),
        output_root=arguments.output_root.resolve(),
        timeout_seconds=arguments.timeout_seconds,
        environment_report=environment,
    )
    print("PHASE3_OPTION_F_UNIFIED_270_PIPELINE:", result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
