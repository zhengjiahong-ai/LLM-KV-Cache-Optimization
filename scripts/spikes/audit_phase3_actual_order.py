"""Audit Phase 3 E sensitivity against actual Native submission order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.profiling.phase3_actual_order_audit import audit_actual_order_archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-archive", required=True, type=Path)
    parser.add_argument("--cohort-seal", required=True, type=Path)
    parser.add_argument("--classification", required=True, type=Path)
    parser.add_argument("--evidence-directory", type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    arguments = parser.parse_args()
    result = audit_actual_order_archive(
        execution_archive=arguments.execution_archive.resolve(),
        cohort_seal=arguments.cohort_seal.resolve(),
        classification_path=arguments.classification.resolve(),
        output_directory=arguments.output_directory.resolve(),
        evidence_directory=(
            arguments.evidence_directory.resolve()
            if arguments.evidence_directory is not None
            else None
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
